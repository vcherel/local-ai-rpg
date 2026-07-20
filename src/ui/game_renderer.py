from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.particles import get_particles
from ui import widgets
from ui.loading_indicator import LoadingIndicator

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.items import Item
    from game.entities.monsters import Monster
    from game.entities.npcs import NPC
    from game.entities.player import Player
    from game.entities.projectile import Projectile
    from game.world import World


class GameRenderer:
    def __init__(self, screen):
        self.screen: pygame.Surface = screen
        # Grouped left to right: player panels, world info, system controls,
        # with an extra gap between each group so the bar reads as clusters.
        self.inv_button_rect = pygame.Rect(10, 10, 120, 35)
        self.quest_button_rect = pygame.Rect(140, 10, 120, 35)
        self.stats_button_rect = pygame.Rect(270, 10, 120, 35)

        self.lore_button_rect = pygame.Rect(420, 10, 120, 35)

        self.help_button_rect = pygame.Rect(570, 10, 120, 35)
        self.pause_button_rect = pygame.Rect(700, 10, 120, 35)
        self.loading_indicator = LoadingIndicator(self.screen, c.Screen.WIDTH - 30, 30)
        # Toggled by clicking the loading indicator; lists the LLM's in-flight tasks.
        self.show_llm_tasks = False

    @staticmethod
    def _on_screen(camera: Camera, x, y, margin=60):
        return abs(x - camera.x) <= c.Screen.ORIGIN_X + margin and abs(y - camera.y) <= c.Screen.ORIGIN_Y + margin

    def draw_world(self, camera: Camera, world: World, player: Player):
        self.screen.fill(c.Colors.GREEN)

        for x, y, kind in world.floor_details:
            if not self._on_screen(camera, x, y, margin=5):
                continue
            screen_x, screen_y = camera.world_to_screen(x, y)
            if kind == "stone":
                pygame.draw.circle(self.screen, (100, 100, 100), (screen_x, screen_y), 3)
            else:
                pygame.draw.circle(self.screen, (255, 0, 0), (screen_x, screen_y), 2)

        for building in world.buildings:
            if self._on_screen(camera, building.x, building.y, margin=max(building.w, building.h)):
                building.draw(self.screen, camera)

        for npc in world.npcs:
            if self._on_screen(camera, npc.x, npc.y):
                npc.draw(self.screen, camera)

        for monster in world.monsters:
            if self._on_screen(camera, monster.x, monster.y):
                monster.draw(self.screen, camera)

        for item in (i for i in world.items if not i.picked_up):
            if self._on_screen(camera, item.x, item.y):
                item.draw(self.screen, camera)

        for projectile in world.projectiles:
            projectile.draw(self.screen, camera)

        get_particles().draw(self.screen, camera)

        player.draw(self.screen)

        self.draw_offscreen_indicators(camera, world.items, world.npcs, player)

    def draw_interior(
        self, camera: Camera, building, player: Player, monsters: List[Monster], projectiles: List[Projectile] = ()
    ):
        building.draw_interior(self.screen, camera, player)
        for monster in monsters:
            monster.draw(self.screen, camera)
        for projectile in projectiles:
            projectile.draw(self.screen, camera)
        get_particles().draw(self.screen, camera)
        player.draw(self.screen)

    def _draw_button(self, rect: pygame.Rect, label: str, mouse_pos):
        hover = rect.collidepoint(mouse_pos)
        widgets.draw_button(self.screen, rect, label, c.Fonts.button, hovered=hover)

    def draw_ui(self, nb_items, nb_coins, nb_quests, llm_tasks, player: Player):
        active_task_count = len(llm_tasks)
        mouse_pos = pygame.mouse.get_pos()
        self._draw_button(self.inv_button_rect, "Inventory (I)", mouse_pos)
        self._draw_button(self.quest_button_rect, "Quests (Q)", mouse_pos)
        self._draw_button(self.stats_button_rect, "Character (C)", mouse_pos)
        self._draw_button(self.lore_button_rect, "Lore (L)", mouse_pos)
        self._draw_button(self.help_button_rect, "Help (H)", mouse_pos)
        self._draw_button(self.pause_button_rect, "Pause (P)", mouse_pos)

        coins_text = f"Coins: {nb_coins}"
        objects_text = f"Items: {nb_items}"
        quests_text = f"Quests: {nb_quests}"
        coins_surface = c.Fonts.text.render(coins_text, True, c.Colors.WHITE)
        objects_surface = c.Fonts.text.render(objects_text, True, c.Colors.WHITE)
        quests_surface = c.Fonts.text.render(quests_text, True, c.Colors.WHITE)
        self.screen.blit(coins_surface, (12, 55))
        self.screen.blit(objects_surface, (12, 90))
        self.screen.blit(quests_surface, (12, 125))

        weapon = player.equipped_item("weapon")
        armor = player.equipped_item("armor")
        accessory = player.equipped_item("accessory")
        equipped_text = (
            f"Weapon: {weapon.name if weapon else '-'}  "
            f"Armor: {armor.name if armor else '-'}  "
            f"Accessory: {accessory.name if accessory else '-'}"
        )
        equipped_surface = c.Fonts.small.render(equipped_text, True, c.Colors.BORDER)
        self.screen.blit(equipped_surface, (12, 160))

        self.loading_indicator.update()
        if active_task_count > 0:
            self.loading_indicator.draw_task_indicator(active_task_count)
        else:
            # Nothing running: the icon is gone, so there's nothing left to reopen from.
            self.show_llm_tasks = False

        if self.show_llm_tasks:
            self._draw_llm_task_panel(llm_tasks)

    def _draw_llm_task_panel(self, llm_tasks):
        width = 240
        pad = 10
        row_h = 34
        header_h = 26
        height = header_h + pad + max(len(llm_tasks), 1) * row_h + pad
        right = c.Screen.WIDTH - 10
        top = self.loading_indicator.rect.bottom + 6
        panel = pygame.Rect(right - width, top, width, height)
        widgets.draw_panel(self.screen, panel)

        title = c.Fonts.button.render(f"LLM tasks ({len(llm_tasks)})", True, c.Colors.ACCENT)
        self.screen.blit(title, (panel.x + pad, panel.y + pad))

        y = panel.y + pad + header_h
        for task in llm_tasks:
            running = task["state"] == "running"
            bullet = "●" if running else "○"
            color = c.Colors.WHITE if running else c.Colors.BORDER
            label = c.Fonts.small.render(f"{bullet} {task['category']}", True, color)
            self.screen.blit(label, (panel.x + pad, y))

            status = f"running  {task['elapsed']:.1f}s" if running else "queued"
            status_surface = c.Fonts.small.render(status, True, c.Colors.BORDER)
            self.screen.blit(status_surface, (panel.x + pad + 16, y + 15))
            y += row_h

    def draw_offscreen_indicators(self, camera: Camera, items: List[Item], npcs: List[NPC], player: Player):
        margin = 30
        arrow_size = 32

        def draw_arrow(target_x, target_y, color):
            screen_x, screen_y = camera.world_to_screen(target_x, target_y)
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
            arrow_points = [(arrow_size, 0), (-arrow_size // 2, -arrow_size // 2), (-arrow_size // 2, arrow_size // 2)]

            rotated_points = []
            for px, py in arrow_points:
                rx = px * math.cos(angle) - py * math.sin(angle)
                ry = px * math.sin(angle) + py * math.cos(angle)
                rotated_points.append((arrow_x + rx, arrow_y + ry))

            arrow_surface = pygame.Surface((arrow_size * 3, arrow_size * 3), pygame.SRCALPHA)
            local_points = [
                (p[0] - arrow_x + arrow_size * 1.5, p[1] - arrow_y + arrow_size * 1.5) for p in rotated_points
            ]

            arrow_color = (*color, 120)
            pygame.draw.polygon(arrow_surface, arrow_color, local_points)
            pygame.draw.polygon(arrow_surface, (*c.Colors.BLACK, 150), local_points, 1)
            self.screen.blit(arrow_surface, (arrow_x - arrow_size * 1.5, arrow_y - arrow_size * 1.5))

        for item in items:
            if not item.picked_up:
                draw_arrow(item.x, item.y, item.color)

        for npc in npcs:
            if npc.has_active_quest and npc.quest.item in player.inventory:
                draw_arrow(npc.x, npc.y, c.Colors.YELLOW)

    def draw_fps(self, fps):
        fps_text = c.Fonts.small.render(f"FPS: {int(fps)}", True, c.Colors.MENU_BACKGROUND)
        self.screen.blit(fps_text, (self.screen.get_width() - 60, self.screen.get_height() - 20))
