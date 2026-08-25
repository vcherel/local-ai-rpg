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
class Minimap:
    """The top right map (ui/minimap.py). Small, fixed zoom, no live entities: it says
    where you have been, never what is around you."""

    SIZE: int = 180
    MARGIN: int = 10
    PADDING: int = 6
    # World span across the whole map. Roughly one and a half screens, so it orients
    # without scouting ahead.
    RANGE: int = 2600
    # World units to a pace, for the "paces from home" strip: the raw distance runs to five
    # figures and reads as noise, where a pace is a number a person can hold in their head.
    PACE: int = 32

    UNSEEN_COLOR: tuple = (18, 17, 22)
    GROUND_COLOR: tuple = (58, 74, 48)
    PLAZA_COLOR: tuple = (120, 98, 70)
    PLAYER_COLOR: tuple = (245, 245, 245)
    POI_COLORS = {
        "ruins": (150, 148, 140),
        "camp": (215, 140, 60),
        "shrine": (200, 195, 145),
        "farmstead": (176, 148, 92),
        "graveyard": (130, 140, 150),
        "watchtower": (170, 160, 145),
        "stones": (160, 150, 185),
        "signpost": (196, 168, 110),
        "cave": (70, 66, 62),
    }

    # A rumour is the one thing on the map the player has not walked to: it is drawn
    # wherever it lies, clamped to the panel edge when it is further out than RANGE, and
    # rubbed out once the player gets close enough to see the place for themselves.
    RUMOR_COLOR: tuple = (236, 196, 92)
    RUMOR_CLEAR_DISTANCE: int = 700

    # The day/night dial under the map, drawn whether or not the map itself is shown.
    CLOCK_HEIGHT: int = 46
    CLOCK_DAY_COLOR: tuple = (238, 206, 120)
    CLOCK_NIGHT_COLOR: tuple = (150, 170, 220)


@dataclass(frozen=True)
class Colors:
    BLACK: tuple = (0, 0, 0)
    GREEN: tuple = (41, 179, 41)
    RED: tuple = (201, 30, 22)
    WHITE: tuple = (255, 255, 255)
    YELLOW: tuple = (255, 255, 0)
    # A warning rather than a fight: the badge and the toast a villager gives the player
    # before their village actually turns on them.
    ORANGE: tuple = (238, 140, 40)
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


@dataclass(frozen=True)
class Music:
    """What the score is watching for (core/music.py, resolved in `Game._music_context`)."""

    # How close something hostile has to be before the music calls it a fight, and how long
    # it goes on calling it one after the last of them is out of range.
    COMBAT_RANGE: float = 620.0
    COMBAT_HOLD_MS: int = 6000
    # A boss is heard from further off than a wolf is: the pad is the warning.
    BOSS_RANGE: float = 900.0
