import pygame

from ui.menus.base_menu import BaseMenu


class PauseMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=360, height=170)

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

        self.draw_overlay()
        surface = self.create_menu_surface("Paused")

        self.draw_hint(surface, "P, Esc or click to resume")
        self.blit_panel(surface)
