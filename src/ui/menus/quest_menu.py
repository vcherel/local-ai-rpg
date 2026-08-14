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
            elif event.key in (pygame.K_j, pygame.K_ESCAPE):
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
                widgets.draw_slot(menu_surface, card_rect, hovered=visible_index == self.hovered_quest_index)
                self._draw_card(menu_surface, quest, card_y)

            if quest_count > self.max_visible_quests:
                self._draw_scroll_indicator(menu_surface, quest_count)

        self.screen.blit(menu_surface, (menu_x, menu_y))

    def _objective_text(self, quest) -> str:
        if quest.quest_type == "kill_mob":
            return f"Kill: {quest.target_monster_kind} ({quest.kills_done}/{quest.kill_count})"
        if quest.quest_type == "loot_mob":
            return f"Loot: {quest.item_name} from a {quest.target_monster_kind}"
        if quest.quest_type == "recover_stolen":
            return f"Recover: {quest.item_name} from {quest.thief_npc_name}"
        if quest.quest_type == "slay_boss":
            return f"Slay: {quest.boss_name}" if quest.boss_name else "Slay: the boss"
        if quest.quest_type == "clear_camp":
            return f"Clear: the bandit camp ({quest.kills_done}/{quest.kill_count})"
        if quest.quest_type == "steal":
            return f"Steal: {quest.item_name} from a house"
        if quest.quest_type == "deliver":
            return f"Deliver: {quest.item_name} to {quest.recipient_npc_name} ({quest.kills_done}/{quest.kill_count})"
        return f"Fetch: {quest.item_name}"

    def _draw_card(self, surface, quest, card_y: int):
        """Name, description, objective and reward stacked in that order. The objective and
        reward sit at the bottom of the card and the description takes whatever room is
        left above them, so a long one is trimmed instead of running into them."""
        text_x = self.padding + 15
        max_width = self.card_width - 30
        line_height = 22

        npc_surface = c.Fonts.heading.render(quest.npc_name, True, c.Colors.YELLOW)
        surface.blit(npc_surface, (text_x, card_y + 10))

        objective_surface = c.Fonts.button.render(self._objective_text(quest), True, c.Colors.WHITE)
        if quest.reward_item_name:
            reward_surface = c.Fonts.button.render(f"Reward: {quest.reward_item_name}", True, c.Colors.YELLOW)
        else:
            reward_surface = c.Fonts.button.render("Reward: coins", True, c.Colors.WHITE)

        block_height = objective_surface.get_height() + reward_surface.get_height() + 4
        block_y = card_y + self.card_height - 10 - block_height

        desc_y = card_y + 10 + npc_surface.get_height() + 6
        max_lines = max(1, (block_y - 4 - desc_y) // line_height)
        lines = widgets.wrap_text(quest.description, c.Fonts.text, max_width)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self._ellipsize(lines[-1], max_width)

        for line in lines:
            surface.blit(c.Fonts.text.render(line, True, c.Colors.WHITE), (text_x, desc_y))
            desc_y += line_height

        surface.blit(objective_surface, (text_x, block_y))
        surface.blit(reward_surface, (text_x, block_y + objective_surface.get_height() + 4))

    def _ellipsize(self, text: str, max_width: int) -> str:
        """Mark a truncated last line, dropping characters until the ellipsis fits."""
        while text and c.Fonts.text.size(text + "...")[0] > max_width:
            text = text[:-1]
        return text.rstrip() + "..."

    def _draw_scroll_indicator(self, surface, quest_count):
        indicator_x = self.width - 12
        indicator_y = self.content_top
        indicator_height = self.max_visible_quests * (self.card_height + self.card_spacing) - self.card_spacing

        pygame.draw.rect(surface, c.Colors.SLOT_BG, (indicator_x, indicator_y, 6, indicator_height))

        thumb_height = max(20, (self.max_visible_quests / quest_count) * indicator_height)
        thumb_y = indicator_y + (self.scroll_offset / (quest_count - self.max_visible_quests)) * (
            indicator_height - thumb_height
        )
        pygame.draw.rect(surface, c.Colors.ACCENT, (indicator_x, thumb_y, 6, thumb_height))
