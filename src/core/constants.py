from dataclasses import dataclass

@dataclass(frozen=True)
class Screen:
    WIDTH: int = 1800
    HEIGHT: int = 900
    DELTA_Y: int = 0  # Distance between center and player
    ORIGIN_X: int = WIDTH // 2
    ORIGIN_Y: int = HEIGHT // 2 + DELTA_Y

@dataclass(frozen=True)
class Size:
    PLAYER: int = 30  # TODO change constants class
    NPC: int = 30
    MONSTER: int = 25
    ITEM: int = 25

@dataclass(frozen=True)
class Player:
    PLAYER_SPEED: int = 5
    PLAYER_RUN_SPEED: int = 8
    PLAYER_TURN_SPEED: float = 0.03

    INTERACTION_DISTANCE: int = 30  # TODO: Make interaction in front of player
    ATTACK_REACH: int = 20
    ATTACK_DAMAGE: int = 5

@dataclass(frozen=True)
class World:
    WORLD_SIZE: int = 5000
    NB_NPCS: int = 20 * (WORLD_SIZE // 1000)
    NB_MONSTERS: int = 10 * (WORLD_SIZE // 1000)
    NB_DETAILS: int = 500 * (WORLD_SIZE // 1000)

@dataclass(frozen=True)
class Combat:
    PLAYER_HP: int = 100
    NPC_HP: int = 50
    MONSTER_HP: int = 20

@dataclass(frozen=True)
class Colors:
    BLACK: tuple = (0, 0, 0)
    GREEN: tuple = (34, 139, 34)
    RED: tuple = (201, 30, 22)
    WHITE: tuple = (255, 255, 255)
    YELLOW: tuple = (255, 255, 0)
    CYAN: tuple = (0, 255, 255)

    PLAYER: tuple = (255, 200, 160)
    ECHAP_TEXT: tuple = (200, 200, 200)
    MENU_BACKGROUND: tuple = (50, 50, 50)
    BUTTON: tuple = (70, 70, 70)
    BORDER: tuple = (100, 100, 100)
    BUTTON_HOVERED: tuple = (90, 90, 90) 
    BORDER_HOVERED: tuple = (255, 215, 0)

@dataclass(frozen=True)
class Hyperparameters:
    GPU_LAYERS: int = -1
    CONTEXT_SIZE: int = 4096
    MAX_TOKENS: int = 200
    TEMPERATURE: float = 0.8
    REPETITION_PENALTY: float = 1.2