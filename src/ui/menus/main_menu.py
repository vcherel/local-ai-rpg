from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets

if TYPE_CHECKING:
    from core.save import SaveSystem


class MainMenu:
    def __init__(self, screen, save_system):
        self.screen: pygame.Surface = screen
        self.save_system: SaveSystem = save_system
        self.active = True

        self.button_width = 300
        self.button_height = 60
        self.button_spacing = 20

        center_x = c.Screen.WIDTH // 2 - self.button_width // 2
        center_y = c.Screen.HEIGHT // 2 - self.button_height

        self.new_game_button = pygame.Rect(center_x, center_y, self.button_width, self.button_height)
        self.continue_button = pygame.Rect(
            center_x, center_y + self.button_height + self.button_spacing, self.button_width, self.button_height
        )

    def handle_click(self, pos):
        if self.new_game_button.collidepoint(pos):
            self.save_system.clear()
            self.active = False
            return "new_game"
        elif self.continue_button.collidepoint(pos):
            return "continue"
        return None

    def draw_button(self, rect: pygame.Rect, text, mouse_pos, pressed):
        hover = rect.collidepoint(mouse_pos)
        widgets.draw_button(self.screen, rect, text, c.Fonts.title, hovered=hover, pressed=pressed and hover)

    def draw(self):
        if not self.active:
            return

        self.screen.fill(c.Colors.MENU_BACKGROUND)

        title_text = c.Fonts.big_title.render("AI RPG", True, c.Colors.WHITE)
        title_x = (self.screen.get_width() - title_text.get_width()) // 2
        title_y = 150
        self.screen.blit(title_text, (title_x, title_y))
        underline_y = title_y + title_text.get_height() + 6
        pygame.draw.line(
            self.screen,
            c.Colors.ACCENT,
            (title_x, underline_y),
            (title_x + title_text.get_width(), underline_y),
            3,
        )

        mouse_pos = pygame.mouse.get_pos()
        pressed = pygame.mouse.get_pressed()[0]

        self.draw_button(self.new_game_button, "New Game", mouse_pos, pressed)
        self.draw_button(self.continue_button, "Continue", mouse_pos, pressed)


def run_main_menu(screen, clock, save_system):
    main_menu = MainMenu(screen, save_system)

    while main_menu.active:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    if main_menu.handle_click(event.pos):
                        return True

        main_menu.draw()
        pygame.display.flip()
        clock.tick(60)

    return True
