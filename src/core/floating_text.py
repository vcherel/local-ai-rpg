"""Floating combat text: damage numbers popping up and fading over a hit."""

from __future__ import annotations

import random

import core.constants as c


class FloatingText:
    __slots__ = ("big", "color", "drift_x", "life", "max_life", "text", "x", "y")

    def __init__(self, x, y, text, color, life, big):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.life = life
        self.max_life = life
        self.big = big
        self.drift_x = random.uniform(-0.3, 0.3)


class FloatingTextSystem:
    def __init__(self):
        self.entries: list[FloatingText] = []

    def spawn(self, x, y, text, color=c.Colors.WHITE, big=False, life=700):
        # Small random x offset so several numbers popping at once don't stack exactly.
        self.entries.append(FloatingText(x + random.uniform(-8, 8), y, text, color, life, big))

    def update(self, dt):
        factor = dt * c.TARGET_FPS / 1000.0
        alive = []
        for e in self.entries:
            e.life -= dt
            if e.life <= 0:
                continue
            e.x += e.drift_x * factor
            alive.append(e)
        self.entries = alive

    def draw(self, surface, camera):
        for e in self.entries:
            t = 1 - e.life / e.max_life
            rise = t * 34
            screen_x, screen_y = camera.world_to_screen(e.x, e.y - rise)
            if not (0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT):
                continue
            alpha = 255 if t < 0.6 else max(0, int(255 * (1 - (t - 0.6) / 0.4)))
            font = c.Fonts.heading if e.big else c.Fonts.small
            shadow = font.render(e.text, True, (0, 0, 0))
            label = font.render(e.text, True, e.color)
            shadow.set_alpha(alpha)
            label.set_alpha(alpha)
            rect = label.get_rect(center=(screen_x, screen_y))
            surface.blit(shadow, (rect.x + 1, rect.y + 2))
            surface.blit(label, rect)


_system = None


def get_floating_text() -> FloatingTextSystem:
    global _system
    if _system is None:
        _system = FloatingTextSystem()
    return _system
