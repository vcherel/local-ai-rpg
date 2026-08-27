from __future__ import annotations

import math
import random
import threading
import time
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.daynight import DayNightCycle
from core.decals import get_decals
from core.utils import parse_world_context
from game.combat import WorldCombat
from game.entities.bomb import MINE, Bomb
from game.entities.boss import Boss
from game.entities.breakables import Breakable, generate_breakables
from game.entities.buildings import Building, set_active_buildings
from game.entities.critter import Critter, pick_critter_kind
from game.entities.entities import advance_impulse
from game.entities.items import AMMO_BUNDLE, Item
from game.entities.monsters import Monster, pick_monster_kind
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest
from game.entities.projectile import ARROW_COLOR, STONE_COLOR, Projectile
from game.entities.scenery import Scenery
from game.entities.traps import BearTrap
from game.entities.village import Village, generate_starting_world, register_world_sites, settlements_near_chunk
from game.events import EventSystem
from game.loot import roll_shop_stock
from game.navigation import Point, WorldNavigation
from game.places import WorldPlaces
from game.projectiles import WorldProjectiles
from game.streaming import WorldStreaming
from llm.llm_request_queue import generate_response_queued
from llm.merchant_system import generate_shop_inventories

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World(WorldCombat, WorldProjectiles, WorldStreaming, WorldPlaces, WorldNavigation):
    """The living world and everything standing in it.

    Four parts live in their own modules and are mixed in here: `WorldCombat`
    (game/combat.py) resolves every blow and its aftermath, `WorldStreaming`
    (game/streaming.py) generates the endless map around the player and names what it
    finds, `WorldPlaces` (game/places.py) is what the player can do at a place once they
    reach it (camps, fires, shrines, directions, theft), and `WorldNavigation`
    (game/navigation.py) is how anything gets from where it is to where it wants to be.
    All of them work on the entity lists this class owns; keeping them as one class is
    what lets `self.monsters` and friends stay the single source of truth, and what
    decides which file a new method belongs in is the job it does, not which object holds
    the data.

    What is left here is the state itself: the lists, the chunk indexes that say what is
    solid where, spawning and its caps, saving, and the per-frame `update`.
    """

    def __init__(self, save_system: SaveSystem, context_window: ContextMenu, notify):
        self._init_state()
        self.save_system = save_system
        self.context_window = context_window
        self.notify = notify
        # Read through the same guard the generation is: a save written before that guard
        # existed can hold a stray word where the lore should be, and it would otherwise be
        # written across the black on every launch for the rest of the playthrough.
        self.context = parse_world_context(self.save_system.load("context", None))
        # Whether the lore in hand is lore the model actually wrote, as against the fallback
        # a failed call leaves behind: only the real thing is ever written to the save.
        self._lore_generated = self.context is not None
        if not self._lore_generated:
            self.save_system.update("context", None)
        self.events = EventSystem(self, notify)
        self.daynight = DayNightCycle(self.save_system.load("daynight_elapsed_ms", 0.0))
        self._load_persisted_state()

        saved_npcs = self.save_system.load("npcs", None)
        if saved_npcs is not None:
            self._restore_saved_world(saved_npcs)
        else:
            self._create_new_world()
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

    def _init_state(self):
        """Every list, index and timer the world keeps, before anything is loaded or built."""
        self._init_terrain_state()
        self._init_entity_state()
        self._init_generation_state()

    def _init_terrain_state(self):
        """The ground and what is indexed about it: all of it streamed, none of it saved."""
        # Regenerated on the fly as the player explores; see _sync_chunks. Kept chunk by
        # chunk rather than in one list: there are a couple of hundred pebbles and flowers
        # per chunk and the renderer wants the handful of chunks it can see, not all of them.
        self.floor_details: dict[tuple[int, int], list] = {}
        # The wilderness: trees, rocks, grass, ponds and roads, streamed with the chunks
        # and never saved. Indexed by `_reindex_scenery` into what is drawn under the
        # entities, what is drawn with the props, and a fine grid of the solid ones for
        # `blocked`.
        self.scenery: list[Scenery] = []
        self._ground_by_chunk: dict = {}
        self._props_by_chunk: dict = {}
        self._scenery_by_cell: dict = {}
        self._water_by_cell: dict = {}
        self._loaded_chunks = set()
        # Chunks in range and not built yet, nearest first, a few per frame; see
        # `WorldStreaming._build_pending_chunks`.
        self._pending_chunks: list[tuple[int, int]] = []
        self._current_chunk = None
        self._last_reveal_cell = None

    def _init_entity_state(self):
        """Everything standing in the world, the indexes that find it, and the timers that
        keep the ground around the player populated."""
        self.items: list[Item] = []
        self.npcs: list[NPC] = []
        self.monsters: list[Monster] = []
        # Named, multi-phase bosses. Kept apart from monsters: they never despawn, don't
        # count toward the monster cap, and get their own update, health bar and rewards.
        self.bosses: list[Boss] = []
        self.buildings: list[Building] = []
        # Buildings (and village wells) bucketed by chunk, so a collision test looks at the
        # handful standing near a point instead of everything in every village ever found.
        self._buildings_by_chunk: dict = {}
        # The solid parts of a village that are not buildings: its well, and the palisade
        # and towers of a walled town.
        self._village_solids_by_chunk: dict = {}
        self.breakables: list[Breakable] = []
        # Bombs the player has thrown or laid. A grenade in the air and a mine waiting in
        # the grass are the same object at different points of its life (`game/entities/bomb.py`).
        self.bombs: list[Bomb] = []
        # When each body may next be pricked by a town's stakes (`WorldCombat.prick_spikes`),
        # by id. Session-only, like a projectile: nothing about standing in a ditch of
        # sharpened sticks is worth saving.
        self._spike_ready: dict[int, int] = {}
        # Everyone who was in the fight with the player last frame, by `id`. A villager
        # joins because the player came near them (`Villages.MOB_ENGAGE_RANGE`) and leaves
        # only at the far longer leash, so a mob is the street the player is standing in
        # rather than every angry person in the settlement. Session-only: who is swinging
        # right now is not something a save has any business remembering.
        self._engaged: set = set()
        # Every village generated so far. Unlike POIs these are kept, not regenerated: a
        # settlement's NPCs carry affinity, quests and shop stock that a chunk seed can't
        # rebuild. `village_site` still decides where they go, so the map itself is endless.
        self.villages: list[Village] = []
        # Only the POIs of the chunks currently loaded around the player; see _load_chunk.
        self.pois: list[PointOfInterest] = []
        # The hunters' bear traps of those same chunks, streamed and dropped with them. The
        # one thing a player changes about a trap is springing it, so that is all that is
        # saved (`trap_state`, by trap id), exactly like a POI.
        self.traps: list[BearTrap] = []
        # The tunnel the player is standing in, or None on the surface. A tunnel is ordinary
        # world space a long way from anywhere (game/entities/tunnel.py); this is what tells
        # the world to stop streaming ground, stop spawning wildlife and stop drawing a sky
        # while the player is down there. `tunnels` caches the ones built so far and
        # `tunnel_state` is what each of them has left (garrison, hoard), persisted.
        self.underground = None
        self.tunnels: dict = {}
        # Where the player climbed down from, so the ladder puts them back at that well.
        self.surface_return = None
        # Wandering wildlife, purely atmospheric; transient like particles, never saved.
        self.critters: list[Critter] = []
        # Arrows in flight; transient like particles, never saved.
        self.projectiles: list[Projectile] = []
        # Places a rumour pointed at, drawn on the minimap until the player gets there.
        # Session-only: a rumour is a lead to follow now, not a pin to keep forever.
        self.rumor_marks: list[dict] = []
        self.respawn_timer = 0.0
        self.critter_respawn_timer = 0.0
        self.boss_roam_timer = 0.0

    def _init_generation_state(self):
        """What keeps the background threads from treading on each other and on the save."""
        # Generation guards: a merchant with no shop yet, an unnamed landmark or an unnamed
        # village would otherwise be picked up again by every path that checks, queueing a
        # duplicate call while the first one is still in flight.
        self._shops_generating = False
        self._landmark_naming = False
        self._naming_villages: set = set()
        # Counts down to the next look around for a settlement worth preparing; see
        # `WorldStreaming._prepare_settlements_near`. Nothing here is urgent to the frame.
        self._prepare_timer = 0.0

        # Throttles persist_world: several generation threads finishing at once would
        # otherwise each serialise the entire world back to disk.
        self._persist_lock = threading.Lock()
        self._last_persist = 0.0

        # Set by close() when the player leaves the game. Background generation threads
        # outlive the session (an LLM call can still be queued behind others), and the
        # save file is shared with whatever game is started next; without this they would
        # write a dead world's state over the new game's save.
        self.closed = False

    def _load_persisted_state(self):
        """The parts of the world the save owns outright: what the player did to a POI or a
        trap, what is left of each tunnel, where they have walked and what they have used."""
        # When each place the player rests will serve them again, by POI id for a campfire
        # and by building id for a villager's bed (wall-clock seconds, so quitting to the
        # menu can't reset a fire or a bed the player just used). One that has come round
        # again is dropped rather than loaded.
        self.rest_cooldowns = {
            key: until for key, until in self.save_system.load("camp_rest", {}).items() if until > time.time()
        }
        # What the player did to a POI (looted, discovered, camper spawned), by POI id.
        # Everything else about a POI comes back from its chunk seed, so this is all that
        # needs saving.
        self.poi_state = self.save_system.load("pois", {})
        self.trap_state = self.save_system.load("traps", {})
        # Which trees the player has cut down, as "cx:cy:index" keys. The one thing about
        # the wilderness the world remembers: everything else in a chunk is rolled from its
        # seed, so a felled tree has to be a player change kept beside the POI state rather
        # than something the generator could ever know.
        self.felled = set(self.save_system.load("felled", []))
        # And which boulders they have broken open, keyed exactly the same way. A second
        # set rather than a second meaning for the first: a stump and a pile of rubble are
        # laid back over a regenerated chunk by different calls, and one list of "things
        # the player wrecked" would have to be told which was which anyway.
        self.smashed = set(self.save_system.load("smashed", []))
        # Mines are left lying where the player laid them, so walking back to one you set
        # last night is a real thing to do. A grenade is in the air and is never saved.
        self.bombs = [Bomb.from_dict(d) for d in self.save_system.load("bombs", [])]
        # How much patience each settlement has left with the player, by village key and by
        # what the player did: {"cx:cy": {"assault": {"count": int, "at": seconds}}}. A
        # village warns before it turns (`WorldPlaces.strike_village`), once per kind of
        # offence, and the warning has to survive a save the way the anger it leads to does,
        # or quitting would be a way of starting over on a clean slate. Strikes older than
        # the window are dropped rather than loaded.
        self.village_strikes = self._load_strikes(self.save_system.load("village_strikes", {}))
        self.tunnel_state = self.save_system.load("tunnels", {})
        # Grid cells the player has walked through (Fog.CELL wide), the memory the minimap
        # draws; everything outside it stays black.
        self.explored = {
            tuple(int(part) for part in key.split(":")) for key in self.save_system.load("explored", []) if ":" in key
        }

    def _restore_saved_world(self, saved_npcs):
        self._restore(saved_npcs)
        # Before a single chunk is generated: the starting town was rolled per playthrough
        # rather than out of a region, so nothing laid out from the village sites knows it
        # is there until this puts it back on the map (game/entities/village.py).
        register_world_sites(self.villages, self.buildings)
        self._plan_streets()
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
            if village.defended and not any(npc.is_guard and village.contains_point(npc.x, npc.y) for npc in self.npcs):
                self._post_guards(village)
        self._light_windows()

    def _light_windows(self):
        """Tell every building which settlement's tier lights its windows after dark.

        Set on the buildings a village is laid out with (`village._build`), so this is only
        ever the loaded ones: which village a saved house belongs to is a fact about where
        it stands, not something worth a key in the save."""
        for building in self.buildings:
            village = self.village_at(building.x, building.y)
            building.village_tier = village.tier if village is not None else -1

    def _create_new_world(self):
        village, buildings = generate_starting_world()
        self.villages = [village]
        self.buildings = buildings
        self._index_buildings()
        set_active_buildings(self.buildings)
        self.breakables = generate_breakables(self.buildings)
        self._plan_streets()
        self._populate_npcs(self.buildings, village)
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

    def _populate_npcs(self, buildings: list[Building], village: Village | None = None):
        """Fill one village with people: a merchant standing at each shop, and a villager or
        more living at every house and tavern. Called for the starting town and again for each
        village the player finds, so a settlement is never an empty film set.

        How many of them there are and how much they can take both come off the settlement,
        never off what they are holding: a farmer's hoe is a farmer's hoe wherever it is
        swung, and a deep wilds town is dangerous because there are more of them, they are
        harder to put down and there is a wall between you and them."""
        for shop in (b for b in buildings if b.kind == "shop"):
            npc = NPC(*shop.door_front())
            npc.is_merchant = True
            npc.color = c.Colors.MERCHANT
            self._set_toughness(npc, village)
            self.npcs.append(npc)

        size = village.size if village is not None else "village"
        per_home = c.Villages.VILLAGERS_PER_HOME_BY_SIZE.get(size, c.Villages.VILLAGERS_PER_HOME)
        for home in (b for b in buildings if b.kind in ("house", "tavern")):
            door_x, door_y = home.door_front()
            for _ in range(random.randint(*per_home)):
                npc = NPC(door_x + random.randint(-80, 80), door_y + random.randint(0, 80))
                npc.home = (door_x, door_y)
                self._set_toughness(npc, village)
                self.npcs.append(npc)

    @staticmethod
    def _set_toughness(npc: NPC, village: Village | None):
        """What one villager is worth in a fight: their settlement's tier, and whether they
        are the one who takes up arms for it. The only place a villager's health is set."""
        npc.defence_tier = village.tier if village is not None else 0
        mult = c.Villages.HP_BY_TIER[npc.defence_tier]
        if npc.is_guard:
            mult *= c.Villages.GUARD_HP_MULT
        elif npc.is_militia:
            mult *= c.Villages.MILITIA_HP_MULT
        npc.max_hp = round(c.Entities.NPC_HP * mult)
        npc.hp = npc.max_hp

    def _post_guards(self, village: Village):
        """Stand somebody at every gate and every tower of a walled town.

        A guard is an ordinary villager with three differences, all of them already meant
        something elsewhere: they always take up arms (`NPC.is_militia`), they carry a real
        weapon rather than a tool, and they hold their post instead of strolling the street.
        That is enough for the militia orders, the mob and the surround slots to treat them
        like anyone else. How many stand there and what they hold is the settlement's tier;
        from tier 1 the towers hold archers, who shoot over the wall rather than coming down
        off it (`_loose_arrows`)."""
        defences = village.defences()
        tier = village.tier
        per_post = c.Villages.GUARDS_PER_POST_BY_TIER[tier]
        archers = c.Villages.ARCHERS_PER_TOWER_BY_TIER[tier]

        def post(x, y, archer: bool):
            # An archer is posted *on* the tower, which is solid ground to everything else:
            # the top of it is where they stand, so their spot is the tower itself rather
            # than the first clear pixel around it. That search is what used to put them
            # outside their own wall, shooting at a player standing inside it. Nothing else
            # about them moves either (`World._update_npcs` skips them), so nothing ever
            # walks them off the post.
            spot = (x, y) if archer else self.free_spot_near(x, y, c.Entities.NPC_SIZE / 2)
            guard = NPC(*spot)
            guard.is_guard = True
            guard.is_archer = archer
            guard.home = spot
            guard.color = c.Villages.GUARD_COLOR
            guard.wander.radius = 0 if archer else c.Villages.GUARD_POST_RADIUS
            self._set_toughness(guard, village)
            self.npcs.append(guard)

        for gate in defences["gates"]:
            for _ in range(per_post):
                post(*gate["pos"], archer=False)
        for tower in defences["towers"]:
            # Several bodies on one roof would stack on the same pixel, so the ones after the
            # first stand a step round the parapet from each other.
            for index in range(max(per_post, archers)):
                archer = index < archers
                if not archer:
                    post(*tower, archer=False)
                    continue
                bearing = 2 * math.pi * index / max(1, archers)
                offset = village.tower_radius * c.Villages.TOWER_STAND_FRAC
                post(tower[0] + math.cos(bearing) * offset, tower[1] + math.sin(bearing) * offset, archer=True)
        # And, on the best defended walls, somebody standing on each stretch: four corners
        # cover a small settlement and nothing like the length of a town's wall.
        for wall in defences["walls"]:
            for _ in range(c.Villages.ARCHERS_PER_WALL_BY_TIER[tier]):
                if max(wall.width, wall.height) < c.Villages.GATE_WIDTH:
                    continue  # a gatehouse block, not a stretch worth standing on
                # Standing on the wall means standing just inside it: the middle of the
                # stretch is solid, and a free spot searched for from there is as likely to
                # be found outside the town as in it.
                inward = math.hypot(village.x - wall.centerx, village.y - wall.centery) or 1.0
                step = village.wall_thickness + c.Entities.NPC_SIZE
                post(
                    wall.centerx + (village.x - wall.centerx) / inward * step,
                    wall.centery + (village.y - wall.centery) / inward * step,
                    archer=True,
                )

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
        if self._lore_generated:
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
        # And a cave's warden is not saved for the same reason: it is a flag on its tunnel,
        # and `_populate_cave` stands it back up from that whenever anyone walks back in.
        bosses = [boss for boss in self.bosses if not boss.camp_id]
        return {
            "items": [item.to_dict() for item in self.items],
            "npcs": [npc.to_dict() for npc in npcs],
            "monsters": [monster.to_dict() for monster in monsters],
            "bosses": [boss.to_dict() for boss in bosses],
            "buildings": [building.to_dict() for building in self.buildings],
            "villages": [village.to_dict() for village in self.villages],
            "breakables": [breakable.to_dict() for breakable in self.breakables],
            "pois": self._poi_state_snapshot(),
            "traps": self._trap_state_snapshot(),
            "felled": sorted(self.felled),
            "smashed": sorted(self.smashed),
            "bombs": [bomb.to_dict() for bomb in self.bombs if bomb.kind == MINE],
            "tunnels": self._tunnel_state_snapshot(),
            "underground": (
                None
                if self.underground is None
                else {"id": self.underground.id, "return": list(self.surface_return or self.underground.entrance)}
            ),
            "camp_rest": {key: until for key, until in self.rest_cooldowns.items() if until > time.time()},
            "village_strikes": self.village_strikes,
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
            bucket(self._buildings_by_chunk, building.bounds, building)
        for village in self.villages:
            # A walled town is solid all the way out to its palisade, so it is bucketed by
            # the whole ring rather than by the well in the middle of it.
            reach = village.grounds_radius if village.defended else c.Villages.WELL_RADIUS
            footprint = pygame.Rect(0, 0, reach * 2, reach * 2)
            footprint.center = (round(village.x), round(village.y))
            bucket(self._village_solids_by_chunk, footprint, village)

    def _register_buildings(self, buildings: list[Building]):
        """Add a newly generated village's buildings to the world and the lookup index."""
        self.buildings.extend(buildings)
        self._index_buildings()
        set_active_buildings(self.buildings)

    def buildings_near(self, x, y) -> list[Building]:
        """The buildings whose footprint can reach (x, y)."""
        return self._buildings_by_chunk.get(self._chunk_of(x, y), [])

    def buildings_in_range(self, x, y, radius) -> list[Building]:
        """Every building in the chunks covering the box of `radius` around (x, y). For
        callers working over an area (a swing's reach, a detour, the map) rather than a point."""
        found = {}
        for chunk in self._chunk_window(x, y, radius):
            for building in self._buildings_by_chunk.get(chunk, ()):
                found[building.id] = building
        return list(found.values())

    def blocked(self, x, y, radius) -> bool:
        """Is something solid standing here? The test everything on the ground moves by.

        A settlement's palisade is the one solid this asks about that `blocked_over_walls`
        does not, so it is checked here and the rest of the world is left to that one.
        """
        # Underground there is no settlement to have a wall, and the palisade check would
        # be looking at a chunk index nothing down there is registered in.
        if self.underground is None:
            solids = self._village_solids_by_chunk.get(self._chunk_of(x, y), ())
            if any(village.blocks(x, y, radius) for village in solids):
                return True
        return self.blocked_over_walls(x, y, radius)

    def on_building(self, x, y, radius: float = 0.0) -> bool:
        """Whether this spot is on any part of a building, its floor included.

        `blocked` answers False inside a room, which is the right answer for something
        walking about in one and the wrong one for anything being *placed*: it is what put
        a village dog on a roof and a deer in a bedroom."""
        return any(building.covers(x, y, radius) for building in self.buildings_near(x, y))

    def blocked_over_walls(self, x, y, radius) -> bool:
        """`blocked` for something flying above a town's wall: houses, trees and boulders
        still stop it, the palisade and its towers do not. The one thing that reads this is
        an arrow loosed from a tower, and the archer's own sight test before it.

        Also the whole of `blocked` bar the palisade, so the two never drift apart."""
        # Underground the answer is the rock, and nothing else: a tunnel is carved out of a
        # part of the world no chunk ever streams into, so there is nothing else down there
        # to collide with.
        if self.underground is not None:
            return self.underground.blocks(x, y, radius)
        if any(building.blocks(x, y, radius) for building in self.buildings_near(x, y)):
            return True
        return any(item.blocks(x, y, radius) for item in self.scenery_near(x, y))

    def _chunk_window(self, x, y, radius) -> list[tuple[int, int]]:
        """Every chunk covering the box of `radius` around (x, y). The one place that walk
        is written, shared by the building lookup and by the scenery the renderer asks for."""
        size = c.World.CHUNK_SIZE
        return [
            (cx, cy)
            for cx in range(int((x - radius) // size), int((x + radius) // size) + 1)
            for cy in range(int((y - radius) // size), int((y + radius) // size) + 1)
        ]

    def floor_details_in_range(self, x, y, radius):
        """The pebbles and flowers scattered over the ground around a point."""
        for chunk in self._chunk_window(x, y, radius):
            yield from self.floor_details.get(chunk, ())

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

    def scenery_near(self, x, y) -> list[Scenery]:
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
        and never gets better at it, which is the whole reason a river is worth crossing.

        A town's ditch is the same idea dug by hand: it costs an approach its speed under
        the archers on the wall, and it never stops anyone, so a gate is still the fast way
        in rather than the only one."""
        if self.water_at(x, y):
            return c.Scenery.SWIM_SPEED
        for village in self._village_solids_by_chunk.get(self._chunk_of(x, y), ()):
            if village.in_ditch(x, y):
                return c.Villages.DITCH_SPEED
        return 1.0

    def quest_target_spot(self, x, y) -> tuple[float, float]:
        """Where to put whatever a quest sends the player after, given where it was handed
        over: open ground a real walk away (`Quests.MIN_TARGET_DISTANCE`), out of any
        settlement and out of the water.

        The chunk it lands in has almost certainly never been loaded, so most of what is
        asked here can only answer for the ground already streamed in. That is the point:
        the far ground is empty until it is generated, and a quest item lying in it is
        picked up off whatever grows there later."""
        best = (x, y)
        for _ in range(40):
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(c.Quests.MIN_TARGET_DISTANCE, c.Quests.MAX_TARGET_DISTANCE)
            tx, ty = x + math.cos(angle) * distance, y + math.sin(angle) * distance
            best = (tx, ty)
            if self.village_at(tx, ty, c.World.VILLAGE_SPAWN_MARGIN) is not None:
                continue
            if self.building_at(tx, ty) is not None or self.water_at(tx, ty):
                continue
            if not self.blocked(tx, ty, c.Entities.ITEM_SIZE):
                return tx, ty
        return best

    @staticmethod
    def _load_strikes(saved: dict) -> dict:
        """The warning ledger as it comes off disk, with anything the window has outlived
        dropped rather than loaded.

        A save written before warnings were counted per offence holds one counter per
        settlement ({"count", "at"}); it loads as a warning for violence, which is what that
        counter always was in practice."""
        ledgers: dict = {}
        now = time.time()
        for key, record in saved.items():
            if "count" in record:
                record = {c.Villages.DEFAULT_OFFENCE: record}
            ledger = {
                offence: entry
                for offence, entry in record.items()
                if now - entry.get("at", 0) < c.Villages.STRIKE_WINDOW_S
            }
            if ledger:
                ledgers[key] = ledger
        return ledgers

    @staticmethod
    def ring_search(x, y, step: float, rings: int, accept) -> tuple[float, float] | None:
        """Walk outward from (x, y) in rings of eight points per ring, `step` apart, and give
        back the first point `accept` says yes to. None when the whole search comes up empty.

        The one definition of "somewhere near here that will do", shared by every placement
        in the world: a body stepping out of a wall, the player being put down clear of what
        killed them, a guardian standing as near its ruin as it is allowed to. What differs
        between them is only what counts as a good spot, which is what `accept` carries.
        """
        for ring in range(1, rings + 1):
            distance = ring * step
            for index in range(ring * 8):
                angle = 2 * math.pi * index / (ring * 8)
                cx, cy = x + math.cos(angle) * distance, y + math.sin(angle) * distance
                if accept(cx, cy):
                    return cx, cy
        return None

    def free_spot_near(self, x, y, radius, rings: int | None = None) -> tuple[float, float]:
        """The nearest standable point to (x, y), which may be (x, y) itself.

        The spawn point is a fixed world coordinate while the starting town is laid out
        around a random centre near it, so the two overlap often; the same is true of any
        village generated later. Rather than move the settlement, whoever is being placed
        steps out to the first clear spot around it.

        `rings` caps how far out the search goes, for a caller who wants a body put back on
        the open ground it is standing in rather than moved to wherever there is room."""
        if not self.blocked(x, y, radius):
            return x, y
        found = self.ring_search(
            x, y, radius * 2, rings or c.World.FREE_SPOT_MAX_RINGS, lambda cx, cy: not self.blocked(cx, cy, radius)
        )
        # Walled in on every side within the search: leave the caller where they were
        # rather than teleporting them somewhere arbitrary.
        return found or (x, y)

    def advance_impulses(self, player: Player, dt):
        """Spend one frame of every shove in flight: the monsters, the bosses, the villagers,
        the wildlife and the player.

        A blow hands its target a velocity rather than a new position (`WorldCombat._knockback`),
        which is what makes a pole's shove a thing that visibly happens rather than a body
        appearing at the far end of the room. Nothing here knows what did the shoving."""
        for body, radius in self.bodies(player):
            advance_impulse(body, dt, radius, self.blocked)

    def bodies(self, player: Player) -> list:
        """Everything standing in the world with a size, as (body, radius) pairs. The one
        walk over all of them, shared by the shoves in flight and by anything that has to
        know who is in the way of a leaf about to shut."""
        return (
            [(m, m.kind.size / 2) for m in self.monsters]
            + [(b, b.kind.size / 2) for b in self.bosses]
            + [(n, c.Entities.NPC_SIZE / 2) for n in self.npcs]
            + [(cr, cr.size / 2) for cr in self.critters]
            + [(player, c.Player.SIZE / 2)]
        )

    def unstick(self, body, radius: float) -> bool:
        """Put a body that has ended up inside something solid back onto open ground.

        Everything on legs tests `blocked` at the point it wants to step *to*, so one that
        is already inside a wall has every step refused and stays there for good: a villager
        a new village was built on top of, a monster shouldered into a tower by the crowd
        behind it, anything caught by a door shutting on it. This is the one answer to that,
        shared by the player, the villagers, the monsters and the wildlife, and the search is
        deliberately short (`World.UNSTICK_RINGS`) so a body steps out of what it is in
        rather than being moved through it."""
        if not self.blocked(body.x, body.y, radius):
            return False
        body.x, body.y = self.free_spot_near(body.x, body.y, radius, rings=c.World.UNSTICK_RINGS)
        return True

    def hostiles_near(self, x, y, radius: float) -> list:
        """Everything within `radius` of (x, y) that would attack the player: monsters,
        bosses, villagers who have turned, and animals currently hunting."""
        near = []
        near += [m for m in self.monsters if m.distance_to_point((x, y)) <= radius]
        near += [b for b in self.bosses if b.distance_to_point((x, y)) <= radius]
        near += [n for n in self.npcs if n.hostile and n.distance_to_point((x, y)) <= radius]
        near += [cr for cr in self.critters if cr.hostile and cr.distance_to_point((x, y)) <= radius]
        return near

    def safe_spot_near(self, x, y, radius, clearance: float | None = None) -> tuple[float, float]:
        """Where to put the player: `free_spot_near` knows only about geometry, and a point
        with no wall in it is not safe if whatever killed the player is standing on it. Same
        outward ring search, with candidates holding anything hostile within `clearance`
        rejected as well, falling back to the geometric answer when the search finds nowhere
        clear (better a rough spawn than a hang)."""
        clearance = c.World.SAFE_SPOT_CLEARANCE if clearance is None else clearance

        def clear(cx, cy) -> bool:
            return not self.blocked(cx, cy, radius) and not self.hostiles_near(cx, cy, clearance)

        if clear(x, y):
            return x, y
        found = self.ring_search(x, y, radius * 2, c.World.FREE_SPOT_MAX_RINGS, clear)
        return found or self.free_spot_near(x, y, radius)

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

    # ------------------------------------------------------------------ bosses

    def spawn_boss(
        self,
        x,
        y,
        template: c.BossKind = None,
        quest_tag: str | None = None,
        announce: str | None = None,
        name: str = "",
    ) -> Boss:
        """Create a boss, register it, and kick off LLM naming. `announce`, if given, is a
        message template shown once the name is ready (use '{name}' for the boss's name).

        `name` is one that has already been generated: a cave's warden is stood back up
        every time anybody walks down to its vault, and asking the model to rename the same
        creature on every visit would be a call a session for a name nobody wanted changed."""
        boss = Boss(x, y, template or random.choice(c.BOSS_KINDS), quest_tag=quest_tag)
        self.bosses.append(boss)
        if name:
            boss.set_identity(name)
        elif self.context:
            threading.Thread(target=self._generate_boss_identity, args=(boss, announce), daemon=True).start()
        return boss

    def boss_spawn_ok(self, x, y) -> bool:
        """Whether a boss may be stood up here. Every way one is spawned asks this: a boss
        never despawns, so anywhere it lands is somewhere it stays.

        A settlement is not one of those places, and neither is the ground the player starts
        on. A monster wandering into a village is a fight the militia can have; a boss
        standing in the plaza of the first town is the run over before it started.

        Distance from a settlement is measured off its grounds and against the site registry
        rather than the villages built so far, because a village a chunk away has not been
        generated yet and a boss put down next to where one is going to stand is the same
        mistake made a minute later. The world's own spawn margin is what keeps a wolf out
        of the fields; a boss is held the far side of them (`Boss.MIN_DIST_FROM_VILLAGE`)."""
        center = c.World.WORLD_SIZE // 2
        if math.hypot(x - center, y - center) < c.Boss.MIN_DIST_FROM_START:
            return False
        if self.settlement_distance(x, y) < c.Boss.MIN_DIST_FROM_VILLAGE:
            return False
        if self.building_at(x, y) is not None:
            return False
        return not self.blocked(x, y, c.MONSTER_MAX_SIZE)

    @staticmethod
    def settlement_distance(x, y) -> float:
        """How far (x, y) lies past the grounds of the nearest settlement, asked of the sites
        rather than of the villages built so far: a town three chunks out has not been
        generated yet and is no less somewhere people live. Infinite where there is nothing
        within reach at all."""
        size = c.World.CHUNK_SIZE
        chunk = (int(x // size), int(y // size))
        # The clearance in chunks, plus two for the largest grounds a town can have.
        reach = math.ceil(c.Boss.MIN_DIST_FROM_VILLAGE / size) + 2
        nearest = float("inf")
        for site_x, site_y, _, _, radius in settlements_near_chunk(*chunk, reach):
            nearest = min(nearest, math.hypot(x - site_x, y - site_y) - radius)
        return nearest

    def wild_bosses(self) -> int:
        """How many of the bosses standing in the world count towards the cap: the ones that
        are the wilds' own population rather than fixtures put somewhere for a reason
        (`Boss.counts_against_cap`)."""
        return sum(1 for boss in self.bosses if boss.counts_against_cap)

    def boss_cap(self, player: Player) -> int:
        """How many bosses the world holds at once around the player: one on the settled
        ring, up to `Boss.MAX_ACTIVE_FAR` out in the deep wilds. The same shape as the
        roaming monster cap and for the same reason. Difficulty is how many there are and
        which kinds they are, never what one of them is made of."""
        near, far = c.Boss.MAX_ACTIVE_NEAR, c.Boss.MAX_ACTIVE_FAR
        return round(near + (far - near) * self._danger_ratio(player))

    @staticmethod
    def _danger_ratio(player: Player) -> float:
        """Where the player stands between the settled ring and the deep wilds, 0 to 1."""
        center = c.World.WORLD_SIZE // 2
        distance = math.hypot(player.x - center, player.y - center)
        span = max(c.Boss.DENSITY_FAR_DISTANCE - c.Boss.ROAM_MIN_DISTANCE, 1)
        return min(max((distance - c.Boss.ROAM_MIN_DISTANCE) / span, 0.0), 1.0)

    def _spawn_landmark_boss(self):
        """A guardian waits at the ruined landmark from the very first world. It's named
        later, once the world context has finished generating.

        It goes through `boss_spawn_ok` like every other boss: the ruin is placed clear of
        the starting town, but "clear" for a building is a few hundred paces and "clear" for
        a boss is the far side of the fields, and this one is standing there from the first
        frame of the save."""
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None:
            return
        # In front of the ruin if that is allowed, and otherwise as near to it as a boss may
        # legally stand: the guardian belongs to the landmark, and the clearance it is held
        # to is measured from a settlement rather than from the stone it guards.
        spot = self._guardian_spot(landmark)
        if spot is not None:
            # It belongs to the ruin and it never leaves it, so it is not one of the bosses
            # the wilds are counted to hold around the player.
            self.spawn_boss(*spot).fixture = True

    def _guardian_spot(self, landmark: Building) -> tuple[float, float] | None:
        front = (landmark.x, landmark.y + landmark.h / 2 + 90)
        if self.boss_spawn_ok(*front):
            return front
        step = max(landmark.w, landmark.h) / 2 + 90
        return self.ring_search(landmark.x, landmark.y, step, c.Boss.GUARDIAN_SEARCH_RINGS, self.boss_spawn_ok)

    def spawn_boss_for_quest(self) -> Boss:
        """Spawn a boss out in the dangerous outer wilds as a quest hunt target.

        The band starts at `Boss.QUEST_SPAWN_MIN_DISTANCE`, well past where roaming ones
        begin, and runs outward from there. The world has no edge, so it is deliberately not
        clamped to the settled ring: hunting one is meant to be a walk past everything the
        player already knows.
        """
        center = c.World.WORLD_SIZE // 2
        x = y = center
        for _ in range(20):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(
                c.Boss.QUEST_SPAWN_MIN_DISTANCE, c.Boss.QUEST_SPAWN_MIN_DISTANCE + c.Boss.QUEST_SPAWN_BAND
            )
            x = center + math.cos(angle) * dist
            y = center + math.sin(angle) * dist
            if self.boss_spawn_ok(x, y):
                break
        # A boss never despawns, so unlike a monster it can't be left standing in a wall
        # if every roll was blocked: whatever came out of the loop is stepped clear first.
        x, y = self.free_spot_near(x, y, c.MONSTER_MAX_SIZE)
        tag = f"quest_boss_{random.randint(1000, 9999)}"
        return self.spawn_boss(x, y, quest_tag=tag)

    def _generate_boss_identity(self, boss: Boss, announce: str | None = None):
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
        if self.wild_bosses() >= self.boss_cap(player):
            return
        center = c.World.WORLD_SIZE // 2
        if math.hypot(player.x - center, player.y - center) < c.Boss.ROAM_MIN_DISTANCE:
            return
        ratio = self._danger_ratio(player)
        chance = c.Boss.ROAM_CHANCE_NEAR + (c.Boss.ROAM_CHANCE_FAR - c.Boss.ROAM_CHANCE_NEAR) * ratio
        chance *= c.DayNight.NIGHT_BOSS_ROAM_MULT if self.daynight.is_night else 1.0
        if random.random() > chance:
            return
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_SPAWN_MIN_DIST, c.Boss.ROAM_SPAWN_MAX_DIST)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if self.boss_spawn_ok(x, y):
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
            npc.add_stock(roll_shop_stock(missing, luck=npc.stock_luck) if missing > 0 else [])

    def start_shop_generation(self, merchants: list | None = None):
        """Stock the given merchants, in a single background call.

        `merchants` is the shortlist the caller wants filled: the shops of a settlement the
        player is walking up to (`_prepare_settlements_near`) or the one merchant an event
        has just put on the road. Passing nothing stocks every merchant still waiting, which
        is a whole world's worth of calls and is only what a caller standing in front of all
        of them would want."""
        if merchants is None:
            merchants = [npc for npc in self.npcs if npc.is_merchant and not npc.shop_ready]
        merchants = [npc for npc in merchants if npc.is_merchant and not npc.shop_ready]
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
            # Nothing is stood up on somebody's floor: `blocked` says nothing about a room,
            # since a wall is solid and the boards inside it are not.
            if self._spawn_is_sheltered(x, y) or self.building_at(x, y) is not None:
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
                    indoors = self.building_at(mate_x, mate_y) is not None
                    if not indoors and not self.blocked(mate_x, mate_y, leader.kind.size / 2):
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
            # Nothing wild is stood up in somebody's front room either, nor on the roof
            # of the back half of an L: the floor of a house is not blocked ground, so the
            # question is what the footprint covers rather than what stops a body.
            if self.blocked(x, y, kind.size / 2) or self.on_building(x, y, kind.size / 2):
                continue
            for _ in range(random.randint(*kind.group)):
                spread = c.Wildlife.GROUP_SPREAD
                mate_x = x + random.uniform(-spread, spread)
                mate_y = y + random.uniform(-spread, spread)
                indoors = self.on_building(mate_x, mate_y, kind.size / 2)
                if not indoors and not self.blocked(mate_x, mate_y, kind.size / 2):
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
            size = c.CRITTER_KINDS_BY_NAME["dog"].size / 2
            for _ in range(wanted - len(living)):
                # A dog lives in the street, not in the tavern: the spot is rolled again
                # rather than settled for when it lands on somebody's floor, and a village
                # that has no room for another dog simply keeps the ones it has.
                spot = None
                for _attempt in range(8):
                    angle = random.uniform(0, 2 * math.pi)
                    distance = random.uniform(village.radius * 0.15, village.radius * 0.5)
                    x, y = self.free_spot_near(
                        village.x + math.cos(angle) * distance,
                        village.y + math.sin(angle) * distance,
                        size,
                    )
                    if not self.on_building(x, y, size):
                        spot = (x, y)
                        break
                if spot is None:
                    continue
                x, y = spot
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
        """Who this monster is coming for. The player, unless somebody else is nearer and it
        can actually get at them: a villager is prey, not scenery to be filed past.

        It used to take a settlement's grounds to make one worth eating, which left the
        woman standing twenty paces outside her own gate ignored by the wolf beside her while
        it walked round her at the player. So the test is reach and sight instead: anyone
        inside `Villages.DEFEND_RADIUS`, nearer than the player, and not behind a wall.
        Villagers who are already down (`NPC.surrendered`) are as good a target as any: a
        monster is not owed a surrender.

        A camp guard is left out of it. It holds a piece of ground rather than raiding, and
        a garrison drifting off to fight the nearest farmer would empty its own camp. So is
        anything still in a disguise: what it is wearing is worn for the player's benefit,
        and a husk that threw its villager off at a passing farmer would spend the one
        moment it has on somebody who was never going to be surprised by it."""
        if monster.camp_id or not monster.revealed or not self.npcs:
            return player
        reach = min(monster.distance_to_point(player.get_pos()), c.Villages.DEFEND_RADIUS)
        near = sorted(
            (npc for npc in self.npcs if monster.distance_to_point((npc.x, npc.y)) < reach),
            key=lambda npc: monster.distance_to_point((npc.x, npc.y)),
        )
        # Sight is walked step by step, so it is asked about the nearest few and no further:
        # anyone behind three other people is not the one this thing is going to eat.
        for npc in near[: c.Villages.MONSTER_PREY_TRIES]:
            if self.line_of_sight(monster.x, monster.y, npc.x, npc.y):
                return npc
        return player

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
            source=monster,
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
        mob = self._mob_orders(player, flee, quest_system)
        # An archer is in the orders so `_loose_arrows` knows what they are shooting at, but
        # never in the crowd: a body on a tower roof is not one of the ring of people pushing
        # in around the player, and being shouldered by that ring is what walked them off it.
        crowd = [npc for npc in self.npcs if id(npc) in mob and not npc.is_archer]
        all_home = self._households_in(mob) if self.daynight.curfew else frozenset()
        defenders = [npc for npc in self.npcs if id(npc) in fight]
        self.assign_surround_slots(crowd, player)
        self._throw_stones(player, mob)
        self._work_gates(player, dt)
        self._loose_arrows(fight, mob, player)

        for npc in self.npcs:
            if npc.is_archer:
                # Posted on a tower roof, which is solid ground: never unstuck off it, never
                # walked off it, never pushed off it. All they do is aim and loose
                # (`_loose_arrows`), so the frame is run with nothing to walk to.
                npc.update(player, dt, self.blocked, face_player=False)
                continue
            # Anything standing inside a solid is put back on open ground before it tries to
            # move: from in there every step it could take would be refused, and a villager
            # a village was built on top of stayed in the wall for the rest of the save.
            self.unstick(npc, c.Entities.NPC_SIZE / 2)
            # And anything standing on legal ground it cannot get off (the inside corner of
            # an L, the neck between two houses) is prised out of it: that one is invisible
            # to `blocked` and only shows up as a body that has meant to move for a while
            # and has not.
            self.unwedge(
                npc,
                c.Entities.NPC_SIZE / 2,
                dt,
                wants_move=bool(id(npc) in mob or id(npc) in fight or id(npc) in flee or npc.wander.target is not None),
            )
            enemy = fight.get(id(npc))
            # The orders were worked out once for the whole street, so the neighbour who
            # went first may already have finished this one off.
            if enemy is not None and enemy.hp <= 0:
                enemy = None
            if enemy is not None:
                self._npc_fights(npc, enemy, player, dt, quest_system, defenders)
                continue

            shelter = flee.get(id(npc))
            if shelter is not None:
                self._npc_flees(npc, shelter, player, dt)
                continue

            # Night, and nothing to fight: whoever is not already after the player leaves
            # off what they were doing and goes home to bed. A settlement after dark is a
            # street of shut doors and lit windows, which is what makes coming back into one
            # at dusk worth something and makes the wilds at night worth avoiding.
            if self.daynight.curfew and id(npc) not in mob and not npc.is_guard:
                home = self._home_for(npc)
                if home is not None:
                    self._npc_sleeps(npc, home, player, dt, shut=id(home) in all_home)
                    continue

            self._wake_up(npc)
            self._npc_walks(npc, player, dt, mob, crowd, indoors)

    def _npc_fights(self, npc: NPC, enemy, player: Player, dt, quest_system: QuestSystem, defenders: list):
        """One villager's frame spent meeting whatever the settlement sent them at."""
        waypoint = self.chase_waypoint(npc, enemy, c.Entities.NPC_SIZE / 2)
        damage = npc.update(
            player,
            dt,
            self.blocked,
            waypoint,
            target=enemy,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
            standoff=npc.melee_standoff(enemy.size),
            crowd=defenders,
        )
        if not damage:
            return
        # A militia's swing lands on whatever they were sent at, and a boss is kept on its
        # own list: handing the wrong list here would take a dying boss off nothing at all.
        self._resolve_monster_hit(
            enemy,
            self.bosses if isinstance(enemy, Boss) else self.monsters,
            damage,
            player,
            quest_system,
            kb_dir=self._dir_from(npc.x, npc.y, enemy.x, enemy.y),
            blocked=self.blocked,
            by_player=False,
        )

    def _npc_flees(self, npc: NPC, shelter: Building, player: Player, dt):
        """One villager's frame spent running for a door and shutting it behind them."""
        self.open_door_for(npc)
        inside = (shelter.x, shelter.interior_rect().centery)
        self.pass_gate_for(npc, c.Entities.NPC_SIZE / 2, Point(*inside))
        waypoint = self.chase_waypoint(npc, Point(*inside), c.Entities.NPC_SIZE / 2)
        npc.update(
            player,
            dt,
            self.blocked,
            refuge=waypoint or inside,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
        )
        if shelter.contains_point(npc.x, npc.y) and not shelter.door_broken:
            # Behind the door and shutting it. The player can be shut out or shut in with
            # them; either way the street is emptier than it was. Whoever is standing in the
            # frame is stepped out of it rather than sealed in it.
            self.shut_door(shelter, player)

    @staticmethod
    def _wake_up(npc: NPC):
        """Morning: somebody who went to bed behind their own shut door opens it again.

        Their wander is anchored on their doorstep, which is outside, so this is all it takes
        to put the street back: without it the first night a settlement kept was the last day
        anybody was seen in it."""
        home = npc.home_building
        if home is not None and home.door_closed and home.contains_point(npc.x, npc.y):
            home.door_open = True

    def _households_in(self, mob: dict) -> frozenset:
        """Which homes have everybody who lives there back inside, as ids of the buildings.

        The one thing a villager going to bed cannot work out for themselves: shutting the
        door behind you while your neighbour is still on the step puts them back out into the
        street (`shut_door` clears the frame rather than sealing anyone in it), and the two
        of you do that to each other until morning. So the door is only ever shut by the last
        one in."""
        households: dict = {}
        for npc in self.npcs:
            if npc.is_guard or id(npc) in mob:
                continue
            home = self._home_for(npc)
            if home is None:
                continue
            households.setdefault(id(home), []).append((home, npc))
        return frozenset(
            key for key, people in households.items() if all(home.contains_point(one.x, one.y) for home, one in people)
        )

    def _home_for(self, npc: NPC) -> Building | None:
        """The building this one lives in: the one nearest the doorstep they were stood up
        at, which is the door they came out of.

        A merchant's home is their shop, so a night shuts the shop with them inside it
        rather than leaving them standing in the street beside it. Anyone whose house has
        been streamed out from under them has no home to walk to and simply keeps their
        street.

        Found once and kept on the villager: a building does not move once its settlement is
        laid out, and this is asked of everybody in the world on every frame of every
        night."""
        if npc.home_building is None:
            homes = [b for b in self.buildings_near(*npc.home) if b.has_door]
            # Measured to the doorstep and not to the middle of the building, because a
            # villager's home *is* a doorstep (`World._populate_npcs`): off the centres, the
            # shop across the lane won half the street.
            npc.home_building = min(homes, key=lambda b: math.dist(npc.home, b.door_front()), default=None)
        return npc.home_building

    def _npc_sleeps(self, npc: NPC, home: Building, player: Player, dt, shut: bool = True):
        """One villager's frame spent walking home for the night and staying in.

        The same walk as running from a monster (`_npc_flees`), because it is the same act:
        the door is opened, the gate is worked if their house is the other side of one, and
        it is shut behind them. What is different is only where they are going, which is
        their own roof rather than the nearest one.

        The last stride is walked at the room and not at the doorway: a refuge is arrived at
        from `Entities.NPC_ATTACK_RANGE` off it, which is far enough short of a door front to
        leave somebody standing on their own step all night. So the point they are sent to is
        that much shorter than an arm's length (`refuge_reach`), so they stop in the room
        rather than in the frame of their own door."""
        radius = c.Entities.NPC_SIZE / 2
        inside = (home.x, home.interior_rect().centery)
        door = home.door_rect()
        self.pass_gate_for(npc, radius, Point(*inside))
        if home.contains_point(npc.x, npc.y):
            goal = inside
        elif math.hypot(npc.x - door.centerx, npc.y - door.centery) <= c.Buildings.DOOR_BASH_REACH * 3:
            # Their own door, and they have come up to it: it is open before they reach it,
            # the way anyone's is when they are the one who lives there. They are walked
            # square through the gap rather than at the middle of the room, which is a
            # diagonal that clips the wall beside the door: they slid along it all night.
            home.door_open = True
            nx, ny = home.outward()
            step_in = c.Buildings.WALL_THICKNESS + radius + 6
            goal = (door.centerx - nx * step_in, door.centery - ny * step_in)
        else:
            self.open_door_for(npc)
            goal = self.chase_waypoint(npc, Point(*inside), radius) or inside
        npc.update(
            player,
            dt,
            self.blocked,
            refuge=goal,
            refuge_reach=radius,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
            face_player=False,
        )
        if shut and home.contains_point(npc.x, npc.y) and not home.door_broken:
            # In for the night, and the door shut behind them, but only once everybody who
            # lives here is in (`_households_in`). Whoever is standing in the frame is
            # stepped out of it rather than sealed in it, exactly as when a village is
            # running from something.
            self.shut_door(home, player)

    def _npc_walks(self, npc: NPC, player: Player, dt, mob: dict, crowd: list, indoors: bool):
        """One villager's frame spent hunting the player, or spent on their own street."""
        # Only an angry villager actually closing on the player needs a route round the
        # houses; everyone else is wandering and steers for itself.
        chasing = id(npc) in mob
        if chasing:
            self.open_door_for(npc)
            self.pass_gate_for(npc, c.Entities.NPC_SIZE / 2, player)
        waypoint = self.chase_waypoint(npc, player, c.Entities.NPC_SIZE / 2) if chasing else None
        # A villager turns to greet the player in the street, but not through the wall of a
        # house they are standing in: a vision cone that always points at the player is not a
        # cone, and the whole of stealing is choosing a moment nobody is looking.
        damage = npc.update(
            player,
            dt,
            self.blocked,
            waypoint,
            target=player if chasing else None,
            face_player=not indoors,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
            standoff=mob.get(id(npc), 0.0),
            crowd=crowd if chasing else None,
        )
        if damage:
            player.receive_damage(damage, source=npc)

    def _mob_orders(self, player: Player, flee: dict, quest_system: QuestSystem) -> dict:
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
            if not npc.hostile:
                continue
            distance = npc.distance_to_point((player.x, player.y))
            # A village is angry everywhere, but only the people the player is standing
            # among fight them: someone whose street this is not carries on with their day
            # rather than walking the length of the settlement to join a fight they cannot
            # see. Whoever is already in it keeps it out to the longer leash, so a fight the
            # player walks away from is broken off rather than dropped the moment they cross
            # a line. An archer is the exception and answers at the range of their bow: they
            # are posted on the wall precisely to shoot what is too far off to reach.
            if npc.is_archer:
                limit = c.Villages.ARCHER_RANGE
            else:
                limit = c.Entities.NPC_HOSTILE_RANGE if id(npc) in self._engaged else c.Villages.MOB_ENGAGE_RANGE
            if distance > limit:
                continue
            if npc.routed:
                if npc.is_militia:
                    for recruit in self.call_for_help(npc):
                        # Nobody hands in a task to someone they have just joined a fight
                        # against, the same rule a provoked village goes by.
                        quest_system.remove_quest(recruit)
                elif not npc.yielded:
                    self.yield_to_player(npc)
                    continue
                shelter = self._refuge_for(npc)
                if shelter is not None:
                    flee[id(npc)] = shelter
                    continue
            if npc.is_archer:
                # An archer holds the wall and shoots off it (`_loose_arrows`); walking out
                # to swing a bow at the player is exactly what they are posted not to do.
                orders[id(npc)] = c.Villages.ARCHER_RANGE * 0.7
            elif npc.is_militia:
                # Their own weapon's length, so the one with the pitchfork fights at the
                # length of a pitchfork instead of walking up the player's nose with it.
                orders[id(npc)] = npc.melee_standoff(c.Player.SIZE)
            else:
                orders[id(npc)] = c.Villages.MOB_STANDOFF
        self._engaged = set(orders)
        return orders

    def _work_gates(self, player: Player, dt):
        """Bar the gates of any settlement that has turned on the player, lean them shut for
        the night, open them again once it is calm and light, and carry every leaf a frame
        along its swing.

        Shutting for the night is not barring: no beam goes across, so anyone on either side
        works one open with a press and walks through (`Village.push_open`). Barring is the
        wall, and only a grudge or a real mob puts it up.

        A gate is the one part of a wall that is ever a wall to the player: while it is
        barred, getting out of a town you have set against you means heaving the beam up
        yourself (`Game._lift_gate`, slow) or hacking your way through it, and a pack that
        followed you in is shut in with you. A gate already beaten down never shuts again.

        One angry villager is not a siege. A settlement only shuts itself once somebody was
        killed here (the grudge nothing runs out) or `Villages.BAR_GATES_MOB` of its people
        are after the player at once, so a caught thief costs the player a fight and not the
        way out of town."""
        for village in self.villages:
            if not village.defended:
                continue
            angry = [npc for npc in self.npcs if npc.hostile and village.contains_point(npc.x, npc.y)]
            village.barred = any(npc.grudge for npc in angry) or len(angry) >= c.Villages.BAR_GATES_MOB
            village.shut_for_night = c.Villages.NIGHT_GATES and self.daynight.curfew
            village.advance_gates(dt, (player.x, player.y))
            if village.barred or village.shut_for_night:
                # Whichever of the two shut it, nothing is ever sealed inside a leaf.
                self.clear_gateways(village, player)

    def _loose_arrows(self, fight: dict, mob: dict, player: Player):
        """The archers posted in the towers, shooting over their own wall.

        They never come down: an archer holds their post and answers whatever the settlement
        is fighting, the monster in the street first and the player second. Their arrow is an
        ordinary `Projectile`, so it hits whatever is standing in the way, and it credits
        nobody (`by_player=False`): a town's kill is the town's."""
        now = pygame.time.get_ticks()
        for npc in self.npcs:
            if not npc.is_archer or now < npc.next_arrow_ms:
                continue
            target = fight.get(id(npc))
            if target is not None and target.hp <= 0:
                target = None
            if target is None and id(npc) in mob:
                target = player
            if target is None:
                continue
            dx, dy = target.x - npc.x, target.y - npc.y
            # Deliberately shorter than the arrow's own flight: a shot loosed at the very
            # limit of its range dies in the air as soon as its target takes a step away.
            if math.hypot(dx, dy) > c.Villages.ARCHER_RANGE * c.Villages.ARCHER_FIRE_FRAC:
                continue
            if not self.line_of_sight(npc.x, npc.y, target.x, target.y, over_walls=True):
                continue
            if not self._lane_clear(npc, target):
                continue
            npc.next_arrow_ms = now + random.randint(*c.Villages.ARCHER_COOLDOWN_MS)
            npc.start_attack_anim()
            play_sound("shoot")
            arrow = Projectile(
                npc.x,
                npc.y,
                npc.aim_at(target.x, target.y),
                c.Villages.ARCHER_DAMAGE,
                color=ARROW_COLOR,
                shake=c.Combat.PLAYER_HURT_SHAKE / 2,
                hostile=target is player,
                owner_id=id(npc),
                source_name=npc.name or "a town archer",
                max_range=c.Villages.ARCHER_RANGE,
                by_player=False,
                over_walls=True,
            )
            arrow.from_npc = True
            self.projectiles.append(arrow)

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
            if not self._lane_clear(npc, player):
                continue
            npc.next_stone_ms = now + random.randint(*c.Villages.MOB_STONE_COOLDOWN_MS)
            npc.start_attack_anim()
            play_sound("shoot")
            stone = Projectile(
                npc.x,
                npc.y,
                npc.aim_at(player.x, player.y),
                c.Villages.MOB_STONE_DAMAGE,
                style="stone",
                color=STONE_COLOR,
                shake=c.Combat.PLAYER_HURT_SHAKE / 2,
                hostile=True,
                owner_id=id(npc),
                source_name=npc.name or "a villager",
                max_range=c.Villages.MOB_STONE_RANGE,
            )
            stone.from_npc = True
            self.projectiles.append(stone)

    def _lane_clear(self, shooter: NPC, target) -> bool:
        """Whether a villager has a clear lane to what they are shooting at, meaning none of
        their own people standing in it.

        Their shot cannot wound a neighbour any more (`Projectile.from_npc`), but loosing
        one straight through the back of somebody's head still looks like a mistake, and a
        crowded street should thin the volley coming out of the towers rather than leaving
        it untouched. Perpendicular distance to the segment, and only what lies between the
        two of them counts: someone standing behind the shooter is not in the way."""
        dx, dy = target.x - shooter.x, target.y - shooter.y
        span = math.hypot(dx, dy)
        if span == 0:
            return True
        for other in self.npcs:
            if other is shooter or other is target:
                continue
            along = ((other.x - shooter.x) * dx + (other.y - shooter.y) * dy) / span
            if not 0 < along < span:
                continue
            across = abs((other.x - shooter.x) * dy - (other.y - shooter.y) * dx) / span
            if across < c.Villages.FRIENDLY_LANE_WIDTH:
                return False
        return True

    def update(self, player: Player, dt, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        # Particles/floating text/screen fx update once per frame in Game.run() instead of
        # here, so they keep animating even while a menu pauses the rest of this update.
        self.daynight.update(dt)
        # None of this happens underground, and that absence is most of what makes a tunnel
        # somewhere else: no ground streams in around the player, nothing is discovered, no
        # event finds them, and the map remembers nothing of a place with no landmarks.
        # What is down there was put there when they climbed down, and that is all.
        # The map is the exception: it remembers the dark too, on its own finer grid, so a
        # cave unfolds on the minimap as it is walked exactly as the countryside does.
        self._reveal_around(player)
        if self.underground is None:
            self._sync_chunks(player)
            self.events.update(dt, player, quest_system, npc_name_generator)
            self._check_poi_discovery(player)
            self._prepare_settlements_near(player, dt, npc_name_generator)
            self._check_village_discovery(player)
            self._clear_reached_rumors(player)

        # After dark everything hits harder and notices sooner, whenever it spawned: night
        # is a state of the world, not a property of the monsters standing in it.
        damage_mult = self.night_damage_mult()

        # The same pass every villager, monster and animal gets, and for the same reason:
        # from inside a solid every step is refused, so a player a door was shut on, or a
        # village was built around, would otherwise stay wedged there for good.
        self.unstick(player, player.size / 2)

        # Whatever is still travelling under a blow's shove is carried first, so a body
        # crosses the ground it was thrown across before it gets a step of its own.
        self.advance_impulses(player, dt)
        self._update_monsters(player, dt, quest_system, damage_mult)
        self.update_projectiles(player, quest_system, dt)
        self.update_bombs(player, quest_system, dt)
        self._update_npcs(player, dt, quest_system)
        self._update_critters(player, dt, damage_mult)
        # A warning nobody is counting any more is rubbed out here rather than left to be
        # filtered wherever it is read, so the HUD, the ladder and the save all see the same
        # ledger.
        self.forget_stale_strikes()
        # Checked once everything has taken its step, so a trap shuts on where things
        # actually ended up this frame rather than on where they set off from.
        self.snap_traps(player, quest_system)
        self.prick_spikes(player, quest_system)
        self._track_bloody_feet(player)

        # Restocking is the surface's alone: a tunnel holds what was put in it when the
        # player climbed down, and nothing wanders in after them.
        if self.underground is None:
            self._restock_surface(player, dt)

    def _track_bloody_feet(self, player: Player):
        """Anything walking through fresh blood picks it up and prints it out again for the
        next few strides (`DecalSystem.track_walkers`).

        Only what is near enough to be on screen: a trail nobody can see is bookkeeping, and
        the whole point of the prints is reading which way something walked away from a
        body. Called after everything has taken its step, like the traps, so a foot is
        judged on where it actually ended up this frame."""
        reach = c.World.CHUNK_SIZE
        walkers = [(id(player), player.x, player.y)]
        for group in (self.monsters, self.npcs, self.critters):
            walkers.extend(
                (id(body), body.x, body.y)
                for body in group
                if abs(body.x - player.x) <= reach and abs(body.y - player.y) <= reach
            )
        get_decals().track_walkers(walkers)

    def _update_monsters(self, player: Player, dt, quest_system: QuestSystem, damage_mult: float):
        """Every monster near enough to react, plus the bosses, the burns ticking on both
        and whatever a monster does that is not a step: shooting, bashing a door, exploding."""
        player_pos = player.get_pos()
        detection = c.World.DETECTION_RANGE * (c.DayNight.NIGHT_DETECTION_MULT if self.daynight.is_night else 1.0)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt). Never tighter
        # than the screen itself, though: one that has noticed nobody still roams its patch,
        # and a monster standing perfectly still at the edge of the view until the player
        # steps into its detection ring is what made every cave mouth look like an ambush
        # laid in advance.
        update_radius = max(detection + c.Player.SIZE, c.Screen.ORIGIN_X + c.MONSTER_MAX_SIZE)
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
            # Anything that has ended up inside a solid (shouldered into a tower by the pack
            # behind it, caught by a door shutting) is put back on open ground first: every
            # step it could take from in there would be refused.
            self.unstick(monster, monster.kind.size / 2)
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
        # Fuses burn on the clock rather than on the player being close, so a creeper that
        # drifted out of `nearby` mid-fuse still goes off instead of freezing where it stands.
        for monster in list(self.monsters):
            if monster.fuse_expired():
                self.detonate_creeper(monster, player, quest_system)
        self.fire_monster_shots(player, damage_mult)
        self.bash_doors(player, damage_mult)
        self.bash_gates(player, damage_mult)

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        # Camp guards are the exception: they hold a place rather than roam, and their camp
        # would look abandoned while its chunk is still loaded. They leave with the chunk
        # instead (see WorldStreaming._unload_chunks). Nothing despawns while the player is
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

    def _update_critters(self, player: Player, dt, damage_mult: float):
        player_pos = player.get_pos()
        for critter in self.critters:
            self.unstick(critter, critter.size / 2)
            # Only an animal actually coming for the player needs a route round the houses;
            # everything else is wandering or running and steers for itself.
            chasing = critter.hostile and critter.distance_to_point(player_pos) <= critter.kind.detection
            waypoint = self.chase_waypoint(critter, player, critter.size / 2) if chasing else None
            critter.update(
                player, dt, self.blocked, damage_mult, waypoint, terrain_mult=self.terrain_speed(critter.x, critter.y)
            )

    def _restock_surface(self, player: Player, dt):
        """What keeps the ground around the player populated: the village dogs, the wildlife
        despawning behind and respawning ahead, and the roaming monsters up to the cap."""
        player_pos = player.get_pos()
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
