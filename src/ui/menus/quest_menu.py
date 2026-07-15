from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

if TYPE_CHECKING:
    from llm.quest_system import QuestSystem


class QuestMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=720, height=560)
        self.header_height = HEADER_HEIGHT

        self.card_width = self.width - 2 * self.padding
        self.card_height = 140
        self.card_spacing = 15
        self.max_visible_quests = 3
        self.scroll_offset = 0
        self.hovered_quest_index = None

    def close(self):
        self.active = False
        self.hovered_quest_index = None
        self.scroll_offset = 0

    def get_quest_at_mouse(self, mouse_x, mouse_y, menu_x, menu_y, quest_count):
        """Returns the quest index at the given mouse position, or None"""
        relative_mouse_x = mouse_x - menu_x
        relative_mouse_y = mouse_y - menu_y

        content_start_y = self.content_top

        if relative_mouse_x < self.padding or relative_mouse_x > self.width - self.padding:
            return None
        if relative_mouse_y < content_start_y:
            return None

        for i in range(min(quest_count, self.max_visible_quests)):
            visible_index = i + self.scroll_offset
            if visible_index >= quest_count:
                break

            card_y = content_start_y + i * (self.card_height + self.card_spacing)

            if relative_mouse_y >= card_y and relative_mouse_y < card_y + self.card_height:
                return visible_index

        return None

    def handle_event(self, event, quest_system):
        if not self.active:
            return False

        max_scroll = max(0, len(quest_system.active_quests) - self.max_visible_quests)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self.scroll_offset = max(0, self.scroll_offset - 1)
            elif event.key == pygame.K_DOWN:
                self.scroll_offset = min(max_scroll, self.scroll_offset + 1)
            elif event.key in (pygame.K_q, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEWHEEL:
            self.scroll_offset = max(0, min(max_scroll, self.scroll_offset - event.y))

        return True

    def draw(self, quest_system: QuestSystem):
        if not self.active:
            return

        menu_x, menu_y = self.get_centered_position()

        self.draw_overlay()

        menu_surface = self.create_menu_surface("Active Quests")

        quest_count = len(quest_system.active_quests)
        count_text = c.Fonts.text.render(f"{quest_count} active", True, c.Colors.ACCENT)
        menu_surface.blit(
            count_text,
            (self.width - self.padding - count_text.get_width(), (HEADER_HEIGHT - count_text.get_height()) // 2),
        )

        mouse_pos = pygame.mouse.get_pos()
        self.hovered_quest_index = self.get_quest_at_mouse(mouse_pos[0], mouse_pos[1], menu_x, menu_y, quest_count)

        if quest_count == 0:
            no_quests_text = c.Fonts.heading.render("No active quests", True, c.Colors.MUTED)
            text_x = (self.width - no_quests_text.get_width()) // 2
            text_y = (self.height - no_quests_text.get_height()) // 2
            menu_surface.blit(no_quests_text, (text_x, text_y))
        else:
            content_start_y = self.content_top

            for i in range(min(quest_count, self.max_visible_quests)):
                visible_index = i + self.scroll_offset
                if visible_index >= quest_count:
                    break

                quest = quest_system.active_quests[visible_index]
                card_y = content_start_y + i * (self.card_height + self.card_spacing)

                card_rect = pygame.Rect(self.padding, card_y, self.card_width, self.card_height)
                widgets.draw_slot(menu_surface, card_rect, hovered=visible_index == self.hovered_quest_index, radius=10)

                text_x = self.padding + 15
                text_y = card_y + 10

                npc_text = c.Fonts.heading.render(quest.npc_name, True, c.Colors.YELLOW)
                menu_surface.blit(npc_text, (text_x, text_y))

                desc_y = text_y + 40
                max_width = self.card_width - 30
                wrapped_lines = self._wrap_text(quest.description, max_width)

                for line in wrapped_lines[:2]:  # Show max 2 lines
                    desc_surface = c.Fonts.text.render(line, True, c.Colors.WHITE)
                    menu_surface.blit(desc_surface, (text_x, desc_y))
                    desc_y += 22

                bottom_y = card_y + self.card_height - 50
                if quest.quest_type == "kill_mob":
                    item_text = f"Kill: {quest.target_monster_kind} ({quest.kills_done}/{quest.kill_count})"
                elif quest.quest_type == "loot_mob":
                    item_text = f"Loot: {quest.item_name} from a {quest.target_monster_kind}"
                elif quest.quest_type == "recover_stolen":
                    item_text = f"Recover: {quest.item_name} from {quest.thief_npc_name}"
                else:
                    item_text = f"Fetch: {quest.item_name}"
                item_surface = c.Fonts.button.render(item_text, True, c.Colors.WHITE)
                menu_surface.blit(item_surface, (text_x, bottom_y))

                if quest.reward_item_name:
                    reward_text = f"Reward: {quest.reward_item_name}"
                    reward_color = c.Colors.YELLOW
                else:
                    reward_text = "Reward: coins"
                    reward_color = c.Colors.WHITE
                reward_surface = c.Fonts.button.render(reward_text, True, reward_color)
                menu_surface.blit(reward_surface, (text_x, bottom_y + 22))

            if quest_count > self.max_visible_quests:
                self._draw_scroll_indicator(menu_surface, quest_count)

        self.screen.blit(menu_surface, (menu_x, menu_y))

    def _wrap_text(self, text: str, max_width):
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            test_surface = c.Fonts.text.render(test_line, True, c.Colors.WHITE)

            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def _draw_scroll_indicator(self, surface, quest_count):
        indicator_x = self.width - 12
        indicator_y = self.content_top
        indicator_height = self.max_visible_quests * (self.card_height + self.card_spacing) - self.card_spacing

        pygame.draw.rect(surface, c.Colors.SLOT_BG, (indicator_x, indicator_y, 6, indicator_height), border_radius=3)

        thumb_height = max(20, (self.max_visible_quests / quest_count) * indicator_height)
        thumb_y = indicator_y + (self.scroll_offset / (quest_count - self.max_visible_quests)) * (
            indicator_height - thumb_height
        )
        pygame.draw.rect(surface, c.Colors.ACCENT, (indicator_x, thumb_y, 6, thumb_height), border_radius=3)
