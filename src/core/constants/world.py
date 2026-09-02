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
    ROAMING_CAP_NEAR: int = 6
    ROAMING_CAP_FAR: int = 150
    ROAMING_CAP_FAR_DISTANCE: int = 6500
    ROAMING_CAP_CURVE: float = 2.0

    # Slain monsters are replenished over time so the world never empties out.
    RESPAWN_INTERVAL_MS: int = 2200
    # New monsters spawn at least this far from the player so they never pop into view.
    # The screen's half-diagonal is ~1006px, so anything under that can appear on camera.
    SPAWN_MIN_DISTANCE: int = 1500
    # ...and at most this far, so they still show up as the player explores.
    SPAWN_MAX_DISTANCE: int = 2100
    # Monsters left this far behind despawn, freeing their slot to respawn near the player.
    DESPAWN_DISTANCE: int = 3400
    # Monsters placed at world creation start at least this far from the player spawn point.
    INITIAL_SPAWN_MIN_DISTANCE: int = 2200
    # Nothing hostile is ever spawned within this radius of the world centre, which is where
    # the player starts and respawns. Comfortably past the starting village's own radius, so
    # standing in town produces no respawns at all rather than a ring at its boundary: the
    # player has to walk out to find the fight. Kept equal to INITIAL_SPAWN_MIN_DISTANCE so
    # world creation and respawning follow the one rule.
    SAFE_RADIUS: int = 2200
    # ...and none within this much of any other settlement's edge either, so a monster never
    # materialises pressed against the houses.
    VILLAGE_SPAWN_MARGIN: int = 400
    # How far apart the members of a pack kind (MonsterKind.group) are scattered on spawn.
    PACK_SPREAD: int = 110

    # Obstacle avoidance: a monster probes this many steps ahead (never less than
    # STEER_MIN_PROBE past its own radius) so it turns away from a wall early instead
    # of pressing into it.
    STEER_LOOKAHEAD: float = 12.0
    STEER_MIN_PROBE: int = 26
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
    # What each kind of floor detail is: its colour and how big a dot it makes. A table
    # rather than a branch in the renderer, so a new kind of speck on the ground is a row
    # here and a name in the roll, the way every other look-per-kind in the game works.
    FLOOR_DETAILS = {
        "stone": ((100, 100, 100), 3),
        "flower": ((196, 108, 132), 2),
    }
    # Chunks within this many chunks of the player are generated...
    CHUNK_LOAD_RADIUS: int = 2
    # ...and stay loaded until this much farther away, to avoid load/unload thrashing at the edge.
    CHUNK_KEEP_RADIUS: int = 3
    # How many steps of chunk building a single frame is allowed. Crossing a chunk border
    # brings a whole edge of the load square into range at once, and building all of it on
    # the frame the border was crossed is a visible stutter every thousand paces. The rest is
    # built over the frames that follow, nearest first: they are two chunks away, and the
    # player walks at a few hundred paces a second. A chunk is two steps, its ground and then
    # what grows on it (`WorldStreaming._load_chunk`, `_grow_chunk`).
    CHUNK_LOADS_PER_FRAME: int = 1
    # ...except within this many chunks of the player, which is ground they could walk onto
    # before the queue reaches it. That is built on the spot whatever the budget says.
    CHUNK_URGENT_RADIUS: int = 1
    # And however many steps are allowed, a frame stops starting them once it has spent this
    # long building. A step is a handful of milliseconds where the ground is grass and a
    # hundred where it turns out to hold a settlement, so counting steps alone still let
    # three cheap ones and an expensive one land on the same frame.
    CHUNK_BUILD_BUDGET_MS: float = 6.0

    # How many times the world's lore is asked for before the world gives up on having any.
    CONTEXT_ATTEMPTS: int = 2
    # Quoted by the prompts that ask about the world (village names, shop stock, boss names)
    # when the lore call came back with nothing readable in it. Never shown to the player
    # and never saved: it is here so a failed lore call costs the lore and nothing else, and
    # the next session asks for a real world again.
    FALLBACK_CONTEXT: str = (
        "The game takes place in a wide green wilderness of scattered villages, old ruins "
        "and roads nobody has walked in years."
    )

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

    # How much cheaper the other way round an obstacle must be before a chaser gives up the
    # corner it is already walking to (`World._detour_corner`). Both ways round cost within a
    # pixel of each other from anywhere near the middle of a wall, so with no margin at all
    # the answer flipped every frame and the chaser rocked on the spot instead of walking.
    ROUTE_SWITCH_MARGIN: float = 0.85

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

    # The banner an event that changes the rules opens with, and how long each end of it
    # spends fading. A toast says something happened; this says the night is different now.
    BANNER_DURATION_MS: float = 4200.0
    BANNER_FADE_MS: float = 900.0

    # Chance a treasure or blood night is preceded by a short lore warning instead of striking instantly.
    PRESAGE_CHANCE: float = 0.5
    PRESAGE_DELAY_RANGE_S: tuple = (8, 15)
    PROPHECY_DELAY_RANGE_S: tuple = (20, 40)

    # A caravan is met on the road, never watched into existence: the band starts past the
    # corner of the screen (half the diagonal of UI.WIDTH x UI.HEIGHT is a little over
    # 1000), so the pair are stood up out of sight and walked into view. The same distance
    # is what they have to be past before they are taken away again.
    MERCHANT_MIN_DIST: int = 1150
    MERCHANT_MAX_DIST: int = 1700
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

    # How dark it has to be before a village calls it a night: its people leave off what
    # they were doing and walk home, and its gates lean shut. Lower than `is_night` (0.5)
    # on purpose, so the street empties through dusk and is empty by dark rather than
    # everyone turning on their heel at the same instant.
    CURFEW_DARKNESS: float = 0.35

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
    standing outside and which wall they are standing at: a room is open along its facade
    and shut everywhere else, which makes an empty street, the dark, or the back of a house
    the way to rob it."""

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
    # Sleeping in a bed is not an instant somebody either saw or missed: it is a night, and
    # a settlement's people come and go through one. So the bed is answered by who is near
    # it by morning rather than by who was looking at it (`WorldSocial.squatter_witness`),
    # which is what makes a tavern room something taken rather than something free.
    SQUAT_WITNESS_RADIUS: float = 620.0


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
    # Some buildings are an L rather than a box: a second rect growing out of the back half
    # of one side, so the facade stays one straight wall and the door, the windows and the
    # awning know nothing about it. Rolled from the building's own id like its roof, and the
    # room inside follows the shape (`Building.footprint`, `interior_rects`).
    WING_KINDS: tuple = ("house", "shop", "tavern")
    WING_CHANCE: float = 0.4
    WING_DEPTH: tuple = (110, 180)
    WING_LENGTH_FRAC: tuple = (0.45, 0.8)
    # The neck between the two halves is kept this clear of furniture, the same rule the
    # corridor in from the door follows: a table dropped in it walls the wing off.
    WING_NECK_CLEAR: int = 80

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
    # An open leaf standing out against the facade: how thick it is, and how far out of the
    # wall it swings as a fraction of the doorway's own width.
    DOOR_LEAF_THICKNESS: int = 8
    DOOR_LEAF_SWING: float = 0.6

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
    FURNITURE_HP = {"crate": 22, "shelf": 16, "table": 26, "chair": 12, "counter": 34, "bed": 30}
    # The ones with something in them: the same odds a shop crate has always had.
    FURNITURE_LOOT: tuple = ("crate", "shelf")
    WINDOW_HP: int = 10
    # Smashing a shop crate always yields a few coins and sometimes a common item.
    CRATE_COIN_MIN: int = 1
    CRATE_COIN_MAX: int = 3
    CRATE_ITEM_CHANCE: float = 0.2

    # Two windows flank the door on every non-landmark building's front facade;
    # broken ones stay broken (per-building index set, like broken crates). Wide enough for
    # a body to get through, because that is what a broken one is for: the hole a shattered
    # pane leaves is the way into a house whose door is locked, so the pane on the wall has
    # to be the size of the gap the wall loses.
    WINDOW_W: int = 46
    WINDOW_H: int = 20
    WINDOW_Y_FROM_BOTTOM: int = 45
    WINDOW_X_FROM_DOOR: int = 40
    WINDOW_HIT_RADIUS: int = 18
    # Some houses are locked, rolled off the building's own id so the same one is always
    # locked and the player can learn which. A locked door never opens for the player from
    # outside: the answer is a window, and once inside the door is unbarred from the near
    # side for good. Shops and taverns are never locked, since a shut shop is a merchant
    # the player cannot trade with rather than a puzzle.
    LOCK_KINDS: tuple = ("house",)
    LOCK_CHANCE: float = 0.3

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
    """The dark under the world: the dug-out beneath a village well, and the cave mouth out
    in the wilds that leads into the same kind of place (game/entities/tunnel.py).

    Not a separate game: a tunnel is a handful of rooms carved out of the same world space
    everything else stands in, only a very long way from any ground that is ever walked on,
    which is what lets movement, collision, combat and loot work down there without knowing
    they have gone underground. What makes it feel like somewhere else is that nothing
    streams in around it: no sky, no wilderness, no wandering monsters, and no light except
    what the player carries.
    """

    # Not every well goes anywhere. A well that is only a well is what makes finding one
    # that isn't worth the walk over to look. A cave mouth always does: it is a landmark
    # the player walked out into the wilds to find, not one of a settlement's fittings.
    CHANCE: float = 0.55
    # The corner of world space the tunnels are laid out in, one grid slot per chunk. Far
    # enough out that nothing generated on the surface can ever reach it, and the caves
    # offset again from the wells so a landmark and a village sharing a chunk never share
    # the ground under it.
    ORIGIN: int = 1_000_000
    SPACING: int = 20_000
    CAVE_OFFSET: int = 400_000

    # How big the place is, by the way in. A cave is a real descent rather than a cellar
    # somebody dug: more rooms, more guards, and the same hoard at the end of it.
    ROOMS = {"well": (3, 5), "cave": (5, 8)}
    ROOM_SIZE: tuple = (420, 640)
    ROOM_GAP: tuple = (640, 900)
    # Comfortably wider than the broadest thing that walks: a corridor nothing fits down is
    # a wall, and collision here is the floor rectangles rather than the walls between them.
    CORRIDOR_WIDTH: int = 170

    # What lives down there, rolled once per tunnel and kept like a bandit camp's garrison:
    # the dark is a place to clear, and clearing it has to stay cleared.
    GUARDS = {"well": (3, 5), "cave": (5, 8)}
    # They roll their kind as if the tunnel stood this much deeper into the wilds, so what
    # is waiting under a village is not what is wandering the fields above it.
    GUARD_DANGER_BONUS: int = 2800
    # Nothing is stood up this close to the shaft. A garrison scattered over the whole floor
    # put somebody at the foot of the ladder often enough that climbing down read as an
    # ambush the player was given no chance to see coming.
    ENTRANCE_CLEARANCE: int = 260
    HOARD: tuple = (2, 3)
    # The hoard is rolled with this much luck per thousand paces the way in stands from the
    # world centre, so the dark under a far-flung cave is worth the walk to it and the one
    # under the starting town is not. The same lean-the-ladder-up trick the shops use.
    HOARD_LUCK_PACES: float = 1000.0
    HOARD_LUCK_PER_PACES: float = 0.16
    # The last room of a cave is a vault: a dead-end holding one guaranteed legendary box,
    # the one reward in the world that is not rolled for. Wells have none; a cellar under a
    # village is not an expedition.
    VAULT_RARITY: str = "legendary"
    # The bats that live in a cave, woken as a swarm the first time anyone walks in. Not a
    # fight so much as the cave objecting to being entered.
    BATS: tuple = (4, 7)
    # And what guards a vault, in a cave whose mouth stands at least this far from the world
    # centre: a warden, which is an ordinary boss placed in the dark. This is the one boss
    # in the game that is somewhere rather than roaming, so it is the one the player can go
    # looking for on purpose.
    WARDEN_MIN_DISTANCE: int = 6000

    # How far the player can see down there, and how black it is past that. Nothing outside
    # the light is seen at all: at 240 the far side of the cave stayed faintly legible,
    # which gave away the whole layout from the doorway.
    LIGHT_RADIUS: int = 340
    DARKNESS: int = 255
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
    # How close the player has to be to set a shut one again. Wider than the jaws, so the
    # prompt is offered from beside the trap rather than from on top of it.
    REARM_DISTANCE: int = 70
    # Steel jaws through a leg. It is meant to be the worst thing in the woods that is not
    # alive: what makes a trap frightening is that a careless walk out of town costs a real
    # part of the health bar and not only the seconds afterwards.
    DAMAGE: int = 30
    # Long enough that being caught is a real event rather than a stutter, because the
    # player is not meant to sit it out: every movement key pressed while the jaws are on
    # them works the foot loose by STRUGGLE_MS, so escaping is something they do. Anything
    # else the trap catches has no keys to press and simply waits out the whole hold.
    HOLD_MS: int = 4200
    STRUGGLE_MS: int = 260
    STRUGGLE_SHAKE: float = 3.0
    JAW_COLOR: tuple = (118, 116, 112)
    PLATE_COLOR: tuple = (86, 84, 80)
    SPRUNG_COLOR: tuple = (96, 92, 86)

    # What being caught looks like (core/screen_fx.py `TrapSnap`). A bite of health and a
    # few seconds of not moving is, on its own, a number and a body that has stopped
    # responding, which reads as the game freezing rather than as a trap. So the jaws shut
    # over the whole screen: in fast, held, then easing open again as the hold runs out.
    SNAP_FX_MS: float = 900.0
    SNAP_FX_BITE_FRAC: float = 0.18  # share of that spent slamming shut
    SNAP_FX_REACH: float = 0.22  # how far into the screen each jaw bites, as a share of it
    SNAP_FX_TEETH: int = 14
    SNAP_FX_SHAKE: float = 20.0
    SNAP_FX_HITSTOP_MS: float = 90.0


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
    # Water is laid down in three passes rather than three shapes per body: the blobs of a
    # course overlap each other and a river runs into a lake, so a bank drawn per body
    # paints over its neighbour's deep middle and the water reads as a row of scales. The
    # first kind of each body carries the water itself; the other two are decoration
    # standing at the same point, nothing more (see WATER_LAYERS).
    GROUND_KINDS: tuple = (
        "patch",
        "pond",
        "lake",
        "river",
        "pond_body",
        "lake_body",
        "river_body",
        "pond_deep",
        "lake_deep",
        "river_deep",
        "path",
        "road_verge",
        "road",
        "bridge",
        "pebbles",
        "grass",
        "flowers",
    )
    # Every body of water stands three times, once per layer, and the layer is the kind:
    # the bank of everything is laid down, then the body of everything, then the deep of
    # everything. Still water drawn body by body had the river's bank painted across the
    # middle of the lake it ran into, which is the same fault the river was split up for.
    WATER_LAYERS = {
        "pond": ("pond", "pond_body", "pond_deep"),
        "lake": ("lake", "lake_body", "lake_deep"),
        "river": ("river", "river_body", "river_deep"),
    }
    # How much of a body of water each of those three passes covers.
    WATER_LAYER_SCALE: tuple = (1.0, 0.9, 0.5)
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
    # The width a lane of average size runs at; a lane rolls its own scale on top, so the
    # map holds brooks and rivers rather than one width repeated everywhere.
    RIVER_WIDTH: tuple = (96, 138)
    RIVER_LANE_SCALE: tuple = (0.7, 2.1)
    RIVER_WOBBLE: int = 420  # how far the course wanders off a straight line
    RIVER_BANK_CLEARANCE: int = 30  # no trunk or boulder stands this close to the water
    # A river bends around a settlement's centre by this much rather than running through
    # its plaza: a village's radius plus a margin of dry ground.
    RIVER_VILLAGE_CLEARANCE: int = 820
    # ...and never closer than the settlement's own grounds plus this, since how far a
    # town reaches is its wall rather than a fixed number: a river ran straight through a
    # big one while a hamlet had it bowing politely around empty grass.
    RIVER_VILLAGE_MARGIN: int = 260

    # Crossings. One is laid at fixed intervals along a river whatever else is nearby, so a
    # bridge is always findable; another wherever a road meets the water, since that is
    # where anyone would have built one.
    BRIDGE_INTERVAL: int = 2400
    # A deck is laid across the water it actually spans (`_deck_length`), since how broad a
    # river is is rolled per lane: this is the shortest one ever built and how much wider
    # than the water any of them is, so there is a landing at each end.
    BRIDGE_MIN_LENGTH: int = 150
    BRIDGE_SPAN: float = 1.45
    BRIDGE_WIDTH: int = 76
    BRIDGE_COLOR: tuple = (132, 100, 66)
    BRIDGE_PLANK_COLOR: tuple = (108, 80, 52)
    BRIDGE_RAIL_COLOR: tuple = (92, 66, 42)
    # The rail down each side of a deck: drawn, and solid. A bridge is the one place the
    # water is walked over, and a crossing you can step off the side of is just a plank.
    BRIDGE_RAIL: int = 8
    # Nothing solid stands this close to a deck. A crossing walled in by a trunk at the end
    # of it is worse than no crossing at all, since the player walked to it.
    BRIDGE_CLEARANCE: int = 45
    # No two crossings stand closer than this. A lane lays one at fixed intervals and every
    # road that meets the water asks for one of its own, so the two used to end up as a
    # pair of bridges a few strides apart over the same stretch of river. The road wins the
    # argument about which way the deck lies: a crossing a track runs onto is laid along
    # the track, since a deck squared onto the current with a road arriving at it sideways
    # is a bridge nobody could walk over.
    BRIDGE_MIN_GAP: int = 900

    # Water is drawn from the bank inward: shallow edge, body, deep middle.
    WATER_COLORS: tuple = ((70, 96, 96), (58, 106, 122), (96, 148, 158))

    # What crossing water costs. The player wades at SWIM_SPEED, climbing toward
    # SWIM_SPEED_MAX as the swimming stat levels; everything else in the world is stuck at
    # SWIM_SPEED for good, which is what makes a river an answer to a chase and keeps a
    # bridge the fast way over for the whole game.
    SWIM_SPEED: float = 0.35
    SWIM_SPEED_MAX: float = 0.75

    # A canopy is overhead, so it is drawn in front of whatever stands under it and fades
    # out while something does: a wood the player can walk into and be lost inside is a
    # place to avoid rather than cover. The margin is how far past its own radius a canopy
    # counts as being over a body, since its lobes are rolled out past that radius.
    CANOPY_KINDS: tuple = ("tree", "pine")
    CANOPY_FADE_ALPHA: int = 105
    CANOPY_COVER_MARGIN: float = 1.35

    # Roads: every village site is joined to its nearest ROAD_LINKS neighbours, and the
    # chunk being generated lays down the packed earth of whatever passes through it.
    # Nothing that blocks may stand within CLEARANCE of one, so a road is always walkable.
    ROAD_SITE_CHUNK_RADIUS: int = 15
    # More than one link per settlement is what makes the map a network rather than a
    # chain, and the cap on a road's length is what keeps a lone village in the deep wilds
    # from being joined to a town half a world away by a road nobody would have cut. Never
    # longer than ROAD_SITE_CHUNK_RADIUS reaches, or a chunk in the middle of one would not
    # know the road existed.
    # Both grew with the gap between settlements (`Villages.MIN_GAP`): a road that cannot
    # reach the nearest neighbour is a village with no road at all, and the deep wilds were
    # meant to be sparse, not trackless.
    ROAD_LINKS: int = 3
    ROAD_MAX_LENGTH: int = 14000
    # How much dry ground a road keeps between itself and a settlement it is only passing:
    # its own two ends are met at the gate, anything else in the way is bowed around.
    ROAD_VILLAGE_CLEARANCE: int = 120
    # Blobs of packed earth laid closer together than they are wide, so the track reads as
    # one worn line rather than as stepping stones.
    ROAD_STEP: int = 16
    # A road between two settlements is the one track the player is meant to see from a
    # distance and follow: it is drawn wider than a footpath, in its own colour, with the
    # verge either side of it. A path out to a landmark is a line worn in the grass.
    ROAD_WIDTH: tuple = (26, 36)
    # A track is one worn line whose width swells and narrows as it goes, not a radius
    # rolled per blob: how much it swells, over how long, and the shorter wave over that
    # which keeps the edge from reading as a drawn curve.
    ROAD_SWELL: float = 0.14
    ROAD_SWELL_PERIOD: int = 520
    ROAD_EDGE_NOISE: float = 0.06
    ROAD_EDGE_PERIOD: int = 90
    # A road runs thousands of pixels between two settlements, so the bend has to be worth
    # that length: one long wave that grows with the distance, plus a shorter one over it.
    ROAD_WOBBLE: int = 260
    ROAD_WOBBLE_FULL: int = 4000  # the length at which a road wanders by the full wobble
    ROAD_DETAIL: float = 0.22  # amplitude of the shorter wave, as a fraction of the wobble
    ROAD_CLEARANCE: int = 55
    # The small things lying on the ground rather than making it: what a chunk scatters
    # over its floor once the broad patches are down. They are the only kinds kept off a
    # road's band and a settlement's lanes, since a patch is the ground itself and a road
    # laid over one loses nothing.
    DECOR_KINDS: tuple = ("grass", "flowers", "pebbles", "reeds")
    # How far off a settlement's lanes and its plaza that decoration keeps. Nothing solid
    # grows on village grounds at all; this is the tufts and the flowers, which do, and
    # which only have to stay off the trodden earth itself.
    STREET_CLEARANCE: int = 8
    ROAD_COLOR: tuple = (128, 106, 76)
    # The bigger road between two villages: warmer and lighter than a footpath, with a
    # trodden verge drawn under it so the width reads from across a field.
    ROAD_MAIN_COLOR: tuple = (146, 122, 88)
    ROAD_VERGE_COLOR: tuple = (114, 106, 72)
    ROAD_VERGE: int = 5

    # Footpaths: the tracks worn out to the landmarks, drawn exactly like a road but
    # narrower. A landmark joins the settlement it is nearest to, or, out where there is
    # none in reach, the next landmark along, so a string of them in the deep wilds is
    # walkable and a landmark with nothing near it keeps no path at all.
    PATH_WIDTH: tuple = (7, 11)
    PATH_CHUNK_RADIUS: int = 3
    PATH_MAX_LENGTH: int = 2600


@dataclass(frozen=True)
class Fog:
    """Explored-ground memory behind the minimap (World.explored).

    The world is remembered as a coarse grid of cells, revealed around the player as they
    walk and never forgotten. Cells are deliberately big: the map is a record of roughly
    where you have been, not a survey.
    """

    CELL: int = 250
    REVEAL_RADIUS: int = 620

    # Underground the same memory is kept on a much finer grid, and only as far as the
    # player can see. A tunnel is a few rooms wide where the surface is a countryside, so
    # surface-sized cells would blot the whole place in on the first step down; revealing
    # only what the lantern reaches is what makes a cave unfold on the map as it is walked.
    # The cells are world cells like any other (a tunnel is ordinary world space), just
    # counted at this size, and they are saved and reloaded with the rest.
    TUNNEL_CELL: int = 70
    TUNNEL_REVEAL_RADIUS: int = 320


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
    first time it is walked up to; "signpost" reads out the way to somewhere unexplored;
    "cave" is a way into the dark under the world for a player who is nowhere near a well.
    """

    # Points of interest stream in per chunk like the floor details, so the wilderness
    # keeps offering something to find however far out the player walks. At most one per
    # chunk, kept CHUNK_MARGIN away from the chunk's edges, which is what spaces
    # neighbouring chunks' landmarks apart without any cross-chunk bookkeeping.
    PER_CHUNK_CHANCE: float = 0.7
    CHUNK_MARGIN: int = 260
    MIN_DIST_FROM_BUILDING: int = 400
    # How much open ground a landmark keeps beyond a settlement's own grounds, which are
    # asked for directly (`village.site_grounds_radius`) rather than approximated by the
    # distance to its centre.
    VILLAGE_MARGIN: int = 260
    MIN_DIST_FROM_CENTER: int = 900
    # Nobody pitches a camp or raises a shrine in a river.
    MIN_DIST_FROM_WATER: int = 120
    SIZE: int = 46
    HIT_RADIUS: int = 34
    # How much ground each landmark actually covers, as a radius from its centre: what is
    # drawn, not what is walked up to. A graveyard is four rows of stones spread over
    # several hundred pixels, so a road aimed at its centre point ran straight through the
    # graves and a footpath "reaching" it stopped in the middle of them. Anything not
    # listed is the size of the marker itself.
    FOOTPRINT = {
        "graveyard": 240,
        "cave": 105,
        "camp": 95,
        "farmstead": 90,
        "stones": 75,
        "watchtower": 70,
        "shrine": 60,
    }
    # The open ground a footpath leaves round the landmark it leads to, past its footprint.
    PATH_MARGIN: int = 30
    # How near a road between two settlements may pass a landmark. A landmark stands down
    # rather than the road bending: the road was cut between two places people live, and
    # what gives way is the thing nobody laid out.
    ROAD_MARGIN: int = 60
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
        ("cave", 2),
    )

    # How close the player has to be to walk into a cave mouth. Wider than a shrine's reach
    # because the mouth itself is wide.
    CAVE_ENTER_DISTANCE: int = 130

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
        "cave": (
            "A cave mouth in the rock. Something has worn a path to it. Enter (E).",
            "A black opening in the hillside, colder than the air outside it. Enter (E).",
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
    # A signpost is the one landmark that is a prop: a post somebody can put a weapon
    # through, worth about as much work as a barrel. What it costs is what was written on
    # it, so breaking one before reading it is the player's own doing.
    SIGNPOST_HP: int = 30
    WRECKABLE: tuple = ("signpost",)
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
    # Sitting down is not a button press: the fire builds, the embers go up and the warmth
    # comes off the player for this long afterwards. Cosmetic only, the health is already
    # theirs, but a rest that was over on the frame it started never felt like one.
    REST_ANIM_MS: float = 2600.0
    # A camper trades out of their pack: stock rolled locally, no LLM call in the wilds.
    CAMPER_STOCK_SIZE: int = 5
    # How far a camper's directions look for something the player hasn't walked to yet.
    HINT_CHUNK_RADIUS: int = 4
    HINT_MIN_DISTANCE: int = 700


@dataclass(frozen=True)
class Weather:
    """Rain and fog, the second thing that happens to the whole world at once.

    Night is already a state of the world rather than a filter over it: it changes what
    spawns, what a monster notices and how far a villager sees. Weather is the same idea on
    a shorter clock and with no schedule, so a walk across open country is not the same walk
    twice. It is session only, like the wildlife and the particles: what the sky is doing is
    not a fact a save has any business restoring.
    """

    # How often the sky is asked to change its mind, and how long a spell of weather holds
    # once it has. Rolled on the same kind of cadence an event is, so weather is something
    # the player walks into rather than something that flickers.
    CHECK_INTERVAL_MS: tuple = (90_000, 180_000)
    RAIN_DURATION_MS: tuple = (60_000, 150_000)
    FOG_DURATION_MS: tuple = (60_000, 120_000)
    # The chance a change is to rain and to fog; the rest of the roll is the sky clearing.
    RAIN_CHANCE: float = 0.35
    FOG_CHANCE: float = 0.2
    # How long a spell takes to come on and to bleed out again, at each end of its duration,
    # exactly as a blood night does: everything weather changes reads the ramp, so the
    # world thickens and thins instead of switching.
    FADE_MS: int = 9_000

    # What it costs to see through, at full strength. Both are multipliers on a distance
    # that already exists: what a villager catches the player at (`World.witness_radius`)
    # and what a monster notices them from (`World._update_monsters`). Rain is a nuisance,
    # fog is the reason to stay in.
    RAIN_SIGHT_MULT: float = 0.75
    FOG_SIGHT_MULT: float = 0.45

    # Rain is drawn as a fixed set of streaks falling down the screen on their own loop,
    # placed off one seeded shuffle rather than a live particle system: it is weather, it
    # never interacts with anything, and a thousand particles a frame for that is a frame
    # spent on nothing.
    RAIN_DROPS: int = 260
    RAIN_COLOR: tuple = (168, 190, 214)
    RAIN_LENGTH: tuple = (14, 26)
    RAIN_SPEED: tuple = (900.0, 1400.0)
    RAIN_SLANT: float = 0.22
    RAIN_ALPHA: int = 120
    # And fog as a flat wash kept by `screen_fx.Overlay`, in steps no finer than it reads.
    FOG_COLOR: tuple = (176, 180, 186)
    FOG_MAX_ALPHA: int = 155
