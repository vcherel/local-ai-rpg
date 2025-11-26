import pygame

import core.constants as c


class BaseMenu:
    """Base class for all menu windows in the game"""
    
    def __init__(self, screen: pygame.Surface, width: int, height: int):
        self.screen = screen
        self.active = False
        self.just_active = False
        self.width = width
        self.height = height
        self.padding = 20
    
    def toggle(self):
        """Toggle menu visibility"""
        self.active = not self.active
        self.just_active = True
    
    def close(self):
        """Close the menu"""
        self.active = False
    
    def get_centered_position(self) -> tuple[int, int]:
        """Calculate centered position for the menu window"""
        menu_x = (c.Screen.WIDTH - self.width) // 2
        menu_y = (c.Screen.HEIGHT - self.height) // 2
        return menu_x, menu_y
    
    def draw_overlay(self):
        """Draw semi-transparent dark overlay behind menu"""
        if self.just_active:
            print("DRAW OVERLAY")
            overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
            overlay.fill(c.Colors.TRANSPARENT)
            self.screen.blit(overlay, (0, 0))
            self.just_active = False
    
    def create_menu_surface(self) -> pygame.Surface:
        """Create menu background surface with border"""
        surface = pygame.Surface((self.width, self.height))
        surface.fill(c.Colors.MENU_BACKGROUND)
        pygame.draw.rect(surface, c.Colors.WHITE, (0, 0, self.width, self.height), 3)
        return surface
    
    @staticmethod
    def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        """
        Wrap text to fit within max_width pixels.
        Returns list of wrapped lines.
        """
        words = text.split(' ')
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            test_surface = font.render(test_line, True, c.Colors.WHITE)
            
            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))
            
        return lines
    
    def draw_wrapped_text(self, surface: pygame.Surface, text: str, x: int, y: int, 
                         max_width: int, font=None, line_spacing: int = 25):
        """
        Draw text with word wrapping at specified position.
        Returns the final y position after all lines.
        """
        if font is None:
            font = c.Fonts.text
            
        lines = self.wrap_text(text, font, max_width)
        
        for i, line in enumerate(lines):
            line_surface = font.render(line, True, c.Colors.WHITE)
            surface.blit(line_surface, (x, y + i * line_spacing))
        
        return y + len(lines) * line_spacing