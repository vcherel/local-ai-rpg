import pygame

import core.constants as c
from ui import widgets

# Height of the title band drawn at the top of a menu when it has a title.
HEADER_HEIGHT = 56


class BaseMenu:
    def __init__(self, screen: pygame.Surface, width: int, height: int):
        self.screen = screen
        self.active = False
        self.just_active = False
        self.width = width
        self.height = height
        self.padding = 20
        # Set to HEADER_HEIGHT by create_menu_surface when a title is drawn; menus that
        # hit-test against content geometry read content_top, so it must be right before
        # the first draw too. Header menus override this in their __init__.
        self.header_height = 0

    def toggle(self):
        self.active = not self.active
        self.just_active = True

    def close(self):
        self.active = False

    def get_centered_position(self) -> tuple[int, int]:
        menu_x = (c.Screen.WIDTH - self.width) // 2
        menu_y = (c.Screen.HEIGHT - self.height) // 2
        return menu_x, menu_y

    def draw_overlay(self):
        """Dim the world behind the menu every frame, then cast the panel's shadow."""
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill(c.Colors.OVERLAY_DIM)
        self.screen.blit(overlay, (0, 0))

        if self.width > 0 and self.height > 0:
            menu_x, menu_y = self.get_centered_position()
            widgets.draw_shadow(self.screen, pygame.Rect(menu_x, menu_y, self.width, self.height))
        self.just_active = False

    def create_menu_surface(self, title: str = None) -> pygame.Surface:
        surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        widgets.draw_panel(surface, surface.get_rect())
        if title:
            self._draw_header(surface, title)
        else:
            self.header_height = 0
        return surface

    def _draw_header(self, surface: pygame.Surface, title: str):
        self.header_height = HEADER_HEIGHT

        # Darker band clipped to the panel's rounded top corners, with a gold underline.
        band = pygame.Surface((self.width, HEADER_HEIGHT), pygame.SRCALPHA)
        band.fill((*c.Colors.HEADER_BG, 190))
        mask = pygame.Surface((self.width, HEADER_HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), pygame.Rect(0, 0, self.width, HEADER_HEIGHT * 2), border_radius=14)
        band.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
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
        return (self.header_height or 0) + 18

    def draw_hint(self, surface: pygame.Surface, text: str):
        hint = c.Fonts.small.render(text, True, c.Colors.MUTED)
        surface.blit(hint, ((self.width - hint.get_width()) // 2, self.height - self.padding - hint.get_height()))

    def blit_panel(self, surface: pygame.Surface):
        menu_x, menu_y = self.get_centered_position()
        self.screen.blit(surface, (menu_x, menu_y))

    @staticmethod
    def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = text.split(" ")
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            test_surface = font.render(test_line, True, c.Colors.WHITE)

            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def draw_wrapped_text(
        self, surface: pygame.Surface, text: str, x: int, y: int, max_width: int, font=None, line_spacing: int = 25
    ):
        """
        Draw text with word wrapping at specified position.
        Returns the final y position after all lines.
        """
        if font is None:
            font = c.Fonts.text

        lines = self.wrap_text(text, font, max_width)

        for i, line in enumerate(lines):
            line_surface = font.render(line, True, c.Colors.WHITE)
            surface.blit(line_surface, (x, y + i * line_spacing))

        return y + len(lines) * line_spacing
