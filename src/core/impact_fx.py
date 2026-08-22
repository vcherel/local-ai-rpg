"""The picture an area effect leaves behind it: a wave of particles going out and a bolt to
each thing it caught.

Chain Strike used to be invisible. A legendary weapon would land one blow and damage
numbers would pop on three creatures at once with nothing on screen connecting them,
which reads as a bug rather than as an affix. So the pulse draws itself: a ring expanding
to exactly the radius the damage was applied over, and a jagged bolt from its centre to
everything it actually hit, so what was caught is attributable rather than guessed.

What goes out is a scatter of particles thrown round the source rather than one drawn
circle: a perfect ring reads as a UI element laid over the fight, while a wave of debris
reads as something having gone off there. The radius they are thrown to is still exactly
the radius the damage was applied over, so the promise the picture makes is unchanged.

Session-only global in the same shape as particles, swing arcs and decals: updated once
per frame from `Game.run`, drawn from `GameRenderer.draw_world`, never saved.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.particles import get_particles

if TYPE_CHECKING:
    from core.camera import Camera


class ImpactPulse:
    """One pulse: the bolts out to each point it struck. The wave itself is particles, thrown
    at the moment of the hit (`ImpactFxSystem.pulse`); what is left here is the part that has
    to be drawn as lines. Anchored to the world where the blow landed, not to whatever was
    standing there, since that may well be dead before the pulse finishes."""

    def __init__(self, x, y, radius, color, struck):
        self.x = x
        self.y = y
        self.radius = radius
        self.color = color
        # Where the bolts go, sampled at the moment of the hit for the same reason.
        self.struck = list(struck)
        self.age = 0.0

    @property
    def dead(self) -> bool:
        return self.age >= c.ImpactFx.RING_MS

    def update(self, dt):
        self.age += dt

    def _bolt(self, start, end):
        """A line broken into a few jagged segments, so the reach reads as a discharge
        rather than as a laser pointer."""
        points = [start]
        segments = c.ImpactFx.BOLT_SEGMENTS
        for i in range(1, segments):
            t = i / segments
            mx = start[0] + (end[0] - start[0]) * t
            my = start[1] + (end[1] - start[1]) * t
            jitter = c.ImpactFx.BOLT_JITTER * (1 - abs(0.5 - t) * 2)
            points.append((mx + random.uniform(-jitter, jitter), my + random.uniform(-jitter, jitter)))
        points.append(end)
        return points

    def draw(self, layer: pygame.Surface, camera: Camera):
        progress = min(1.0, self.age / c.ImpactFx.RING_MS)
        # The bolts only last the first part of the pulse's life: they say what was hit on
        # the frame it was hit, and then get out of the way of the fight.
        if progress > c.ImpactFx.BOLT_LIFE_FRAC:
            return
        alpha = round(210 * (1.0 - progress) ** 1.6)
        bolt_alpha = round(alpha * (1 - progress / c.ImpactFx.BOLT_LIFE_FRAC))
        if bolt_alpha <= 2:
            return
        center = camera.world_to_screen(self.x, self.y)
        for wx, wy in self.struck:
            end = camera.world_to_screen(wx, wy)
            pygame.draw.lines(layer, (*self.color, bolt_alpha), False, self._bolt(center, end), c.ImpactFx.BOLT_WIDTH)


class ImpactFxSystem:
    def __init__(self):
        self.rings: list[ImpactPulse] = []

    def pulse(self, x, y, radius, color, struck=()):
        """Throw the wave and keep the bolts. The particles are spread all round the source
        and out to the radius the damage covered, thinning as they go, with a bright puff at
        the middle so where it went off is never in question."""
        self.rings.append(ImpactPulse(x, y, radius, color, struck))
        particles = get_particles()
        if radius > 0:
            count = max(c.ImpactFx.WAVE_MIN, round(radius / c.ImpactFx.WAVE_PER_PIXELS))
            for i in range(count):
                # Spread round the circle with a wobble on both the angle and the distance,
                # so the wave never comes out as beads on a wire.
                angle = 2 * math.pi * (i + random.uniform(-0.35, 0.35)) / count
                reach = radius * random.uniform(c.ImpactFx.WAVE_INNER, 1.0)
                particles.spawn_directional_burst(
                    x + math.cos(angle) * reach,
                    y + math.sin(angle) * reach,
                    angle,
                    spread_deg=40.0,
                    color=color,
                    count=2,
                    speed=c.ImpactFx.WAVE_SPEED,
                    life=c.ImpactFx.WAVE_LIFE_MS,
                    size=c.ImpactFx.WAVE_SIZE,
                    gravity=0.12,
                )
        particles.spawn_burst(
            x, y, color, count=c.ImpactFx.CORE_PARTICLES, speed=3.0, life=c.ImpactFx.WAVE_LIFE_MS, size=6
        )

    def update(self, dt):
        for ring in self.rings:
            ring.update(dt)
        self.rings = [ring for ring in self.rings if not ring.dead]

    def draw(self, surface: pygame.Surface, camera: Camera):
        """One transparent layer for every pulse in flight, blitted once, exactly as the
        swing arcs are drawn: they need per-pixel alpha to fade, and a surface each would
        mean a full-screen allocation per hit."""
        if not self.rings:
            return
        layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for ring in self.rings:
            ring.draw(layer, camera)
        surface.blit(layer, (0, 0))


_impacts = None


def get_impacts() -> ImpactFxSystem:
    global _impacts
    if _impacts is None:
        _impacts = ImpactFxSystem()
    return _impacts
