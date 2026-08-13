from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

import pygame

import core.constants as c
from game.entities.items import (
    ACCESSORY_FLAVOR_LABELS,
    affix_label,
    base_value,
    draw_shape_with_border,
    potion_description,
    rarity_color,
)
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

if TYPE_CHECKING:
    from game.entities.items import Item
    from game.entities.player import Player


RARE_GLOW = {"rare", "epic", "legendary"}


class InventoryMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=1000, height=640)
        self.header_height = HEADER_HEIGHT

        self.cell_size = 76
        self.cell_padding = 12
        self.paperdoll_width = 240
        self.footer_height = 44

        self.scroll_row = 0
        self.hovered_slot: Optional[int] = None
        self.hovered_equip: Optional[str] = None

    def close(self):
        self.active = False
        self.hovered_slot = None
        self.hovered_equip = None
        self.scroll_row = 0

    def _grouped_items(self, player: Player) -> list[dict]:
        item_dict = {}
        for item in player.inventory:
            # Effects and flavour distinguish otherwise-identical items, so they don't merge in the grid.
            key = (
                item.name,
                item.rarity,
                item.bonus,
                item.accessory_flavor,
                item.potion_effect,
                tuple(sorted(item.affixes.items())),
            )
            if key not in item_dict:
                item_dict[key] = {"count": 0, "item": item}
            item_dict[key]["count"] += item.quantity
        return list(item_dict.values())

    # --- geometry -------------------------------------------------------------
    # width/height are fixed, so draw and hit-testing share the same layout.

    def _grid_geom(self) -> dict:
        top = self.content_top
        grid_x0 = self.padding + self.paperdoll_width + 24
        area_w = self.width - grid_x0 - self.padding
        area_h = self.height - top - self.footer_height

        step = self.cell_size + self.cell_padding
        cols = max(1, (area_w + self.cell_padding) // step)
        rows = max(1, (area_h + self.cell_padding) // step)

        grid_w = cols * self.cell_size + (cols - 1) * self.cell_padding
        start_x = grid_x0 + (area_w - grid_w) // 2
        return {"cols": cols, "rows": rows, "start_x": start_x, "start_y": top, "step": step}

    def _paperdoll_rects(self) -> list[tuple[str, str, str, pygame.Rect]]:
        """(item_type, label, glyph, slot_rect) for each equip slot, laid out as a 2x2 grid."""
        slot = 100
        label_h = 24
        gap_x = 20
        gap_y = 22
        cols = 2
        rows = math.ceil(len(widgets.EQUIP_SLOTS) / cols)
        block_h = label_h + slot

        grid_w = cols * slot + (cols - 1) * gap_x
        grid_h = rows * block_h + (rows - 1) * gap_y

        area_h = self.height - self.content_top - self.footer_height
        start_y = self.content_top + max(0, (area_h - grid_h) // 2)
        start_x = self.padding + (self.paperdoll_width - grid_w) // 2

        rects = []
        for i, (item_type, label, glyph) in enumerate(widgets.EQUIP_SLOTS):
            col, row = i % cols, i // cols
            x = start_x + col * (slot + gap_x)
            y = start_y + row * (block_h + gap_y)
            rect = pygame.Rect(x, y + label_h, slot, slot)
            rects.append((item_type, label, glyph, rect))
        return rects

    def _slot_at(self, rel_x: int, rel_y: int, item_count: int) -> Optional[int]:
        g = self._grid_geom()
        col = (rel_x - g["start_x"]) // g["step"]
        row = (rel_y - g["start_y"]) // g["step"]
        if col < 0 or row < 0 or col >= g["cols"] or row >= g["rows"]:
            return None
        cell_x = g["start_x"] + col * g["step"]
        cell_y = g["start_y"] + row * g["step"]
        if not (cell_x <= rel_x < cell_x + self.cell_size and cell_y <= rel_y < cell_y + self.cell_size):
            return None
        index = (row + self.scroll_row) * g["cols"] + col
        return index if index < item_count else None

    def _equip_at(self, rel_x: int, rel_y: int) -> Optional[str]:
        for item_type, _label, _glyph, rect in self._paperdoll_rects():
            if rect.collidepoint(rel_x, rel_y):
                return item_type
        return None

    def _max_scroll(self, item_count: int) -> int:
        g = self._grid_geom()
        total_rows = math.ceil(item_count / g["cols"]) if item_count else 0
        return max(0, total_rows - g["rows"])

    # --- events ---------------------------------------------------------------

    def handle_event(self, event, player: Player):
        if not self.active:
            return False

        items_list = self._grouped_items(player)
        menu_x, menu_y = self.get_centered_position()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            rel_x, rel_y = event.pos[0] - menu_x, event.pos[1] - menu_y
            slot = self._slot_at(rel_x, rel_y, len(items_list))
            if slot is not None:
                item = items_list[slot]["item"]
                if item.item_type == "potion":
                    player.use_potion(item)
                else:
                    player.toggle_equip(item)
                return True
            equip_type = self._equip_at(rel_x, rel_y)
            if equip_type is not None:
                equipped = player.equipped_item(equip_type)
                if equipped is not None:
                    player.toggle_equip(equipped)
                return True

        elif event.type == pygame.MOUSEWHEEL:
            self.scroll_row = max(0, min(self._max_scroll(len(items_list)), self.scroll_row - event.y))

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_i, pygame.K_ESCAPE):
                self.close()
            elif event.key == pygame.K_UP:
                self.scroll_row = max(0, self.scroll_row - 1)
            elif event.key == pygame.K_DOWN:
                self.scroll_row = min(self._max_scroll(len(items_list)), self.scroll_row + 1)

        return True

    # --- drawing --------------------------------------------------------------

    def draw(self, player: Player):
        if not self.active:
            return

        menu_x, menu_y = self.get_centered_position()
        self.draw_overlay()
        surface = self.create_menu_surface("Inventory")

        coins = c.Fonts.text.render(f"{player.coins} coins", True, c.Colors.ACCENT)
        surface.blit(coins, (self.width - self.padding - coins.get_width(), (HEADER_HEIGHT - coins.get_height()) // 2))

        items_list = self._grouped_items(player)
        self.scroll_row = min(self.scroll_row, self._max_scroll(len(items_list)))
        equipped_ids = set(player.equipped_ids().values())

        mouse_pos = pygame.mouse.get_pos()
        rel_x, rel_y = mouse_pos[0] - menu_x, mouse_pos[1] - menu_y
        self.hovered_slot = self._slot_at(rel_x, rel_y, len(items_list))
        self.hovered_equip = self._equip_at(rel_x, rel_y)

        self._draw_paperdoll(surface, player)
        self._draw_grid(surface, items_list, equipped_ids)

        tooltip_item = None
        if self.hovered_slot is not None:
            tooltip_item = items_list[self.hovered_slot]["item"]
        elif self.hovered_equip is not None:
            tooltip_item = player.equipped_item(self.hovered_equip)

        self.draw_hint(surface, "Click to equip, unequip or drink. Scroll for more. ESC or I to close")
        self.blit_panel(surface)

        # Drawn on the screen after the panel, not onto it: a long tooltip near an edge
        # would otherwise be clipped at the panel border instead of overhanging it.
        if tooltip_item is not None:
            self._draw_tooltip(tooltip_item, mouse_pos, tooltip_item.id in equipped_ids)

    def _draw_paperdoll(self, surface, player: Player):
        header = c.Fonts.heading.render("Equipped", True, c.Colors.MUTED)
        first_rect = self._paperdoll_rects()[0][3]
        surface.blit(header, (self.padding, first_rect.y - 24 - header.get_height() - 6))

        for item_type, label, glyph, rect in self._paperdoll_rects():
            item = player.equipped_item(item_type)
            hovered = self.hovered_equip == item_type

            label_surf = c.Fonts.small.render(label, True, c.Colors.MUTED)
            surface.blit(label_surf, (rect.centerx - label_surf.get_width() // 2, rect.y - 22))

            border = c.Colors.ACCENT if item else c.Colors.SLOT_BORDER
            widgets.draw_slot(surface, rect, hovered=hovered, border_color=border)

            if item is not None:
                widgets.draw_item_scaled(surface, item, rect.centerx, rect.centery - 6, 58)
                name = c.Fonts.small.render(item.name, True, rarity_color(item.rarity))
                name = self._fit(name, item.name, rect.width - 8, rarity_color(item.rarity))
                surface.blit(name, (rect.centerx - name.get_width() // 2, rect.bottom - 20))
            else:
                draw_shape_with_border(surface, glyph, rect.center, 24, (66, 66, 76), 2, (90, 90, 104))

    def _draw_grid(self, surface, items_list, equipped_ids):
        g = self._grid_geom()
        for row in range(g["rows"]):
            for col in range(g["cols"]):
                index = (row + self.scroll_row) * g["cols"] + col
                cell_x = g["start_x"] + col * g["step"]
                cell_y = g["start_y"] + row * g["step"]
                rect = pygame.Rect(cell_x, cell_y, self.cell_size, self.cell_size)

                if index >= len(items_list):
                    widgets.draw_slot(surface, rect, hovered=False)
                    continue

                item = items_list[index]["item"]
                count = items_list[index]["count"]
                equipped = item.id in equipped_ids
                glow = rarity_color(item.rarity) if item.rarity in RARE_GLOW else None
                if equipped:
                    border = c.Colors.ACCENT
                elif item.rarity != "common":
                    border = rarity_color(item.rarity)
                else:
                    border = None

                widgets.draw_slot(
                    surface,
                    rect,
                    hovered=index == self.hovered_slot,
                    border_color=border,
                    glow_color=glow,
                    border_w=3 if equipped else 2,
                )
                widgets.draw_item_scaled(surface, item, rect.centerx, rect.centery, 44)

                if equipped:
                    pygame.draw.circle(surface, c.Colors.ACCENT, (rect.x + 12, rect.y + 12), 5)
                if count > 1:
                    self._draw_count(surface, rect, count)

        if self._max_scroll(len(items_list)) > 0:
            self._draw_scrollbar(surface, g, len(items_list))

    def _draw_count(self, surface, rect, count):
        text = c.Fonts.small.render(f"x{count}", True, c.Colors.BLACK)
        pill = pygame.Rect(0, 0, text.get_width() + 10, text.get_height() + 2)
        pill.bottomright = (rect.right - 4, rect.bottom - 4)
        pygame.draw.rect(surface, c.Colors.ACCENT, pill)
        surface.blit(text, (pill.x + 5, pill.y + 1))

    def _draw_scrollbar(self, surface, g, item_count):
        track_x = g["start_x"] + g["cols"] * g["step"] - self.cell_padding + 4
        track_y = g["start_y"]
        track_h = g["rows"] * g["step"] - self.cell_padding
        pygame.draw.rect(surface, c.Colors.SLOT_BG, (track_x, track_y, 6, track_h))

        total_rows = math.ceil(item_count / g["cols"])
        thumb_h = max(24, int(track_h * g["rows"] / total_rows))
        max_scroll = self._max_scroll(item_count)
        thumb_y = track_y + int((track_h - thumb_h) * (self.scroll_row / max_scroll)) if max_scroll else track_y
        pygame.draw.rect(surface, c.Colors.ACCENT, (track_x, thumb_y, 6, thumb_h))

    def _fit(self, surf, text, max_width, color):
        """Truncate a rendered label with an ellipsis so it fits `max_width`."""
        if surf.get_width() <= max_width:
            return surf
        while text and c.Fonts.small.render(text + "…", True, color).get_width() > max_width:
            text = text[:-1]
        return c.Fonts.small.render(text + "…", True, color)

    def _draw_tooltip(self, item: "Item", mouse_pos, is_equipped):
        if item.item_type == "weapon" and item.bonus > 0:
            text = f"{item.name}  (+{item.bonus} attack)"
        elif item.item_type == "armor" and item.bonus > 0:
            text = f"{item.name}  (+{item.bonus} defense)"
        elif item.item_type == "accessory" and item.bonus > 0:
            flavor = ACCESSORY_FLAVOR_LABELS.get(item.accessory_flavor, item.accessory_flavor)
            text = f"{item.name}  (+{item.bonus} {flavor})"
        elif item.item_type == "ammo":
            text = f"{item.name}  (x{item.quantity})"
        elif item.item_type == "potion":
            text = f"{item.name}  (x{item.quantity})"
        elif item.item_type == "misc":
            text = f"{item.name}  (valuable, sells for ~{base_value(item)}g)"
        else:
            text = item.name
        if is_equipped:
            text += "  [equipped, click to unequip]"
        elif item.item_type == "potion":
            text += "  [click to drink]"
        elif item.item_type in ("weapon", "armor", "accessory"):
            text += "  [click to equip]"

        # Main line in the rarity colour, then one muted line per rolled effect.
        lines = [(c.Fonts.text.render(text, True, rarity_color(item.rarity)))]
        if item.item_type == "potion":
            lines.append(c.Fonts.small.render(potion_description(item), True, c.Colors.ACCENT))
        for affix, magnitude in item.affixes.items():
            lines.append(c.Fonts.small.render(affix_label(affix, magnitude), True, c.Colors.ACCENT))

        w = max(line.get_width() for line in lines) + 20
        h = sum(line.get_height() for line in lines) + 12 + 2 * (len(lines) - 1)

        # Flip to the other side of the cursor when it would run off screen, then clamp,
        # so a tooltip wider than the space on either side still shows in full.
        mouse_x, mouse_y = mouse_pos
        x = mouse_x + 16
        y = mouse_y + 16
        if x + w > c.Screen.WIDTH - 8:
            x = mouse_x - w - 16
        if y + h > c.Screen.HEIGHT - 8:
            y = mouse_y - h - 16
        x = max(8, min(x, c.Screen.WIDTH - w - 8))
        y = max(8, min(y, c.Screen.HEIGHT - h - 8))

        rect = pygame.Rect(x, y, w, h)
        widgets.draw_panel(self.screen, rect, fill=(24, 24, 30), border=c.Colors.ACCENT)
        line_y = y + 6
        for line in lines:
            self.screen.blit(line, (x + 10, line_y))
            line_y += line.get_height() + 2
