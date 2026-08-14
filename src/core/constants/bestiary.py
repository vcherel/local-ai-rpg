from dataclasses import dataclass


@dataclass(frozen=True)
class Entities:
    NPC_SIZE: int = 30
    ITEM_SIZE: int = 25
    # NPCs wander around their spawn point: walk to a random spot within
    # NPC_WANDER_RADIUS, then idle for a random duration before moving again.
    NPC_WANDER_SPEED: float = 1.5
    NPC_WANDER_RADIUS: int = 250
    NPC_IDLE_MIN_MS: int = 2000
    NPC_IDLE_MAX_MS: int = 7000
    # NPCs stop wandering and face the player when he gets this close.
    NPC_WANDER_PAUSE_DISTANCE: int = 120
    # Hit a villager and the settlement turns on you: they drop what they were doing and
    # come at you with whatever is to hand. Slower and weaker than a bandit one on one,
    # dangerous because a village holds a dozen of them.
    NPC_HP: int = 45
    NPC_HOSTILE_SPEED: float = 3.4
    NPC_ATTACK_RANGE: int = 34
    NPC_DAMAGE: int = 9
    NPC_ATTACK_COOLDOWN_MS: int = 900
    # Angry villagers are not a hunting party: outrun them by this much and they go back
    # to their houses. Still hostile, still waiting, just no longer following you across
    # the world in a column of eighteen.
    NPC_HOSTILE_RANGE: int = 1100
    SWING_SPEED: float = 0.007
    # How long an entity flashes white after being hit (ms).
    FLASH_MS: int = 150
    # A dropped item pops from its source (a smashed crate, say) and settles into place.
    DROP_POP_MS: int = 400
    DROP_POP_HEIGHT: float = 26.0
    # Loot lying on the ground bobs over a pulsing halo in its rarity colour, so it can be
    # spotted from across the screen instead of blending into the grass.
    LOOT_BOB_HEIGHT: float = 3.0
    LOOT_GLOW_RADIUS: int = 9
    LOOT_GLOW_ALPHA_MIN: int = 40
    LOOT_GLOW_ALPHA_SWING: int = 45


@dataclass(frozen=True)
class MonsterKind:
    name: str
    color: tuple
    size: int
    hp: int
    speed: int
    attack_range: int
    damage: int
    # Only spawns at least this far from the world center, so tougher kinds show up farther out.
    min_distance: int
    # Relative pick weight among kinds unlocked at a given distance; higher means more common.
    weight: int
    # Ranged kinds shoot instead of swinging: `attack_range` is how far they can shoot from,
    # `keep_distance` the range they try to hold, backing off when the player closes in, and
    # `shot_cooldown_ms` how often they loose one. A melee kind leaves all three alone.
    ranged: bool = False
    keep_distance: int = 0
    shot_cooldown_ms: int = 0
    # How many spawn together when this kind is rolled. A pack kind is picked once and then
    # stood up as a group, which is what makes wolves and goblins read differently from
    # everything else without any new AI.
    group: tuple = (1, 1)
    # A charger holds its ground, winds up, then crosses the gap in one burst instead of
    # walking in. Its damage still lands through the normal swing; the charge only moves it.
    charge: bool = False
    # A flanker refuses to walk straight at the player: its approach angle is bent to one
    # side, flipping every few seconds, so it circles in rather than queueing up in front.
    flank_deg: float = 0.0


# Ordered weakest to strongest, scaling up with distance from the world center so wandering
# further gets more dangerous. Mobs hit harder and reach the player, but the tougher kinds
# stay spaced out from the world center so there's room to explore before they show up.
# The archer and the hexer are what stop a fight being won by walking backwards: they hold
# their distance and shoot, so closing on them is the only answer.
MONSTER_KINDS: tuple[MonsterKind, ...] = (
    MonsterKind("Slime", (90, 190, 90), 22, 16, 3, 10, 8, min_distance=0, weight=10),
    MonsterKind("Goblin", (110, 150, 80), 22, 14, 5, 9, 7, min_distance=600, weight=7, group=(2, 4)),
    MonsterKind("Wolf", (140, 140, 140), 26, 32, 5, 10, 13, min_distance=1400, weight=6, group=(2, 3)),
    MonsterKind(
        "Archer",
        (168, 122, 62),
        26,
        26,
        4,
        420,
        11,
        min_distance=1800,
        weight=4,
        ranged=True,
        keep_distance=260,
        shot_cooldown_ms=1900,
    ),
    MonsterKind("Skeleton", (215, 210, 195), 26, 42, 3, 11, 16, min_distance=2200, weight=4),
    MonsterKind("Bandit", (150, 40, 40), 28, 55, 4, 12, 19, min_distance=2800, weight=4),
    MonsterKind("Wraith", (150, 130, 200), 24, 34, 6, 10, 15, min_distance=3400, weight=3, flank_deg=55),
    MonsterKind("Troll", (60, 90, 55), 34, 95, 3, 14, 29, min_distance=4200, weight=2),
    MonsterKind("Ogre", (120, 95, 70), 40, 150, 2, 16, 34, min_distance=5200, weight=2, charge=True),
    MonsterKind(
        "Hexer",
        (128, 78, 188),
        28,
        48,
        3,
        480,
        17,
        min_distance=4600,
        weight=2,
        ranged=True,
        keep_distance=320,
        shot_cooldown_ms=2400,
    ),
)

MONSTER_MAX_SIZE: int = max(kind.size for kind in MONSTER_KINDS)


@dataclass(frozen=True)
class Charge:
    """A charging monster's rush (MonsterKind.charge). It plants itself for WINDUP_MS with
    the charge lined up, then crosses the gap at SPEED_MULT before going back to walking.
    The windup is the whole point: the rush is meant to be sidestepped, not tanked."""

    # Only starts a rush from inside this range, and only once per COOLDOWN_MS.
    RANGE: int = 420
    MIN_RANGE: int = 120
    WINDUP_MS: int = 650
    DURATION_MS: int = 750
    COOLDOWN_MS: int = 4200
    SPEED_MULT: float = 3.4


@dataclass(frozen=True)
class Flank:
    """A flanking monster (MonsterKind.flank_deg) bends its approach to one side, swapping
    sides every FLIP_MS. The bend fades out inside CLOSE_DISTANCE so it still arrives
    instead of orbiting the player forever."""

    FLIP_MIN_MS: int = 1400
    FLIP_MAX_MS: int = 2600
    CLOSE_DISTANCE: int = 140


@dataclass(frozen=True)
class BossKind:
    """Template for a boss archetype. The LLM fills in the name/title at spawn; these
    fields fix the stats, look and which special abilities the boss can use."""

    archetype: str  # "brute" | "warlock" | "colossus"
    color: tuple
    aura: tuple  # glow ring color behind the body
    size: int
    hp: int
    speed: float
    attack_range: int
    damage: int
    # Any of ("slam", "volley", "summon"); one is rolled each time the ability cooldown fires.
    abilities: tuple
    summon_kind: str  # MonsterKind name spawned as adds by the "summon" ability
    flavor: str  # short hint fed to the LLM when it names this boss


# The three boss archetypes. Stats sit well above the toughest normal monster (Troll, 60 hp)
# so a boss is a real fight, not just a big monster.
BOSS_KINDS: tuple[BossKind, ...] = (
    BossKind(
        "brute",
        (170, 45, 45),
        (255, 110, 60),
        60,
        320,
        3.2,
        22,
        26,
        abilities=("slam", "summon"),
        summon_kind="Bandit",
        flavor="a towering brute that crushes any who come near",
    ),
    BossKind(
        "warlock",
        (120, 60, 195),
        (185, 120, 255),
        52,
        240,
        3.6,
        22,
        18,
        abilities=("volley", "summon"),
        summon_kind="Wolf",
        flavor="a dark sorcerer that hurls bolts of ruinous energy",
    ),
    BossKind(
        "colossus",
        (95, 115, 90),
        (150, 225, 150),
        74,
        460,
        2.4,
        26,
        34,
        abilities=("slam",),
        summon_kind="Troll",
        flavor="an ancient stone colossus, slow but earth-shattering",
    ),
)


@dataclass(frozen=True)
class Boss:
    # A boss only chases and uses abilities within this range; farther out it idles.
    AGGRO_RANGE: int = 700

    # Second phase: when HP drops below this fraction the boss enrages (faster, hits harder).
    ENRAGE_HP_RATIO: float = 0.5
    ENRAGE_SPEED_MULT: float = 1.5
    ENRAGE_COOLDOWN_MULT: float = 0.6  # abilities come faster when enraged
    ENRAGE_DAMAGE_MULT: float = 1.3

    # Special abilities fire on this cooldown (ms), randomised within the range.
    ABILITY_COOLDOWN_RANGE_MS: tuple = (4500, 7000)

    # Slam: a telegraphed ground pound. Warns for TELEGRAPH_MS, then damages anyone
    # still within RADIUS of the boss.
    SLAM_TELEGRAPH_MS: int = 700
    SLAM_RADIUS: int = 190
    SLAM_DAMAGE: int = 24
    SLAM_SHAKE: float = 22.0

    # Volley: a fan of hostile bolts aimed at the player.
    VOLLEY_COUNT: int = 5
    VOLLEY_SPREAD_DEG: float = 44.0
    VOLLEY_DAMAGE: int = 14

    # Summon: adds spawned in a ring around the boss.
    SUMMON_COUNT: int = 3
    SUMMON_RADIUS: int = 170

    # A slain boss always drops a lootbox of this rarity, on top of the usual roll.
    REWARD_RARITY: str = "legendary"

    # No more than this many bosses exist at once (the landmark guardian counts).
    MAX_ACTIVE: int = 3
    # Wandering far from the world center can spawn a roaming boss, rolled on this cadence.
    ROAM_MIN_DISTANCE: int = 3500
    ROAM_CHECK_INTERVAL_MS: int = 45_000
    ROAM_CHANCE: float = 0.25
    ROAM_SPAWN_MIN_DIST: int = 900
    ROAM_SPAWN_MAX_DIST: int = 1400

    # Health-bar geometry, pinned near the top of the screen (screen space).
    BAR_WIDTH: int = 620
    BAR_HEIGHT: int = 26
    BAR_TOP: int = 72


@dataclass(frozen=True)
class CritterKind:
    """One species of wildlife (game/entities/critter.py).

    `temperament` is the whole personality and the only thing that decides how an animal
    answers the player:
      "passive"   never fights, whatever is done to it. Its answer is to run.
      "retaliate" peaceful until struck, then hunts the player until it is badly hurt,
                  at which point it breaks off and runs like a passive one.
      "predator"  hostile on sight inside `detection`, and never flees.
      "guard"     peaceful and tied to a settlement or camp, turns with it (village dogs
                  go hostile through World.provoke_village, camp dogs are born hostile).
    """

    name: str
    color: tuple
    size: int
    hp: int
    weight: int  # spawn weight in the wilderness; 0 means it is only placed deliberately
    temperament: str = "passive"
    min_distance: int = 0  # only spawns this far from the world center, like a monster kind
    group: tuple = (1, 1)  # how many appear together
    # Hit radius as a multiple of the size, since none of these are drawn as a circle of
    # `size` across: the small ones are ellipses about 1.3 sizes long, and a quadruped is a
    # whole standing animal running from its tail to its muzzle.
    hit_radius_mult: float = 0.7
    shape: str = "small"  # "small" (ellipse and head) or "quadruped" (flank, legs, neck)
    wander_speed: float = 1.0
    # Running away. The sprint is held for `stamina_ms` and then drops to a tired trot, so a
    # deer outruns the player outright while a rabbit only wins the first two seconds.
    sprint_mult: float = 2.6
    stamina_ms: int = 2200
    flee_distance: int = 90
    # Fighting back. Unused by a passive kind.
    damage: int = 0
    chase_speed: float = 1.6
    attack_range: int = 30
    attack_cooldown_ms: int = 900
    detection: int = 0  # predators and angry guards only: how far off they notice the player
    # A kill sometimes leaves a valuable behind. Bigger game is the surer bet.
    drop_chance: float = 0.0
    drop_name: str = ""


CRITTER_KINDS: tuple[CritterKind, ...] = (
    CritterKind(
        "rabbit",
        (200, 190, 170),
        14,
        8,
        weight=5,
        sprint_mult=3.6,
        stamina_ms=1500,
        drop_chance=0.5,
        drop_name="Rabbit Pelt",
    ),
    CritterKind(
        "deer",
        (150, 110, 70),
        26,
        22,
        weight=3,
        group=(2, 4),
        hit_radius_mult=1.0,
        shape="quadruped",
        sprint_mult=3.0,
        stamina_ms=5000,
        flee_distance=170,
        drop_chance=1.0,
        drop_name="Venison Haunch",
    ),
    CritterKind(
        "fox",
        (195, 100, 55),
        16,
        12,
        weight=3,
        sprint_mult=2.9,
        stamina_ms=2600,
        drop_chance=0.75,
        drop_name="Fox Pelt",
    ),
    CritterKind(
        "badger",
        (120, 115, 110),
        16,
        20,
        weight=2,
        temperament="retaliate",
        min_distance=700,
        hit_radius_mult=0.8,
        sprint_mult=2.2,
        stamina_ms=1800,
        flee_distance=55,
        damage=8,
        chase_speed=1.9,
        attack_cooldown_ms=750,
        detection=260,
        drop_chance=0.8,
        drop_name="Badger Hide",
    ),
    CritterKind(
        "boar",
        (105, 80, 70),
        26,
        46,
        weight=2,
        temperament="retaliate",
        min_distance=1200,
        group=(1, 2),
        hit_radius_mult=0.9,
        shape="quadruped",
        sprint_mult=2.4,
        stamina_ms=2600,
        flee_distance=60,
        damage=15,
        chase_speed=2.6,
        attack_range=34,
        attack_cooldown_ms=1000,
        detection=340,
        drop_chance=1.0,
        drop_name="Boar Tusk",
    ),
    CritterKind(
        "wild dog",
        (128, 118, 104),
        20,
        24,
        weight=3,
        temperament="predator",
        min_distance=1500,
        group=(2, 4),
        hit_radius_mult=0.8,
        shape="quadruped",
        sprint_mult=2.4,
        damage=10,
        chase_speed=2.7,
        attack_cooldown_ms=800,
        detection=520,
        drop_chance=0.6,
        drop_name="Hound Fang",
    ),
    CritterKind(
        "bear",
        (95, 72, 55),
        36,
        130,
        weight=1,
        temperament="predator",
        min_distance=3200,
        hit_radius_mult=1.0,
        shape="quadruped",
        wander_speed=0.8,
        sprint_mult=2.0,
        damage=30,
        chase_speed=2.3,
        attack_range=42,
        attack_cooldown_ms=1300,
        detection=480,
        drop_chance=1.0,
        drop_name="Bear Hide",
    ),
    # Never rolled in the wild (weight 0): dogs are placed by their village or camp.
    CritterKind(
        "dog",
        (170, 145, 110),
        20,
        26,
        weight=0,
        temperament="guard",
        hit_radius_mult=0.8,
        shape="quadruped",
        sprint_mult=2.2,
        flee_distance=0,
        damage=9,
        chase_speed=2.6,
        attack_cooldown_ms=800,
        detection=460,
        drop_chance=0.0,
    ),
)

CRITTER_KINDS_BY_NAME = {kind.name: kind for kind in CRITTER_KINDS}


@dataclass(frozen=True)
class Wildlife:
    """Tuning shared by every critter (game/entities/critter.py). Session-only, like
    particles or projectiles: never saved, just respawned near the player as the world
    loads or as they roam. What each species does with the player is in `CritterKind`.
    """

    COUNT: int = 25
    RESPAWN_INTERVAL_MS: int = 800
    # Kept above the screen's half-diagonal (~1006px) so an animal is never seen popping
    # into existence in front of the player; it has to be walked up to.
    SPAWN_MIN_DISTANCE: int = 1150
    SPAWN_MAX_DISTANCE: int = 1700
    DESPAWN_DISTANCE: int = 2200
    GROUP_SPREAD: int = 90

    WANDER_RADIUS: int = 200
    IDLE_MIN_MS: int = 1500
    IDLE_MAX_MS: int = 5000

    # Running away is a straight sprint, not a scatter: a fleeing animal commits to a
    # heading and only bends it TURN_RATE_DEG per frame, so it pulls away in a line instead
    # of jittering on the spot every time the player circles it. Once its stamina is spent
    # it keeps going at TIRED_MULT of the sprint for RECOVER_MS, which is the window the
    # player has to catch it.
    FLEE_TURN_RATE_DEG: float = 7.0
    TIRED_MULT: float = 0.55
    RECOVER_MS: int = 2500
    # A wounded animal runs (or charges, if it fights back) whatever the distance.
    BOLT_DURATION_MS: int = 2500
    # A retaliating animal gives up and runs once this much of its health is gone.
    BREAK_OFF_HP_FRAC: float = 0.3
    # A struck or angered animal drags its own kind in from this far off: packs answer together.
    PACK_AGGRO_RADIUS: int = 320
    # Village dogs, per settlement, and the dogs standing guard at a bandit camp.
    VILLAGE_DOGS: tuple = (1, 3)
    CAMP_DOGS: tuple = (0, 2)
    DOG_WANDER_RADIUS: int = 260
