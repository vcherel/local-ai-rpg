from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui.menus.base_menu import BaseMenu

if TYPE_CHECKING:
    from game.entities.player import Player


ROW_HEIGHT = 72
TALLY_ROW_HEIGHT = 52


class StatsMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=620, height=712 + TALLY_ROW_HEIGHT * 2 + 10)

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_c, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.close()

        return True

    def draw(self, player: Player, record=None):
        if not self.active:
            return

        self.draw_overlay()
        surface = self.create_menu_surface("Character")

        stats = player.stats
        rows = [
            ("strength", f"+{stats.attack_bonus()} attack damage"),
            ("resistance", f"-{stats.damage_reduction()} damage taken"),
            ("speed", f"+{round((stats.speed_multiplier() - 1) * 100)}% move speed"),
            ("vitality", f"{stats.max_hp()} max HP"),
            (
                "magic",
                f"+{stats.magic_bonus()} bolt damage, {stats.max_mana()} mana, "
                f"{round(stats.mana_regen_rate() * 1000, 1)} mana/s",
            ),
            (
                "bartering",
                f"buy {round((1 - stats.buy_multiplier()) * 100)}% cheaper, "
                f"sell {round((stats.sell_multiplier() - 1) * 100)}% higher",
            ),
            (
                "persuasion",
                f"+{round(stats.quest_reward_weights()[4] - c.Rarity.QUEST_REWARD_WEIGHTS[4])}pt "
                "legendary quest reward odds, NPCs more receptive",
            ),
            ("swimming", f"cross water at {round(stats.swim_multiplier() * 100)}% of walking pace"),
        ]

        bar_w = self.width - self.padding * 2
        y = self.content_top
        for key, effect in rows:
            name_surf = c.Fonts.heading.render(c.STAT_LABELS[key], True, c.Colors.WHITE)
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

        if record is not None:
            self._draw_tally(surface, record, y)

        self.draw_hint(surface, "C or ESC to close")
        self.blit_panel(surface)

    def _draw_tally(self, surface, record, y: int):
        """The two numbers that are not stats: quests handed in and deaths. Drawn under the
        ladders, with the next milestone each of them is walking toward, so both read as
        something going somewhere rather than as a scoreboard."""
        pygame.draw.line(surface, c.Colors.SLOT_BORDER, (self.padding, y - 6), (self.width - self.padding, y - 6), 1)
        rows = (
            ("Quests completed", record.quests_done, self._next_quest_note(record)),
            ("Deaths", record.deaths, self._next_death_note(record)),
        )
        for label, value, note in rows:
            name = c.Fonts.heading.render(label, True, c.Colors.WHITE)
            surface.blit(name, (self.padding, y))
            count = c.Fonts.heading.render(str(value), True, c.Colors.ACCENT)
            surface.blit(count, (self.width - self.padding - count.get_width(), y))
            if note:
                hint = c.Fonts.small.render(note, True, c.Colors.MUTED)
                surface.blit(hint, (self.padding, y + 26))
            y += TALLY_ROW_HEIGHT

    @staticmethod
    def _next_quest_note(record) -> str:
        nxt = next(((count, rarity) for count, rarity in c.Milestones.QUESTS if count > record.quests_done), None)
        if nxt is None:
            return "every milestone claimed"
        count, rarity = nxt
        article = "an" if rarity[0] in "aeiou" else "a"
        return f"{count - record.quests_done} more for {article} {rarity} reward"

    @staticmethod
    def _next_death_note(record) -> str:
        nxt = next((count for count in c.Milestones.DEATHS if count > record.deaths), None)
        if nxt is None:
            return "death has run out of new things to say"
        return f"{nxt - record.deaths} more and death finds new words for you"
