"""The trail a melee attack leaves behind it.

A swing used to be invisible: the arm animated, particles popped on whatever was hit, and
nothing on screen said how much ground the blow actually covered. That is fine for a
dagger and useless for a cleaving weapon, where the whole point is the crowd it catches.
So an arc is drawn along the exact wedge the hit test uses (the weapon's `arc_deg` at its
reach), and a cleaving weapon draws it wider and hotter than a single-target one.

A thrust is drawn from the same rule and comes out as a different picture, because it is
tested differently: a `pierce_melee` weapon covers a lane down its facing rather than a
wedge, so it draws that lane, blind spot and all. Both live in the one system and both
promise exactly what their hit test accepts.

Session-only global in the same shape as particles, floating text and decals: updated once
per frame from `Game.run`, drawn from `GameRenderer.draw_world`, never saved.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera


class SwingArc:
    """One swing's trail: a wedge centred on where the swinger stood, sweeping across its
    span as it fades. Anchored to the world, not to the swinger, so the arc stays where the
    blow was struck even if the player keeps running."""

    def __init__(self, x, y, angle, radius, span_deg, cleave):
        self.x = x
        self.y = y
        # Facing, measured from straight up and clockwise, like every other angle here.
        self.angle = angle
        self.radius = radius
        self.span = math.radians(span_deg)
        self.color = c.Combat.SWING_ARC_CLEAVE_COLOR if cleave else c.Combat.SWING_ARC_COLOR
        self.width = c.Combat.SWING_ARC_WIDTH if cleave else max(2, c.Combat.SWING_ARC_WIDTH - 3)
        self.age = 0.0

    @property
    def dead(self) -> bool:
        return self.age >= c.Combat.SWING_ARC_MS

    def update(self, dt):
        self.age += dt

    def draw(self, layer: pygame.Surface, camera: "Camera"):
        progress = min(1.0, self.age / c.Combat.SWING_ARC_MS)
        alpha = round(200 * (1.0 - progress) ** 1.5)
        if alpha <= 2:
            return
        # The arc sweeps from one edge of the wedge to the other as it ages, so a slow
        # heavy weapon reads as a sweep rather than a stamp.
        start = self.angle - self.span / 2
        swept = self.span * (0.25 + 0.75 * progress)
        steps = max(4, round(math.degrees(swept) / 8))
        points = []
        for i in range(steps + 1):
            a = start + swept * i / steps
            wx = self.x + math.sin(a) * self.radius
            wy = self.y - math.cos(a) * self.radius
            points.append(camera.world_to_screen(wx, wy))
        if len(points) < 2:
            return
        pygame.draw.lines(layer, (*self.color, alpha), False, points, self.width)


class ThrustTrail:
    """A thrust's lane: the stretch of ground a spear covers, from the end of its blind
    spot out to its reach, drawn as the shaft driving forward and fading."""

    def __init__(self, x, y, angle, reach, blind_spot):
        self.x = x
        self.y = y
        self.angle = angle
        self.reach = reach
        self.blind_spot = blind_spot
        self.age = 0.0

    @property
    def dead(self) -> bool:
        return self.age >= c.Combat.SWING_ARC_MS

    def update(self, dt):
        self.age += dt

    def draw(self, layer: pygame.Surface, camera: "Camera"):
        progress = min(1.0, self.age / c.Combat.SWING_ARC_MS)
        alpha = round(210 * (1.0 - progress) ** 1.5)
        if alpha <= 2:
            return
        # The near end runs out to the far one over the trail's life, so the lane reads as
        # a thrust going in rather than as a stick lying on the ground.
        near = self.blind_spot + (self.reach - self.blind_spot) * progress * 0.6
        sin_a, cos_a = math.sin(self.angle), math.cos(self.angle)
        start = camera.world_to_screen(self.x + sin_a * near, self.y - cos_a * near)
        end = camera.world_to_screen(self.x + sin_a * self.reach, self.y - cos_a * self.reach)
        pygame.draw.line(layer, (*c.Combat.THRUST_TRAIL_COLOR, alpha), start, end, c.Combat.THRUST_TRAIL_WIDTH)


class SwingArcSystem:
    def __init__(self):
        self.arcs: list = []

    def spawn(self, x, y, angle, radius, span_deg, cleave: bool = False):
        self.arcs.append(SwingArc(x, y, angle, radius, span_deg, cleave))

    def spawn_thrust(self, x, y, angle, reach, blind_spot):
        self.arcs.append(ThrustTrail(x, y, angle, reach, blind_spot))

    def update(self, dt):
        for arc in self.arcs:
            arc.update(dt)
        self.arcs = [arc for arc in self.arcs if not arc.dead]

    def draw(self, surface: pygame.Surface, camera: "Camera"):
        """One transparent layer for every arc in flight, blitted once: the arcs need
        per-pixel alpha to fade, and a surface each would mean a full-screen allocation
        per swing."""
        if not self.arcs:
            return
        layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for arc in self.arcs:
            arc.draw(layer, camera)
        surface.blit(layer, (0, 0))


_swings = None


def get_swings() -> SwingArcSystem:
    global _swings
    if _swings is None:
        _swings = SwingArcSystem()
    return _swings
