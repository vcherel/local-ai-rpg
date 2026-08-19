"""Ground decals: blood splats left behind by hits and kills.

One global, session-only system, the same pattern as ParticleSystem: it draws during
both outdoor and interior rendering, so a splat left mid-fight in a room is still
there if the player steps out and back in. Capped so a long fight can't grow the
list forever.
"""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c


class Decal:
    __slots__ = ("blobs", "color", "life", "max_life", "x", "y")

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

    def spawn_spray(self, x, y, direction=None, count=8, distance=(16.0, 105.0), radius=(3.0, 9.0), color=None):
        """A fan of droplets flung out from a kill, thinning out with distance.

        `direction` is the killing blow's (dx, dy) unit vector: the spray goes that way,
        away from the attacker, so a death reads as directional. Without one (a burn tick,
        an execute) it sprays all round instead. Droplets land farther out but smaller,
        the way a real splatter falls off.
        """
        base = math.atan2(direction[1], direction[0]) if direction else 0.0
        spread = math.radians(c.Decals.SPRAY_SPREAD_DEG) if direction else 2 * math.pi
        near, far = distance
        small, big = radius
        for _ in range(count):
            angle = base + random.uniform(-spread / 2, spread / 2)
            # Squaring the roll clusters droplets near the body, with a few thrown wide.
            reach = random.random() ** 2
            dist = near + (far - near) * reach
            self.spawn(
                x + math.cos(angle) * dist,
                y + math.sin(angle) * dist,
                radius=big - (big - small) * reach,
                color=color or c.Decals.BLOOD_COLOR,
            )

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
