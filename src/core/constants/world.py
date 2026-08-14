from dataclasses import dataclass


@dataclass(frozen=True)
class World:
    WORLD_SIZE: int = 5000
    # How far a monster notices the player and gives chase. Deliberately wider than the
    # screen's half-width: the wilderness should come at you rather than be walked past.
    DETECTION_RANGE = 700

    # How many people a settlement holds follows from its buildings (Villages), not from a
    # world-wide count: the world is endless, so there is no total to fix.
    NB_MONSTERS: int = 120

    # Slain monsters are replenished over time so the world never empties out.
    RESPAWN_INTERVAL_MS: int = 2200
    # New monsters spawn at least this far from the player so they never pop into view.
    # The screen's half-diagonal is ~1006px, so anything under that can appear on camera.
    SPAWN_MIN_DISTANCE: int = 1100
    # ...and at most this far, so they still show up as the player explores.
    SPAWN_MAX_DISTANCE: int = 1500
    # Monsters left this far behind despawn, freeing their slot to respawn near the player.
    DESPAWN_DISTANCE: int = 3000
    # Monsters placed at world creation start at least this far from the player spawn point.
    INITIAL_SPAWN_MIN_DISTANCE: int = 1200
    # How far apart the members of a pack kind (MonsterKind.group) are scattered on spawn.
    PACK_SPREAD: int = 110

    # Obstacle avoidance: a monster probes this many steps ahead (never less than
    # STEER_MIN_PROBE past its own radius) so it turns away from a wall early instead
    # of pressing into it, and heads for a door once within DOOR_APPROACH_DISTANCE of it.
    STEER_LOOKAHEAD: float = 12.0
    STEER_MIN_PROBE: int = 26
    DOOR_APPROACH_DISTANCE: int = 90
    # When every long probe is blocked (a corner, a gap between two pieces of furniture),
    # the same fan is tried again this far ahead: in a tight room there is usually exactly
    # one way out and the lookahead is too long to see it.
    STEER_CLOSE_PROBE: int = 4

    # Buildings are bucketed by chunk for collision lookups, each one padded by this much
    # so a footprint just over a chunk border is still found from the chunk next door.
    # Comfortably above the biggest radius anything collides with.
    BUILDING_INDEX_PAD: int = 160

    # Floor details stream in per chunk as the player explores, so the world has no edge.
    CHUNK_SIZE: int = 1000
    DETAILS_PER_CHUNK: int = 200
    # Chunks within this many chunks of the player are generated...
    CHUNK_LOAD_RADIUS: int = 2
    # ...and stay loaded until this much farther away, to avoid load/unload thrashing at the edge.
    CHUNK_KEEP_RADIUS: int = 3

    # Shortest gap between two World.persist_world writes. Every write serialises the whole
    # world, and generation threads finish in bursts; the periodic autosave catches the rest.
    PERSIST_MIN_INTERVAL_S: float = 5.0

    # How many rings World.free_spot_near searches before giving up. Each ring is one body
    # diameter farther out, so this covers a building's whole footprint and then some.
    FREE_SPOT_MAX_RINGS: int = 24

    # How many rings of chunks World.find_bandit_camp generates outward looking for a camp
    # a clear_camp quest can send the player at. Far enough to be a journey, near enough
    # that the walk out is not the whole quest.
    CAMP_SEARCH_RINGS: int = 8


@dataclass(frozen=True)
class Events:
    # A random world event is rolled on this cadence; each roll picks one enabled kind.
    INTERVAL_RANGE_MS: tuple = (180_000, 360_000)

    # Relative pick weights among the event kinds currently enabled.
    WEIGHT_MERCHANT: int = 3
    WEIGHT_TREASURE: int = 4
    WEIGHT_BLOOD_NIGHT: int = 2
    WEIGHT_RUMOR: int = 5
    WEIGHT_PROPHETIC_RUMOR: int = 2
    WEIGHT_CRISIS: int = 3
    WEIGHT_BOSS: int = 2

    BOSS_EVENT_MIN_DIST: int = 800
    BOSS_EVENT_MAX_DIST: int = 1200

    # Chance a treasure or blood night is preceded by a short lore warning instead of striking instantly.
    PRESAGE_CHANCE: float = 0.5
    PRESAGE_DELAY_RANGE_S: tuple = (8, 15)
    PROPHECY_DELAY_RANGE_S: tuple = (20, 40)

    MERCHANT_MIN_DIST: int = 400
    MERCHANT_MAX_DIST: int = 700
    MERCHANT_DURATION_MS: int = 180_000

    TREASURE_MIN_DIST: int = 300
    TREASURE_MAX_DIST: int = 600

    BLOOD_NIGHT_DURATION_MS: int = 120_000
    BLOOD_NIGHT_RESPAWN_MULT: float = 3.0
    BLOOD_NIGHT_DROP_MULT: float = 2.0


@dataclass(frozen=True)
class DayNight:
    # A full day/night cycle takes this long in real time.
    CYCLE_LENGTH_MS: int = 600_000

    # Cycle progress (0..1) at which each phase ends; day holds steady from 0, dusk and
    # dawn ramp darkness up/down between the steady day and night stretches.
    DAY_END: float = 0.45
    DUSK_END: float = 0.55
    NIGHT_END: float = 0.85

    NIGHT_COLOR: tuple = (15, 20, 60)
    NIGHT_MAX_ALPHA: int = 90

    # Blood night overrides the normal tint with a fixed dark red look, regardless of
    # whatever the time of day would otherwise show.
    BLOOD_NIGHT_COLOR: tuple = (80, 0, 10)
    BLOOD_NIGHT_ALPHA: int = 130

    # After dark the wilds turn on the player: more of them, hitting harder, noticing
    # from farther off, rolled as if the ground itself were deeper into the wilds, and
    # far likelier to turn up something with a name. Night is meant to be waited out at
    # a fire or inside a village, not walked through.
    NIGHT_RESPAWN_MULT: float = 2.2
    NIGHT_DAMAGE_MULT: float = 1.35
    NIGHT_DETECTION_MULT: float = 1.4
    NIGHT_DANGER_BONUS: int = 1500
    NIGHT_BOSS_ROAM_MULT: float = 2.0


@dataclass(frozen=True)
class Crime:
    """Helping yourself to what a villager owns: their chest, their bed.

    A house is theirs, not loot: taking from the chest or sleeping in the bed is free and
    silent right up until someone sees it. Whoever catches you turns on you alone (the rest
    of the village never hears about it), which is the one way a single NPC goes hostile
    without the whole settlement; swinging back at them is what escalates it, through the
    usual `World.provoke_village`. Nobody sees through a wall, so what decides it is who is
    standing outside, which makes an empty street or the dark the way to rob a house."""

    WITNESS_RADIUS: float = 430.0
    # How much of that radius is left after dark. Night is when a house is worth robbing.
    NIGHT_WITNESS_MULT: float = 0.4


@dataclass(frozen=True)
class Buildings:
    # How many of each a settlement holds is set per village size (Villages.COMPOSITION),
    # not here: buildings only ever exist as part of a village now.

    # (width range, height range) per kind. The landmark ruin has no door and no interior.
    # A house/shop/tavern's footprint is also its interior room now (no separate coordinate
    # space), so these are sized to hold a walkable room with furniture, not just a facade.
    SIZES = {
        "house": ((320, 380), (280, 340)),
        "shop": ((340, 380), (280, 320)),
        "tavern": ((420, 480), (340, 400)),
        "landmark": ((280, 330), (240, 290)),
    }
    ROOF_COLORS = {
        "house": (152, 76, 56),
        "shop": (88, 110, 152),
        "tavern": (122, 88, 140),
    }

    # Every building rolls a style from its own id, so a village is a row of different
    # houses instead of the same one repeated. The kind still reads first (a shop keeps
    # its awning, a tavern its sign); the style only changes the roof and the trim.
    #
    # Roof material: the covering drawn over the walls, as (name, weight).
    ROOF_MATERIALS: tuple = (("tile", 4), ("thatch", 3), ("shingle", 3), ("slate", 2))
    # Base colour per material. The kind's ROOF_COLORS hue is blended into it so a shop
    # still reads blue-ish and a tavern purple-ish under any covering.
    ROOF_MATERIAL_COLORS = {
        "tile": (168, 84, 62),
        "thatch": (176, 150, 88),
        "shingle": (120, 96, 74),
        "slate": (98, 104, 116),
    }
    ROOF_KIND_BLEND: float = 0.45
    # Roof form: how the covering is drawn. "gable" has a ridge along one axis, "hip"
    # slopes to a point, "flat" is the plain slab the game had before.
    ROOF_FORMS: tuple = (("gable", 5), ("hip", 3), ("flat", 2))
    # Wall colour jitter per building, so two neighbours of the same material differ.
    WALL_TINT_RANGE: tuple = (0.88, 1.12)
    # Extras rolled on top, each independently. A building takes at most EXTRA_MAX of them.
    EXTRAS: tuple = (("chimney", 4), ("porch", 3), ("shutters", 4), ("flowerbox", 3), ("woodpile", 2))
    EXTRA_MAX: int = 2

    # Buildings keep their distance from each other, the spawn point and the world edge.
    MIN_GAP: int = 350
    SPAWN_CLEARANCE: int = 700
    EDGE_MARGIN: int = 250

    DOOR_WIDTH: int = 70
    # The entry trigger straddles the front wall, extending this far on each side of it.
    DOOR_DEPTH: int = 35

    # Every door starts shut and blocks the doorway like any other wall. The player opens
    # and closes it with E; a monster that cannot reach the player through it beats it
    # down over several blows, and a door once broken is a hole for good.
    DOOR_HP: int = 55
    DOOR_BASH_REACH: int = 46
    DOOR_BASH_COOLDOWN_MS: int = 900
    DOOR_COLOR: tuple = (96, 68, 44)

    # Thickness of the wall shell drawn/collided around a building's footprint; the
    # walkable floor is the footprint inset by this on every side.
    WALL_THICKNESS: int = 16

    TAVERN_SLEEP_COST: int = 15
    INTERACT_DISTANCE: int = 120

    # Nothing breaks in one tap: a crate takes a few blows, each one splintering it a
    # little further, and only the last one spills what's inside.
    CRATE_HP: int = 22
    WINDOW_HP: int = 10
    # Smashing a shop crate always yields a few coins and sometimes a common item.
    CRATE_COIN_MIN: int = 1
    CRATE_COIN_MAX: int = 6
    CRATE_ITEM_CHANCE: float = 0.2

    # Two windows flank the door on every non-landmark building's front facade;
    # broken ones stay broken (per-building index set, like broken crates).
    WINDOW_W: int = 24
    WINDOW_H: int = 20
    WINDOW_Y_FROM_BOTTOM: int = 45
    WINDOW_X_FROM_DOOR: int = 40
    WINDOW_HIT_RADIUS: int = 18

    WALL_COLOR: tuple = (72, 56, 44)
    FLOOR_COLOR: tuple = (152, 112, 72)
    STONE_COLOR: tuple = (138, 136, 128)


@dataclass(frozen=True)
class Breakables:
    """Outdoor props scattered near houses/shops/taverns (game/entities/breakables.py).
    "barrel" smashes the same way as an interior crate, with the same coin/item odds;
    "powder" is a keg that goes off instead of dropping anything; everything else is pure
    decoration, just a satisfying puff with no reward."""

    PER_BUILDING_MIN: int = 2
    PER_BUILDING_MAX: int = 4
    SIZE: int = 30
    HIT_RADIUS: int = 20
    # Relative pick weight among kinds scattered near a building. What grows by a door
    # says more about the people living behind it than a row of clay pots did, so the
    # decorative half of the list is planted rather than potted.
    KIND_WEIGHTS: tuple = (
        ("barrel", 5),
        ("powder", 2),
        ("bush", 3),
        ("flowerbed", 3),
        ("herbs", 2),
        ("sapling", 2),
    )
    # A powder keg gives quickly and takes an arrow, because the point of it is the blast
    # (constants.Explosion), not the work of breaking it.
    POWDER_HIT_RADIUS: int = 26
    # How much punishment each kind takes before it gives. A flower bed is cleared in a
    # swipe, a barrel has to be worked at; the props are scenery you fight through, not
    # confetti.
    DEFAULT_HP: int = 8
    HP = {"barrel": 20, "powder": 6, "bush": 5, "flowerbed": 4, "herbs": 4, "sapling": 9}


@dataclass(frozen=True)
class Scenery:
    """The wilderness itself: trees, boulders, grass, ponds and the roads between villages
    (game/entities/scenery.py).

    Streamed per chunk like the floor details and thrown away with them, so none of it is
    saved and none of it can be changed by the player. A chunk rolls one biome, which is
    what makes a forest read as a forest instead of an even sprinkle of trees over
    everything. Trunks and boulders are the only part that stops movement.
    """

    # Trunk/rock radius per kind that stops movement. A tree's canopy is drawn much wider
    # than this: what blocks is the trunk, so walking under the leaves still works.
    BLOCK_RADIUS = {"tree": 15, "pine": 14, "boulder": 30, "stump": 13}
    # Drawn under the entities with the floor, rather than over it with the props, and in
    # this order: the broad patches of ground first, then what lies on them, so a road is
    # never buried under the meadow it crosses.
    GROUND_KINDS: tuple = ("patch", "pond", "path", "pebbles", "grass", "flowers")

    # Broad soft patches of a different ground colour, laid down before everything else.
    # They are what stops open country reading as one flat green sheet, so every biome
    # gets them, in its own shades: (multiplier on the ground green, or an absolute colour).
    PATCH_RADIUS: tuple = (90, 200)
    PATCH_COLORS = {
        "plain": ((0.86, 0.94, 0.72), (1.06, 1.02, 0.9), (0.92, 1.04, 0.86)),
        "forest": ((0.72, 0.82, 0.66), (0.84, 0.9, 0.7), (0.62, 0.76, 0.6)),
        "rocky": ((0.86, 0.86, 0.78), (0.94, 0.9, 0.74), (0.78, 0.82, 0.76)),
        "wetland": ((0.7, 0.88, 0.82), (0.8, 0.92, 0.76), (0.66, 0.8, 0.78)),
    }

    # Blocking scenery is bucketed on its own fine grid rather than by chunk: a forest
    # chunk holds dozens of trunks and `World.blocked` runs several times per entity per
    # frame, so the lookup has to land on a handful of them, not on the whole wood.
    INDEX_CELL: int = 250
    # Padding on each bucketed item, comfortably above the biggest radius anything
    # collides with, so a trunk just over a cell border is still found from next door.
    INDEX_PAD: int = 80

    # Relative weight per biome, rolled once per chunk.
    BIOME_WEIGHTS: tuple = (("plain", 5), ("forest", 4), ("rocky", 3), ("wetland", 2))
    # What one chunk of each biome holds, as (kind, cluster count, members per cluster,
    # cluster spread). Scenery grows in clumps because scattered singles read as noise:
    # a copse, a boulder field and a reed bed are places, a uniform dusting is texture.
    BIOMES = {
        "plain": (
            ("patch", (4, 7), (1, 2), 200),
            ("grass", (10, 14), (4, 7), 140),
            ("flowers", (3, 6), (3, 7), 100),
            ("tree", (1, 3), (1, 3), 70),
            ("pebbles", (1, 3), (2, 4), 90),
        ),
        "forest": (
            ("patch", (5, 8), (1, 2), 200),
            ("tree", (6, 9), (4, 8), 170),
            ("pine", (2, 4), (3, 6), 150),
            ("stump", (1, 3), (1, 2), 60),
            ("grass", (6, 10), (3, 6), 130),
            ("flowers", (1, 3), (2, 4), 90),
        ),
        "rocky": (
            ("patch", (4, 7), (1, 2), 200),
            ("boulder", (3, 5), (2, 4), 140),
            ("pebbles", (6, 10), (3, 6), 110),
            ("grass", (4, 7), (2, 5), 120),
            ("pine", (1, 3), (1, 3), 90),
        ),
        "wetland": (
            ("patch", (5, 8), (1, 2), 210),
            ("pond", (1, 3), (1, 1), 0),
            ("reeds", (4, 8), (4, 8), 110),
            ("grass", (6, 10), (3, 6), 140),
            ("tree", (1, 3), (1, 2), 80),
        ),
    }

    # How far from a building, landmark or plaza anything is kept, so cover never grows
    # through a wall or over a campfire.
    CLEARANCE_BUILDING: int = 90
    CLEARANCE_POI: int = 150
    CLEARANCE_VILLAGE: int = 260

    # Ponds are the one kind big enough to need its own footprint.
    POND_RADIUS: tuple = (70, 150)

    # Roads: each village site is joined to its nearest neighbour, and the chunk being
    # generated lays down the packed earth of whatever passes through it. Nothing that
    # blocks may stand within CLEARANCE of one, so a road is always walkable.
    ROAD_SITE_CHUNK_RADIUS: int = 8
    # Blobs of packed earth laid closer together than they are wide, so the track reads as
    # one worn line rather than as stepping stones.
    ROAD_STEP: int = 16
    ROAD_WIDTH: tuple = (14, 22)
    ROAD_WOBBLE: int = 90
    ROAD_CLEARANCE: int = 55
    ROAD_COLOR: tuple = (128, 106, 76)


@dataclass(frozen=True)
class Villages:
    """Settlements the player finds by walking (game/entities/village.py).

    The world is endless, so villages are not a fixed list: each square region of
    REGION_CHUNKS x REGION_CHUNKS chunks picks at most one chunk to hold a settlement, which
    keeps neighbouring villages a long walk apart without any cross-region bookkeeping.
    A village found for the first time is generated once and then saved with the world
    (unlike a POI, which is cheap to rebuild from its chunk seed): its NPCs carry affinity,
    quests and shop stock, none of which survives being regenerated.
    """

    # Settlements are meant to be a find, not scenery: a bigger region and a lower chance
    # put a real stretch of wilderness between one and the next, which only works because
    # that wilderness has cover, landmarks and roads of its own (Scenery, PointsOfInterest).
    REGION_CHUNKS: int = 4
    REGION_CHANCE: float = 0.55
    # Two regions can both settle near their shared border; the later one stands down, so
    # there is always this much empty wilderness between one settlement and the next.
    MIN_GAP: int = 3500
    # Kept away from the chunk's own edges so the cluster stays inside its own region.
    CHUNK_MARGIN: int = 380
    # The starting town already sits here; no streamed village crowds it.
    MIN_DIST_FROM_SPAWN: int = 3000

    # Buildings sit on a loose grid around an open plaza, close enough to read as one
    # settlement, far enough apart for the doors (always on the south facade) to be usable.
    SLOT_W: int = 500
    SLOT_H: int = 520
    SLOT_JITTER: int = 30

    # Relative pick weight per settlement size, and what each one is made of.
    SIZE_WEIGHTS: tuple = (("hamlet", 5), ("village", 4), ("town", 2))
    COMPOSITION = {
        "hamlet": {"tavern": (0, 0), "shop": (0, 1), "house": (2, 3)},
        "village": {"tavern": (0, 1), "shop": (1, 1), "house": (3, 5)},
        "town": {"tavern": (1, 1), "shop": (1, 2), "house": (5, 7)},
    }
    # The village the player starts in, at the world centre.
    START_COMPOSITION = {"tavern": (2, 2), "shop": (3, 3), "house": (8, 8)}
    START_DISTANCE_FROM_CENTER: int = 900

    VILLAGERS_PER_HOME: tuple = (1, 2)

    # The plaza: an open patch of packed earth with a well in the middle.
    PLAZA_RADIUS: int = 150
    WELL_RADIUS: int = 34
    PLAZA_COLOR: tuple = (146, 118, 84)
    WELL_STONE: tuple = (142, 138, 130)

    # Walking this close to the plaza discovers the village (one toast, then its name
    # shows on the map).
    DISCOVER_DISTANCE: int = 420
    # A wilderness point of interest keeps this far from a village site, generated or not.
    MIN_DIST_FROM_POI: int = 1100


@dataclass(frozen=True)
class Fog:
    """Explored-ground memory behind the minimap (World.explored).

    The world is remembered as a coarse grid of cells, revealed around the player as they
    walk and never forgotten. Cells are deliberately big: the map is a record of roughly
    where you have been, not a survey.
    """

    CELL: int = 250
    REVEAL_RADIUS: int = 620


@dataclass(frozen=True)
class PointsOfInterest:
    """Wilderness landmarks scattered across the map, away from town (game/entities/poi.py).
    "ruins" is a smashable loot cache, better odds and rarity than a plain outdoor barrel
    since it takes more effort to find; "shrine" is a one-time gamble, prayed at for a
    blessing that sometimes turns out to be a curse;
    a "camp" rolls into either a bandit camp (guarded cache) or a traveller camp (a camper
    who trades and points the way), and either way its fire can be rested at once the camp
    is settled. "farmstead" is a second lootable cache with its own look; "graveyard",
    "watchtower" and "stones" are places rather than rewards, each saying what it is the
    first time it is walked up to; "signpost" reads out the way to somewhere unexplored.
    """

    # Points of interest stream in per chunk like the floor details, so the wilderness
    # keeps offering something to find however far out the player walks. At most one per
    # chunk, kept CHUNK_MARGIN away from the chunk's edges, which is what spaces
    # neighbouring chunks' landmarks apart without any cross-chunk bookkeeping.
    PER_CHUNK_CHANCE: float = 0.7
    CHUNK_MARGIN: int = 260
    MIN_DIST_FROM_BUILDING: int = 400
    MIN_DIST_FROM_CENTER: int = 900
    SIZE: int = 46
    HIT_RADIUS: int = 34
    # Relative pick weight among kinds scattered across the wilderness. The three that
    # can be acted on (a cache to force, a camp to clear or trade at, a shrine to pray at)
    # stay the most common; the rest are there so that walking out finds a place rather
    # than the same three landmarks over and over.
    KIND_WEIGHTS: tuple = (
        ("ruins", 4),
        ("camp", 3),
        ("shrine", 3),
        ("farmstead", 3),
        ("graveyard", 2),
        ("watchtower", 2),
        ("stones", 2),
        ("signpost", 2),
    )

    # A landmark shows its flavor line the first time the player gets this close. A
    # shrine's line always ends with what a shrine is for, because a landmark that never
    # says what it does is a landmark the player walks past forever.
    DISCOVER_DISTANCE: int = 160
    # What each of the quiet landmarks says the first time it is reached. A signpost says
    # nothing here: it reads out directions to somewhere unexplored instead, like a camper.
    LANDMARK_MESSAGES = {
        "farmstead": (
            "An abandoned farmstead. Whoever worked this field left in a hurry.",
            "Fallen fences and a caved-in barn. Something worth taking may still be inside.",
        ),
        "graveyard": (
            "A wilderness graveyard. The names on the stones have worn away.",
            "Old graves, dug well away from any village. Best not linger after dark.",
        ),
        "watchtower": (
            "A ruined watchtower, its stair long collapsed.",
            "This tower watched the road once. Nobody has climbed it in years.",
        ),
        "stones": (
            "Standing stones in a rough circle, humming faintly.",
            "These stones were raised on purpose, a very long time ago.",
        ),
    }
    SHRINE_MESSAGES: tuple = (
        "An old shrine, worn smooth by countless hands.",
        "Faded offerings lie at the foot of this shrine.",
        "The carvings on this shrine predate any living memory.",
        "Someone has left a wilted flower at this shrine.",
    )
    SHRINE_EXPLANATION: str = "Pray at it (E) for a blessing, but the old gods are not always kind."

    # Praying is a gamble taken once per shrine: mostly a timed blessing, sometimes the
    # shrine takes something instead.
    SHRINE_PRAY_DISTANCE: int = 120
    SHRINE_CURSE_CHANCE: float = 0.3
    # (buff effect, magnitude, seconds, message). The effects are the potion buffs, read
    # back by the same multipliers, so a blessing needs no machinery of its own.
    SHRINE_BLESSINGS: tuple = (
        ("strength", 1.35, 45.0, "The shrine's warmth settles in your arms: you strike harder."),
        ("swiftness", 1.30, 45.0, "Your feet feel light. The shrine speeds your step."),
        ("stoneskin", 7, 45.0, "Your skin hardens like the shrine's own stone."),
    )
    # (curse kind, message). "weakness" is the same Shaken timer dying leaves behind,
    # "tithe" takes coins, "wound" takes health on the spot.
    SHRINE_CURSES: tuple = (
        ("weakness", "The shrine drinks something out of you. You feel shaken."),
        ("tithe", "The offering bowl empties your purse: {amount} coins gone."),
        ("wound", "Old stone cuts back. Something unseen tears at you."),
    )
    SHRINE_CURSE_WEAKNESS_S: float = 40.0
    SHRINE_CURSE_TITHE_FRAC: float = 0.2
    SHRINE_CURSE_WOUND_FRAC: float = 0.2

    # A cache is stone and iron banding, not a barrel: it takes real work to open.
    CACHE_HP: int = 45
    CACHE_COIN_MIN: int = 8
    CACHE_COIN_MAX: int = 22
    CACHE_ITEM_CHANCE: float = 0.5

    # Which kind of camp this one is, rolled from its id so it never changes under the
    # player: a bandit camp to clear out, or a traveller camp to trade at.
    CAMP_BANDIT_CHANCE: float = 0.6
    # Bandits posted around the fire, plus a leader rolling its kind as if it stood this
    # much deeper into the wilds, so a camp is a real fight rather than one stray wolf.
    CAMP_GUARD_MIN: int = 2
    CAMP_GUARD_MAX: int = 3
    CAMP_GUARD_SPREAD: int = 130
    CAMP_LEADER_DANGER_BONUS: int = 1400
    # Nothing hostile within this far of the fire: the bandit cache can be broken open and
    # either camp can be rested at. This is the whole gate, so despawns and reloads can't
    # leave a camp permanently locked.
    CAMP_CLEAR_RADIUS: int = 340
    REST_DISTANCE: int = 130
    # A fire patches you up, it doesn't make you new: part of your health back, and that
    # particular fire won't serve you again for a while. Otherwise every cleared camp is
    # a health button you can stand next to and spam.
    REST_HEAL_FRAC: float = 0.6
    REST_COOLDOWN_S: float = 300.0
    # A camper trades out of their pack: stock rolled locally, no LLM call in the wilds.
    CAMPER_STOCK_SIZE: int = 5
    # How far a camper's directions look for something the player hasn't walked to yet.
    HINT_CHUNK_RADIUS: int = 4
    HINT_MIN_DISTANCE: int = 700
