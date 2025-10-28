import pygame


class ContextWindow:
    def __init__(self, screen_width, screen_height):
        self.visible = False
        self.context_text = None
        self.shown_once = False
        
        # Window dimensions
        self.width = 600
        self.height = 200
        self.x = (screen_width - self.width) // 2
        self.y = (screen_height - self.height) // 2
        
        # Colors
        self.bg_color = (40, 40, 50, 230)  # Semi-transparent dark background
        self.border_color = (100, 100, 120)
        self.text_color = (255, 255, 255)
        self.button_color = (80, 80, 100)
        self.button_hover_color = (100, 100, 120)
        
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
            self.visible = True
            self.shown_once = True
    
    def handle_event(self, event):
        """Handle mouse events for the window"""
        if not self.visible:
            return False
        
        if event.type == pygame.MOUSEMOTION:
            self.button_hovered = self.close_button.collidepoint(event.pos)
        
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                if self.close_button.collidepoint(event.pos):
                    self.visible = False
                    return True
        
        return False
    
    def draw(self, screen):
        if not self.visible or self.context_text is None:
            return
        
        # Create semi-transparent overlay
        overlay = pygame.Surface((screen.get_width(), screen.get_height()), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 100))
        screen.blit(overlay, (0, 0))
        
        # Draw window background
        window_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        window_surface.fill(self.bg_color)
        pygame.draw.rect(window_surface, self.border_color, (0, 0, self.width, self.height), 2)
        
        # Draw title
        title = self.title_font.render("Contexte du monde", True, self.text_color)
        window_surface.blit(title, (20, 20))
        
        # Draw context text (wrapped)
        self._draw_wrapped_text(window_surface, self.context_text, 20, 60, self.width - 40)
        
        # Draw close button
        button_color = self.button_hover_color if self.button_hovered else self.button_color
        button_rect = pygame.Rect(self.width - 80, self.height - 50, 60, 30)
        pygame.draw.rect(window_surface, button_color, button_rect, border_radius=5)
        pygame.draw.rect(window_surface, self.border_color, button_rect, 2, border_radius=5)
        
        button_text = self.button_font.render("Ok", True, self.text_color)
        text_rect = button_text.get_rect(center=button_rect.center)
        window_surface.blit(button_text, text_rect)
        
        # Blit window to screen
        screen.blit(window_surface, (self.x, self.y))
    
    def _draw_wrapped_text(self, surface, text, x, y, max_width):
        """Draw text with word wrapping"""
        words = text.split(' ')
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            test_surface = self.text_font.render(test_line, True, self.text_color)
            
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
            line_surface = self.text_font.render(line, True, self.text_color)
            surface.blit(line_surface, (x, y + i * 25))
