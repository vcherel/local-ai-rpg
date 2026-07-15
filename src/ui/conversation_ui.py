from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets

if TYPE_CHECKING:
    from core.utils import ConversationHistory


class ConversationUI:
    def __init__(self, screen):
        self.screen: pygame.Surface = screen

        self.scroll_offset = 0
        self.max_visible_height = 170
        self.line_height = 26

        self.user_input = ""

    def handle_text_input(self, event) -> str:
        if event.key == pygame.K_RETURN and self.user_input.strip():
            message = self.user_input
            self.user_input = ""
            return message
        elif event.key == pygame.K_BACKSPACE:
            self.user_input = self.user_input[:-1]
        elif event.unicode and len(self.user_input) < 150:
            self.user_input += event.unicode
        return None

    def handle_key_scroll(self, direction: int, history: ConversationHistory, npc_name: str):
        scroll_amount = -self.line_height * direction
        total_height = self._calculate_total_height(history.messages, npc_name)
        max_scroll = max(0, total_height - self.max_visible_height)
        self.scroll_offset = max(0, min(self.scroll_offset + scroll_amount, max_scroll))

    def auto_scroll(self, history: ConversationHistory, npc_name: str):
        total_height = self._calculate_total_height(history.messages, npc_name)
        if total_height > self.max_visible_height:
            self.scroll_offset = total_height - self.max_visible_height
        else:
            self.scroll_offset = 0

    def reset(self):
        self.user_input = ""
        self.scroll_offset = 0

    def _calculate_total_height(self, messages: list, npc_name: str) -> int:
        total_height = 0
        for msg in messages:
            prefix = "You: " if msg["role"] == "user" else f"{npc_name}: "
            lines = widgets.wrap_text(prefix + msg["content"], c.Fonts.medium, c.Screen.WIDTH - 60)
            total_height += len(lines) * self.line_height
        return total_height

    def draw(self, npc_name: str, history: ConversationHistory, ended: bool = False):
        box_height = 300
        box_y = c.Screen.HEIGHT - box_height - 25

        pygame.draw.rect(self.screen, c.Colors.MENU_BACKGROUND, (10, box_y, c.Screen.WIDTH - 20, box_height))
        pygame.draw.rect(self.screen, c.Colors.WHITE, (10, box_y, c.Screen.WIDTH - 20, box_height), 2)

        name_surface = c.Fonts.title.render(npc_name, True, c.Colors.YELLOW)
        self.screen.blit(name_surface, (25, box_y + 10))

        self._draw_messages(self.screen, box_y, npc_name, history.messages)

        if ended:
            self._draw_ended_notice(self.screen, box_y, box_height)
        else:
            self._draw_input_box(self.screen, box_y, box_height)

    def _draw_messages(self, screen: pygame.Surface, box_y: int, npc_name: str, messages: list):
        message_area_y = box_y + 55
        clip_rect = pygame.Rect(20, message_area_y, c.Screen.WIDTH - 40, self.max_visible_height)
        screen.set_clip(clip_rect)

        y_offset = message_area_y - self.scroll_offset
        total_height = self._calculate_total_height(messages, npc_name)

        for msg in messages:
            if msg["role"] == "user":
                prefix = "You: "
                color = c.Colors.CYAN
            else:
                prefix = f"{npc_name}: "
                color = c.Colors.WHITE

            lines = widgets.wrap_text(prefix + msg["content"], c.Fonts.medium, c.Screen.WIDTH - 60)
            for line in lines:
                text_surface = c.Fonts.medium.render(line, True, color)
                screen.blit(text_surface, (25, y_offset))
                y_offset += self.line_height

        screen.set_clip(None)

        if total_height > self.max_visible_height and self.scroll_offset < total_height - self.max_visible_height:
            scroll_text = "↑ Scroll to see more"
            scroll_surface = c.Fonts.text.render(scroll_text, True, c.Colors.YELLOW)
            screen.blit(scroll_surface, (c.Screen.WIDTH - 250, message_area_y - 35))

    def _draw_input_box(self, screen: pygame.Surface, box_y: int, box_height: int):
        input_y = box_y + box_height - 60
        pygame.draw.rect(screen, c.Colors.BLACK, (20, input_y, c.Screen.WIDTH - 40, 35))
        pygame.draw.rect(screen, c.Colors.WHITE, (20, input_y, c.Screen.WIDTH - 40, 35), 2)

        input_text = self.user_input + "|"
        input_surface = c.Fonts.medium.render(input_text, True, c.Colors.WHITE)
        screen.blit(input_surface, (30, input_y + 1))  # + is to fix y position of input text

    def _draw_ended_notice(self, screen: pygame.Surface, box_y: int, box_height: int):
        notice_y = box_y + box_height - 60
        notice = c.Fonts.medium.render("The conversation is over. Press Escape to leave.", True, c.Colors.BORDER)
        screen.blit(notice, (30, notice_y + 1))
