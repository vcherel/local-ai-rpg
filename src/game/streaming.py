from __future__ import annotations

import random
import threading
from typing import TYPE_CHECKING

import core.constants as c
from core.audio import play_sound
from core.utils import parse_world_context
from game.entities.breakables import generate_breakables
from game.entities.poi import pois_for_chunk
from game.entities.terrain import blocking_index, generate_chunk_scenery, water_index
from game.entities.traps import traps_for_chunk
from game.entities.village import generate_village, village_site
from llm.llm_request_queue import generate_response_queued, generate_response_stream_queued

if TYPE_CHECKING:
    from game.entities.buildings import Building
    from game.entities.player import Player
    from game.entities.village import Village
    from llm.name_generator import NPCNameGenerator


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
        self.floor_details[chunk] = [
            (cx * size + rng.uniform(0, size), cy * size + rng.uniform(0, size), rng.choice(["stone", "flower"]))
            for _ in range(c.World.DETAILS_PER_CHUNK)
        ]

        self._ensure_village(chunk)

        nearby = self.buildings_in_range((cx + 0.5) * size, (cy + 0.5) * size, size)
        chunk_pois = pois_for_chunk(cx, cy, nearby)
        for poi in chunk_pois:
            state = self.poi_state.get(poi.id)
            if state:
                poi.apply_state(state)
            self.pois.append(poi)
            self._populate_camp(poi)

        # The wilderness itself, laid down last so it can be kept off everything already
        # standing here: the settlement, its buildings and this chunk's landmark.
        center = ((cx + 0.5) * size, (cy + 0.5) * size)
        villages = [v for v in self.villages if v.distance_to_point(center) < v.grounds_radius + size * 2]
        chunk_scenery = generate_chunk_scenery(cx, cy, nearby, villages, chunk_pois)
        # A tree the player already cut down comes back as its own stump, and a boulder they
        # broke open as its own rubble. The chunk itself is still a pure function of its
        # seed: what the player did to it is the one thing laid over the top, by position in
        # the generated list, the same way a POI's state is laid over a regenerated POI.
        for index, item in enumerate(chunk_scenery):
            if not (item.choppable or item.smashable):
                continue
            item.key = f"{cx}:{cy}:{index}"
            if item.key in self.felled:
                item.fell()
                item.fell_start_ms = None
            elif item.key in self.smashed:
                item.smash()
        self.scenery.extend(chunk_scenery)

        # The hunters' traps, laid last: they need the wilderness this chunk just grew and
        # the settlement standing in it, so none of them ends up under a trunk, in the
        # water, or on somebody's wall where nothing could step on it.
        for trap in traps_for_chunk(cx, cy, nearby, chunk_scenery, villages):
            trap.sprung = self.trap_state.get(trap.id, False)
            self.traps.append(trap)

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
        village.plan_streets(buildings)
        self._clear_scenery_for(village, buildings)
        self.breakables.extend(generate_breakables(buildings))
        self._populate_npcs(buildings, village)
        self._post_guards(village)

    def _plan_streets(self):
        """Wear the lanes between the houses of every settlement the world holds.

        A village's streets are worked out from where its buildings ended up, so they come
        back with the buildings rather than being saved; a village generated during play is
        planned as it is built (`_ensure_village`), and this is for the starting town and
        for the ones loaded out of a save, both of which have to be on the map the roads are
        laid out from before their lanes can reach one."""
        for village in self.villages:
            if not village.streets:
                village.plan_streets([b for b in self.buildings if village.contains_point(b.x, b.y)])

    def _clear_scenery_for(self, village: Village, buildings: list[Building]):
        """Cut back the wilderness a new settlement has just been built in.

        A chunk keeps its own scenery clear of what already stands in it, but a village
        reaches into the chunks around it and those may have been generated first, so the
        trees that would end up in the middle of the street are taken out here instead.

        The tufts and the flowers go the same way, off the lanes and the plaza only: a
        settlement cuts the wood back off its whole grounds, but grass is what its grounds
        are made of, and only what is drawn as trodden earth has to lose it."""
        keep_out = village.grounds_radius + c.Scenery.CLEARANCE_VILLAGE
        footprints = [b.bounds.inflate(c.Scenery.CLEARANCE_BUILDING, c.Scenery.CLEARANCE_BUILDING) for b in buildings]
        kept = []
        for item in self.scenery:
            if item.blocking_radius and village.distance_to_point((item.x, item.y)) < keep_out:
                continue
            if any(rect.collidepoint(item.x, item.y) for rect in footprints):
                continue
            if item.kind in c.Scenery.DECOR_KINDS and village.street_at(item.x, item.y, c.Scenery.STREET_CLEARANCE):
                continue
            kept.append(item)
        self.scenery = kept

    def _unload_chunks(self, chunks: set):
        """Drop everything the given chunks brought with them, in one pass over each list.

        Taken as a set rather than one chunk at a time because they leave in groups: walking
        over a border pushes a whole edge of the keep square out of range at once, and doing
        it chunk by chunk rebuilt the scenery, the traps and the POIs once per chunk on the
        frame that could least afford it.
        """
        if not chunks:
            return
        for chunk in chunks:
            self.floor_details.pop(chunk, None)
        # Filtered on the chunk that generated it rather than the one it stands in: a copse
        # rolled at a chunk's edge spills over the border, and it leaves with its own chunk.
        self.scenery = [s for s in self.scenery if s.chunk not in chunks]
        # A trap is rebuilt from its chunk seed like everything else here; only the fact
        # that one has already shut is worth carrying away with it.
        self.traps = [t for t in self.traps if t.chunk not in chunks]
        dropped = set()
        for poi in self.pois:
            if self._chunk_of(poi.x, poi.y) not in chunks:
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
        self._loaded_chunks -= chunks

    def _sync_chunks(self, player: Player):
        """Keep the ground around the player in step with where they are: queue what has
        come into range, drop what has left it, and build a frame's worth of the queue.

        Crossing a border used to build the whole edge that came into range on that one
        frame, which is a village, its landmark, a wood and a band of traps in a single
        update, and it is felt every time. What is queued here is two chunks away in the
        direction of travel, so the frames after the crossing are ample time to build it.
        """
        chunk = self._chunk_of(player.x, player.y)
        if chunk != self._current_chunk:
            self._current_chunk = chunk
            cx, cy = chunk
            load_r = c.World.CHUNK_LOAD_RADIUS
            keep_r = c.World.CHUNK_KEEP_RADIUS
            pending = [
                (cx + dx, cy + dy)
                for dx in range(-load_r, load_r + 1)
                for dy in range(-load_r, load_r + 1)
                if (cx + dx, cy + dy) not in self._loaded_chunks
            ]
            # Nearest first: the ground the player is walking onto is built before the
            # corners of the square they may never turn towards.
            pending.sort(key=lambda ch: max(abs(ch[0] - cx), abs(ch[1] - cy)))
            self._pending_chunks = pending
            self._unload_chunks(
                {loaded for loaded in self._loaded_chunks if max(abs(loaded[0] - cx), abs(loaded[1] - cy)) > keep_r}
            )
        self._build_pending_chunks(player)

    def _build_pending_chunks(self, player: Player, budget: int | None = None):
        """Build up to `budget` queued chunks, plus any queued chunk near enough that the
        player could walk into it before the queue got there anyway."""
        if not self._pending_chunks:
            return
        cx, cy = self._current_chunk
        budget = c.World.CHUNK_LOADS_PER_FRAME if budget is None else budget
        built = 0
        while self._pending_chunks:
            candidate = self._pending_chunks[0]
            urgent = max(abs(candidate[0] - cx), abs(candidate[1] - cy)) <= c.World.CHUNK_URGENT_RADIUS
            if built >= budget and not urgent:
                break
            self._load_chunk(self._pending_chunks.pop(0))
            built += 1
        if not built:
            return
        self._reindex_scenery()
        # A trunk generated by the chunk the player just walked into can land on top of
        # them (nothing knows where they stand at generation time), so they step out to
        # the nearest clear ground rather than being stuck inside a tree. The same pass
        # everything else on legs goes through (`World.unstick`).
        self.unstick(player, player.size / 2)

    def prepare(self, player: Player):
        """Build the ground the player is about to open their eyes on, before they can move.

        Chunk streaming used to happen on the first frame after the opening lore was
        dismissed, which is the worst possible moment for it: the player takes control into a
        freeze while a ring of chunks generates its wilderness, its landmarks and its traps,
        and then watches trees pop in around them. The generation is the same work either
        way, so it is done here instead, while nothing is on screen but black.

        The whole ring at once, budget ignored: this is the one moment in the game with
        nothing on screen to stutter, and spreading it over frames here would only move the
        work back to the first frames the player can walk.
        """
        if self.underground is not None:
            return
        self._sync_chunks(player)
        self._build_pending_chunks(player, budget=len(self._pending_chunks))
        self._reveal_around(player)

    def _reindex_scenery(self):
        """Rebuild what the renderer and `World.blocked` read the wilderness through.

        Done once per chunk sync, not once per chunk: a sync loads several at a time. The
        drawing side is bucketed by chunk (and, on the ground, by kind, which is its draw
        order) because a wood holds thousands of pieces and only the few chunks on screen
        are worth walking every frame."""
        self._ground_by_chunk = {}
        self._props_by_chunk = {}
        for item in self.scenery:
            chunk = self._chunk_of(item.x, item.y)
            if item.ground:
                self._ground_by_chunk.setdefault(chunk, {}).setdefault(item.kind, []).append(item)
            else:
                self._props_by_chunk.setdefault(chunk, []).append(item)
        self._scenery_by_cell = blocking_index(self.scenery)
        self._water_by_cell = water_index(self.scenery)

    def _generate_context(self):
        system_prompt = (
            "You create worlds for an RPG. "
            "Each world must contain one original detail that can serve as a starting point for quests."
        )
        prompt = (
            "In a single very short sentence, describe an RPG world starting with 'The game takes place...' "
            "The sentence must contain one original detail that can serve as a starting point for adventures."
        )
        # Asked again if the first answer holds no lore. A quantized model now and then
        # replies with a title rather than the sentence, and the stream is cut at the line
        # break that follows it, so the whole answer is one stray word; a second roll is
        # cheaper than a playthrough whose world is "Warlock".
        for _ in range(c.World.CONTEXT_ATTEMPTS):
            streamed = ""
            for chunk in generate_response_stream_queued(prompt, system_prompt, "Context generation"):
                if chunk:
                    self.context_window.push_chunk(chunk)
                    streamed = chunk
            self.context = parse_world_context(streamed)
            if self.context:
                break
            # Take the unreadable answer back off the black before asking again.
            self.context_window.push_chunk("")

        self._lore_generated = self.context is not None
        # An answer with no lore in it leaves the screen empty rather than the word the
        # stream happened to be cut on. Nothing is shown and nothing is saved, so the next
        # session asks again; what the rest of the world quotes in its own prompts falls
        # back to a plain sentence, since a village with no name and a merchant with no
        # stock is a town the player cannot so much as talk to.
        self.context_window.finish_streaming(self.context or "")
        if not self._lore_generated:
            self.context = c.World.FALLBACK_CONTEXT

        self.persist_world()

        for boss in self.bosses:
            threading.Thread(target=self._generate_boss_identity, args=(boss, None), daemon=True).start()
        self._start_landmark_naming()

    def _prepare_settlements_near(self, player: Player, dt, npc_name_generator: NPCNameGenerator):
        """Ask the model for what a settlement the player is walking up to is about to need:
        its name, its merchants' stock, and a name in the buffer for whoever they talk to.

        All three used to be asked for the moment a village existed, and every one of them
        again on every load, so a world the player had wandered through cost a call per town
        and per shop for towns they never entered and shops they never opened. Nothing here
        is generated until a settlement is within `Villages.PREPARE_DISTANCE`, which is far
        enough out that the answers land before the player is in the street: the name is
        what the discovery toast waits on, and a merchant with no stock cannot be talked to
        at all.

        Looked for a few times a second rather than every frame: it walks the villages and
        the NPCs, and an answer is seconds away in any case.
        """
        if not self.context:
            return
        self._prepare_timer -= dt
        if self._prepare_timer > 0:
            return
        self._prepare_timer = c.Villages.PREPARE_INTERVAL_MS

        pos = player.get_pos()
        near = [v for v in self.villages if v.distance_to_point(pos) < c.Villages.PREPARE_DISTANCE]
        if not near:
            return

        for village in near:
            if village.name or village.chunk in self._naming_villages:
                continue
            self._naming_villages.add(village.chunk)
            threading.Thread(target=self._generate_village_name, args=(village,), daemon=True).start()

        # One batched call for the shops of every settlement in reach, the same call that
        # used to stock the whole world at once.
        self.start_shop_generation(
            [
                npc
                for npc in self.npcs
                if npc.is_merchant
                and not npc.shop_ready
                and any(village.contains_point(npc.x, npc.y) for village in near)
            ]
        )
        # And a name waiting for the first villager they speak to, which is the one thing
        # here the player would otherwise stand and wait for.
        npc_name_generator.start_generation()

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
