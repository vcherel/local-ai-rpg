import pygame

import core.constants as c
from ui import widgets

# Height of the title band drawn at the top of a menu when it has a title.
HEADER_HEIGHT = 56

# The keys the repeated one-click actions answer to, wherever their button is drawn. Kept
# here rather than in each menu so the inventory and the shop cannot drift apart on the
# same action, and so the label a button prints comes from the key it is bound to.
EQUIP_BEST_KEY = pygame.K_e
SELL_VALUABLES_KEY = pygame.K_s
SELL_GEAR_KEY = pygame.K_u

# The dim wash drawn behind every open menu, built on first use and reused; see draw_overlay.
_OVERLAY: pygame.Surface | None = None


class BaseMenu:
    # The key that opened this menu, which is also the key that shuts it again. One key, or
    # several when more than one thing leads here (a board is opened with E and named N).
    # Escape is never listed: it shuts every menu and `handle_close` already knows that.
    toggle_key: int | tuple[int, ...] | None = None

    def __init__(self, screen: pygame.Surface, width: int, height: int):
        self.screen = screen
        self.active = False
        self.width = width
        self.height = height
        self.padding = 20
        # Set to HEADER_HEIGHT by create_menu_surface when a title is drawn; menus that
        # hit-test against content geometry read content_top, so it must be right before
        # the first draw too. Header menus override this in their __init__.
        self.header_height = 0

    def toggle(self):
        self.active = not self.active

    def close(self):
        self.active = False

    def handle_close(self, event) -> bool:
        """Shut the menu if this event is the press that shuts it, and say whether it was.

        The toggle key is written once in `Game.key_actions` and once here, and a menu that
        spelled its own key tuple out inside `handle_event` was a third copy that could be
        rebound in one place and not the other."""
        if event.type != pygame.KEYDOWN:
            return False
        keys = self.toggle_key if isinstance(self.toggle_key, tuple) else (self.toggle_key,)
        if event.key != pygame.K_ESCAPE and event.key not in keys:
            return False
        self.close()
        return True

    def get_centered_position(self) -> tuple[int, int]:
        menu_x = (c.Screen.WIDTH - self.width) // 2
        menu_y = (c.Screen.HEIGHT - self.height) // 2
        return menu_x, menu_y

    def panel_rect(self) -> pygame.Rect:
        """Where this menu's panel actually sits on screen. What anything drawn over the top
        of an open menu (the quest arrow) has to keep off."""
        return pygame.Rect(*self.get_centered_position(), self.width, self.height)

    def draw_overlay(self):
        """Dim the world behind the menu every frame.

        The wash is built once and kept: it never changes, and a fresh screen-sized alpha
        surface per frame is an allocation the size of the window for a flat colour.
        """
        global _OVERLAY
        if _OVERLAY is None:
            _OVERLAY = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
            _OVERLAY.fill(c.Colors.OVERLAY_DIM)
        self.screen.blit(_OVERLAY, (0, 0))

    def create_menu_surface(self, title: str | None = None) -> pygame.Surface:
        surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        widgets.draw_panel(surface, surface.get_rect())
        if title:
            self._draw_header(surface, title)
        else:
            self.header_height = 0
        return surface

    def _draw_header(self, surface: pygame.Surface, title: str):
        self.header_height = HEADER_HEIGHT

        # Darker band across the top of the panel, with a gold underline.
        band = pygame.Surface((self.width, HEADER_HEIGHT), pygame.SRCALPHA)
        band.fill((*c.Colors.HEADER_BG, 190))
        surface.blit(band, (0, 0))

        pygame.draw.line(
            surface,
            c.Colors.ACCENT,
            (self.padding, HEADER_HEIGHT - 1),
            (self.width - self.padding, HEADER_HEIGHT - 1),
            2,
        )

        label = c.Fonts.title.render(title, True, c.Colors.WHITE)
        surface.blit(label, (self.padding, (HEADER_HEIGHT - label.get_height()) // 2))

    @property
    def content_top(self) -> int:
        """First y inside the panel below the header band."""
        return self.header_height + 18

    def draw_hint(self, surface: pygame.Surface, text: str):
        hint = c.Fonts.small.render(text, True, c.Colors.MUTED)
        surface.blit(hint, ((self.width - hint.get_width()) // 2, self.height - self.padding - hint.get_height()))

    def blit_panel(self, surface: pygame.Surface):
        menu_x, menu_y = self.get_centered_position()
        self.screen.blit(surface, (menu_x, menu_y))

    def draw_wrapped_text(
        self, surface: pygame.Surface, text: str, x: int, y: int, max_width: int, font=None, line_spacing: int = 25
    ):
        """Returns the y the text ended at, so whatever follows it doesn't have to guess."""
        if font is None:
            font = c.Fonts.text

        lines = widgets.wrap_text(text, font, max_width)

        for i, line in enumerate(lines):
            line_surface = font.render(line, True, c.Colors.WHITE)
            surface.blit(line_surface, (x, y + i * line_spacing))

        return y + len(lines) * line_spacing
