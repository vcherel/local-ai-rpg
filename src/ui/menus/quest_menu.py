from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

import core.constants as c

if TYPE_CHECKING:
    from llm.quest_system import QuestSystem


# TODO: gather code from menus
class QuestMenu:
    """Quest Menu display"""
    def __init__(self, screen):
        self.screen: pygame.Surface = screen
        self.active = False

        # Menu dimensions
        self.width = 700
        self.height = 550
        self.padding = 20
        
        # Quest card settings
        self.card_width = self.width - 2 * self.padding
        self.card_height = 120
        self.card_spacing = 15
        self.max_visible_quests = 3
        self.scroll_offset = 0
        self.hovered_quest_index = None
        
    def toggle(self):
        self.active = not self.active
        
    def close(self):
        self.active = False
        self.hovered_quest_index = None
        self.scroll_offset = 0
        
    def get_quest_at_mouse(self, mouse_x, mouse_y, menu_x, menu_y, quest_count):
        """Returns the quest index at the given mouse position, or None"""
        relative_mouse_x = mouse_x - menu_x
        relative_mouse_y = mouse_y - menu_y
        
        content_start_y = self.padding + 100
        
        if relative_mouse_x < self.padding or relative_mouse_x > self.width - self.padding:
            return None
        if relative_mouse_y < content_start_y:
            return None
            
        # Calculate which quest card is being hovered
        for i in range(min(quest_count, self.max_visible_quests)):
            visible_index = i + self.scroll_offset
            if visible_index >= quest_count:
                break
                
            card_y = content_start_y + i * (self.card_height + self.card_spacing)
            
            if (relative_mouse_y >= card_y and 
                relative_mouse_y < card_y + self.card_height):
                return visible_index
        
        return None
        
    def handle_event(self, event, quest_system):
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self.scroll_offset = max(0, self.scroll_offset - 1)
            elif event.key == pygame.K_DOWN:
                max_scroll = max(0, len(quest_system.active_quests) - self.max_visible_quests)
                self.scroll_offset = min(max_scroll, self.scroll_offset + 1)
            elif event.key in (pygame.K_q, pygame.K_ESCAPE):
                self.close()

        return True

    def draw(self, quest_system: QuestSystem):
        if not self.active:
            return
        
        # Calculate centered position
        menu_x = (c.Screen.WIDTH - self.width) // 2
        menu_y = (c.Screen.HEIGHT - self.height) // 2
        
        # Draw semi-transparent background overlay
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill(c.Colors.TRANSPARENT)
        self.screen.blit(overlay, (0, 0))
        
        # Draw menu background
        menu_surface = pygame.Surface((self.width, self.height))
        menu_surface.fill(c.Colors.MENU_BACKGROUND)
        pygame.draw.rect(menu_surface, c.Colors.WHITE, (0, 0, self.width, self.height), 3)
        
        # Draw title
        title = c.Fonts.title.render("Quêtes Actives", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        menu_surface.blit(title, (title_x, self.padding))
        
        # Draw quest count
        quest_count = len(quest_system.active_quests)
        count_text = c.Fonts.text.render(f"Quêtes: {quest_count}", True, c.Colors.YELLOW)
        menu_surface.blit(count_text, (self.padding, self.padding + 50))
        
        # Get mouse position for hover detection
        mouse_pos = pygame.mouse.get_pos()
        self.hovered_quest_index = self.get_quest_at_mouse(
            mouse_pos[0], mouse_pos[1], menu_x, menu_y, quest_count
        )
        
        # Draw quests
        if quest_count == 0:
            no_quests_text = c.Fonts.heading.render(
                "Aucune quête active", True, c.Colors.WHITE
            )
            text_x = (self.width - no_quests_text.get_width()) // 2
            text_y = (self.height - no_quests_text.get_height()) // 2
            menu_surface.blit(no_quests_text, (text_x, text_y))
        else:
            content_start_y = self.padding + 100
            
            # Draw visible quests
            for i in range(min(quest_count, self.max_visible_quests)):
                visible_index = i + self.scroll_offset
                if visible_index >= quest_count:
                    break
                    
                quest = quest_system.active_quests[visible_index]
                card_y = content_start_y + i * (self.card_height + self.card_spacing)
                
                # Determine card colors based on hover and completion
                if visible_index == self.hovered_quest_index:
                    card_color = c.Colors.BUTTON_HOVERED
                    border_color = c.Colors.BORDER_HOVERED
                else:
                    card_color = c.Colors.BUTTON
                    border_color = c.Colors.BORDER
                
                # Draw card background
                pygame.draw.rect(menu_surface, card_color,
                               (self.padding, card_y, self.card_width, self.card_height))
                pygame.draw.rect(menu_surface, border_color,
                               (self.padding, card_y, self.card_width, self.card_height), 2)
                
                # Draw quest details
                text_x = self.padding + 15
                text_y = card_y + 10
                
                # NPC name
                npc_text = c.Fonts.heading.render(quest.npc_name, True, c.Colors.YELLOW)
                menu_surface.blit(npc_text, (text_x, text_y))
                
                # Quest description (wrapped if too long)
                desc_y = text_y + 30
                max_width = self.card_width - 30
                wrapped_lines = self._wrap_text(quest.description, max_width)
                
                for line in wrapped_lines[:2]:  # Show max 2 lines
                    desc_surface = c.Fonts.medium.render(line, True, c.Colors.WHITE)
                    menu_surface.blit(desc_surface, (text_x, desc_y))
                    desc_y += 22
                
                # Item requirement
                item_y = card_y + self.card_height - 25
                item_text = f"Objet: {quest.item_name}"
                item_surface = c.Fonts.medium.render(item_text, True, c.Colors.WHITE)
                menu_surface.blit(item_surface, (text_x, item_y))
            
            # Draw scroll indicator if needed
            if quest_count > self.max_visible_quests:
                self._draw_scroll_indicator(menu_surface, quest_count)
        
        # Blit menu to screen
        self.screen.blit(menu_surface, (menu_x, menu_y))
    
    def _wrap_text(self, text: str, max_width):
        """Wrap text to fit within max_width pixels"""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            test_surface = c.Fonts.text.render(test_line, True, c.Colors.WHITE)
            
            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
    
    def _draw_scroll_indicator(self, surface, quest_count):
        """Draw a scroll bar on the right side"""
        indicator_x = self.width - 15
        indicator_y = self.padding + 100
        indicator_height = self.max_visible_quests * (self.card_height + self.card_spacing) - self.card_spacing
        
        # Draw track
        pygame.draw.rect(surface, (80, 80, 80),
                        (indicator_x, indicator_y, 5, indicator_height))
        
        # Draw thumb
        thumb_height = max(20, (self.max_visible_quests / quest_count) * indicator_height)
        thumb_y = indicator_y + (self.scroll_offset / (quest_count - self.max_visible_quests)) * (indicator_height - thumb_height)
        pygame.draw.rect(surface, c.Colors.YELLOW,
                        (indicator_x, thumb_y, 5, thumb_height))
