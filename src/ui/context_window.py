import pygame

import core.constants as c

class ContextWindow:
    def __init__(self, screen_width, screen_height):
        self.active = False
        self.context_text = None
        self.shown_once = False
        
        # Window dimensions
        self.width = 600
        self.height = 200
        self.x = (screen_width - self.width) // 2
        self.y = (screen_height - self.height) // 2
        
        # Close button
        self.close_button = pygame.Rect(self.x + self.width - 80, self.y + self.height - 50, 60, 30)
        self.button_hovered = False
        
        # Font
        self.title_font = pygame.font.SysFont("arial", 24, bold=True)
        self.text_font = pygame.font.SysFont("arial", 18)
        self.button_font = pygame.font.SysFont("arial", 16)
    
    def set_context(self, context):
        """Set the context and show the window"""
        if not self.shown_once:
            self.context_text = context
            self.active = True
            self.shown_once = True
    
    def handle_event(self, event):
        """Handle mouse events for the window"""
        if not self.active:
            return False
        
        if event.type == pygame.MOUSEMOTION:
            self.button_hovered = self.close_button.collidepoint(event.pos)
        
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                if self.close_button.collidepoint(event.pos):
                    self.close()
                    return True
        return False
    
    def draw(self, screen):
        if not self.active or self.context_text is None:
            return

        screen_width = screen.get_width()
        screen_height = screen.get_height()

        # Semi-transparent dark overlay
        overlay = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150)) 
        screen.blit(overlay, (0, 0))

        # --- Centered window position ---
        window_x = (screen_width - self.width) // 2
        window_y = (screen_height - self.height) // 2

        #Window background
        window_surface = pygame.Surface((self.width, self.height))
        window_surface.fill(c.Colors.MENU_BACKGROUND)  # dark gray like inventory
        pygame.draw.rect(window_surface, c.Colors.WHITE, (0, 0, self.width, self.height), 3)

        # Title
        title = self.title_font.render("Contexte du monde", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        window_surface.blit(title, (title_x, 20))

        #  Context text
        self._draw_wrapped_text(window_surface, self.context_text, 30, 70, self.width - 60)

        # Button styling
        button_rect = pygame.Rect(self.width - 100, self.height - 60, 80, 35)
        if self.button_hovered:
            button_color = c.Colors.BUTTON_HOVERED
            border_color = c.Colors.BORDER_HOVERED
        else:
            button_color = c.Colors.BUTTON
            border_color = c.Colors.BORDER

        pygame.draw.rect(window_surface, button_color, button_rect, border_radius=6)
        pygame.draw.rect(window_surface, border_color, button_rect, 2, border_radius=6)

        # Button text
        button_text = self.button_font.render("OK", True, (255, 255, 255))
        text_rect = button_text.get_rect(center=button_rect.center)
        window_surface.blit(button_text, text_rect)

        # Close instruction
        close_text = self.text_font.render("Appuyez sur ECHAP pour fermer", True, c.Colors.ECHAP_TEXT)
        close_x = (self.width - close_text.get_width()) // 2
        window_surface.blit(close_text, (close_x, self.height - 30))

        # Draw final window to screen
        screen.blit(window_surface, (window_x, window_y))


    def _draw_wrapped_text(self, surface, text, x, y, max_width):
        """Draw text with word wrapping"""
        words = text.split(' ')
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            test_surface = self.text_font.render(test_line, True, c.Colors.WHITE)
            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        # Draw lines
        for i, line in enumerate(lines):
            line_surface = self.text_font.render(line, True, c.Colors.WHITE)
            surface.blit(line_surface, (x, y + i * 25))

    def close(self):
        self.active = False