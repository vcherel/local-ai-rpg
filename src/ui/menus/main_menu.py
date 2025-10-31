from __future__ import annotations

import sys
import pygame
from typing import TYPE_CHECKING

import core.constants as c

if TYPE_CHECKING:
    from core.save import SaveSystem

class MainMenu:
    """Main Menu of the game (New game, Continue)"""

    def __init__(self, screen, save_system):
        self.screen: pygame.Surface = screen
        self.save_system: SaveSystem = save_system
        self.active = True

        # Button dimensions
        self.button_width = 300
        self.button_height = 60
        self.button_spacing = 20

        # Calculate positions
        center_x = c.Screen.WIDTH // 2 - self.button_width // 2
        center_y = c.Screen.HEIGHT // 2 - self.button_height

        # Create button rectangles
        self.new_game_button = pygame.Rect(center_x, center_y, self.button_width, self.button_height)
        self.continue_button = pygame.Rect(
            center_x,
            center_y + self.button_height + self.button_spacing,
            self.button_width,
            self.button_height
        )

        # Colors
        self.button_default_color = c.Colors.BUTTON
        self.button_hover_color = c.Colors.BUTTON_HOVERED

    def handle_click(self, pos):
        """Handle mouse clicks on menu buttons"""
        if self.new_game_button.collidepoint(pos):
            self.save_system.clear()
            self.active = False
            return "new_game"
        elif self.continue_button.collidepoint(pos):
            return "continue"
        return None

    def draw_button(self, rect: pygame.Rect, text, mouse_pos):
        hover = rect.collidepoint(mouse_pos)
        color = self.button_hover_color if hover else self.button_default_color
        border_color = c.Colors.BORDER_HOVERED if hover else c.Colors.BORDER

        # Draw button background
        pygame.draw.rect(self.screen, color, rect)
        pygame.draw.rect(self.screen, border_color, rect, 3)

        # Draw button text
        text_surf = c.Fonts.title.render(text, True, c.Colors.WHITE)
        text_rect = text_surf.get_rect(center=rect.center)
        self.screen.blit(text_surf, text_rect)

    def draw(self):
        if not self.active:
            return
        
        self.screen.fill(c.Colors.MENU_BACKGROUND)

        # Draw title
        title_text = c.Fonts.big_title.render("RPG IA", True, c.Colors.WHITE)
        title_x = (self.screen.get_width() - title_text.get_width()) // 2
        title_y = 150
        self.screen.blit(title_text, (title_x, title_y))

        # Mouse position
        mouse_pos = pygame.mouse.get_pos()

        # Draw buttons with hover style
        self.draw_button(self.new_game_button, "Nouvelle Partie", mouse_pos)
        self.draw_button(self.continue_button, "Continuer", mouse_pos)

def run_main_menu(screen, clock, save_system):
    main_menu = MainMenu(screen, save_system)
    
    while main_menu.active:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    result = main_menu.handle_click(event.pos)
                    if result == "new_game":
                        return True  # Start new game
                    elif result == "continue":
                        return True
        
        main_menu.draw()
        pygame.display.flip()
        clock.tick(60)
    
    return True
