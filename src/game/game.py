from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

from core.camera import Camera
from game.entities.player import Player
from game.world import World
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import get_llm_task_count
from llm.name_generator import NPCNameGenerator
from ui.context_window import ContextWindow
from ui.game_renderer import GameRenderer
from ui.inventory_menu import InventoryMenu
from ui.quest_menu import QuestMenu

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.items import Item


class Game:
    """Handle the game inputs, camera, data"""
    def __init__(self, screen, clock, save_system: SaveSystem):
        # Pygame
        self.screen = screen
        self.clock: pygame.time.Clock = clock
        self.camera = Camera()

        # Context window
        self.context_window = ContextWindow()
        self.window_active = False

        # Helper
        self.save_system = save_system
        self.world = World(self.save_system, self.context_window)
        self.game_renderer = GameRenderer(self.screen)  # TODO: do not pass screen

        # Player
        self.player = Player(self.save_system, self.save_system.load("coins", 0))
        
        # Inventory menu
        self.inventory_menu = InventoryMenu()
        self.inv_button_rect = pygame.Rect(10, 10, 120, 35)

        # Quest menu
        self.quest_menu = QuestMenu()
        self.quest_button_rect = pygame.Rect(140, 10, 120, 35)

        # Dialogue manager
        self.dialogue_manager = DialogueManager(self.world.items, self.player)
        self.npc_name_generator = NPCNameGenerator(self.save_system)

    def update_camera(self):
        """Center camera on player with proper offset"""
        self.camera.set_pos(self.player.get_pos())

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
            
            if self.quest_menu.handle_event(event, self.dialogue_manager.quest_system):
                return True
            
            if not self.window_active:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        # Open inventory
                        if self.inv_button_rect.collidepoint(event.pos):
                            self.inventory_menu.toggle()

                        # Open quest menu
                        elif self.quest_button_rect.collidepoint(event.pos):
                            self.quest_menu.toggle()

                        # Attack
                        else:
                            self.world.handle_attack(self.player)
                
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
                    
                    elif event.key == pygame.K_q:
                        self.quest_menu.toggle()

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

            running = self.handle_input()
            if not running:
                break
            
            # Move the world
            if not self.window_active:
                dt = self.clock.get_time()
                self.player.move(self.camera.get_pos(), dt)
                self.update_camera()
                self.world.update(self.player, dt)
            
            # Draw and update menus
            self.game_renderer.draw_world(self.camera, self.world, self.player)
            self.game_renderer.draw_ui(len(self.player.inventory), self.player.coins, get_llm_task_count())
            self.dialogue_manager.draw(self.screen)
            self.inventory_menu.draw(self.screen, self.player)
            self.quest_menu.draw(self.screen, self.dialogue_manager.quest_system)
            self.context_window.draw(self.screen)

            current_time = pygame.time.get_ticks()
            if current_time - last_save_time >= 300_000:
                self.save_data()
                last_save_time = current_time
                print("Game auto-saved.")

            if self.player.hp <= 0:
                self.save_data()
                return  # Exit game loop and return to main menu

            pygame.display.flip()
            self.clock.tick(60)

        self.save_data()
