from dataclasses import dataclass


@dataclass(frozen=True)
class Entities:
    # One multiplier on every monster's own `MonsterKind.speed`, so the pace of the whole
    # bestiary is one number rather than sixty. Pulled down alongside `Player.SPEED`: a
    # fight is meant to be read as it happens, and a chase to be a chase rather than two
    # bodies teleporting round each other. The ladder between kinds is untouched.
    MONSTER_SPEED_SCALE: float = 0.8
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
    NPC_HP: int = 70
    NPC_HOSTILE_SPEED: float = 3.4
    NPC_ATTACK_RANGE: int = 34
    NPC_DAMAGE: int = 9
    # What a villager actually has in their hands, rolled once off their home so the same
    # house always sends the same person out with the same thing. It is a name, resolved
    # through `weapon_archetype` like anything the player picks up, so a halberd reaches
    # further and a hoe is slow and feeble without a line of new numbers: the two above are
    # the baseline the archetype's multipliers are applied to.
    #
    # A farmer owns no weapon. What they bring to a fight came off their own wall and
    # resolves to the `tool` archetype: short, slow and barely worth the swing. A village
    # is dangerous in numbers, in health and behind its wall, never in what its people are
    # holding, which is why the militia and guard pools are ladders indexed by the
    # settlement's own defence tier (`Village.tier`) rather than one list for the world.
    VILLAGER_WEAPONS: tuple = ("Hoe", "Shovel", "Rake", "Sickle", "Rolling Pin", "Fire Poker", "Broom")
    MILITIA_WEAPON_TIERS: tuple = (
        ("Pitchfork", "Hatchet", "Cudgel", "Woodaxe"),
        ("Spear", "Sword", "Axe", "Mace"),
        ("Halberd", "Longsword", "War Axe", "Mace"),
    )
    GUARD_WEAPON_TIERS: tuple = (
        ("Guard's Spear", "Sword", "Mace"),
        ("Halberd", "Longsword", "Guard's Spear"),
        ("Greatsword", "Warhammer", "War Axe", "Guard's Pike"),
    )
    # A posted archer's bow. Drawn like any other weapon and fired through the same
    # `Projectile` a thrown stone already used.
    ARCHER_WEAPONS: tuple = ("Hunting Bow", "Longbow")
    # The steel and the haft a villager's weapon is drawn in. Nobody in a village carries
    # anything enchanted, so it is one colour rather than an item's rarity tint.
    WEAPON_COLOR: tuple = (176, 178, 186)
    WEAPON_OUTLINE: tuple = (64, 62, 58)
    # Angry villagers are not a hunting party: outrun them by this much and they go back
    # to their houses. Still hostile, still waiting, just no longer following you across
    # the world in a column of eighteen.
    NPC_HOSTILE_RANGE: int = 1100
    # Nobody chats with a wolf on the doorstep: an NPC in reach refuses to talk while
    # anything hostile is standing this close to the player.
    TALK_SAFE_RADIUS: float = 520.0
    # How a kind's share of the spawn roll fades once the player walks past the ground it
    # belongs to: its weight halves every DEPTH_HALF_LIFE beyond its own `min_distance`,
    # never falling below DEPTH_MIN_WEIGHT_FRAC of what it started at, so a slime is still
    # possible in the deep wilds but is no longer what the deep wilds are made of. This is
    # the whole difficulty curve: without it, walking out only added kinds to the roll.
    DEPTH_HALF_LIFE: float = 1500.0
    DEPTH_MIN_WEIGHT_FRAC: float = 0.012
    # What a killed villager leaves on the ground (game/loot.py `loot_villager`). Enough
    # that cutting one down is a real choice against losing the village, nowhere near
    # enough to make a street of them worth farming. A merchant carries a merchant's purse.
    VILLAGER_COIN_RANGE: tuple = (3, 14)
    VILLAGER_ITEM_CHANCE: float = 0.18
    MERCHANT_COIN_MULT: float = 3.0
    MERCHANT_ITEM_CHANCE: float = 0.45
    # A chaser walks to its own bearing on a ring just inside its own reach rather than to
    # the player's exact position, and shoulders aside anything standing where it wants to
    # be, so a pack surrounds the player instead of stacking into one body.
    CHASE_RING_MARGIN: int = 4
    CHASE_ARRIVE: int = 6
    # How much of the overlap between two chasers is undone per frame when they collide.
    SEPARATION_PUSH: float = 0.45
    # Surrounding rather than queueing. The chasers coming for one target are dealt evenly
    # spaced bearings around it (World.assign_surround_slots) instead of each rolling its
    # own, and a chaser only takes a new bearing once its own has drifted this far from the
    # one it holds, so the ring settles instead of reshuffling every frame.
    SLOT_REASSIGN_DEG: float = 55.0
    # ...and only this many of them may be mid-swing at once. The rest hold their place on
    # the ring and keep circling, which is the whole difference between being surrounded
    # and standing in a queue. A token is held until the swing lands or its holder walks
    # out of reach, and the nearest claim it first.
    MAX_ACTIVE_ATTACKERS: int = 3
    # Waiting its turn does not mean standing still: one held back off the tokens walks its
    # bearing round the ring at this rate (degrees per frame), so the circle turns and the
    # player is being stalked rather than politely queued for.
    CIRCLE_SPEED_DEG: float = 1.1
    # Backing away is always slower than walking in, so closing on an archer is a real
    # answer; driven inside this fraction of its keep_distance it stops retreating, stops
    # shooting and fights with the knife it has, at this reach.
    RETREAT_SPEED_MULT: float = 0.55
    CORNERED_FRAC: float = 0.4
    RANGED_MELEE_RANGE: int = 8
    SWING_SPEED: float = 0.007
    # How far out a monster starts winding a swing up, as a multiple of its own reach. The
    # animation is deliberately begun long before the blow could land, so it connects on the
    # frame the monster arrives rather than starting from nothing once it is already there;
    # whether the swing actually hits is Monster.start_attack_anim's call, on the real reach.
    SWING_WINDUP_REACH_MULT: float = 10.0
    # The walk cycle (game/entities/entities.py `Gait`), shared by the player, the villagers,
    # the monsters and the animals. Advanced by the ground actually covered rather than by
    # the clock, so a slowed, rooted or dead-stopped thing never moonwalks: one full cycle
    # per GAIT_STRIDE pixels, arms and legs carried GAIT_ARM/GAIT_LEG at the ends of it, the
    # body lifting GAIT_BOB off the ground at each stride. Movement under GAIT_DEADZONE a
    # frame is standing still, and the swing eases in and out at GAIT_EASE rather than
    # snapping, so stopping settles instead of freezing mid-step.
    # A stride is long and the amplitudes are small on purpose: a short stride at a high
    # amplitude is read as shaking rather than as walking, since the whole sprite is only a
    # few dozen pixels across and every offset lands on a whole pixel when it is blitted.
    GAIT_STRIDE: float = 64.0
    GAIT_DEADZONE: float = 0.35
    GAIT_EASE: float = 0.12
    GAIT_ARM: float = 3.0
    GAIT_BOB: float = 1.2
    GAIT_LEAN_DEG: float = 1.6
    # How far a quadruped's feet carry fore and aft over a stride, in fractions of its own
    # size: legs are the one place an animal's walk can actually be drawn rather than implied.
    GAIT_LEG: float = 0.22
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
    # A detonator has no swing at all: it closes, plants itself, burns a fuse and blows up,
    # killing itself and hurting whatever is standing near it. See `Creeper` below.
    detonate: bool = False
    # How it is drawn (game/entities/monster_art.py): one of "humanoid", "goblin", "hulk",
    # "skeleton", "wraith", "blob", "beast", "robed". A kind's name has to be legible from
    # its silhouette alone, so this is picked per kind rather than defaulted per stat block.
    shape: str = "humanoid"
    # The weapon it visibly carries, as a `WEAPON_ARCHETYPES` name ("bow", "staff", "axe",
    # "sword", "hammer", "dagger"). Drawn by the same `gear.draw_weapon` the player's gear
    # goes through, in the hand the swing animation uses, so what it holds is what it hits
    # with. Empty means bare hands.
    weapon: str = ""
    # The colour of its eyes, the one part of a monster that glows. Read at a glance, and
    # after dark it is the brightest thing on the sprite.
    eye_color: tuple = (255, 120, 60)


@dataclass(frozen=True)
class Creeper:
    """A detonating monster (MonsterKind.detonate), which is a timer rather than a fight.

    It walks in, plants itself inside TRIGGER_RANGE and burns FUSE_MS of fuse before going
    off. Everything about it is counterplay: the fuse is long enough to run out of, the body
    is soft enough to kill in it, and knockback moves the blast rather than stopping it. It
    is killed by its own blast, so nothing it destroys pays the player.
    """

    TRIGGER_RANGE: int = 95
    FUSE_MS: int = 1150
    RADIUS: float = 145.0
    DAMAGE: int = 48
    # Damage falls off from full at the centre to this share of it at the rim, like a keg's.
    EDGE_DAMAGE_FRAC: float = 0.3
    KNOCKBACK: float = 30.0
    SHAKE: float = 18.0


# Ordered weakest to strongest, scaling up with distance from the world center so wandering
# further gets more dangerous. Mobs hit harder and reach the player, but the tougher kinds
# stay spaced out from the world center so there's room to explore before they show up.
# The archer and the hexer are what stop a fight being won by walking backwards: they hold
# their distance and shoot, so closing on them is the only answer.
MONSTER_KINDS: tuple[MonsterKind, ...] = (
    MonsterKind(
        "Slime", (90, 190, 90), 22, 16, 3, 10, 8, min_distance=0, weight=10, shape="blob", eye_color=(240, 255, 180)
    ),
    MonsterKind(
        "Goblin",
        (110, 150, 80),
        22,
        14,
        5,
        9,
        7,
        min_distance=1000,
        weight=7,
        group=(2, 4),
        shape="goblin",
        weapon="axe",
        eye_color=(255, 210, 70),
    ),
    MonsterKind(
        "Wolf",
        (140, 140, 140),
        26,
        32,
        5,
        10,
        13,
        min_distance=2000,
        weight=6,
        group=(2, 3),
        shape="beast",
        eye_color=(255, 235, 130),
    ),
    MonsterKind(
        "Archer",
        (168, 122, 62),
        26,
        26,
        4,
        420,
        11,
        min_distance=2800,
        weight=4,
        ranged=True,
        keep_distance=260,
        shot_cooldown_ms=1900,
        shape="humanoid",
        weapon="bow",
        eye_color=(255, 190, 90),
    ),
    MonsterKind(
        "Skeleton",
        (215, 210, 195),
        26,
        42,
        3,
        11,
        16,
        min_distance=3600,
        weight=4,
        shape="skeleton",
        weapon="sword",
        eye_color=(120, 220, 255),
    ),
    MonsterKind(
        "Bandit",
        (150, 40, 40),
        28,
        55,
        4,
        12,
        19,
        min_distance=4500,
        weight=4,
        shape="humanoid",
        weapon="dagger",
        eye_color=(255, 150, 90),
    ),
    MonsterKind(
        "Wraith",
        (150, 130, 200),
        24,
        34,
        6,
        10,
        15,
        min_distance=5400,
        weight=3,
        flank_deg=55,
        shape="wraith",
        eye_color=(200, 160, 255),
    ),
    MonsterKind(
        "Troll", (60, 90, 55), 34, 95, 3, 14, 29, min_distance=7200, weight=2, shape="hulk", eye_color=(255, 240, 120)
    ),
    MonsterKind(
        "Ogre",
        (120, 95, 70),
        40,
        150,
        2,
        16,
        34,
        min_distance=8400,
        weight=2,
        charge=True,
        shape="hulk",
        weapon="hammer",
        eye_color=(255, 130, 60),
    ),
    MonsterKind(
        "Hexer",
        (128, 78, 188),
        28,
        48,
        3,
        480,
        17,
        min_distance=6400,
        weight=2,
        ranged=True,
        keep_distance=320,
        shot_cooldown_ms=2400,
        shape="robed",
        weapon="staff",
        eye_color=(215, 130, 255),
    ),
    MonsterKind(
        "Creeper",
        (96, 168, 92),
        26,
        30,
        4,
        Creeper.TRIGGER_RANGE,
        0,
        min_distance=3200,
        weight=3,
        detonate=True,
        shape="creeper",
        eye_color=(255, 150, 60),
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
    # Look, same three fields a MonsterKind carries and drawn by the same code: a boss is a
    # monster with an aura, so it gets a silhouette rather than a bigger circle.
    shape: str = "hulk"
    weapon: str = ""
    eye_color: tuple = (255, 120, 60)


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
        shape="hulk",
        weapon="hammer",
        eye_color=(255, 100, 70),
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
        shape="robed",
        weapon="staff",
        eye_color=(220, 150, 255),
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
        shape="hulk",
        eye_color=(160, 255, 170),
    ),
)


@dataclass(frozen=True)
class MonsterArt:
    """How a hostile thing is drawn (game/entities/monster_art.py), above whatever silhouette
    its kind picked. Everything here applies to every shape, because a monster is read from
    three things before its outline: that it stands on the ground, that it is breathing, and
    that it is looking at you."""

    # The shadow under the body, which is what stops a sprite floating over the grass.
    SHADOW_ALPHA: int = 70
    SHADOW_WIDTH: float = 1.05  # as a multiple of the body size
    SHADOW_HEIGHT: float = 0.42
    SHADOW_OFFSET: float = 0.22  # pushed down the screen so the body sits in front of it
    # The idle breath: a slow scale pulse, offset per monster so a pack does not pulse in
    # unison. A creature standing perfectly still reads as a sprite rather than as alive.
    BREATH_PERIOD_MS: int = 1900
    BREATH_AMOUNT: float = 0.045
    # Eyes. The glow is a soft disc behind the dot; both grow when the thing has noticed the
    # player, which is the only tell a monster gives that it is coming.
    EYE_RADIUS: float = 0.055  # multiple of the body size
    EYE_GLOW_MULT: float = 2.4
    EYE_GLOW_ALPHA: int = 55
    AGGRO_EYE_MULT: float = 1.3
    AGGRO_GLOW_ALPHA: int = 100
    # A wraith has no solid body: it drifts between these two alphas as it breathes.
    WRAITH_ALPHA_MIN: int = 120
    WRAITH_ALPHA_MAX: int = 215
    # A monster's steel is rusted and plain, never rarity-coloured like the player's.
    WEAPON_COLOR: tuple = (132, 126, 116)
    WEAPON_OUTLINE: tuple = (42, 38, 34)


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
    # Deliberately well past the settled ring: a boss is what the deep wilds hold, not
    # something met on the walk to the second village.
    ROAM_MIN_DISTANCE: int = 5500
    # How wide a band past that a quest's hunt target is placed in.
    QUEST_SPAWN_BAND: int = 2500
    # No boss of any kind stands closer than this to the world centre, however it was
    # spawned: the landmark guardian placed there from the first frame, a roaming one, a
    # quest target, a world event. Finding one is meant to be a journey rather than
    # something walked into on the way out of the starting town.
    MIN_DIST_FROM_START: int = 2200
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
