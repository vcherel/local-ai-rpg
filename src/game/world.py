from __future__ import annotations

import math
import random
import threading
import time
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.daynight import DayNightCycle
from core.utils import parse_world_context
from core.weather import WeatherSystem
from game.bosses import WorldBosses
from game.breaking import WorldBreaking
from game.combat import WorldCombat
from game.entities.bomb import MINE, Bomb
from game.entities.boss import Boss
from game.entities.breakables import Breakable, generate_breakables
from game.entities.buildings import Building, set_active_buildings
from game.entities.critter import Critter
from game.entities.entities import advance_impulse
from game.entities.items import Item
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest
from game.entities.projectile import Projectile
from game.entities.scenery import Scenery
from game.entities.traps import BearTrap
from game.entities.village import Village
from game.entities.village_generation import generate_starting_world
from game.entities.village_sites import register_world_sites
from game.events import EventSystem
from game.explosives import WorldExplosives
from game.gore import WorldGore
from game.navigation import WorldNavigation
from game.places import WorldPlaces
from game.projectiles import WorldProjectiles
from game.shops import WorldShops
from game.social import WorldSocial
from game.spawning import WorldSpawning
from game.streaming import WorldStreaming
from game.villagers import WorldVillagers

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World(
    WorldBosses,
    WorldCombat,
    WorldBreaking,
    WorldGore,
    WorldExplosives,
    WorldProjectiles,
    WorldStreaming,
    WorldSpawning,
    WorldPlaces,
    WorldShops,
    WorldSocial,
    WorldNavigation,
    WorldVillagers,
):
    """The living world and everything standing in it.

    The jobs live in their own modules and are mixed in here: `WorldCombat`
    (game/combat.py) resolves every blow and its aftermath, `WorldBreaking`
    (game/breaking.py) is the blow that lands on the built world rather than on a body and
    `WorldGore` (game/gore.py)
    draws what one left behind, `WorldExplosives`
    (game/explosives.py) is every blast and what it caught, `WorldStreaming`
    (game/streaming.py) generates the endless map around the player and names what it
    finds, `WorldPlaces` (game/places.py) is what the player can do at a place once they
    reach it (camps, fires, shrines, tunnels, directions), `WorldSocial` (game/social.py)
    is what a settlement thinks of them and does about it (witnesses, warnings, anger,
    amends, notoriety, raids, the notice board), `WorldNavigation`
    (game/navigation.py) is how anything gets from where it is to where it wants to be,
    `WorldSpawning` (game/spawning.py) keeps the ground around the player populated and
    runs what is standing on it,
    `WorldBosses` (game/bosses.py) stands the bosses up, and `WorldShops`
    (game/shops.py) fills the shelves.
    All of them work on the entity lists this class owns; keeping them as one class is
    what lets `self.monsters` and friends stay the single source of truth, and what
    decides which file a new method belongs in is the job it does, not which object holds
    the data.

    What is left here is the state itself: the lists, the chunk indexes that say what is
    solid where, saving, and the per-frame `update`.
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
        # What the sky is doing, on its own clock and never saved: rain and fog are a state
        # of the world exactly as night is, and one nobody has to be able to plan around.
        self.weather = WeatherSystem()
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
        # and never saved. Filed by `_index_scenery` as each chunk arrives into what is drawn
        # under the entities, what is drawn with the props, and a fine grid of the solid ones
        # for `blocked` and another of the wet ones for `water_at`.
        self.scenery: list[Scenery] = []
        self._ground_by_chunk: dict = {}
        self._props_by_chunk: dict = {}
        self._scenery_by_cell: dict = {}
        self._water_by_cell: dict = {}
        self._loaded_chunks = set()
        # Chunks in range and not built yet, nearest first, a step or two per frame; see
        # `WorldStreaming._build_pending_chunks`. A chunk is built in two: its ground here,
        # and then its wilderness from `_pending_wild`, on a later frame.
        self._pending_chunks: list[tuple[int, int]] = []
        self._pending_wild: list[tuple[int, int]] = []
        # What each of those rolled, waiting for its own wilderness to be kept off it.
        self._chunk_pois: dict[tuple[int, int], list] = {}
        self._current_chunk = None
        self._last_reveal_cell = None

    def _init_entity_state(self):
        """Everything standing in the world, the indexes that find it, and the timers that
        keep the ground around the player populated."""
        self.items: list[Item] = []
        self.npcs: list[NPC] = []
        # Where each villager is being walked to while the player sleeps a night away, as
        # (npc, where they lay down, where they will be standing at dawn). Session-only and
        # empty every frame but the second or so of a fade (`WorldVillagers.plan_morning`).
        self.morning_walk: list = []
        # The settlement's night, as the three things that start with the bell: whether it
        # is under way, when it began (the hour every villager's own bedtime is measured
        # from) and how many tolls are still to come. Session-only, like the weather: what
        # the clock was doing is worked out again on the next frame after a load.
        self.curfew_on = False
        self.curfew_at_ms = 0
        self.bell_left = 0
        self.bell_next_ms = 0
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
        # The solid ones filed on the same fine grid the trunks and boulders use, kept up as
        # they are scattered and taken away with the one that is smashed. A world holds a
        # few hundred once the player has found a handful of towns, and `blocked` runs
        # several times per body per frame, so this is never a walk of the list.
        self._breakables_by_cell: dict = {}
        # And the same props bucketed by chunk, for the callers working over an area rather
        # than a point: the renderer asks for what it can see. Unlike the traps, these are
        # not dropped when their chunk unloads (a smashed barrel is world state), so the
        # list grows for the whole session exactly as the buildings do, and is looked up
        # the same way for the same reason.
        self._breakables_by_chunk: dict = {}
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
        # The blood night's raid on a settlement, or None: which village it is on, where it
        # stands, how many of it the player has put down and when it is called off
        # (`WorldSocial.raid_village`). Session-only, like the night that started it: what
        # is left of a raid is monsters standing on a map, and those are saved already.
        self.raid: dict | None = None
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

        # The starting-town villager who walks over and offers the first quest, and the
        # countdown before they set off (`WorldVillagers._update_greeter`). Set only on a
        # new world; None once the quest has been handed over or on any reload.
        self.greeter: NPC | None = None
        self.greeter_timer = 0.0
        self._greeter_pending = False

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
        # Where the player last died and left their coins and their things, or None once
        # they have been back for them. Saved, unlike a rumour's mark: the drop itself is in
        # `items` and outlives the session, so the pin that finds it has to as well.
        self.death_drop = self.save_system.load("death_drop", None)
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
        # village warns before it turns (`WorldSocial.strike_village`), once per kind of
        # offence, and the warning has to survive a save the way the anger it leads to does,
        # or quitting would be a way of starting over on a clean slate. Strikes older than
        # the window are dropped rather than loaded.
        self.village_strikes = self._load_strikes(self.save_system.load("village_strikes", {}))
        # What the player has done that people repeat, as points on the map with a weight and
        # a time (`WorldSocial.record_deed`). A grudge belongs to the settlement holding it;
        # this is what the settlement over the hill has heard, so it is kept by where it
        # happened rather than by whose it was. Saved for the same reason the strikes are:
        # quitting is not a way of starting again with a clean name.
        self.deeds = self.save_system.load("notoriety", [])
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
        # The starting-town greeter, if the player quit before hearing them out: pick them
        # back up off the saved flag so the first quest still finds its way over.
        self.greeter = next((npc for npc in self.npcs if npc.is_greeter and not npc.has_active_quest), None)
        if self.greeter is not None:
            self.greeter_timer = self.save_system.load("greeter_timer", 0.0)
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
        # Lanes first: a prop is kept off the trodden earth, so the earth has to be worn
        # before there is anything to keep off.
        self._plan_streets()
        self.breakables = generate_breakables(self.buildings, village)
        self._index_breakables()
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
        # The greeter is chosen on the first frame instead of here: the player has not been
        # placed in the world yet, and it should be whoever is nearest to where they spawn.
        self._greeter_pending = True

    def _designate_greeter(self, player):
        """Pick the villager who walks over and offers the first quest: someone on foot,
        not a merchant and not on the wall, nearest to where the player came into the
        world so the walk is short and does not cross the settlement wall."""
        self._greeter_pending = False
        candidates = [npc for npc in self.npcs if not npc.is_merchant and not npc.is_guard and not npc.is_archer]
        if not candidates:
            return
        self.greeter = min(candidates, key=lambda npc: npc.distance_to_point(player.get_pos()))
        self.greeter.is_greeter = True
        self.greeter_timer = c.Onboarding.GREET_DELAY_S

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
            # Never more people than the room was furnished for. How many beds a room fits is
            # the room's own arithmetic (a second one is skipped when there is no wall left
            # for it), and a household dealt more people than beds is somebody lying on the
            # floor of their own house every night of the save. One is the floor: a house
            # nobody lives in is a house, but not one this is allowed to make.
            beds = max(1, len(home.interior_layout()["beds"]))
            for _ in range(min(random.randint(*per_home), beds)):
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
            if not archer:
                # A watch is walked, not stood: a guard covers a wider patch than the two
                # paces they used to and barely stops on it, and their head turns while they
                # do stop (`NPC._keep_watch`). Posted still, since the anchor is the gate.
                guard.wander.idle_min_ms, guard.wander.idle_max_ms = c.Villages.GUARD_IDLE_MS
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

    def night_damage_mult(self) -> float:
        """How much harder everything hits right now. A property of the hour, not of the
        monster, so anything that damages the player reads it from here."""
        return c.DayNight.NIGHT_DAMAGE_MULT if self.daynight.is_night else 1.0

    def _restore(self, saved_npcs: list):
        """Rebuild items, NPCs, monsters and buildings from a saved game, relinking quest items by id."""
        self.buildings = [Building.from_dict(d) for d in self.save_system.load("buildings", [])]
        self.villages = [Village.from_dict(d) for d in self.save_system.load("villages", [])]
        self.breakables = [Breakable.from_dict(d) for d in self.save_system.load("breakables", [])]
        self._index_breakables()
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
            # A tunnel's old traps are session-only, like its garrison: never saved, laid
            # again on the next descent.
            if trap.sprung and not trap.tunnel_id:
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
            "notoriety": self.deeds,
            "death_drop": self.death_drop,
            "explored": [f"{gx}:{gy}" for gx, gy in sorted(self.explored)],
            "daynight_elapsed_ms": self.daynight.elapsed_ms,
            "greeter_timer": self.greeter_timer,
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

    def _index_breakables(self):
        """File every outdoor prop the world holds. Only for the two moments the whole list
        arrives at once (a new world, a loaded save); everything after that goes piece by
        piece through `add_breakables` and `drop_breakable`."""
        self._breakables_by_cell = {}
        self._breakables_by_chunk = {}
        self._file_breakables(self.breakables)

    def add_breakables(self, breakables: list[Breakable]):
        """Scatter a newly generated settlement's props, filing the solid ones as they land."""
        self.breakables.extend(breakables)
        self._file_breakables(breakables)

    def _file_breakables(self, breakables: list[Breakable]):
        """Put props into both lookups: the fine grid the solid ones are collided against,
        and the chunk bucket the renderer reads. The one place a prop is filed."""
        for breakable in breakables:
            for cell in breakable.block_cells():
                self._breakables_by_cell.setdefault(cell, []).append(breakable)
            chunk = self._chunk_of(breakable.x, breakable.y)
            self._breakables_by_chunk.setdefault(chunk, []).append(breakable)

    def drop_breakable(self, breakable: Breakable):
        """Take one off the world for good, out of the lookup as well as out of the list. The
        one path a smashed prop leaves by, so nothing is ever left blocking ground it is no
        longer standing on."""
        self.breakables.remove(breakable)
        for cell in breakable.block_cells():
            here = self._breakables_by_cell.get(cell)
            if here and breakable in here:
                here.remove(breakable)
        bucket = self._breakables_by_chunk.get(self._chunk_of(breakable.x, breakable.y))
        if bucket and breakable in bucket:
            bucket.remove(breakable)

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
        # The cell is read straight rather than through `breakables_near`, and a cell nothing
        # solid stands in holds no bucket at all: this runs several times per body per frame
        # and most of the world has no barrel in it, so the common answer costs one dict miss
        # and never builds a generator over an empty list.
        cell = c.Scenery.INDEX_CELL
        props = self._breakables_by_cell.get((int(x // cell), int(y // cell)))
        if props is not None and any(prop.blocks(x, y, radius) for prop in props):
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

    def breakables_in_range(self, x, y, radius):
        """The outdoor props standing in the chunks around a point, for the frame that has to
        draw them. `scenery_props_in_range` for the barrels and the kegs."""
        for chunk in self._chunk_window(x, y, radius):
            yield from self._breakables_by_chunk.get(chunk, ())

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

    def building_at(self, x, y) -> Building | None:
        """The building whose floor (x, y) stands on, or None. Buildings are kept far enough
        apart that at most one can contain a given point."""
        for building in self.buildings_near(x, y):
            if building.contains_point(x, y):
                return building
        return None

    def doorway_building_at(self, x, y) -> Building | None:
        """The building whose doorway (x, y) is standing in, or None.

        `building_at` is the floor, and a doorway is a hole in the wall rather than a piece
        of floor: by that question a body mid-threshold belongs to nowhere, which is exactly
        the body navigation has no way round (`WorldNavigation.chase_waypoint`)."""
        for building in self.buildings_near(x, y):
            if building.in_doorway(x, y):
                return building
        return None

    def bed_taken(self, bed) -> NPC | None:
        """Whoever is asleep in this bed, or None. A villager in their own bed is a body in
        it: the player takes another one or comes back in the morning."""
        return next((npc for npc in self.npcs if npc.asleep and npc.bed == bed), None)

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
        pos = player.reach_point(c.Player.INTERACTION_DISTANCE)
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

    def update(self, player: Player, dt, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        # Particles/floating text/screen fx update once per frame in Game.run() instead of
        # here, so they keep animating even while a menu pauses the rest of this update.
        self.daynight.update(dt)
        # The sky over the surface only: a tunnel has no weather, and the rain that was
        # falling when the player climbed down is still falling when they come back up.
        if self.underground is None:
            # A roof is a roof whether it is a house's or a hill's: the fog is drawn through
            # how much sky the player is standing out under, which is what makes a doorway a
            # moment instead of a switch.
            self.weather.update(dt, self.building_at(player.x, player.y) is not None)
        # None of this happens underground, and that absence is most of what makes a tunnel
        # somewhere else: no ground streams in around the player, nothing is discovered, no
        # event finds them, and the map remembers nothing of a place with no landmarks.
        # What is down there was put there when they climbed down, and that is all.
        # The map is the exception: it remembers the dark too, on its own finer grid, so a
        # cave unfolds on the minimap as it is walked exactly as the countryside does.
        self._reveal_around(player)
        # Not in the surface branch below: a death underground leaves its drop in the tunnel
        # it happened in, and walking back down to it is how it is rubbed out.
        self._clear_reached_death_drop(player)
        if self.underground is not None:
            # The dark's own mood: the lantern's flicker and dim, the down draught, the
            # noises off. None of it moves anything in the world.
            self._update_cave_mood(player, dt)
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
        # And every deed nobody repeats any more, on the same frame and for the same reason:
        # the HUD, a shop's prices and the save all read one list.
        self.forget_stale_deeds()
        # Checked once everything has taken its step, so a trap shuts on where things
        # actually ended up this frame rather than on where they set off from.
        self.snap_traps(player, quest_system)
        self.prick_spikes(player, quest_system)
        self._track_bloody_feet(player)

        # Restocking is the surface's alone: a tunnel holds what was put in it when the
        # player climbed down, and nothing wanders in after them.
        if self.underground is None:
            self._restock_surface(player, dt)
            # A raid is over when there is nothing left of it or its time has run out, and
            # that is when the village pays for it (`WorldSocial.update_raid`).
            self.update_raid()
