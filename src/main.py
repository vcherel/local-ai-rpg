import pygame
import random
import math
import sys
from typing import List

import constants as c
from entities import Player, NPC, Item, get_npc_name_generator
from dialogue_manager import DialogueManager
from llm_request_queue import get_llm_task_count, init_llm_queue
from loading_indicator import LoadingIndicator
from menu import InventoryMenu

class Game:
    def __init__(self):
        self.screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT))
        self.clock = pygame.time.Clock()
        
        # World settings
        self.world_width = c.Screen.WIDTH * 2
        self.world_height = c.Screen.HEIGHT * 2
        
        # World items
        self.floor_details = [
            (random.randint(0, self.world_width), random.randint(0, self.world_height), 
             random.choice(["stone", "flower"])) 
            for _ in range(300)
        ]
        
        # Game objects
        self.player = Player(self.world_width // 2, self.world_height // 2)
        self.npcs: List[NPC] = []
        self.items: List[Item] = []
        
        # Spawn NPCs randomly
        for i in range(c.Game.NB_NPCS):
            x = random.randint(100, self.world_width - 100)
            y = random.randint(100, self.world_height - 100)
            self.npcs.append(NPC(x, y, i))
        
        # Dialogue manager
        self.dialogue_manager = DialogueManager(self.world_width, self.world_height)
        self.dialogue_manager.items_list = self.items
        self.dialogue_manager.player = self.player
        get_npc_name_generator() # Initialize the name generator
        
        # Inventory menu
        self.inventory_menu = InventoryMenu()
        self.inv_button_rect = pygame.Rect(10, 10, 120, 35)
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
        
        # UI
        self.small_font = pygame.font.SysFont("arial", 22)
        self.loading_indicator = LoadingIndicator()
    
    def update_camera(self):
        """Center camera on player"""
        self.camera_x = self.player.x - c.Screen.WIDTH // 2
        self.camera_y = self.player.y - c.Screen.HEIGHT // 2
        
        # Clamp camera to world bounds
        self.camera_x = max(0, min(self.camera_x, self.world_width - c.Screen.WIDTH))
        self.camera_y = max(0, min(self.camera_y, self.world_height - c.Screen.HEIGHT))
    
    def interact_with_nearby_npc(self):
        """Check for nearby NPCs and interact"""
        for npc in self.npcs:
            if npc.distance_to_player(self.player) < c.Game.INTERACTION_DISTANCE:
                self.dialogue_manager.interact_with_npc(npc)
                break  # Only interact with one NPC at a time
    
    def pickup_nearby_item(self):
        """Check for nearby items and pick them up"""
        for item in self.items:
            if not item.picked_up and item.distance_to_player(self.player) < c.Game.INTERACTION_DISTANCE:
                item.picked_up = True
                self.player.inventory.append(item.name)
                break
    
    def draw_ui(self):
        """Draw inventory button, coins, controls, and loading indicators"""
        # Draw inventory button
        mouse_pos = pygame.mouse.get_pos()
        is_hovering = self.inv_button_rect.collidepoint(mouse_pos)
        
        button_color = (80, 80, 80) if is_hovering else (60, 60, 60)
        pygame.draw.rect(self.screen, button_color, self.inv_button_rect)
        pygame.draw.rect(self.screen, c.Colors.WHITE, self.inv_button_rect, 2)
        
        # Draw button text
        button_text = self.small_font.render("Inventaire", True, c.Colors.WHITE)
        text_x = self.inv_button_rect.x + (self.inv_button_rect.width - button_text.get_width()) // 2
        text_y = self.inv_button_rect.y + (self.inv_button_rect.height - button_text.get_height()) // 2
        self.screen.blit(button_text, (text_x, text_y))
        
        # Draw quick info below button
        coins_text = f"Pièces: {self.player.coins}"
        objects_text = f"Objets: {len(self.player.inventory)}"

        coins_surface = self.small_font.render(coins_text, True, c.Colors.WHITE)
        objects_surface = self.small_font.render(objects_text, True, c.Colors.WHITE)

        self.screen.blit(coins_surface, (12, 55))
        self.screen.blit(objects_surface, (12, 90))
        
        # Draw controls
        controls = self.small_font.render("ZQSD : Déplacer | E : Parler/Ramasser | I : Inventaire | ECHAP : Fermer", True, c.Colors.WHITE)
        self.screen.blit(controls, (10, c.Screen.HEIGHT - 25))
        
        # Draw loading indicators (top right)
        indicator_x = c.Screen.WIDTH - 30
        indicator_y = 30
        
        # Background task indicator
        active_task_count = get_llm_task_count()
        if active_task_count > 0:
            self.loading_indicator.draw_task_indicator(self.screen, indicator_x, indicator_y, active_task_count)
    
    def draw_world(self):
        """Draw all world elements"""
        # Background
        self.screen.fill(c.Colors.GREEN)
        
        # Floor details
        for (x, y, kind) in self.floor_details:
            if kind == "stone":
                pygame.draw.circle(self.screen, (100, 100, 100), 
                                (x - self.camera_x, y - self.camera_y), 3)
            else:
                pygame.draw.circle(self.screen, (255, 0, 0), 
                                (x - self.camera_x, y - self.camera_y), 2)
        
        # World border
        pygame.draw.rect(self.screen, c.Colors.WHITE, 
                    (0 - self.camera_x, 0 - self.camera_y, 
                        self.world_width, self.world_height), 3)
        
        # NPCs
        for npc in self.npcs:
            npc.draw(self.screen, self.camera_x, self.camera_y)
        
        # Items
        for item in self.items:
            item.draw(self.screen, self.camera_x, self.camera_y)
        
        # Player
        self.player.draw(self.screen, self.camera_x, self.camera_y)
        
        # Off-screen item indicators
        self.draw_offscreen_indicators()

    def draw_offscreen_indicators(self):
        """Draw arrows pointing to off-screen items and NPCs with active quests."""
        margin = 30
        arrow_size = 32

        def draw_arrow(target_x, target_y, color):
            # Calculate position relative to camera
            screen_x = target_x - self.camera_x
            screen_y = target_y - self.camera_y

            # Check if target is off-screen
            if 0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT:
                return  # On-screen → no indicator

            # Calculate direction to target
            dx = target_x - (self.camera_x + c.Screen.WIDTH // 2)
            dy = target_y - (self.camera_y + c.Screen.HEIGHT // 2)

            distance = math.hypot(dx, dy)
            if distance == 0:
                return
            dx /= distance
            dy /= distance

            # Find arrow position near screen edge
            arrow_x = c.Screen.WIDTH // 2 + dx * (c.Screen.WIDTH // 2 - margin)
            arrow_y = c.Screen.HEIGHT // 2 + dy * (c.Screen.HEIGHT // 2 - margin)

            arrow_x = max(margin, min(arrow_x, c.Screen.WIDTH - margin))
            arrow_y = max(margin, min(arrow_y, c.Screen.HEIGHT - margin))

            # Calculate arrow rotation
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

            # Draw semi-transparent arrow
            arrow_surface = pygame.Surface((arrow_size * 3, arrow_size * 3), pygame.SRCALPHA)
            local_points = [
                (p[0] - arrow_x + arrow_size * 1.5, p[1] - arrow_y + arrow_size * 1.5)
                for p in rotated_points
            ]
            arrow_color = (*color, 120)
            pygame.draw.polygon(arrow_surface, arrow_color, local_points)
            pygame.draw.polygon(arrow_surface, (*c.Colors.BLACK, 150), local_points, 1)
            self.screen.blit(arrow_surface, (arrow_x - arrow_size * 1.5, arrow_y - arrow_size * 1.5))

        # --- Item indicators ---
        for item in self.items:
            if not item.picked_up:
                draw_arrow(item.x, item.y, item.color)

        # --- NPC indicators ---
        for npc in self.npcs:
            if (
                npc.has_active_quest
                and not npc.quest_complete
                and npc.quest_item_name in self.player.inventory
            ):
                # Yellow arrow (quest return indicator)
                draw_arrow(npc.x, npc.y, c.Colors.YELLOW)

    def handle_input(self):
        """Handle keyboard and mouse input"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    # Check if inventory button was clicked
                    if self.inv_button_rect.collidepoint(event.pos):
                        if not self.dialogue_manager.active:
                            self.inventory_menu.toggle()
            
            if event.type == pygame.KEYDOWN:
                # Chat text input when dialogue is active
                if self.dialogue_manager.active:
                    # Handle scrolling with arrow keys
                    if event.key == pygame.K_UP:
                        self.dialogue_manager.handle_scroll(1)  # Scroll up
                    elif event.key == pygame.K_DOWN:
                        self.dialogue_manager.handle_scroll(-1)  # Scroll down
                    else:
                        self.dialogue_manager.handle_text_input(event)
                
                # Game controls
                if event.key == pygame.K_e and not self.dialogue_manager.active and not self.inventory_menu.active:
                    self.interact_with_nearby_npc()
                    if not self.dialogue_manager.active:
                        self.pickup_nearby_item()
                
                if event.key == pygame.K_ESCAPE:
                    if self.inventory_menu.active:
                        self.inventory_menu.close()
                    else:
                        self.dialogue_manager.close()
        return True
    
    def update_player_movement(self):
        """Update player position based on input"""
        if not self.dialogue_manager.active and not self.inventory_menu.active:
            keys = pygame.key.get_pressed()
            dx = dy = 0
            
            if keys[pygame.K_z]:
                dy = -c.Game.PLAYER_SPEED
            if keys[pygame.K_s]:
                dy = c.Game.PLAYER_SPEED
            if keys[pygame.K_q]:
                dx = -c.Game.PLAYER_SPEED
            if keys[pygame.K_d]:
                dx = c.Game.PLAYER_SPEED
            
            self.player.move(dx, dy, self.world_width, self.world_height)
    
    def run(self):
        """Main game loop"""
        running = True
        
        while running:            
            # Handle input
            running = self.handle_input()
            if not running:
                break
            
            # Update dialogue
            self.dialogue_manager.update()

            # Update loading indicator
            self.loading_indicator.update()
            
            # Update player movement
            self.update_player_movement()
            
            # Update camera
            self.update_camera()
            
            # Draw everything
            self.draw_world()
            self.draw_ui()
            self.dialogue_manager.draw(self.screen)
            self.inventory_menu.draw(self.screen, self.player)
            
            pygame.display.flip()
            self.clock.tick(60)
        
        pygame.quit()
        sys.exit()

# Initialize LLM request queue
init_llm_queue()

# Initialize Pygame
pygame.init()

game = Game()
game.run()