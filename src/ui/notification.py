import pygame

import core.constants as c
from game.quest import Quest
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


class QuestNotification(_TimedBanner):
    def __init__(self, screen: pygame.Surface):
        super().__init__(screen, duration_ms=8000)
        self.quest = None

        self.width = 1000
        self.height = 150
        self.padding = 15
        self.start_x = -self.width

    def show(self, quest: Quest):
        self.quest = quest
        self._activate()

    def draw(self):
        if self._expired() or not self.quest:
            return

        title_text = f"New quest from {self.quest.npc_name}"
        title_width = c.Fonts.title.size(title_text)[0]

        if self.quest.quest_type == "kill_mob":
            npc_text = f"Kill: {self.quest.kill_count} {self.quest.target_monster_kind}(s)"
        else:
            npc_text = f"Item: {self.quest.item_name}"
        npc_width = c.Fonts.button.size(npc_text)[0]

        max_desc_width = 0
        max_width = 2000  # Maximum width to prevent overly wide notifications
        desc_lines = widgets.wrap_text(self.quest.description, c.Fonts.text, max_width - 2 * self.padding)
        desc_line_height = 20

        for line in desc_lines[:2]:
            line_width = c.Fonts.text.size(line)[0]
            max_desc_width = max(max_desc_width, line_width)

        self.width = min(max(title_width, npc_width, max_desc_width) + 2 * self.padding, max_width)

        x = self._current_x(self.start_x)
        y = 120

        surface = pygame.Surface((self.width, self.height))
        surface.fill(c.Colors.BUTTON)
        pygame.draw.rect(surface, c.Colors.BORDER, (0, 0, self.width, self.height), 3)

        title = c.Fonts.title.render(title_text, True, c.Colors.YELLOW)
        surface.blit(title, (self.padding, self.padding))

        desc_y = self.padding + c.Fonts.title.size(title_text)[1] + 10
        for line in desc_lines[:2]:
            desc_surface = c.Fonts.text.render(line, True, c.Colors.WHITE)
            surface.blit(desc_surface, (self.padding, desc_y))
            desc_y += desc_line_height

        npc_y = desc_y + 20
        npc_surface = c.Fonts.button.render(npc_text, True, c.Colors.WHITE)
        surface.blit(npc_surface, (self.padding, npc_y))

        self.screen.blit(surface, (int(x), y))


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
