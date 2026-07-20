import pygame

import core.constants as c
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

CONTROLS = [
    ("W / Z", "Move forward (aim with mouse)"),
    ("S", "Move backward"),
    ("Shift", "Run"),
    ("Left Click", "Attack"),
    ("E", "Interact, talk, pick up"),
    ("M", "Toggle menu buttons"),
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
        super().__init__(screen, width=480, height=HEADER_HEIGHT + len(CONTROLS) * 34 + 60)

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

        self.draw_overlay()
        surface = self.create_menu_surface("Controls")

        y = self.content_top
        key_x = self.padding
        desc_x = self.padding + 130
        for key, description in CONTROLS:
            key_surf = c.Fonts.heading.render(key, True, c.Colors.ACCENT)
            surface.blit(key_surf, (key_x, y))

            desc_surf = c.Fonts.text.render(description, True, c.Colors.WHITE)
            surface.blit(desc_surf, (desc_x, y))

            y += 34

        self.draw_hint(surface, "H or ESC to close")
        self.blit_panel(surface)
