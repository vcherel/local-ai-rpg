"""Everything about a settlement: where one stands, who lives in it, what its wall is
made of, and how much patience it has left with the player.

Split out of `world.py` because a village is a subject of its own rather than a corner of
the terrain: the wall tiers, the defence orders, the warning ladder and the shop clock are
all read together and none of them tune the ground the village sits on.
"""

from dataclasses import dataclass


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
    # How likely a region is to settle at all, and how likely it is to settle a second
    # chunk, both read off how far out the region stands: the deep wilds are emptier of
    # people than the settled ring only because nobody drew any villages out there, which
    # left walking outward feeling like walking off the map. Density is the one lever a
    # region grid has, so both of these ramp to REGION_FAR_DISTANCE and stop.
    REGION_CHANCE: float = 0.55
    REGION_CHANCE_FAR: float = 1.0
    REGION_SECOND_CHANCE: float = 0.0
    REGION_SECOND_CHANCE_FAR: float = 0.85
    REGION_FAR_DISTANCE: int = 24000
    # Two regions can both settle near their shared border; the later one stands down, so
    # there is always this much empty wilderness between one settlement and the next. The
    # same rule settles the two a single far-out region may offer.
    MIN_GAP: int = 3200
    # ...and how close they may stand out where settlements are meant to be thick on the
    # ground. A gap is what keeps two villages from reading as one sprawl, so it can close
    # up as the density rises but never past the point where their walls would meet.
    MIN_GAP_FAR: int = 2500
    # Kept away from the chunk's own edges so the cluster stays inside its own region.
    CHUNK_MARGIN: int = 380
    # The starting town already sits here; no streamed village crowds it.
    MIN_DIST_FROM_SPAWN: int = 3000

    # Buildings sit on a loose grid around an open plaza, close enough to read as one
    # settlement, far enough apart for the doors (always on the south facade) to be usable.
    SLOT_W: int = 500
    SLOT_H: int = 520
    SLOT_JITTER: int = 30
    # How many times the layout may shove overlapping buildings apart before it settles for
    # what it has. A pass fixes every pair it sees, so a few of them clear even a street of
    # L-shaped houses; the cap is only there so a pathological seed cannot loop forever.
    SEPARATE_PASSES: int = 12

    # Relative pick weight per settlement size, and what each one is made of.
    SIZE_WEIGHTS: tuple = (("hamlet", 5), ("village", 4), ("town", 2))
    COMPOSITION = {
        "hamlet": {"tavern": (0, 0), "shop": (0, 1), "house": (2, 3)},
        "village": {"tavern": (0, 1), "shop": (1, 1), "house": (3, 5)},
        "town": {"tavern": (1, 1), "shop": (1, 2), "house": (5, 7)},
    }
    # The village the player starts in, at the world centre.
    START_COMPOSITION = {"tavern": (1, 1), "shop": (3, 3), "house": (9, 9)}
    # No two of the same special building stand within this of each other. Slots are handed
    # out from the plaza outward, so taking them in order put both of a town's taverns on
    # the same corner of the square; a settlement has one of each thing per quarter of it.
    SPECIAL_MIN_GAP: int = 900
    # The clear ground in front of every front door: nothing is laid out over one, nothing
    # is planted in one, and a neighbour that ends up standing on one is pushed off it.
    DOORSTEP_CLEAR: int = 150
    DOORSTEP_WIDTH: int = 190
    # The lanes worn between the houses: one from the plaza out to every front door, laid
    # in the same blobs a road is (`Village.plan_streets`). A settlement whose buildings
    # stood on undisturbed grass read as sheds dropped in a field.
    STREET_WIDTH: int = 15
    STREET_STEP: int = 16
    START_DISTANCE_FROM_CENTER: int = 900

    # How many people live in one home. A bigger settlement is a busier one: numbers are
    # the first of the three things a village is made strong with (the others being health
    # and its wall), never what its people are carrying.
    VILLAGERS_PER_HOME: tuple = (1, 2)
    VILLAGERS_PER_HOME_BY_SIZE = {"hamlet": (1, 2), "village": (1, 3), "town": (2, 3)}

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

    # Nobody turns on the player over one blow any more, and no settlement counts one kind
    # of offence against another. Each kind (a swing that lands, a hand in somebody's chest,
    # a room taken for the night, a chair put through a wall) keeps its own ledger: the
    # first of each is a warning, the second of the *same* kind inside STRIKE_WINDOW_S is
    # what provokes the place. A killing skips the ladder entirely, as does a second strike
    # after that kind's window has run out, which resets to a fresh warning.
    STRIKES_BEFORE_ANGER: int = 2
    STRIKE_WINDOW_S: float = 45.0
    # How long the shout hangs over the villager who gave it.
    WARNING_MS: int = 2600
    # Every offence a settlement counts, with the words it is warned about in. A ladder per
    # kind means the wording can be the one thing that says which ledger was just spent, so
    # nobody is ever told to put a bed back.
    OFFENCES = {
        "assault": {
            "label": "Violence",
            "shouts": (
                "Hey! Touch me again and you're done.",
                "Watch yourself, stranger.",
                "Try that once more and we'll all be on you.",
                "That's your one warning.",
            ),
        },
        "theft": {
            "label": "Theft",
            "shouts": (
                "Hands off that!",
                "I saw that. Put it back.",
                "Thief! Next time I call the whole street.",
            ),
        },
        "squatting": {
            "label": "Trespass",
            "shouts": (
                "That bed isn't yours to sleep in.",
                "Out. Find your own roof.",
                "You slept here? Next time you sleep in the ditch.",
            ),
        },
        "vandalism": {
            "label": "Damage",
            "shouts": (
                "That's my property you're breaking!",
                "Wreck one more thing and we'll wreck you.",
                "Who's paying for that?",
            ),
        },
    }
    DEFAULT_OFFENCE: str = "assault"

    # A village defends itself. Only some of its people take up arms (rolled per NPC off
    # their home, so the same house always sends the same person out); the rest run for the
    # nearest door and shut it. A monster inside a settlement's grounds plus this margin is
    # an intruder, a militiaman walks this far from where they stand to meet one, and anyone
    # else bolts once one is this close.
    # How many of them take up arms, by the settlement's own tier: a deep wilds town turns
    # out more people as well as better armed ones, since living out there is what teaches
    # a village to answer for itself.
    MILITIA_FRACTION_BY_TIER: tuple = (0.35, 0.5, 0.65)
    DEFEND_MARGIN: float = 300.0
    DEFEND_RADIUS: float = 620.0
    # How many of the nearest villagers a monster asks whether it can actually see before
    # settling for the player. Sight is walked step by step and monsters are the long list.
    MONSTER_PREY_TRIES: int = 3
    PANIC_RADIUS: float = 520.0

    # The same split decides what an angry village does about the player, so a mob is not a
    # column of identical farmers. The militia close and swing; everyone else keeps this far
    # back and throws whatever is to hand, which is a real threat in numbers and impossible
    # to answer with a sword. Anyone cut down to this fraction of their health has had
    # enough and runs for a door, so a mob thins out as it loses rather than fighting to
    # the last farmer.
    # Only the people the player is actually standing among fight them. An angry village is
    # angry everywhere, but a farmer three streets away carries on with their day rather
    # than converging on the player from across the settlement: whoever is inside this
    # radius takes up the fight, everyone else stays where they are and does what they were
    # doing. Once engaged they are held by the longer `Entities.NPC_HOSTILE_RANGE` leash, so
    # a fight the player walks away from is broken off rather than dropped on the spot.
    MOB_ENGAGE_RANGE: float = 430.0
    MOB_STANDOFF: float = 250.0
    MOB_STONE_RANGE: float = 340.0
    MOB_STONE_DAMAGE: int = 5
    MOB_STONE_COOLDOWN_MS: tuple = (1400, 2600)
    ROUT_HP_FRAC: float = 0.35

    # What a villager does once they are cut that far down, which is now a decision rather
    # than the fight quietly stopping. Whoever took up arms for the place (militia, guards)
    # falls back shouting for help, and the shout is worth as much as their sword was:
    # every calm villager inside HELP_SHOUT_RANGE joins the fight. Everyone else yields:
    # they drop what they were holding, kneel under a white flag and stop being anything to
    # fight for SURRENDER_S, then get up and run for a door. Cutting down somebody who has
    # yielded is the one offence that skips the ladder outright.
    SURRENDER_S: float = 9.0
    HELP_SHOUT_RANGE: float = 520.0
    HELP_SHOUTS: tuple = (
        "To me! To me!",
        "Help, someone!",
        "They're killing me, get out here!",
    )
    # How many of a settlement's people have to be after the player at once before it shuts
    # itself. One angry farmer is a brawl, not a siege: gates only come down on a real mob,
    # or the moment somebody is killed here and the place holds a grudge.
    BAR_GATES_MOB: int = 3

    # A town is worth defending, and a hamlet has nothing to defend with: only the largest
    # settlements (and the starting town) stand a wall. The ring follows the settlement's
    # own footprint rather than being a square around its diagonal, with a gate cut in the
    # middle of each side, so there is always a way in from whichever direction the player
    # or a pack arrives, and the wall itself is something to be routed round rather than a
    # box with one door. A tower stands at each corner: solid, and the one piece of a
    # village that reads from a long way off.
    WALLED_SIZES: tuple = ("town", "village")
    WALL_MARGIN: int = 150
    WALL_THICKNESS: int = 26
    # Big enough to read as a way in from across a field, and wide enough that a chased
    # player and whatever is behind them both fit through it.
    GATE_WIDTH: int = 260
    # The block of wall thickened either side of a gateway. Solid like the rest, so
    # navigation routes round it for free.
    GATEHOUSE: int = 54
    WALL_COLOR: tuple = (118, 92, 62)
    WALL_TOP: tuple = (146, 116, 78)
    WALL_STONE: tuple = (128, 124, 116)
    WALL_STONE_TOP: tuple = (162, 158, 148)
    TOWER_STONE: tuple = (136, 132, 124)
    GATE_POST: tuple = (92, 70, 46)
    GATE_LEAF: tuple = (104, 76, 48)
    # Somebody stands at each gate and each tower, always armed and always willing. They
    # hold their post rather than strolling the way a villager does; how many of them is the
    # settlement's tier, through GUARDS_PER_POST_BY_TIER.
    GUARD_POST_RADIUS: int = 70
    GUARD_COLOR: tuple = (92, 104, 126)

    # How well defended one settlement is: a number from 0 to MAX_TIER, rolled once from
    # how far out it stands and how big it is, then persisted with the village like its
    # wall. It is the one lever behind every difference between a border hamlet and a deep
    # wilds town: the wall's material, how many stand on it, whether any of them carry a
    # bow, whether there are stakes and a ditch outside it, which weapon ladder its people
    # draw from and how much health they have. Walking further out should be visible
    # before anything is fought.
    TIER_DISTANCES: tuple = (6500, 14000)
    TIER_SIZE_BONUS = {"hamlet": -1, "village": 0, "town": 1}
    MAX_TIER: int = 2
    WALL_STYLE_BY_TIER: tuple = ("palisade", "palisade", "stone")
    WALL_THICKNESS_BY_TIER: tuple = (26, 32, 40)
    TOWER_RADIUS_BY_TIER: tuple = (44, 52, 62)
    GUARDS_PER_POST_BY_TIER: tuple = (1, 1, 2)
    # Archers are posted in the towers, where they can see over the wall. A tier 0 wall is
    # watched by spearmen alone.
    ARCHERS_PER_TOWER_BY_TIER: tuple = (0, 1, 2)
    # Where on a tower roof an archer stands, as a fraction of its radius from the middle:
    # far enough apart that two of them are two people at a parapet rather than one body
    # drawn twice, near enough that neither is standing off the edge.
    TOWER_STAND_FRAC: float = 0.45
    # A wall long enough to matter is not covered from its corners alone, so the best
    # defended settlements also stand somebody on each stretch between a gate and a tower.
    ARCHERS_PER_WALL_BY_TIER: tuple = (0, 1, 1)
    # How far the arrow itself carries, still short of the player's own bow (Projectile.RANGE)
    # so outranging a wall is a real option. What they will loose at is deliberately less
    # than that (FIRE_FRAC of it): a shot taken at the exact limit of its flight dies in the
    # air the moment its target takes a step, which reads as an arrow that falls short.
    ARCHER_RANGE: float = 950.0
    ARCHER_FIRE_FRAC: float = 0.85
    ARCHER_DAMAGE: int = 12
    ARCHER_COOLDOWN_MS: tuple = (1500, 2600)
    # How wide a corridor around the line to the target has to be clear of their own people
    # before an archer or a stone-thrower lets go. Nobody in a village shoots a neighbour in
    # the back, and nothing they put in the air can hit one either (Projectile.from_npc).
    FRIENDLY_LANE_WIDTH: float = 44.0

    # The gates stand open while a settlement has nothing to fear. Turn the place against
    # you and they are barred, which is when a gate is a wall with a hit-point pool: the
    # one part of a wall that can be broken, by the player hacking their way out or by a
    # pack beating its way in. Nothing else about a palisade ever gives.
    GATE_HP: int = 240
    # A gate is a thing on hinges, so it is drawn swinging rather than blinking: the leaves
    # take GATE_SWING_MS to open, and open means folded right back against the inside of
    # their own wall, since a gate stands open nearly always and one left sticking into the
    # street is a pair of planks in the way of every villager who never touches them.
    # Purely what is drawn, never what is collided against: a barred gate is a wall from the
    # frame it is barred (`Village.gate_closed`), the leaves only catch up with it.
    GATE_SWING_MS: float = 260.0
    GATE_SWING_DEG: float = 168.0
    # How long a gate a villager has let themselves through stands open before it shuts
    # again behind them (`Village.let_through`).
    GATE_HOLD_MS: float = 900.0

    # The player working a barred gate open from the inside: the bar is a beam, so lifting
    # it is a hold rather than a press, and it is slow enough that a mob at your back is a
    # real reason to break the gate instead. Once lifted it stands open long enough to walk
    # through and then falls back into place.
    GATE_LIFT_S: float = 4.0
    GATE_LIFT_HOLD_MS: float = 1800.0
    # Being hit while heaving at it loses this much of the lift: a gate is not opened in the
    # middle of a fight.
    GATE_LIFT_HIT_LOSS: float = 0.4

    # Stakes outside the wall from tier 1, a ditch from tier 2. Both follow the wall
    # stretches only, so a gateway is never obstructed by either. Stakes prick whatever
    # walks into them on their own cooldown; the ditch costs speed rather than health,
    # like water, so it slows an approach instead of stopping one.
    SPIKE_TIER: int = 1
    SPIKE_OFFSET: int = 40
    SPIKE_SPACING: int = 34
    SPIKE_LENGTH: int = 22
    SPIKE_RADIUS: int = 16
    SPIKE_DAMAGE: int = 7
    SPIKE_COOLDOWN_MS: int = 900
    SPIKE_COLOR: tuple = (126, 100, 66)
    DITCH_TIER: int = 2
    DITCH_OFFSET: int = 92
    DITCH_WIDTH: int = 76
    DITCH_SPEED: float = 0.55
    DITCH_COLOR: tuple = (86, 72, 52)

    # What a villager is worth in a fight, by their settlement's tier and by what they do
    # in it. A farmer with a hoe is not meant to win; a street of them, a militia that
    # takes real hits and a guard on the gate together are.
    HP_BY_TIER: tuple = (1.0, 1.25, 1.55)
    MILITIA_HP_MULT: float = 1.4
    GUARD_HP_MULT: float = 1.9

    # A merchant's shelf refills on a clock rather than staying whatever the model wrote at
    # world generation. What is already out stays out and the delivery tops the stock back
    # up to SHOP_STOCK_TARGET, so buying a shop empty is worth doing and coming back later
    # is worth doing too. Rolled locally (game.loot.roll_shop_stock): a fresh LLM call per
    # restock is exactly the cost the batched generation exists to avoid.
    SHOP_RESTOCK_S: float = 600.0
    SHOP_STOCK_TARGET: int = 10
