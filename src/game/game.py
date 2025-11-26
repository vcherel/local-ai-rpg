from __future__ import annotations

import pygame
from typing import TYPE_CHECKING

from core.camera import Camera
from game.entities.player import Player
from game.world import World
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import get_llm_task_count
from llm.name_generator import NPCNameGenerator
from ui.menus.context_menu import ContextMenu
from ui.game_renderer import GameRenderer
from ui.menus.inventory_menu import InventoryMenu
from ui.menus.quest_menu import QuestMenu

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
        self.context_window = ContextMenu(self.screen)
        self.inventory_menu = InventoryMenu(self.screen)
        self.quest_menu = QuestMenu(self.screen)

        # Helper
        self.save_system = save_system
        self.world = World(self.save_system, self.context_window)
        self.game_renderer = GameRenderer(self.screen)

        # Player
        self.player = Player(self.save_system, self.save_system.load("coins", 0))

        # Dialogue manager
        self.dialogue_manager = DialogueManager(self.screen, self.world.items, self.player)
        self.npc_name_generator = NPCNameGenerator(self.save_system)
        self.active_menu = False  # To know if one of the window is active

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
            
            if not self.active_menu:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        # Open inventory
                        if self.game_renderer.inv_button_rect.collidepoint(event.pos):
                            self.inventory_menu.toggle()

                        # Open quest menu
                        elif self.game_renderer.quest_button_rect.collidepoint(event.pos):
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
            self.active_menu = self.context_window.active or self.dialogue_manager.active or  self.quest_menu.active or self.inventory_menu.active

            running = self.handle_input()
            if not running:
                break
            
            # Move the world
            if not self.active_menu:
                dt = self.clock.get_time()
                self.player.move(self.camera.get_pos(), dt)
                self.update_camera()
                self.world.update(self.player, dt)

            # We want the least amount of computations possible when dialogue manager is opened
            if not self.dialogue_manager.active:
                self.game_renderer.draw_world(self.camera, self.world, self.player)
                self.game_renderer.draw_ui(len(self.player.inventory), self.player.coins, get_llm_task_count())
            
            # Draw and update menus
            self.dialogue_manager.draw()
            self.dialogue_manager.notification.draw()
            self.inventory_menu.draw(self.player)
            self.quest_menu.draw(self.dialogue_manager.quest_system)
            self.context_window.draw()

            # Show FPS
            if not self.active_menu:
                fps = self.clock.get_fps()
                self.game_renderer.draw_fps(fps) 

            current_time = pygame.time.get_ticks()
            if current_time - last_save_time >= 300_000:
                self.save_data()
                last_save_time = current_time
                print("Game auto-saved.")

            if self.player.hp <= 0:
                self.save_data()
                return  # Exit game loop and return to main menu

            pygame.display.flip()

            # Increase fps when we are typing
            if self.dialogue_manager.active:
                self.clock.tick(180)
            else:
                self.clock.tick(60)

        self.save_data()
