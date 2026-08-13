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
    """A wandering animal: fills the wilderness with life, and can be hunted for a pelt.

    It never fights back. Its only answer to being attacked is to run: getting close makes
    it skitter, and a hit that doesn't kill it makes it bolt for a few seconds however far
    away the attacker is. Session-only, like particles or projectiles: never saved,
    respawned near the player as needed, so a dead one simply leaves its drop behind.
    """

    def __init__(self, x, y, kind: str = "rabbit"):
        self.x = x
        self.y = y
        self.kind = kind
        self.orientation = random.uniform(0, 2 * math.pi)
        self.max_hp = c.Wildlife.HP[kind]
        self.hp = self.max_hp
        self.last_damage_ms = 0
        # Set by `startle` when hit: bolts until this timestamp, ignoring flee distance.
        self.bolt_until_ms = 0
        self.wander = Wander(
            c.Wildlife.WANDER_SPEED, c.Wildlife.WANDER_RADIUS, c.Wildlife.IDLE_MIN_MS, c.Wildlife.IDLE_MAX_MS
        )

    @property
    def size(self) -> int:
        return c.Wildlife.SIZES[self.kind]

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def receive_damage(self, damage) -> bool:
        """Apply damage; True if it died."""
        self.hp -= damage
        self.last_damage_ms = pygame.time.get_ticks()
        return self.hp <= 0

    def startle(self):
        """Wounded but alive: run flat out for a while, wherever the player is."""
        self.bolt_until_ms = pygame.time.get_ticks() + c.Wildlife.BOLT_DURATION_MS

    def update(self, player: Player, dt, blocked=None):
        radius = self.size / 2
        bolting = pygame.time.get_ticks() < self.bolt_until_ms

        if bolting or self.distance_to_point((player.x, player.y)) < c.Wildlife.FLEE_DISTANCE:
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
        size = self.size
        color = c.Wildlife.COLORS[self.kind]
        # Flashes white for a moment after a hit, the same read as any other wounded thing.
        if self.last_damage_ms and pygame.time.get_ticks() - self.last_damage_ms < c.Entities.FLASH_MS:
            color = c.Colors.WHITE
        shade = tuple(max(0, v - 45) for v in color)

        def at(forward, side):
            """Point (forward, side) in the critter's own space, in screen coordinates."""
            cos_o, sin_o = math.cos(self.orientation), math.sin(self.orientation)
            return (
                round(sx + cos_o * forward * size - sin_o * side * size),
                round(sy + sin_o * forward * size + cos_o * side * size),
            )

        if self.kind == "deer":
            self._draw_deer(screen, at, color, shade, size)
            return

        body = pygame.Rect(0, 0, round(size * 1.3), round(size * 0.85))
        body.center = (round(sx), round(sy))
        pygame.draw.ellipse(screen, color, body)
        pygame.draw.ellipse(screen, shade, body, 1)
        head = at(0.7, 0)
        pygame.draw.circle(screen, color, head, round(size * 0.35))

        if self.kind == "rabbit":
            for side in (-1, 1):
                pygame.draw.line(screen, color, head, at(1.1, side * 0.25), 3)
        elif self.kind == "fox":
            pygame.draw.circle(screen, (230, 230, 225), at(-0.9, 0), round(size * 0.3))

    @staticmethod
    def _draw_deer(screen, at, color, shade, size):
        """A deer is long-bodied and stands on legs, so it can't be drawn as one blob the
        way the small critters are: from this far up a plain ellipse with two lines off the
        front reads as a snail rather than an animal."""
        # Hooves first, so they poke out from under the flank rather than sit on top of it.
        for forward, splay in ((0.34, 0.46), (-0.38, -0.52)):
            for side in (-1, 1):
                pygame.draw.line(screen, shade, at(forward, side * 0.26), at(splay, side * 0.5), 3)

        flank = [at(0.5, -0.28), at(0.5, 0.28), at(-0.55, 0.32), at(-0.72, 0.14), at(-0.72, -0.14), at(-0.55, -0.32)]
        pygame.draw.polygon(screen, color, flank)
        pygame.draw.polygon(screen, shade, flank, 1)

        pygame.draw.line(screen, color, at(0.42, 0), at(0.88, 0), max(3, round(size * 0.18)))  # neck
        head = at(0.95, 0)
        pygame.draw.circle(screen, color, head, round(size * 0.2))
        pygame.draw.circle(screen, shade, head, round(size * 0.2), 1)
        pygame.draw.circle(screen, shade, at(1.1, 0), max(2, round(size * 0.1)))  # muzzle

        # Antlers: a beam sweeping forward off the brow with a tine on each, not the pair
        # of straight antennae this used to have.
        antler = (60, 44, 28)
        for side in (-1, 1):
            brow, tip = at(1.0, side * 0.12), at(1.32, side * 0.46)
            pygame.draw.line(screen, antler, brow, tip, 2)
            pygame.draw.line(screen, antler, at(1.16, side * 0.29), at(1.1, side * 0.58), 2)
            pygame.draw.line(screen, antler, tip, at(1.5, side * 0.34), 2)

        pygame.draw.circle(screen, (235, 232, 220), at(-0.76, 0), max(2, round(size * 0.13)))  # tail
