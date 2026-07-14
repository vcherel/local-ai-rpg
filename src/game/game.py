from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import Camera
from core.particles import get_particles
from game.entities.items import rarity_color
from game.entities.player import Player
from game.loot import open_lootbox
from game.world import World
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import get_llm_task_count
from llm.name_generator import NPCNameGenerator
from ui.game_renderer import GameRenderer
from ui.menus.context_menu import ContextMenu
from ui.menus.game_over import run_game_over
from ui.menus.help_menu import HelpMenu
from ui.menus.inventory_menu import InventoryMenu
from ui.menus.pause_menu import PauseMenu
from ui.menus.quest_menu import QuestMenu
from ui.menus.shop_menu import ShopMenu
from ui.menus.stats_menu import StatsMenu
from ui.notification import ToastNotification

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
        self.shop_menu = ShopMenu(self.screen)
        self.stats_menu = StatsMenu(self.screen)
        self.help_menu = HelpMenu(self.screen)
        self.pause_menu = PauseMenu(self.screen)
        self.loot_notification = ToastNotification(self.screen)

        self.save_system = save_system
        self.world = World(self.save_system, self.context_window, self.loot_notification.show)
        self.game_renderer = GameRenderer(self.screen)

        self.player = Player(self.save_system, self.save_system.load("coins", 0))

        self.dialogue_manager = DialogueManager(self.screen, self.world.items, self.player)
        self.npc_name_generator = NPCNameGenerator(self.save_system)
        self.active_menu = False

        # When inside a building the player moves in that building's interior
        # coordinate space; the world simulation pauses until they step back out.
        self.interior = None
        self._interior_return_pos = None
        # Monsters that were actively chasing the player through the door; they keep
        # following inside instead of being left behind in the outdoor world.
        self.indoor_monsters = []

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

            if self.inventory_menu.handle_event(event, self.player):
                continue

            if self.shop_menu.handle_event(event):
                continue

            if self.dialogue_manager.handle_event(event, self.npc_name_generator):
                continue

            if self.quest_menu.handle_event(event, self.dialogue_manager.quest_system):
                continue

            if self.stats_menu.handle_event(event):
                continue

            if self.help_menu.handle_event(event):
                continue

            if self.pause_menu.handle_event(event):
                continue

            if not self.active_menu:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        if self.game_renderer.inv_button_rect.collidepoint(event.pos):
                            self.inventory_menu.toggle()

                        elif self.game_renderer.quest_button_rect.collidepoint(event.pos):
                            self.quest_menu.toggle()

                        elif self.game_renderer.stats_button_rect.collidepoint(event.pos):
                            self.stats_menu.toggle()

                        elif self.game_renderer.lore_button_rect.collidepoint(event.pos):
                            self._show_lore()

                        elif self.game_renderer.help_button_rect.collidepoint(event.pos):
                            self.help_menu.toggle()

                        elif self.game_renderer.pause_button_rect.collidepoint(event.pos):
                            self.pause_menu.toggle()

                        elif self.interior is None:
                            self.world.handle_attack(self.player, self.dialogue_manager.quest_system)

                        else:
                            self.world.handle_attack(
                                self.player, self.dialogue_manager.quest_system, monsters=self.indoor_monsters
                            )

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_e:
                        if self.interior is not None:
                            self._interior_interact()
                        else:
                            self._interact_with_world()

                    elif event.key == pygame.K_i:
                        self.inventory_menu.toggle()

                    elif event.key == pygame.K_q:
                        self.quest_menu.toggle()

                    elif event.key == pygame.K_c:
                        self.stats_menu.toggle()

                    elif event.key == pygame.K_l:
                        self._show_lore()

                    elif event.key == pygame.K_h:
                        self.help_menu.toggle()

                    elif event.key in (pygame.K_p, pygame.K_ESCAPE):
                        self.pause_menu.toggle()

        # The frame the dialogue opened is over; later keystrokes are real input.
        self.dialogue_manager.opened_this_frame = False

        if self.dialogue_manager.shop_requested and not self.dialogue_manager.active:
            npc = self.dialogue_manager.current_npc
            if npc is not None and npc.is_merchant:
                self.shop_menu.open(npc, self.player, self.world.items)
            self.dialogue_manager.shop_requested = False

        return True

    def _show_lore(self):
        if self.world.context:
            self.context_window.show(self.world.context)

    def _open_lootbox(self, lootbox: Item):
        self.world.items.remove(lootbox)

        coins, loot_item = open_lootbox(self.player.x, self.player.y, lootbox.rarity)
        self.player.add_coins(coins)

        message = f"Lootbox: +{coins} coins"
        if loot_item is not None:
            self.world.items.append(loot_item)
            self.player.inventory.append(loot_item)
            message += f" and a {loot_item.rarity} {loot_item.name}!"

        self.loot_notification.show(message, rarity_color(lootbox.rarity))
        play_sound("lootbox_open")

    def _interact_with_world(self):
        item: Item = self.world.pickup_item(self.player)
        if item is not None:
            item.picked_up = True
            if item.item_type == "lootbox":
                self._open_lootbox(item)
            else:
                self.player.inventory.append(item)
                play_sound("pickup")
            get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)
        else:
            npc = self.world.talk_npc(self.player)
            if npc is not None:
                self.player.stats.train("bartering", c.Stats.XP_PER_TALK_BARTERING)
                self.player.stats.train("persuasion", c.Stats.XP_PER_TALK)
                self.dialogue_manager.interact_with_npc(npc, self.npc_name_generator, self.world)

    def _enter_building(self, building):
        self._interior_return_pos = building.door_front()

        # Monsters that were actively chasing the player right up to the door follow inside.
        chase_range = c.World.DETECTION_RANGE + c.Player.SIZE // 2
        pursuers = [m for m in self.world.monsters if m.distance_to_point((self.player.x, self.player.y)) < chase_range]
        entry_x, entry_y = building.interior_entry_pos()
        for monster in pursuers:
            self.world.monsters.remove(monster)
            monster.x = entry_x + monster.target_offset[0]
            monster.y = entry_y + monster.target_offset[1]
        self.indoor_monsters = pursuers

        self.interior = building
        self.player.x, self.player.y = building.interior_entry_pos()

    def _check_building_entry(self):
        for building in self.world.buildings:
            zone = building.door_zone()
            if zone is not None and zone.collidepoint(self.player.x, self.player.y):
                self._enter_building(building)
                return

    def _check_interior_exit(self):
        if self.interior.interior_exit_zone().collidepoint(self.player.x, self.player.y):
            door_x, door_y = self._interior_return_pos
            for monster in self.indoor_monsters:
                monster.x = door_x + monster.target_offset[0]
                monster.y = door_y + monster.target_offset[1]
                self.world.monsters.append(monster)
            self.indoor_monsters = []

            self.player.x, self.player.y = self._interior_return_pos
            self.interior = None

    def _interior_interact(self):
        hit = self.interior.interactable_at(self.player.x, self.player.y)
        if hit is None:
            return
        kind, _rect = hit
        if kind == "chest":
            self._open_interior_chest()
        elif kind == "bed":
            self._sleep_in_bed()

    def _open_interior_chest(self):
        from game.entities.items import roll_rarity

        self.interior.looted = True
        rarity = roll_rarity()
        coins, loot_item = open_lootbox(self.player.x, self.player.y, rarity)
        self.player.add_coins(coins)

        message = f"Chest: +{coins} coins"
        if loot_item is not None:
            self.world.items.append(loot_item)
            self.player.inventory.append(loot_item)
            message += f" and a {loot_item.rarity} {loot_item.name}!"

        self.loot_notification.show(message, rarity_color(rarity))
        play_sound("lootbox_open")

    def _sleep_in_bed(self):
        if self.player.hp >= self.player.max_hp:
            self.loot_notification.show("You are already fully rested", c.Colors.WHITE)
            return
        if self.player.coins < c.Buildings.INN_SLEEP_COST:
            self.loot_notification.show("Not enough coins to rest here", c.Colors.RED)
            return
        self.player.add_coins(-c.Buildings.INN_SLEEP_COST)
        self.player.hp = self.player.max_hp
        self.loot_notification.show("You rest and recover fully", c.Colors.GREEN)
        play_sound("quest_complete")

    def save_data(self):
        self.save_system.update("name", self.npc_name_generator.get_name())
        # The player's live position is in interior space while inside a building;
        # persist the spot they will step back out to instead.
        player_state = self.player.to_dict()
        if self.interior is not None:
            player_state["x"], player_state["y"] = self._interior_return_pos
        self.save_system.update("player", player_state)
        self.player.save_stats()
        self.save_system.update("inventory", [item.id for item in self.player.inventory])

        world_state = self.world.serialize()
        monsters = world_state["monsters"]
        if self.interior is not None:
            # Indoor pursuers live in the building's interior coordinate space, not the
            # outdoor world; save them at the door they'd step back out to instead.
            door_x, door_y = self._interior_return_pos
            for monster in self.indoor_monsters:
                monster_state = monster.to_dict()
                monster_state["x"], monster_state["y"] = door_x, door_y
                monsters.append(monster_state)
        self.save_system.update("items", world_state["items"])
        self.save_system.update("npcs", world_state["npcs"])
        self.save_system.update("monsters", monsters)
        self.save_system.update("buildings", world_state["buildings"])

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
                or self.shop_menu.active
                or self.stats_menu.active
                or self.help_menu.active
                or self.pause_menu.active
            )

            running = self.handle_input()
            if not running:
                break

            # Skip world simulation and rendering while a menu is open to save computation
            if not self.active_menu:
                dt = self.clock.get_time()
                if self.interior is not None:
                    self.player.move(self.camera.get_pos(), dt, self.interior.interior_blocked)
                    for monster in self.indoor_monsters:
                        monster.move(self.player, dt, self.interior.interior_blocked)
                    self._check_interior_exit()
                else:
                    self.player.move(self.camera.get_pos(), dt, self.world.blocked)
                    self.world.update(self.player, dt, self.dialogue_manager.quest_system, self.npc_name_generator)
                    self._check_building_entry()
                self.update_camera()

                if self.interior is not None:
                    self.game_renderer.draw_interior(self.camera, self.interior, self.player, self.indoor_monsters)
                else:
                    self.game_renderer.draw_world(self.camera, self.world, self.player)
                self.game_renderer.draw_ui(
                    len(self.player.inventory),
                    self.player.coins,
                    len(self.dialogue_manager.quest_system.active_quests),
                    get_llm_task_count(),
                    self.player,
                )

            self.context_window.update()

            self.dialogue_manager.draw()
            if not self.active_menu:
                self.dialogue_manager.notification.draw()
                self.loot_notification.draw()
            self.inventory_menu.draw(self.player)
            self.quest_menu.draw(self.dialogue_manager.quest_system)
            self.shop_menu.draw()
            self.stats_menu.draw(self.player)
            self.help_menu.draw()
            self.pause_menu.draw()
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
                self.player.hp = self.player.max_hp
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
