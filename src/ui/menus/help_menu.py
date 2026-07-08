import pygame

import core.constants as c
from ui.menus.base_menu import BaseMenu

CONTROLS = [
    ("W / Z", "Move forward (aim with mouse)"),
    ("S", "Move backward"),
    ("Shift", "Run"),
    ("Left Click", "Attack"),
    ("E", "Interact, talk, pick up"),
    ("I", "Inventory"),
    ("Q", "Quests"),
    ("C", "Character"),
    ("L", "Lore"),
    ("H", "Help"),
    ("P", "Pause"),
    ("Esc", "Close menu / pause"),
]


class HelpMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=460, height=80 + len(CONTROLS) * 34)

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_h, pygame.K_ESCAPE):
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

        title = c.Fonts.title.render("Controls", True, c.Colors.WHITE)
        surface.blit(title, ((self.width - title.get_width()) // 2, self.padding))

        y = self.padding + 55
        key_x = self.padding
        desc_x = self.padding + 130
        for key, description in CONTROLS:
            key_surf = c.Fonts.heading.render(key, True, c.Colors.YELLOW)
            surface.blit(key_surf, (key_x, y))

            desc_surf = c.Fonts.text.render(description, True, c.Colors.WHITE)
            surface.blit(desc_surf, (desc_x, y))

            y += 34

        hint = c.Fonts.small.render("H or ESC to close", True, c.Colors.BORDER)
        surface.blit(hint, ((self.width - hint.get_width()) // 2, self.height - self.padding - hint.get_height()))

        self.screen.blit(surface, (menu_x, menu_y))
