from __future__ import annotations

import sys

import pygame

import core.constants as c
from ui import widgets


def run_game_over(screen, clock):
    """Blocking Game Over screen. Returns once the player chooses to continue."""
    button_width = 300
    button_height = 60

    center_x = c.Screen.WIDTH // 2 - button_width // 2
    center_y = c.Screen.HEIGHT // 2 + 40
    menu_button = pygame.Rect(center_x, center_y, button_width, button_height)

    while True:
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if menu_button.collidepoint(event.pos):
                    return
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                return

        screen.fill(c.Colors.MENU_BACKGROUND)

        title_text = c.Fonts.big_title.render("Game Over", True, c.Colors.RED)
        title_x = (c.Screen.WIDTH - title_text.get_width()) // 2
        screen.blit(title_text, (title_x, 200))

        hover = menu_button.collidepoint(mouse_pos)
        pressed = pygame.mouse.get_pressed()[0] and hover
        widgets.draw_button(screen, menu_button, "Main Menu", c.Fonts.title, hovered=hover, pressed=pressed)

        pygame.display.flip()
        clock.tick(60)
