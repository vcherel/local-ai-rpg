from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera


class Projectile:
    """A fired arrow travelling in a straight line until it hits, hits a wall, or runs out of range."""

    def __init__(self, x, y, angle, damage):
        self.x = x
        self.y = y
        self.angle = angle
        self.vx = math.sin(angle) * c.Projectile.SPEED
        self.vy = -math.cos(angle) * c.Projectile.SPEED
        self.damage = damage
        self.traveled = 0.0
        self.dead = False

    def update(self, dt, blocked=None):
        move_factor = dt * c.TARGET_FPS / 1000.0
        step_x = self.vx * move_factor
        step_y = self.vy * move_factor
        self.x += step_x
        self.y += step_y
        self.traveled += math.hypot(step_x, step_y)
        if self.traveled >= c.Projectile.RANGE:
            self.dead = True
        elif blocked is not None and blocked(self.x, self.y, c.Projectile.SIZE):
            self.dead = True

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])

    def draw(self, screen, camera: Camera = None):
        if camera is not None:
            x, y = camera.world_to_screen(self.x, self.y)
        else:
            x, y = self.x, self.y

        length = 16
        tail_x = x - math.sin(self.angle) * length
        tail_y = y + math.cos(self.angle) * length
        pygame.draw.line(screen, (90, 60, 30), (tail_x, tail_y), (x, y), 3)
        pygame.draw.circle(screen, (180, 140, 90), (x, y), 2)
