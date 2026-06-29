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
    NB_DETAILS: int = 5000

    # Slain monsters are replenished over time so the world never empties out.
    RESPAWN_INTERVAL_MS: int = 3000
    # New monsters spawn at least this far from the player so they never pop into view.
    SPAWN_MIN_DISTANCE: int = 900


@dataclass(frozen=True)
class Colors:
    BLACK: tuple = (0, 0, 0)
    GREEN: tuple = (41, 179, 41)
    RED: tuple = (201, 30, 22)
    WHITE: tuple = (255, 255, 255)
    YELLOW: tuple = (255, 255, 0)
    CYAN: tuple = (0, 255, 255)

    PLAYER: tuple = (255, 200, 160)
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
