import queue
import threading

import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import BaseMenu


class ContextMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=0, height=0)

        self.context_text = ""
        self._chunk_queue: queue.Queue = queue.Queue()
        self._generating = False
        self._ready = False
        self._lock = threading.Lock()

    def start_streaming(self):
        """Open the panel and start receiving streamed chunks. Blocks the game."""
        with self._lock:
            self.context_text = ""
            self._generating = True
            self._ready = False
            self.active = True

    def push_chunk(self, accumulated: str):
        """Called from background thread with the latest accumulated text."""
        self._chunk_queue.put(("chunk", accumulated))

    def finish_streaming(self):
        """Called from background thread once generation is complete."""
        self._chunk_queue.put(("done", None))

    def show(self, text: str):
        """Show a pre-generated context and wait for the player to start."""
        with self._lock:
            self.context_text = text
            self._generating = False
            self._ready = True
            self.active = True
            self.just_active = True
            self._calculate_dimensions()

    def update(self):
        if not self.active:
            return

        changed = False
        try:
            while True:
                kind, data = self._chunk_queue.get_nowait()
                if kind == "chunk":
                    self.context_text = data
                    changed = True
                elif kind == "done":
                    self._generating = False
                    self._ready = True
                    changed = True
        except queue.Empty:
            pass

        if changed:
            self._calculate_dimensions()

    def _calculate_dimensions(self):
        if not self.context_text:
            return

        lines = widgets.wrap_text(self.context_text, c.Fonts.text, c.Screen.WIDTH * 0.35)

        max_line_width = max(
            (c.Fonts.text.render(line, True, c.Colors.WHITE).get_width() for line in lines),
            default=0,
        )

        self.width = max(max_line_width + 60, 300)
        self.height = max(len(lines) * 25 + 130, 180)

    def handle_event(self, event):
        if not self.active:
            return False

        if self._ready and event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self.close()
            return True

        return True

    def draw(self):
        if not self.active:
            return

        self.draw_overlay()

        if not self.context_text:
            return

        window_x, window_y = self.get_centered_position()
        menu_surface = self.create_menu_surface()

        title = c.Fonts.heading.render("World Context", True, c.Colors.WHITE)
        title_x = (self.width - title.get_width()) // 2
        menu_surface.blit(title, (title_x, 20))

        self.draw_wrapped_text(menu_surface, self.context_text, 30, 70, self.width - 60)

        if self._ready:
            hint_color = c.Colors.WHITE
            hint = c.Fonts.text.render("Press any key to close", True, hint_color)
        else:
            hint_color = (150, 150, 150)
            hint = c.Fonts.text.render("Generating...", True, hint_color)

        hint_x = (self.width - hint.get_width()) // 2
        menu_surface.blit(hint, (hint_x, self.height - 35))

        self.screen.blit(menu_surface, (window_x, window_y))
