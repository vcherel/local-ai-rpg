import pygame

import core.constants as c
from ui.menus.base_menu import BaseMenu


class PauseMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=320, height=150)

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_p, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.close()

        return True

    def draw(self):
        if not self.active:
            return

        menu_x, menu_y = self.get_centered_position()
        self.draw_overlay()
        surface = self.create_menu_surface()

        title = c.Fonts.title.render("Paused", True, c.Colors.WHITE)
        surface.blit(title, ((self.width - title.get_width()) // 2, self.padding))

        hint = c.Fonts.small.render("P, Esc or click to resume", True, c.Colors.BORDER)
        surface.blit(hint, ((self.width - hint.get_width()) // 2, self.height - self.padding - hint.get_height()))

        self.screen.blit(surface, (menu_x, menu_y))
