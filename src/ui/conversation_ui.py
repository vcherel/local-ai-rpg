from typing import List
import pygame

from core.utils import ConversationHistory
import core.constants as c


class ConversationUI:
    """Handles all UI rendering and input for dialogue"""
    
    def __init__(self):
        # Fonts
        self.font = pygame.font.SysFont("arial", 28, bold=True)
        self.message_font = pygame.font.SysFont("arial", 20)
        self.input_font = pygame.font.SysFont("arial", 24)
        self.small_font = pygame.font.SysFont("arial", 18)
        
        # Scroll state
        self.scroll_offset = 0
        self.max_visible_height = 170
        self.line_height = 26
        
        # Input state
        self.user_input = ""
    
    def handle_text_input(self, event) -> str:
        """Handle text input, return message if ENTER pressed"""
        if event.key == pygame.K_RETURN and self.user_input.strip():
            message = self.user_input
            self.user_input = ""
            return message
        elif event.key == pygame.K_BACKSPACE:
            self.user_input = self.user_input[:-1]
        elif event.unicode and len(self.user_input) < 150:
            self.user_input += event.unicode
        return None
    
    def handle_scroll(self, direction: int, history: ConversationHistory, npc_name: str):
        """Handle arrow key scrolling (1 for up, -1 for down)"""
        scroll_amount = -self.line_height * direction
        total_height = self._calculate_total_height(history.messages, npc_name)
        max_scroll = max(0, total_height - self.max_visible_height)
        self.scroll_offset = max(0, min(self.scroll_offset + scroll_amount, max_scroll))
    
    def auto_scroll(self, history: ConversationHistory, npc_name: str):
        """Auto-scroll to bottom of chat"""
        total_height = self._calculate_total_height(history.messages, npc_name)
        if total_height > self.max_visible_height:
            self.scroll_offset = total_height - self.max_visible_height
        else:
            self.scroll_offset = 0
    
    def reset(self):
        """Reset UI state"""
        self.user_input = ""
        self.scroll_offset = 0
    
    def _calculate_total_height(self, messages: list, npc_name: str) -> int:
        """Calculate total height of all messages"""
        total_height = 0
        for msg in messages:
            prefix = "Vous : " if msg["role"] == "user" else f"{npc_name} : "
            lines = self._wrap_text(prefix + msg["content"])
            total_height += len(lines) * self.line_height
        return total_height
    
    def _wrap_text(self, text: str) -> List[str]:
        """Wrap text to fit within dialogue box"""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            if self.message_font.size(test_line)[0] < c.Screen.WIDTH - 60:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
    
    def draw(self, screen: pygame.Surface, npc_name: str, history: ConversationHistory):
        """Draw dialogue box with conversation"""
        box_height = 300
        box_y = c.Screen.HEIGHT - box_height - 25
        
        # Draw main box
        pygame.draw.rect(screen, c.Colors.MENU_BACKGROUND, (10, box_y, c.Screen.WIDTH - 20, box_height))
        pygame.draw.rect(screen, c.Colors.WHITE, (10, box_y, c.Screen.WIDTH - 20, box_height), 2)
        
        # Draw NPC name
        name_surface = self.font.render(npc_name, True, c.Colors.YELLOW)
        screen.blit(name_surface, (25, box_y + 10))
        
        # Draw messages
        self._draw_messages(screen, box_y, npc_name, history.messages)
        
        # Draw input box
        self._draw_input_box(screen, box_y, box_height)
    
    def _draw_messages(self, screen: pygame.Surface, box_y: int, npc_name: str, messages: list):
        """Draw scrollable conversation messages"""
        message_area_y = box_y + 55
        clip_rect = pygame.Rect(20, message_area_y, c.Screen.WIDTH - 40, self.max_visible_height)
        screen.set_clip(clip_rect)
        
        y_offset = message_area_y - self.scroll_offset
        total_height = self._calculate_total_height(messages, npc_name)
        
        for msg in messages:
            if msg["role"] == "user":
                prefix = "Vous : "
                color = c.Colors.CYAN
            elif msg["role"] == "assistant":
                prefix = f"{npc_name} : "
                color = c.Colors.WHITE
            else:
                prefix = ""
                color = c.Colors.BLACK
            
            lines = self._wrap_text(prefix + msg["content"])
            for line in lines:
                text_surface = self.message_font.render(line, True, color)
                screen.blit(text_surface, (25, y_offset))
                y_offset += self.line_height
        
        screen.set_clip(None)
        
        # Draw scroll indicator
        if total_height > self.max_visible_height and self.scroll_offset < total_height - self.max_visible_height:
            scroll_text = "↑ Défiler pour voir plus"
            scroll_surface = self.small_font.render(scroll_text, True, c.Colors.YELLOW)
            screen.blit(scroll_surface, (c.Screen.WIDTH - 250, message_area_y - 35))
    
    def _draw_input_box(self, screen: pygame.Surface, box_y: int, box_height: int):
        """Draw the chat input box"""
        input_y = box_y + box_height - 60
        pygame.draw.rect(screen, c.Colors.BLACK, (20, input_y, c.Screen.WIDTH - 40, 35))
        pygame.draw.rect(screen, c.Colors.WHITE, (20, input_y, c.Screen.WIDTH - 40, 35), 2)
        
        input_text = self.user_input + "|"
        input_surface = self.input_font.render(input_text, True, c.Colors.WHITE)
        screen.blit(input_surface, (30, input_y))
