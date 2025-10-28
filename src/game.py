import math
import random
import sys
import threading
from typing import List
import pygame

from core.camera import Camera
import core.constants as c
from core.save import SaveSystem
from core.utils import random_coordinates
from entities import NPC, Item, Player
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import generate_response_queued, get_llm_task_count
from llm.name_generator import NPCNameGenerator
from ui.context_window import ContextWindow
from ui.game_renderer import GameRenderer
from ui.loading_indicator import LoadingIndicator
from ui.inventory_menu import InventoryMenu


class Game:
    def __init__(self, screen, clock, save_system: SaveSystem):
        # Pygame
        self.screen = screen
        self.clock = clock
        self.camera = Camera()

        self.save_system = save_system
        self.game_renderer = GameRenderer(self.screen)

        # World items
        self.floor_details = [
            (*random_coordinates(), random.choice(["stone", "flower"]))
            for _ in range(c.Game.NB_DETAILS)
        ]
        
        # Game objects
        self.player = Player(self.save_system, self.save_system.load("coins", 0))
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
        self.context_window = ContextWindow(screen.get_width(), screen.get_height())

        # Context
        self.context = self.save_system.load("context", None)
        if self.context is None:
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            self.context_window.set_context(self.context)

        # Dialogue manager
        self.dialogue_manager = DialogueManager(self.items, self.player)
        self.npc_name_generator = NPCNameGenerator(self.save_system, get_context_callback=lambda: self.context)

    def _generate_context(self):
        system_prompt = (
            "Tu crées des mondes pour un RPG. "
            "Chaque monde doit contenir un détail original qui peut servir de point de départ pour des quêtes."
        )
        prompt = (
            "En une seule phrase très courte, décris un monde RPG avec un ou élément intéressant pour des quêtes."
        )
        self.context = generate_response_queued(prompt, system_prompt)
        self.save_system.update("context", self.context)
        self.context_window.set_context(self.context)

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

    def handle_input(self):
        """Handle keyboard and mouse input"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            if self.context_window.handle_event(event):
                continue
            
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
                    elif self.dialogue_manager.active:
                        self.dialogue_manager.close()
                    elif self.context_window.active:
                        self.context_window.close
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

            # Check if it is running
            if keys[pygame.K_LSHIFT]:
                self.player.is_running = True
            else:
                self.player.is_running = False

            # Move player
            if distance != 0:
                self.player.move(distance, self.camera.angle)

    def save_data(self):
        self.save_system.update("name", self.npc_name_generator.get_name(generate_again=False))
        self.save_system.save_all()

    def run(self):
        """Main game loop"""
        running = True
        last_save_time = pygame.time.get_ticks()
        
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
            self.game_renderer.draw_world(self.camera, self.floor_details, self.npcs, self.items, self.player)
            self.game_renderer.draw_ui(self.player, self.loading_indicator, get_llm_task_count())
            self.dialogue_manager.draw(self.screen)
            self.inventory_menu.draw(self.screen, self.player)
            self.context_window.draw(self.screen)

            # Auto-save every 5 minutes (300,000 ms)
            current_time = pygame.time.get_ticks()
            if current_time - last_save_time >= 300_000:
                self.save_data()
                last_save_time = current_time
                print("Game auto-saved.")
            
            pygame.display.flip()
            self.clock.tick(60)
        
        self.save_data()
        pygame.quit()
        sys.exit()