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
    REGEN_RATE: float = 0.001
    SIZE: int = 30

    SPEED: int = 5
    RUN_SPEED: int = 7

    INTERACTION_DISTANCE: int = 30
    ATTACK_REACH: int = 17
    ATTACK_DAMAGE: int = 5


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
    # Camera never shakes more than this, so heavy hits stay readable rather than nauseating.
    MAX_SHAKE: float = 30.0
    SHAKE_DECAY: float = 0.82  # per-60fps-frame multiplier


@dataclass(frozen=True)
class WeaponArchetype:
    """Feel profile for a weapon family, resolved from the weapon name's keyword.

    Multipliers apply to the base melee values (`Player.ATTACK_REACH/ATTACK_DAMAGE`,
    `Entities.SWING_SPEED`). `shake` and `knockback` are in world pixels.
    """

    name: str
    reach_mult: float
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


UNARMED = WeaponArchetype("unarmed", 1.0, 1.0, 1.0, 350, 8, 0.08, False, 1.0, 2.0, False, False)

WEAPON_ARCHETYPES: dict[str, WeaponArchetype] = {
    "dagger": WeaponArchetype("dagger", 0.8, 1.8, 0.7, 180, 4, 0.30, False, 1.0, 2.0, False, False),
    "sword": WeaponArchetype("sword", 1.0, 1.0, 1.0, 350, 10, 0.12, True, 1.4, 4.0, False, False),
    "axe": WeaponArchetype("axe", 1.05, 0.7, 1.25, 520, 14, 0.10, True, 1.8, 7.0, False, False),
    "hammer": WeaponArchetype("hammer", 0.9, 0.55, 1.6, 620, 26, 0.05, False, 1.0, 14.0, False, False),
    "spear": WeaponArchetype("spear", 1.8, 0.9, 0.95, 380, 8, 0.12, False, 1.0, 4.0, False, False),
    "staff": WeaponArchetype("staff", 1.0, 1.0, 1.0, 420, 6, 0.10, False, 1.0, 2.0, True, False),
    "bow": WeaponArchetype("bow", 1.0, 1.0, 1.0, 400, 4, 0.10, False, 1.0, 1.0, True, True),
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


# Ordered weakest to strongest. Kept close to the old single Monster stats near the village,
# scaling up with distance from the world center so wandering further gets more dangerous.
MONSTER_KINDS: tuple[MonsterKind, ...] = (
    MonsterKind("Slime", (90, 190, 90), 22, 10, 3, 8, 3, min_distance=0, weight=10),
    MonsterKind("Wolf", (140, 140, 140), 26, 20, 5, 10, 6, min_distance=1200, weight=6),
    MonsterKind("Bandit", (150, 40, 40), 28, 35, 4, 12, 9, min_distance=2500, weight=4),
    MonsterKind("Troll", (60, 90, 55), 34, 60, 3, 14, 14, min_distance=4000, weight=2),
)

MONSTER_MAX_SIZE: int = max(kind.size for kind in MONSTER_KINDS)


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
    NPC_HP: int = 30
    # NPCs wander around their spawn point: walk to a random spot within
    # NPC_WANDER_RADIUS, then idle for a random duration before moving again.
    NPC_WANDER_SPEED: float = 1.5
    NPC_WANDER_RADIUS: int = 250
    NPC_IDLE_MIN_MS: int = 2000
    NPC_IDLE_MAX_MS: int = 7000
    # NPCs stop wandering and face the player when he gets this close.
    NPC_WANDER_PAUSE_DISTANCE: int = 120
    SWING_SPEED: float = 0.007
    # How long an entity flashes white after being hit (ms).
    FLASH_MS: int = 150


@dataclass(frozen=True)
class World:
    WORLD_SIZE: int = 5000
    DETECTION_RANGE = 500

    NB_NPCS: int = 20
    NB_MONSTERS: int = 100

    # Slain monsters are replenished over time so the world never empties out.
    RESPAWN_INTERVAL_MS: int = 3000
    # New monsters spawn at least this far from the player so they never pop into view...
    SPAWN_MIN_DISTANCE: int = 900
    # ...and at most this far, so they still show up as the player explores.
    SPAWN_MAX_DISTANCE: int = 1500
    # Monsters left this far behind despawn, freeing their slot to respawn near the player.
    DESPAWN_DISTANCE: int = 3000
    # Monsters placed at world creation start at least this far from the player spawn point.
    INITIAL_SPAWN_MIN_DISTANCE: int = 1200

    # Floor details stream in per chunk as the player explores, so the world has no edge.
    CHUNK_SIZE: int = 1000
    DETAILS_PER_CHUNK: int = 200
    # Chunks within this many chunks of the player are generated...
    CHUNK_LOAD_RADIUS: int = 2
    # ...and stay loaded until this much farther away, to avoid load/unload thrashing at the edge.
    CHUNK_KEEP_RADIUS: int = 3


@dataclass(frozen=True)
class Events:
    # A random world event is rolled on this cadence; each roll picks one enabled kind.
    INTERVAL_RANGE_MS: tuple = (60_000, 120_000)

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
class Buildings:
    NB_HOUSES: int = 8
    NB_SHOPS: int = 3
    NB_TAVERNS: int = 2

    # (width range, height range) per kind. The landmark ruin has no door and no interior.
    SIZES = {
        "house": ((170, 230), (140, 200)),
        "shop": ((190, 230), (150, 180)),
        "tavern": ((260, 310), (200, 240)),
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

    # Interior room dimensions; each interior is its own small coordinate space.
    ROOM_W: int = 1100
    ROOM_H: int = 700
    ROOM_WALL: int = 25

    TAVERN_SLEEP_COST: int = 15
    INTERACT_DISTANCE: int = 120

    # Smashing a shop crate always yields a few coins and sometimes a common item.
    CRATE_COIN_MIN: int = 2
    CRATE_COIN_MAX: int = 12
    CRATE_ITEM_CHANCE: float = 0.2

    WALL_COLOR: tuple = (72, 56, 44)
    FLOOR_COLOR: tuple = (152, 112, 72)
    STONE_COLOR: tuple = (138, 136, 128)


@dataclass(frozen=True)
class LootBox:
    # Chance a slain monster drops a lootbox.
    DROP_CHANCE: float = 0.2
    COIN_MIN: int = 5
    COIN_MAX: int = 25
    # Chance the box also contains a weapon or armor piece, on top of coins.
    ITEM_CHANCE: float = 0.35


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
        RarityTier("legendary", (255, 150, 40), 2, (11, 14), (6, 7), (11, 14), 6.0),
    )
    # Quest rewards skip the low tiers so completing a quest always feels worth it.
    QUEST_REWARD_WEIGHTS: tuple = (0, 0, 60, 30, 10)


@dataclass(frozen=True)
class Stats:
    # Character progression is use-based: every stat starts at level 1 and gains XP
    # from a matching action. Effects are pure functions of the level, so growing a
    # stat never touches the save format.
    NAMES: tuple = ("strength", "resistance", "speed", "vitality", "bartering", "persuasion")

    # XP needed for level 1 -> 2, scaled by XP_GROWTH for each further level.
    BASE_XP: float = 35.0
    XP_GROWTH: float = 1.45

    # Effect increment per level above 1.
    STRENGTH_PER_LEVEL: int = 2  # flat attack damage
    RESISTANCE_PER_LEVEL: int = 1  # flat damage reduction
    SPEED_PER_LEVEL: float = 0.04  # +4% move speed
    VITALITY_HP_PER_LEVEL: int = 15  # extra max HP
    VITALITY_REGEN_PER_LEVEL: float = 0.0005
    BARTER_PER_LEVEL: float = 0.03  # 3% better prices per level

    # Quest reward weight shifted from "rare" to "legendary" per level above 1, capped
    # so "rare" never drops below a quarter of its base weight.
    PERSUASION_WEIGHT_SHIFT_PER_LEVEL: float = 2.0
    PERSUASION_MAX_WEIGHT_SHIFT: float = 45.0

    # Effect per point of an equipped accessory's bonus, on top of trained stats.
    ACCESSORY_SPEED_PER_BONUS: float = 0.01  # +1% move speed per bonus point
    ACCESSORY_REGEN_PER_BONUS: float = 0.0005  # extra HP regen per bonus point
    ACCESSORY_LUCK_PER_BONUS: float = 0.01  # +1% better prices per bonus point

    # Prices can move at most this far from their base value.
    BUY_FLOOR: float = 0.5
    SELL_CEILING: float = 2.0

    # XP granted per action.
    XP_PER_HIT: float = 4.0
    XP_PER_DAMAGE_TAKEN: float = 2.0
    XP_PER_KILL: float = 8.0
    XP_PER_RUN_FRAME: float = 0.015
    XP_PER_TALK: float = 6.0  # persuasion
    XP_PER_TALK_BARTERING: float = 1.5  # small bartering trickle from talking
    XP_PER_TRADE: float = 8.0  # bartering, per shop buy/sell


@dataclass(frozen=True)
class Affinity:
    # Per-NPC relationship level. Starts neutral; an LLM judges how each closed
    # conversation should move it, independent of the global player Stats.
    START: float = 50.0
    MIN: float = 0.0
    MAX: float = 100.0

    # Bounds how much a single conversation's LLM judgment can move affinity.
    MAX_DELTA_PER_CONVERSATION: int = 10

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

    @staticmethod
    def load() -> "Fonts":
        return Fonts(
            big_title=pygame.font.SysFont("arial", 64, bold=True),
            title=pygame.font.SysFont("arial", 32, bold=True),
            heading=pygame.font.SysFont("arial", 22, bold=True),
            text=pygame.font.SysFont("arial", 20),
            small=pygame.font.SysFont("arial", 16),
            medium=pygame.font.SysFont("arial", 22),
            button=pygame.font.SysFont("arial", 20, bold=True),
        )
