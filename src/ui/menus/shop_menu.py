from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import pygame

import core.constants as c
from ui.menus.base_menu import BaseMenu

if TYPE_CHECKING:
    from game.entities.items import Item
    from game.entities.npcs import NPC
    from game.entities.player import Player


PANEL_GAP = 20
ROW_HEIGHT = 60
LIST_TOP = 90


def _sell_price(item: Item) -> int:
    if item.item_type in ("weapon", "armor"):
        return max(5, item.bonus * 10)
    return 5


class ShopMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=920, height=580)
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

    def _row_rect(self, panel_x: int, index: int) -> pygame.Rect:
        y = LIST_TOP + index * ROW_HEIGHT
        return pygame.Rect(panel_x, y, self._panel_width(), ROW_HEIGHT - 6)

    def _buy_price(self, item: Item) -> int:
        return max(1, round(self.merchant.shop_prices[item.id] * self.player.stats.buy_multiplier()))

    def _sell_price(self, item: Item) -> int:
        return max(1, round(_sell_price(item) * self.player.stats.sell_multiplier()))

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

    def _sell(self, index: int):
        item = self.player.inventory[index]
        price = self._sell_price(item)
        self.player.inventory.pop(index)
        if item in self.world_items:
            self.world_items.remove(item)
        self.player.add_coins(price)

    def draw(self):
        if not self.active:
            return

        menu_x, menu_y = self.get_centered_position()
        self.draw_overlay()
        surface = self.create_menu_surface()

        title = c.Fonts.title.render(f"{self.merchant.name or 'Merchant'}'s Shop", True, c.Colors.WHITE)
        surface.blit(title, (self.padding, self.padding))

        coins_text = c.Fonts.text.render(f"Coins: {self.player.coins}", True, c.Colors.YELLOW)
        surface.blit(coins_text, (self.width - self.padding - coins_text.get_width(), self.padding + 5))

        pw = self._panel_width()
        bx = self._buy_panel_x()
        sx = self._sell_panel_x()

        buy_label = c.Fonts.heading.render("Buy", True, (100, 255, 100))
        surface.blit(buy_label, (bx, LIST_TOP - 28))

        sell_label = c.Fonts.heading.render("Sell", True, (255, 180, 80))
        surface.blit(sell_label, (sx, LIST_TOP - 28))

        if not self.merchant.shop_ready:
            msg = c.Fonts.text.render("Preparing wares...", True, c.Colors.BORDER)
            surface.blit(msg, (bx + 10, LIST_TOP + 10))
        elif not self.merchant.shop_items:
            msg = c.Fonts.text.render("Nothing for sale right now.", True, c.Colors.BORDER)
            surface.blit(msg, (bx + 10, LIST_TOP + 10))
        else:
            for i, item in enumerate(self.merchant.shop_items):
                price = self._buy_price(item)
                self._draw_row(surface, bx, pw, i, item, price, self.hovered_buy == i, (100, 255, 100))

        sell_items = list(self.player.inventory)
        for i, item in enumerate(sell_items):
            price = self._sell_price(item)
            can_afford = True
            self._draw_row(surface, sx, pw, i, item, price, self.hovered_sell == i, (255, 180, 80), can_afford)

        hint = c.Fonts.small.render("ESC or B to close", True, c.Colors.BORDER)
        surface.blit(hint, (self.width // 2 - hint.get_width() // 2, self.height - self.padding - hint.get_height()))

        self.screen.blit(surface, (menu_x, menu_y))

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
        bg = c.Colors.BUTTON_HOVERED if hovered else c.Colors.BUTTON
        border = c.Colors.BORDER_HOVERED if hovered else c.Colors.BORDER
        pygame.draw.rect(surface, bg, r, border_radius=4)
        pygame.draw.rect(surface, border, r, 1, border_radius=4)

        icon_x = r.x + 28
        icon_y = r.centery
        item.draw(surface, x=icon_x, y=icon_y)

        name_color = c.Colors.WHITE if enabled else c.Colors.BORDER
        name_surf = c.Fonts.text.render(item.name, True, name_color)
        surface.blit(name_surf, (r.x + 56, r.y + 8))

        if item.bonus > 0 and item.item_type in ("weapon", "armor"):
            label = "atk" if item.item_type == "weapon" else "def"
            stat_surf = c.Fonts.small.render(f"+{item.bonus} {label}", True, c.Colors.BORDER)
            surface.blit(stat_surf, (r.x + 56, r.y + 30))

        price_surf = c.Fonts.text.render(f"{price}g", True, price_color)
        surface.blit(price_surf, (r.right - price_surf.get_width() - 8, r.centery - price_surf.get_height() // 2))
