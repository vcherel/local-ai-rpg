from dataclasses import dataclass

@dataclass(frozen=True)
class Screen:
    WIDTH: int = 1800
    HEIGHT: int = 900
    ORIGIN_X: int = WIDTH // 2
    ORIGIN_Y: int = HEIGHT // 2

@dataclass(frozen=True)
class Size:
    PLAYER: int = 30
    NPC: int = 30
    ITEM: int = 25

@dataclass(frozen=True)
class Game:
    PLAYER_SPEED: int = 5
    PLAYER_TURN_SPEED: float = 0.04  # Radians per frame
    INTERACTION_DISTANCE: int = 50
    NB_NPCS: int = 20

@dataclass(frozen=True)
class Colors:
    BLACK: tuple = (0, 0, 0)
    GREEN: tuple = (34, 139, 34)
    WHITE: tuple = (255, 255, 255)
    YELLOW: tuple = (255, 255, 0)
    GRAY: tuple = (100, 100, 100)
    DARK_GRAY: tuple = (50, 50, 50)
    CYAN: tuple = (0, 255, 255)
    RED: tuple = (255, 0, 0)

@dataclass(frozen=True)
class Hyperparameters:
    GPU_LAYERS: int = -1
    CONTEXT_SIZE: int = 4096
    MAX_TOKENS: int = 200
    TEMPERATURE: float = 0.8
    REPETITION_PENALTY: float = 1.2