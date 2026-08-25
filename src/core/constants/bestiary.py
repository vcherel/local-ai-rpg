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
    # The health bar floating under anything that can be hurt. One geometry for the whole
    # bestiary and every villager: a bar that changed size by kind would read as a status
    # of its own rather than as the same measure taken of a different body. The player's
    # own bar is HUD and sized separately (`Player.HEALTH_BAR_WIDTH`).
    HEALTH_BAR_WIDTH: int = 60
    HEALTH_BAR_HEIGHT: int = 8
    HEALTH_BAR_OFFSET: int = 10
    HEALTH_BAR_BORDER: int = 2
    # NPCs wander around their spawn point: walk to a random spot within
    # NPC_WANDER_RADIUS, then idle for a random duration before moving again.
    NPC_WANDER_SPEED: float = 1.5
    NPC_WANDER_RADIUS: int = 250
    NPC_IDLE_MIN_MS: int = 2000
    NPC_IDLE_MAX_MS: int = 7000
    # A monster that has not noticed anybody roams instead of standing where it was put.
    # Slower and over a wider circle than a villager's stroll, because it is patrolling
    # ground rather than living on a street; a monster planted on the spot until the player
    # walks into its detection ring read as something waiting to be triggered, which is
    # exactly what it was.
    MONSTER_WANDER_SPEED: float = 0.9
    MONSTER_WANDER_RADIUS: int = 420
    MONSTER_IDLE_MIN_MS: int = 1800
    MONSTER_IDLE_MAX_MS: int = 6000
    # How many spots a wanderer may try before idling again rather than strolling into a
    # wall. Inside a village half the ground around a villager's own home is their house,
    # and a stroll that ends against it is a body shuffling on its own doorstep.
    WANDER_PICK_TRIES: int = 5
    # A body that means to be moving and is not: wedged in the corner of a building, in
    # the neck of an L, against a wall its slide cannot carry it round. Nothing detects that
    # from geometry, because it is standing on legal ground; only time says so. Move less
    # than WEDGE_STEP pixels a frame for WEDGE_MS while meaning to move and you are prised
    # out onto open ground (`WorldNavigation.unwedge`).
    WEDGE_MS: float = 1600.0
    WEDGE_STEP: float = 0.35
    # How much clearance that search asks for, as a multiple of the body's own radius: a
    # corner is legal ground, so a spot is only worth moving to if it has room around it.
    WEDGE_CLEARANCE: float = 1.7
    # NPCs stop wandering and face the player when he gets this close.
    NPC_WANDER_PAUSE_DISTANCE: int = 120
    # How long a villager keeps looking down the shot they just took (`NPC.aim_at`), rather
    # than being turned back to face their own footsteps by the next frame of wandering.
    NPC_AIM_HOLD_MS: int = 700
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
    # Even the ones who never trained arm themselves better the further out they live: a
    # border farmer has a broom, someone whose street is walked by wolves keeps a hatchet by
    # the door and someone in a deep wilds town owns an actual blade. Indexed by the
    # settlement's tier like the two ladders below it.
    VILLAGER_WEAPON_TIERS: tuple = (
        ("Hoe", "Shovel", "Rake", "Sickle", "Rolling Pin", "Fire Poker", "Broom"),
        ("Hoe", "Sickle", "Fire Poker", "Hatchet", "Mallet", "Cudgel"),
        ("Hatchet", "Cudgel", "Pitchfork", "Woodaxe", "Knife", "Sword"),
    )
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
    # A disguised kind wears a villager until the player is close enough to see what it is
    # (`Husk` below): it holds still, gives none of the tells a monster gives, and only
    # then reveals and comes. See `Monster.revealed`.
    disguise: bool = False
    # A detonator has no swing at all: it closes, plants itself, burns a fuse and blows up,
    # killing itself and hurting whatever is standing near it. See `Creeper` below.
    detonate: bool = False
    # How it is drawn (game/entities/monster_art.py): one of "humanoid", "goblin", "hulk",
    # "skeleton", "wraith", "blob", "beast", "robed", "creeper", "husk". A kind's name has to be legible from
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
class Husk:
    """A monster wearing a villager (MonsterKind.disguise).

    Its whole fight is the moment before it: it stands where a person would stand, gives
    none of the tells a monster gives (no lit eyes, no walk, no weapon) and does nothing at
    all until the player is inside REVEAL_RANGE. It is deliberately not a perfect copy: the
    body is a shade too grey, the arms hang too low and the eyes carry the faintest light,
    so somebody paying attention can tell a husk from a villager at a distance and somebody
    walking through the wilds cannot.

    Revealing is a lunge rather than a start of a chase: it gets LUNGE_MS at LUNGE_SPEED_MULT
    of its own pace, which is what makes an ambush cost something even to a player who
    spotted it a step too late.
    """

    REVEAL_RANGE: int = 170
    LUNGE_MS: int = 900
    LUNGE_SPEED_MULT: float = 2.1
    # The light in its eyes while it is still pretending, against the (255, 150, 90) it
    # opens with. Low enough to be missed, never zero: a face with nothing behind it at all
    # would leave the disguise with no tell whatsoever.
    DISGUISE_EYE: tuple = (168, 146, 122)


@dataclass(frozen=True)
class Creeper:
    """A detonating monster (MonsterKind.detonate), which is a timer rather than a fight.

    It walks in, plants itself inside TRIGGER_RANGE and burns FUSE_MS of fuse before going
    off. Everything about it is counterplay: the fuse is long enough to run out of, the body
    is soft enough to kill in it, and knockback moves the blast rather than stopping it. It
    is killed by its own blast, so nothing it destroys pays the player.
    """

    TRIGGER_RANGE: int = 95
    # A short fuse and a heavy blast. The counterplay is unchanged and still threefold (walk
    # out of the ring, shove it away with a cudgel, kill it inside its own timer), it just
    # can no longer be taken at a stroll: a creeper that was out-walked by accident was
    # scenery rather than a threat.
    FUSE_MS: int = 800
    RADIUS: float = 145.0
    DAMAGE: int = 68
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
        "Husk",
        (146, 138, 150),
        Entities.NPC_SIZE,
        50,
        4,
        13,
        24,
        min_distance=4000,
        weight=3,
        disguise=True,
        shape="husk",
        eye_color=(255, 150, 90),
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
    # A shrinking boss loses body with its health, stepping down through `Boss.SHRINK_BANDS`
    # instead of holding one silhouette all fight: huge and slow, then quick, then small and
    # frantic. The only place a boss's own stat block moves for a reason other than enrage.
    shrinks: bool = False


# The boss archetypes. Stats sit well above the toughest normal monster (Troll, 60 hp)
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
    BossKind(
        "devourer",
        (150, 90, 160),
        (225, 130, 235),
        96,
        520,
        2.0,
        30,
        30,
        abilities=("slam", "summon"),
        summon_kind="Slime",
        flavor="a vast devouring mass that sheds itself as it is wounded",
        shape="blob",
        eye_color=(255, 210, 120),
        shrinks=True,
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

    # Summon: adds spawned in a ring around the boss. Nothing appears out of nothing: each
    # spot is marked first and the thing standing there arrives when the mark has finished
    # (`Boss._summon_adds`), so a fight that suddenly has three more bodies in it is
    # something the player watched happen and could step away from. Whatever arrives is held
    # where it stands for a moment while it climbs out, which is what the mark promised.
    SUMMON_COUNT: int = 3
    SUMMON_RADIUS: int = 170
    SUMMON_TELEGRAPH_MS: float = 750.0
    SUMMON_EMERGE_MS: int = 350

    # Coming up out of the ground. A boss is held where it stands for this long before it
    # is a fight at all: the ring opens under it, it climbs out, and the roar, the flash and
    # the shake land on the frame it finishes. Nothing arrives from nowhere in this world,
    # and the thing that matters most is the thing that may least afford to.
    RISE_MS: float = 1300.0
    RISE_SHAKE: float = 30.0
    RISE_FLASH: float = 0.45

    # A shrinking boss (BossKind.shrinks) steps down a band each time its health passes the
    # threshold, and never back up. Each band is (health fraction it starts at, size, speed
    # multiplier, damage multiplier): it trades reach and mass for pace, so the fight opens
    # as something to be kept away from and ends as something that cannot be walked away
    # from. Only the last band can be knocked back, which is the reward for cutting it down
    # to size.
    SHRINK_BANDS: tuple = ((1.0, 1.0, 1.0, 1.0), (0.66, 0.72, 1.45, 0.8), (0.33, 0.46, 2.0, 0.62))
    # Which band onward it can be shoved about, counted from the last one back.
    SHRINK_KNOCKBACK_BAND: int = 2

    # A slain boss always drops a lootbox of this rarity, on top of the usual roll.
    REWARD_RARITY: str = "legendary"

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
    # ...and none of them stands on anybody's doorstep either, however far out that doorstep
    # is. Measured past a settlement's own grounds, so a boss is always a walk out of town
    # rather than something the militia inherits. The world's own margin
    # (`World.VILLAGE_SPAWN_MARGIN`) is what keeps a wolf off the fields; a boss needs the
    # far side of them.
    MIN_DIST_FROM_VILLAGE: int = 1200
    ROAM_CHECK_INTERVAL_MS: int = 45_000
    ROAM_SPAWN_MIN_DIST: int = 900
    ROAM_SPAWN_MAX_DIST: int = 1400
    # How thick with bosses the world is, as a ramp on the player's own distance from the
    # centre: the settled ring holds one at a time and the deep wilds hold five, rolled far
    # more often. This is the boss half of difficulty-by-distance, and it moves how many
    # there are rather than what any one of them is made of.
    ROAM_CHANCE_NEAR: float = 0.25
    ROAM_CHANCE_FAR: float = 0.7
    MAX_ACTIVE_NEAR: int = 1
    MAX_ACTIVE_FAR: int = 5
    # Where the far end of both ramps is measured, as distance from the world centre.
    DENSITY_FAR_DISTANCE: int = 16_000

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
    # The one animal that lives underground. `weight=0` keeps it out of the wilderness roll:
    # a bat is placed, by the cave it belongs to, and never met in a field.
    CritterKind(
        "bat",
        (92, 78, 96),
        12,
        10,
        weight=0,
        temperament="predator",
        group=(3, 5),
        hit_radius_mult=0.9,
        wander_speed=1.6,
        sprint_mult=2.2,
        stamina_ms=1200,
        damage=6,
        chase_speed=2.6,
        attack_range=22,
        attack_cooldown_ms=650,
        detection=420,
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
