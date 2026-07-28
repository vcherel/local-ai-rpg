import queue

import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import HEADER_HEIGHT, BaseMenu

LINE_SPACING = 28
# The panel pops up on its own, so a key or click already in flight when it opens would
# close it before it was ever read. Input is swallowed for this long after it appears.
INPUT_GRACE_MS = 400


class RumorMenu(BaseMenu):
    """Panel showing one whispered rumour until the player dismisses it.

    Rumours are LLM sentences generated on a background thread, far too long to read in
    the passing loot toast, so they get a panel that waits for a keypress instead of
    expiring on a timer. Text arrives through a queue and only opens once no other menu
    is up, so a rumour never lands on top of a dialogue or a shop.
    """

    def __init__(self, screen):
        super().__init__(screen, width=0, height=0)
        self.header_height = HEADER_HEIGHT
        self.text = ""
        self.opened_at = 0
        self._pending: queue.Queue = queue.Queue()

    def push(self, text: str):
        """Queue a rumour. Safe to call from the thread that generated it."""
        self._pending.put(text)

    def update(self, menu_open: bool):
        """Open the next queued rumour once the screen is free."""
        if self.active or menu_open:
            return

        try:
            self.text = self._pending.get_nowait()
        except queue.Empty:
            return

        self._layout()
        self.active = True
        self.just_active = True
        self.opened_at = pygame.time.get_ticks()

    def _layout(self):
        lines = widgets.wrap_text(self.text, c.Fonts.text, c.Screen.WIDTH * 0.3)
        widest = max((c.Fonts.text.size(line)[0] for line in lines), default=0)
        self.width = max(widest + 2 * self.padding, 460)
        self.height = self.content_top + len(lines) * LINE_SPACING + 70

    def handle_event(self, event) -> bool:
        if not self.active:
            return False

        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            if pygame.time.get_ticks() - self.opened_at >= INPUT_GRACE_MS:
                self.close()

        return True

    def draw(self):
        if not self.active:
            return

        self.draw_overlay()
        surface = self.create_menu_surface("Rumour")

        self.draw_wrapped_text(
            surface,
            self.text,
            self.padding,
            self.content_top,
            self.width - 2 * self.padding,
            line_spacing=LINE_SPACING,
        )

        self.draw_hint(surface, "Press any key to close")
        self.blit_panel(surface)
