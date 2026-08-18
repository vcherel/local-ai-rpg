from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from core.swing_arcs import get_swings
from game.entities.item_icons import draw_shape_with_border
from game.entities.items import POTION_EFFECT_LABELS, rarity_color
from ui import widgets
from ui.loading_indicator import LoadingIndicator
from ui.minimap import Minimap

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player
    from game.world import World


class GameRenderer:
    # Everything below sits inside one permanent panel in the top left corner:
    # a row of icon buttons, then coin/item/quest counters, then equipped gear, then the
    # weapon bar the number keys switch between. Kept as small as it can be read at: the
    # panel is drawn over the world and over anything the screen edge is trying to point
    # at, so every slot here costs the player a piece of the view.
    HUD_PANEL_RECT = pygame.Rect(8, 8, 284, 176)
    HUD_ICON_SIZE = 34
    HUD_ICON_GAP = 6
    # Equip and weapon slots. No captions under them: the ghost glyph says what an empty
    # slot takes, and the captions were what forced the row twice as wide as its icons.
    HUD_SLOT_SIZE = 38
    HUD_SLOT_STEP = 44

    # Potion quickbar, centred just above the player's health bar (drawn by Player.draw
    # at ORIGIN_Y + SIZE/2 + its health_bar_offset).
    QUICK_SLOT_SIZE = 52
    QUICK_SLOT_GAP = 8
    QUICK_BAR_BOTTOM = c.Screen.ORIGIN_Y + c.Player.SIZE // 2 + 360 - 12

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
            (self.quest_button_rect, "scroll", "Quests (J)"),
            (self.stats_button_rect, "person", "Character (C)"),
            (self.lore_button_rect, "book", "Lore (L)"),
            (self.help_button_rect, "question", "Help (H)"),
            (self.pause_button_rect, "pause", "Pause (P)"),
        )

        self.minimap = Minimap(self.screen)
        # Left of the minimap, which owns the top right corner now.
        self.loading_indicator = LoadingIndicator(self.screen, self.minimap.rect.left - 30, 30)
        # Toggled by clicking the loading indicator; lists the LLM's in-flight tasks.
        self.show_llm_tasks = False

    @staticmethod
    def _on_screen(camera: Camera, x, y, margin=60):
        return abs(x - camera.x) <= c.Screen.ORIGIN_X + margin and abs(y - camera.y) <= c.Screen.ORIGIN_Y + margin

    @staticmethod
    def _hidden_indoors(world: World, x, y, interior) -> bool:
        """True when (x, y) stands on a building's floor that isn't the one the player is in.
        That building still has its roof on, so whatever is inside it must not be drawn over
        the top of it."""
        building = world.building_at(x, y)
        return building is not None and building is not interior

    def draw_world(
        self, camera: Camera, world: World, player: Player, interior=None, interaction=None, quest_target=None
    ):
        """`interior` is the building (if any) the player is currently standing inside; that
        one building draws as a roofless cutaway instead of its normal solid block, while
        everything else, indoors or out, keeps drawing in this same pass around it.
        `interaction` is what the interact key would act on right now (Game.current_interaction),
        drawn as the one prompt on screen; `quest_target` is where the tracked quest points,
        the only thing that still gets an offscreen arrow."""
        # Underground the ground is the tunnel and there is nothing else: no sky, no
        # wilderness, no buildings, because none of it is generated where a tunnel is dug.
        # Everything that walks, flies or lies on the floor keeps drawing below exactly as
        # it does on the surface, which is the whole point of a tunnel being world space.
        if world.underground is not None:
            world.underground.draw(self.screen, camera)
            get_decals().draw(self.screen, camera)
            self._draw_entities(camera, world, player, interior, interaction, quest_target, underground=True)
            return

        self.screen.fill(c.Colors.GREEN)

        for x, y, kind in world.floor_details:
            if not self._on_screen(camera, x, y, margin=5):
                continue
            screen_x, screen_y = camera.world_to_screen(x, y)
            if kind == "stone":
                pygame.draw.circle(self.screen, (100, 100, 100), (screen_x, screen_y), 3)
            else:
                pygame.draw.circle(self.screen, (255, 0, 0), (screen_x, screen_y), 2)

        # Roads, ponds, grass and flowers: the ground itself, so they go under everything
        # standing on it (the props they came with are drawn further down, with the barrels).
        ground_margin = max(c.Scenery.POND_RADIUS[1], c.Scenery.PATCH_RADIUS[1])
        for item in world.scenery_ground_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + ground_margin):
            if self._on_screen(camera, item.x, item.y, margin=ground_margin):
                item.draw(self.screen, camera)

        # The plaza a village is built around, drawn under its buildings.
        for village in world.villages:
            if self._on_screen(camera, village.x, village.y, margin=c.Villages.PLAZA_RADIUS + 40):
                village.draw(self.screen, camera)

        for building in world.buildings_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + 500):
            if self._on_screen(camera, building.x, building.y, margin=max(building.w, building.h)):
                building.draw(self.screen, camera, player_inside=building is interior)

        get_decals().draw(self.screen, camera)

        if interaction is not None and interaction.kind in ("chest", "bed"):
            self._draw_witness_cones(camera, world, player)

        # Lying on the ground and under everything that walks over it: a trap is meant to be
        # caught sight of, not read off the top of whoever is about to step in it.
        for trap in world.traps:
            if self._on_screen(camera, trap.x, trap.y):
                trap.draw(self.screen, camera)

        for breakable in world.breakables:
            if self._on_screen(camera, breakable.x, breakable.y):
                breakable.draw(self.screen, camera)

        for item in world.scenery_props_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + 100):
            if self._on_screen(camera, item.x, item.y, margin=70):
                item.draw(self.screen, camera)

        for poi in world.pois:
            if self._on_screen(camera, poi.x, poi.y):
                poi.draw(self.screen, camera)

        self._draw_entities(camera, world, player, interior, interaction, quest_target)

    def _draw_entities(
        self, camera: Camera, world: World, player: Player, interior, interaction, quest_target, underground=False
    ):
        """Everything standing on whatever was drawn under it: the same pass indoors, outdoors
        and underground, since all three are the one world and the one set of entity lists."""

        def visible(x, y, margin=60) -> bool:
            return self._on_screen(camera, x, y, margin) and not self._hidden_indoors(world, x, y, interior)

        for critter in world.critters:
            if visible(critter.x, critter.y):
                critter.draw(self.screen, camera)

        for npc in world.npcs:
            if visible(npc.x, npc.y):
                npc.draw(self.screen, camera)

        for monster in world.monsters:
            if visible(monster.x, monster.y):
                monster.draw(self.screen, camera)

        for boss in world.bosses:
            if visible(boss.x, boss.y, margin=boss.kind.size + c.Boss.SLAM_RADIUS):
                boss.draw(self.screen, camera)

        for item in (i for i in world.items if not i.picked_up):
            if visible(item.x, item.y):
                item.draw(self.screen, camera)

        for projectile in world.projectiles:
            projectile.draw(self.screen, camera)

        # Under the particles and over the entities: the arc says how much ground the
        # swing covered, the particles say what it landed on.
        get_swings().draw(self.screen, camera)
        get_particles().draw(self.screen, camera)
        get_floating_text().draw(self.screen, camera)

        player.draw(self.screen)

        # Over everything alive and under the prompt: what is out past the lantern is not
        # seen at all, which is the tunnel's real difficulty and the reason to go back up.
        if underground:
            world.underground.draw_dark(self.screen, camera, player)

        if interaction is not None:
            self._draw_interaction_prompt(camera, interaction)
        self.draw_offscreen_indicators(camera, quest_target)
        self.draw_boss_bar(world, player)

    def _draw_witness_cones(self, camera: Camera, world: World, player: Player):
        """What every villager who could catch the player stealing can actually see, drawn on
        the ground while a chest or a bed is in reach.

        Only up while the player is stood over something that isn't theirs: the cone is the
        question "is anyone looking right now", and a street permanently full of wedges would
        be wallpaper. Red is the one that has the player in it. Radius and angle come from
        `World.witness_radius` and the same constant `NPC.sees` tests, so the picture cannot
        promise cover the rule doesn't give."""
        radius = world.witness_radius()
        half = math.radians(c.Crime.VIEW_CONE_DEG) / 2
        watchers = world.watchers_near(player.x, player.y)
        if not watchers:
            return

        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        for npc in watchers:
            seen = npc.sees(player.x, player.y, radius)
            facing = npc.orientation - math.pi / 2
            origin = camera.world_to_screen(npc.x, npc.y)
            steps = 14
            points = [origin]
            for step in range(steps + 1):
                angle = facing - half + (2 * half) * step / steps
                edge = (npc.x + math.cos(angle) * radius, npc.y + math.sin(angle) * radius)
                points.append(camera.world_to_screen(*edge))
            # Kept faint: several of these overlap on a busy street, and they are drawn on
            # the ground the player is trying to read, not over it.
            pygame.draw.polygon(overlay, (200, 70, 60, 38) if seen else (230, 225, 200, 16), points)
            pygame.draw.lines(overlay, (200, 70, 60, 90) if seen else (230, 225, 200, 40), True, points, 1)
        self.screen.blit(overlay, (0, 0))

    def _draw_interaction_prompt(self, camera: Camera, interaction):
        """The one prompt on screen, floating over whatever the interact key would act on.
        A merchant also gets its trade key on a second line underneath."""
        x, y = camera.world_to_screen(interaction.x, interaction.y)
        y -= 30
        bob = math.sin(pygame.time.get_ticks() / 260.0) * 3

        lines = [c.Fonts.small.render(interaction.label, True, c.Colors.WHITE)]
        if interaction.hint:
            lines.append(c.Fonts.small.render(interaction.hint, True, c.Colors.ACCENT))

        width = max(surface.get_width() for surface in lines) + 16
        height = sum(surface.get_height() for surface in lines) + 6 * len(lines)
        box = pygame.Rect(0, 0, width, height)
        box.midbottom = (round(x), round(y + bob))
        widgets.draw_panel(self.screen, box)

        line_y = box.y + 3
        for surface in lines:
            self.screen.blit(surface, (box.centerx - surface.get_width() // 2, line_y))
            line_y += surface.get_height() + 6

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

    def _draw_dock_button(self, rect: pygame.Rect, icon: str, mouse_pos) -> bool:
        """Draw one dock icon. Returns whether it's hovered, so the caller can draw its
        tooltip last: it hangs below the row, over the stat chips drawn after the loop."""
        hover = rect.collidepoint(mouse_pos)
        widgets.draw_button(self.screen, rect, "", c.Fonts.button, hovered=hover)
        self._draw_icon(icon, rect.center, rect.width * 0.32, c.Colors.WHITE)
        return hover

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

    def draw_ui(self, nb_items, nb_coins, nb_quests, llm_tasks, player: Player, world: World):
        active_task_count = len(llm_tasks)
        mouse_pos = pygame.mouse.get_pos()

        self.minimap.draw(world, player)

        widgets.draw_panel(self.screen, self.HUD_PANEL_RECT)
        hovered_dock = None
        for rect, icon, tooltip in self.dock_buttons:
            if self._draw_dock_button(rect, icon, mouse_pos):
                hovered_dock = (rect, tooltip)

        stats_y = self.inv_button_rect.bottom + 10
        x = self.HUD_PANEL_RECT.x + 10
        x = self._draw_stat_chip(x, stats_y, "coin", nb_coins)
        x = self._draw_stat_chip(x, stats_y, "bag", nb_items)
        self._draw_stat_chip(x, stats_y, "scroll", nb_quests)

        equipped_bottom = self._draw_equipped(player, top=stats_y + 28)
        self._draw_weapon_bar(player, top=equipped_bottom + 8)
        self._draw_potion_bar(player)
        self._draw_guard_bar(player)

        # Last, so the panel's own contents can't cover it.
        if hovered_dock is not None:
            self._draw_tooltip(*hovered_dock)

        self.loading_indicator.update()
        if active_task_count > 0:
            self.loading_indicator.draw_task_indicator(active_task_count)
        else:
            # Nothing running: the icon is gone, so there's nothing left to reopen from.
            self.show_llm_tasks = False

        if self.show_llm_tasks:
            self._draw_llm_task_panel(llm_tasks)

    def _quick_slot_rects(self) -> List[pygame.Rect]:
        step = self.QUICK_SLOT_SIZE + self.QUICK_SLOT_GAP
        count = c.Potions.QUICK_SLOTS
        total = count * self.QUICK_SLOT_SIZE + (count - 1) * self.QUICK_SLOT_GAP
        left = c.Screen.ORIGIN_X - total // 2
        top = self.QUICK_BAR_BOTTOM - self.QUICK_SLOT_SIZE
        return [pygame.Rect(left + i * step, top, self.QUICK_SLOT_SIZE, self.QUICK_SLOT_SIZE) for i in range(count)]

    def _draw_potion_bar(self, player: Player):
        """The potion quickbar above the health bar: one slot per quick key, with the
        live buff chips floating just over it."""
        potions = player.quick_potions()
        rects = self._quick_slot_rects()

        for i, rect in enumerate(rects):
            item = potions[i] if i < len(potions) else None
            border = rarity_color(item.rarity) if item else c.Colors.SLOT_BORDER
            widgets.draw_slot(self.screen, rect, border_color=border)

            if item is not None:
                widgets.draw_item_scaled(self.screen, item, rect.centerx + 2, rect.centery - 3, 32)
                if item.quantity > 1:
                    count = c.Fonts.small.render(f"x{item.quantity}", True, c.Colors.WHITE)
                    self.screen.blit(count, (rect.right - count.get_width() - 4, rect.bottom - count.get_height() - 2))
            else:
                draw_shape_with_border(self.screen, "flask", rect.center, 14, (60, 60, 70), 2, (84, 84, 98))

            key_label = c.Fonts.small.render(c.Potions.QUICK_KEYS[i].upper(), True, c.Colors.MUTED)
            self.screen.blit(key_label, (rect.x + 4, rect.y + 2))

        self._draw_buff_chips(player, bottom=rects[0].top - 6)

    def _draw_guard_bar(self, player: Player):
        """The shield's guard, drawn just under the health bar and only while a shield is
        carried. It brightens while the block is up and turns red once the guard breaks,
        so the player can see what holding block is costing them."""
        if not player.has_shield():
            return
        width, height = 400, 10
        rect = pygame.Rect(0, 0, width, height)
        rect.midtop = (c.Screen.ORIGIN_X, c.Screen.ORIGIN_Y + c.Player.SIZE // 2 + 360 + 30 + 6)

        broken = player.guard_broken()
        fill = (200, 70, 60) if broken else ((150, 210, 255) if player.blocking else (90, 130, 175))
        pygame.draw.rect(self.screen, c.Colors.SLOT_BG, rect)
        ratio = max(0.0, player.guard / c.Shield.GUARD_MAX)
        pygame.draw.rect(self.screen, fill, (rect.x, rect.y, round(rect.width * ratio), rect.height))
        pygame.draw.rect(self.screen, c.Colors.SLOT_BORDER, rect, 2)

        if broken:
            label = c.Fonts.small.render("Guard broken", True, (255, 150, 140))
            self.screen.blit(label, (rect.centerx - label.get_width() // 2, rect.bottom + 2))

    def _draw_buff_chips(self, player: Player, bottom: int):
        # (dot colour, rendered label) per chip: the potion buffs, then the post-death
        # weakness, which is a timed effect like the rest and shouldn't be invisible or
        # unexplained.
        chips = []
        for effect, remaining, _magnitude in player.active_buffs():
            text = f"{POTION_EFFECT_LABELS.get(effect, effect)} {int(remaining) + 1}s"
            chips.append((c.Potions.COLORS[effect], c.Fonts.small.render(text, True, c.Colors.WHITE)))

        weakened = player.weakness_remaining()
        if weakened > 0:
            # Named for what it does and carrying its worst number: "Shaken 12s" said
            # nothing, while this is three penalties at once.
            damage_loss = round((1 - c.Death.DEBUFF_DAMAGE_MULT) * 100)
            text = f"Weakened {int(weakened) + 1}s  -{damage_loss}% dmg"
            chips.append((c.Colors.RED, c.Fonts.small.render(text, True, c.Colors.WHITE)))

        if not chips:
            return

        pad = 8
        gap = 6
        dot_space = 16
        widths = [label.get_width() + pad * 2 + dot_space for _, label in chips]
        height = chips[0][1].get_height() + 8
        x = c.Screen.ORIGIN_X - (sum(widths) + gap * (len(widths) - 1)) // 2
        y = bottom - height

        for (color, label), width in zip(chips, widths):
            rect = pygame.Rect(x, y, width, height)
            widgets.draw_panel(self.screen, rect)
            pygame.draw.circle(self.screen, color, (rect.x + pad + 4, rect.centery), 5)
            self.screen.blit(label, (rect.x + pad + dot_space, rect.centery - label.get_height() // 2))
            x += width + gap

    def _draw_equipped(self, player: Player, top: int) -> int:
        """A mini paper-doll on the HUD: one slot per equip type. Returns the y it ends at,
        so what comes under it doesn't have to guess."""
        slot = self.HUD_SLOT_SIZE
        left = self.HUD_PANEL_RECT.x + 10
        for i, (item_type, _caption, glyph) in enumerate(widgets.EQUIP_SLOTS):
            item = player.equipped_item(item_type)
            rect = pygame.Rect(left + i * self.HUD_SLOT_STEP, top, slot, slot)

            border = rarity_color(item.rarity) if item else c.Colors.SLOT_BORDER
            widgets.draw_slot(self.screen, rect, border_color=border)
            if item is not None:
                widgets.draw_item_scaled(self.screen, item, rect.centerx, rect.centery, 28)
                if item.quantity > 1:
                    count = c.Fonts.small.render(str(item.quantity), True, c.Colors.WHITE)
                    self.screen.blit(count, (rect.right - count.get_width() - 2, rect.bottom - count.get_height()))
            else:
                draw_shape_with_border(self.screen, glyph, rect.center, 13, (60, 60, 70), 2, (84, 84, 98))
        return top + slot

    def _draw_weapon_bar(self, player: Player, top: int):
        """The number-key weapon bar. A gold border marks the two weapons currently in the
        melee and ranged slots, so the bar shows what a key would do and what it already did."""
        slot = self.HUD_SLOT_SIZE
        left = self.HUD_PANEL_RECT.x + 10
        live = {player.equipped_melee_weapon_id, player.equipped_ranged_weapon_id}

        for i, item in enumerate(player.weapon_bar_items()):
            rect = pygame.Rect(left + i * self.HUD_SLOT_STEP, top, slot, slot)
            active = item is not None and item.id in live
            border = c.Colors.ACCENT if active else (rarity_color(item.rarity) if item else c.Colors.SLOT_BORDER)
            widgets.draw_slot(self.screen, rect, border_color=border, border_w=3 if active else 2)

            if item is not None:
                widgets.draw_item_scaled(self.screen, item, rect.centerx, rect.centery, 28)
            else:
                draw_shape_with_border(self.screen, "sword", rect.center, 13, (60, 60, 70), 2, (84, 84, 98))

            key = c.Fonts.small.render(str(i + 1), True, c.Colors.ACCENT if active else c.Colors.MUTED)
            self.screen.blit(key, (rect.x + 4, rect.y + 2))

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

    def draw_offscreen_indicators(self, camera: Camera, target):
        """One arrow, for the tracked quest's target and nothing else. Pointing at every
        dropped item and every boss on the map turned the screen edge into noise; loot is
        found by looking at it now (Item.draw's ground glow), not by following an arrow."""
        if target is None:
            return

        screen_x, screen_y = camera.world_to_screen(target[0], target[1])
        if 0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT:
            return

        margin = 30
        arrow_size = 32
        center_x = c.Screen.WIDTH // 2
        center_y = c.Screen.HEIGHT // 2
        dx = screen_x - center_x
        dy = screen_y - center_y
        distance = math.hypot(dx, dy)
        if distance == 0:
            return

        dx /= distance
        dy /= distance
        arrow_x = max(margin, min(center_x + dx * (center_x - margin), c.Screen.WIDTH - margin))
        arrow_y = max(margin, min(center_y + dy * (center_y - margin), c.Screen.HEIGHT - margin))

        # The HUD panel owns the top left corner and is drawn after this, so an arrow
        # pointing that way would be painted over. The panel is in a corner, so the only
        # ways out are right and down; take whichever is the shorter move, which keeps the
        # arrow as close as it can be to the direction it is actually pointing.
        blocked = self.HUD_PANEL_RECT.inflate(arrow_size * 2, arrow_size * 2)
        if blocked.collidepoint(arrow_x, arrow_y):
            if blocked.right - arrow_x <= blocked.bottom - arrow_y:
                arrow_x = blocked.right
            else:
                arrow_y = blocked.bottom

        angle = math.atan2(dy, dx)
        arrow_points = [(arrow_size, 0), (-arrow_size // 2, -arrow_size // 2), (-arrow_size // 2, arrow_size // 2)]
        # Drawn onto its own surface, in that surface's coordinates, so the polygon can be
        # blitted with an alpha the screen's own draw calls wouldn't give it.
        local_points = [
            (
                px * math.cos(angle) - py * math.sin(angle) + arrow_size * 1.5,
                px * math.sin(angle) + py * math.cos(angle) + arrow_size * 1.5,
            )
            for px, py in arrow_points
        ]

        arrow_surface = pygame.Surface((arrow_size * 3, arrow_size * 3), pygame.SRCALPHA)
        pygame.draw.polygon(arrow_surface, (*c.Colors.YELLOW, 120), local_points)
        pygame.draw.polygon(arrow_surface, (*c.Colors.BLACK, 150), local_points, 1)
        self.screen.blit(arrow_surface, (arrow_x - arrow_size * 1.5, arrow_y - arrow_size * 1.5))

    def draw_fps(self, fps):
        fps_text = c.Fonts.small.render(f"FPS: {int(fps)}", True, c.Colors.MENU_BACKGROUND)
        self.screen.blit(fps_text, (self.screen.get_width() - 60, self.screen.get_height() - 20))
