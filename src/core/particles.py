"""Simple world-space particle bursts for combat and pickup feedback."""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size")

    def __init__(self, x, y, vx, vy, life, color, size):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size


class ParticleSystem:
    def __init__(self):
        self.particles: list[Particle] = []

    def spawn_burst(self, x, y, color, count=10, speed=4.0, life=400, size=4):
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
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
                )
            )

    def update(self, dt):
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
            alive.append(p)
        self.particles = alive

    def draw(self, surface, camera):
        for p in self.particles:
            screen_x, screen_y = camera.world_to_screen(p.x, p.y)
            if not (0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT):
                continue
            alpha = max(0, min(255, int(255 * p.life / p.max_life)))
            radius = max(1, int(p.size))
            blob = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(blob, (*p.color[:3], alpha), (radius, radius), radius)
            surface.blit(blob, (screen_x - radius, screen_y - radius))


_system = None


def get_particles() -> ParticleSystem:
    global _system
    if _system is None:
        _system = ParticleSystem()
    return _system
