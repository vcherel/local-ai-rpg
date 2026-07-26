"""Ground decals: blood splats left behind by hits and kills.

One global, session-only system, the same pattern as ParticleSystem: it draws during
both outdoor and interior rendering, so a splat left mid-fight in a room is still
there if the player steps out and back in. Capped so a long fight can't grow the
list forever.
"""

from __future__ import annotations

import random

import pygame

import core.constants as c


class Decal:
    __slots__ = ("x", "y", "blobs", "life", "max_life", "color")

    def __init__(self, x, y, radius, color, life):
        self.x = x
        self.y = y
        self.life = life
        self.max_life = life
        # A few overlapping irregular blobs read as an organic splat instead of a
        # perfect circle; offsets/sizes are fixed at spawn so the shape stays stable.
        count = random.randint(2, 4)
        self.blobs = [
            (
                random.uniform(-radius * 0.5, radius * 0.5),
                random.uniform(-radius * 0.5, radius * 0.5),
                random.uniform(radius * 0.5, radius),
            )
            for _ in range(count)
        ]
        self.color = tuple(max(0, min(255, v + random.randint(-12, 12))) for v in color)


class DecalSystem:
    def __init__(self):
        self.decals: list[Decal] = []

    def spawn(self, x, y, radius=10, color=(130, 18, 18), life=None):
        self.decals.append(Decal(x, y, radius, color, life or c.Decals.LIFE_MS))
        if len(self.decals) > c.Decals.MAX_COUNT:
            self.decals.pop(0)

    def update(self, dt):
        alive = []
        for d in self.decals:
            d.life -= dt
            if d.life > 0:
                alive.append(d)
        self.decals = alive

    def draw(self, surface, camera):
        for d in self.decals:
            screen_x, screen_y = camera.world_to_screen(d.x, d.y)
            fade_start = d.max_life * 0.25
            fade = min(1.0, d.life / fade_start) if d.life < fade_start else 1.0
            alpha = int(150 * fade)
            for ox, oy, r in d.blobs:
                sx, sy = screen_x + ox, screen_y + oy
                radius = max(1, int(r))
                if not (-radius <= sx <= c.Screen.WIDTH + radius and -radius <= sy <= c.Screen.HEIGHT + radius):
                    continue
                blob = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(blob, (*d.color, alpha), (radius, radius), radius)
                surface.blit(blob, (sx - radius, sy - radius))


_system = None


def get_decals() -> DecalSystem:
    global _system
    if _system is None:
        _system = DecalSystem()
    return _system
