import pygame

import core.constants as c
from game.quest import Quest


class QuestNotification:
    def __init__(self, screen: pygame.Surface):
        self.screen: pygame.Surface = screen
        self.active = False
        self.quest = None

        self.width = 1000
        self.height = 150
        self.padding = 15

        self.target_x = 20
        self.start_x = -self.width

        self.start_time = 0
        self.duration = 8000  # 8 seconds
        self.slide_duration = 300  # ms

    def show(self, quest: Quest):
        self.quest = quest
        self.active = True
        self.start_time = pygame.time.get_ticks()

    def _get_current_x(self):
        elapsed = pygame.time.get_ticks() - self.start_time

        if elapsed < self.slide_duration:
            progress = elapsed / self.slide_duration
            return self.start_x + (self.target_x - self.start_x) * progress
        elif elapsed > self.duration - self.slide_duration:
            progress = (elapsed - (self.duration - self.slide_duration)) / self.slide_duration
            return self.target_x + (self.start_x - self.target_x) * progress
        else:
            return self.target_x

    def _wrap_text(self, text: str, max_width, font: pygame.font.Font):
        words = text.split(" ")
        lines = []
        current_line = []

        for word in words:
            current_line.append(word)
            line = " ".join(current_line)
            if font.size(line)[0] > max_width:
                if len(current_line) == 1:
                    lines.append(line)
                    current_line = []
                else:
                    current_line.pop()
                    lines.append(" ".join(current_line))
                    current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def draw(self):
        if not self.active or not self.quest:
            return

        if pygame.time.get_ticks() - self.start_time > self.duration:
            self.active = False
            return

        title_text = f"Nouvelle quête de {self.quest.npc_name}"
        title_width = c.Fonts.title.size(title_text)[0]

        npc_text = f"Objet: {self.quest.item_name}"
        npc_width = c.Fonts.button.size(npc_text)[0]

        max_desc_width = 0
        max_width = 2000  # Maximum width to prevent overly wide notifications
        desc_lines = self._wrap_text(self.quest.description, max_width - 2 * self.padding, c.Fonts.text)
        desc_line_height = 20

        for line in desc_lines[:2]:
            line_width = c.Fonts.text.size(line)[0]
            max_desc_width = max(max_desc_width, line_width)

        self.width = min(max(title_width, npc_width, max_desc_width) + 2 * self.padding, max_width)

        x = self._get_current_x()
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
