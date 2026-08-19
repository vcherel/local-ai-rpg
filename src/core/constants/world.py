from dataclasses import dataclass


@dataclass(frozen=True)
class World:
    WORLD_SIZE: int = 5000
    # How far a monster notices the player and gives chase. Deliberately wider than the
    # screen's half-width: the wilderness should come at you rather than be walked past.
    DETECTION_RANGE = 700

    # How many people a settlement holds follows from its buildings (Villages), not from a
    # world-wide count: the world is endless, so there is no total to fix.
    #
    # How many monsters roam is not world-wide either: it follows where the player is
    # standing, ramping from the near cap on the starting town's doorstep to the far cap
    # out past ROAMING_CAP_FAR_DISTANCE. The safest ground in the game shouldn't be
    # stocked like the deep wilds. A new world is created holding the *near* cap, since
    # everything placed at creation lands within despawn range of the spawn point.
    #
    # The ramp is deliberately long and eased (ROAMING_CAP_CURVE, an exponent on the
    # distance fraction): the first walk out of town is meant to be quiet enough to learn
    # the game in, and the crowding is meant to arrive at the same depth the tougher kinds
    # do, not a thousand pixels out.
    ROAMING_CAP_NEAR: int = 16
    ROAMING_CAP_FAR: int = 150
    ROAMING_CAP_FAR_DISTANCE: int = 6500
    ROAMING_CAP_CURVE: float = 2.0

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
    INITIAL_SPAWN_MIN_DISTANCE: int = 1400
    # Nothing hostile is ever spawned within this radius of the world centre, which is where
    # the player starts and respawns. Comfortably past the starting village's own radius, so
    # standing in town produces no respawns at all rather than a ring at its boundary: the
    # player has to walk out to find the fight. Kept equal to INITIAL_SPAWN_MIN_DISTANCE so
    # world creation and respawning follow the one rule.
    SAFE_RADIUS: int = 1400
    # ...and none within this much of any other settlement's edge either, so a monster never
    # materialises pressed against the houses.
    VILLAGE_SPAWN_MARGIN: int = 400
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
    # A deflection is held for this long once taken: without it a monster re-picks a side
    # every frame at the seam of an obstacle and shivers on the spot instead of walking
    # round it. Probes are also sampled along their length rather than at the tip alone,
    # so a thin wall between the monster and a clear point beyond it still counts.
    STEER_COMMIT_MS: int = 450
    STEER_PROBE_SAMPLES: int = 3
    # How far off the straight line a detour will look for a way round a clump of trees.
    # Past this the wood is not an obstacle any more, it is the terrain, and steering has
    # to deal with it a trunk at a time.
    SCENERY_DETOUR_RANGE: int = 520

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

    # How often the game saves itself while it is being played. The world is also written
    # at the moments worth not replaying (a tunnel entered or left, a night slept through,
    # a quest handed in, a death), so this is the floor under all of them rather than the
    # only thing standing between the player and a lost hour.
    AUTOSAVE_INTERVAL_S: float = 300.0

    # How many rings World.free_spot_near searches before giving up. Each ring is one body
    # diameter farther out, so this covers a building's whole footprint and then some.
    FREE_SPOT_MAX_RINGS: int = 24

    # How many of those rings World.unstick is allowed, which is deliberately far fewer.
    # A body standing inside a solid is meant to step out of what it is in, not to be
    # teleported across the house it was embedded in.
    UNSTICK_RINGS: int = 4

    # How far World.safe_spot_near keeps the player from anything hostile when placing them.
    # Well past every melee reach, so whatever is standing on the spawn point cannot swing
    # the moment the player arrives.
    SAFE_SPOT_CLEARANCE: int = 350

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
    # How fast the caravan works its way down the road, in world pixels a second. Slow: the
    # point is that they are somewhere else next time, not that they are hard to catch.
    MERCHANT_TRAVEL_SPEED: float = 26.0

    TREASURE_MIN_DIST: int = 300
    TREASURE_MAX_DIST: int = 600

    BLOOD_NIGHT_DURATION_MS: int = 120_000
    BLOOD_NIGHT_RESPAWN_MULT: float = 3.0
    BLOOD_NIGHT_DROP_MULT: float = 2.0
    # How long the blood night takes to come on and to bleed back out, at each end of its
    # duration. Everything it changes (the sky, the respawn rate, the loot) is scaled by
    # that ramp, so the world visibly boils up instead of the pressure arriving a frame
    # before the colour does.
    BLOOD_NIGHT_FADE_MS: int = 12_000


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
    # The danger bonus is capped at a fraction of how far out the spawn already is, so
    # night deepens the wilds instead of importing them: on the starting ring's edge it is
    # worth a few hundred, out past the settled ring it is worth all of NIGHT_DANGER_BONUS.
    NIGHT_DANGER_BONUS: int = 1800
    NIGHT_DANGER_DISTANCE_FRAC: float = 0.35
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
    # Nobody has eyes in the back of their head: a villager only catches what happens inside
    # this wedge of their facing, which the game draws on the ground while the player is
    # standing over a chest or a bed. Waiting for someone to turn away is the whole skill.
    VIEW_CONE_DEG: float = 110.0
    # How long the one villager who catches the player stays angry about it. Shorter than a
    # whole settlement's anger: it is their chest, and it is only their business.
    THEFT_ANGER_S: float = 180.0
    # How far a villager has to move, and how far they have to turn, before the wedge drawn
    # on the ground is recast rather than reused (`World.vision_polygon`). A cone is a few
    # hundred raycasts, and somebody standing still sees the same thing they saw last frame.
    CONE_CACHE_MOVE: float = 6.0
    CONE_CACHE_TURN_DEG: float = 3.0


@dataclass(frozen=True)
class Buildings:
    # How many of each a settlement holds is set per village size (Villages.COMPOSITION),
    # not here: buildings only ever exist as part of a village now.

    # (width range, height range) per kind. The landmark ruin has no door and no interior.
    # A house/shop/tavern's footprint is also its interior room now (no separate coordinate
    # space), so these are sized to hold a walkable room with furniture, not just a facade.
    # Deliberately wide ranges on both axes and rolled independently, so a street holds a
    # long hall beside a squat cottage rather than four copies of the same square. The
    # floor still has to hold the furniture, which is what sets the lower bounds.
    SIZES = {
        "house": ((290, 420), (250, 360)),
        "shop": ((310, 430), (260, 350)),
        "tavern": ((400, 520), (320, 430)),
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

    INTERACT_DISTANCE: int = 120

    # Sleeping. Nobody climbs into a bed with something hostile this close, and the night
    # is not skipped instantly: the screen fades out and back over SLEEP_FADE_MS while the
    # sky and every clock in the world run forward to just after dawn, so hours passing is
    # something the player watches rather than something they infer from the tint.
    SLEEP_SAFE_RADIUS: int = 420
    SLEEP_FADE_MS: int = 1500
    SLEEP_WAKE_PROGRESS: float = 0.02

    # Everything in a room that can be taken apart, and what it costs to do it. A bed and a
    # chest are deliberately absent: both are mechanics (the one full rest in the game, and
    # somebody's savings) rather than props, and a player who smashed either would only have
    # removed something they wanted. What is here pays nothing but splinters, apart from the
    # two that hold wares.
    FURNITURE_HP = {"crate": 22, "shelf": 16, "table": 26, "chair": 12, "counter": 34}
    # The ones with something in them: the same odds a shop crate has always had.
    FURNITURE_LOOT: tuple = ("crate", "shelf")
    WINDOW_HP: int = 10
    # Smashing a shop crate always yields a few coins and sometimes a common item.
    CRATE_COIN_MIN: int = 1
    CRATE_COIN_MAX: int = 3
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
class Tunnels:
    """The dug-out under a village well (game/entities/tunnel.py).

    Not a separate game: a tunnel is a handful of rooms carved out of the same world space
    everything else stands in, only a very long way from any ground that is ever walked on,
    which is what lets movement, collision, combat and loot work down there without knowing
    they have gone underground. What makes it feel like somewhere else is that nothing
    streams in around it: no sky, no wilderness, no wandering monsters, and no light except
    what the player carries.
    """

    # Not every well goes anywhere. A well that is only a well is what makes finding one
    # that isn't worth the walk over to look.
    CHANCE: float = 0.55
    # The corner of world space the tunnels are laid out in, one grid slot per village
    # chunk. Far enough out that nothing generated on the surface can ever reach it.
    ORIGIN: int = 1_000_000
    SPACING: int = 20_000

    ROOMS: tuple = (3, 5)
    ROOM_SIZE: tuple = (420, 640)
    ROOM_GAP: tuple = (640, 900)
    # Comfortably wider than the broadest thing that walks: a corridor nothing fits down is
    # a wall, and collision here is the floor rectangles rather than the walls between them.
    CORRIDOR_WIDTH: int = 170

    # What lives down there, rolled once per tunnel and kept like a bandit camp's garrison:
    # the dark is a place to clear, and clearing it has to stay cleared.
    GUARDS: tuple = (3, 5)
    # They roll their kind as if the tunnel stood this much deeper into the wilds, so what
    # is waiting under a village is not what is wandering the fields above it.
    GUARD_DANGER_BONUS: int = 2800
    HOARD: tuple = (2, 3)

    # How far the player can see down there, and how black it is past that.
    LIGHT_RADIUS: int = 340
    DARKNESS: int = 240
    # How close to the shaft the player has to be to climb back out.
    EXIT_RADIUS: int = 90

    # Light enough to read as floor once the player's own light is on it: everything down
    # here is seen through the dark overlay, so the stone has to start well above black.
    FLOOR_COLOR: tuple = (124, 110, 94)
    ROCK_COLOR: tuple = (30, 27, 24)
    LADDER_COLOR: tuple = (126, 92, 56)


@dataclass(frozen=True)
class Traps:
    """Bear traps set by hunters in the woods around a settlement (game/entities/traps.py).

    Nobody laid them for the player and nobody is watching them: a trap shuts on whatever
    stands on it first, a deer, a wolf chasing something of its own, a monster chasing the
    player, or the player. Most of what it costs is the seconds it holds you still, which
    is the only thing in the world that stops something moving without a wall in the way.
    """

    # The hunting ground of a settlement: past its own fields, inside a morning's walk.
    # Nothing is trapped out in the deep wilds, where nobody lives to come and check it.
    MIN_FROM_VILLAGE: int = 900
    MAX_FROM_VILLAGE: int = 2400
    # About half the chunks of that band hold one, which works out at a handful of traps
    # ringing a settlement: enough that the woods around a village have to be watched,
    # few enough that walking out of one is not a minefield.
    PER_CHUNK: tuple = (0, 1)
    # Off the doorstep of anything already standing there, and out of the water.
    CLEARANCE: int = 150

    # Half hidden in the grass, so it is caught sight of rather than read at a glance: what
    # gives it away is the ring of jaws, and only from about as far off as it can be avoided.
    SIZE: int = 26
    TRIGGER_RADIUS: int = 26
    DAMAGE: int = 16
    HOLD_MS: int = 2400
    JAW_COLOR: tuple = (118, 116, 112)
    PLATE_COLOR: tuple = (86, 84, 80)
    SPRUNG_COLOR: tuple = (96, 92, 86)


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
    # A river is laid down in three passes rather than three circles per blob: the blobs
    # overlap each other, so a per-blob bank ring paints over its neighbour's deep middle
    # and the course reads as a row of scales. "river" carries the water itself and draws
    # the bank; the other two are decoration standing at the same points, nothing more.
    GROUND_KINDS: tuple = (
        "patch",
        "pond",
        "lake",
        "river",
        "river_body",
        "river_deep",
        "path",
        "bridge",
        "pebbles",
        "grass",
        "flowers",
    )
    # The kinds the player wades through rather than walks over. A bridge sits on top of
    # them in the draw order for the same reason it does in the world.
    WATER_KINDS: tuple = ("pond", "lake", "river")

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
    # A lake is a pond big enough to be worth walking round, rolled in the biomes that
    # hold water. Same drawing, same swim rules: only the scale differs.
    LAKE_RADIUS: tuple = (200, 380)
    LAKE_CHANCE = {"wetland": 0.55, "plain": 0.12, "forest": 0.1, "rocky": 0.06}

    # Rivers. Nothing about water blocks: it is crossed slowly (see SWIM_SPEED), so a river
    # is a delay and an exposure rather than a wall, and a bridge is worth walking to.
    # Lanes run on a coarse multiple of the chunk grid, each one a pure function of its
    # index like everything else streamed, so a chunk lays down its own stretch of river
    # with no idea what its neighbours did.
    RIVER_LANE_CHUNKS: int = 9  # one river every this many chunk columns/rows
    RIVER_LANE_CHANCE: float = 0.7  # not every lane carries one, so the map isn't a grid
    # Blobs laid well inside each other's width, so the channel reads as running water
    # rather than as a string of beads.
    RIVER_STEP: int = 12
    RIVER_WIDTH: tuple = (52, 78)
    RIVER_WOBBLE: int = 420  # how far the course wanders off a straight line
    RIVER_BANK_CLEARANCE: int = 30  # no trunk or boulder stands this close to the water
    # A river bends around a settlement's centre by this much rather than running through
    # its plaza: a village's radius plus a margin of dry ground.
    RIVER_VILLAGE_CLEARANCE: int = 820

    # Crossings. One is laid at fixed intervals along a river whatever else is nearby, so a
    # bridge is always findable; another wherever a road meets the water, since that is
    # where anyone would have built one.
    BRIDGE_INTERVAL: int = 2400
    BRIDGE_LENGTH: int = 130  # along the river; comfortably wider than the water itself
    BRIDGE_WIDTH: int = 76
    BRIDGE_COLOR: tuple = (132, 100, 66)
    BRIDGE_PLANK_COLOR: tuple = (108, 80, 52)
    BRIDGE_RAIL_COLOR: tuple = (92, 66, 42)
    # Nothing solid stands this close to a deck. A crossing walled in by a trunk at the end
    # of it is worse than no crossing at all, since the player walked to it.
    BRIDGE_CLEARANCE: int = 45

    # Water is drawn from the bank inward: shallow edge, body, deep middle.
    WATER_COLORS: tuple = ((70, 96, 96), (58, 106, 122), (96, 148, 158))

    # What crossing water costs. The player wades at SWIM_SPEED, climbing toward
    # SWIM_SPEED_MAX as the swimming stat levels; everything else in the world is stuck at
    # SWIM_SPEED for good, which is what makes a river an answer to a chase and keeps a
    # bridge the fast way over for the whole game.
    SWIM_SPEED: float = 0.35
    SWIM_SPEED_MAX: float = 0.75

    # Roads: each village site is joined to its nearest neighbour, and the chunk being
    # generated lays down the packed earth of whatever passes through it. Nothing that
    # blocks may stand within CLEARANCE of one, so a road is always walkable.
    ROAD_SITE_CHUNK_RADIUS: int = 8
    # Blobs of packed earth laid closer together than they are wide, so the track reads as
    # one worn line rather than as stepping stones.
    ROAD_STEP: int = 16
    ROAD_WIDTH: tuple = (14, 22)
    # A road runs thousands of pixels between two settlements, so the bend has to be worth
    # that length: one long wave that grows with the distance, plus a shorter one over it.
    ROAD_WOBBLE: int = 260
    ROAD_WOBBLE_FULL: int = 4000  # the length at which a road wanders by the full wobble
    ROAD_DETAIL: float = 0.22  # amplitude of the shorter wave, as a fraction of the wobble
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

    # How long a settlement stays angry after the player strikes one of its people, and the
    # ceiling a second offence can push that to. Anger is a countdown now rather than a
    # permanent state: a scuffle is something a village lives down, so the player is not
    # locked out of a shop for the rest of the save over one stray swing. Killing someone is
    # the exception, and it is not on this clock at all (World.hold_grudge).
    ANGER_S: float = 240.0
    ANGER_CAP_S: float = 900.0

    # A village defends itself. Only some of its people take up arms (rolled per NPC off
    # their home, so the same house always sends the same person out); the rest run for the
    # nearest door and shut it. A monster inside a settlement's grounds plus this margin is
    # an intruder, a militiaman walks this far from where they stand to meet one, and anyone
    # else bolts once one is this close.
    MILITIA_FRACTION: float = 0.45
    DEFEND_MARGIN: float = 300.0
    DEFEND_RADIUS: float = 620.0
    PANIC_RADIUS: float = 520.0

    # The same split decides what an angry village does about the player, so a mob is not a
    # column of identical farmers. The militia close and swing; everyone else keeps this far
    # back and throws whatever is to hand, which is a real threat in numbers and impossible
    # to answer with a sword. Anyone cut down to this fraction of their health has had
    # enough and runs for a door, so a mob thins out as it loses rather than fighting to
    # the last farmer.
    MOB_STANDOFF: float = 250.0
    MOB_STONE_RANGE: float = 340.0
    MOB_STONE_DAMAGE: int = 5
    MOB_STONE_COOLDOWN_MS: tuple = (1400, 2600)
    ROUT_HP_FRAC: float = 0.35

    # A town is worth defending, and a hamlet has nothing to defend with: only the largest
    # settlements (and the starting town) stand a palisade. The wall is a square ring set
    # this far outside the last row of houses, with a gate cut in the middle of each side,
    # so there is always a way in from whichever direction the player or a pack arrives,
    # and the wall itself is something to be routed round rather than a box with one door.
    # A watchtower stands at each corner: solid, and the one piece of a village that reads
    # from a long way off.
    WALLED_SIZES: tuple = ("town",)
    WALL_MARGIN: int = 150
    WALL_THICKNESS: int = 26
    GATE_WIDTH: int = 190
    TOWER_RADIUS: int = 46
    WALL_COLOR: tuple = (118, 92, 62)
    WALL_TOP: tuple = (146, 116, 78)
    TOWER_STONE: tuple = (136, 132, 124)
    GATE_POST: tuple = (92, 70, 46)
    # Somebody stands at each gate and each tower, always armed and always willing. They
    # hold their post rather than strolling the way a villager does.
    GUARDS_PER_GATE: int = 1
    GUARD_POST_RADIUS: int = 70
    GUARD_COLOR: tuple = (92, 104, 126)

    # A merchant's shelf refills on a clock rather than staying whatever the model wrote at
    # world generation. What is already out stays out and the delivery tops the stock back
    # up to SHOP_STOCK_TARGET, so buying a shop empty is worth doing and coming back later
    # is worth doing too. Rolled locally (game.loot.roll_shop_stock): a fresh LLM call per
    # restock is exactly the cost the batched generation exists to avoid.
    SHOP_RESTOCK_S: float = 600.0
    SHOP_STOCK_TARGET: int = 10


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
    # Nobody pitches a camp or raises a shrine in a river.
    MIN_DIST_FROM_WATER: int = 120
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
    # Kept short on purpose: the two are toasted as one line, and a paragraph on the screen
    # is read as furniture rather than as something the player just found.
    SHRINE_MESSAGES: tuple = (
        "An old shrine, worn smooth.",
        "A shrine, its offerings long faded.",
        "A shrine older than any memory.",
        "A shrine, one wilted flower at its foot.",
    )
    SHRINE_EXPLANATION: str = "Pray (E): the old gods are not always kind."

    # Praying is a gamble taken once per shrine: mostly a timed blessing, sometimes the
    # shrine takes something instead.
    SHRINE_PRAY_DISTANCE: int = 120
    SHRINE_CURSE_CHANCE: float = 0.3
    # (buff effect, magnitude, seconds, message). The effects are the potion buffs, read
    # back by the same multipliers, so a blessing needs no machinery of its own.
    SHRINE_BLESSINGS: tuple = (
        ("strength", 1.35, 45.0, "The shrine warms your arms: you strike harder."),
        ("swiftness", 1.30, 45.0, "Your feet feel light."),
        ("stoneskin", 7, 45.0, "Your skin hardens like the stone."),
    )
    # (curse kind, message). "weakness" is the same Weakened timer dying leaves behind,
    # "tithe" takes coins, "wound" takes health on the spot.
    SHRINE_CURSES: tuple = (
        ("weakness", "The shrine drinks something out of you."),
        ("tithe", "The bowl takes its tithe: {amount} coins gone."),
        ("wound", "Old stone cuts back."),
    )
    SHRINE_CURSE_WEAKNESS_S: float = 40.0
    SHRINE_CURSE_TITHE_FRAC: float = 0.2
    SHRINE_CURSE_WOUND_FRAC: float = 0.2

    # A cache is stone and iron banding, not a barrel: it takes real work to open.
    CACHE_HP: int = 45
    CACHE_COIN_MIN: int = 6
    CACHE_COIN_MAX: int = 16
    CACHE_ITEM_CHANCE: float = 0.5

    # Which kind of camp this one is, rolled from its id so it never changes under the
    # player: a bandit camp to clear out, or a traveller camp to trade at.
    CAMP_BANDIT_CHANCE: float = 0.6
    # Bandits posted around the fire, plus a leader rolling its kind as if it stood this
    # much deeper into the wilds, so a camp is a real fight rather than one stray wolf.
    CAMP_GUARD_MIN: int = 2
    CAMP_GUARD_MAX: int = 3
    CAMP_GUARD_SPREAD: int = 130
    CAMP_LEADER_DANGER_BONUS: int = 2400
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
