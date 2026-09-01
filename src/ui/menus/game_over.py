from __future__ import annotations

import sys

import pygame

import core.constants as c


def run_game_over(
    screen,
    clock,
    coins_lost: int,
    items_lost: int,
    debuff_duration_s: float,
    taunt: str = "",
    killer: str = "",
):
    """Blocking death screen. Holds for a beat, mocks the player, reports the penalty, then
    returns so the game can put them back at world spawn; the run continues, no main menu
    detour. `taunt` is written by the LLM ahead of time (llm/death_taunts.py) and never names
    the killer, so who did it goes on its own line above it."""
    lost = f"-{coins_lost} coins" + (f"  ·  -{items_lost} items" if items_lost else "")
    penalty_text = f"{lost}  ·  left where you fell"
    # The one place with room to say what the weakness actually costs, so the HUD chip
    # that follows the player around is read as a reminder rather than a mystery. The
    # numbers are what it costs at its worst: it eases off over the duration rather than
    # holding and then ending.
    weakness_text = (
        f"Weakened {int(debuff_duration_s)}s, fading:  "
        f"-{round((1 - c.Death.DEBUFF_DAMAGE_MULT) * 100)}% damage  ·  "
        f"-{round((1 - c.Death.DEBUFF_SPEED_MULT) * 100)}% speed  ·  "
        f"-{round((1 - c.Death.DEBUFF_MAX_HP_MULT) * 100)}% max HP"
    )
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

        def centered(surface, y):
            screen.blit(surface, ((c.Screen.WIDTH - surface.get_width()) // 2, y))

        centered(c.Fonts.big_title.render("You Died", True, c.Colors.RED), 280)

        if killer:
            centered(c.Fonts.title.render(f"Killed by {killer}", True, c.Colors.MUTED), 362)
        if taunt:
            # The model is asked for a short line but doesn't always oblige; a long one
            # drops a size rather than running off both edges of the screen.
            line = c.Fonts.title.render(taunt, True, (210, 150, 150))
            if line.get_width() > c.Screen.WIDTH - 80:
                line = c.Fonts.heading.render(taunt, True, (210, 150, 150))
            centered(line, 402)

        centered(c.Fonts.title.render(penalty_text, True, c.Colors.WHITE), 462)
        centered(c.Fonts.heading.render(weakness_text, True, c.Colors.MUTED), 502)
        centered(c.Fonts.title.render(f"Respawning in {remaining_ms // 1000 + 1}...", True, c.Colors.MUTED), 548)

        pygame.display.flip()
        clock.tick(60)
