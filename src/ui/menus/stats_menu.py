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
        super().__init__(screen, width=620, height=608)

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

        self.draw_overlay()
        surface = self.create_menu_surface("Character")

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
            (
                "Persuasion",
                "persuasion",
                f"+{round(stats.quest_reward_weights()[4] - c.Rarity.QUEST_REWARD_WEIGHTS[4])}pt "
                "legendary quest reward odds, NPCs more receptive",
            ),
        ]

        bar_w = self.width - self.padding * 2
        y = self.content_top
        for label, key, effect in rows:
            name_surf = c.Fonts.heading.render(label, True, c.Colors.WHITE)
            surface.blit(name_surf, (self.padding, y))

            level_surf = c.Fonts.heading.render(f"Lv {stats.level[key]}", True, c.Colors.ACCENT)
            surface.blit(level_surf, (self.width - self.padding - level_surf.get_width(), y))

            effect_surf = c.Fonts.small.render(effect, True, c.Colors.MUTED)
            surface.blit(effect_surf, (self.padding, y + 26))

            ratio = min(stats.xp[key] / stats.xp_to_next(key), 1.0)
            bar_y = y + 50
            bar_h = 10
            pygame.draw.rect(surface, c.Colors.SLOT_BG, (self.padding, bar_y, bar_w, bar_h))
            if ratio > 0:
                pygame.draw.rect(
                    surface,
                    c.Colors.GREEN,
                    (self.padding, bar_y, max(bar_h, int(bar_w * ratio)), bar_h),
                )
            pygame.draw.rect(surface, c.Colors.SLOT_BORDER, (self.padding, bar_y, bar_w, bar_h), 1)

            y += ROW_HEIGHT

        self.draw_hint(surface, "C or ESC to close")
        self.blit_panel(surface)
