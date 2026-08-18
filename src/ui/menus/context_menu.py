import math
import queue
import threading

import pygame

import core.constants as c
from ui import widgets
from ui.menus.base_menu import BaseMenu


class ContextMenu(BaseMenu):
    """The world's lore, in one of two presentations.

    Opening a session is the intro: the screen holds black, the lore is written onto it and
    nothing else is on screen, then the world fades up once the player dismisses it. That is
    the whole reason for the mode. The same text asked for mid-game with L is an ordinary
    panel over the world, which is what a reference wants to be.
    """

    # How long the world takes to come up once the opening text is dismissed.
    FADE_MS = 900

    def __init__(self, screen):
        super().__init__(screen, width=0, height=0)

        self.context_text = ""
        self._chunk_queue: queue.Queue = queue.Queue()
        self._generating = False
        self._ready = False
        self._lock = threading.Lock()
        # Whether this showing is the opening of a session (black screen) rather than the
        # lore looked up mid-game (panel), and when the opening was dismissed.
        self.intro = False
        self._faded_in_at = 0

    def start_streaming(self):
        """Open on black and start receiving streamed chunks. Always the opening of a new
        game: nothing else has been seen yet, and this is what the player reads first."""
        with self._lock:
            self.context_text = ""
            self._generating = True
            self._ready = False
            self.active = True
            self.intro = True

    def push_chunk(self, accumulated: str):
        """Called from background thread with the latest accumulated text."""
        self._chunk_queue.put(("chunk", accumulated))

    def finish_streaming(self):
        """Called from background thread once generation is complete."""
        self._chunk_queue.put(("done", None))

    def show(self, text: str, intro: bool = False):
        """Show an already generated context. `intro` is a continued game opening on it, held
        on black like a new one; without it this is the L key, a panel over the world."""
        with self._lock:
            self.context_text = text
            self._generating = False
            self._ready = True
            self.active = True
            self.just_active = True
            self.intro = intro
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
            if self.intro:
                self._faded_in_at = pygame.time.get_ticks()
            self.close()
            return True

        return True

    def draw_fade(self):
        """The world coming up out of the black the opening text was written on. Drawn over
        everything once the panel itself is gone, which is what makes the first frame of the
        game an arrival rather than a cut."""
        if not self._faded_in_at:
            return
        elapsed = pygame.time.get_ticks() - self._faded_in_at
        if elapsed >= self.FADE_MS:
            self._faded_in_at = 0
            return
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT))
        overlay.fill((0, 0, 0))
        overlay.set_alpha(round(255 * (1 - elapsed / self.FADE_MS)))
        self.screen.blit(overlay, (0, 0))

    def _draw_intro(self):
        """The opening: the lore alone on a black screen, with nothing else drawn anywhere.

        No panel and no dimmed world behind it, because both are what made this read as one
        more widget over a street full of villagers instead of the thing to read."""
        self.screen.fill((0, 0, 0))

        width = round(c.Screen.WIDTH * 0.52)
        lines = widgets.wrap_text(self.context_text, c.Fonts.text, width) if self.context_text else []
        line_height = 34
        block_height = len(lines) * line_height
        y = (c.Screen.HEIGHT - block_height) // 2

        rule_y = y - 46
        pygame.draw.line(
            self.screen,
            c.Colors.ACCENT,
            (c.Screen.WIDTH // 2 - width // 4, rule_y),
            (c.Screen.WIDTH // 2 + width // 4, rule_y),
            2,
        )

        for index, line in enumerate(lines):
            surface = c.Fonts.text.render(line, True, c.Colors.WHITE)
            self.screen.blit(surface, ((c.Screen.WIDTH - surface.get_width()) // 2, y + index * line_height))

        if self._ready:
            # Pulsed rather than static: it is the only thing on screen once the reading is
            # done, and it has to say the game is waiting on the player, not on itself.
            alpha = 150 + round(105 * abs(math.sin(pygame.time.get_ticks() / 700.0)))
            hint = c.Fonts.text.render("Press any key to enter the world", True, c.Colors.ACCENT)
            hint.set_alpha(alpha)
        else:
            hint = c.Fonts.text.render("The world is taking shape...", True, c.Colors.MUTED)
        self.screen.blit(hint, ((c.Screen.WIDTH - hint.get_width()) // 2, y + block_height + 60))

    def draw(self):
        if not self.active:
            return

        if self.intro:
            self._draw_intro()
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
