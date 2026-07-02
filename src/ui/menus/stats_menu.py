from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui.menus.base_menu import BaseMenu

if TYPE_CHECKING:
    from game.entities.player import Player


ROW_HEIGHT = 78


class StatsMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=620, height=530)

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_c, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.close()

        return True

    def draw(self, player: Player):
        if not self.active:
            return

        menu_x, menu_y = self.get_centered_position()
        self.draw_overlay()
        surface = self.create_menu_surface()

        title = c.Fonts.title.render("Character", True, c.Colors.WHITE)
        surface.blit(title, ((self.width - title.get_width()) // 2, self.padding))

        stats = player.stats
        rows = [
            ("Strength", "strength", f"+{stats.attack_bonus()} attack damage"),
            ("Resistance", "resistance", f"-{stats.damage_reduction()} damage taken"),
            ("Speed", "speed", f"+{round((stats.speed_multiplier() - 1) * 100)}% move speed"),
            ("Vitality", "vitality", f"{stats.max_hp()} max HP"),
            (
                "Bartering",
                "bartering",
                f"buy {round((1 - stats.buy_multiplier()) * 100)}% cheaper, "
                f"sell {round((stats.sell_multiplier() - 1) * 100)}% higher",
            ),
        ]

        bar_w = self.width - self.padding * 2
        y = self.padding + 60
        for label, key, effect in rows:
            name_surf = c.Fonts.heading.render(label, True, c.Colors.WHITE)
            surface.blit(name_surf, (self.padding, y))

            level_surf = c.Fonts.heading.render(f"Lv {stats.level[key]}", True, c.Colors.YELLOW)
            surface.blit(level_surf, (self.width - self.padding - level_surf.get_width(), y))

            effect_surf = c.Fonts.small.render(effect, True, c.Colors.BORDER)
            surface.blit(effect_surf, (self.padding, y + 26))

            ratio = min(stats.xp[key] / stats.xp_to_next(key), 1.0)
            bar_y = y + 50
            bar_h = 10
            pygame.draw.rect(surface, c.Colors.BUTTON, (self.padding, bar_y, bar_w, bar_h))
            pygame.draw.rect(surface, c.Colors.GREEN, (self.padding, bar_y, int(bar_w * ratio), bar_h))
            pygame.draw.rect(surface, c.Colors.BORDER, (self.padding, bar_y, bar_w, bar_h), 1)

            y += ROW_HEIGHT

        hint = c.Fonts.small.render("C or ESC to close", True, c.Colors.BORDER)
        surface.blit(hint, ((self.width - hint.get_width()) // 2, self.height - self.padding - hint.get_height()))

        self.screen.blit(surface, (menu_x, menu_y))
