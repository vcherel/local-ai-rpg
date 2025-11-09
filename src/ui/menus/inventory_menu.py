from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

import core.constants as c
from ui.menus.base_menu import BaseMenu

if TYPE_CHECKING:
    from game.entities.items import Item
    from game.entities.player import Player


class InventoryMenu(BaseMenu):
    """Inventoy Menu display"""

    def __init__(self, screen):
        super().__init__(screen, width=600, height=500)

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
        
    def handle_event(self, event):
        if not self.active:
            return False
        
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                self.close()
        
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_i:
                self.close()

            elif event.key == pygame.K_ESCAPE:
                self.close()

        return True

    def draw(self, player: Player):
        if not self.active:
            return
        
        # Calculate centered position
        menu_x, menu_y = self.get_centered_position()
        
        # Draw semi-transparent background overlay
        self.draw_overlay()
        
        # Draw menu background
        menu_surface = self.create_menu_surface()
        
        # Draw title
        title = c.Fonts.title.render("Inventaire", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        menu_surface.blit(title, (title_x, self.padding))
        
        # Draw coins
        coins_text = c.Fonts.text.render(f"Pièces: {player.coins}", True, c.Colors.YELLOW)
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
                    cell_color = c.Colors.BUTTON_HOVERED
                    border_color = c.Colors.BORDER_HOVERED
                else:
                    cell_color = c.Colors.BUTTON
                    border_color = c.Colors.BORDER
                
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
                        count_text = c.Fonts.text.render(f"x{count}", True, c.Colors.WHITE)
                        count_bg = pygame.Surface((count_text.get_width() + 4, count_text.get_height() + 2), pygame.SRCALPHA)
                        count_bg.fill(c.Colors.TRANSPARENT)
                        menu_surface.blit(count_bg, (cell_x + self.cell_size - count_text.get_width() - 6, 
                                                     cell_y + self.cell_size - count_text.get_height() - 4))
                        menu_surface.blit(count_text, (cell_x + self.cell_size - count_text.get_width() - 4, 
                                                       cell_y + self.cell_size - count_text.get_height() - 2))
        
        # Draw tooltip for hovered item
        if self.hovered_slot is not None and self.hovered_slot < len(items_list):
            item_data = items_list[self.hovered_slot]
            item: Item = item_data['item']
            
            tooltip_text = item.name
            tooltip_surface = c.Fonts.text.render(tooltip_text, True, c.Colors.WHITE)
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
            tooltip_bg.fill(c.Colors.TRANSPARENT)
            menu_surface.blit(tooltip_bg, (tooltip_x, tooltip_y))
            pygame.draw.rect(menu_surface, c.Colors.YELLOW, 
                           (tooltip_x, tooltip_y, tooltip_width, tooltip_height), 2)
            
            # Draw tooltip text
            menu_surface.blit(tooltip_surface, (tooltip_x + 10, tooltip_y + 5))
        
        # Blit menu to screen
        self.screen.blit(menu_surface, (menu_x, menu_y))
