import math
import pygame
from typing import List

import core.constants as c
from core.camera import Camera
from game.entities import Monster, Player, NPC
from game.items import Item
from game.world import World
from ui.loading_indicator import LoadingIndicator


class GameRenderer:
    def __init__(self, screen):
        self.screen = screen
        self.small_font = pygame.font.SysFont("arial", 22)
        self.inv_button_rect = pygame.Rect(10, 10, 120, 35)
    
    def draw_world(self, camera: Camera, world: World, player: Player):
        """Draw all world elements"""
        self.screen.fill(c.Colors.GREEN)
        
        # Floor details
        for (x, y, kind) in world.floor_details:
            rotated_x, rotated_y = camera.rotate_point(x, y)
            if kind == "stone":
                pygame.draw.circle(self.screen, (100, 100, 100), (rotated_x, rotated_y), 3)
            else:
                pygame.draw.circle(self.screen, (255, 0, 0), (rotated_x, rotated_y), 2)
        
        # NPCs
        for npc in world.npcs:
            npc.draw(self.screen, camera)

        # Monsters
        for monster in world.monsters:
            monster.draw(self.screen, camera)
        
        # Items
        for item in (i for i in world.items if not i.picked_up):
            item.draw(self.screen, camera)
        
        # Player
        player.draw(self.screen)
        
        # Off-screen indicators
        self.draw_offscreen_indicators(camera, world.items, world.npcs, player)
    
    def draw_ui(self, player, loading_indicator: LoadingIndicator, active_task_count):
        """Draw inventory button, coins, and loading indicators"""
        # Draw inventory button
        mouse_pos = pygame.mouse.get_pos()
        is_hovering = self.inv_button_rect.collidepoint(mouse_pos)
        
        button_color = c.Colors.BUTTON_HOVERED if is_hovering else c.Colors.BUTTON
        border_color = c.Colors.BORDER_HOVERED if is_hovering else c.Colors.BORDER
        pygame.draw.rect(self.screen, button_color, self.inv_button_rect)
        pygame.draw.rect(self.screen, border_color, self.inv_button_rect, 2)
        
        button_text = self.small_font.render("Inventaire", True, c.Colors.WHITE)
        text_x = self.inv_button_rect.x + (self.inv_button_rect.width - button_text.get_width()) // 2
        text_y = self.inv_button_rect.y + (self.inv_button_rect.height - button_text.get_height()) // 2
        self.screen.blit(button_text, (text_x, text_y))
        
        coins_text = f"Pièces: {player.coins}"
        objects_text = f"Objets: {len(player.inventory)}"
        coins_surface = self.small_font.render(coins_text, True, c.Colors.WHITE)
        objects_surface = self.small_font.render(objects_text, True, c.Colors.WHITE)
        self.screen.blit(coins_surface, (12, 55))
        self.screen.blit(objects_surface, (12, 90))
        
        if active_task_count > 0:
            loading_indicator.draw_task_indicator(self.screen, c.Screen.WIDTH - 30, 30, active_task_count)
    
    def draw_offscreen_indicators(self, camera: Camera, items: List[Item], npcs: List[NPC], player: Player):
        """Draw arrows pointing to off-screen items and NPCs with active quests."""
        margin = 30
        arrow_size = 32
        
        def draw_arrow(target_x, target_y, color):
            screen_x, screen_y = camera.rotate_point(target_x, target_y)
            
            if 0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT:
                return
            
            center_x = c.Screen.WIDTH // 2
            center_y = c.Screen.HEIGHT // 2
            dx = screen_x - center_x
            dy = screen_y - center_y
            distance = math.hypot(dx, dy)
            
            if distance == 0:
                return
            
            dx /= distance
            dy /= distance
            
            arrow_x = center_x + dx * (c.Screen.WIDTH // 2 - margin)
            arrow_y = center_y + dy * (c.Screen.HEIGHT // 2 - margin)
            arrow_x = max(margin, min(arrow_x, c.Screen.WIDTH - margin))
            arrow_y = max(margin, min(arrow_y, c.Screen.HEIGHT - margin))
            
            angle = math.atan2(dy, dx)
            arrow_points = [
                (arrow_size, 0),
                (-arrow_size // 2, -arrow_size // 2),
                (-arrow_size // 2, arrow_size // 2)
            ]
            
            rotated_points = []
            for px, py in arrow_points:
                rx = px * math.cos(angle) - py * math.sin(angle)
                ry = px * math.sin(angle) + py * math.cos(angle)
                rotated_points.append((arrow_x + rx, arrow_y + ry))
            
            arrow_surface = pygame.Surface((arrow_size * 3, arrow_size * 3), pygame.SRCALPHA)
            local_points = [
                (p[0] - arrow_x + arrow_size * 1.5, p[1] - arrow_y + arrow_size * 1.5)
                for p in rotated_points
            ]
            arrow_color = (*color, 120)
            pygame.draw.polygon(arrow_surface, arrow_color, local_points)
            pygame.draw.polygon(arrow_surface, (*c.Colors.BLACK, 150), local_points, 1)
            self.screen.blit(arrow_surface, (arrow_x - arrow_size * 1.5, arrow_y - arrow_size * 1.5))
        
        for item in items:
            if not item.picked_up:
                draw_arrow(item.x, item.y, item.color)
        
        for npc in npcs:
            if (npc.has_active_quest and npc.quest_item in player.inventory):
                draw_arrow(npc.x, npc.y, c.Colors.YELLOW)
