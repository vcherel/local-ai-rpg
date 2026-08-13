from __future__ import annotations

import math
import random
import threading
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.daynight import DayNightCycle
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from core.screen_fx import get_hitstop
from game.entities.boss import Boss
from game.entities.breakables import Breakable, generate_breakables
from game.entities.buildings import Building, set_active_buildings
from game.entities.critter import Critter, pick_critter_kind
from game.entities.items import AMMO_BUNDLE, Item, rarity_color, rarity_tier
from game.entities.monsters import Monster, pick_monster_kind
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest, pois_for_chunk
from game.entities.projectile import Projectile
from game.entities.village import Village, generate_starting_world, generate_village, village_site
from game.events import EventSystem
from game.loot import break_crate, open_poi_cache, roll_shop_stock
from llm.llm_request_queue import generate_response_queued, generate_response_stream_queued

# What a camper calls each kind of landmark when giving directions.
_POI_HINT_LABELS = {"ruins": "old ruins", "camp": "somebody's camp", "shrine": "a forgotten shrine"}


def _compass_direction(dx: float, dy: float) -> str:
    """The bearing from one point to another, in the words a person would use."""
    names = ("east", "south east", "south", "south west", "west", "north west", "north", "north east")
    index = round(math.atan2(dy, dx) / (math.pi / 4)) % 8
    return names[index]


if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World:
    def __init__(self, save_system: SaveSystem, context_window: ContextMenu, notify, show_rumor):
        # Regenerated on the fly as the player explores; see _sync_chunks.
        self.floor_details = []
        self._loaded_chunks = set()
        self._current_chunk = None

        self.items: List[Item] = []
        self.npcs: List[NPC] = []
        self.monsters: List[Monster] = []
        # Named, multi-phase bosses. Kept apart from monsters: they never despawn, don't
        # count toward the monster cap, and get their own update, health bar and rewards.
        self.bosses: List[Boss] = []
        self.buildings: List[Building] = []
        # Buildings (and village wells) bucketed by chunk, so a collision test looks at the
        # handful standing near a point instead of everything in every village ever found.
        self._buildings_by_chunk: dict = {}
        self._wells_by_chunk: dict = {}
        self.breakables: List[Breakable] = []
        # Every village generated so far. Unlike POIs these are kept, not regenerated: a
        # settlement's NPCs carry affinity, quests and shop stock that a chunk seed can't
        # rebuild. `village_site` still decides where they go, so the map itself is endless.
        self.villages: List[Village] = []
        # Only the POIs of the chunks currently loaded around the player; see _load_chunk.
        self.pois: List[PointOfInterest] = []
        # What the player did to a POI (looted, discovered, camper spawned), by POI id.
        # Everything else about a POI comes back from its chunk seed, so this is all that
        # needs saving.
        self.poi_state: dict = {}
        # Grid cells the player has walked through (Fog.CELL wide), the memory the minimap
        # draws. Persisted; everything outside it stays black.
        self.explored: set = set()
        self._last_reveal_cell = None
        # Camps whose bandits are already posted this session, so walking in and out of a
        # camp's chunk doesn't stack up guards around it.
        self._guarded_camps: set = set()
        # Wandering wildlife, purely atmospheric; transient like particles, never saved.
        self.critters: List[Critter] = []
        # Arrows in flight; transient like particles, never saved.
        self.projectiles: List[Projectile] = []
        self.respawn_timer = 0.0
        self.critter_respawn_timer = 0.0
        self.boss_roam_timer = 0.0

        self.save_system = save_system
        self.context_window = context_window
        self.notify = notify
        self.context = self.save_system.load("context", None)
        self.events = EventSystem(self, notify, show_rumor)
        self.daynight = DayNightCycle(self.save_system.load("daynight_elapsed_ms", 0.0))

        # Generation guards: a merchant with no shop yet, an unnamed landmark or an unnamed
        # village would otherwise be picked up again by every path that checks, queueing a
        # duplicate call while the first one is still in flight.
        self._shops_generating = False
        self._landmark_naming = False
        self._naming_villages: set = set()

        # Set by close() when the player leaves the game. Background generation threads
        # outlive the session (an LLM call can still be queued behind others), and the
        # save file is shared with whatever game is started next; without this they would
        # write a dead world's state over the new game's save.
        self.closed = False

        saved_pois = self.save_system.load("pois", {})
        # Saves written before the world became endless hold a plain list of POIs placed
        # inside the old fixed box; those positions mean nothing now, so they're dropped.
        self.poi_state = saved_pois if isinstance(saved_pois, dict) else {}
        self.explored = {
            tuple(int(part) for part in key.split(":")) for key in self.save_system.load("explored", []) if ":" in key
        }

        saved_npcs = self.save_system.load("npcs", None)
        if saved_npcs is not None:
            self._restore(saved_npcs)
            # Fills in quests saved before boss names were tracked, and quests whose boss
            # was still unnamed when the game was last closed.
            self.sync_quest_boss_names()
            if self.context:
                self.start_shop_generation()
        else:
            village, buildings = generate_starting_world()
            self.villages = [village]
            self.buildings = buildings
            self._index_buildings()
            set_active_buildings(self.buildings)
            self.breakables = generate_breakables(self.buildings)
            self._populate_npcs(self.buildings)
            self.monsters = [
                self._new_monster(*self._random_coords_away_from_spawn()) for _ in range(c.World.NB_MONSTERS)
            ]
            self._spawn_landmark_boss()
        self._index_buildings()
        set_active_buildings(self.buildings)

        if self.context is None:
            self.context_window.start_streaming()
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            self.context_window.show(self.context)
            self._start_landmark_naming()
            self._start_village_naming()

    def _populate_npcs(self, buildings: List[Building]):
        """Fill one village with people: a merchant standing at each shop, and a villager or
        two living at every house and tavern. Called for the starting town and again for each
        village the player finds, so a settlement is never an empty film set."""
        for shop in (b for b in buildings if b.kind == "shop"):
            npc = NPC(*shop.door_front())
            npc.is_merchant = True
            npc.color = c.Colors.MERCHANT
            self.npcs.append(npc)

        for home in (b for b in buildings if b.kind in ("house", "tavern")):
            door_x, door_y = home.door_front()
            for _ in range(random.randint(*c.Villages.VILLAGERS_PER_HOME)):
                npc = NPC(door_x + random.randint(-80, 80), door_y + random.randint(0, 80))
                npc.home = (door_x, door_y)
                self.npcs.append(npc)

    def _random_coords_away_from_spawn(self) -> tuple[int, int]:
        center = c.World.WORLD_SIZE // 2
        min_dist = c.World.INITIAL_SPAWN_MIN_DISTANCE
        for _ in range(20):
            x, y = random.randint(0, c.World.WORLD_SIZE), random.randint(0, c.World.WORLD_SIZE)
            if math.hypot(x - center, y - center) >= min_dist and not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                return x, y
        # Nothing clear in 20 tries: settle for the last roll rather than looping forever.
        # A monster standing in a wall beats hanging world generation.
        return x, y

    def _populate_camp(self, poi: PointOfInterest):
        """Put a camp's occupants on the ground the first time its chunk loads.

        A bandit camp gets a ring of guards and a leader rolling its kind as if it stood
        deeper into the wilds, so the cache behind them is worth the fight; they are posted
        once per session, since monsters are saved and would otherwise pile up. A traveller
        camp gets its camper, who is a permanent NPC like any villager and so is spawned
        once for the whole save (`npc_spawned`)."""
        if poi.kind != "camp":
            return
        if poi.variant == "traveller":
            self._spawn_camper(poi)
            return
        if poi.looted or poi.id in self._guarded_camps:
            return
        self._guarded_camps.add(poi.id)

        spread = c.PointsOfInterest.CAMP_GUARD_SPREAD
        count = random.randint(c.PointsOfInterest.CAMP_GUARD_MIN, c.PointsOfInterest.CAMP_GUARD_MAX)
        for i in range(count + 1):
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(spread * 0.5, spread)
            x = poi.x + math.cos(angle) * distance
            y = poi.y + math.sin(angle) * distance
            leader = i == count
            self.monsters.append(
                self._new_monster(x, y, danger_bonus=c.PointsOfInterest.CAMP_LEADER_DANGER_BONUS if leader else 0)
            )

    def _spawn_camper(self, poi: PointOfInterest):
        """The trader living at a traveller camp: a merchant like any other, but stocked
        from the local loot tables rather than the LLM, since a lone camper in the wilds
        shouldn't hold the queue up behind a shop generation call."""
        if poi.npc_spawned:
            return
        poi.npc_spawned = True
        npc = NPC(poi.x + 62, poi.y + 60)
        npc.is_merchant = True
        npc.color = c.Colors.MERCHANT
        npc.home = (npc.x, npc.y)
        npc.set_shop(roll_shop_stock(c.PointsOfInterest.CAMPER_STOCK_SIZE))
        self.npcs.append(npc)

    def camp_is_clear(self, poi: PointOfInterest) -> bool:
        """True when nothing hostile is left standing near a camp's fire.

        This is the whole gate on a bandit camp's cache and on resting at either camp:
        checking the ground rather than tracking which monsters were spawned as guards
        means despawns, reloads and wandering monsters can't leave a camp locked shut."""
        return not any(
            entity.distance_to_point((poi.x, poi.y)) < c.PointsOfInterest.CAMP_CLEAR_RADIUS
            for entity in self.monsters + self.bosses
        )

    def camp_in_reach(self, player: Player) -> PointOfInterest | None:
        """The campfire the player could rest at right now: near enough, still burning, and
        with nothing hostile around it."""
        pos = player.get_pos()
        camps = [
            poi
            for poi in self.pois
            if poi.has_fire
            and poi.distance_to_point(pos) < c.PointsOfInterest.REST_DISTANCE
            and self.camp_is_clear(poi)
        ]
        return min(camps, key=lambda poi: poi.distance_to_point(pos), default=None)

    def rest_at_camp(self, player: Player, poi: PointOfInterest):
        """Sit at a camp's fire: back to full health, and the post-death weakness shaken off.
        Free, and it can't be done with anything hostile nearby, which is what stops it
        being a heal button in the middle of a fight."""
        player.heal(player.max_hp)
        player.clear_death_debuff()
        play_sound("rest")
        get_particles().spawn_burst(poi.x + 40, poi.y + 12, (255, 170, 60), count=18, speed=3, life=700, size=4)
        if self.notify:
            self.notify("You rest at the fire. Wounds closed, nerves steadied.", (255, 190, 110))

    def _new_monster(self, x, y, danger_bonus: int = 0) -> Monster:
        """Tougher kinds unlock farther from the world center, so wandering out gets more
        dangerous. `danger_bonus` rolls the kind as if this spot were that much farther out,
        which is how a camp leader outclasses the guards around it."""
        center = c.World.WORLD_SIZE // 2
        distance_from_center = math.hypot(x - center, y - center) + danger_bonus
        return Monster(x, y, pick_monster_kind(distance_from_center))

    def _restore(self, saved_npcs: list):
        """Rebuild items, NPCs, monsters and buildings from a saved game, relinking quest items by id."""
        self.buildings = [Building.from_dict(d) for d in self.save_system.load("buildings", [])]
        self.villages = [Village.from_dict(d) for d in self.save_system.load("villages", [])]
        self.breakables = [Breakable.from_dict(d) for d in self.save_system.load("breakables", [])]
        self.items = [Item.from_dict(d) for d in self.save_system.load("items", [])]
        items_by_id = {item.id: item for item in self.items}
        self.npcs = [NPC.from_dict(d, items_by_id) for d in saved_npcs]
        self.monsters = [Monster.from_dict(d) for d in self.save_system.load("monsters", [])]
        self.bosses = [Boss.from_dict(d) for d in self.save_system.load("bosses", [])]

    def close(self):
        """Leave the session: background threads still in flight stop writing to the save."""
        self.closed = True
        self.notify = None

    def persist_world(self):
        """Flush generated world state to disk. Called by the background generation threads
        so finished work (context, shops, boss and landmark names) survives a restart
        instead of being regenerated on the next continue."""
        if self.closed:
            return
        try:
            state = self.serialize()
        except RuntimeError:
            # A list mutated on the main thread mid-serialisation; skip this write, the
            # periodic autosave and the next completion will catch it.
            return
        for key, value in state.items():
            self.save_system.update(key, value)
        self.save_system.update("context", self.context)
        self.save_system.save_all()

    def _poi_state_snapshot(self) -> dict:
        """Everything the player has changed about a POI, loaded chunks included: the rest
        of a POI is regenerated from its chunk seed and never needs saving."""
        snapshot = dict(self.poi_state)
        for poi in self.pois:
            if poi.touched:
                snapshot[poi.id] = poi.state()
        return snapshot

    def serialize(self) -> dict:
        # A wandering merchant is a transient event; drop it rather than saving it as permanent.
        npcs = [npc for npc in self.npcs if npc is not self.events.wandering_merchant]
        return {
            "items": [item.to_dict() for item in self.items],
            "npcs": [npc.to_dict() for npc in npcs],
            "monsters": [monster.to_dict() for monster in self.monsters],
            "bosses": [boss.to_dict() for boss in self.bosses],
            "buildings": [building.to_dict() for building in self.buildings],
            "villages": [village.to_dict() for village in self.villages],
            "breakables": [breakable.to_dict() for breakable in self.breakables],
            "pois": self._poi_state_snapshot(),
            "explored": [f"{gx}:{gy}" for gx, gy in sorted(self.explored)],
            "daynight_elapsed_ms": self.daynight.elapsed_ms,
        }

    # ------------------------------------------------------------------ building lookups

    def _index_buildings(self):
        """Bucket every building (and every village well) by the chunks it reaches, so a
        collision test only looks at what stands near the point. The world gains a village
        every time the player finds one, and scanning the whole list per monster step per
        frame would get slower the more of the world they had seen."""
        self._buildings_by_chunk = {}
        self._wells_by_chunk = {}
        size = c.World.CHUNK_SIZE
        pad = c.World.BUILDING_INDEX_PAD

        def bucket(index: dict, rect: pygame.Rect, value):
            # Padded by the biggest radius any caller tests with, so something just over a
            # chunk border is still found from the chunk next door.
            area = rect.inflate(pad * 2, pad * 2)
            for cx in range(area.left // size, area.right // size + 1):
                for cy in range(area.top // size, area.bottom // size + 1):
                    index.setdefault((cx, cy), []).append(value)

        for building in self.buildings:
            bucket(self._buildings_by_chunk, building.rect, building)
        for village in self.villages:
            well = pygame.Rect(0, 0, c.Villages.WELL_RADIUS * 2, c.Villages.WELL_RADIUS * 2)
            well.center = (round(village.x), round(village.y))
            bucket(self._wells_by_chunk, well, village)

    def _register_buildings(self, buildings: List[Building]):
        """Add a newly generated village's buildings to the world and the lookup index."""
        self.buildings.extend(buildings)
        self._index_buildings()
        set_active_buildings(self.buildings)

    def buildings_near(self, x, y) -> List[Building]:
        """The buildings whose footprint can reach (x, y)."""
        return self._buildings_by_chunk.get(self._chunk_of(x, y), [])

    def buildings_in_range(self, x, y, radius) -> List[Building]:
        """Every building in the chunks covering the box of `radius` around (x, y). For
        callers working over an area (a swing's reach, a detour, the map) rather than a point."""
        size = c.World.CHUNK_SIZE
        found = {}
        for cx in range(int((x - radius) // size), int((x + radius) // size) + 1):
            for cy in range(int((y - radius) // size), int((y + radius) // size) + 1):
                for building in self._buildings_by_chunk.get((cx, cy), ()):
                    found[building.id] = building
        return list(found.values())

    def buildings_around(self, x, y) -> List[Building]:
        """The buildings of the chunk block around (x, y), the usual local query."""
        return self.buildings_in_range(x, y, c.World.CHUNK_SIZE)

    def blocked(self, x, y, radius) -> bool:
        if any(village.blocks(x, y, radius) for village in self._wells_by_chunk.get(self._chunk_of(x, y), ())):
            return True
        return any(building.blocks(x, y, radius) for building in self.buildings_near(x, y))

    def building_at(self, x, y) -> Building | None:
        """The building whose floor (x, y) stands on, or None. Buildings are kept far enough
        apart that at most one can contain a given point."""
        for building in self.buildings_near(x, y):
            if building.contains_point(x, y):
                return building
        return None

    def chase_waypoint(self, monster: Monster, player: Player):
        """Where a chasing monster should head next, or None to walk straight at the player.

        Buildings are the only obstacles and each has a single door, so a chase across a wall
        never needs a real pathfinder: aim for the door of whichever building separates the
        two, and walk round any other building standing in the way rather than into it.
        """
        monster_building = self.building_at(monster.x, monster.y)
        player_building = self.building_at(player.x, player.y)
        start = (monster.x, monster.y)
        radius = monster.kind.size / 2

        if monster_building is player_building:
            if monster_building is not None:
                # Same room: nothing between them but furniture, which steering handles.
                return None
            # Both outdoors: straight at the player, round anything standing in the way.
            goal = (player.x, player.y)
        elif monster_building is not None:
            # Indoors with the player elsewhere: out through the door first, and no detour
            # around the building the monster is standing in.
            return self._door_goal(monster_building, monster, radius, leaving=True)
        else:
            goal = self._door_goal(player_building, monster, radius, leaving=False)

        return self._detour_corner(start, goal, radius) or goal

    @staticmethod
    def _door_goal(building: Building, monster: Monster, radius: float, leaving: bool):
        """The point to walk to next to get through `building`'s door, in or out. A monster
        lines up with the doorway from the outside first, then steps across the threshold,
        so it goes through the gap instead of shouldering the wall next to it."""
        door_front = building.door_front()
        inside = (building.x, building.interior_rect().bottom - 20)
        fits = radius < c.Buildings.DOOR_WIDTH / 2 - 4
        aligned = abs(monster.x - building.x) < c.Buildings.DOOR_WIDTH / 2 - radius
        if leaving:
            return door_front if aligned else inside
        # Too broad for the doorway (the stone colossus): it waits on the doorstep rather
        # than shoving itself into a wall it can never pass. Still round the far side of the
        # building, and the door is on the front: only step in from the front half.
        if not fits or not aligned or monster.y < building.rect.centery:
            return door_front
        return inside

    def _detour_corner(self, start, goal, radius: float):
        """The corner to head for when a building sits between `start` and `goal`, or None
        when the way is clear.

        The way past a rectangle runs through at most two of its corners, so both ways round
        are costed in full and the first corner of the shorter one is returned. Costing the
        whole detour, rather than just picking the nearest corner, is what stops a monster
        oscillating between the near corner behind it and the far corner it should round.
        """
        for building in self.buildings_around(*start):
            margin = radius + 8
            rect = building.rect.inflate(margin * 2, margin * 2)
            # A goal inside the shell is that building's own doorway; walking round the
            # building would be walking away from the door.
            if rect.collidepoint(goal):
                continue
            # Tested against a hair-smaller rect so a leg running along an edge, corner to
            # corner, doesn't count as cutting through the building.
            inner = rect.inflate(-2, -2)
            if not inner.clipline(start, goal):
                continue

            corners = [rect.topleft, rect.topright, rect.bottomright, rect.bottomleft]
            best = None
            for i, first in enumerate(corners):
                if inner.clipline(start, first):
                    continue
                for last in (first, corners[(i + 1) % 4], corners[(i - 1) % 4]):
                    if last is not first and inner.clipline(first, last):
                        continue
                    if inner.clipline(last, goal):
                        continue
                    cost = math.dist(start, first) + math.dist(first, last) + math.dist(last, goal)
                    if best is None or cost < best[0]:
                        # Aim at the next corner along once this one is effectively reached.
                        target = first if math.dist(start, first) > radius + 6 else last
                        best = (cost, target)
            if best is not None:
                return best[1]
        return None

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
        for poi in self.pois:
            if self._chunk_of(poi.x, poi.y) == chunk and poi.touched:
                self.poi_state[poi.id] = poi.state()
        self.pois = [p for p in self.pois if self._chunk_of(p.x, p.y) != chunk]
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

    # ------------------------------------------------------------------ bosses

    def spawn_boss(self, x, y, template: c.BossKind = None, quest_tag: str = None, announce: str = None) -> Boss:
        """Create a boss, register it, and kick off LLM naming. `announce`, if given, is a
        message template shown once the name is ready (use '{name}' for the boss's name)."""
        boss = Boss(x, y, template or random.choice(c.BOSS_KINDS), quest_tag=quest_tag)
        self.bosses.append(boss)
        if self.context:
            threading.Thread(target=self._generate_boss_identity, args=(boss, announce), daemon=True).start()
        return boss

    def _spawn_landmark_boss(self):
        """A guardian waits at the ruined landmark from the very first world. It's named
        later, once the world context has finished generating."""
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None:
            return
        self.spawn_boss(landmark.x, landmark.y + landmark.h / 2 + 90)

    def spawn_boss_for_quest(self) -> Boss:
        """Spawn a boss out in the dangerous outer ring as a quest hunt target."""
        center = c.World.WORLD_SIZE // 2
        for _ in range(20):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_MIN_DISTANCE, c.World.WORLD_SIZE // 2)
            x = center + math.cos(angle) * dist
            y = center + math.sin(angle) * dist
            if (
                0 <= x <= c.World.WORLD_SIZE
                and 0 <= y <= c.World.WORLD_SIZE
                and not self.blocked(x, y, c.MONSTER_MAX_SIZE)
            ):
                break
        tag = f"quest_boss_{random.randint(1000, 9999)}"
        return self.spawn_boss(x, y, quest_tag=tag)

    def _generate_boss_identity(self, boss: Boss, announce: str = None):
        system_prompt = (
            "You name bosses for a dark fantasy RPG. Reply with only the name, optionally as "
            "'Name, the Epithet'. No quotes, no other text."
        )
        prompt = f"World: {self.context}\nName {boss.template.flavor}. 2 to 5 words."
        text = generate_response_queued(prompt, system_prompt, "Boss naming") or ""
        boss.set_identity(text)
        self.sync_quest_boss_names()
        self.persist_world()
        if announce and self.notify:
            self.notify(announce.format(name=boss.name), c.Colors.BOSS_BAR)

    def sync_quest_boss_names(self):
        """Copy each boss's display name onto the slay_boss quest hunting it.

        The quest links to its boss by `target_monster_kind` holding the internal spawn
        tag ("quest_boss_1234"), which is never fit to show; naming happens later on a
        background thread, so the quest picks the real name up from here.
        """
        by_tag = {boss.quest_tag: boss for boss in self.bosses if boss.quest_tag}
        for npc in self.npcs:
            quest = npc.quest
            if quest is None or quest.quest_type != "slay_boss":
                continue
            boss = by_tag.get(quest.target_monster_kind)
            if boss is not None:
                quest.boss_name = boss.display_name

    def _maybe_spawn_roaming_boss(self, player: Player):
        if len(self.bosses) >= c.Boss.MAX_ACTIVE:
            return
        center = c.World.WORLD_SIZE // 2
        if math.hypot(player.x - center, player.y - center) < c.Boss.ROAM_MIN_DISTANCE:
            return
        if random.random() > c.Boss.ROAM_CHANCE:
            return
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_SPAWN_MIN_DIST, c.Boss.ROAM_SPAWN_MAX_DIST)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE):
                self.spawn_boss(x, y, announce="A roaming terror, {name}, prowls the wilds")
                return

    def start_shop_generation(self):
        """Stock every merchant still waiting for one, in a single background call."""
        merchants = [npc for npc in self.npcs if npc.is_merchant and not npc.shop_ready]
        if not merchants or not self.context or self._shops_generating:
            return
        self._shops_generating = True
        threading.Thread(target=self._generate_merchant_shops, args=(merchants,), daemon=True).start()

    def _generate_merchant_shops(self, merchants: list):
        from llm.merchant_system import generate_shop_inventories

        try:
            stocks = generate_shop_inventories(self.context, len(merchants))
            for merchant, stock in zip(merchants, stocks):
                merchant.set_shop(stock + self._shop_staples())
        finally:
            self._shops_generating = False
        self.persist_world()
        # A merchant that showed up mid-batch (the wandering merchant event) was skipped
        # by the guard, so give it its own pass now that this one is done.
        self.start_shop_generation()

    @staticmethod
    def _shop_staples() -> list:
        """Stocked in every shop regardless of what the LLM comes up with, so ranged combat
        doesn't depend entirely on loot RNG for its ammo, nor healing on finding a flask."""
        return [
            {"name": "Arrows", "item_type": "ammo", "rarity": "common", "price": 30, "quantity": AMMO_BUNDLE}
            for _ in range(2)
        ] + [{"name": "Healing Potion", "item_type": "potion", "rarity": "common", "price": 18} for _ in range(2)]

    def quest_target(self, quest, player: Player):
        """Where the tracked quest points right now, as (x, y), or None when it has no fixed
        place to go (killing any wolf, looting a drop). Once the objective is in hand it
        points back at the NPC waiting for it.
        """
        if quest is None:
            return None

        giver = next((npc for npc in self.npcs if npc.quest is quest), None)
        ready_to_hand_in = (quest.item is not None and quest.item in player.inventory) or (
            quest.quest_type == "kill_mob" and quest.kills_done >= quest.kill_count
        )
        if ready_to_hand_in:
            return (giver.x, giver.y) if giver else None

        if quest.quest_type == "fetch" and quest.item is not None and not quest.item.picked_up:
            return (quest.item.x, quest.item.y)
        if quest.quest_type == "slay_boss":
            boss = next((b for b in self.bosses if b.quest_tag == quest.target_monster_kind), None)
            return (boss.x, boss.y) if boss else None
        if quest.quest_type == "recover_stolen":
            thief = next((npc for npc in self.npcs if npc.name == quest.thief_npc_name), None)
            return (thief.x, thief.y) if thief else None
        return None

    def npc_in_reach(self, player: Player) -> NPC | None:
        """The NPC the player is close enough to interact with, nearest first. Shared by the
        on-screen prompt, the talk key and the trade key so they can't disagree."""
        pos = player.get_pos(c.Player.INTERACTION_DISTANCE)
        reach = c.Player.INTERACTION_DISTANCE + c.Entities.NPC_SIZE // 2
        in_reach = [npc for npc in self.npcs if npc.distance_to_point(pos) < reach]
        return min(in_reach, key=lambda npc: npc.distance_to_point(pos), default=None)

    def handle_attack(self, player: Player, quest_system: QuestSystem, ranged: bool = False):
        """The weapon's archetype (constants.weapon_archetype) drives reach, damage, cadence,
        crit, knockback and cleave, so different weapon families feel different to swing.
        Building interiors are just world space now, so this has no indoor/outdoor split:
        monsters, NPCs, crates and windows are all found the same way whether the player is
        standing in a house or out in the open.

        `ranged` selects the ranged weapon slot (right click) instead of the melee one (left
        click), so a bow/staff and a melee weapon can be carried and used independently."""
        blocked = self.blocked

        if ranged:
            weapon = player.equipped_item("ranged_weapon")
            if weapon is None:
                return
            self._fire_ranged(player, self.projectiles, c.weapon_archetype(weapon.name))
            return

        weapon = player.equipped_item("melee_weapon")
        arch = c.weapon_archetype(weapon.name if weapon else None)

        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:  # still on cooldown from the previous swing
            return
        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult

        player.start_attack_anim("right")
        play_sound("attack")

        reach = c.Player.ATTACK_REACH * arch.reach_mult
        pos = player.get_pos(reach)
        origin = player.get_pos()
        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus() + player.stats.attack_bonus()
        ) * player.damage_multiplier()
        hit_radius = reach * (arch.cleave_radius_mult if arch.cleave else 1.0)

        def in_reach(entities, size_of):
            return self._targets_in_reach(
                entities, pos, hit_radius, size_of, arch.cleave, origin, arch.min_hit_distance
            )

        if self.bosses:
            boss_targets = in_reach(self.bosses, lambda b: b.kind.size)
            if boss_targets:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
                for boss in boss_targets:
                    self._strike_monster(boss, self.bosses, base_damage, arch, player, quest_system, blocked)
                return

        monster_targets = in_reach(self.monsters, lambda m: m.kind.size)
        if monster_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for monster in monster_targets:
                self._strike_monster(monster, self.monsters, base_damage, arch, player, quest_system, blocked)
            return

        # Wildlife is struck before villagers, so hunting a rabbit in a crowd doesn't start
        # a brawl, and after monsters, so a fox never soaks a swing meant for a wolf.
        critter_targets = in_reach(self.critters, lambda cr: cr.size)
        if critter_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for critter in critter_targets:
                self._strike_critter(critter, base_damage, arch, player)
            return

        npc_targets = in_reach(self.npcs, lambda n: c.Entities.NPC_SIZE)
        if npc_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for npc in npc_targets:
                self._strike_npc(npc, base_damage, arch, player, quest_system, blocked)
            return

        # A swing that reaches a shop/tavern crate smashes it instead.
        for building in self.buildings_around(*pos):
            crate = building.break_crate_at(pos, hit_radius)
            if crate is not None:
                self._break_crate(player, building, crate)
                return

        # A swing that reaches an unlooted wilderness ruins pile or camp cache smashes it.
        poi_hit = next(
            (
                p
                for p in self.pois
                if p.has_loot and not p.looted and p.distance_to_point(pos) < hit_radius + c.PointsOfInterest.HIT_RADIUS
            ),
            None,
        )
        if poi_hit is not None:
            self._break_poi(player, poi_hit)
            return

        # Nothing living in range: a swing that reaches a barrel/pot/bush smashes it instead.
        breakable = next(
            (b for b in self.breakables if b.distance_to_point(pos) < hit_radius + c.Breakables.HIT_RADIUS), None
        )
        if breakable is not None:
            self._break_breakable(player, breakable)
            return

        window_hit = self._find_window_in_reach(pos, hit_radius)
        if window_hit is not None:
            building, idx, window = window_hit
            self._break_window(building, idx, window)

    @staticmethod
    def _targets_in_reach(
        entities, pos, hit_radius, size_of, cleave: bool, origin=None, min_distance: float = 0.0
    ) -> list:
        """Entities within a swing's reach: every one in range if the weapon cleaves,
        otherwise just the nearest.

        `min_distance` is the weapon's blind spot measured from `origin` (the player's own
        position): a spear covers a ring, not a disc, so anything pressed up against the
        player is past the point of the shaft and takes nothing."""
        targets = [e for e in entities if e.distance_to_point(pos) < hit_radius + size_of(e) // 2]
        if min_distance and origin is not None:
            targets = [e for e in targets if e.distance_to_point(origin) >= min_distance]
        if not targets or cleave:
            return targets
        return [min(targets, key=lambda e: e.distance_to_point(pos))]

    def _find_window_in_reach(self, pos, hit_radius):
        """Nearest unbroken window (on any non-landmark building) a swing reaches, as
        (building, index, rect), or None."""
        px, py = pos
        best = None
        for building in self.buildings_around(px, py):
            for idx, window in enumerate(building.window_rects()):
                if idx in building.broken_windows:
                    continue
                dist = math.hypot(px - window.centerx, py - window.centery)
                if dist < hit_radius + c.Buildings.WINDOW_HIT_RADIUS and (best is None or dist < best[0]):
                    best = (dist, building, idx, window)
        return None if best is None else (best[1], best[2], best[3])

    def _break_window(self, building: Building, idx: int, window):
        """Shatter a window: no loot, just a satisfying crash."""
        building.broken_windows.add(idx)
        get_shake().add(c.Combat.WINDOW_SHAKE)
        play_sound("glass_break")
        get_particles().spawn_burst(
            window.centerx,
            window.centery,
            (210, 230, 240),
            count=16,
            speed=6,
            life=500,
            size=3,
            gravity=0.5,
            shape="shard",
        )

    def _fire_ranged(self, player: Player, proj_list: List[Projectile], arch: c.WeaponArchetype):
        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:
            return
        if arch.uses_ammo:
            # Ammo stacks per rarity, so shoot the cheapest quiver first: rarity only
            # changes what a stack sells for, and nobody wants to fire legendary arrows
            # at slimes while common ones sit in the bag.
            ammo = min(
                (item for item in player.inventory if item.item_type == "ammo"),
                key=lambda item: rarity_tier(item.rarity).price_mult,
                default=None,
            )
            if ammo is None:
                return
            ammo.quantity -= 1
            if ammo.quantity <= 0:
                player.inventory.remove(ammo)

        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult
        player.start_attack_anim("left")
        play_sound("shoot")

        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus(ranged=True) + player.stats.attack_bonus()
        ) * player.damage_multiplier()
        # A shot can crit too (weapon + affix chance), boosting damage and the hit's shake.
        # Rampage forces every Nth shot to crit and amplifies it further.
        rampage = player.rampage_trigger(ranged=True)
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus(ranged=True), rampage=rampage)
        crit_shake = c.Combat.CRIT_SHAKE_BONUS if crit else 0.0
        rampage_shake = c.Combat.CRIT_SHAKE_BONUS if rampage else 0.0
        shake = arch.shake + crit_shake + rampage_shake
        if arch.name == "staff":
            proj = Projectile(
                player.x,
                player.y,
                player.orientation,
                damage,
                style="bolt",
                color=(150, 90, 230),
                knockback=arch.knockback,
                shake=shake,
            )
        else:
            proj = Projectile(
                player.x,
                player.y,
                player.orientation,
                damage,
                knockback=arch.knockback,
                shake=shake,
            )
        proj.pierce = player.pierce_count()
        proj_list.append(proj)

    def _roll_hit(
        self, base_damage: float, arch: c.WeaponArchetype, crit_bonus: float = 0.0, rampage: bool = False
    ) -> tuple[int, bool]:
        """Apply the weapon's damage multiplier and roll for a crit (weapon + affix chance).
        Rampage forces the crit and amplifies it further on top."""
        damage = base_damage * arch.damage_mult
        crit = rampage or random.random() < arch.crit_chance + crit_bonus
        if crit:
            damage *= c.Combat.CRIT_MULT
        if rampage:
            damage *= c.Affixes.RAMPAGE_BONUS_MULT
        return max(1, int(round(damage))), crit

    @staticmethod
    def _dir_from(x0, y0, x1, y1):
        """Unit vector from (x0,y0) toward (x1,y1), or None if they coincide."""
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist == 0:
            return None
        return (dx / dist, dy / dist)

    @staticmethod
    def _knockback(target, radius, kb_dir, distance, blocked):
        """Shove a target along kb_dir, sliding along walls one axis at a time."""
        if not kb_dir or distance <= 0:
            return
        step_x, step_y = kb_dir[0] * distance, kb_dir[1] * distance
        if blocked is not None and blocked(target.x + step_x, target.y, radius):
            step_x = 0
        target.x += step_x
        if blocked is not None and blocked(target.x, target.y + step_y, radius):
            step_y = 0
        target.y += step_y

    def _strike_monster(self, monster, monster_list, base_damage, arch, player, quest_system, blocked):
        rampage = player.rampage_trigger(ranged=False)
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus(), rampage=rampage)
        crit_shake = c.Combat.CRIT_SHAKE_BONUS if crit else 0.0
        rampage_shake = c.Combat.CRIT_SHAKE_BONUS if rampage else 0.0
        shake = arch.shake + crit_shake + rampage_shake
        kb_dir = self._dir_from(player.x, player.y, monster.x, monster.y)
        died = self._resolve_monster_hit(
            monster,
            monster_list,
            damage,
            player,
            quest_system,
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=kb_dir,
            blocked=blocked,
        )
        self._apply_on_hit_effects(monster, monster_list, damage, player, quest_system, died)
        self._apply_chainstrike(monster, monster_list, damage, player, quest_system, blocked, ranged=False)

    def _strike_npc(self, npc, base_damage, arch, player, quest_system, blocked):
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus())
        # Lifesteal works on any struck target, NPCs included.
        frac = player.lifesteal_frac()
        if frac > 0:
            player.heal(damage * frac)
        shake = arch.shake + (c.Combat.CRIT_SHAKE_BONUS if crit else 0.0)
        kb_dir = self._dir_from(player.x, player.y, npc.x, npc.y)
        self._resolve_npc_hit(
            npc,
            damage,
            quest_system,
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=kb_dir,
            blocked=blocked,
        )

    def _strike_critter(self, critter: Critter, base_damage, arch, player: Player):
        """Wildlife takes hits like anything else, but never fights back: a survivor just
        bolts. No quest system involvement, no loot table, nothing to burn or chain into."""
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus())
        get_shake().add(arch.shake + (c.Combat.CRIT_SHAKE_BONUS if crit else 0.0))
        self._pop_damage(critter.x, critter.y - critter.size / 2, damage, crit)
        kb_dir = self._dir_from(player.x, player.y, critter.x, critter.y)
        if critter.receive_damage(damage):
            self._kill_critter(critter, player, kb_dir)
            return
        self._hit_feedback(critter.x, critter.y, crit, kb_dir)
        self._knockback(critter, critter.size / 2, kb_dir, arch.knockback, self.blocked)
        critter.startle()

    def _kill_critter(self, critter: Critter, player: Player, direction=None):
        """A hunted animal leaves a pelt worth selling, and nothing else: critters are
        session-only, so the drop is the only trace of it that reaches the save."""
        play_sound("monster_death")
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        self._spill_blood(critter.x, critter.y, c.Wildlife.COLORS[critter.kind], direction)
        player.stats.train("vitality", c.Stats.XP_PER_KILL * 0.5)
        if random.random() < c.Wildlife.DROP_CHANCE[critter.kind]:
            drop = Item(critter.x, critter.y, c.Wildlife.DROP_NAMES[critter.kind], "misc", rarity="common")
            drop.start_pop_anim(critter.x, critter.y - critter.size)
            self.items.append(drop)
        self.critters.remove(critter)

    @staticmethod
    def _break_effects(x, y, color, count):
        """Shared shake, crash sound and shard burst for a smashed crate/cache/barrel."""
        get_shake().add(c.Combat.CRATE_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(x, y, color, count=count, speed=6, life=550, size=5, gravity=0.4, shape="shard")

    def _break_loot(self, player: Player, x, y, coins, loot_item, label: str, place_item):
        """Credit coins, pop any dropped item out near (x, y) via `place_item`, and toast the result."""
        player.gain_coins(coins)
        message = f"{label}: +{coins} coins"
        color = c.Colors.WHITE
        if loot_item is not None:
            loot_item.x = x + random.uniform(-20, 20)
            loot_item.y = y + random.uniform(-20, 20)
            loot_item.start_pop_anim(x, y)
            place_item(loot_item)
            message += f", and a {loot_item.rarity} {loot_item.name} dropped"
            color = rarity_color(loot_item.rarity)
        if self.notify:
            self.notify(message, color)

    def _break_crate(self, player: Player, building: Building, crate):
        """Smash a shop or tavern crate: juice, a few coins, and a small chance of a dropped item.

        The crate has already been removed from the interior's collision set by
        break_crate_at; here we handle the feedback and the loot. Coins are credited
        straight away; an item (if any) pops out onto the floor for the player to walk
        over and collect, rather than jumping straight into the inventory.
        """
        self._break_effects(crate.centerx, crate.centery, (150, 110, 70), 20)
        coins, loot_item = break_crate()
        self._break_loot(
            player, crate.centerx, crate.centery, coins, loot_item, "Crate smashed", building.dropped_items.append
        )

    def _break_poi(self, player: Player, poi: PointOfInterest):
        """Smash a wilderness ruins pile or bandit camp cache: same feedback as an outdoor
        barrel, better odds and rarity since it took more effort to find. Left in place
        afterwards (not removed like a breakable) so the ruin/camp still reads as a landmark,
        just picked over.

        A bandit camp's cache stays shut while its owners are still on their feet: the loot
        is the reward for clearing the camp, not for running past it."""
        if poi.kind == "camp" and not self.camp_is_clear(poi):
            if self.notify:
                self.notify("The camp is still guarded", c.Colors.MUTED)
            return
        poi.looted = True
        self._break_effects(poi.x, poi.y, (150, 140, 120), 20)
        coins, loot_item = open_poi_cache()
        label = "Camp cache" if poi.kind == "camp" else "Ruins searched"
        self._break_loot(player, poi.x, poi.y, coins, loot_item, label, self.items.append)

    def _break_breakable(self, player: Player, breakable: Breakable):
        """Smash an outdoor prop. A barrel plays out like a shop crate: juice, coins,
        and a small chance of a dropped item landing straight in the open world. A
        pot or bush is pure decoration: a satisfying puff and nothing else, so the
        world has more to smash without inflating the loot economy. Either way the
        prop is gone for good, no debris left behind."""
        self.breakables.remove(breakable)

        if not breakable.loot:
            get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
            if breakable.kind == "pot":
                play_sound("crate_break")
                get_particles().spawn_burst(
                    breakable.x,
                    breakable.y,
                    (170, 100, 60),
                    count=10,
                    speed=5,
                    life=400,
                    size=3,
                    gravity=0.4,
                    shape="shard",
                )
            else:  # bush
                play_sound("bush_rustle")
                get_particles().spawn_burst(
                    breakable.x, breakable.y, (80, 150, 65), count=14, speed=4, life=450, size=4, gravity=0.3
                )
            return

        self._break_effects(breakable.x, breakable.y, (150, 110, 70), 18)
        coins, loot_item = break_crate()
        self._break_loot(player, breakable.x, breakable.y, coins, loot_item, "Barrel smashed", self.items.append)

    def _resolve_monster_hit(
        self,
        monster: Monster,
        monster_list: List[Monster],
        damage: int,
        player: Player,
        quest_system: QuestSystem,
        crit: bool = False,
        shake: float = 0.0,
        knockback: float = 0.0,
        kb_dir=None,
        blocked=None,
    ) -> bool:
        """Applies damage to a monster and its kill rewards. Returns True if it died."""
        get_shake().add(shake)
        self._pop_damage(monster.x, monster.y - monster.kind.size / 2, damage, crit)
        if monster.receive_damage(damage):
            self._kill_monster(monster, monster_list, player, quest_system, direction=kb_dir)
            return True
        self._hit_feedback(monster.x, monster.y, crit, kb_dir)
        if not getattr(monster, "knockback_immune", False):
            self._knockback(monster, monster.kind.size / 2, kb_dir, knockback, blocked)
        return False

    @staticmethod
    def _spill_blood(x, y, body_color, direction=None, boss: bool = False):
        """The gore of a kill: a pool where it dropped, a fan of droplets thrown along the
        killing blow, and a spray still in the air over both.

        `direction` is the blow's (dx, dy) unit vector, so the mess points away from the
        player instead of ringing the corpse. A kill with no direction (a burn tick, an
        execute) bursts outward instead."""
        decals = get_decals()
        decals.spawn(x, y, radius=c.Decals.BOSS_KILL_RADIUS if boss else c.Decals.KILL_RADIUS)
        decals.spawn_spray(
            x,
            y,
            direction,
            count=c.Decals.BOSS_SPRAY_COUNT if boss else c.Decals.KILL_SPRAY_COUNT,
            distance=c.Decals.BOSS_SPRAY_DISTANCE if boss else c.Decals.KILL_SPRAY_DISTANCE,
            radius=c.Decals.BOSS_SPRAY_RADIUS if boss else c.Decals.KILL_SPRAY_RADIUS,
        )

        blood = (178, 26, 26)
        count = 34 if boss else 22
        speed = 12 if boss else 9
        size = 6 if boss else 5
        if direction:
            get_particles().spawn_directional_burst(
                x,
                y,
                math.atan2(direction[1], direction[0]),
                spread_deg=c.Decals.SPRAY_SPREAD_DEG,
                color=blood,
                count=count,
                speed=speed,
                life=700,
                size=size,
                gravity=0.32,
            )
        else:
            get_particles().spawn_burst(x, y, blood, count=count, speed=speed, life=700, size=size, gravity=0.32)
        # Chunks of the thing itself, so a slime still bleeds green over the red.
        get_particles().spawn_burst(x, y, body_color, count=16 if boss else 12, speed=6, life=550, size=5, gravity=0.42)

    def _kill_monster(self, monster, monster_list, player: Player, quest_system: QuestSystem, direction=None):
        """Death rewards and cleanup for a slain monster, shared by hits and burn ticks."""
        player.stats.train("vitality", c.Stats.XP_PER_KILL)
        play_sound("monster_death")
        # Bloodlust: any kill with a weapon carrying it refreshes the damage buff.
        bloodlust = player.bloodlust_mult()
        if bloodlust > 1.0:
            player.apply_buff("bloodlust", bloodlust, c.Affixes.BLOODLUST_DURATION_S)
        if isinstance(monster, Boss):
            self._on_boss_killed(monster, quest_system, direction)
            monster_list.remove(monster)
            return
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        self._spill_blood(monster.x, monster.y, monster.kind.color, direction)
        quest_item = quest_system.on_monster_killed(monster.kind.name, monster.x, monster.y)
        if quest_item is not None:
            self.items.append(quest_item)
        drop_chance = c.LootBox.DROP_CHANCE
        if self.events.blood_night_active:
            drop_chance *= c.Events.BLOOD_NIGHT_DROP_MULT
        if random.random() < drop_chance:
            self.items.append(Item(monster.x, monster.y, "Lootbox", "lootbox"))
        monster_list.remove(monster)

    def _apply_on_hit_effects(self, monster, monster_list, damage, player, quest_system, died, ranged: bool = False):
        """Weapon lifesteal/burn/execute after a hit lands. `died` is the hit's own result."""
        frac = player.lifesteal_frac(ranged)
        if frac > 0 and damage > 0:
            player.heal(damage * frac)
            get_particles().spawn_burst(player.x, player.y, c.Colors.GREEN, count=5, speed=3, life=300, size=3)
        if died:
            return
        burn = player.burn_damage(ranged)
        if burn > 0:
            monster.apply_burn(burn)
        # Execute finishes off a badly wounded non-boss outright.
        thr = player.execute_threshold(ranged)
        if thr > 0 and not isinstance(monster, Boss) and 0 < monster.hp <= monster.max_hp * thr:
            get_particles().spawn_burst(monster.x, monster.y, (255, 60, 60), count=10, speed=5, life=400, size=4)
            if monster.receive_damage(monster.hp):
                self._kill_monster(monster, monster_list, player, quest_system)

    def _apply_chainstrike(self, primary, target_list, damage, player, quest_system, blocked, ranged: bool = False):
        """Chain Strike: a landed hit also strikes the nearest other target in the same
        list within range, for a fraction of the primary hit's damage."""
        frac = player.chainstrike_frac(ranged)
        if frac <= 0:
            return
        chain_target = min(
            (
                m
                for m in target_list
                if m is not primary and m.distance_to_point((primary.x, primary.y)) < c.Affixes.CHAINSTRIKE_RADIUS
            ),
            key=lambda m: m.distance_to_point((primary.x, primary.y)),
            default=None,
        )
        if chain_target is None:
            return
        chain_damage = max(1, int(damage * frac))
        get_particles().spawn_burst(chain_target.x, chain_target.y, (140, 200, 255), count=8, speed=4, life=300, size=3)
        kb_dir = self._dir_from(primary.x, primary.y, chain_target.x, chain_target.y)
        died = self._resolve_monster_hit(
            chain_target,
            target_list,
            chain_damage,
            player,
            quest_system,
            shake=0.0,
            knockback=0.0,
            kb_dir=kb_dir,
            blocked=blocked,
        )
        self._apply_on_hit_effects(chain_target, target_list, chain_damage, player, quest_system, died, ranged=ranged)

    def _on_boss_killed(self, boss: Boss, quest_system: QuestSystem, direction=None):
        """A boss dies with extra spectacle and a guaranteed legendary lootbox."""
        get_hitstop().trigger(c.Combat.HITSTOP_BOSS_MS)
        self._spill_blood(boss.x, boss.y, boss.template.color, direction, boss=True)
        get_particles().spawn_burst(boss.x, boss.y, boss.template.aura, count=40, speed=10, life=800, size=7)
        get_shake().add(c.Boss.SLAM_SHAKE)
        quest_system.on_boss_killed(boss)
        reward = Item(boss.x, boss.y, "Lootbox", "lootbox")
        reward.rarity = c.Boss.REWARD_RARITY
        self.items.append(reward)
        if self.notify:
            self.notify(f"{boss.name} has been slain!", c.Colors.BOSS_BAR_ENRAGED)

    def _resolve_npc_hit(
        self,
        npc: NPC,
        damage: int,
        quest_system: QuestSystem,
        crit: bool = False,
        shake: float = 0.0,
        knockback: float = 0.0,
        kb_dir=None,
        blocked=None,
    ) -> bool:
        """Applies damage to an NPC and handles death. Returns True if it died."""
        get_shake().add(shake)
        self._pop_damage(npc.x, npc.y - c.Entities.NPC_SIZE / 2, damage, crit)
        if npc.receive_damage(damage):
            stolen_item = quest_system.on_npc_killed(npc)
            if stolen_item is not None:
                self.items.append(stolen_item)
            # Drop any quest this NPC was offering so it can't become uncompletable
            quest_system.remove_quest(npc)
            play_sound("monster_death")
            get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
            self._spill_blood(npc.x, npc.y, npc.color, kb_dir)
            self.npcs.remove(npc)
            return True
        self._hit_feedback(npc.x, npc.y, crit, kb_dir)
        self._knockback(npc, c.Entities.NPC_SIZE / 2, kb_dir, knockback, blocked)
        return False

    @staticmethod
    def _hit_feedback(x, y, crit: bool, direction=None):
        """Sound + particle burst for a non-fatal hit; crits read brighter and louder.
        `direction` (attacker -> target unit vector), if given, sprays the particles as a
        cone away from the hit instead of a plain omnidirectional poof."""
        play_sound("crit" if crit else "hit")
        if crit:
            get_hitstop().trigger(c.Combat.HITSTOP_CRIT_MS)
        get_decals().spawn(x, y, radius=c.Decals.HIT_RADIUS)
        color = (255, 240, 160) if crit else (255, 180, 180)
        count = 12 if crit else 6
        speed = 4 if crit else 3
        life = 350 if crit else 300
        size = 4 if crit else 3
        if direction:
            angle = math.atan2(direction[1], direction[0])
            get_particles().spawn_directional_burst(
                x, y, angle, spread_deg=80.0, color=color, count=count, speed=speed, life=life, size=size, gravity=0.35
            )
        else:
            get_particles().spawn_burst(x, y, color, count=count, speed=speed, life=life, size=size)

    @staticmethod
    def _pop_damage(x, y, damage: int, crit: bool):
        """Floating damage number over a hit; crits pop bigger and gold."""
        text = f"{damage}!" if crit else str(damage)
        color = (255, 210, 90) if crit else c.Colors.WHITE
        get_floating_text().spawn(x, y, text, color, big=crit)

    def update_projectiles(self, player: Player, quest_system: QuestSystem, dt):
        for proj in list(self.projectiles):
            proj.update(dt, self.blocked)
            if proj.dead:
                self.projectiles.remove(proj)
                continue

            # A boss's bolts fly past monsters and NPCs and only threaten the player.
            if proj.hostile:
                if proj.distance_to_point((player.x, player.y)) < c.Projectile.SIZE + c.Player.SIZE / 2:
                    player.receive_damage(proj.damage)
                    get_shake().add(proj.shake)
                    self.projectiles.remove(proj)
                continue

            if self._projectile_hits_monster(proj, self.monsters, player, quest_system):
                continue
            if self._projectile_hits_monster(proj, self.bosses, player, quest_system):
                continue
            if self._projectile_hits_critter(proj, player):
                continue
            self._projectile_hits_npc(proj, player, quest_system)

    def _projectile_hits_monster(self, proj: Projectile, targets, player: Player, quest_system: QuestSystem) -> bool:
        """Resolve a projectile against one list of monsters or bosses (both take hits the
        same way). Returns True if it struck something, pierced onward or not."""
        target = next(
            (
                t
                for t in targets
                if id(t) not in proj.hit_ids
                and proj.distance_to_point((t.x, t.y)) < c.Projectile.SIZE + t.kind.size // 2
            ),
            None,
        )
        if target is None:
            return False

        player.stats.train("strength", c.Stats.XP_PER_HIT)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        died = self._resolve_monster_hit(
            target,
            targets,
            proj.damage,
            player,
            quest_system,
            shake=proj.shake,
            knockback=proj.knockback,
            kb_dir=kb_dir,
            blocked=self.blocked,
        )
        self._apply_on_hit_effects(target, targets, proj.damage, player, quest_system, died, ranged=True)
        self._apply_chainstrike(target, targets, proj.damage, player, quest_system, self.blocked, ranged=True)
        self._projectile_after_hit(proj, self.projectiles, target)
        return True

    def _projectile_hits_critter(self, proj: Projectile, player: Player) -> bool:
        """Resolve a projectile against wildlife: an arrow is how most animals get hunted,
        since they run long before a swing lands. Returns True if it struck one."""
        critter = next(
            (
                cr
                for cr in self.critters
                if id(cr) not in proj.hit_ids
                and proj.distance_to_point((cr.x, cr.y)) < c.Projectile.SIZE + cr.size // 2
            ),
            None,
        )
        if critter is None:
            return False

        player.stats.train("strength", c.Stats.XP_PER_HIT)
        get_shake().add(proj.shake)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        self._pop_damage(critter.x, critter.y - critter.size / 2, proj.damage, False)
        if critter.receive_damage(proj.damage):
            self._kill_critter(critter, player, kb_dir)
        else:
            self._hit_feedback(critter.x, critter.y, False, kb_dir)
            self._knockback(critter, critter.size / 2, kb_dir, proj.knockback, self.blocked)
            critter.startle()
        self._projectile_after_hit(proj, self.projectiles, critter)
        return True

    def _projectile_hits_npc(self, proj: Projectile, player: Player, quest_system: QuestSystem):
        npc = next(
            (
                n
                for n in self.npcs
                if id(n) not in proj.hit_ids
                and proj.distance_to_point((n.x, n.y)) < c.Projectile.SIZE + c.Entities.NPC_SIZE // 2
            ),
            None,
        )
        if npc is None:
            return

        player.stats.train("strength", c.Stats.XP_PER_HIT)
        self._resolve_npc_hit(
            npc,
            proj.damage,
            quest_system,
            shake=proj.shake,
            knockback=proj.knockback,
            kb_dir=self._dir_from(0, 0, proj.vx, proj.vy),
            blocked=self.blocked,
        )
        frac = player.lifesteal_frac(ranged=True)
        if frac > 0:
            player.heal(proj.damage * frac)
        self._projectile_after_hit(proj, self.projectiles, npc)

    def _tick_burns(self, monster_list: List[Monster], player: Player, quest_system: QuestSystem):
        now = pygame.time.get_ticks()
        for monster in list(monster_list):
            if monster.burn_ticks_remaining <= 0 or now < monster.burn_next_ms:
                continue
            monster.burn_ticks_remaining -= 1
            monster.burn_next_ms = now + c.Affixes.BURN_INTERVAL_MS
            get_particles().spawn_burst(monster.x, monster.y, (255, 140, 40), count=4, speed=2, life=300, size=3)
            get_floating_text().spawn(
                monster.x, monster.y - monster.kind.size / 2, str(monster.burn_damage), (255, 150, 60)
            )
            if monster.receive_damage(monster.burn_damage):
                self._kill_monster(monster, monster_list, player, quest_system)

    @staticmethod
    def _projectile_after_hit(proj: Projectile, proj_list: List[Projectile], target):
        """Record the target and either pierce onward (arrow-pierce) or stop the projectile."""
        proj.hit_ids.add(id(target))
        if proj.pierce > 0:
            proj.pierce -= 1
        else:
            proj_list.remove(proj)

    def item_in_reach(self, player: Player) -> Item | None:
        """The loot the player can pick up right now, nearest first."""
        pos = player.get_pos()
        in_reach = [
            item for item in self.items if not item.picked_up and item.distance_to_point(pos) < c.Player.PICKUP_DISTANCE
        ]
        return min(in_reach, key=lambda item: item.distance_to_point(pos), default=None)

    def village_at(self, x, y) -> Village | None:
        """The village whose grounds (x, y) stands on, or None out in the wilds."""
        return next((village for village in self.villages if village.contains_point(x, y)), None)

    def _spawn_monster_away_from(self, player: Player):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.World.SPAWN_MIN_DISTANCE, c.World.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            # Monsters wander into settlements, but none of them starts life in one: a
            # village should read as the safe ground between stretches of wilderness.
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2) and self.village_at(x, y) is None:
                self.monsters.append(self._new_monster(x, y))
                return

    def _spawn_critter_away_from(self, player: Player):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Wildlife.SPAWN_MIN_DISTANCE, c.Wildlife.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.blocked(x, y, max(c.Wildlife.SIZES.values()) / 2):
                self.critters.append(Critter(x, y, pick_critter_kind()))
                return

    def _check_poi_discovery(self, player: Player):
        """The one-time line a landmark gives up the first time the player walks to it: a
        shrine's flavor, or a camper's directions to somewhere still unexplored."""
        pos = player.get_pos()
        for poi in self.pois:
            if poi.discovered or poi.distance_to_point(pos) >= c.PointsOfInterest.DISCOVER_DISTANCE:
                continue
            if poi.kind == "shrine":
                poi.discovered = True
                if self.notify:
                    self.notify(random.choice(c.PointsOfInterest.SHRINE_MESSAGES), c.Colors.WHITE)
            elif poi.variant == "traveller":
                poi.discovered = True
                if self.notify:
                    self.notify(self._traveller_directions(poi), (200, 190, 150))

    def _traveller_directions(self, poi: PointOfInterest) -> str:
        """What the camper at a traveller camp tells the player: where the nearest thing they
        have not walked to yet lies. Village sites and points of interest are both pure
        functions of their chunk, so this can point at places that have never been generated,
        which is exactly what makes it worth hearing."""
        best = None
        radius = c.PointsOfInterest.HINT_CHUNK_RADIUS
        cx, cy = self._chunk_of(poi.x, poi.y)
        for gx in range(cx - radius, cx + radius + 1):
            for gy in range(cy - radius, cy + radius + 1):
                candidates = [(site, "a settlement") for site in [village_site(gx, gy)] if site is not None]
                for other in pois_for_chunk(gx, gy, self.buildings):
                    candidates.append(((other.x, other.y), _POI_HINT_LABELS[other.kind]))
                for (x, y), label in candidates:
                    distance = math.hypot(x - poi.x, y - poi.y)
                    if distance < c.PointsOfInterest.HINT_MIN_DISTANCE or self.is_explored(x, y):
                        continue
                    if best is None or distance < best[0]:
                        best = (distance, x, y, label)

        if best is None:
            return "The camper has nothing left to point you towards."
        distance, x, y, label = best
        bearing = _compass_direction(x - poi.x, y - poi.y)
        reach = "not far" if distance < 1800 else ("a fair walk" if distance < 3200 else "a long way")
        return f"The camper points {bearing}: {label}, {reach} from here."

    def is_explored(self, x, y) -> bool:
        """True once the player has walked close enough to this spot for the map to remember it."""
        cell = c.Fog.CELL
        return (int(x // cell), int(y // cell)) in self.explored

    def _reveal_around(self, player: Player):
        """Remember the ground around the player. Only recomputed when they cross into a new
        cell, so the common case costs one comparison."""
        cell = c.Fog.CELL
        here = (int(player.x // cell), int(player.y // cell))
        if here == self._last_reveal_cell:
            return
        self._last_reveal_cell = here
        span = int(c.Fog.REVEAL_RADIUS // cell) + 1
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                gx, gy = here[0] + dx, here[1] + dy
                center = ((gx + 0.5) * cell, (gy + 0.5) * cell)
                if math.hypot(center[0] - player.x, center[1] - player.y) <= c.Fog.REVEAL_RADIUS:
                    self.explored.add((gx, gy))

    def update(self, player: Player, dt, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        # Particles/floating text/screen fx update once per frame in Game.run() instead of
        # here, so they keep animating even while a menu pauses the rest of this update.
        self._sync_chunks(player)
        self._reveal_around(player)
        self.daynight.update(dt)
        self.events.update(dt, player, quest_system, npc_name_generator)
        self._check_poi_discovery(player)
        self._check_village_discovery(player)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt).
        update_radius = c.World.DETECTION_RANGE + c.Player.SIZE
        for monster in self.monsters:
            if abs(monster.x - player.x) <= update_radius and abs(monster.y - player.y) <= update_radius:
                monster.move(player, dt, self.blocked, self.chase_waypoint(monster, player))

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        self.monsters = [m for m in self.monsters if m.distance_to_point(player.get_pos()) <= c.World.DESPAWN_DISTANCE]

        # Burn (weapon affix) ticks over time and can finish a wounded target off.
        self._tick_burns(self.monsters, player, quest_system)
        self._tick_burns(self.bosses, player, quest_system)

        # Bosses never despawn; they chase, cast and enrage on their own schedule.
        for boss in list(self.bosses):
            boss.update_boss(self, player, dt, quest_system)

        self.boss_roam_timer += dt
        if self.boss_roam_timer >= c.Boss.ROAM_CHECK_INTERVAL_MS:
            self.boss_roam_timer = 0.0
            self._maybe_spawn_roaming_boss(player)

        self.update_projectiles(player, quest_system, dt)

        for npc in self.npcs:
            npc.update(player, dt, self.blocked)

        for critter in self.critters:
            critter.update(player, dt, self.blocked)
        player_pos = player.get_pos()
        self.critters = [
            critter for critter in self.critters if critter.distance_to_point(player_pos) <= c.Wildlife.DESPAWN_DISTANCE
        ]
        if len(self.critters) < c.Wildlife.COUNT:
            self.critter_respawn_timer += dt
            if self.critter_respawn_timer >= c.Wildlife.RESPAWN_INTERVAL_MS:
                self.critter_respawn_timer = 0.0
                self._spawn_critter_away_from(player)

        if len(self.monsters) < c.World.NB_MONSTERS:
            self.respawn_timer += dt
            respawn_interval = c.World.RESPAWN_INTERVAL_MS
            if self.events.blood_night_active:
                respawn_interval /= c.Events.BLOOD_NIGHT_RESPAWN_MULT
            elif self.daynight.is_night:
                respawn_interval /= c.DayNight.NIGHT_RESPAWN_MULT
            if self.respawn_timer >= respawn_interval:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
