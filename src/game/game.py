import math
import sys
import pygame

from core.camera import Camera
import core.constants as c
from core.save import SaveSystem
from game.entities import Player
from game.items import Item
from game.world import World
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import get_llm_task_count
from llm.name_generator import NPCNameGenerator
from ui.context_window import ContextWindow
from ui.game_renderer import GameRenderer
from ui.loading_indicator import LoadingIndicator
from ui.inventory_menu import InventoryMenu


class Game:
    def __init__(self, screen, clock, save_system: SaveSystem):
        # Pygame
        self.screen = screen
        self.clock: pygame.time.Clock = clock
        self.camera = Camera()

        # UI
        self.small_font = pygame.font.SysFont("arial", 22)
        self.loading_indicator = LoadingIndicator()
        self.context_window = ContextWindow()
        self.window_active = False

        # Helper
        self.save_system = save_system
        self.world = World(self.save_system, self.context_window)
        self.game_renderer = GameRenderer(self.screen)

        # Player
        self.player = Player(self.save_system, self.save_system.load("coins", 0))
        
        # Inventory menu
        self.inventory_menu = InventoryMenu()
        self.inv_button_rect = pygame.Rect(10, 10, 120, 35)

        # Dialogue manager
        self.dialogue_manager = DialogueManager(self.world.items, self.player)
        self.npc_name_generator = NPCNameGenerator(self.save_system)

    def update_camera(self):
        """Center camera on player with proper offset"""
        self.camera.update_position(self.player.x, self.player.y)

    def handle_input(self):
        """Handle keyboard and mouse input"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            if self.context_window.handle_event(event):
                return True

            if self.inventory_menu.handle_event(event):
                return True
            
            if self.dialogue_manager.handle_event(event, self.npc_name_generator):
                return True
            
            if not self.window_active:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        if self.inv_button_rect.collidepoint(event.pos):
                            self.inventory_menu.toggle()

                        else:
                            self.player.start_attack()
                
                if event.type == pygame.KEYDOWN:
                    # Game controls
                    if event.key == pygame.K_e:
                        # First we pick item
                        item: Item = self.world.pickup_item(self.player)
                        if item is not None:
                            item.picked_up = True
                            self.player.inventory.append(item)
                        
                        # Then we talk if we did not pick item
                        else:                       
                            npc = self.world.talk_npc(self.player)
                            if npc is not None:
                                self.dialogue_manager.interact_with_npc(npc, self.npc_name_generator, self.world)

                    elif event.key == pygame.K_i:
                        self.inventory_menu.toggle()

        return True

    def save_data(self):
        self.save_system.update("name", self.npc_name_generator.get_name())
        self.save_system.save_all()

    def run(self):
        """Main game loop"""
        running = True
        last_save_time = pygame.time.get_ticks()
        
        while running:
            self.window_active = self.context_window.active or self.inventory_menu.active or self.dialogue_manager.active

            # Handle input
            running = self.handle_input()
            if not running:
                break
            
            # Update dialogue
            self.dialogue_manager.update()

            # Update loading indicator
            self.loading_indicator.update()
            
            if not self.window_active:
                # Update player movement
                self.player.move(self.camera, self.clock)
            
                # Update camera
                self.update_camera()
            
            # Draw everything
            self.game_renderer.draw_world(self.camera, self.world, self.player)
            self.game_renderer.draw_ui(self.player, self.loading_indicator, get_llm_task_count())
            self.dialogue_manager.draw(self.screen)
            self.inventory_menu.draw(self.screen, self.player)
            self.context_window.draw(self.screen)

            # Auto-save every 5 minutes
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
