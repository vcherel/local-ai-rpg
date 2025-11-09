import pygame

import core.constants as c

class ContextMenu:
    """Display the window that gives information about the world"""
    
    def __init__(self, screen):
        self.screen: pygame.Surface = screen
        self.active = False
        self.context_text = None
        
        # Window dimensions (will be calculated dynamically)
        self.width = 0
        self.height = 0
        self.x = c.Screen.ORIGIN_X
        self.y = c.Screen.ORIGIN_Y - 100
    
    def toggle(self, context):
        """Set the context and show the window"""
        self.context_text = context
        self.active = True
        
        # Calculate dimensions based on text
        self._calculate_dimensions()
    
    def _calculate_dimensions(self):
        """Calculate window dimensions based on the text content"""
        if not self.context_text:
            return
            
        # Calculate text dimensions
        lines = self._get_wrapped_lines(self.context_text, c.Screen.WIDTH * 0.3)  # Use 30% of screen width max
        
        # Find the longest line width
        max_line_width = 0
        for line in lines:
            line_surface = c.Fonts.text.render(line, True, c.Colors.WHITE)
            max_line_width = max(max_line_width, line_surface.get_width())
        
        # Set dimensions with padding
        padding_x = 60
        padding_y = 100
        
        self.width = max_line_width + padding_x
        self.height = len(lines) * 25 + padding_y
        
        # Ensure minimum dimensions
        self.width = max(self.width, 300)
        self.height = max(self.height, 150)
    
    def _get_wrapped_lines(self, text: str, max_width: int):
        """Split text into wrapped lines and return as list"""
        words = text.split(' ')
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
    
    def draw(self):
        if not self.active or self.context_text is None:
            return

        # Semi-transparent dark overlay
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill(c.Colors.TRANSPARENT) 
        self.screen.blit(overlay, (0, 0))

        # Centered window position
        window_x = (c.Screen.WIDTH - self.width) // 2
        window_y = (c.Screen.HEIGHT - self.height) // 2

        # Window background
        window_surface = pygame.Surface((self.width, self.height))
        window_surface.fill(c.Colors.MENU_BACKGROUND)  # dark gray like inventory
        pygame.draw.rect(window_surface, c.Colors.WHITE, (0, 0, self.width, self.height), 3)

        # Title
        title = c.Fonts.heading.render("Contexte du monde", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        window_surface.blit(title, (title_x, 20))

        # Context text
        self._draw_wrapped_text(window_surface, self.context_text, 30, 70, self.width - 60)

        # Draw final window to screen
        self.screen.blit(window_surface, (window_x, window_y))

    def _draw_wrapped_text(self, surface: pygame.Surface, text: str, x, y, max_width):
        """Draw text with word wrapping"""
        lines = self._get_wrapped_lines(text, max_width)
        
        # Draw lines
        for i, line in enumerate(lines):
            line_surface = c.Fonts.text.render(line, True, c.Colors.WHITE)
            surface.blit(line_surface, (x, y + i * 25))

    def close(self):
        self.active = False
