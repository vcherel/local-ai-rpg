import threading
import pygame
import random
import math
import sys
from typing import List

import constants as c
from camera import Camera
from entities import Player, NPC, Item
from dialogue_manager import DialogueManager
from llm_request_queue import generate_response_queued, get_llm_queue, get_llm_task_count
from loading_indicator import LoadingIndicator
from menu import InventoryMenu
from name_generator import NPCNameGenerator
from utils import random_coordinates

class Game:
    def __init__(self):
        # Pygame
        self.screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT))
        self.clock = pygame.time.Clock()
        self.camera = Camera()
        
        # World items
        self.floor_details = [
            (*random_coordinates(), random.choice(["stone", "flower"]))
            for _ in range(c.Game.NB_DETAILS)
        ]
        
        # Game objects
        self.player = Player()
        self.npcs: List[NPC] = []
        self.items: List[Item] = []
        
        # Spawn NPCs randomly
        for i in range(c.Game.NB_NPCS):
            self.npcs.append(NPC(*random_coordinates(), i))
        
        # Inventory menu
        self.inventory_menu = InventoryMenu()
        self.inv_button_rect = pygame.Rect(10, 10, 120, 35)
        
        # UI
        self.small_font = pygame.font.SysFont("arial", 22)
        self.loading_indicator = LoadingIndicator()

        # Context
        self.context = None
        threading.Thread(target=self._generate_context, daemon=True).start()

        # Dialogue manager
        self.dialogue_manager = DialogueManager()
        self.dialogue_manager.items_list = self.items  # To spawn quest items
        self.dialogue_manager.player = self.player
        self.npc_name_generator = NPCNameGenerator(get_context_callback=lambda: self.context)

    def _generate_context(self):
        system_prompt = (
            "Tu crées des mondes pour un RPG. "
            "Chaque monde doit contenir un détail original qui peut servir de point de départ pour des quêtes."
        )
        prompt = (
            "En une seule phrase très courte, décris un monde RPG avec un ou élément intéressant pour des quêtes."
        )
        # self.context = generate_response_queued(prompt, system_prompt)
        self.context = "Dans le monde d'Aetheris, où les rêves deviennent réalité et s'effondrent aléatoirement chaque nuit, un cartographe de cauchemars est chargé de tracer une porte vers la source des mondes perdus."
        print("Context : ", self.context)

    def update_camera(self):
        """Center camera on player with proper offset"""
        self.camera.update_position(self.player.x, self.player.y)
    
    def interact_with_nearby_npc(self):
        """Check for nearby NPCs and interact"""
        for npc in self.npcs:
            if npc.distance_to_player(self.player) < c.Game.INTERACTION_DISTANCE:
                self.dialogue_manager.interact_with_npc(npc, self.npc_name_generator)
                break  # Only interact with one NPC at a time
    
    def pickup_nearby_item(self):
        """Check for nearby items and pick them up"""
        for item in self.items:
            if not item.picked_up and item.distance_to_player(self.player) < c.Game.INTERACTION_DISTANCE:
                item.picked_up = True
                self.player.inventory.append(item)
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
        controls = self.small_font.render("ZQSD : Déplacer | E : Parler/Ramasser", True, c.Colors.WHITE)
        self.screen.blit(controls, (10, c.Screen.HEIGHT - 25))
        
        # Draw loading indicators (top right)
        indicator_x = c.Screen.WIDTH - 30
        indicator_y = 30
        
        # Background task indicator
        active_task_count = get_llm_task_count()
        if active_task_count > 0:
            self.loading_indicator.draw_task_indicator(self.screen, indicator_x, indicator_y, active_task_count)
    
    def draw_world(self):
        """Draw all world elements with rotation"""        
        # Background
        self.screen.fill(c.Colors.GREEN)
        
        # Floor details
        for (x, y, kind) in self.floor_details:
            rotated_x, rotated_y = self.camera.rotate_point(x, y)
            
            if kind == "stone":
                pygame.draw.circle(self.screen, (100, 100, 100), (rotated_x, rotated_y), 3)
            else:
                pygame.draw.circle(self.screen, (255, 0, 0), (rotated_x, rotated_y), 2)
        
        # NPCs
        for npc in self.npcs:
            npc.draw(self.screen, self.camera)
        
        # Items
        for item in (i for i in self.items if not i.picked_up):
            item.draw(self.screen, self.camera)
        
        # Player
        self.player.draw(self.screen)
        
        # Off-screen item indicators
        self.draw_offscreen_indicators()

    def draw_offscreen_indicators(self):
        """Draw arrows pointing to off-screen items and NPCs with active quests."""
        margin = 30
        arrow_size = 32
        
        def draw_arrow(target_x, target_y, color):
            # Rotate target position to screen space
            screen_x, screen_y = self.camera.rotate_point(target_x, target_y)
            
            # Check if target is off-screen
            if 0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT:
                return  # On-screen → no indicator
            
            # Calculate direction to target in screen space
            center_x = c.Screen.WIDTH // 2
            center_y = c.Screen.HEIGHT // 2
            dx = screen_x - center_x
            dy = screen_y - center_y
            distance = math.hypot(dx, dy)
            
            if distance == 0:
                return
            
            dx /= distance
            dy /= distance
            
            # Find arrow position near screen edge
            arrow_x = center_x + dx * (c.Screen.WIDTH // 2 - margin)
            arrow_y = center_y + dy * (c.Screen.HEIGHT // 2 - margin)
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
        
        # Item indicators
        for item in self.items:
            if not item.picked_up:
                draw_arrow(item.x, item.y, item.color)
        
        # NPC indicators
        for npc in self.npcs:
            if (
                npc.has_active_quest
                and not npc.quest_complete
                and npc.quest_item in self.player.inventory
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
                        self.dialogue_manager.handle_text_input(event, self.context)
                
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
        """Update player position and camera based on keyboard"""
        if not self.dialogue_manager.active and not self.inventory_menu.active:
            keys = pygame.key.get_pressed()
            distance = 0

            # Player movement (forward/back relative to camera rotation)
            if keys[pygame.K_z]:
                distance += c.Game.PLAYER_SPEED
            if keys[pygame.K_s]:
                distance -= c.Game.PLAYER_SPEED / 2  # Backward is slower

            # Rotate camera using Q/D
            if keys[pygame.K_q]:
                self.camera.update_angle(c.Game.PLAYER_TURN_SPEED)
            if keys[pygame.K_d]:
                self.camera.update_angle(-c.Game.PLAYER_TURN_SPEED)

            # Move player
            if distance != 0:
                self.player.move(distance, self.camera.angle)
    
    def run(self):
        """Main game loop"""
        running = True
        
        while running:            
            # Handle input
            running = self.handle_input()
            if not running:
                break
            
            # Update dialogue
            self.dialogue_manager.update(self.context)

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

# Initialize Pygame
pygame.init()

# Initialize LLM queue
get_llm_queue()

game = Game()
game.run()