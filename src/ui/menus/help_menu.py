import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

WIDTH = 660
# Gap between the key column and the description that follows it.
COLUMN_GAP = 24
LINE_HEIGHT = 26
ROW_GAP = 8

CONTROLS = [
    ("W / Z", "Move forward (aim with mouse)"),
    ("S", "Move backward"),
    ("Shift", "Run"),
    ("Left Click", "Attack with melee weapon"),
    ("Right Click", "Fire equipped bow/staff"),
    ("Space", "Hold to raise your shield and block"),
    ("E", "Interact, talk, pick up, open a door, rest at a camp"),
    ("B", "Trade with a merchant you are next to"),
    ("F", "Equip the last picked-up upgrade"),
    ("1 - 3", "Draw the weapon in that bar slot"),
    ("Q R T Y", "Drink the potion in that quickbar slot"),
    ("I", "Inventory"),
    ("J", "Quests"),
    ("C", "Character"),
    ("L", "Lore"),
    ("M", "Show/hide the map"),
    ("H", "Help"),
    ("P", "Pause"),
    ("Esc", "Close menu / pause"),
]


class HelpMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=WIDTH, height=HEADER_HEIGHT + len(CONTROLS) * 34 + 60)
        self._rows = None
        self._desc_x = 0

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_h, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.close()

        return True

    def _layout(self):
        """Measure the rows once: the description column starts after the widest key label,
        and a description too long for what is left of the panel is wrapped rather than run
        off its edge. Done here rather than in __init__ because the fonts are only loaded
        once the game has started."""
        if self._rows is not None:
            return

        self._desc_x = self.padding + max(c.Fonts.heading.size(key)[0] for key, _ in CONTROLS) + COLUMN_GAP
        max_width = self.width - self._desc_x - self.padding

        self._rows = [(key, widgets.wrap_text(description, c.Fonts.text, max_width)) for key, description in CONTROLS]
        body = sum(len(lines) * LINE_HEIGHT + ROW_GAP for _, lines in self._rows)
        self.height = HEADER_HEIGHT + 18 + body + 46

    def draw(self):
        if not self.active:
            return

        self._layout()
        self.draw_overlay()
        surface = self.create_menu_surface("Controls")

        y = self.content_top
        for key, lines in self._rows:
            key_surf = c.Fonts.heading.render(key, True, c.Colors.ACCENT)
            surface.blit(key_surf, (self.padding, y))

            for i, line in enumerate(lines):
                desc_surf = c.Fonts.text.render(line, True, c.Colors.WHITE)
                surface.blit(desc_surf, (self._desc_x, y + i * LINE_HEIGHT))

            y += len(lines) * LINE_HEIGHT + ROW_GAP

        self.draw_hint(surface, "H or ESC to close")
        self.blit_panel(surface)
