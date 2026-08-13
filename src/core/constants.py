from dataclasses import dataclass

import pygame

# Movement and animation speeds were tuned for 60 FPS. Scaling per-frame motion by
# dt * TARGET_FPS / 1000 keeps that feel identical at 60 FPS while staying consistent
# at any other frame rate.
TARGET_FPS: int = 60


@dataclass(frozen=True)
class Screen:
    WIDTH: int = 1800
    HEIGHT: int = 900
    ORIGIN_X: int = WIDTH // 2
    ORIGIN_Y: int = HEIGHT // 2


@dataclass(frozen=True)
class Player:
    HP: int = 100
    # Passive regen is a slow between-fights trickle, not a heal button: it only starts
    # REGEN_DELAY_MS after the last hit taken, so a fight is won with potions, lifesteal
    # and positioning rather than by backing off for two seconds. A regen potion is
    # deliberately exempt from the delay, it's what you drink when you're already hurt.
    REGEN_RATE: float = 0.00025
    REGEN_DELAY_MS: int = 12000
    SIZE: int = 30

    SPEED: int = 5
    RUN_SPEED: int = 7

    INTERACTION_DISTANCE: int = 30
    # Loot is picked up from a bit farther out than an NPC is talked to: the prompt over a
    # dropped item should show while walking past it, not only when standing on it.
    PICKUP_DISTANCE: int = 70
    ATTACK_REACH: int = 17
    ATTACK_DAMAGE: int = 5


@dataclass(frozen=True)
class Death:
    """Dying doesn't reload the save at the same spot with full HP for free: it costs
    coins and leaves the player weakened for a while after respawning at world spawn.

    The weakness is meant to reshape the next few minutes rather than tickle them: a
    third of the run's coins gone, and three minutes of hitting softer, moving slower
    and carrying less health. A fire or an inn bed is what shakes it off early."""

    COIN_LOSS_PCT: float = 0.45
    DEBUFF_DURATION_S: float = 180.0
    DEBUFF_DAMAGE_MULT: float = 0.6
    DEBUFF_SPEED_MULT: float = 0.85
    DEBUFF_MAX_HP_MULT: float = 0.8
    # How long the death screen holds before the player is put back at world spawn.
    RESPAWN_DELAY_S: float = 2.5


@dataclass(frozen=True)
class Shield:
    """The offhand shield and the guard it holds (game/entities/player.py).

    A shield is worn in its own slot and raised by holding the block key. Raised, it eats
    a share of any hit coming from the front and drains the guard meter by what it stopped;
    run the meter out and the guard breaks, leaving the player wide open for a moment. So a
    shield rewards blocking the blow you saw coming, not standing behind it forever.
    """

    BLOCK_BASE: float = 0.45  # fraction of a frontal hit stopped by a plain shield
    BLOCK_PER_BONUS: float = 0.03  # ...plus this per point of the shield's bonus
    BLOCK_MAX: float = 0.85
    # Only hits arriving within this cone of the player's facing are blocked at all.
    ARC_DEG: float = 150.0
    SPEED_MULT: float = 0.55  # movement while the shield is up

    GUARD_MAX: float = 60.0
    GUARD_REGEN_PER_S: float = 12.0
    # Guard only comes back once the shield has been down (or unhit) this long.
    GUARD_REGEN_DELAY_MS: int = 1200
    # Running the guard out breaks it: no blocking at all until this passes.
    GUARD_BREAK_MS: int = 2500
    GUARD_BREAK_SHAKE: float = 12.0


@dataclass(frozen=True)
class Projectile:
    SPEED: int = 14
    RANGE: int = 650
    SIZE: int = 6


@dataclass(frozen=True)
class Combat:
    CRIT_MULT: float = 1.8
    # Extra screen shake added on top of a weapon's base shake when a hit crits.
    CRIT_SHAKE_BONUS: float = 6.0
    PLAYER_HURT_SHAKE: float = 5.0
    # Kick when a shop crate is smashed.
    CRATE_SHAKE: float = 5.0
    # Softer kicks for the smaller outdoor breaks: a decorative pot/bush, or a window pane.
    DECOR_BREAK_SHAKE: float = 3.0
    WINDOW_SHAKE: float = 3.5
    # Camera never shakes more than this, so heavy hits stay readable rather than nauseating.
    MAX_SHAKE: float = 30.0
    SHAKE_DECAY: float = 0.82  # per-60fps-frame multiplier

    # Hit-stop: gameplay dt is multiplied by this for a few frames after a heavy hit,
    # a near-freeze that sells impact without new animation work.
    HITSTOP_SLOW_FACTOR: float = 0.06
    HITSTOP_CRIT_MS: float = 45.0
    HITSTOP_KILL_MS: float = 55.0
    HITSTOP_BOSS_MS: float = 110.0

    # Player-hurt screen vignette: triggered amount decays back to 0 at this rate.
    VIGNETTE_DECAY: float = 0.90  # per-60fps-frame multiplier
    PLAYER_HURT_VIGNETTE: float = 0.7


@dataclass(frozen=True)
class WeaponArchetype:
    """Feel profile for a weapon family, resolved from the weapon name's keyword.

    Multipliers apply to the base melee values (`Player.ATTACK_REACH/ATTACK_DAMAGE`,
    `Entities.SWING_SPEED`). `shake` and `knockback` are in world pixels.
    """

    name: str
    reach_mult: float
    # Polearm blind spot: a living target whose centre is closer than this many world
    # pixels to the player is missed entirely, so a spear hits at the end of its shaft
    # instead of stabbing something pressed against the player's chest. 0 disables it.
    min_hit_distance: float
    swing_mult: float  # >1 swings faster (cosmetic animation speed)
    damage_mult: float
    cooldown_ms: int  # minimum time between swings
    knockback: float  # pixels the target is shoved on a hit
    crit_chance: float
    cleave: bool  # hit every target in the swing radius, not just the nearest
    cleave_radius_mult: float  # widens the hit radius for cleave weapons
    shake: float  # base screen shake on a hit
    ranged: bool  # fires a projectile instead of swinging
    uses_ammo: bool  # ranged weapons only: consume an ammo item per shot


UNARMED = WeaponArchetype("unarmed", 1.0, 0.0, 1.0, 1.0, 350, 8, 0.08, False, 1.0, 2.0, False, False)

WEAPON_ARCHETYPES: dict[str, WeaponArchetype] = {
    "dagger": WeaponArchetype("dagger", 0.8, 0.0, 1.8, 0.7, 180, 4, 0.30, False, 1.0, 2.0, False, False),
    "sword": WeaponArchetype("sword", 1.0, 0.0, 1.0, 1.0, 350, 10, 0.12, True, 1.4, 4.0, False, False),
    "axe": WeaponArchetype("axe", 1.05, 0.0, 0.7, 1.25, 520, 14, 0.10, True, 1.8, 7.0, False, False),
    "hammer": WeaponArchetype("hammer", 0.9, 0.0, 0.55, 1.6, 620, 26, 0.05, False, 1.0, 14.0, False, False),
    # The spear trades the whole close range for reach and a heavy thrust: nothing within
    # 46px of the player is hit at all, and the ring it does cover runs out past 85px.
    "spear": WeaponArchetype("spear", 2.2, 46.0, 0.9, 1.35, 380, 14, 0.12, False, 1.0, 5.0, False, False),
    "staff": WeaponArchetype("staff", 1.0, 0.0, 1.0, 1.0, 420, 6, 0.10, False, 1.0, 2.0, True, False),
    "bow": WeaponArchetype("bow", 1.0, 0.0, 1.0, 1.0, 400, 4, 0.10, False, 1.0, 1.0, True, True),
}

# Weapon-name keyword -> archetype key. Keywords mirror items.WEAPON_KEYWORDS.
_KEYWORD_TO_ARCHETYPE = {
    "dagger": "dagger",
    "knife": "dagger",
    "sword": "sword",
    "blade": "sword",
    "axe": "axe",
    "club": "hammer",
    "mace": "hammer",
    "hammer": "hammer",
    "spear": "spear",
    "lance": "spear",
    "staff": "staff",
    "bow": "bow",
}


def weapon_archetype(name: str | None) -> WeaponArchetype:
    """Resolve a weapon name to its feel profile; generic/unknown weapons swing like a sword."""
    if not name:
        return UNARMED
    lower = name.lower()
    for keyword, key in _KEYWORD_TO_ARCHETYPE.items():
        if keyword in lower:
            return WEAPON_ARCHETYPES[key]
    return WEAPON_ARCHETYPES["sword"]


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

    # Buildings keep their distance from each other, the spawn point and the world edge.
    MIN_GAP: int = 350
    SPAWN_CLEARANCE: int = 700
    EDGE_MARGIN: int = 250

    DOOR_WIDTH: int = 70
    # The entry trigger straddles the front wall, extending this far on each side of it.
    DOOR_DEPTH: int = 35

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
    "pot" and "bush" are pure decoration, just a satisfying puff with no reward."""

    PER_BUILDING_MIN: int = 1
    PER_BUILDING_MAX: int = 2
    SIZE: int = 30
    HIT_RADIUS: int = 20
    # Relative pick weight among kinds scattered near a building.
    KIND_WEIGHTS: tuple = (("barrel", 5), ("pot", 3), ("bush", 3))
    # How much punishment each kind takes before it gives. A bush is cleared in a swipe,
    # a barrel has to be worked at; the props are scenery you fight through, not confetti.
    HP = {"barrel": 20, "pot": 8, "bush": 5}


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

    REGION_CHUNKS: int = 3
    REGION_CHANCE: float = 0.7
    # Two regions can both settle near their shared border; the later one stands down, so
    # there is always this much empty wilderness between one settlement and the next.
    MIN_GAP: int = 2200
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
class Minimap:
    """The top right map (ui/minimap.py). Small, fixed zoom, no live entities: it says
    where you have been, never what is around you."""

    SIZE: int = 180
    MARGIN: int = 10
    PADDING: int = 6
    # World span across the whole map. Roughly one and a half screens, so it orients
    # without scouting ahead.
    RANGE: int = 2600

    UNSEEN_COLOR: tuple = (18, 17, 22)
    GROUND_COLOR: tuple = (58, 74, 48)
    PLAZA_COLOR: tuple = (120, 98, 70)
    PLAYER_COLOR: tuple = (245, 245, 245)
    POI_COLORS = {"ruins": (150, 148, 140), "camp": (215, 140, 60), "shrine": (200, 195, 145)}


@dataclass(frozen=True)
class PointsOfInterest:
    """Wilderness landmarks scattered across the map, away from town (game/entities/poi.py).
    "ruins" is a smashable loot cache, better odds and rarity than a plain outdoor barrel
    since it takes more effort to find; "shrine" is pure discovery flavor, no loot at all;
    a "camp" rolls into either a bandit camp (guarded cache) or a traveller camp (a camper
    who trades and points the way), and either way its fire can be rested at once the camp
    is settled.
    """

    # Points of interest stream in per chunk like the floor details, so the wilderness
    # keeps offering something to find however far out the player walks. At most one per
    # chunk, kept CHUNK_MARGIN away from the chunk's edges, which is what spaces
    # neighbouring chunks' landmarks apart without any cross-chunk bookkeeping.
    PER_CHUNK_CHANCE: float = 0.55
    CHUNK_MARGIN: int = 260
    MIN_DIST_FROM_BUILDING: int = 400
    MIN_DIST_FROM_CENTER: int = 900
    SIZE: int = 46
    HIT_RADIUS: int = 34
    # Relative pick weight among kinds scattered across the wilderness.
    KIND_WEIGHTS: tuple = (("ruins", 4), ("camp", 3), ("shrine", 3))

    # A shrine shows its flavor line the first time the player gets this close.
    DISCOVER_DISTANCE: int = 160
    SHRINE_MESSAGES: tuple = (
        "An old shrine, worn smooth by countless hands.",
        "Faded offerings lie at the foot of this shrine.",
        "The carvings on this shrine predate any living memory.",
        "Someone has left a wilted flower at this shrine.",
    )

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


@dataclass(frozen=True)
class LootBox:
    # Chance a slain monster drops a lootbox.
    DROP_CHANCE: float = 0.2
    COIN_MIN: int = 3
    COIN_MAX: int = 12
    # Chance the box also contains an item on top of coins, indexed by rarity tier
    # (common..legendary), so a legendary box is far less likely to be coins only.
    ITEM_CHANCE_BY_TIER: tuple = (0.35, 0.45, 0.60, 0.80, 1.0)
    # Item type roll weights (weapon, armor, accessory, ammo, potion), indexed by rarity
    # tier. Common stays an even split; higher tiers skew hard toward gear so a legendary
    # box is unlikely to hand back "just" a stack of arrows or a potion.
    TYPE_WEIGHTS_BY_TIER: tuple = (
        (1, 1, 1, 1, 1),
        (2, 2, 2, 1, 1),
        (3, 3, 3, 1, 1),
        (4, 4, 4, 1, 1),
        (5, 5, 5, 1, 1),
    )


@dataclass(frozen=True)
class Potions:
    """Drinkable consumables (item_type "potion"). Every table is indexed by rarity
    tier (common..legendary), so a legendary flask of the same name is simply stronger.

    "heal" restores hp on the spot; the other four start a timed buff held on the
    player (`Player.buffs`) and read back by the matching multiplier helpers.
    """

    HEAL_FRAC: tuple = (0.25, 0.40, 0.55, 0.70, 0.90)  # fraction of max hp restored at once
    REGEN_RATE: tuple = (0.0025, 0.0035, 0.0045, 0.006, 0.008)  # extra hp/ms while active
    STRENGTH_MULT: tuple = (1.15, 1.25, 1.40, 1.60, 1.90)  # damage dealt multiplier
    SWIFTNESS_MULT: tuple = (1.12, 1.20, 1.30, 1.45, 1.60)  # move speed multiplier
    STONESKIN_REDUCTION: tuple = (2, 4, 6, 9, 13)  # flat damage reduction on top of armour

    # How long a buff lasts, in seconds. Unused by "heal", which is instant.
    DURATION_S: tuple = (12.0, 15.0, 18.0, 22.0, 26.0)

    # Worth before the rarity multiplier, used by items.base_value for shop pricing.
    BASE_VALUE: int = 15

    # Liquid colour per effect, tinting the flask icon so a potion reads at a glance.
    COLORS = {
        "heal": (214, 62, 72),
        "regen": (92, 208, 118),
        "strength": (232, 132, 46),
        "swiftness": (88, 198, 234),
        "stoneskin": (172, 172, 188),
    }

    # Potions the player can drink straight from the HUD with the number keys.
    QUICK_SLOTS: int = 4


@dataclass(frozen=True)
class Affixes:
    """Special effects rolled onto weapons and armour, on top of their flat bonus.

    Every table is indexed by rarity tier (common..legendary); a value of 0 at the
    common tier means the affix can't roll there. COUNT_BY_TIER caps how many distinct
    affixes an item of each tier carries.
    """

    COUNT_BY_TIER: tuple = (0, 1, 1, 2, 3)

    WEAPON_POOL: tuple = ("lifesteal", "burn", "crit", "execute")
    ARMOR_POOL: tuple = ("thorns", "dodge", "regen_still")

    # Weapon affixes.
    LIFESTEAL: tuple = (0.0, 0.06, 0.09, 0.12, 0.15)  # fraction of damage dealt healed back
    BURN: tuple = (0, 2, 3, 4, 6)  # damage per burn tick
    CRIT: tuple = (0.0, 0.06, 0.09, 0.13, 0.18)  # added crit chance
    EXECUTE: tuple = (0.0, 0.08, 0.11, 0.15, 0.20)  # kill a non-boss left below this fraction of max hp

    # Burn timing is fixed; only the per-tick damage scales with rarity.
    BURN_TICKS: int = 4
    BURN_INTERVAL_MS: int = 500

    # Armour affixes.
    THORNS: tuple = (0, 2, 3, 5, 8)  # flat damage reflected to a melee attacker
    DODGE: tuple = (0.0, 0.05, 0.08, 0.12, 0.16)  # chance to take no damage from a hit
    REGEN_STILL: tuple = (0.0, 0.002, 0.003, 0.005, 0.008)  # extra hp/ms regen while standing still

    # Legendary signature effects: build-defining, not just bigger numbers. Every
    # legendary weapon/armour guarantees exactly one of these on top of its normal
    # affix rolls (roll_affixes in items.py), so a legendary always feels distinct
    # from an epic instead of just having one more line of the same pool.
    WEAPON_LEGENDARY_POOL: tuple = ("rampage", "bloodlust", "chainstrike")
    ARMOR_LEGENDARY_POOL: tuple = ("guardian_ward", "retribution")

    # Rampage: every Nth landed hit (melee) or shot fired (ranged) is a guaranteed,
    # amplified crit.
    RAMPAGE_EVERY_N_HITS: int = 4
    RAMPAGE_BONUS_MULT: float = 1.75  # extra multiplier stacked on top of the normal crit

    # Bloodlust: killing anything with this weapon buffs damage for a while, refreshed
    # (not stacked) by the next kill.
    BLOODLUST_DAMAGE_MULT: float = 1.3
    BLOODLUST_DURATION_S: float = 8.0

    # Chain Strike: a landed hit also strikes the nearest other enemy within range.
    CHAINSTRIKE_DAMAGE_FRAC: float = 0.6
    CHAINSTRIKE_RADIUS: float = 220.0

    # Guardian's Ward: a lethal-looking hit instead clamps hp at this fraction of max and
    # grants a brief window of total invulnerability, on an internal cooldown.
    GUARDIAN_WARD_HP_FRAC: float = 0.2
    GUARDIAN_WARD_INVULN_S: float = 2.0
    GUARDIAN_WARD_COOLDOWN_S: float = 45.0

    # Retribution: reflects a fraction of incoming damage back at a melee attacker
    # (before armour reduction), unlike flat Thorns this scales with how hard the hit was.
    RETRIBUTION_REFLECT_FRAC: float = 0.2


@dataclass(frozen=True)
class Decals:
    """Blood splats left on the ground by hits and kills (core/decals.py)."""

    LIFE_MS: float = 18_000.0
    # Oldest decal is dropped once the list grows past this, so a long fight
    # never leaves an unbounded number of splats to draw.
    MAX_COUNT: int = 300

    HIT_RADIUS: int = 7
    KILL_RADIUS: int = 22
    BOSS_KILL_RADIUS: int = 38
    PLAYER_HURT_RADIUS: int = 11

    # A kill throws a fan of droplets out along the killing blow rather than leaving one
    # tidy circle: the pool marks where it died, the spray says how it went.
    SPRAY_SPREAD_DEG: float = 110.0
    KILL_SPRAY_COUNT: int = 10
    KILL_SPRAY_DISTANCE: tuple = (16.0, 105.0)
    KILL_SPRAY_RADIUS: tuple = (3.0, 9.0)
    # A boss bleeds across half the arena.
    BOSS_SPRAY_COUNT: int = 24
    BOSS_SPRAY_DISTANCE: tuple = (25.0, 210.0)
    BOSS_SPRAY_RADIUS: tuple = (5.0, 15.0)
    # Deep arterial red, darker than the bright particle spray so the two read as
    # "still in the air" versus "already on the ground".
    BLOOD_COLOR: tuple = (128, 16, 16)


@dataclass(frozen=True)
class RarityTier:
    name: str
    color: tuple
    weight: float
    weapon_bonus: tuple
    armor_bonus: tuple
    accessory_bonus: tuple
    price_mult: float


@dataclass(frozen=True)
class Rarity:
    TIERS: tuple = (
        RarityTier("common", (200, 200, 200), 50, (1, 2), (1, 1), (1, 2), 1.0),
        RarityTier("uncommon", (96, 200, 96), 27, (3, 4), (2, 2), (3, 4), 1.5),
        RarityTier("rare", (90, 150, 255), 14, (5, 7), (3, 3), (5, 7), 2.5),
        RarityTier("epic", (190, 105, 240), 7, (8, 10), (4, 5), (8, 10), 4.0),
        # Weight kept low on purpose: a legendary should feel like an event, not a
        # regular find. Its power comes from a signature effect (Affixes) rather than
        # from showing up often.
        RarityTier("legendary", (255, 150, 40), 0.5, (11, 14), (6, 7), (11, 14), 6.0),
    )
    # Quest rewards skip the low tiers so completing a quest always feels worth it, but
    # legendary still stays a rare highlight rather than the default quest payout.
    QUEST_REWARD_WEIGHTS: tuple = (0, 0, 60, 30, 3)


@dataclass(frozen=True)
class Stats:
    # Character progression is use-based: every stat starts at level 1 and gains XP
    # from a matching action. Effects are pure functions of the level, so growing a
    # stat never touches the save format.
    NAMES: tuple = ("strength", "resistance", "speed", "vitality", "bartering", "persuasion")

    # XP needed for level 1 -> 2, scaled by XP_GROWTH for each further level.
    BASE_XP: float = 35.0
    XP_GROWTH: float = 1.45

    # Combat stats level from very frequent actions (per hit, per frame moved) compared
    # to persuasion/bartering, so they get an extra multiplier on top of the shared curve.
    COMBAT_STAT_NAMES: tuple = ("strength", "resistance", "speed", "vitality")
    COMBAT_XP_GROWTH_MULTIPLIER: float = 3.0

    # Effect increment per level above 1.
    STRENGTH_PER_LEVEL: int = 2  # flat attack damage
    RESISTANCE_PER_LEVEL: int = 1  # flat damage reduction
    SPEED_PER_LEVEL: float = 0.04  # +4% move speed
    VITALITY_HP_PER_LEVEL: int = 15  # extra max HP
    VITALITY_REGEN_PER_LEVEL: float = 0.0001
    BARTER_PER_LEVEL: float = 0.03  # 3% better prices per level

    # Quest reward weight shifted from "rare" to "legendary" per level above 1, capped so
    # even a maxed-out persuasion character still sees a legendary reward well under a
    # fifth of the time, rather than persuasion alone trivialising legendary drop odds.
    PERSUASION_WEIGHT_SHIFT_PER_LEVEL: float = 0.8
    PERSUASION_MAX_WEIGHT_SHIFT: float = 10.0

    # Effect per point of an equipped accessory's bonus, on top of trained stats.
    ACCESSORY_SPEED_PER_BONUS: float = 0.01  # +1% move speed per bonus point
    ACCESSORY_REGEN_PER_BONUS: float = 0.0005  # extra HP regen per bonus point
    ACCESSORY_LUCK_PER_BONUS: float = 0.01  # +1% better prices per bonus point
    ACCESSORY_CRIT_PER_BONUS: float = 0.012  # +1.2% crit chance per bonus point
    ACCESSORY_LIFESTEAL_PER_BONUS: float = 0.01  # +1% of damage healed per bonus point
    ACCESSORY_COINFIND_PER_BONUS: float = 0.06  # +6% coins from loot per bonus point
    ACCESSORY_XP_PER_BONUS: float = 0.04  # +4% xp from all actions per bonus point

    # Shops buy loot below its worth; bartering raises the fraction toward SELL_CEILING.
    SELL_BASE: float = 0.6
    # Prices can move at most this far from their base value.
    BUY_FLOOR: float = 0.5
    SELL_CEILING: float = 1.4

    # XP granted per action.
    XP_PER_HIT: float = 4.0
    XP_PER_DAMAGE_TAKEN: float = 2.0
    XP_PER_KILL: float = 8.0
    XP_PER_RUN_FRAME: float = 0.015
    XP_PER_TALK: float = 6.0  # persuasion
    XP_PER_TALK_BARTERING: float = 1.5  # small bartering trickle from talking
    XP_PER_TRADE: float = 8.0  # bartering, per shop buy/sell


# Display name per Stats.NAMES key, shared by the stats menu and the level-up popup.
STAT_LABELS: dict[str, str] = {
    "strength": "Strength",
    "resistance": "Resistance",
    "speed": "Speed",
    "vitality": "Vitality",
    "bartering": "Bartering",
    "persuasion": "Persuasion",
}


@dataclass(frozen=True)
class Affinity:
    # Per-NPC relationship level. Starts neutral, moves from concrete player
    # actions toward that NPC rather than an LLM judgment of conversation tone.
    START: float = 50.0
    MIN: float = 0.0
    MAX: float = 100.0

    # Affinity gained from completing this NPC's quest, and from each trade at
    # a merchant's shop.
    QUEST_COMPLETE_BONUS: float = 15.0
    TRADE_BONUS: float = 1.0

    # Quest reward weight shifted from "rare" to "legendary" per point of affinity
    # above START, capped like persuasion's shift.
    WEIGHT_SHIFT_PER_POINT: float = 0.9
    MAX_WEIGHT_SHIFT: float = 45.0

    # Shop buy/sell price swing between MIN and MAX affinity, on top of bartering.
    MAX_PRICE_SWING: float = 0.15


@dataclass(frozen=True)
class Colors:
    BLACK: tuple = (0, 0, 0)
    GREEN: tuple = (41, 179, 41)
    RED: tuple = (201, 30, 22)
    WHITE: tuple = (255, 255, 255)
    YELLOW: tuple = (255, 255, 0)
    CYAN: tuple = (0, 255, 255)

    # Boss health bar: deep crimson, turning to a hotter orange-red once the boss enrages.
    BOSS_BAR: tuple = (150, 30, 40)
    BOSS_BAR_ENRAGED: tuple = (235, 80, 30)

    PLAYER: tuple = (255, 200, 160)
    MERCHANT: tuple = (220, 170, 50)
    MENU_BACKGROUND: tuple = (50, 50, 50)
    BUTTON: tuple = (70, 70, 70)
    BORDER: tuple = (100, 100, 100)
    BUTTON_HOVERED: tuple = (90, 90, 90)
    TRANSPARENT: tuple = (0, 0, 0, 150)

    # Dark menu theme, flat and square throughout; a gold accent marks hover/focus
    # and every menu, the HUD and dialogue share the same palette as one system.
    HEADER_BG: tuple = (32, 32, 40)
    ACCENT: tuple = (235, 190, 75)
    MUTED: tuple = (150, 150, 162)
    SLOT_BG: tuple = (30, 30, 37)
    SLOT_BG_HOVER: tuple = (52, 52, 63)
    SLOT_BORDER: tuple = (82, 82, 96)
    OVERLAY_DIM: tuple = (0, 0, 0, 170)


@dataclass(frozen=True)
class Hyperparameters:
    GPU_LAYERS: int = -1
    CONTEXT_SIZE: int = 8192
    MAX_TOKENS: int = 200
    # NPC replies are asked to be one short sentence; capping them keeps a rambling
    # answer from outgrowing the dialogue box and from stalling the queue for everyone.
    DIALOGUE_MAX_TOKENS: int = 120
    TEMPERATURE: float = 0.8
    REPETITION_PENALTY: float = 1.2


@dataclass(frozen=True)
class Fonts:
    big_title: pygame.font.Font
    title: pygame.font.Font
    heading: pygame.font.Font
    text: pygame.font.Font
    small: pygame.font.Font
    medium: pygame.font.Font
    button: pygame.font.Font
    badge: pygame.font.Font
    badge_small: pygame.font.Font

    @staticmethod
    def load() -> "Fonts":
        return Fonts(
            big_title=pygame.font.SysFont("dejavusans", 64, bold=True),
            title=pygame.font.SysFont("dejavusans", 32, bold=True),
            heading=pygame.font.SysFont("dejavusans", 22, bold=True),
            text=pygame.font.SysFont("dejavusans", 20),
            small=pygame.font.SysFont("dejavusans", 16),
            medium=pygame.font.SysFont("dejavusans", 22),
            button=pygame.font.SysFont("dejavusans", 20, bold=True),
            # NPC head markers (quest "!", thief "?", merchant "$"): the default pygame
            # font, not dejavusans, kept as-is from before these were cached.
            badge=pygame.font.Font(None, 45),
            badge_small=pygame.font.Font(None, 40),
        )
