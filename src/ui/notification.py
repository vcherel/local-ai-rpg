import pygame

import core.constants as c
from ui import widgets


class _TimedBanner:
    """Shared slide-in/hold/slide-out animation and auto-expiry for a screen banner."""

    def __init__(self, screen: pygame.Surface, duration_ms: int, slide_duration_ms: int = 300, target_x: int = 20):
        self.screen: pygame.Surface = screen
        self.active = False
        self.start_time = 0
        self.duration = duration_ms
        self.slide_duration = slide_duration_ms
        self.target_x = target_x

    def _activate(self):
        self.active = True
        self.start_time = pygame.time.get_ticks()

    def _expired(self) -> bool:
        if not self.active:
            return True
        if pygame.time.get_ticks() - self.start_time > self.duration:
            self.active = False
            return True
        return False

    def _current_x(self, start_x: float) -> float:
        elapsed = pygame.time.get_ticks() - self.start_time

        if elapsed < self.slide_duration:
            progress = elapsed / self.slide_duration
            return start_x + (self.target_x - start_x) * progress
        elif elapsed > self.duration - self.slide_duration:
            progress = (elapsed - (self.duration - self.slide_duration)) / self.slide_duration
            return self.target_x + (start_x - self.target_x) * progress
        else:
            return self.target_x


class ToastNotification(_TimedBanner):
    """Sliding banner for one-off events like opening a lootbox or hearing a rumour.

    Wraps onto a few lines rather than running off the screen: a rumour or a landmark's
    explanation is a full sentence, and it is the only place that text is ever shown.
    """

    MAX_WIDTH_FRAC = 0.45
    LINE_SPACING = 26

    def __init__(self, screen: pygame.Surface):
        super().__init__(screen, duration_ms=4000)
        self.lines = []
        self.color = c.Colors.YELLOW

        self.padding = 15

    def show(self, text: str, color: tuple = None):
        self.lines = widgets.wrap_text(text, c.Fonts.button, c.Screen.WIDTH * self.MAX_WIDTH_FRAC)
        self.color = color or c.Colors.YELLOW
        self._activate()

    def draw(self):
        if self._expired() or not self.lines:
            return

        rendered = [c.Fonts.button.render(line, True, self.color) for line in self.lines]
        width = max(line.get_width() for line in rendered) + 2 * self.padding
        height = max(60, len(rendered) * self.LINE_SPACING + 2 * self.padding)

        x = self._current_x(-width)
        y = 280

        surface = pygame.Surface((width, height))
        surface.fill(c.Colors.BUTTON)
        pygame.draw.rect(surface, c.Colors.BORDER, (0, 0, width, height), 3)
        top = (height - len(rendered) * self.LINE_SPACING) // 2
        for i, line in enumerate(rendered):
            surface.blit(line, (self.padding, top + i * self.LINE_SPACING))

        self.screen.blit(surface, (int(x), y))
