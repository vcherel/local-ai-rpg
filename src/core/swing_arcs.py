"""The trail a melee attack leaves behind it.

A swing used to be invisible: the arm animated, particles popped on whatever was hit, and
nothing on screen said how much ground the blow actually covered. That is fine for a
dagger and useless for a cleaving weapon, where the whole point is the crowd it catches.
So an arc is drawn along the exact wedge the hit test uses (the weapon's `arc_deg` at its
reach), and a cleaving weapon draws it wider and hotter than a single-target one.

A thrust is drawn from the same rule and comes out as a different picture, because it is
tested differently: a `pierce_melee` weapon covers a lane down its facing rather than a
wedge, so it draws that lane, blind spot and all, as a head driven out along it. Both live
in the one system and both promise exactly what their hit test accepts.

Session-only global in the same shape as particles, floating text and decals: updated once
per frame from `Game.run`, drawn from `GameRenderer.draw_world`, never saved.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.particles import get_particles

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

    def draw(self, layer: pygame.Surface, camera: Camera):
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
    """A thrust's lane, drawn as the lunge it is: the head driving out to the end of the
    shaft, the shaft stretching behind it, and the air torn open either side.

    A spear's whole argument is the ground it covers before anything reaches the player, so
    the picture is a weapon being driven forward rather than a line lying on the grass. What
    it covers is still exactly the lane the hit test accepts, blind spot and all.
    """

    def __init__(self, x, y, angle, reach, blind_spot):
        self.x = x
        self.y = y
        self.angle = angle
        self.reach = reach
        self.blind_spot = blind_spot
        self.age = 0.0
        # The dust kicked up along the lane, thrown once at the moment of the lunge.
        sin_a, cos_a = math.sin(angle), math.cos(angle)
        for i in range(c.Combat.THRUST_DUST):
            t = (i + 1) / c.Combat.THRUST_DUST
            along = blind_spot + (reach - blind_spot) * t
            get_particles().spawn_directional_burst(
                x + sin_a * along,
                y - cos_a * along,
                math.atan2(-cos_a, sin_a),
                spread_deg=45.0,
                color=c.Combat.THRUST_TRAIL_COLOR,
                count=1,
                speed=3.0 + 3.0 * t,
                life=260,
                size=4,
            )

    @property
    def dead(self) -> bool:
        return self.age >= c.Combat.THRUST_MS

    def update(self, dt):
        self.age += dt

    def draw(self, layer: pygame.Surface, camera: Camera):
        progress = min(1.0, self.age / c.Combat.THRUST_MS)
        alpha = round(230 * (1.0 - progress) ** 1.4)
        if alpha <= 2:
            return
        # Out fast and then held: the head reaches the end of the lane in the first part of
        # the life and the rest of it is the shaft fading behind, which is what a lunge
        # looks like as against a stick being laid down.
        drive = min(1.0, progress / c.Combat.THRUST_DRIVE_FRAC)
        eased = 1.0 - (1.0 - drive) ** 3
        sin_a, cos_a = math.sin(self.angle), math.cos(self.angle)
        tip_along = self.blind_spot + (self.reach - self.blind_spot) * eased
        # The tail is dragged along behind the head rather than pinned to the blind spot, so
        # the shaft thins out into a streak instead of growing forever.
        tail_along = self.blind_spot + (tip_along - self.blind_spot) * progress * 0.55

        def point(along, across=0.0):
            return camera.world_to_screen(
                self.x + sin_a * along + cos_a * across,
                self.y - cos_a * along + sin_a * across,
            )

        # The shaft: a wedge, wide at the head and closing to nothing at the tail.
        half = c.Combat.THRUST_TRAIL_WIDTH / 2
        shaft = [point(tail_along, 0), point(tip_along, -half), point(tip_along, half)]
        pygame.draw.polygon(layer, (*c.Combat.THRUST_TRAIL_COLOR, alpha), shaft)

        # The head itself: a bright blade at the end of the lane, still visible when the
        # shaft behind it has all but gone.
        head = c.Combat.THRUST_HEAD
        blade = [
            point(tip_along + head * 0.55),
            point(tip_along - head * 0.25, -head * 0.28),
            point(tip_along - head * 0.55),
            point(tip_along - head * 0.25, head * 0.28),
        ]
        pygame.draw.polygon(layer, (*c.Combat.THRUST_CORE_COLOR, min(255, alpha + 25)), blade)

        # The air torn either side of the shaft: two lines swept out from the head, which is
        # what makes the lane read as driven through rather than pointed at.
        wind = c.Combat.THRUST_WIND_SPREAD * (0.4 + 0.6 * progress)
        for side in (-1, 1):
            pygame.draw.line(
                layer,
                (*c.Combat.THRUST_TRAIL_COLOR, alpha // 2),
                point(tail_along, side * wind * 0.4),
                point(tip_along - head * 0.4, side * wind),
                2,
            )


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

    def draw(self, surface: pygame.Surface, camera: Camera):
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
