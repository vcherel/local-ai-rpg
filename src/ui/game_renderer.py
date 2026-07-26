from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from game.entities.items import draw_shape_with_border, rarity_color
from ui import widgets
from ui.loading_indicator import LoadingIndicator

# HUD equipment strip: (slot key, caption, ghost glyph shown when empty).
_EQUIP_HUD_SLOTS = (
    ("melee_weapon", "Melee", "sword"),
    ("ranged_weapon", "Ranged", "sword"),
    ("armor", "Armor", "shield"),
    ("accessory", "Accessory", "gem"),
)

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.items import Item
    from game.entities.monsters import Monster
    from game.entities.npcs import NPC
    from game.entities.player import Player
    from game.entities.projectile import Projectile
    from game.world import World


class GameRenderer:
    # Everything below sits inside one permanent panel in the top left corner:
    # a row of icon buttons, then coin/item/quest counters, then equipped gear.
    HUD_PANEL_RECT = pygame.Rect(8, 8, 300, 170)
    HUD_ICON_SIZE = 40
    HUD_ICON_GAP = 8

    def __init__(self, screen):
        self.screen: pygame.Surface = screen

        icon_y = self.HUD_PANEL_RECT.y + 10
        icon_x = self.HUD_PANEL_RECT.x + 10
        step = self.HUD_ICON_SIZE + self.HUD_ICON_GAP
        self.inv_button_rect = pygame.Rect(icon_x, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE)
        self.quest_button_rect = pygame.Rect(icon_x + step, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE)
        self.stats_button_rect = pygame.Rect(icon_x + step * 2, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE)
        self.lore_button_rect = pygame.Rect(icon_x + step * 3, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE)
        self.help_button_rect = pygame.Rect(icon_x + step * 4, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE)
        self.pause_button_rect = pygame.Rect(icon_x + step * 5, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE)
        # (rect, icon glyph, tooltip label) for the icon dock row, in draw/hit-test order.
        self.dock_buttons = (
            (self.inv_button_rect, "bag", "Inventory (I)"),
            (self.quest_button_rect, "scroll", "Quests (Q)"),
            (self.stats_button_rect, "person", "Character (C)"),
            (self.lore_button_rect, "book", "Lore (L)"),
            (self.help_button_rect, "question", "Help (H)"),
            (self.pause_button_rect, "pause", "Pause (P)"),
        )

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

        get_decals().draw(self.screen, camera)

        for breakable in world.breakables:
            if self._on_screen(camera, breakable.x, breakable.y):
                breakable.draw(self.screen, camera)

        for npc in world.npcs:
            if self._on_screen(camera, npc.x, npc.y):
                npc.draw(self.screen, camera)

        for monster in world.monsters:
            if self._on_screen(camera, monster.x, monster.y):
                monster.draw(self.screen, camera)

        for boss in world.bosses:
            if self._on_screen(camera, boss.x, boss.y, margin=boss.kind.size + c.Boss.SLAM_RADIUS):
                boss.draw(self.screen, camera)

        for item in (i for i in world.items if not i.picked_up):
            if self._on_screen(camera, item.x, item.y):
                item.draw(self.screen, camera)

        for projectile in world.projectiles:
            projectile.draw(self.screen, camera)

        get_particles().draw(self.screen, camera)
        get_floating_text().draw(self.screen, camera)

        player.draw(self.screen)

        self.draw_offscreen_indicators(camera, world.items, world.npcs, player, world.bosses)
        self.draw_boss_bar(world, player)

    def draw_interior(
        self, camera: Camera, building, player: Player, monsters: List[Monster], projectiles: List[Projectile] = ()
    ):
        building.draw_interior(self.screen, camera, player)
        get_decals().draw(self.screen, camera)
        for monster in monsters:
            monster.draw(self.screen, camera)
        for projectile in projectiles:
            projectile.draw(self.screen, camera)
        get_particles().draw(self.screen, camera)
        get_floating_text().draw(self.screen, camera)
        player.draw(self.screen)

    def _draw_icon(self, kind: str, center: tuple, size: int, color: tuple):
        """A small flat glyph for a HUD icon button. `size` is roughly the icon's radius."""
        cx, cy = center
        r = size
        if kind == "bag":
            top_w, bot_w = r * 0.9, r * 1.3
            top_y, bot_y = cy - r * 0.3, cy + r * 0.9
            pygame.draw.polygon(
                self.screen,
                color,
                [(cx - top_w / 2, top_y), (cx + top_w / 2, top_y), (cx + bot_w / 2, bot_y), (cx - bot_w / 2, bot_y)],
                2,
            )
            pygame.draw.arc(self.screen, color, pygame.Rect(cx - r * 0.4, cy - r * 1.3, r * 0.8, r * 1.0), 3.4, 6.0, 2)
        elif kind == "scroll":
            rect = pygame.Rect(cx - r * 0.7, cy - r * 0.9, r * 1.4, r * 1.8)
            pygame.draw.rect(self.screen, color, rect, 2, border_radius=3)
            for i in range(3):
                ly = rect.top + rect.height * 0.32 + i * rect.height * 0.22
                pygame.draw.line(self.screen, color, (rect.left + 4, ly), (rect.right - 4, ly), 1)
        elif kind == "person":
            pygame.draw.circle(self.screen, color, (cx, cy - r * 0.5), r * 0.4, 2)
            pygame.draw.arc(
                self.screen, color, pygame.Rect(cx - r * 0.7, cy - r * 0.1, r * 1.4, r * 1.3), 3.14, 6.28, 2
            )
        elif kind == "book":
            rect = pygame.Rect(cx - r * 0.9, cy - r * 0.7, r * 1.8, r * 1.4)
            pygame.draw.rect(self.screen, color, rect, 2)
            pygame.draw.line(self.screen, color, (cx, rect.top), (cx, rect.bottom), 2)
        elif kind == "question":
            label = c.Fonts.button.render("?", True, color)
            self.screen.blit(label, label.get_rect(center=center))
        elif kind == "pause":
            bar_w, gap, h = max(2, int(r * 0.35)), r * 0.4, r * 1.4
            pygame.draw.rect(self.screen, color, pygame.Rect(cx - gap - bar_w, cy - h / 2, bar_w, h))
            pygame.draw.rect(self.screen, color, pygame.Rect(cx + gap, cy - h / 2, bar_w, h))
        elif kind == "coin":
            pygame.draw.circle(self.screen, color, center, r * 0.9, 2)
            label = c.Fonts.small.render("$", True, color)
            self.screen.blit(label, label.get_rect(center=center))

    def _draw_dock_button(self, rect: pygame.Rect, icon: str, tooltip: str, mouse_pos):
        hover = rect.collidepoint(mouse_pos)
        widgets.draw_button(self.screen, rect, "", c.Fonts.button, hovered=hover)
        self._draw_icon(icon, rect.center, rect.width * 0.32, c.Colors.WHITE)
        if hover:
            self._draw_tooltip(rect, tooltip)

    def _draw_tooltip(self, anchor: pygame.Rect, text: str):
        label = c.Fonts.small.render(text, True, c.Colors.WHITE)
        pad = 6
        box = pygame.Rect(anchor.left, anchor.bottom + 4, label.get_width() + pad * 2, label.get_height() + pad * 2)
        widgets.draw_panel(self.screen, box)
        self.screen.blit(label, (box.x + pad, box.y + pad))

    def _draw_stat_chip(self, x: int, y: int, icon: str, value: int) -> int:
        """Draw an icon + number pair at (x, y), returning the x position right after it."""
        icon_size = 9
        self._draw_icon(icon, (x + icon_size, y + icon_size), icon_size, c.Colors.MUTED)
        label = c.Fonts.text.render(str(value), True, c.Colors.WHITE)
        text_x = x + icon_size * 2 + 6
        self.screen.blit(label, (text_x, y + icon_size - label.get_height() // 2))
        return text_x + label.get_width() + 22

    def draw_ui(self, nb_items, nb_coins, nb_quests, llm_tasks, player: Player):
        active_task_count = len(llm_tasks)
        mouse_pos = pygame.mouse.get_pos()

        widgets.draw_panel(self.screen, self.HUD_PANEL_RECT)
        for rect, icon, tooltip in self.dock_buttons:
            self._draw_dock_button(rect, icon, tooltip, mouse_pos)

        stats_y = self.inv_button_rect.bottom + 10
        x = self.HUD_PANEL_RECT.x + 10
        x = self._draw_stat_chip(x, stats_y, "coin", nb_coins)
        x = self._draw_stat_chip(x, stats_y, "bag", nb_items)
        self._draw_stat_chip(x, stats_y, "scroll", nb_quests)

        self._draw_equipped(player, top=stats_y + 30)

        self.loading_indicator.update()
        if active_task_count > 0:
            self.loading_indicator.draw_task_indicator(active_task_count)
        else:
            # Nothing running: the icon is gone, so there's nothing left to reopen from.
            self.show_llm_tasks = False

        if self.show_llm_tasks:
            self._draw_llm_task_panel(llm_tasks)

    def _draw_equipped(self, player: Player, top: int):
        """A mini paper-doll on the HUD: one captioned slot per equip type."""
        slot = 46
        step = 70
        left = self.HUD_PANEL_RECT.x + 10
        for i, (item_type, caption, glyph) in enumerate(_EQUIP_HUD_SLOTS):
            item = player.equipped_item(item_type)
            rect = pygame.Rect(left + i * step, top, slot, slot)

            border = rarity_color(item.rarity) if item else c.Colors.SLOT_BORDER
            widgets.draw_slot(self.screen, rect, border_color=border)
            if item is not None:
                widgets.draw_item_scaled(self.screen, item, rect.centerx, rect.centery, 34)
            else:
                draw_shape_with_border(self.screen, glyph, rect.center, 15, (60, 60, 70), 2, (84, 84, 98))

            label = c.Fonts.small.render(caption, True, c.Colors.MUTED)
            self.screen.blit(label, (rect.centerx - label.get_width() // 2, rect.bottom + 3))

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

    def draw_boss_bar(self, world: World, player: Player):
        """A wide health bar pinned near the top of the screen for the nearest engaged boss."""
        active = [b for b in world.bosses if b.distance_to_point((player.x, player.y)) <= c.Boss.AGGRO_RANGE]
        if not active:
            return
        boss = min(active, key=lambda b: b.distance_to_point((player.x, player.y)))

        width, height = c.Boss.BAR_WIDTH, c.Boss.BAR_HEIGHT
        x = (c.Screen.WIDTH - width) // 2
        y = c.Boss.BAR_TOP
        fill_color = c.Colors.BOSS_BAR_ENRAGED if boss.enraged else c.Colors.BOSS_BAR
        ratio = max(boss.hp / boss.max_hp, 0)

        pygame.draw.rect(self.screen, c.Colors.MENU_BACKGROUND, (x - 3, y - 3, width + 6, height + 6))
        pygame.draw.rect(self.screen, (20, 20, 24), (x, y, width, height))
        pygame.draw.rect(self.screen, fill_color, (x, y, int(width * ratio), height))
        pygame.draw.rect(self.screen, c.Colors.BORDER, (x, y, width, height), 2)

        label = boss.display_name + ("  [ENRAGED]" if boss.enraged else "")
        name_surface = c.Fonts.button.render(label, True, c.Colors.WHITE)
        self.screen.blit(name_surface, ((c.Screen.WIDTH - name_surface.get_width()) // 2, y - 26))

    def draw_offscreen_indicators(self, camera: Camera, items: List[Item], npcs: List[NPC], player: Player, bosses=()):
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

        # Bosses are always worth pointing to, wherever they are.
        for boss in bosses:
            draw_arrow(boss.x, boss.y, c.Colors.BOSS_BAR_ENRAGED)

    def draw_fps(self, fps):
        fps_text = c.Fonts.small.render(f"FPS: {int(fps)}", True, c.Colors.MENU_BACKGROUND)
        self.screen.blit(fps_text, (self.screen.get_width() - 60, self.screen.get_height() - 20))
