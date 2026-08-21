"""Ground decals: blood splats left behind by hits and kills.

One global, session-only system, the same pattern as ParticleSystem: it draws during
both outdoor and interior rendering, so a splat left mid-fight in a room is still
there if the player steps out and back in. Capped so a long fight can't grow the
list forever.

Each splat is painted into its own little surface once at spawn and then blitted, so a
smear can be stretched and turned along the blow that made it without costing a rotate
per frame. A fresh one carries a wet highlight that dulls as it dries.
"""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c


class Decal:
    __slots__ = ("angle", "life", "max_life", "sheen", "surface", "x", "y")

    def __init__(self, x, y, radius, color, life, stretch: float = 1.0, angle: float = 0.0):
        self.x = x
        self.y = y
        self.life = life
        self.max_life = life
        self.angle = angle
        # How wet it still looks. A streak thrown from an artery glistens; a small drop
        # is dry almost at once, so the shine never turns into a field of glitter.
        self.sheen = min(1.0, radius / 14.0)
        self.surface = self._paint(radius, color, stretch, angle)

    @staticmethod
    def _paint(radius, color, stretch, angle) -> pygame.Surface:
        """A few overlapping irregular blobs, drawn once. `stretch` pulls them along the
        blow's direction, which is what turns a splat into a smear."""
        radius = max(1.0, radius)
        long_r = radius * stretch
        pad = 3
        size = (round(long_r * 2 + pad * 2), round(radius * 2 + pad * 2))
        surface = pygame.Surface(size, pygame.SRCALPHA)
        cx, cy = size[0] / 2, size[1] / 2

        for _ in range(random.randint(3, 5)):
            r = random.uniform(radius * 0.45, radius)
            # Along the smear, not around it: offsets scale with the stretch so the extra
            # length is filled in rather than leaving one blob at each end.
            ox = random.uniform(-long_r * 0.5, long_r * 0.5)
            oy = random.uniform(-radius * 0.45, radius * 0.45)
            tint = tuple(max(0, min(255, v + random.randint(-14, 14))) for v in color)
            blob = pygame.Rect(0, 0, round(r * 2 * max(1.0, stretch * 0.7)), round(r * 2))
            blob.center = (round(cx + ox), round(cy + oy))
            pygame.draw.ellipse(surface, tint, blob)

        # The thin tail a thrown droplet leaves behind it, only worth drawing on a smear.
        if stretch > 1.4:
            tail = pygame.Rect(0, 0, round(long_r * 1.8), max(2, round(radius * 0.5)))
            tail.center = (round(cx), round(cy))
            pygame.draw.ellipse(surface, color, tail)

        if angle:
            surface = pygame.transform.rotate(surface, -math.degrees(angle))
        return surface


class DecalSystem:
    def __init__(self):
        self.decals: list[Decal] = []

    def spawn(self, x, y, radius=10, color=(130, 18, 18), life=None, stretch=1.0, angle=0.0):
        self.decals.append(Decal(x, y, radius, color, life or c.Decals.LIFE_MS, stretch, angle))
        if len(self.decals) > c.Decals.MAX_COUNT:
            self.decals.pop(0)

    def spawn_spray(self, x, y, direction=None, count=8, distance=(16.0, 105.0), radius=(3.0, 9.0), color=None):
        """A fan of droplets flung out from a kill, thinning out with distance.

        `direction` is the killing blow's (dx, dy) unit vector: the spray goes that way,
        away from the attacker, so a death reads as directional. Without one (a burn tick,
        an execute) it sprays all round instead. Droplets land farther out but smaller,
        the way a real splatter falls off, and the ones thrown hardest land as smears
        pointing the way they travelled rather than as tidy dots.
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
                stretch=1.0 + reach * c.Decals.SMEAR_STRETCH,
                angle=angle,
            )

    def spawn_arcs(self, x, y, direction=None, count=3, length=(70.0, 190.0), color=None):
        """The long throws: a handful of arterial streaks laid out from the body, each a
        line of shrinking drops rather than one shape, so it reads as blood travelling."""
        base = math.atan2(direction[1], direction[0]) if direction else random.uniform(0, 2 * math.pi)
        spread = math.radians(c.Decals.ARC_SPREAD_DEG)
        near, far = length
        for _ in range(count):
            angle = base + random.uniform(-spread / 2, spread / 2)
            reach = random.uniform(near, far)
            drops = max(3, round(reach / 26))
            for step in range(drops):
                t = (step + 1) / drops
                jitter = random.uniform(-7, 7)
                self.spawn(
                    x + math.cos(angle) * reach * t - math.sin(angle) * jitter,
                    y + math.sin(angle) * reach * t + math.cos(angle) * jitter,
                    radius=max(2.0, 7.0 * (1.0 - t * 0.7)),
                    color=color or c.Decals.BLOOD_COLOR,
                    stretch=1.6 + t,
                    angle=angle,
                )

    def update(self, dt):
        alive = []
        for d in self.decals:
            d.life -= dt
            if d.life > 0:
                alive.append(d)
        self.decals = alive

    def draw(self, surface, camera, hidden=None):
        """`hidden(x, y)` is the same rule entities and items are drawn by
        (GameRenderer._hidden_indoors): a splat on another building's floor is under a roof
        that is still on, so it must not be painted over the top of that roof."""
        for d in self.decals:
            if hidden is not None and hidden(d.x, d.y):
                continue
            screen_x, screen_y = camera.world_to_screen(d.x, d.y)
            rect = d.surface.get_rect(center=(round(screen_x), round(screen_y)))
            if not rect.colliderect(surface.get_rect()):
                continue
            age = 1.0 - d.life / d.max_life
            fade_start = d.max_life * 0.25
            fade = min(1.0, d.life / fade_start) if d.life < fade_start else 1.0
            d.surface.set_alpha(int(c.Decals.ALPHA * fade))
            surface.blit(d.surface, rect)

            # Wet while it is fresh: one bright arc across the splat, gone within a few
            # seconds, which is what makes a kill land instead of just leaving a stain.
            wet = d.sheen * max(0.0, 1.0 - age / c.Decals.SHEEN_FRACTION)
            if wet > 0.05:
                gloss = pygame.Surface(rect.size, pygame.SRCALPHA)
                pygame.draw.ellipse(
                    gloss,
                    (120, 40, 40, int(70 * wet)),
                    gloss.get_rect().inflate(-rect.width * 0.7, -rect.height * 0.72),
                )
                surface.blit(gloss, rect, special_flags=pygame.BLEND_RGBA_ADD)


_system = None


def get_decals() -> DecalSystem:
    global _system
    if _system is None:
        _system = DecalSystem()
    return _system
