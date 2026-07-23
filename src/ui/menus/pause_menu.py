import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import BaseMenu

BUTTON_WIDTH = 200
BUTTON_HEIGHT = 44


class PauseMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=360, height=200)
        self.save_button_rect = None

    def _button_rect(self) -> pygame.Rect:
        x = (self.width - BUTTON_WIDTH) // 2
        return pygame.Rect(x, self.content_top + 8, BUTTON_WIDTH, BUTTON_HEIGHT)

    def handle_event(self, event, on_save=None) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_p, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            menu_x, menu_y = self.get_centered_position()
            rel = (event.pos[0] - menu_x, event.pos[1] - menu_y)
            if self.save_button_rect and self.save_button_rect.collidepoint(rel):
                if on_save:
                    on_save()
                self.close()
            else:
                # Click anywhere else resumes.
                self.close()

        return True

    def draw(self):
        if not self.active:
            return

        self.draw_overlay()
        surface = self.create_menu_surface("Paused")

        self.save_button_rect = self._button_rect()
        menu_x, menu_y = self.get_centered_position()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        hovered = self.save_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(surface, self.save_button_rect, "Save game", c.Fonts.button, hovered=hovered)

        self.draw_hint(surface, "P, Esc or click to resume")
        self.blit_panel(surface)
