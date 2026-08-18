from __future__ import annotations

import sys

import pygame

import core.constants as c
from ui import widgets
from ui.menus.menu_scene import MenuScene


class MainMenu:
    """The title screen: two buttons over a village going about its day (`MenuScene`).

    The scene is the point of it. What is behind the title is the same generator, the same
    houses and the same people the game itself is made of, running live, so the first thing
    seen says what this is rather than being a dark rectangle with the game's name on it.
    """

    def __init__(self, screen):
        self.screen: pygame.Surface = screen
        self.active = True
        self.scene = MenuScene(screen)

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
            self.active = False
            return "new_game"
        elif self.continue_button.collidepoint(pos):
            self.active = False
            return "continue"
        return None

    def draw_button(self, rect: pygame.Rect, text, mouse_pos, pressed):
        hover = rect.collidepoint(mouse_pos)
        widgets.draw_button(self.screen, rect, text, c.Fonts.title, hovered=hover, pressed=pressed and hover)

    def draw(self, dt):
        if not self.active:
            return

        self.scene.update(dt)
        self.scene.draw()
        # A wash over the whole scene: the village behind still reads, the title and the
        # buttons on top of it stay legible whatever the sky is doing.
        veil = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        veil.fill((*c.Colors.MENU_BACKGROUND, 130))
        self.screen.blit(veil, (0, 0))

        title_text = c.Fonts.big_title.render("AI RPG", True, c.Colors.WHITE)
        title_x = (self.screen.get_width() - title_text.get_width()) // 2
        title_y = 150
        # A dark plate under the letters, so the title holds up over a lit street as well
        # as over a night one.
        shadow = c.Fonts.big_title.render("AI RPG", True, (0, 0, 0))
        self.screen.blit(shadow, (title_x + 3, title_y + 3))
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


def run_main_menu(screen, clock) -> str:
    """Blocking title screen. Returns the chosen action: "new_game" or "continue"."""
    main_menu = MainMenu(screen)

    while main_menu.active:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    choice = main_menu.handle_click(event.pos)
                    if choice:
                        return choice

        main_menu.draw(clock.get_time())
        pygame.display.flip()
        clock.tick(60)

    return "continue"
