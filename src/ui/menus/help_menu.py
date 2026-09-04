import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

# One control column: the key label, then the description beside it. Two of them side by
# side is what keeps the whole key map on screen without scrolling it.
COLUMN_WIDTH = 540
# Gap between the key column and the description that follows it.
COLUMN_GAP = 24
# Gap between the two columns of controls.
GUTTER = 40
LINE_HEIGHT = 26
ROW_GAP = 8
BOTTOM_MARGIN = 46

CONTROLS = [
    ("W / Z", "Move forward (aim with mouse)"),
    ("S", "Move backward"),
    ("W Z S Space", "Mash to pull free of a bear trap"),
    ("Shift", "Run"),
    ("Left Click", "Use the weapon in hand one (swing it or fire it)"),
    ("Right Click", "Use the weapon in hand two"),
    ("Space", "Hold to raise your shield: it covers the side it is worn on and turns shots away"),
    ("E", "Interact: talk, open a door, a chest, a bed, rest at a camp"),
    ("Loot", "Picked up by walking over it, no key needed"),
    ("B", "Trade with a merchant you are next to"),
    ("K", "Pay a village you have turned its blood price, so it lets you back in"),
    ("F", "Equip the last picked-up upgrade"),
    ("G", "Throw or lay the bomb in the bomb slot"),
    ("1", "Swap your two weapons over, hand one to hand two"),
    ("Q R T Y", "Drink the potion in that quickbar slot"),
    ("E", "In the bag or a shop: equip the best of everything carried"),
    ("S / U", "In a shop: sell every valuable / every unused piece of gear"),
    ("I", "Inventory"),
    ("J", "Quests"),
    ("C", "Character"),
    ("L", "Lore"),
    ("M", "Show/hide the map"),
    ("V", "Keep every villager's line of sight on screen, not only while you are stealing"),
    ("H", "Help"),
    ("P", "Pause"),
    ("Esc", "Close menu / pause"),
]


class HelpMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=2 * COLUMN_WIDTH + GUTTER + 40, height=HEADER_HEIGHT + 200)
        self._columns = None
        self._key_width = 0

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
        """Measure the rows once and deal them into two columns of roughly equal height.

        The description column starts after the widest key label, and a description too long
        for what is left of its column is wrapped rather than run off the edge. One column of
        every control was taller than the screen, so the panel was cut off at the top and the
        bottom; two columns is what makes the whole map fit on any screen the game runs at.
        Done here rather than in __init__ because the fonts are only loaded once the game has
        started."""
        if self._columns is not None:
            return

        self._key_width = max(c.Fonts.heading.size(key)[0] for key, _ in CONTROLS)
        max_width = COLUMN_WIDTH - self._key_width - COLUMN_GAP

        rows = [(key, widgets.wrap_text(description, c.Fonts.text, max_width)) for key, description in CONTROLS]
        heights = [len(lines) * LINE_HEIGHT + ROW_GAP for _, lines in rows]

        # Break where the first column has taken up half the total, so neither column is
        # left a head taller than the other.
        half = sum(heights) / 2
        split, run = len(rows), 0
        for i, height in enumerate(heights):
            if run + height / 2 >= half:
                split = i
                break
            run += height

        self._columns = [rows[:split], rows[split:]]
        body = max(sum(heights[:split]), sum(heights[split:]))
        self.height = min(HEADER_HEIGHT + 18 + body + BOTTOM_MARGIN, c.Screen.HEIGHT - 20)

    def draw(self):
        if not self.active:
            return

        self._layout()
        self.draw_overlay()
        surface = self.create_menu_surface("Controls")

        for column, rows in enumerate(self._columns):
            x = self.padding + column * (COLUMN_WIDTH + GUTTER)
            y = self.content_top
            for key, lines in rows:
                key_surf = c.Fonts.heading.render(key, True, c.Colors.ACCENT)
                surface.blit(key_surf, (x, y))

                for i, line in enumerate(lines):
                    desc_surf = c.Fonts.text.render(line, True, c.Colors.WHITE)
                    surface.blit(desc_surf, (x + self._key_width + COLUMN_GAP, y + i * LINE_HEIGHT))

                y += len(lines) * LINE_HEIGHT + ROW_GAP

        self.draw_hint(surface, "H or ESC to close")
        self.blit_panel(surface)
