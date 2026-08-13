from __future__ import annotations

import random
import threading
from typing import TYPE_CHECKING

import core.constants as c
from core.audio import play_sound
from game.entities.breakables import generate_breakables
from game.entities.poi import pois_for_chunk
from game.entities.village import generate_village, village_site
from llm.llm_request_queue import generate_response_queued, generate_response_stream_queued

if TYPE_CHECKING:
    from game.entities.buildings import Building
    from game.entities.player import Player
    from game.entities.village import Village


class WorldStreaming:
    """How the endless map comes into being around the player: chunks of floor detail and
    landmarks generated from their coordinates and dropped again when left behind, the
    settlements those chunks hold, and the LLM naming that gives the world, its villages and
    its landmark their names.

    Mixed into `World`. A chunk is a pure function of (cx, cy) apart from `World.poi_state`,
    so it can be thrown away and rebuilt at will; a village is the deliberate exception,
    generated once and then kept in the save (see `_ensure_village`).
    """

    def _chunk_of(self, x, y) -> tuple[int, int]:
        size = c.World.CHUNK_SIZE
        return int(x // size), int(y // size)

    def _load_chunk(self, chunk: tuple[int, int]):
        """Deterministically generate a chunk's floor details and points of interest, so
        revisiting it looks the same and walking outward never runs out of things to find.
        A chunk that holds a village site builds the settlement too, the first time only."""
        cx, cy = chunk
        size = c.World.CHUNK_SIZE
        rng = random.Random(f"{cx},{cy}")
        for _ in range(c.World.DETAILS_PER_CHUNK):
            x = cx * size + rng.uniform(0, size)
            y = cy * size + rng.uniform(0, size)
            self.floor_details.append((x, y, rng.choice(["stone", "flower"])))

        self._ensure_village(chunk)

        nearby = self.buildings_around((cx + 0.5) * size, (cy + 0.5) * size)
        for poi in pois_for_chunk(cx, cy, nearby):
            state = self.poi_state.get(poi.id)
            if state:
                poi.apply_state(state)
            self.pois.append(poi)
            self._populate_camp(poi)

        self._loaded_chunks.add(chunk)

    def _ensure_village(self, chunk: tuple[int, int]):
        """Build the village this chunk holds, if it holds one and nobody has built it yet.

        This is the one piece of the world that is generated on the fly and then kept: the
        settlement's people carry names, affinity, quests and stock, so it goes into the save
        alongside the starting town rather than being rebuilt from the seed on every visit.
        """
        site = village_site(*chunk)
        if site is None or any(village.chunk == chunk for village in self.villages):
            return

        village, buildings = generate_village(site[0], site[1], chunk)
        self.villages.append(village)
        self._register_buildings(buildings)
        self.breakables.extend(generate_breakables(buildings))
        self._populate_npcs(buildings)
        # The new merchants need stock, and the settlement needs a name.
        self.start_shop_generation()
        self._start_village_naming()

    def _unload_chunk(self, chunk: tuple[int, int]):
        self.floor_details = [d for d in self.floor_details if self._chunk_of(d[0], d[1]) != chunk]
        dropped = set()
        for poi in self.pois:
            if self._chunk_of(poi.x, poi.y) != chunk:
                continue
            if poi.touched:
                self.poi_state[poi.id] = poi.state()
            dropped.add(poi.id)
        self.pois = [p for p in self.pois if p.id not in dropped]
        # A camp's guards belong to its chunk, not to the world: they leave with it and are
        # stood back up from the camp's own count when it loads again. Without this they
        # would be the one thing that accumulated forever as the player found more camps.
        if dropped:
            self.monsters = [m for m in self.monsters if m.camp_id not in dropped]
            self.critters = [cr for cr in self.critters if cr.camp_id not in dropped]
        self._loaded_chunks.discard(chunk)

    def _sync_chunks(self, player: Player):
        chunk = self._chunk_of(player.x, player.y)
        if chunk == self._current_chunk:
            return
        self._current_chunk = chunk
        cx, cy = chunk
        load_r = c.World.CHUNK_LOAD_RADIUS
        keep_r = c.World.CHUNK_KEEP_RADIUS
        for dx in range(-load_r, load_r + 1):
            for dy in range(-load_r, load_r + 1):
                candidate = (cx + dx, cy + dy)
                if candidate not in self._loaded_chunks:
                    self._load_chunk(candidate)
        for loaded in list(self._loaded_chunks):
            if max(abs(loaded[0] - cx), abs(loaded[1] - cy)) > keep_r:
                self._unload_chunk(loaded)

    def _generate_context(self):
        system_prompt = (
            "You create worlds for an RPG. "
            "Each world must contain one original detail that can serve as a starting point for quests."
        )
        prompt = (
            "In a single very short sentence, describe an RPG world starting with 'The game takes place...' "
            "The sentence must contain one original detail that can serve as a starting point for adventures."
        )
        for chunk in generate_response_stream_queued(prompt, system_prompt, "Context generation"):
            if chunk:
                self.context_window.push_chunk(chunk)
                self.context = chunk
        self.context_window.finish_streaming()

        self.persist_world()

        self._start_village_naming()
        self.start_shop_generation()
        for boss in self.bosses:
            threading.Thread(target=self._generate_boss_identity, args=(boss, None), daemon=True).start()
        self._start_landmark_naming()

    def _start_village_naming(self):
        """Name every village still waiting for one, one short call each. A village keeps its
        name for good, so this runs once per settlement in the life of a save."""
        if not self.context:
            return
        for village in self.villages:
            if village.name or village.chunk in self._naming_villages:
                continue
            self._naming_villages.add(village.chunk)
            threading.Thread(target=self._generate_village_name, args=(village,), daemon=True).start()

    def _generate_village_name(self, village: Village):
        system_prompt = "You name settlements for an RPG world. Reply with the name only, no quotes, no punctuation."
        prompt = (
            f"{self.context}\nGive a short name, 1 to 3 words, for a small {village.size} in the wilds of this world."
        )
        try:
            name = generate_response_queued(prompt, system_prompt, "Village naming") or ""
            name = name.strip().strip('"').strip(".")
            if name:
                village.name = " ".join(name.split()[:3])
                self.persist_world()
        finally:
            self._naming_villages.discard(village.chunk)

    def _check_village_discovery(self, player: Player):
        """Walking into a village for the first time announces it. Held back until the name
        has generated, so the toast never reads "You have found None"."""
        pos = player.get_pos()
        for village in self.villages:
            if village.discovered or not village.name:
                continue
            if village.distance_to_point(pos) < c.Villages.DISCOVER_DISTANCE:
                village.discovered = True
                play_sound("discover")
                if self.notify:
                    self.notify(f"You have found {village.name}", c.Colors.ACCENT)

    def _start_landmark_naming(self):
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None or landmark.name or self._landmark_naming:
            return
        self._landmark_naming = True
        threading.Thread(target=self._generate_landmark_name, args=(landmark,), daemon=True).start()

    def _generate_landmark_name(self, landmark: Building):
        system_prompt = "You name landmarks for an RPG world. Reply with the name only, no quotes, no punctuation."
        prompt = f"{self.context}\nGive a short name, 2 to 4 words, for the ancient ruined landmark of this world."
        try:
            name = generate_response_queued(prompt, system_prompt, "Landmark naming") or ""
            name = name.strip().strip('"').strip(".")
            if name:
                landmark.name = " ".join(name.split()[:5])
                self.persist_world()
        finally:
            self._landmark_naming = False
