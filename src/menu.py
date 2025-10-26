import pygame

import constants as c

class InventoryMenu:
    def __init__(self):
        self.active = False
        self.font = pygame.font.SysFont("arial", 24)
        self.title_font = pygame.font.SysFont("arial", 32, bold=True)
        
        # Menu dimensions
        self.width = 500
        self.height = 400
        self.padding = 20
        
    def toggle(self):
        self.active = not self.active
    
    def close(self):
        self.active = False
    
    def draw(self, screen: pygame.Surface, player):
        if not self.active:
            return
        
        screen_width = screen.get_width()
        screen_height = screen.get_height()
        
        # Calculate centered position
        x = (screen_width - self.width) // 2
        y = (screen_height - self.height) // 2
        
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
        
        # Draw inventory items
        items_y = self.padding + 100
        
        if not player.inventory:
            empty_text = self.font.render("Inventaire vide", True, (150, 150, 150))
            empty_x = (self.width - empty_text.get_width()) // 2
            menu_surface.blit(empty_text, (empty_x, items_y + 30))
        else:
            # Group items by name and count them
            item_counts = {}
            for item in player.inventory:
                item_counts[item] = item_counts.get(item, 0) + 1
            
            # Draw each unique item with count
            for i, (item_name, count) in enumerate(item_counts.items()):
                item_y = items_y + i * 35
                
                # Draw item box
                box_height = 30
                pygame.draw.rect(menu_surface, (70, 70, 70), 
                               (self.padding, item_y, self.width - self.padding * 2, box_height))
                pygame.draw.rect(menu_surface, c.Colors.WHITE, 
                               (self.padding, item_y, self.width - self.padding * 2, box_height), 2)
                
                # Draw item text
                if count > 1:
                    item_text = self.font.render(f"{item_name} x{count}", True, c.Colors.WHITE)
                else:
                    item_text = self.font.render(item_name, True, c.Colors.WHITE)
                
                menu_surface.blit(item_text, (self.padding + 10, item_y + 3))
        
        # Draw close instruction
        close_text = self.font.render("Appuyez sur ECHAP pour fermer", True, (200, 200, 200))
        close_x = (self.width - close_text.get_width()) // 2
        menu_surface.blit(close_text, (close_x, self.height - self.padding - 30))
        
        # Blit menu to screen
        screen.blit(menu_surface, (x, y))