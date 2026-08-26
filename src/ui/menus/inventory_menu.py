from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from game.entities.item_icons import draw_shape_with_border
from game.entities.items import (
    ACCESSORY_FLAVOR_LABELS,
    INVENTORY_SECTIONS,
    affix_label,
    base_value,
    inventory_section,
    potion_description,
    rarity_color,
    rarity_tier,
)
from ui import widgets
from ui.menus.base_menu import EQUIP_BEST_KEY, HEADER_HEIGHT, BaseMenu

if TYPE_CHECKING:
    from game.entities.items import Item
    from game.entities.player import Player


RARE_GLOW = {"rare", "epic", "legendary"}

# Height of a section heading row, cell rows being cell_size + cell_padding tall.
HEADER_ROW_H = 34

# The button under the grid, sized here so drawing and hit-testing share the one rect.
AUTO_EQUIP_SIZE = (170, 30)


class InventoryMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=1000, height=640)
        self.header_height = HEADER_HEIGHT

        self.cell_size = 76
        self.cell_padding = 12
        self.paperdoll_width = 240
        self.footer_height = 74

        self.scroll_row = 0
        # The grouped entry under the cursor (not an index: the rows are rebuilt per frame).
        self.hovered_entry: dict | None = None
        self.hovered_equip: str | None = None

    def close(self):
        self.active = False
        self.hovered_entry = None
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

        def sort_key(entry):
            item = entry["item"]
            section_rank = INVENTORY_SECTIONS.index(inventory_section(item))
            # Best first inside a section, so the gear worth equipping sits at the top of
            # its block rather than wherever it happened to be picked up.
            rarity_rank = -c.Rarity.TIERS.index(rarity_tier(item.rarity))
            return (section_rank, rarity_rank, -item.bonus, item.name)

        return sorted(item_dict.values(), key=sort_key)

    # --- geometry -------------------------------------------------------------
    # width/height are fixed, so draw and hit-testing share the same layout.

    def _grid_geom(self) -> dict:
        top = self.content_top
        grid_x0 = self.padding + self.paperdoll_width + 24
        area_w = self.width - grid_x0 - self.padding
        area_h = self.height - top - self.footer_height

        step = self.cell_size + self.cell_padding
        cols = max(1, (area_w + self.cell_padding) // step)

        grid_w = cols * self.cell_size + (cols - 1) * self.cell_padding
        start_x = grid_x0 + (area_w - grid_w) // 2
        return {"cols": cols, "start_x": start_x, "start_y": top, "step": step, "width": grid_w, "area_h": area_h}

    def _rows(self, items_list: list[dict], cols: int) -> list[tuple]:
        """The grid as a flat list of rows, each either ("header", title) or ("cells",
        entries). Scrolling, hit-testing and drawing all walk this one list, so a section
        heading takes a row of its own rather than being laid over the cells."""
        rows = []
        for title in INVENTORY_SECTIONS:
            group = [entry for entry in items_list if inventory_section(entry["item"]) == title]
            if not group:
                continue
            rows.append(("header", title))
            for start in range(0, len(group), cols):
                rows.append(("cells", group[start : start + cols]))
        return rows

    def _row_height(self, row) -> int:
        return HEADER_ROW_H if row[0] == "header" else self.cell_size + self.cell_padding

    def _visible_rows(self, rows: list[tuple]) -> list[tuple]:
        """(row, y) for the rows that fit below the scroll position, in draw order."""
        g = self._grid_geom()
        laid_out = []
        y = g["start_y"]
        for row in rows[self.scroll_row :]:
            height = self._row_height(row)
            # The padding under the last row falls outside the area, so it doesn't count.
            if y + height - self.cell_padding > g["start_y"] + g["area_h"]:
                break
            laid_out.append((row, y))
            y += height
        # A heading whose section was cut off below it says nothing, so it goes with them.
        if laid_out and laid_out[-1][0][0] == "header":
            laid_out.pop()
        return laid_out

    def _max_scroll(self, rows: list[tuple]) -> int:
        """The first scroll position that still shows the last row, found by filling the
        area from the bottom up, since rows are not all the same height."""
        remaining = self._grid_geom()["area_h"] + self.cell_padding
        fitting = 0
        for row in reversed(rows):
            height = self._row_height(row)
            if height > remaining:
                break
            remaining -= height
            fitting += 1
        return max(0, len(rows) - fitting)

    def _paperdoll_rects(self) -> list[tuple[str, str, str, pygame.Rect]]:
        """(item_type, label, glyph, slot_rect) for each equip slot, laid out as a 2x2 grid."""
        slot = 76
        label_h = 24
        gap_x = 20
        gap_y = 16
        # Room kept above the grid for the "Equipped" heading, which is drawn from the
        # first slot's position and would otherwise ride up into the title band.
        heading_h = 26
        cols = 2
        rows = math.ceil(len(widgets.EQUIP_SLOTS) / cols)
        block_h = label_h + slot

        grid_w = cols * slot + (cols - 1) * gap_x
        grid_h = rows * block_h + (rows - 1) * gap_y

        area_h = self.height - self.content_top - self.footer_height - heading_h
        start_y = self.content_top + heading_h + max(0, (area_h - grid_h) // 2)
        start_x = self.padding + (self.paperdoll_width - grid_w) // 2

        rects = []
        for i, (item_type, label, glyph) in enumerate(widgets.EQUIP_SLOTS):
            col, row = i % cols, i // cols
            x = start_x + col * (slot + gap_x)
            y = start_y + row * (block_h + gap_y)
            rect = pygame.Rect(x, y + label_h, slot, slot)
            rects.append((item_type, label, glyph, rect))
        return rects

    def _auto_equip_rect(self) -> pygame.Rect:
        """The Equip best button, under the paper-doll it changes."""
        width, height = AUTO_EQUIP_SIZE
        return pygame.Rect(self.width - self.padding - width, self.height - self.footer_height + 4, width, height)

    def _entry_at(self, rel_x: int, rel_y: int, rows: list[tuple]) -> dict | None:
        g = self._grid_geom()
        for row, y in self._visible_rows(rows):
            if row[0] == "header" or not (y <= rel_y < y + self.cell_size):
                continue
            col = (rel_x - g["start_x"]) // g["step"]
            if col < 0 or col >= len(row[1]):
                return None
            cell_x = g["start_x"] + col * g["step"]
            return row[1][col] if cell_x <= rel_x < cell_x + self.cell_size else None
        return None

    def _equip_at(self, rel_x: int, rel_y: int) -> str | None:
        for item_type, _label, _glyph, rect in self._paperdoll_rects():
            if rect.collidepoint(rel_x, rel_y):
                return item_type
        return None

    # --- events ---------------------------------------------------------------

    def handle_event(self, event, player: Player):
        if not self.active:
            return False

        rows = self._rows(self._grouped_items(player), self._grid_geom()["cols"])
        menu_x, menu_y = self.get_centered_position()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            rel_x, rel_y = event.pos[0] - menu_x, event.pos[1] - menu_y
            entry = self._entry_at(rel_x, rel_y, rows)
            if entry is not None:
                item = entry["item"]
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
            if self._auto_equip_rect().collidepoint(rel_x, rel_y):
                player.auto_equip_best()
                return True

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            # Right click walks a weapon from one hand to the other and then off the end,
            # or a potion along the quickbar: the only way to say which button a weapon
            # answers to, since equipping and picking up only ever fill a hand that is free.
            rel_x, rel_y = event.pos[0] - menu_x, event.pos[1] - menu_y
            entry = self._entry_at(rel_x, rel_y, rows)
            if entry is not None:
                item = entry["item"]
                if item.item_type == "potion":
                    player.cycle_potion_slot(item)
                else:
                    player.cycle_weapon_slot(item)
            return True

        elif event.type == pygame.MOUSEWHEEL:
            self.scroll_row = max(0, min(self._max_scroll(rows), self.scroll_row - event.y))

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_i, pygame.K_ESCAPE):
                self.close()
            elif event.key == pygame.K_UP:
                self.scroll_row = max(0, self.scroll_row - 1)
            elif event.key == pygame.K_DOWN:
                self.scroll_row = min(self._max_scroll(rows), self.scroll_row + 1)
            elif event.key == EQUIP_BEST_KEY:
                player.auto_equip_best()

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

        rows = self._rows(self._grouped_items(player), self._grid_geom()["cols"])
        self.scroll_row = min(self.scroll_row, self._max_scroll(rows))
        equipped_ids = set(player.equipped_ids().values())

        mouse_pos = pygame.mouse.get_pos()
        rel_x, rel_y = mouse_pos[0] - menu_x, mouse_pos[1] - menu_y
        self.hovered_entry = self._entry_at(rel_x, rel_y, rows)
        self.hovered_equip = self._equip_at(rel_x, rel_y)

        self._draw_paperdoll(surface, player)
        self._draw_auto_equip_button(surface, player, (rel_x, rel_y))
        self._draw_grid(surface, rows, equipped_ids, player)

        tooltip_item = None
        if self.hovered_entry is not None:
            tooltip_item = self.hovered_entry["item"]
        elif self.hovered_equip is not None:
            tooltip_item = player.equipped_item(self.hovered_equip)

        self.draw_hint(
            surface,
            "Click to equip, unequip or drink. Right click a weapon to move it hand to hand. ESC or I to close",
        )
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
            # The three slots a button or a key spends take the gold caption and say what
            # uses them, since what a slot is for is the whole of what the doll tells.
            key = widgets.SLOT_KEYS.get(item_type)
            caption = f"{label} [{key}]" if key is not None and key != label[0] else label

            label_surf = c.Fonts.small.render(caption, True, c.Colors.ACCENT if key else c.Colors.MUTED)
            surface.blit(label_surf, (rect.centerx - label_surf.get_width() // 2, rect.y - 22))

            border = c.Colors.ACCENT if item else c.Colors.SLOT_BORDER
            widgets.draw_slot(surface, rect, hovered=hovered, border_color=border, border_w=3 if key else 2)

            if item is not None:
                widgets.draw_item_scaled(surface, item, rect.centerx, rect.centery - 6, 58)
                name = c.Fonts.small.render(item.name, True, rarity_color(item.rarity))
                name = self._fit(name, item.name, rect.width - 8, rarity_color(item.rarity))
                surface.blit(name, (rect.centerx - name.get_width() // 2, rect.bottom - 20))
            else:
                draw_shape_with_border(surface, glyph, rect.center, 24, (66, 66, 76), 2, (90, 90, 104))

    def _draw_auto_equip_button(self, surface, player: Player, rel_pos):
        """One click to put the best of everything carried on, reporting how many upgrades
        are sitting in the bag unworn."""
        rect = self._auto_equip_rect()
        pending = player.pending_upgrades()
        label = f"[{pygame.key.name(EQUIP_BEST_KEY).upper()}] Equip best ({pending})" if pending else "Equip best"
        widgets.draw_button(
            surface,
            rect,
            label,
            c.Fonts.small,
            hovered=rect.collidepoint(rel_pos),
            text_color=c.Colors.WHITE if pending else c.Colors.MUTED,
        )

    def _draw_grid(self, surface, rows, equipped_ids, player: Player):
        g = self._grid_geom()
        for row, y in self._visible_rows(rows):
            if row[0] == "header":
                self._draw_section_header(surface, g, row[1], y)
                continue

            for col, entry in enumerate(row[1]):
                rect = pygame.Rect(g["start_x"] + col * g["step"], y, self.cell_size, self.cell_size)
                self._draw_cell(surface, rect, entry, equipped_ids, player)

        if self._max_scroll(rows) > 0:
            self._draw_scrollbar(surface, g, rows)

    def _draw_section_header(self, surface, g, title: str, y: int):
        label = c.Fonts.small.render(title.upper(), True, c.Colors.MUTED)
        baseline = y + HEADER_ROW_H - 10
        surface.blit(label, (g["start_x"], baseline - label.get_height()))
        line_x = g["start_x"] + label.get_width() + 10
        line_y = baseline - 6
        pygame.draw.line(surface, c.Colors.SLOT_BORDER, (line_x, line_y), (g["start_x"] + g["width"], line_y))

    def _draw_cell(self, surface, rect, entry, equipped_ids, player: Player):
        item = entry["item"]
        count = entry["count"]
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
            hovered=entry is self.hovered_entry,
            border_color=border,
            glow_color=glow,
            border_w=3 if equipped else 2,
        )
        widgets.draw_item_scaled(surface, item, rect.centerx, rect.centery, 44)

        if equipped:
            pygame.draw.circle(surface, c.Colors.ACCENT, (rect.x + 12, rect.y + 12), 5)
        # Whichever button or key would reach for the item, drawn on it: the mouse button
        # for a weapon, G for the bomb, a letter for a potion on the quickbar.
        bound = widgets.SLOT_KEYS.get(player.equipped_slot_of(item))
        if bound is None and item.id in player.potion_bar:
            bound = c.Potions.QUICK_KEYS[player.potion_bar.index(item.id)].upper()
        if bound is not None:
            key = c.Fonts.small.render(bound, True, c.Colors.ACCENT)
            surface.blit(key, (rect.right - key.get_width() - 5, rect.y + 3))
        if count > 1:
            self._draw_count(surface, rect, count)

    def _draw_count(self, surface, rect, count):
        text = c.Fonts.small.render(f"x{count}", True, c.Colors.BLACK)
        pill = pygame.Rect(0, 0, text.get_width() + 10, text.get_height() + 2)
        pill.bottomright = (rect.right - 4, rect.bottom - 4)
        pygame.draw.rect(surface, c.Colors.ACCENT, pill)
        surface.blit(text, (pill.x + 5, pill.y + 1))

    def _draw_scrollbar(self, surface, g, rows):
        widgets.draw_scrollbar(
            surface,
            g["start_x"] + g["width"] + 8,
            g["start_y"],
            g["area_h"],
            visible=max(1, len(self._visible_rows(rows))),
            total=len(rows),
            scroll=self.scroll_row,
            max_scroll=self._max_scroll(rows),
        )

    def _fit(self, surf, text, max_width, color):
        """Truncate a rendered label with an ellipsis so it fits `max_width`."""
        if surf.get_width() <= max_width:
            return surf
        while text and c.Fonts.small.render(text + "…", True, color).get_width() > max_width:
            text = text[:-1]
        return c.Fonts.small.render(text + "…", True, color)

    def _draw_tooltip(self, item: Item, mouse_pos, is_equipped):
        if item.item_type == "weapon" and item.bonus > 0:
            text = f"{item.name}  (+{item.bonus} attack)"
        elif item.item_type == "armor" and item.bonus > 0:
            text = f"{item.name}  (+{item.bonus} defense)"
        elif item.item_type == "shield":
            block = round(min(c.Shield.BLOCK_MAX, c.Shield.BLOCK_BASE + item.bonus * c.Shield.BLOCK_PER_BONUS) * 100)
            text = f"{item.name}  (+{item.bonus} defense, blocks {block}% held up)"
        elif item.item_type == "accessory" and item.bonus > 0:
            flavor = ACCESSORY_FLAVOR_LABELS.get(item.accessory_flavor, item.accessory_flavor)
            text = f"{item.name}  (+{item.bonus} {flavor})"
        elif item.item_type in ("ammo", "potion"):
            text = f"{item.name}  (x{item.quantity})"
        elif item.item_type == "misc":
            text = f"{item.name}  (valuable, sells for ~{base_value(item)}g)"
        else:
            text = item.name
        if is_equipped:
            text += "  [equipped, click to unequip]"
        elif item.item_type == "potion":
            text += "  [click to drink]"
        elif item.item_type == "ammo":
            text += "  [click to load]"
        elif item.item_type in ("weapon", "armor", "shield", "accessory"):
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
