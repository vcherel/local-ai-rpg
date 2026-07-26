import pygame

import core.constants as c


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
    """Short, single-line sliding banner for one-off events like opening a lootbox."""

    def __init__(self, screen: pygame.Surface):
        super().__init__(screen, duration_ms=4000)
        self.text = ""
        self.color = c.Colors.YELLOW

        self.height = 60
        self.padding = 15

    def show(self, text: str, color: tuple = None):
        self.text = text
        self.color = color or c.Colors.YELLOW
        self._activate()

    def draw(self):
        if self._expired():
            return

        text_surface = c.Fonts.button.render(self.text, True, self.color)
        width = text_surface.get_width() + 2 * self.padding

        x = self._current_x(-width)
        y = 280

        surface = pygame.Surface((width, self.height))
        surface.fill(c.Colors.BUTTON)
        pygame.draw.rect(surface, c.Colors.BORDER, (0, 0, width, self.height), 3)
        surface.blit(text_surface, (self.padding, (self.height - text_surface.get_height()) // 2))

        self.screen.blit(surface, (int(x), y))
