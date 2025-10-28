import sys
import pygame

import core.constants as c
from core.save import SaveSystem

class MainMenu:
    def __init__(self, screen, save_system):
        self.screen = screen
        self.save_system: SaveSystem = save_system
        self.active = True
        
        # Fonts
        self.title_font = pygame.font.SysFont("arial", 64, bold=True)
        self.button_font = pygame.font.SysFont("arial", 32)
        
        # Button dimensions
        button_width = 300
        button_height = 60
        button_spacing = 20
        center_x = c.Screen.WIDTH // 2 - button_width // 2
        center_y = c.Screen.HEIGHT // 2 - button_height
        
        # Create button rectangles
        self.new_game_button = pygame.Rect(center_x, center_y, button_width, button_height)
        self.continue_button = pygame.Rect(
            center_x, 
            center_y + button_height + button_spacing, 
            button_width, 
            button_height
        )

        # Colors
        self.button_default_color = (70, 130, 70)
        self.button_hover_color = (50, 100, 50)
        
    def handle_click(self, pos):
        """Handle mouse clicks on menu buttons"""
        if self.new_game_button.collidepoint(pos):
            self.save_system.clear()
            self.active = False
            return "new_game"
        elif self.continue_button.collidepoint(pos):
            return "continue"
        return None
    
    def draw_button(self, rect, text, mouse_pos):
        hover = rect.collidepoint(mouse_pos)
        color = self.button_hover_color if hover else self.button_default_color
        pygame.draw.rect(self.screen, color, rect)
        pygame.draw.rect(self.screen, c.Colors.WHITE, rect, 3)
        
        text_surf = self.button_font.render(text, True, c.Colors.WHITE)
        text_rect = text_surf.get_rect(center=rect.center)
        self.screen.blit(text_surf, text_rect)

    def draw(self):
        """Draw the main menu"""
        # Background
        self.screen.fill((20, 20, 30))
        
        # Title
        title_text = self.title_font.render("RPG IA de fou malade", True, c.Colors.WHITE)
        title_rect = title_text.get_rect(center=(c.Screen.WIDTH // 2, 150))
        self.screen.blit(title_text, title_rect)
        
        # Mouse position
        mouse_pos = pygame.mouse.get_pos()

        # Draw buttons
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
