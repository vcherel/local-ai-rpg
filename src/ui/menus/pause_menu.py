import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import BaseMenu

BUTTON_WIDTH = 200
BUTTON_HEIGHT = 44
BUTTON_SPACING = 12


class PauseMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=360, height=240)
        self.save_button_rect = None
        self.quit_button_rect = None

    def _button_rects(self) -> tuple[pygame.Rect, pygame.Rect]:
        x = (self.width - BUTTON_WIDTH) // 2
        save = pygame.Rect(x, self.content_top + 8, BUTTON_WIDTH, BUTTON_HEIGHT)
        quit_rect = pygame.Rect(x, save.bottom + BUTTON_SPACING, BUTTON_WIDTH, BUTTON_HEIGHT)
        return save, quit_rect

    def handle_event(self, event, on_save=None, on_quit=None) -> bool:
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
            elif self.quit_button_rect and self.quit_button_rect.collidepoint(rel):
                self.close()
                if on_quit:
                    on_quit()
            else:
                # Click anywhere else resumes.
                self.close()

        return True

    def draw(self):
        if not self.active:
            return

        self.draw_overlay()
        surface = self.create_menu_surface("Paused")

        self.save_button_rect, self.quit_button_rect = self._button_rects()
        menu_x, menu_y = self.get_centered_position()
        mouse_x, mouse_y = pygame.mouse.get_pos()

        save_hovered = self.save_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(surface, self.save_button_rect, "Save game", c.Fonts.button, hovered=save_hovered)

        quit_hovered = self.quit_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(surface, self.quit_button_rect, "Quit to menu", c.Fonts.button, hovered=quit_hovered)

        self.draw_hint(surface, "P, Esc or click to resume")
        self.blit_panel(surface)
