from __future__ import annotations

import sys

import pygame

import core.constants as c


def run_game_over(screen, clock, coins_lost: int, debuff_duration_s: float):
    """Blocking death screen. Holds for a beat, reports the penalty, then returns so the
    game can put the player back at world spawn; the run continues, no main menu detour."""
    penalty_text = f"-{coins_lost} coins  ·  Shaken for {int(debuff_duration_s)}s"
    end_at = pygame.time.get_ticks() + int(c.Death.RESPAWN_DELAY_S * 1000)

    while True:
        remaining_ms = end_at - pygame.time.get_ticks()
        if remaining_ms <= 0:
            return

        # Input is swallowed rather than acted on: a key held down as the player died
        # shouldn't skip the screen or leak into the world once it closes.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        screen.fill(c.Colors.MENU_BACKGROUND)

        title_text = c.Fonts.big_title.render("You Died", True, c.Colors.RED)
        title_x = (c.Screen.WIDTH - title_text.get_width()) // 2
        screen.blit(title_text, (title_x, 200))

        penalty_surface = c.Fonts.title.render(penalty_text, True, c.Colors.WHITE)
        penalty_x = (c.Screen.WIDTH - penalty_surface.get_width()) // 2
        screen.blit(penalty_surface, (penalty_x, 280))

        hint = c.Fonts.title.render(f"Respawning in {remaining_ms // 1000 + 1}...", True, c.Colors.MUTED)
        screen.blit(hint, ((c.Screen.WIDTH - hint.get_width()) // 2, 360))

        pygame.display.flip()
        clock.tick(60)
