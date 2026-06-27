from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import Camera
from core.particles import get_particles
from game.entities.player import Player
from game.world import World
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import get_llm_task_count
from llm.name_generator import NPCNameGenerator
from ui.game_renderer import GameRenderer
from ui.menus.context_menu import ContextMenu
from ui.menus.game_over import run_game_over
from ui.menus.inventory_menu import InventoryMenu
from ui.menus.quest_menu import QuestMenu

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.items import Item


class Game:
    def __init__(self, screen, clock, save_system: SaveSystem):
        self.screen = screen
        self.clock: pygame.time.Clock = clock
        self.camera = Camera()

        self.context_window = ContextMenu(self.screen)
        self.inventory_menu = InventoryMenu(self.screen)
        self.quest_menu = QuestMenu(self.screen)

        self.save_system = save_system
        self.world = World(self.save_system, self.context_window)
        self.game_renderer = GameRenderer(self.screen)

        self.player = Player(self.save_system, self.save_system.load("coins", 0))

        self.dialogue_manager = DialogueManager(self.screen, self.world.items, self.player)
        self.npc_name_generator = NPCNameGenerator(self.save_system)
        self.active_menu = False

        self._restore_player_state()

    def _restore_player_state(self):
        """Relink the saved inventory and active quests to the world's reloaded items."""
        items_by_id = {item.id: item for item in self.world.items}

        for item_id in self.save_system.load("inventory", []):
            item = items_by_id.get(item_id)
            if item is not None:
                self.player.inventory.append(item)

        quest_system = self.dialogue_manager.quest_system
        for npc in self.world.npcs:
            if npc.has_active_quest:
                quest_system.active_quests.append(npc.quest)

    def update_camera(self):
        self.camera.set_pos(self.player.get_pos())

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            if self.context_window.handle_event(event):
                continue

            if self.inventory_menu.handle_event(event):
                continue

            if self.dialogue_manager.handle_event(event, self.npc_name_generator):
                continue

            if self.quest_menu.handle_event(event, self.dialogue_manager.quest_system):
                continue

            if not self.active_menu:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        if self.game_renderer.inv_button_rect.collidepoint(event.pos):
                            self.inventory_menu.toggle()

                        elif self.game_renderer.quest_button_rect.collidepoint(event.pos):
                            self.quest_menu.toggle()

                        else:
                            self.world.handle_attack(self.player, self.dialogue_manager.quest_system)

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_e:
                        item: Item = self.world.pickup_item(self.player)
                        if item is not None:
                            item.picked_up = True
                            self.player.inventory.append(item)
                            play_sound("pickup")
                            get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)
                        else:
                            npc = self.world.talk_npc(self.player)
                            if npc is not None:
                                self.dialogue_manager.interact_with_npc(npc, self.npc_name_generator, self.world)

                    elif event.key == pygame.K_i:
                        self.inventory_menu.toggle()

                    elif event.key == pygame.K_q:
                        self.quest_menu.toggle()

        # The frame the dialogue opened is over; later keystrokes are real input.
        self.dialogue_manager.opened_this_frame = False

        return True

    def save_data(self):
        self.save_system.update("name", self.npc_name_generator.get_name())
        self.save_system.update("player", self.player.to_dict())
        self.save_system.update("inventory", [item.id for item in self.player.inventory])

        world_state = self.world.serialize()
        self.save_system.update("items", world_state["items"])
        self.save_system.update("npcs", world_state["npcs"])
        self.save_system.update("monsters", world_state["monsters"])

        self.save_system.save_all()

    def run(self):
        running = True
        last_save_time = pygame.time.get_ticks()

        while running:
            self.active_menu = (
                self.context_window.active
                or self.dialogue_manager.active
                or self.quest_menu.active
                or self.inventory_menu.active
            )

            running = self.handle_input()
            if not running:
                break

            # Skip world simulation and rendering while a menu is open to save computation
            if not self.active_menu:
                dt = self.clock.get_time()
                self.player.move(self.camera.get_pos(), dt)
                self.update_camera()
                self.world.update(self.player, dt)

                self.game_renderer.draw_world(self.camera, self.world, self.player)
                self.game_renderer.draw_ui(len(self.player.inventory), self.player.coins, get_llm_task_count())

            self.dialogue_manager.draw()
            self.dialogue_manager.notification.draw()
            self.inventory_menu.draw(self.player)
            self.quest_menu.draw(self.dialogue_manager.quest_system)
            self.context_window.draw()

            if not self.active_menu:
                fps = self.clock.get_fps()
                self.game_renderer.draw_fps(fps)

            current_time = pygame.time.get_ticks()
            if current_time - last_save_time >= 300_000:
                self.save_data()
                last_save_time = current_time

            if self.player.hp <= 0:
                # Persist a recoverable state so "Continue" doesn't reload straight into game over
                self.player.hp = c.Player.HP
                self.save_data()
                run_game_over(self.screen, self.clock)
                return

            pygame.display.flip()

            # Increase fps when we are typing
            if self.dialogue_manager.active:
                self.clock.tick(180)
            else:
                self.clock.tick(60)

        self.save_data()
