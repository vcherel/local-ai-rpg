import sys
import pygame

from entities import Player, Item
import core.constants as c

class InventoryMenu:
    def __init__(self):
        self.active = False
        self.font = pygame.font.SysFont("arial", 20)
        self.title_font = pygame.font.SysFont("arial", 32, bold=True)
        # Menu dimensions
        self.width = 600
        self.height = 500
        self.padding = 20
        # Grid settings
        self.grid_cols = 6
        self.grid_rows = 4
        self.cell_size = 70
        self.cell_padding = 10
        self.hovered_slot = None
        
    def toggle(self):
        self.active = not self.active
        
    def close(self):
        self.active = False
        self.hovered_slot = None
        
    def get_slot_at_mouse(self, mouse_x, mouse_y, menu_x, menu_y):
        """Returns the slot index at the given mouse position, or None"""
        # Convert mouse position to menu-relative coordinates
        relative_mouse_x = mouse_x - menu_x
        relative_mouse_y = mouse_y - menu_y
        
        grid_width = self.grid_cols * self.cell_size + (self.grid_cols - 1) * self.cell_padding
        grid_start_x = (self.width - grid_width) // 2
        grid_start_y = self.padding + 100
        
        if relative_mouse_x < grid_start_x or relative_mouse_y < grid_start_y:
            return None
            
        col = (relative_mouse_x - grid_start_x) // (self.cell_size + self.cell_padding)
        row = (relative_mouse_y - grid_start_y) // (self.cell_size + self.cell_padding)
        
        if col >= self.grid_cols or row >= self.grid_rows:
            return None
            
        # Check if mouse is actually inside the cell (not in padding)
        cell_x = grid_start_x + col * (self.cell_size + self.cell_padding)
        cell_y = grid_start_y + row * (self.cell_size + self.cell_padding)
        
        if (relative_mouse_x >= cell_x and relative_mouse_x < cell_x + self.cell_size and
            relative_mouse_y >= cell_y and relative_mouse_y < cell_y + self.cell_size):
            return row * self.grid_cols + col
        
        return None
        
    def draw(self, screen: pygame.Surface, player: Player):
        if not self.active:
            return
            
        screen_width = screen.get_width()
        screen_height = screen.get_height()
        
        # Calculate centered position
        menu_x = (screen_width - self.width) // 2
        menu_y = (screen_height - self.height) // 2
        
        # Draw semi-transparent background overlay
        overlay = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        screen.blit(overlay, (0, 0))
        
        # Draw menu background
        menu_surface = pygame.Surface((self.width, self.height))
        menu_surface.fill((50, 50, 50))
        pygame.draw.rect(menu_surface, c.Colors.WHITE, (0, 0, self.width, self.height), 3)
        
        # Draw title
        title = self.title_font.render("Inventaire", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        menu_surface.blit(title, (title_x, self.padding))
        
        # Draw coins
        coins_text = self.font.render(f"Pièces: {player.coins}", True, c.Colors.YELLOW)
        menu_surface.blit(coins_text, (self.padding, self.padding + 50))
        
        # Get mouse position
        mouse_pos = pygame.mouse.get_pos()
        self.hovered_slot = self.get_slot_at_mouse(mouse_pos[0], mouse_pos[1], menu_x, menu_y)
        
        # Group items by name and count them, keeping the item reference
        item_dict = {}
        for item in player.inventory:
            if item.name not in item_dict:
                item_dict[item.name] = {'count': 0, 'item': item}
            item_dict[item.name]['count'] += 1
        
        items_list = list(item_dict.values())
        
        # Draw inventory grid
        grid_width = self.grid_cols * self.cell_size + (self.grid_cols - 1) * self.cell_padding
        grid_start_x = (self.width - grid_width) // 2  # Center the grid horizontally
        grid_start_y = self.padding + 100
        
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                slot_index = row * self.grid_cols + col
                cell_x = grid_start_x + col * (self.cell_size + self.cell_padding)
                cell_y = grid_start_y + row * (self.cell_size + self.cell_padding)
                
                # Determine cell color based on hover
                if slot_index == self.hovered_slot and slot_index < len(items_list):
                    cell_color = (90, 90, 90)
                    border_color = c.Colors.YELLOW
                else:
                    cell_color = (70, 70, 70)
                    border_color = (100, 100, 100)
                
                # Draw cell background
                pygame.draw.rect(menu_surface, cell_color,
                               (cell_x, cell_y, self.cell_size, self.cell_size))
                pygame.draw.rect(menu_surface, border_color,
                               (cell_x, cell_y, self.cell_size, self.cell_size), 2)
                
                # Draw item if slot is occupied
                if slot_index < len(items_list):
                    item_data = items_list[slot_index]
                    item = item_data['item']
                    count = item_data['count']
                    
                    # Calculate center position for the icon
                    icon_center_x = cell_x + self.cell_size // 2
                    icon_center_y = cell_y + self.cell_size // 2
                    
                    # Draw item icon using the item's draw method with custom camera offset
                    icon_center_x = cell_x + self.cell_size // 2
                    icon_center_y = cell_y + self.cell_size // 2
                    item.draw(menu_surface, x=icon_center_x, y=icon_center_y)
                    
                    # Draw count if more than 1
                    if count > 1:
                        count_text = self.font.render(f"x{count}", True, c.Colors.WHITE)
                        count_bg = pygame.Surface((count_text.get_width() + 4, count_text.get_height() + 2), pygame.SRCALPHA)
                        count_bg.fill((0, 0, 0, 180))
                        menu_surface.blit(count_bg, (cell_x + self.cell_size - count_text.get_width() - 6, 
                                                     cell_y + self.cell_size - count_text.get_height() - 4))
                        menu_surface.blit(count_text, (cell_x + self.cell_size - count_text.get_width() - 4, 
                                                       cell_y + self.cell_size - count_text.get_height() - 2))
        
        # Draw tooltip for hovered item
        if self.hovered_slot is not None and self.hovered_slot < len(items_list):
            item_data = items_list[self.hovered_slot]
            item: Item = item_data['item']
            
            tooltip_text = item.name
            tooltip_surface = self.font.render(tooltip_text, True, c.Colors.WHITE)
            tooltip_width = tooltip_surface.get_width() + 20
            tooltip_height = tooltip_surface.get_height() + 10
            
            # Position tooltip near mouse but keep it in bounds
            tooltip_x = mouse_pos[0] - menu_x + 15
            tooltip_y = mouse_pos[1] - menu_y + 15
            
            # Keep tooltip within menu bounds
            if tooltip_x + tooltip_width > self.width - 10:
                tooltip_x = mouse_pos[0] - menu_x - tooltip_width - 15
            if tooltip_y + tooltip_height > self.height - 10:
                tooltip_y = mouse_pos[1] - menu_y - tooltip_height - 15
            
            # Draw tooltip background
            tooltip_bg = pygame.Surface((tooltip_width, tooltip_height), pygame.SRCALPHA)
            tooltip_bg.fill((0, 0, 0, 220))
            menu_surface.blit(tooltip_bg, (tooltip_x, tooltip_y))
            pygame.draw.rect(menu_surface, c.Colors.YELLOW, 
                           (tooltip_x, tooltip_y, tooltip_width, tooltip_height), 2)
            
            # Draw tooltip text
            menu_surface.blit(tooltip_surface, (tooltip_x + 10, tooltip_y + 5))
        
        # Draw close instruction
        close_text = self.font.render("Appuyez sur ECHAP pour fermer", True, (200, 200, 200))
        close_x = (self.width - close_text.get_width()) // 2
        menu_surface.blit(close_text, (close_x, self.height - self.padding - 25))
        
        # Blit menu to screen
        screen.blit(menu_surface, (menu_x, menu_y))

class MainMenu:
    def __init__(self, screen):
        self.screen = screen
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
            self.active = False
            return "new_game"
        elif self.continue_button.collidepoint(pos):
            # TODO
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

def run_main_menu(screen, clock):
    main_menu = MainMenu(screen)
    
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
                        pass  # TODO
        
        main_menu.draw()
        pygame.display.flip()
        clock.tick(60)
    
    return True
