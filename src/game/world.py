from __future__ import annotations

import math
import random
import threading
import time
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.daynight import DayNightCycle
from core.particles import get_particles
from game.combat import WorldCombat
from game.entities.boss import Boss
from game.entities.breakables import Breakable, generate_breakables
from game.entities.buildings import Building, set_active_buildings
from game.entities.critter import Critter, pick_critter_kind
from game.entities.items import AMMO_BUNDLE, Item
from game.entities.monsters import Monster, pick_monster_kind
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest, pois_for_chunk
from game.entities.projectile import Projectile
from game.entities.village import Village, generate_starting_world, village_site
from game.events import EventSystem
from game.loot import roll_shop_stock
from game.streaming import WorldStreaming
from llm.llm_request_queue import generate_response_queued
from llm.merchant_system import generate_shop_inventories

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


class World(WorldCombat, WorldStreaming):
    """The living world and everything standing in it.

    Two halves live in their own modules and are mixed in here: `WorldCombat` (game/combat.py)
    resolves every blow and its aftermath, `WorldStreaming` (game/streaming.py) generates the
    endless map around the player and names what it finds. Both work on the entity lists this
    class owns; keeping them here as one class is what lets `self.monsters` and friends stay
    the single source of truth.
    """

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
        # Wandering wildlife, purely atmospheric; transient like particles, never saved.
        self.critters: List[Critter] = []
        # Arrows in flight; transient like particles, never saved.
        self.projectiles: List[Projectile] = []
        # When each camp's fire will serve the player again, by POI id (wall-clock seconds,
        # so quitting to the menu can't reset a fire the player just used).
        self.camp_rest_cooldowns: dict = {}
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

        # Throttles persist_world: several generation threads finishing at once would
        # otherwise each serialise the entire world back to disk.
        self._persist_lock = threading.Lock()
        self._last_persist = 0.0

        # Set by close() when the player leaves the game. Background generation threads
        # outlive the session (an LLM call can still be queued behind others), and the
        # save file is shared with whatever game is started next; without this they would
        # write a dead world's state over the new game's save.
        self.closed = False

        self.camp_rest_cooldowns = {
            poi_id: until for poi_id, until in self.save_system.load("camp_rest", {}).items() if until > time.time()
        }

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
        """Put a camp's occupants on the ground as its chunk loads.

        A bandit camp's garrison is a number, not a set of entities: the first sighting rolls
        how many bandits live here, and from then on that count (and the leader's own flag) is
        the camp. Every chunk load stands the survivors back up around the fire, `_unload_chunk`
        takes them away again, and only a kill lowers the count, so walking off can never empty
        a camp and finding a hundred camps costs no more memory than finding one. They roll
        their kind as if the camp stood deeper into the wilds, so the cache behind them is
        worth the fight. A traveller camp instead gets its camper, a permanent NPC like any
        villager, spawned once for the whole save (`npc_spawned`)."""
        if poi.kind != "camp":
            return
        if poi.variant == "traveller":
            self._spawn_camper(poi)
            return
        if poi.looted:
            return
        if poi.guards_alive is None:
            poi.guards_alive = random.randint(c.PointsOfInterest.CAMP_GUARD_MIN, c.PointsOfInterest.CAMP_GUARD_MAX)
            poi.leader_alive = True

        spread = c.PointsOfInterest.CAMP_GUARD_SPREAD
        for i in range(poi.guards_remaining):
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(spread * 0.5, spread)
            x = poi.x + math.cos(angle) * distance
            y = poi.y + math.sin(angle) * distance
            leader = poi.leader_alive and i == poi.guards_remaining - 1
            guard = self._new_monster(x, y, danger_bonus=c.PointsOfInterest.CAMP_LEADER_DANGER_BONUS if leader else 0)
            guard.camp_id = poi.id
            guard.camp_leader = leader
            self.monsters.append(guard)

    def on_guard_killed(self, monster: Monster):
        """Strike a fallen bandit off its camp's roll, which is what decides whether the cache
        opens and how many stand there when the chunk next loads."""
        poi = next((p for p in self.pois if p.id == monster.camp_id), None)
        if poi is not None:
            poi.guard_killed(monster.camp_leader)
            self.poi_state[poi.id] = poi.state()
            return
        # The camp's chunk unloaded while this guard was still chasing the player: its POI
        # object is gone, so the saved state is the only copy left to edit.
        state = self.poi_state.get(monster.camp_id)
        if state is None:
            return
        if monster.camp_leader:
            state["leader_alive"] = False
        else:
            state["guards_alive"] = max(0, (state.get("guards_alive") or 0) - 1)

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
        """True when a camp is safe to loot and to rest at.

        Two conditions, and they answer different questions. A bandit camp's garrison has to
        have been killed (`guards_defeated`, a count that survives the guards themselves
        being unloaded), which is what makes the cache the reward for taking the camp rather
        than for walking away and back. And whatever the camp, nothing hostile may be standing
        near the fire right now, so a wandering wolf still stops the player resting mid-fight."""
        if poi.variant == "bandit" and not poi.guards_defeated:
            return False
        return not any(
            entity.distance_to_point((poi.x, poi.y)) < c.PointsOfInterest.CAMP_CLEAR_RADIUS
            for entity in self.monsters + self.bosses
        )

    def camp_in_reach(self, player: Player) -> PointOfInterest | None:
        """The campfire the player could rest at right now: near enough, still burning, and
        with nothing hostile around it. A fire still on its cooldown is offered anyway, so
        the prompt can say why nothing happens rather than silently vanishing."""
        pos = player.get_pos()
        camps = [
            poi
            for poi in self.pois
            if poi.has_fire
            and poi.distance_to_point(pos) < c.PointsOfInterest.REST_DISTANCE
            and self.camp_is_clear(poi)
        ]
        return min(camps, key=lambda poi: poi.distance_to_point(pos), default=None)

    def camp_rest_ready_in(self, poi: PointOfInterest) -> float:
        """Seconds until this fire will serve the player again; 0 when it's ready now."""
        return max(0.0, self.camp_rest_cooldowns.get(poi.id, 0.0) - time.time())

    def rest_at_camp(self, player: Player, poi: PointOfInterest):
        """Sit at a camp's fire: some health back, and the post-death weakness shaken off.

        Not a full heal and not repeatable: this particular fire goes cold on the player for
        REST_COOLDOWN_S afterwards. Otherwise any cleared camp is a health button to stand
        next to, and the walk back to town for a bed or a potion stops meaning anything.
        """
        remaining = self.camp_rest_ready_in(poi)
        if remaining > 0:
            if self.notify:
                self.notify(f"This fire has burned low. Usable again in {int(remaining) + 1}s", c.Colors.MUTED)
            return
        self.camp_rest_cooldowns[poi.id] = time.time() + c.PointsOfInterest.REST_COOLDOWN_S
        player.heal(player.max_hp * c.PointsOfInterest.REST_HEAL_FRAC)
        player.clear_death_debuff()
        play_sound("rest")
        get_particles().spawn_burst(poi.x + 40, poi.y + 12, (255, 170, 60), count=18, speed=3, life=700, size=4)
        if self.notify:
            self.notify("You rest at the fire. Some wounds close, nerves steadied.", (255, 190, 110))

    def provoke_village(self, npc: NPC) -> List[NPC]:
        """Turn a settlement on the player after one of its people is struck, returning
        everyone who just went hostile (so the caller can strike their quests off).

        Everyone whose home village this is drops what they were doing and comes for the
        player, their goodwill gone and any quest they were offering with it. Violence in
        town is a decision, not a stray click: the whole place remembers it, and nothing
        here ever calms them back down.
        """
        village = self.village_at(npc.x, npc.y)
        if village is None:
            # A camper or a wandering merchant out in the wilds has no village behind them.
            crowd = [npc]
        else:
            crowd = [other for other in self.npcs if village.contains_point(other.x, other.y)]

        newly_hostile = [other for other in crowd if not other.hostile]
        if not newly_hostile:
            return newly_hostile
        for other in newly_hostile:
            other.hostile = True
            other.affinity = c.Affinity.MIN
        if self.notify:
            name = village.name if village is not None and village.name else "The locals"
            self.notify(f"{name} turns on you!", c.Colors.RED)
        return newly_hostile

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
            "camp_rest": {poi_id: until for poi_id, until in self.camp_rest_cooldowns.items() if until > time.time()},
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
                # What crawls out after dark is what lives much deeper in the wilds.
                bonus = c.DayNight.NIGHT_DANGER_BONUS if self.daynight.is_night else 0
                self.monsters.append(self._new_monster(x, y, danger_bonus=bonus))
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

        player_pos = player.get_pos()

        # After dark everything hits harder and notices sooner, whenever it spawned: night
        # is a state of the world, not a property of the monsters standing in it.
        damage_mult = self.night_damage_mult()
        detection = c.World.DETECTION_RANGE * (c.DayNight.NIGHT_DETECTION_MULT if self.daynight.is_night else 1.0)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt).
        update_radius = detection + c.Player.SIZE
        for monster in self.monsters:
            if abs(monster.x - player.x) <= update_radius and abs(monster.y - player.y) <= update_radius:
                waypoint = self.chase_waypoint(monster, player, monster.kind.size / 2)
                monster.move(player, dt, self.blocked, waypoint, damage_mult, detection)
        self.fire_monster_shots(player, damage_mult)

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        # Camp guards are the exception: they hold a place rather than roam, and their camp
        # would look abandoned while its chunk is still loaded. They leave with the chunk
        # instead (see WorldStreaming._unload_chunk).
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
        if self.boss_roam_timer >= c.Boss.ROAM_CHECK_INTERVAL_MS:
            self.boss_roam_timer = 0.0
            self._maybe_spawn_roaming_boss(player)

        self.update_projectiles(player, quest_system, dt)

        for npc in self.npcs:
            # Only an angry villager actually closing on the player needs a route round
            # the houses; everyone else is wandering and steers for itself.
            chasing = npc.hostile and npc.distance_to_point(player_pos) <= c.Entities.NPC_HOSTILE_RANGE
            waypoint = self.chase_waypoint(npc, player, c.Entities.NPC_SIZE / 2) if chasing else None
            npc.update(player, dt, self.blocked, waypoint)

        for critter in self.critters:
            critter.update(player, dt, self.blocked)
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
        if roaming < c.World.NB_MONSTERS:
            self.respawn_timer += dt
            respawn_interval = c.World.RESPAWN_INTERVAL_MS
            if self.events.blood_night_active:
                respawn_interval /= c.Events.BLOOD_NIGHT_RESPAWN_MULT
            elif self.daynight.is_night:
                respawn_interval /= c.DayNight.NIGHT_RESPAWN_MULT
            if self.respawn_timer >= respawn_interval:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
