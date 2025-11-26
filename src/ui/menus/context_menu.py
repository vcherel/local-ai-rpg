import pygame

import core.constants as c
from ui.menus.base_menu import BaseMenu


class ContextMenu(BaseMenu):
    """Display the window that gives information about the world"""
    
    def __init__(self, screen):
        super().__init__(screen, width=0, height=0) # Window dimensions will be calculated dynamically
        self.context_text = None
        
        self.x = c.Screen.ORIGIN_X
        self.y = c.Screen.ORIGIN_Y - 100
    
    def toggle(self, context):
        """Set the context and show the window"""
        super().toggle()

        self.context_text = context
        
        # Calculate dimensions based on text
        self._calculate_dimensions()
    
    def _calculate_dimensions(self):
        """Calculate window dimensions based on the text content"""
        if not self.context_text:
            return
            
        # Calculate text dimensions
        lines = self.wrap_text(self.context_text, c.Fonts.text, c.Screen.WIDTH * 0.3)  # Use 30% of screen width max
        
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

        # Draw overlay
        self.draw_overlay()

        # Centered window position
        window_x, window_y = self.get_centered_position()

        # Create menu surface
        menu_surface = self.create_menu_surface()

        # Title
        title = c.Fonts.heading.render("Contexte du monde", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        menu_surface.blit(title, (title_x, 20))

        # Context text
        self.draw_wrapped_text(menu_surface, self.context_text, 30, 70, self.width - 60)

        # Draw final window to screen
        self.screen.blit(menu_surface, (window_x, window_y))
