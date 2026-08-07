from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from game.entities.wander import Wander

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player


def pick_critter_kind() -> str:
    return random.choices(c.Wildlife.KINDS, weights=c.Wildlife.KIND_WEIGHTS)[0]


class Critter:
    """A non-hostile wandering animal, purely atmospheric: no hp, can't be fought, just
    fills the wilderness with a bit of life. Skitters away if the player gets too
    close, then goes back to wandering once they've moved on. Session-only, like
    particles or projectiles: never saved, respawned near the player as needed."""

    def __init__(self, x, y, kind: str = "rabbit"):
        self.x = x
        self.y = y
        self.kind = kind
        self.orientation = random.uniform(0, 2 * math.pi)
        self.wander = Wander(
            c.Wildlife.WANDER_SPEED, c.Wildlife.WANDER_RADIUS, c.Wildlife.IDLE_MIN_MS, c.Wildlife.IDLE_MAX_MS
        )

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def update(self, player: Player, dt, blocked=None):
        radius = c.Wildlife.SIZES[self.kind] / 2

        if self.distance_to_point((player.x, player.y)) < c.Wildlife.FLEE_DISTANCE:
            angle = math.atan2(self.y - player.y, self.x - player.x)
            speed = c.Wildlife.WANDER_SPEED * c.Wildlife.FLEE_SPEED_MULT * dt * c.TARGET_FPS / 1000.0
            step_x, step_y = math.cos(angle) * speed, math.sin(angle) * speed
            if blocked is None or not blocked(self.x + step_x, self.y + step_y, radius):
                self.x += step_x
                self.y += step_y
            self.orientation = angle
            # Fleeing resets the wander state, so it picks a fresh spot once it settles.
            self.wander.interrupt()
            return

        moved_angle = self.wander.step(self, dt, (self.x, self.y), radius, blocked)
        if moved_angle is not None:
            self.orientation = moved_angle

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        color = c.Wildlife.COLORS[self.kind]
        size = c.Wildlife.SIZES[self.kind]
        cx, cy = round(sx), round(sy)

        body = pygame.Rect(0, 0, round(size * 1.3), round(size * 0.85))
        body.center = (cx, cy)
        pygame.draw.ellipse(screen, color, body)
        pygame.draw.ellipse(screen, tuple(max(0, v - 40) for v in color), body, 1)

        head_x = cx + math.cos(self.orientation) * size * 0.7
        head_y = cy + math.sin(self.orientation) * size * 0.7
        head = (round(head_x), round(head_y))
        pygame.draw.circle(screen, color, head, round(size * 0.35))

        if self.kind == "rabbit":
            for side in (-1, 1):
                ex = head_x + math.cos(self.orientation + side * 0.3) * size * 0.5
                ey = head_y + math.sin(self.orientation + side * 0.3) * size * 0.5
                pygame.draw.line(screen, color, head, (round(ex), round(ey)), 3)
        elif self.kind == "deer":
            for side in (-1, 1):
                ax = head_x + math.cos(self.orientation + side * 0.5) * size * 0.6
                ay = head_y + math.sin(self.orientation + side * 0.5) * size * 0.6
                pygame.draw.line(screen, (90, 65, 40), head, (round(ax), round(ay)), 2)
        elif self.kind == "fox":
            tail_x = cx - math.cos(self.orientation) * size * 0.9
            tail_y = cy - math.sin(self.orientation) * size * 0.9
            pygame.draw.circle(screen, (230, 230, 225), (round(tail_x), round(tail_y)), round(size * 0.3))
