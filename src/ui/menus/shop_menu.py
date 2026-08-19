from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import pygame

import core.constants as c
from game.entities.items import ACCESSORY_FLAVOR_LABELS, base_value, potion_description, rarity_color
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

if TYPE_CHECKING:
    from game.entities.items import Item
    from game.entities.npcs import NPC
    from game.entities.player import Player


PANEL_GAP = 20
ROW_HEIGHT = 60
# Room below the column labels for the first row.
LABEL_GAP = 30
# Strip at the bottom of the panel kept clear for the hint line and the sell-all buttons.
FOOTER_HEIGHT = 84
BULK_BUTTON_HEIGHT = 30

# What "unused gear" means: equippable kinds only. Ammo and potions are supplies you
# spend rather than gear you outgrow, so a bulk sell never touches them.
GEAR_TYPES = ("weapon", "armor", "shield", "accessory")


def _affinity_swing(npc: NPC) -> float:
    """-MAX_PRICE_SWING..MAX_PRICE_SWING as the NPC's affinity ranges MIN..MAX."""
    span = c.Affinity.MAX - c.Affinity.START
    return (npc.affinity - c.Affinity.START) / span * c.Affinity.MAX_PRICE_SWING


class ShopMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=940, height=600)
        self.header_height = HEADER_HEIGHT
        self.merchant: Optional[NPC] = None
        self.player: Optional[Player] = None
        self.world_items: Optional[List[Item]] = None
        self.hovered_buy: Optional[int] = None
        self.hovered_sell: Optional[int] = None
        # First visible row of each column; a stock or an inventory longer than the panel
        # is otherwise drawn past its bottom edge with no way to reach it.
        self.buy_scroll = 0
        self.sell_scroll = 0

    def open(self, merchant: NPC, player: Player, world_items: List[Item]):
        self.merchant = merchant
        self.player = player
        self.world_items = world_items
        self.active = True
        self.just_active = True
        self.hovered_buy = None
        self.hovered_sell = None
        self.buy_scroll = 0
        self.sell_scroll = 0

    def close(self):
        self.active = False
        self.merchant = None
        self.player = None
        self.world_items = None

    def _panel_width(self) -> int:
        return (self.width - self.padding * 3 - PANEL_GAP) // 2

    def _buy_panel_x(self) -> int:
        return self.padding

    def _sell_panel_x(self) -> int:
        return self.padding * 2 + self._panel_width() + PANEL_GAP

    def _list_top(self) -> int:
        return self.content_top + LABEL_GAP

    def _row_rect(self, panel_x: int, visible_index: int) -> pygame.Rect:
        """Rect of the nth row currently on screen, not of the nth item in the list."""
        y = self._list_top() + visible_index * ROW_HEIGHT
        return pygame.Rect(panel_x, y, self._panel_width(), ROW_HEIGHT - 6)

    def _visible_rows(self) -> int:
        return max(1, (self.height - self._list_top() - FOOTER_HEIGHT) // ROW_HEIGHT)

    def _max_scroll(self, count: int) -> int:
        return max(0, count - self._visible_rows())

    def _buy_price(self, item: Item) -> int:
        swing = _affinity_swing(self.merchant)
        return max(1, round(self.merchant.shop_prices[item.id] * self.player.buy_multiplier() * (1.0 - swing)))

    def _sell_price(self, item: Item) -> int:
        swing = _affinity_swing(self.merchant)
        return max(1, round(base_value(item) * self.player.sell_multiplier() * (1.0 + swing)))

    # --- bulk selling ---------------------------------------------------------

    def _valuables(self) -> List[Item]:
        return [item for item in self.player.inventory if item.item_type == "misc"]

    def _unused_gear(self) -> List[Item]:
        """Equippable items the player is neither wearing nor keeping on the weapon bar."""
        spoken_for = set(self.player.equipped_ids().values()) | set(self.player.weapon_bar)
        return [item for item in self.player.inventory if item.item_type in GEAR_TYPES and item.id not in spoken_for]

    def _bulk_button_rects(self) -> tuple[pygame.Rect, pygame.Rect]:
        width = (self._panel_width() - 10) // 2
        y = self.height - FOOTER_HEIGHT + 6
        left = self._sell_panel_x()
        return (
            pygame.Rect(left, y, width, BULK_BUTTON_HEIGHT),
            pygame.Rect(left + width + 10, y, width, BULK_BUTTON_HEIGHT),
        )

    def _auto_equip_rect(self) -> pygame.Rect:
        """The Equip best button, under the buy column: what you just bought is worn on the
        spot rather than after a trip to the inventory."""
        y = self.height - FOOTER_HEIGHT + 6
        return pygame.Rect(self._buy_panel_x(), y, (self._panel_width() - 10) // 2, BULK_BUTTON_HEIGHT)

    def _sell_all(self, items: List[Item]):
        """Sell a whole batch through the normal per-item path, so each one still trains
        bartering and warms the merchant exactly as it would clicked by hand."""
        for item in items:
            if item in self.player.inventory:
                self._sell(self.player.inventory.index(item))

    def _slot_at(self, panel_x: int, count: int, scroll: int, rel_x: int, rel_y: int) -> Optional[int]:
        """Index in the full list of the row under (rel_x, rel_y), or None."""
        for i in range(max(0, min(self._visible_rows(), count - scroll))):
            if self._row_rect(panel_x, i).collidepoint(rel_x, rel_y):
                return scroll + i
        return None

    def _buy_slot_at(self, rel_x: int, rel_y: int) -> Optional[int]:
        return self._slot_at(self._buy_panel_x(), len(self.merchant.shop_items), self.buy_scroll, rel_x, rel_y)

    def _sell_slot_at(self, rel_x: int, rel_y: int) -> Optional[int]:
        return self._slot_at(self._sell_panel_x(), len(self.player.inventory), self.sell_scroll, rel_x, rel_y)

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        menu_x, menu_y = self.get_centered_position()

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_b, pygame.K_ESCAPE):
                self.close()
            elif event.key == pygame.K_UP:
                self._scroll(-1, *pygame.mouse.get_pos())
            elif event.key == pygame.K_DOWN:
                self._scroll(1, *pygame.mouse.get_pos())

        elif event.type == pygame.MOUSEWHEEL:
            # MOUSEWHEEL carries no position; the column under the cursor scrolls.
            self._scroll(-event.y, *pygame.mouse.get_pos())

        elif event.type == pygame.MOUSEMOTION:
            rx, ry = event.pos[0] - menu_x, event.pos[1] - menu_y
            self.hovered_buy = self._buy_slot_at(rx, ry)
            self.hovered_sell = self._sell_slot_at(rx, ry)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            rx, ry = event.pos[0] - menu_x, event.pos[1] - menu_y
            buy_idx = self._buy_slot_at(rx, ry)
            if buy_idx is not None:
                self._buy(buy_idx)
                return True
            sell_idx = self._sell_slot_at(rx, ry)
            if sell_idx is not None:
                self._sell(sell_idx)
                return True
            valuables_rect, gear_rect = self._bulk_button_rects()
            if valuables_rect.collidepoint(rx, ry):
                self._sell_all(self._valuables())
                return True
            if gear_rect.collidepoint(rx, ry):
                self._sell_all(self._unused_gear())
                return True
            if self._auto_equip_rect().collidepoint(rx, ry):
                self.player.auto_equip_best()
                return True

        return True

    def _scroll(self, rows: int, mouse_x: int, mouse_y: int):
        """Scroll whichever column the cursor sits over, the sell one by default."""
        menu_x, _ = self.get_centered_position()
        if mouse_x - menu_x < self._sell_panel_x():
            limit = self._max_scroll(len(self.merchant.shop_items))
            self.buy_scroll = max(0, min(limit, self.buy_scroll + rows))
        else:
            limit = self._max_scroll(len(self.player.inventory))
            self.sell_scroll = max(0, min(limit, self.sell_scroll + rows))

    def _buy(self, index: int):
        item = self.merchant.shop_items[index]
        price = self._buy_price(item)
        if self.player.coins < price:
            return
        self.merchant.shop_items.pop(index)
        del self.merchant.shop_prices[item.id]
        item.picked_up = True
        # A stackable merges into an existing stack; only a new entry joins the master world list.
        if self.player.add_item(item) is item:
            self.world_items.append(item)
        self.player.add_coins(-price)
        self._record_trade()

    def _sell(self, index: int):
        item = self.player.inventory[index]
        price = self._sell_price(item)
        # A stack sells one unit per click, so parting with a spare arrow or potion
        # doesn't hand the merchant the whole stack for a single item's price.
        if item.quantity > 1:
            item.quantity -= 1
        else:
            self.player.unequip_if_equipped(item)
            self.player.inventory.pop(index)
            if item in self.world_items:
                self.world_items.remove(item)
        self.player.add_coins(price)
        self._record_trade()

    def _record_trade(self):
        """Every completed buy or sell trains bartering and warms the merchant a little."""
        self.player.stats.train("bartering", c.Stats.XP_PER_TRADE)
        self.merchant.affinity = min(c.Affinity.MAX, self.merchant.affinity + c.Affinity.TRADE_BONUS)

    def _restock_label(self) -> str:
        """The countdown drawn over the buy column. Minutes while it is far off, seconds once
        it is close, because a shop about to refill is worth standing around for."""
        remaining = self.merchant.restock_in()
        if remaining <= 0:
            return "New wares arriving"
        if remaining >= 60:
            return f"Restocks in {int(remaining // 60) + 1}m"
        return f"Restocks in {int(remaining) + 1}s"

    def draw(self):
        if not self.active:
            return

        self.draw_overlay()
        surface = self.create_menu_surface(f"{self.merchant.name or 'Merchant'}'s Shop")

        coins_text = c.Fonts.text.render(f"{self.player.coins} coins", True, c.Colors.ACCENT)
        surface.blit(
            coins_text,
            (self.width - self.padding - coins_text.get_width(), (HEADER_HEIGHT - coins_text.get_height()) // 2),
        )

        pw = self._panel_width()
        bx = self._buy_panel_x()
        sx = self._sell_panel_x()
        label_y = self._list_top() - 28

        buy_label = c.Fonts.heading.render("Buy", True, (120, 220, 120))
        surface.blit(buy_label, (bx, label_y))

        # When the next delivery lands, beside the wares it lands on: buying a shop out is
        # only a decision if the player can see what waiting is worth.
        if self.merchant.shop_ready:
            restock = c.Fonts.small.render(self._restock_label(), True, c.Colors.MUTED)
            surface.blit(restock, (bx + pw - restock.get_width(), label_y + 6))

        sell_label = c.Fonts.heading.render("Sell", True, (235, 180, 90))
        surface.blit(sell_label, (sx, label_y))

        # Buying and selling change the lists under the scroll offsets, so clamp here.
        buy_items = self.merchant.shop_items
        sell_items = list(self.player.inventory)
        self.buy_scroll = min(self.buy_scroll, self._max_scroll(len(buy_items)))
        self.sell_scroll = min(self.sell_scroll, self._max_scroll(len(sell_items)))
        visible = self._visible_rows()

        if not self.merchant.shop_ready:
            msg = c.Fonts.text.render("Preparing wares...", True, c.Colors.MUTED)
            surface.blit(msg, (bx + 10, self._list_top() + 10))
        elif not buy_items:
            msg = c.Fonts.text.render("Nothing for sale right now.", True, c.Colors.MUTED)
            surface.blit(msg, (bx + 10, self._list_top() + 10))
        else:
            for row, item in enumerate(buy_items[self.buy_scroll : self.buy_scroll + visible]):
                index = self.buy_scroll + row
                price = self._buy_price(item)
                can_afford = self.player.coins >= price
                self._draw_row(
                    surface, bx, pw, row, item, price, self.hovered_buy == index, (100, 255, 100), can_afford
                )
            self._draw_scrollbar(surface, bx + pw + 4, len(buy_items), self.buy_scroll)

        equipped_ids = set(self.player.equipped_ids().values())
        for row, item in enumerate(sell_items[self.sell_scroll : self.sell_scroll + visible]):
            index = self.sell_scroll + row
            price = self._sell_price(item)
            equipped = item.id in equipped_ids
            self._draw_row(
                surface, sx, pw, row, item, price, self.hovered_sell == index, (255, 180, 80), equipped=equipped
            )
        self._draw_scrollbar(surface, sx + pw + 4, len(sell_items), self.sell_scroll)
        self._draw_bulk_buttons(surface)
        self._draw_auto_equip_button(surface)

        self.draw_hint(surface, "Click an item to buy or sell. Scroll for more. ESC or B to close")
        self.blit_panel(surface)

    def _draw_auto_equip_button(self, surface: pygame.Surface):
        menu_x, menu_y = self.get_centered_position()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        rel = (mouse_x - menu_x, mouse_y - menu_y)

        rect = self._auto_equip_rect()
        pending = self.player.pending_upgrades()
        widgets.draw_button(
            surface,
            rect,
            f"Equip best ({pending})" if pending else "Equip best",
            c.Fonts.small,
            hovered=bool(pending) and rect.collidepoint(rel),
            text_color=c.Colors.WHITE if pending else c.Colors.MUTED,
        )

    def _draw_bulk_buttons(self, surface: pygame.Surface):
        """The two sell-everything buttons under the sell column, each labelled with what
        it would actually pay, so clearing the bag is never a blind click."""
        menu_x, menu_y = self.get_centered_position()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        rel = (mouse_x - menu_x, mouse_y - menu_y)

        batches = (("Valuables", self._valuables()), ("Unused gear", self._unused_gear()))
        for rect, (caption, items) in zip(self._bulk_button_rects(), batches):
            total = sum(self._sell_price(item) for item in items)
            label = f"Sell {caption.lower()}  {total}g" if items else f"No {caption.lower()}"
            widgets.draw_button(
                surface,
                rect,
                label,
                c.Fonts.small,
                hovered=bool(items) and rect.collidepoint(rel),
                text_color=c.Colors.WHITE if items else c.Colors.MUTED,
            )

    def _draw_scrollbar(self, surface: pygame.Surface, x: int, count: int, scroll: int):
        max_scroll = self._max_scroll(count)
        if max_scroll <= 0:
            return

        visible = self._visible_rows()
        track_y = self._list_top()
        track_h = visible * ROW_HEIGHT - 6
        pygame.draw.rect(surface, c.Colors.SLOT_BG, (x, track_y, 6, track_h))

        thumb_h = max(24, int(track_h * visible / count))
        thumb_y = track_y + int((track_h - thumb_h) * (scroll / max_scroll))
        pygame.draw.rect(surface, c.Colors.ACCENT, (x, thumb_y, 6, thumb_h))

    def _draw_row(
        self,
        surface: pygame.Surface,
        panel_x: int,
        panel_w: int,
        index: int,
        item: Item,
        price: int,
        hovered: bool,
        price_color: tuple,
        enabled: bool = True,
        equipped: bool = False,
    ):
        r = self._row_rect(panel_x, index)
        border_color = c.Colors.ACCENT if equipped else (rarity_color(item.rarity) if item.rarity != "common" else None)
        widgets.draw_slot(surface, r, hovered=hovered, border_color=border_color, border_w=3 if equipped else 2)

        icon_x = r.x + 30
        icon_y = r.centery
        widgets.draw_item_scaled(surface, item, icon_x, icon_y, 34)

        if equipped:
            pygame.draw.circle(surface, c.Colors.ACCENT, (r.x + 10, r.y + 10), 5)

        name_color = rarity_color(item.rarity) if enabled else c.Colors.MUTED
        name = f"{item.name} x{item.quantity}" if item.quantity > 1 else item.name
        name_surf = c.Fonts.text.render(name, True, name_color)
        surface.blit(name_surf, (r.x + 58, r.y + 8))
        if equipped:
            tag = c.Fonts.small.render("equipped", True, c.Colors.ACCENT)
            surface.blit(tag, (r.right - tag.get_width() - 8, r.y + 8))

        if item.bonus > 0 and item.item_type in ("weapon", "armor", "shield", "accessory"):
            label = {"weapon": "atk", "armor": "def", "shield": "block"}.get(
                item.item_type, ACCESSORY_FLAVOR_LABELS.get(item.accessory_flavor, item.accessory_flavor)
            )
            stat = f"+{item.bonus} {label}"
            if item.affixes:
                stat += f"  +{len(item.affixes)} fx"
            stat_surf = c.Fonts.small.render(stat, True, c.Colors.MUTED)
            surface.blit(stat_surf, (r.x + 58, r.y + 30))
        elif item.item_type == "potion":
            stat_surf = c.Fonts.small.render(potion_description(item), True, c.Colors.MUTED)
            surface.blit(stat_surf, (r.x + 58, r.y + 30))
        elif item.item_type == "misc":
            stat_surf = c.Fonts.small.render("valuable", True, c.Colors.MUTED)
            surface.blit(stat_surf, (r.x + 58, r.y + 30))

        price_surf = c.Fonts.text.render(f"{price}g", True, price_color)
        surface.blit(price_surf, (r.right - price_surf.get_width() - 8, r.centery - price_surf.get_height() // 2))
