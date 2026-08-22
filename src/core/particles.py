"""Simple world-space particle bursts for combat and pickup feedback.

Most of what happens in a fight happens on one frame, so most of this is bursts. The
exception is anything that takes a moment on purpose (sitting down at a fire): an
`Emitter` keeps throwing the same burst for as long as the thing is going on, so the
animation lasts as long as the action instead of being one puff at the start of it.
"""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c


class Particle:
    __slots__ = (
        "color",
        "gravity",
        "life",
        "max_life",
        "rot",
        "rot_speed",
        "shape",
        "size",
        "vx",
        "vy",
        "vz",
        "x",
        "y",
        "z",
    )

    def __init__(self, x, y, vx, vy, life, color, size, gravity=0.0, shape="circle", rot=0.0, rot_speed=0.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size
        # A fake z-height: the world is drawn top-down, so gravity should pull a particle
        # back down onto the ground plane, not down the screen. vz launches it up, gravity
        # brings it back, and it settles at z=0 once it lands instead of bouncing forever.
        self.z = 0.0
        self.vz = random.uniform(2.0, 4.0) * max(size, 1) / 4.0 if gravity else 0.0
        self.gravity = gravity
        self.shape = shape
        self.rot = rot
        self.rot_speed = rot_speed


class Emitter:
    """A source that keeps throwing the same little burst for a while.

    Everything about the burst is kept as the keyword arguments `spawn_burst` takes, so an
    emitter is only a clock in front of the call that was already there."""

    __slots__ = ("interval", "left", "next_in", "spec", "x", "y")

    def __init__(self, x, y, duration, interval, spec):
        self.x = x
        self.y = y
        self.left = duration
        self.interval = interval
        self.next_in = 0.0
        self.spec = spec


class ParticleSystem:
    def __init__(self):
        self.particles: list[Particle] = []
        self.emitters: list[Emitter] = []

    def _emit(self, x, y, base_angle, angle_range, color, count, speed, life, size, gravity, shape):
        half = angle_range / 2
        for _ in range(count):
            angle = base_angle + random.uniform(-half, half)
            magnitude = random.uniform(0.3, 1.0) * speed
            self.particles.append(
                Particle(
                    x,
                    y,
                    math.cos(angle) * magnitude,
                    math.sin(angle) * magnitude,
                    life,
                    color,
                    random.uniform(size * 0.5, size),
                    gravity=gravity,
                    shape=shape,
                    rot=random.uniform(0, 2 * math.pi) if shape == "shard" else 0.0,
                    rot_speed=random.uniform(-6, 6) if shape == "shard" else 0.0,
                )
            )

    def spawn_burst(self, x, y, color, count=10, speed=4.0, life=400, size=4, gravity=0.0, shape="circle"):
        """Omnidirectional puff: pickups, deaths, ambient effects."""
        self._emit(x, y, 0.0, 2 * math.pi, color, count, speed, life, size, gravity, shape)

    def spawn_directional_burst(
        self,
        x,
        y,
        angle,
        spread_deg=70.0,
        color=(255, 255, 255),
        count=10,
        speed=4.0,
        life=400,
        size=4,
        gravity=0.0,
        shape="circle",
    ):
        """Cone-shaped spray away from `angle` (radians): a slash or a hit reads as
        having a direction, instead of exploding outward like a pickup poof."""
        self._emit(x, y, angle, math.radians(spread_deg), color, count, speed, life, size, gravity, shape)

    def emit_over(self, x, y, duration_ms, interval_ms=90.0, **burst):
        """Throw `burst` from (x, y) every `interval_ms` for `duration_ms`. What a thing that
        takes a couple of seconds looks like, as against a thing that happens at once."""
        self.emitters.append(Emitter(x, y, duration_ms, interval_ms, burst))

    def _advance_emitters(self, dt):
        alive = []
        for emitter in self.emitters:
            emitter.left -= dt
            emitter.next_in -= dt
            if emitter.next_in <= 0.0:
                emitter.next_in = emitter.interval
                self.spawn_burst(emitter.x, emitter.y, **emitter.spec)
            if emitter.left > 0:
                alive.append(emitter)
        self.emitters = alive

    def update(self, dt):
        self._advance_emitters(dt)
        factor = dt * c.TARGET_FPS / 1000.0
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.x += p.vx * factor
            p.y += p.vy * factor
            p.vx *= 0.92
            p.vy *= 0.92
            if p.gravity:
                p.vz -= p.gravity * factor
                p.z = max(0.0, p.z + p.vz * factor)
                if p.z <= 0.0 and p.vz < 0:
                    p.vz = 0.0  # landed: settles in place rather than bouncing forever
            p.rot += p.rot_speed * factor
            alive.append(p)
        self.particles = alive

    def draw(self, surface, camera):
        for p in self.particles:
            screen_x, screen_y = camera.world_to_screen(p.x, p.y)
            screen_y -= p.z
            if not (0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT):
                continue
            alpha = max(0, min(255, int(255 * p.life / p.max_life)))
            if p.shape == "shard":
                self._draw_shard(surface, screen_x, screen_y, p, alpha)
            else:
                radius = max(1, int(p.size))
                blob = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(blob, (*p.color[:3], alpha), (radius, radius), radius)
                surface.blit(blob, (screen_x - radius, screen_y - radius))

    @staticmethod
    def _draw_shard(surface, x, y, p: Particle, alpha):
        w, h = max(2, int(p.size * 1.8)), max(2, int(p.size * 0.9))
        shard = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
        rect = pygame.Rect(2, 2, w, h)
        pygame.draw.rect(shard, (*p.color[:3], alpha), rect)
        border = tuple(max(0, int(v * 0.6)) for v in p.color[:3])
        pygame.draw.rect(shard, (*border, alpha), rect, 1)
        rotated = pygame.transform.rotate(shard, math.degrees(p.rot))
        rrect = rotated.get_rect(center=(x, y))
        surface.blit(rotated, rrect.topleft)


_system = None


def get_particles() -> ParticleSystem:
    global _system
    if _system is None:
        _system = ParticleSystem()
    return _system
