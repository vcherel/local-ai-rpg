from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import pygame

import core.constants as c
from game.entities.items import rarity_color, rarity_tier
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


def _sell_price(item: Item) -> int:
    if item.item_type in ("weapon", "armor", "accessory"):
        base = max(5, item.bonus * 10)
    else:
        base = 5
    return round(base * rarity_tier(item.rarity).price_mult)


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

    def open(self, merchant: NPC, player: Player, world_items: List[Item]):
        self.merchant = merchant
        self.player = player
        self.world_items = world_items
        self.active = True
        self.just_active = True
        self.hovered_buy = None
        self.hovered_sell = None

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

    def _row_rect(self, panel_x: int, index: int) -> pygame.Rect:
        y = self._list_top() + index * ROW_HEIGHT
        return pygame.Rect(panel_x, y, self._panel_width(), ROW_HEIGHT - 6)

    def _buy_price(self, item: Item) -> int:
        swing = _affinity_swing(self.merchant)
        return max(1, round(self.merchant.shop_prices[item.id] * self.player.buy_multiplier() * (1.0 - swing)))

    def _sell_price(self, item: Item) -> int:
        swing = _affinity_swing(self.merchant)
        return max(1, round(_sell_price(item) * self.player.sell_multiplier() * (1.0 + swing)))

    def _slot_at(self, panel_x: int, count: int, rel_x: int, rel_y: int) -> Optional[int]:
        for i in range(count):
            r = self._row_rect(panel_x, i)
            if r.collidepoint(rel_x, rel_y):
                return i
        return None

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        menu_x, menu_y = self.get_centered_position()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()

        elif event.type == pygame.MOUSEMOTION:
            rx, ry = event.pos[0] - menu_x, event.pos[1] - menu_y
            self.hovered_buy = self._slot_at(self._buy_panel_x(), len(self.merchant.shop_items), rx, ry)
            self.hovered_sell = self._slot_at(self._sell_panel_x(), len(self.player.inventory), rx, ry)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            rx, ry = event.pos[0] - menu_x, event.pos[1] - menu_y
            buy_idx = self._slot_at(self._buy_panel_x(), len(self.merchant.shop_items), rx, ry)
            if buy_idx is not None:
                self._buy(buy_idx)
                return True
            sell_idx = self._slot_at(self._sell_panel_x(), len(self.player.inventory), rx, ry)
            if sell_idx is not None:
                self._sell(sell_idx)
                return True

        return True

    def _buy(self, index: int):
        item = self.merchant.shop_items[index]
        price = self._buy_price(item)
        if self.player.coins < price:
            return
        self.merchant.shop_items.pop(index)
        del self.merchant.shop_prices[item.id]
        item.picked_up = True
        self.world_items.append(item)
        self.player.inventory.append(item)
        self.player.add_coins(-price)
        self.player.stats.train("bartering", c.Stats.XP_PER_TRADE)

    def _sell(self, index: int):
        item = self.player.inventory[index]
        price = self._sell_price(item)
        self.player.unequip_if_equipped(item)
        self.player.inventory.pop(index)
        if item in self.world_items:
            self.world_items.remove(item)
        self.player.add_coins(price)
        self.player.stats.train("bartering", c.Stats.XP_PER_TRADE)

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

        sell_label = c.Fonts.heading.render("Sell", True, (235, 180, 90))
        surface.blit(sell_label, (sx, label_y))

        if not self.merchant.shop_ready:
            msg = c.Fonts.text.render("Preparing wares...", True, c.Colors.MUTED)
            surface.blit(msg, (bx + 10, self._list_top() + 10))
        elif not self.merchant.shop_items:
            msg = c.Fonts.text.render("Nothing for sale right now.", True, c.Colors.MUTED)
            surface.blit(msg, (bx + 10, self._list_top() + 10))
        else:
            for i, item in enumerate(self.merchant.shop_items):
                price = self._buy_price(item)
                self._draw_row(surface, bx, pw, i, item, price, self.hovered_buy == i, (100, 255, 100))

        sell_items = list(self.player.inventory)
        for i, item in enumerate(sell_items):
            price = self._sell_price(item)
            can_afford = True
            self._draw_row(surface, sx, pw, i, item, price, self.hovered_sell == i, (255, 180, 80), can_afford)

        self.draw_hint(surface, "Click an item to buy or sell. ESC or B to close")
        self.blit_panel(surface)

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
    ):
        r = self._row_rect(panel_x, index)
        rarity_border = rarity_color(item.rarity) if item.rarity != "common" else None
        widgets.draw_slot(surface, r, hovered=hovered, border_color=rarity_border, radius=8)

        icon_x = r.x + 30
        icon_y = r.centery
        widgets.draw_item_scaled(surface, item, icon_x, icon_y, 34)

        name_color = rarity_color(item.rarity) if enabled else c.Colors.MUTED
        name_surf = c.Fonts.text.render(item.name, True, name_color)
        surface.blit(name_surf, (r.x + 58, r.y + 8))

        if item.bonus > 0 and item.item_type in ("weapon", "armor", "accessory"):
            label = {"weapon": "atk", "armor": "def"}.get(item.item_type, item.accessory_flavor)
            stat_surf = c.Fonts.small.render(f"+{item.bonus} {label}", True, c.Colors.MUTED)
            surface.blit(stat_surf, (r.x + 58, r.y + 30))

        price_surf = c.Fonts.text.render(f"{price}g", True, price_color)
        surface.blit(price_surf, (r.right - price_surf.get_width() - 8, r.centery - price_surf.get_height() // 2))
