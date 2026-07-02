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
class Monster:
    SIZE: int = 25
    HP: int = 15
    SPEED: int = 4
    ATTACK_RANGE: int = 10
    DAMAGE: int = 5


@dataclass(frozen=True)
class Entities:
    NPC_SIZE: int = 30
    ITEM_SIZE: int = 25
    NPC_HP: int = 30
    SWING_SPEED: float = 0.007
    # How long an entity flashes white after being hit (ms).
    FLASH_MS: int = 150


@dataclass(frozen=True)
class World:
    WORLD_SIZE: int = 5000
    DETECTION_RANGE = 500

    NB_NPCS: int = 20
    NB_MONSTERS: int = 100
    MERCHANT_PROBABILITY: float = 0.15
    NB_DETAILS: int = 5000

    # Slain monsters are replenished over time so the world never empties out.
    RESPAWN_INTERVAL_MS: int = 3000
    # New monsters spawn at least this far from the player so they never pop into view.
    SPAWN_MIN_DISTANCE: int = 900
    # Monsters placed at world creation start at least this far from the player spawn point.
    INITIAL_SPAWN_MIN_DISTANCE: int = 1200


@dataclass(frozen=True)
class LootBox:
    # Chance a slain monster drops a lootbox.
    DROP_CHANCE: float = 0.2
    COIN_MIN: int = 5
    COIN_MAX: int = 25
    # Chance the box also contains a weapon or armor piece, on top of coins.
    ITEM_CHANCE: float = 0.35
    WEAPON_BONUS_RANGE: tuple = (1, 5)
    ARMOR_BONUS_RANGE: tuple = (1, 3)


@dataclass(frozen=True)
class Stats:
    # Character progression is use-based: every stat starts at level 1 and gains XP
    # from a matching action. Effects are pure functions of the level, so growing a
    # stat never touches the save format.
    NAMES: tuple = ("strength", "resistance", "speed", "vitality", "bartering")

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

    # Prices can move at most this far from their base value.
    BUY_FLOOR: float = 0.5
    SELL_CEILING: float = 2.0

    # XP granted per action.
    XP_PER_HIT: float = 4.0
    XP_PER_DAMAGE_TAKEN: float = 2.0
    XP_PER_KILL: float = 8.0
    XP_PER_RUN_FRAME: float = 0.015
    XP_PER_TALK: float = 6.0


@dataclass(frozen=True)
class Colors:
    BLACK: tuple = (0, 0, 0)
    GREEN: tuple = (41, 179, 41)
    RED: tuple = (201, 30, 22)
    WHITE: tuple = (255, 255, 255)
    YELLOW: tuple = (255, 255, 0)
    CYAN: tuple = (0, 255, 255)

    PLAYER: tuple = (255, 200, 160)
    MERCHANT: tuple = (220, 170, 50)
    MENU_BACKGROUND: tuple = (50, 50, 50)
    BUTTON: tuple = (70, 70, 70)
    BORDER: tuple = (100, 100, 100)
    BUTTON_HOVERED: tuple = (90, 90, 90)
    BORDER_HOVERED: tuple = (255, 215, 0)
    TRANSPARENT: tuple = (0, 0, 0, 150)


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
