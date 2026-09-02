from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

if TYPE_CHECKING:
    from game.entities.village import Village

CARD_HEIGHT = 96
CARD_GAP = 12
TAKE_BUTTON_W = 110
TAKE_BUTTON_H = 34


class BoardMenu(BaseMenu):
    """The notices pinned to a settlement's board, and the one button that takes one.

    The board itself owns nothing: what it shows is `WorldPlaces.board_offers` and what
    taking one does is `Game._take_notice`, which puts the quest on a villager who actually
    lives here. So this is a list with buttons on it, and every quest it hands out is the
    same object a conversation would have produced.
    """

    def __init__(self, screen):
        super().__init__(screen, width=680, height=442)
        self.header_height = HEADER_HEIGHT
        self.village: Village | None = None
        self.offers: list[dict] = []
        # Set by whoever opened it: called with the notice the player clicked Take on.
        self.on_take = None
        self.hovered: int | None = None

    def open(self, village: Village, offers: list[dict], on_take):
        self.village = village
        self.offers = offers
        self.on_take = on_take
        self.active = True
        self.hovered = None

    def close(self):
        self.active = False
        self.village = None
        self.offers = []
        self.on_take = None

    def _card_rect(self, index: int) -> pygame.Rect:
        y = self.content_top + index * (CARD_HEIGHT + CARD_GAP)
        return pygame.Rect(self.padding, y, self.width - self.padding * 2, CARD_HEIGHT)

    def _take_rect(self, index: int) -> pygame.Rect:
        card = self._card_rect(index)
        left = card.right - TAKE_BUTTON_W - 14
        return pygame.Rect(left, card.bottom - TAKE_BUTTON_H - 12, TAKE_BUTTON_W, TAKE_BUTTON_H)

    def handle_event(self, event) -> bool:
        if not self.active:
            return False
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_n, pygame.K_e):
            self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            menu_x, menu_y = self.get_centered_position()
            local = (event.pos[0] - menu_x, event.pos[1] - menu_y)
            for index in range(len(self.offers)):
                if self._take_rect(index).collidepoint(local):
                    # The offer is handed over rather than its index: the list it came from
                    # is the village's, and whoever takes it is the one that empties it.
                    if self.on_take is not None:
                        self.on_take(self.offers[index])
                    self.close()
                    return True
        return True

    def draw(self):
        if not self.active:
            return
        menu_x, menu_y = self.get_centered_position()
        self.draw_overlay()
        name = self.village.name if self.village is not None and self.village.name else "Notice board"
        surface = self.create_menu_surface(name)

        mouse = pygame.mouse.get_pos()
        local = (mouse[0] - menu_x, mouse[1] - menu_y)
        self.hovered = next((i for i in range(len(self.offers)) if self._take_rect(i).collidepoint(local)), None)

        if not self.offers:
            empty = c.Fonts.heading.render("Nothing pinned up", True, c.Colors.MUTED)
            surface.blit(empty, empty.get_rect(center=(self.width // 2, self.height // 2)))
        else:
            for index, offer in enumerate(self.offers):
                self._draw_card(surface, index, offer)

        self.draw_hint(surface, "Take a notice and whoever posted it will be waiting for you. E or Esc to walk away.")
        self.screen.blit(surface, (menu_x, menu_y))

    def _draw_card(self, surface: pygame.Surface, index: int, offer: dict):
        card = self._card_rect(index)
        widgets.draw_slot(surface, card, hovered=index == self.hovered)

        title = c.Fonts.heading.render(offer["title"], True, c.Colors.YELLOW)
        surface.blit(title, (card.left + 14, card.top + 12))

        description = offer["info"]["quest_description"]
        text_width = card.width - TAKE_BUTTON_W - 44
        y = card.top + 12 + title.get_height() + 6
        for line in widgets.wrap_text(description, c.Fonts.text, text_width)[:2]:
            surface.blit(c.Fonts.text.render(line, True, c.Colors.WHITE), (card.left + 14, y))
            y += 22

        widgets.draw_button(surface, self._take_rect(index), "Take", c.Fonts.button, hovered=index == self.hovered)
