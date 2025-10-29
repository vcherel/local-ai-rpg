import pygame

import core.constants as c

class ContextWindow:
    def __init__(self, screen_width, screen_height):
        self.active = False
        self.context_text = None
        
        # Window dimensions
        self.width = 600
        self.height = 200
        self.x = (screen_width - self.width) // 2
        self.y = (screen_height - self.height) // 2
        
        # Font
        self.title_font = pygame.font.SysFont("arial", 24, bold=True)
        self.text_font = pygame.font.SysFont("arial", 18)
    
    def toggle(self, context):
        """Set the context and show the window"""
        self.context_text = context
        self.active = True
    
    def handle_event(self, event):
        """Handle mouse events for the window"""
        if not self.active:
            return False
        
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                self.close()
        
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()

        return True
    
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
