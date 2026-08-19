from __future__ import annotations

import math
import random
import threading
import time
from collections import namedtuple
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.daynight import DayNightCycle
from game.combat import WorldCombat
from game.entities.boss import Boss
from game.entities.breakables import Breakable, generate_breakables
from game.entities.buildings import Building, set_active_buildings
from game.entities.critter import Critter, pick_critter_kind
from game.entities.items import AMMO_BUNDLE, Item
from game.entities.monsters import Monster, pick_monster_kind
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest
from game.entities.projectile import STONE_COLOR, Projectile
from game.entities.scenery import Scenery
from game.entities.traps import BearTrap
from game.entities.village import Village, generate_starting_world
from game.events import EventSystem
from game.loot import roll_shop_stock
from game.places import WorldPlaces
from game.streaming import WorldStreaming
from llm.llm_request_queue import generate_response_queued
from llm.merchant_system import generate_shop_inventories

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


# A bare coordinate to route towards. `chase_waypoint` only ever reads an x and a y off
# whoever is being chased, and a villager running for a door is chasing a spot on the floor.
_Point = namedtuple("_Point", "x y")


def _merge_rects(rects: List[pygame.Rect]) -> List[pygame.Rect]:
    """Fold overlapping rectangles into the shapes they actually make. A clump of trunks is
    one obstacle to walk round; treated as a dozen, a chaser routes round the first, finds
    the second in its way, and picks its way into the middle of the wood."""
    merged: List[pygame.Rect] = []
    for rect in rects:
        current = rect
        joined = True
        while joined:
            joined = False
            for other in list(merged):
                if current.colliderect(other):
                    merged.remove(other)
                    current = current.union(other)
                    joined = True
        merged.append(current)
    return merged


class World(WorldCombat, WorldStreaming, WorldPlaces):
    """The living world and everything standing in it.

    Three parts live in their own modules and are mixed in here: `WorldCombat`
    (game/combat.py) resolves every blow and its aftermath, `WorldStreaming`
    (game/streaming.py) generates the endless map around the player and names what it
    finds, and `WorldPlaces` (game/places.py) is what the player can do at a place once
    they reach it (camps, fires, shrines, directions, theft). All of them work on the
    entity lists this class owns; keeping them as one class is what lets `self.monsters`
    and friends stay the single source of truth, and what decides which file a new method
    belongs in is the job it does, not which object holds the data.
    """

    def __init__(self, save_system: SaveSystem, context_window: ContextMenu, notify):
        # Regenerated on the fly as the player explores; see _sync_chunks.
        self.floor_details = []
        # The wilderness: trees, rocks, grass, ponds and roads, streamed with the chunks
        # and never saved. Indexed by `_reindex_scenery` into what is drawn under the
        # entities, what is drawn with the props, and a fine grid of the solid ones for
        # `blocked`.
        self.scenery: List[Scenery] = []
        self._ground_by_chunk: dict = {}
        self._props_by_chunk: dict = {}
        self._scenery_by_cell: dict = {}
        self._water_by_cell: dict = {}
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
        # The solid parts of a village that are not buildings: its well, and the palisade
        # and towers of a walled town.
        self._village_solids_by_chunk: dict = {}
        self.breakables: List[Breakable] = []
        # Every village generated so far. Unlike POIs these are kept, not regenerated: a
        # settlement's NPCs carry affinity, quests and shop stock that a chunk seed can't
        # rebuild. `village_site` still decides where they go, so the map itself is endless.
        self.villages: List[Village] = []
        # Only the POIs of the chunks currently loaded around the player; see _load_chunk.
        self.pois: List[PointOfInterest] = []
        # The hunters' bear traps of those same chunks, streamed and dropped with them. The
        # one thing a player changes about a trap is springing it, so that is all that is
        # saved (`trap_state`, by trap id), exactly like a POI.
        self.traps: List[BearTrap] = []
        self.trap_state: dict = {}
        # The tunnel the player is standing in, or None on the surface. A tunnel is ordinary
        # world space a long way from anywhere (game/entities/tunnel.py); this is what tells
        # the world to stop streaming ground, stop spawning wildlife and stop drawing a sky
        # while the player is down there. `tunnels` caches the ones built so far and
        # `tunnel_state` is what each of them has left (garrison, hoard), persisted.
        self.underground = None
        self.tunnels: dict = {}
        self.tunnel_state: dict = {}
        # Where the player climbed down from, so the ladder puts them back at that well.
        self.surface_return = None
        # What the player did to a POI (looted, discovered, camper spawned), by POI id.
        # Everything else about a POI comes back from its chunk seed, so this is all that
        # needs saving.
        self.poi_state: dict = {}
        # Grid cells the player has walked through (Fog.CELL wide), the memory the minimap
        # draws. Persisted; everything outside it stays black.
        self.explored: set = set()
        self._last_reveal_cell = None
        # Wandering wildlife, purely atmospheric; transient like particles, never saved.
        self.critters: List[Critter] = []
        # Arrows in flight; transient like particles, never saved.
        self.projectiles: List[Projectile] = []
        # Places a rumour pointed at, drawn on the minimap until the player gets there.
        # Session-only: a rumour is a lead to follow now, not a pin to keep forever.
        self.rumor_marks: List[dict] = []
        self.respawn_timer = 0.0
        self.critter_respawn_timer = 0.0
        self.boss_roam_timer = 0.0

        self.save_system = save_system
        self.context_window = context_window
        self.notify = notify
        self.context = self.save_system.load("context", None)
        self.events = EventSystem(self, notify)
        self.daynight = DayNightCycle(self.save_system.load("daynight_elapsed_ms", 0.0))

        # Generation guards: a merchant with no shop yet, an unnamed landmark or an unnamed
        # village would otherwise be picked up again by every path that checks, queueing a
        # duplicate call while the first one is still in flight.
        self._shops_generating = False
        self._landmark_naming = False
        self._naming_villages: set = set()

        # Throttles persist_world: several generation threads finishing at once would
        # otherwise each serialise the entire world back to disk.
        self._persist_lock = threading.Lock()
        self._last_persist = 0.0

        # Set by close() when the player leaves the game. Background generation threads
        # outlive the session (an LLM call can still be queued behind others), and the
        # save file is shared with whatever game is started next; without this they would
        # write a dead world's state over the new game's save.
        self.closed = False

        # When each place the player rests will serve them again, by POI id for a campfire
        # and by building id for a villager's bed (wall-clock seconds, so quitting to the
        # menu can't reset a fire or a bed the player just used). One that has come round
        # again is dropped rather than loaded.
        self.rest_cooldowns = {
            key: until for key, until in self.save_system.load("camp_rest", {}).items() if until > time.time()
        }

        self.poi_state = self.save_system.load("pois", {})
        self.trap_state = self.save_system.load("traps", {})
        self.tunnel_state = self.save_system.load("tunnels", {})
        self.explored = {
            tuple(int(part) for part in key.split(":")) for key in self.save_system.load("explored", []) if ":" in key
        }

        saved_npcs = self.save_system.load("npcs", None)
        if saved_npcs is not None:
            self._restore(saved_npcs)
            # A game saved underground is loaded underground: the player's position is
            # already down there, so the tunnel has to be back around it before anything
            # else runs, background generation threads included. One of those persisting a
            # world that had not yet remembered where it was would write the tunnel out of
            # the save.
            self._restore_underground(self.save_system.load("underground", None))
            # Fills in quests saved before boss names were tracked, and quests whose boss
            # was still unnamed when the game was last closed.
            self.sync_quest_boss_names()
            # A settlement saved before it had a wall still gets its garrison, so the towers
            # of a game already in progress are not standing empty.
            for village in self.villages:
                if village.defended and not any(
                    npc.is_guard and village.contains_point(npc.x, npc.y) for npc in self.npcs
                ):
                    self._post_guards(village)
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
            self._post_guards(village)
            # A new world is stocked to the *near* cap, not the far one. Everything placed
            # here lands inside the settled ring, which is within despawn range of the
            # spawn point, so seeding the far cap put the deep wilds' population on the
            # starting town's doorstep and no amount of capping took it back off again.
            # The wilds thicken as the player walks out, through the ordinary respawn.
            self.monsters = [
                self._new_monster(*self._random_coords_away_from_spawn()) for _ in range(c.World.ROAMING_CAP_NEAR)
            ]
            self._spawn_landmark_boss()
        self._index_buildings()
        set_active_buildings(self.buildings)

        if self.context is None:
            self.context_window.start_streaming()
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            # A continued game opens on its lore the same way a new one does: on black,
            # before anything in the world moves, rather than as a panel over a street.
            self.context_window.show(self.context, intro=True)
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

    def _post_guards(self, village: Village):
        """Stand somebody at every gate and every tower of a walled town.

        A guard is an ordinary villager with three differences, all of them already meant
        something elsewhere: they always take up arms (`NPC.is_militia`), they carry a real
        weapon rather than a tool, and they hold their post instead of strolling the street.
        That is enough for the militia orders, the mob and the surround slots to treat them
        like anyone else."""
        defences = village.defences()
        posts = list(defences["gates"]) + list(defences["towers"])
        for x, y in posts:
            for _ in range(c.Villages.GUARDS_PER_GATE):
                spot = self.free_spot_near(x, y, c.Entities.NPC_SIZE / 2)
                guard = NPC(*spot)
                guard.is_guard = True
                guard.home = spot
                guard.color = c.Villages.GUARD_COLOR
                guard.wander.radius = c.Villages.GUARD_POST_RADIUS
                self.npcs.append(guard)

    def _random_coords_away_from_spawn(self) -> tuple[int, int]:
        center = c.World.WORLD_SIZE // 2
        min_dist = c.World.INITIAL_SPAWN_MIN_DISTANCE
        for _ in range(20):
            x, y = random.randint(0, c.World.WORLD_SIZE), random.randint(0, c.World.WORLD_SIZE)
            if math.hypot(x - center, y - center) < min_dist or self._spawn_is_sheltered(x, y):
                continue
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                return x, y
        # Nothing clear in 20 tries: settle for the last roll rather than looping forever.
        # A monster standing in a wall beats hanging world generation.
        return x, y

    def night_damage_mult(self) -> float:
        """How much harder everything hits right now. A property of the hour, not of the
        monster, so anything that damages the player reads it from here."""
        return c.DayNight.NIGHT_DAMAGE_MULT if self.daynight.is_night else 1.0

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
        """Leave the session: background threads still in flight stop writing to the save,
        and stop talking to a screen that belongs to the next game. `EventSystem` reads
        `closed` for the same reason, since a presage thread can outlive the session."""
        self.closed = True
        self.notify = None

    def persist_world(self):
        """Flush generated world state to disk. Called by the background generation threads
        so finished work (context, shops, boss and landmark names) survives a restart
        instead of being regenerated on the next continue.

        Each call serialises the whole world, so a burst of threads finishing together (the
        village names of a freshly found settlement, say) is throttled to one write: the work
        is already in memory, and `Game.save_data` writes it out on the next autosave anyway.
        """
        if self.closed:
            return
        with self._persist_lock:
            now = time.monotonic()
            if now - self._last_persist < c.World.PERSIST_MIN_INTERVAL_S:
                return
            self._last_persist = now
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

    def _trap_state_snapshot(self) -> dict:
        """Which bear traps have already shut, loaded chunks included. Everything else about
        a trap comes back from its chunk seed, so this is the whole of what needs saving."""
        snapshot = dict(self.trap_state)
        for trap in self.traps:
            if trap.sprung:
                snapshot[trap.id] = True
        return snapshot

    def _tunnel_state_snapshot(self) -> dict:
        """What is left of every tunnel visited so far: its garrison and whether its hoard
        has been put out. The layout itself comes back from the village's chunk."""
        snapshot = dict(self.tunnel_state)
        for tunnel_id, tunnel in self.tunnels.items():
            snapshot[tunnel_id] = tunnel.state()
        return snapshot

    def serialize(self) -> dict:
        # A wandering merchant is a transient event; drop it rather than saving it as permanent.
        npcs = [npc for npc in self.npcs if npc is not self.events.wandering_merchant]
        # Camp guards are not saved either: the camp's own count is what a garrison is, and
        # `_populate_camp` stands them back up from it. Saving them too would put the ones on
        # the ground at save time next to the ones the count rebuilds on load.
        monsters = [monster for monster in self.monsters if not monster.camp_id]
        return {
            "items": [item.to_dict() for item in self.items],
            "npcs": [npc.to_dict() for npc in npcs],
            "monsters": [monster.to_dict() for monster in monsters],
            "bosses": [boss.to_dict() for boss in self.bosses],
            "buildings": [building.to_dict() for building in self.buildings],
            "villages": [village.to_dict() for village in self.villages],
            "breakables": [breakable.to_dict() for breakable in self.breakables],
            "pois": self._poi_state_snapshot(),
            "traps": self._trap_state_snapshot(),
            "tunnels": self._tunnel_state_snapshot(),
            "underground": (
                None
                if self.underground is None
                else {"id": self.underground.id, "return": list(self.surface_return or self.underground.entrance)}
            ),
            "camp_rest": {key: until for key, until in self.rest_cooldowns.items() if until > time.time()},
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
        self._village_solids_by_chunk = {}
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
            # A walled town is solid all the way out to its palisade, so it is bucketed by
            # the whole ring rather than by the well in the middle of it.
            reach = village.grounds_radius if village.defended else c.Villages.WELL_RADIUS
            footprint = pygame.Rect(0, 0, reach * 2, reach * 2)
            footprint.center = (round(village.x), round(village.y))
            bucket(self._village_solids_by_chunk, footprint, village)

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
        found = {}
        for chunk in self._chunk_window(x, y, radius):
            for building in self._buildings_by_chunk.get(chunk, ()):
                found[building.id] = building
        return list(found.values())

    def blocked(self, x, y, radius) -> bool:
        # Underground the answer is the rock, and nothing else: a tunnel is carved out of a
        # part of the world no chunk ever streams into, so there is nothing else down there
        # to collide with.
        if self.underground is not None:
            return self.underground.blocks(x, y, radius)
        solids = self._village_solids_by_chunk.get(self._chunk_of(x, y), ())
        if any(village.blocks(x, y, radius) for village in solids):
            return True
        if any(building.blocks(x, y, radius) for building in self.buildings_near(x, y)):
            return True
        return any(item.blocks(x, y, radius) for item in self.scenery_near(x, y))

    def walls_near(self, x, y) -> list:
        """The palisade stretches of any walled town near this point, as rectangles."""
        rects = []
        for village in self._village_solids_by_chunk.get(self._chunk_of(x, y), ()):
            rects.extend(village.defences()["walls"])
        return rects

    def line_of_sight(self, x0, y0, x1, y1) -> bool:
        """Is there a clear line between two points, or is something solid in the way?

        Walks the segment in steps half a wall thick, asking the same `blocked` everything
        else does, so a house wall, a well or a tree trunk all break sight the way they
        break movement. Used by ranged monsters before they shoot: their arrow was already
        stopped by the wall, but they used to keep firing into it at a player they could
        not possibly see."""
        dx, dy = x1 - x0, y1 - y0
        distance = math.hypot(dx, dy)
        if distance == 0:
            return True
        step = c.Buildings.WALL_THICKNESS / 2
        for i in range(1, int(distance / step) + 1):
            t = i * step / distance
            if self.blocked(x0 + dx * t, y0 + dy * t, 1):
                return False
        return True

    def _chunk_window(self, x, y, radius) -> List[tuple[int, int]]:
        """Every chunk covering the box of `radius` around (x, y). The one place that walk
        is written, shared by the building lookup and by the scenery the renderer asks for."""
        size = c.World.CHUNK_SIZE
        return [
            (cx, cy)
            for cx in range(int((x - radius) // size), int((x + radius) // size) + 1)
            for cy in range(int((y - radius) // size), int((y + radius) // size) + 1)
        ]

    def scenery_ground_in_range(self, x, y, radius):
        """The ground itself around a point (patches, ponds, roads, grass), yielded kind by
        kind in draw order, so a road is never buried under the meadow it crosses."""
        chunks = self._chunk_window(x, y, radius)
        for kind in c.Scenery.GROUND_KINDS:
            for chunk in chunks:
                yield from self._ground_by_chunk.get(chunk, {}).get(kind, ())

    def scenery_props_in_range(self, x, y, radius):
        """The trees, rocks and reeds standing around a point."""
        for chunk in self._chunk_window(x, y, radius):
            yield from self._props_by_chunk.get(chunk, ())

    def scenery_near(self, x, y) -> List[Scenery]:
        """The solid scenery (trunks, boulders) that can reach (x, y). Bucketed on its own
        fine grid: there are far more trees in a wood than buildings in a village, and this
        runs several times per entity per frame."""
        cell = c.Scenery.INDEX_CELL
        return self._scenery_by_cell.get((int(x // cell), int(y // cell)), [])

    def water_at(self, x, y) -> bool:
        """Whether that point is in a river, a pond or a lake, with nothing bridging it.

        Water is the one piece of terrain that neither blocks nor is walked over: everything
        crosses it slowly (the player less slowly the more they swim), which is what makes a
        river worth running to and a bridge worth walking to. A deck over the water takes it
        back to ordinary ground, so a crossing is a crossing."""
        cell = c.Scenery.INDEX_CELL
        pieces = self._water_by_cell.get((int(x // cell), int(y // cell)), ())
        wet = False
        for piece in pieces:
            if not piece.covers(x, y):
                continue
            if piece.kind == "bridge":
                return False
            wet = True
        return wet

    def terrain_speed(self, x, y) -> float:
        """What the ground under something costs it. Everything but the player swims badly
        and never gets better at it, which is the whole reason a river is worth crossing."""
        return c.Scenery.SWIM_SPEED if self.water_at(x, y) else 1.0

    def free_spot_near(self, x, y, radius) -> tuple[float, float]:
        """The nearest standable point to (x, y), which may be (x, y) itself.

        The spawn point is a fixed world coordinate while the starting town is laid out
        around a random centre near it, so the two overlap often; the same is true of any
        village generated later. Rather than move the settlement, whoever is being placed
        steps out to the first clear spot around it."""
        if not self.blocked(x, y, radius):
            return x, y
        step = radius * 2
        for ring in range(1, c.World.FREE_SPOT_MAX_RINGS + 1):
            distance = ring * step
            for index in range(ring * 8):
                angle = 2 * math.pi * index / (ring * 8)
                cx, cy = x + math.cos(angle) * distance, y + math.sin(angle) * distance
                if not self.blocked(cx, cy, radius):
                    return cx, cy
        # Walled in on every side within the search: leave the caller where they were
        # rather than teleporting them somewhere arbitrary.
        return x, y

    def hostiles_near(self, x, y, radius: float) -> list:
        """Everything within `radius` of (x, y) that would attack the player: monsters,
        bosses, villagers who have turned, and animals currently hunting."""
        near = []
        near += [m for m in self.monsters if m.distance_to_point((x, y)) <= radius]
        near += [b for b in self.bosses if b.distance_to_point((x, y)) <= radius]
        near += [n for n in self.npcs if n.hostile and n.distance_to_point((x, y)) <= radius]
        near += [cr for cr in self.critters if cr.hostile and cr.distance_to_point((x, y)) <= radius]
        return near

    def safe_spot_near(self, x, y, radius, clearance: float = None) -> tuple[float, float]:
        """Where to put the player: `free_spot_near` knows only about geometry, and a point
        with no wall in it is not safe if whatever killed the player is standing on it. Same
        outward ring search, with candidates holding anything hostile within `clearance`
        rejected as well, falling back to the geometric answer when the search finds nowhere
        clear (better a rough spawn than a hang)."""
        clearance = c.World.SAFE_SPOT_CLEARANCE if clearance is None else clearance
        if not self.blocked(x, y, radius) and not self.hostiles_near(x, y, clearance):
            return x, y
        step = radius * 2
        for ring in range(1, c.World.FREE_SPOT_MAX_RINGS + 1):
            distance = ring * step
            for index in range(ring * 8):
                angle = 2 * math.pi * index / (ring * 8)
                cx, cy = x + math.cos(angle) * distance, y + math.sin(angle) * distance
                if not self.blocked(cx, cy, radius) and not self.hostiles_near(cx, cy, clearance):
                    return cx, cy
        return self.free_spot_near(x, y, radius)

    def clear_hostiles_around(self, x, y, radius: float):
        """Send the roaming monsters standing around (x, y) back out into the wilds. Used
        when the player respawns: the pack that killed them shouldn't still be bearing down
        on the spawn point. Bosses and camp garrisons stay put, being where they belong and
        not something to be rid of by dying."""
        self.monsters = [m for m in self.monsters if m.camp_id or m.distance_to_point((x, y)) > radius]

    def building_at(self, x, y) -> Building | None:
        """The building whose floor (x, y) stands on, or None. Buildings are kept far enough
        apart that at most one can contain a given point."""
        for building in self.buildings_near(x, y):
            if building.contains_point(x, y):
                return building
        return None

    def chase_waypoint(self, chaser, player: Player, radius: float):
        """Where a chaser should head next, or None to walk straight at the player.

        Buildings are the only obstacles and each has a single door, so a chase across a wall
        never needs a real pathfinder: aim for the door of whichever building separates the
        two, and walk round any other building standing in the way rather than into it.

        Takes any entity with an x/y and its own radius, since an angry villager has to find
        its way round a house exactly like a wolf does.
        """
        monster = chaser
        monster_building = self.building_at(monster.x, monster.y)
        player_building = self.building_at(player.x, player.y)
        start = (monster.x, monster.y)

        if monster_building is player_building:
            if monster_building is not None:
                # Same room: the only things between them are the bed and the table, so the
                # detour that walks round a house walks round those too. Without it a monster
                # steered into the furniture and stuck there while the player stood in a
                # corner two steps away.
                solids = [rect for rect, _kind in monster_building.interior_layout()["solids"]]
                corner = self._detour_corner(start, (player.x, player.y), radius, solids)
                # A room is small enough that the way round a table can be a point inside the
                # wall behind it. Sending a monster at one is worse than sending it nowhere:
                # steering gets round furniture on its own, it just needs the room to do it.
                if corner is not None and self.blocked(corner[0], corner[1], radius):
                    return None
                return corner
            # Both outdoors: straight at the player, round anything standing in the way.
            goal = (player.x, player.y)
        elif monster_building is not None:
            # Indoors with the player elsewhere: out through the door first, and no detour
            # around the building the monster is standing in.
            return self._door_goal(monster_building, monster, radius, leaving=True)
        else:
            goal = self._door_goal(player_building, monster, radius, leaving=False)

        return self._detour_corner(start, goal, radius) or goal

    def open_door_for(self, chaser):
        """A villager chasing the player into a house lets themselves in: the door is theirs
        and they live behind it. Monsters get no such courtesy and beat it down instead
        (WorldCombat.bash_doors), which is the whole difference between the two."""
        for building in self.buildings_near(chaser.x, chaser.y):
            if not building.door_closed:
                continue
            door = building.door_rect()
            if math.hypot(chaser.x - door.centerx, chaser.y - door.centery) <= c.Buildings.DOOR_BASH_REACH:
                building.door_open = True

    @staticmethod
    def _door_goal(building: Building, monster: Monster, radius: float, leaving: bool):
        """The point to walk to next to get through `building`'s door, in or out. A monster
        lines up with the doorway from the outside first, then steps across the threshold,
        so it goes through the gap instead of shouldering the wall next to it.

        Written along the door's own outward normal rather than in terms of "the bottom of
        the building", since a house can be turned to face any of the four ways."""
        nx, ny = building.outward()
        door = building.door_rect()
        door_front = building.door_front()
        inside = (door.centerx - nx * 36, door.centery - ny * 36)
        fits = radius < c.Buildings.DOOR_WIDTH / 2 - 4
        # How far off the doorway's centre line this one stands, measured across the facade.
        across = abs((monster.x - door.centerx) * -ny + (monster.y - door.centery) * nx)
        aligned = across < c.Buildings.DOOR_WIDTH / 2 - radius
        if building.door_closed:
            # A shut door is a wall with nothing to walk round: come right up against it from
            # whichever side this is on and beat on it (WorldCombat.bash_doors). Close enough
            # to be in reach of the leaf, which the usual standing-off point is not.
            if leaving:
                return inside
            return (door.centerx + nx * (radius + 6), door.centery + ny * (radius + 6))
        if leaving:
            return door_front if aligned else inside
        # Too broad for the doorway (the stone colossus): it waits on the doorstep rather
        # than shoving itself into a wall it can never pass. Still round the far side of the
        # building, and the door is on the front: only step in from the front half.
        in_front = (monster.x - building.x) * nx + (monster.y - building.y) * ny > 0
        if not fits or not aligned or not in_front:
            return door_front
        return inside

    def assign_surround_slots(self, chasers, target):
        """Deal the chasers coming for one target their places around it, and hand out the
        few permissions to swing.

        Two things turn a pack from a queue into an ambush. The bearings are dealt evenly
        round the ring in the order the chasers already stand in, rather than each rolling
        its own at spawn, so whoever joins the chase late takes the empty side instead of
        the crowded one; and only `Entities.MAX_ACTIVE_ATTACKERS` of them may swing at any
        moment, the nearest first, so the rest close the circle and wait their turn where
        the player can see them coming.

        A chaser keeps the bearing it holds while the dealt one is close to it, which is
        what stops the whole ring rotating a little every frame."""
        if not chasers:
            return
        ordered = sorted(chasers, key=lambda ch: math.atan2(ch.y - target.y, ch.x - target.x))
        # The ring is anchored on where the first of them already stands, so dealing the
        # slots never asks anybody to walk round to the far side for the sake of symmetry.
        base = math.atan2(ordered[0].y - target.y, ordered[0].x - target.x)
        step = 2 * math.pi / len(ordered)
        limit = math.radians(c.Entities.SLOT_REASSIGN_DEG)
        for index, chaser in enumerate(ordered):
            slot = base + step * index
            drift = abs((chaser.slot_angle - slot + math.pi) % (2 * math.pi) - math.pi)
            if drift > limit:
                chaser.slot_angle = slot

        target_pos = (target.x, target.y)
        closest = sorted(chasers, key=lambda ch: ch.distance_to_point(target_pos))
        for rank, chaser in enumerate(closest):
            # A swing already under way is never cut off half finished: the token is spent
            # the moment the arm goes back, not when the blow lands.
            chaser.attack_token = rank < c.Entities.MAX_ACTIVE_ATTACKERS or chaser.attack_in_progress

    def _scenery_obstacles(self, start, goal, radius: float) -> list:
        """The solid wilderness standing between two points, as rectangles a detour can be
        costed round. Trunks and boulders touching each other are merged into one clump: a
        copse is one thing to walk round, and routing round each trunk in turn is what has
        a monster picking its way into the middle of the wood.

        Only looked for over a short stretch (`World.SCENERY_DETOUR_RANGE`). Beyond that a
        wood is not an obstacle, it is the ground, and `Monster._steer` deals with it a
        trunk at a time."""
        span = math.dist(start, goal)
        if not span or span > c.World.SCENERY_DETOUR_RANGE:
            return []
        rects = []
        seen = set()
        step = c.Scenery.INDEX_CELL / 2
        for i in range(int(span / step) + 1):
            t = min(1.0, i * step / span)
            x = start[0] + (goal[0] - start[0]) * t
            y = start[1] + (goal[1] - start[1]) * t
            for piece in self.scenery_near(x, y):
                if not piece.blocking_radius or id(piece) in seen:
                    continue
                seen.add(id(piece))
                reach = piece.blocking_radius + radius
                rects.append(pygame.Rect(piece.x - reach, piece.y - reach, reach * 2, reach * 2))
        return _merge_rects(rects)

    def _detour_corner(self, start, goal, radius: float, rects=None):
        """The corner to head for when something solid sits between `start` and `goal`, or
        None when the way is clear.

        The way past a rectangle runs through at most two of its corners, so both ways round
        are costed in full and the first corner of the shorter one is returned. Costing the
        whole detour, rather than just picking the nearest corner, is what stops a monster
        oscillating between the near corner behind it and the far corner it should round.

        `rects` is what stands in the way: the buildings around `start` by default, or a
        room's furniture when the chase is happening inside one.
        """
        if rects is None:
            rects = [building.rect for building in self.buildings_in_range(*start, c.World.CHUNK_SIZE)]
            # A town wall is the one obstacle in the world too long to steer round a step at
            # a time: each stretch runs from a corner tower to a gatepost, so rounding its
            # end is exactly walking to the nearest gate.
            rects += self.walls_near(*start)
            rects += self._scenery_obstacles(start, goal, radius)
        for obstacle in rects:
            margin = radius + 8
            rect = obstacle.inflate(margin * 2, margin * 2)
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
        """Spawn a boss out in the dangerous outer wilds as a quest hunt target.

        The band starts where roaming bosses start and runs outward from there. The world
        has no edge, so it is deliberately not clamped to the settled ring: hunting one
        is meant to be a walk past everything the player already knows.
        """
        center = c.World.WORLD_SIZE // 2
        x = y = center
        for _ in range(20):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_MIN_DISTANCE, c.Boss.ROAM_MIN_DISTANCE + c.Boss.QUEST_SPAWN_BAND)
            x = center + math.cos(angle) * dist
            y = center + math.sin(angle) * dist
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE):
                break
        # A boss never despawns, so unlike a monster it can't be left standing in a wall
        # if every roll was blocked: whatever came out of the loop is stepped clear first.
        x, y = self.free_spot_near(x, y, c.MONSTER_MAX_SIZE)
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
        chance = c.Boss.ROAM_CHANCE * (c.DayNight.NIGHT_BOSS_ROAM_MULT if self.daynight.is_night else 1.0)
        if random.random() > chance:
            return
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_SPAWN_MIN_DIST, c.Boss.ROAM_SPAWN_MAX_DIST)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE):
                self.spawn_boss(x, y, announce="A roaming terror, {name}, prowls the wilds")
                return

    def _restock_merchants(self):
        """Put a delivery on the shelf of any merchant whose clock has run out.

        Rolled locally rather than asked of the model: the batched generation exists because
        one call per shop was the queue's biggest cost, and a shop that refills every ten
        minutes would put that cost straight back. What is already out is left alone, so a
        restock tops the stock back up instead of replacing what the player was saving up
        for."""
        for npc in self.npcs:
            if not npc.is_merchant or not npc.shop_ready or npc.restock_in() > 0:
                continue
            missing = c.Villages.SHOP_STOCK_TARGET - len(npc.shop_items)
            npc.add_stock(roll_shop_stock(missing) if missing > 0 else [])

    def start_shop_generation(self):
        """Stock every merchant still waiting for one, in a single background call."""
        merchants = [npc for npc in self.npcs if npc.is_merchant and not npc.shop_ready]
        if not merchants or not self.context or self._shops_generating:
            return
        self._shops_generating = True
        threading.Thread(target=self._generate_merchant_shops, args=(merchants,), daemon=True).start()

    def _generate_merchant_shops(self, merchants: list):
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
        # A parcel is in the player's hands from the moment the quest is given, so a delivery
        # points at whoever it is for until it has actually been handed over.
        if quest.quest_type == "deliver" and quest.kills_done < quest.kill_count:
            recipient = next((npc for npc in self.npcs if npc.name == quest.recipient_npc_name), None)
            return (recipient.x, recipient.y) if recipient else None

        ready_to_hand_in = (quest.item is not None and quest.item in player.inventory) or (
            quest.quest_type in ("kill_mob", "clear_camp", "deliver") and quest.kills_done >= quest.kill_count
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
        # A camp and a house both stand still, so the place was written into the quest when
        # it was given rather than looked up again here.
        if quest.quest_type in ("clear_camp", "steal") and quest.target_x is not None:
            return (quest.target_x, quest.target_y)
        return None

    def npc_in_reach(self, player: Player) -> NPC | None:
        """The NPC the player is close enough to interact with, nearest first. Shared by the
        on-screen prompt, the talk key and the trade key so they can't disagree."""
        pos = player.get_pos(c.Player.INTERACTION_DISTANCE)
        reach = c.Player.INTERACTION_DISTANCE + c.Entities.NPC_SIZE // 2
        in_reach = [npc for npc in self.npcs if npc.distance_to_point(pos) < reach]
        return min(in_reach, key=lambda npc: npc.distance_to_point(pos), default=None)

    def village_at(self, x, y, margin: float = 0) -> Village | None:
        """The village whose grounds (x, y) stands on, or None out in the wilds. `margin`
        widens the grounds, which is what keeps a spawn off a settlement's doorstep."""
        return next(
            (
                village
                for village in self.villages
                if village.distance_to_point((x, y)) <= village.grounds_radius + margin
            ),
            None,
        )

    def _spawn_is_sheltered(self, x, y) -> bool:
        """Whether (x, y) is ground nothing hostile may be spawned on: inside the ring the
        world centre holds, or on a settlement's grounds or doorstep."""
        center = c.World.WORLD_SIZE // 2
        if math.hypot(x - center, y - center) < c.World.SAFE_RADIUS:
            return True
        return self.village_at(x, y, c.World.VILLAGE_SPAWN_MARGIN) is not None

    def roaming_cap(self, player: Player) -> int:
        """How many roaming monsters the world holds around the player right now. A ramp
        from the near cap on the starting town's doorstep to the far cap out in the wilds,
        rather than one world-wide number: the early game shouldn't be as crowded as the
        ground the player reaches an hour later. The ramp is eased (ROAMING_CAP_CURVE) so
        the near ground stays near-empty for a good walk rather than filling up at once."""
        center = c.World.WORLD_SIZE // 2
        distance = math.hypot(player.x - center, player.y - center)
        span = max(c.World.ROAMING_CAP_FAR_DISTANCE - c.World.SAFE_RADIUS, 1)
        ratio = min(max((distance - c.World.SAFE_RADIUS) / span, 0.0), 1.0) ** c.World.ROAMING_CAP_CURVE
        return round(c.World.ROAMING_CAP_NEAR + (c.World.ROAMING_CAP_FAR - c.World.ROAMING_CAP_NEAR) * ratio)

    def _spawn_monster_away_from(self, player: Player):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.World.SPAWN_MIN_DISTANCE, c.World.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            # Monsters wander into settlements, but none of them starts life in one or on
            # its doorstep: a village should read as the safe ground between stretches of
            # wilderness. The starting town's ground is wider still (World.SAFE_RADIUS
            # around the world centre), since that is where every run begins and every
            # death sends the player back to.
            if self._spawn_is_sheltered(x, y):
                continue
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                # What crawls out after dark is what lives deeper in the wilds, but only
                # proportionally so: a flat bonus put bandits on the starting town's
                # doorstep every night, which is the one piece of ground that has to stay
                # survivable. Out past the settled ring the whole bonus applies.
                bonus = 0
                if self.daynight.is_night:
                    center = c.World.WORLD_SIZE // 2
                    from_center = math.hypot(x - center, y - center)
                    bonus = min(
                        c.DayNight.NIGHT_DANGER_BONUS,
                        from_center * c.DayNight.NIGHT_DANGER_DISTANCE_FRAC,
                    )
                # A pack kind (wolves, goblins) is rolled once and then stood up as a group,
                # so the wilds hold a few real fights rather than a scatter of single mobs.
                leader = self._new_monster(x, y, danger_bonus=bonus)
                pack = [leader]
                for _ in range(random.randint(*leader.kind.group) - 1):
                    spread = c.World.PACK_SPREAD
                    mate_x, mate_y = x + random.uniform(-spread, spread), y + random.uniform(-spread, spread)
                    if not self.blocked(mate_x, mate_y, leader.kind.size / 2):
                        pack.append(Monster(mate_x, mate_y, leader.kind))
                # Each member takes its own bearing around the player, evenly spread from a
                # random start, so a pack closes in as a ring instead of a queue.
                base = random.uniform(0, 2 * math.pi)
                for index, member in enumerate(pack):
                    member.slot_angle = base + 2 * math.pi * index / len(pack)
                self.monsters.extend(pack)
                return

    def _spawn_critter_away_from(self, player: Player):
        """Put one animal, or one herd/pack, on the ground out of sight of the player. Which
        species turns up is a question of how far out this is, the same rule monsters follow:
        rabbits and deer near town, wild dogs and bears deep in the wilds."""
        center = c.World.WORLD_SIZE // 2
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Wildlife.SPAWN_MIN_DISTANCE, c.Wildlife.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            kind = pick_critter_kind(math.hypot(x - center, y - center))
            if self.blocked(x, y, kind.size / 2):
                continue
            for _ in range(random.randint(*kind.group)):
                spread = c.Wildlife.GROUP_SPREAD
                mate_x = x + random.uniform(-spread, spread)
                mate_y = y + random.uniform(-spread, spread)
                if not self.blocked(mate_x, mate_y, kind.size / 2):
                    self.critters.append(Critter(mate_x, mate_y, kind))
            return

    def _ensure_village_dogs(self, player: Player):
        """Stand a village's dogs back up when the player is near it. They are wildlife, not
        villagers: session-only, rebuilt from the village rather than saved, the same trick a
        bandit camp's garrison uses. How many a settlement keeps is fixed by its chunk, so
        the same village always has the same pack."""
        for village in self.villages:
            if village.distance_to_point(player.get_pos()) > c.Wildlife.DESPAWN_DISTANCE:
                continue
            key = f"{village.chunk[0]}:{village.chunk[1]}"
            wanted = random.Random(f"dogs{key}").randint(*c.Wildlife.VILLAGE_DOGS)
            living = [cr for cr in self.critters if cr.village_key == key]
            hostile = any(npc.hostile for npc in self.npcs if village.contains_point(npc.x, npc.y))
            for _ in range(wanted - len(living)):
                angle = random.uniform(0, 2 * math.pi)
                distance = random.uniform(village.radius * 0.15, village.radius * 0.5)
                x, y = self.free_spot_near(
                    village.x + math.cos(angle) * distance,
                    village.y + math.sin(angle) * distance,
                    c.CRITTER_KINDS_BY_NAME["dog"].size / 2,
                )
                dog = Critter(x, y, c.CRITTER_KINDS_BY_NAME["dog"], home=(x, y), village_key=key)
                # A village that has already turned on the player doesn't hand back a
                # friendly dog just because this one was stood up afterwards.
                dog.hostile = hostile
                self.critters.append(dog)

    def aggro_pack(self, critter: Critter):
        """Bring an animal's own kind in with it. Attacking one wild dog brings the pack,
        and hitting one village dog sets every dog in that village on the player, which is
        what stops a pack animal being killed one at a time in front of its family."""
        critter.aggro()
        for other in self.critters:
            if other is critter or other.hostile:
                continue
            near = other.distance_to_point((critter.x, critter.y)) < c.Wildlife.PACK_AGGRO_RADIUS
            same_pack = other.kind is critter.kind and near
            if same_pack or (critter.village_key and other.village_key == critter.village_key):
                other.aggro()

    def _monster_target(self, monster: Monster, player: Player):
        """Who this monster is coming for. The player, unless it has walked onto a
        settlement's grounds and a villager is nearer: a village is something monsters
        attack, not scenery they file past on their way to the player.

        A camp guard is left out of it. It holds a piece of ground rather than raiding, and
        a garrison drifting off to fight the nearest farmer would empty its own camp."""
        if monster.camp_id or not self.npcs:
            return player
        if self.village_at(monster.x, monster.y, c.Villages.DEFEND_MARGIN) is None:
            return player
        reach = min(monster.distance_to_point(player.get_pos()), c.Villages.DEFEND_RADIUS)
        victims = [npc for npc in self.npcs if monster.distance_to_point((npc.x, npc.y)) < reach]
        if not victims:
            return player
        return min(victims, key=lambda npc: monster.distance_to_point((npc.x, npc.y)))

    def _land_monster_blow(self, monster: Monster, target, damage: int, player: Player, quest_system: QuestSystem):
        """A monster's swing connecting, on the player or on whoever it caught instead. A
        villager cut down by a monster is nothing the player did, so it resolves as friendly
        fire: no provoked village, no purse, and the body stays down for good."""
        if target is player:
            player.receive_damage(damage, source=monster)
            return
        self._resolve_npc_hit(
            target,
            damage,
            player,
            quest_system,
            kb_dir=self._dir_from(monster.x, monster.y, target.x, target.y),
            blocked=self.blocked,
            by_player=False,
        )

    def _update_npcs(self, player: Player, dt, quest_system: QuestSystem):
        """Every villager's frame: fighting off an intruder, running for a door, hunting the
        player, or wandering their street.

        The world picks what each of them is doing and hands it to `NPC.update`, which gives
        back whatever its swing landed so the blow can be taken off the right list. A
        villager only ever fights one thing at a time, and defending the settlement comes
        first: a monster in the street is more pressing than a grudge."""
        indoors = self.building_at(player.x, player.y) is not None
        self._restock_merchants()
        fight, flee = self.militia_orders()
        mob = self._mob_orders(player, flee)
        self.assign_surround_slots([npc for npc in self.npcs if id(npc) in mob], player)
        self._throw_stones(player, mob)

        for npc in self.npcs:
            enemy = fight.get(id(npc))
            # The orders were worked out once for the whole street, so the neighbour who
            # went first may already have finished this one off.
            if enemy is not None and enemy.hp <= 0:
                enemy = None
            if enemy is not None:
                waypoint = self.chase_waypoint(npc, enemy, c.Entities.NPC_SIZE / 2)
                damage = npc.update(
                    player, dt, self.blocked, waypoint, target=enemy, terrain_mult=self.terrain_speed(npc.x, npc.y)
                )
                if damage:
                    self._resolve_monster_hit(
                        enemy,
                        self.monsters,
                        damage,
                        player,
                        quest_system,
                        kb_dir=self._dir_from(npc.x, npc.y, enemy.x, enemy.y),
                        blocked=self.blocked,
                        by_player=False,
                    )
                continue

            shelter = flee.get(id(npc))
            if shelter is not None:
                self.open_door_for(npc)
                inside = (shelter.x, shelter.interior_rect().centery)
                waypoint = self.chase_waypoint(npc, _Point(*inside), c.Entities.NPC_SIZE / 2)
                npc.update(
                    player,
                    dt,
                    self.blocked,
                    refuge=waypoint or inside,
                    terrain_mult=self.terrain_speed(npc.x, npc.y),
                )
                if shelter.contains_point(npc.x, npc.y) and not shelter.door_broken:
                    # Behind the door and shutting it. The player can be shut out or shut in
                    # with them; either way the street is emptier than it was.
                    shelter.door_open = False
                continue

            # Only an angry villager actually closing on the player needs a route round
            # the houses; everyone else is wandering and steers for itself.
            chasing = id(npc) in mob
            if chasing:
                self.open_door_for(npc)
            waypoint = self.chase_waypoint(npc, player, c.Entities.NPC_SIZE / 2) if chasing else None
            # A villager turns to greet the player in the street, but not through the wall of
            # a house they are standing in: a vision cone that always points at the player is
            # not a cone, and the whole of stealing is choosing a moment nobody is looking.
            damage = npc.update(
                player,
                dt,
                self.blocked,
                waypoint,
                target=player if chasing else None,
                face_player=not indoors,
                terrain_mult=self.terrain_speed(npc.x, npc.y),
                standoff=mob.get(id(npc), 0.0),
            )
            if damage:
                player.receive_damage(damage, source=npc)

    def _mob_orders(self, player: Player, flee: dict) -> dict:
        """Who in an angry village is actually coming for the player, and how close they mean
        to get: a dict of `id(npc)` to the standoff they hold.

        The same split that decides who meets a monster in the street decides this. Whoever
        `NPC.is_militia` names closes to arm's length and swings; the rest hang back at
        `Villages.MOB_STANDOFF` and throw stones, which is what makes a mob dangerous to walk
        into rather than something to be cut down one farmer at a time. Anyone already badly
        hurt (`NPC.routed`) drops out of the fight and is sent to a door instead, so a mob
        breaks rather than dying to the last of them."""
        orders: dict = {}
        for npc in self.npcs:
            if not npc.hostile or npc.distance_to_point((player.x, player.y)) > c.Entities.NPC_HOSTILE_RANGE:
                continue
            if npc.routed:
                shelter = self._refuge_for(npc)
                if shelter is not None:
                    flee[id(npc)] = shelter
                    continue
            reach = c.Entities.NPC_ATTACK_RANGE + c.Player.SIZE / 2 - c.Entities.CHASE_RING_MARGIN
            orders[id(npc)] = reach if npc.is_militia else c.Villages.MOB_STANDOFF
        return orders

    def _throw_stones(self, player: Player, mob: dict):
        """The back of the mob doing what a crowd with no swords does: throwing things.

        Only the ones holding their distance throw, only at what they can see, and only on
        their own slow cooldown. One stone is nothing; ten people throwing them is why an
        angry village is somewhere to leave rather than somewhere to fight."""
        now = pygame.time.get_ticks()
        for npc in self.npcs:
            if mob.get(id(npc), 0.0) < c.Villages.MOB_STANDOFF or now < npc.next_stone_ms:
                continue
            dx, dy = player.x - npc.x, player.y - npc.y
            if math.hypot(dx, dy) > c.Villages.MOB_STONE_RANGE:
                continue
            if not self.line_of_sight(npc.x, npc.y, player.x, player.y):
                continue
            npc.next_stone_ms = now + random.randint(*c.Villages.MOB_STONE_COOLDOWN_MS)
            npc.start_attack_anim()
            play_sound("shoot")
            self.projectiles.append(
                Projectile(
                    npc.x,
                    npc.y,
                    # Projectile angles are measured from straight up, clockwise.
                    math.atan2(dx, -dy),
                    c.Villages.MOB_STONE_DAMAGE,
                    style="stone",
                    color=STONE_COLOR,
                    shake=c.Combat.PLAYER_HURT_SHAKE / 2,
                    hostile=True,
                    owner_id=id(npc),
                    source_name=npc.name or "a villager",
                    max_range=c.Villages.MOB_STONE_RANGE,
                )
            )

    def update(self, player: Player, dt, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        # Particles/floating text/screen fx update once per frame in Game.run() instead of
        # here, so they keep animating even while a menu pauses the rest of this update.
        self.daynight.update(dt)
        # None of this happens underground, and that absence is most of what makes a tunnel
        # somewhere else: no ground streams in around the player, nothing is discovered, no
        # event finds them, and the map remembers nothing of a place with no landmarks.
        # What is down there was put there when they climbed down, and that is all.
        if self.underground is None:
            self._sync_chunks(player)
            self._reveal_around(player)
            self.events.update(dt, player, quest_system, npc_name_generator)
            self._check_poi_discovery(player)
            self._check_village_discovery(player)
            self._clear_reached_rumors(player)

        player_pos = player.get_pos()

        # After dark everything hits harder and notices sooner, whenever it spawned: night
        # is a state of the world, not a property of the monsters standing in it.
        damage_mult = self.night_damage_mult()
        detection = c.World.DETECTION_RANGE * (c.DayNight.NIGHT_DETECTION_MULT if self.daynight.is_night else 1.0)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt).
        update_radius = detection + c.Player.SIZE
        nearby = [
            m for m in self.monsters if abs(m.x - player.x) <= update_radius and abs(m.y - player.y) <= update_radius
        ]
        # Who each of them is coming for is settled before any of them moves: the ones
        # converging on the same target are dealt their places around it and the handful of
        # permissions to swing, so a pack closes a circle instead of forming a queue.
        targets = {monster: self._monster_target(monster, player) for monster in nearby}
        by_target: dict = {}
        for monster, target in targets.items():
            by_target.setdefault(id(target), (target, []))[1].append(monster)
        for target, chasers in by_target.values():
            self.assign_surround_slots(chasers, target)

        for monster in nearby:
            target = targets[monster]
            waypoint = self.chase_waypoint(monster, target, monster.kind.size / 2)
            # `nearby` doubles as the crowd each monster shoulders its way out of: the ones
            # converging on the player are exactly the ones that pile up on each other.
            damage = monster.move(
                target,
                dt,
                self.blocked,
                waypoint,
                damage_mult,
                detection,
                crowd=nearby,
                terrain_mult=self.terrain_speed(monster.x, monster.y),
            )
            if damage:
                self._land_monster_blow(monster, target, damage, player, quest_system)
            # A creeper's fuse has burned out: it leaves the map and takes the ground with it.
            if monster.fuse_expired():
                self.detonate_creeper(monster, player, quest_system)
        self.fire_monster_shots(player, damage_mult)
        self.bash_doors(player, damage_mult)

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        # Camp guards are the exception: they hold a place rather than roam, and their camp
        # would look abandoned while its chunk is still loaded. They leave with the chunk
        # instead (see WorldStreaming._unload_chunk). Nothing despawns while the player is
        # underground: every monster on the surface is a world away from a tunnel, and the
        # whole map would empty out and refill itself over one climb down.
        if self.underground is None:
            self.monsters = [
                m for m in self.monsters if m.camp_id or m.distance_to_point(player_pos) <= c.World.DESPAWN_DISTANCE
            ]

        # Burn (weapon affix) ticks over time and can finish a wounded target off.
        self._tick_burns(self.monsters, player, quest_system)
        self._tick_burns(self.bosses, player, quest_system)

        # Bosses never despawn; they chase, cast and enrage on their own schedule.
        for boss in list(self.bosses):
            boss.update_boss(self, player, dt, quest_system)

        self.boss_roam_timer += dt
        if self.underground is None and self.boss_roam_timer >= c.Boss.ROAM_CHECK_INTERVAL_MS:
            self.boss_roam_timer = 0.0
            self._maybe_spawn_roaming_boss(player)

        self.update_projectiles(player, quest_system, dt)

        self._update_npcs(player, dt, quest_system)

        for critter in self.critters:
            # Only an animal actually coming for the player needs a route round the houses;
            # everything else is wandering or running and steers for itself.
            chasing = critter.hostile and critter.distance_to_point(player_pos) <= critter.kind.detection
            waypoint = self.chase_waypoint(critter, player, critter.size / 2) if chasing else None
            critter.update(
                player, dt, self.blocked, damage_mult, waypoint, terrain_mult=self.terrain_speed(critter.x, critter.y)
            )
        # Checked once everything has taken its step, so a trap shuts on where things
        # actually ended up this frame rather than on where they set off from.
        self.snap_traps(player, quest_system)

        # Everything below this line stocks the surface around the player, so none of it runs
        # while they are underground: a tunnel holds what was put in it when they climbed
        # down, and nothing wanders in after them.
        if self.underground is not None:
            return

        self._ensure_village_dogs(player)
        self.critters = [
            critter for critter in self.critters if critter.distance_to_point(player_pos) <= c.Wildlife.DESPAWN_DISTANCE
        ]
        if len(self.critters) < c.Wildlife.COUNT:
            self.critter_respawn_timer += dt
            if self.critter_respawn_timer >= c.Wildlife.RESPAWN_INTERVAL_MS:
                self.critter_respawn_timer = 0.0
                self._spawn_critter_away_from(player)

        # Camp guards don't count: they never despawn, so counting them would slowly choke
        # off the roaming population as the player finds more camps.
        roaming = sum(1 for m in self.monsters if not m.camp_id)
        if roaming < self.roaming_cap(player):
            self.respawn_timer += dt
            respawn_interval = c.World.RESPAWN_INTERVAL_MS
            blood = self.events.blood_intensity
            if blood > 0:
                # Ramped like the sky, so the wilds fill up as the night reddens.
                respawn_interval /= 1.0 + (c.Events.BLOOD_NIGHT_RESPAWN_MULT - 1.0) * blood
            elif self.daynight.is_night:
                respawn_interval /= c.DayNight.NIGHT_RESPAWN_MULT
            if self.respawn_timer >= respawn_interval:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
