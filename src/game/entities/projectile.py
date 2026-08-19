from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera

ARROW_COLOR = (180, 140, 90)
BOLT_COLOR = (150, 90, 230)


class Projectile:
    """A fired arrow travelling in a straight line until it hits, hits a wall, or runs out of range."""

    def __init__(
        self,
        x,
        y,
        angle,
        damage,
        style="arrow",
        color=ARROW_COLOR,
        knockback=0.0,
        shake=0.0,
        hostile=False,
        owner_id=None,
        source_name="",
    ):
        self.x = x
        self.y = y
        self.angle = angle
        self.vx = math.sin(angle) * c.Projectile.SPEED
        self.vy = -math.cos(angle) * c.Projectile.SPEED
        self.damage = damage
        self.style = style  # "arrow" or "bolt" (glowing magic orb)
        self.color = color
        self.knockback = knockback
        self.shake = shake
        # A hostile shot threatens the player, a friendly one the player's enemies. Neither
        # is choosy about what else it meets on the way: an arrow hits the first body in
        # its path, whoever loosed it, which is what makes standing behind a wolf a
        # mistake for a goblin archer.
        self.hostile = hostile
        # Pierce lets an arrow pass through this many targets before stopping (arrow-pierce accessory).
        self.pierce = 0
        # Whoever fired it, already counted as struck so a shot can never hit its own
        # shooter on the frame it leaves them.
        self.owner_id = owner_id
        # What killed the player, on the death screen: an arrow is named for whoever fired
        # it, since the projectile itself has no name to give.
        self.source_name = source_name
        self.hit_ids = set() if owner_id is None else {owner_id}
        self.traveled = 0.0
        self.dead = False

    def update(self, dt, blocked=None):
        """Advance one frame, in hops no longer than the projectile is wide.

        Stepping the whole frame at once let an arrow cross a wall in a single move when
        the framerate dipped: the speed is 14px at 60fps but twice that at 30, and a wall
        shell is 16px thick. Substepping means a wall stops a shot at any framerate."""
        move_factor = dt * c.TARGET_FPS / 1000.0
        total_x = self.vx * move_factor
        total_y = self.vy * move_factor
        distance = math.hypot(total_x, total_y)
        steps = max(1, math.ceil(distance / c.Projectile.SIZE))
        for _ in range(steps):
            self.x += total_x / steps
            self.y += total_y / steps
            self.traveled += distance / steps
            if self.traveled >= c.Projectile.RANGE:
                self.dead = True
                return
            if blocked is not None and blocked(self.x, self.y, c.Projectile.SIZE):
                self.dead = True
                return

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])

    def draw(self, screen, camera: Camera = None):
        if camera is not None:
            x, y = camera.world_to_screen(self.x, self.y)
        else:
            x, y = self.x, self.y

        if self.style == "bolt":
            glow = pygame.Surface((16, 16), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*self.color, 90), (8, 8), 8)
            screen.blit(glow, (x - 8, y - 8))
            pygame.draw.circle(screen, self.color, (int(x), int(y)), 4)
            return

        length = 16
        tail_x = x - math.sin(self.angle) * length
        tail_y = y + math.cos(self.angle) * length
        pygame.draw.line(screen, (90, 60, 30), (tail_x, tail_y), (x, y), 3)
        pygame.draw.circle(screen, self.color, (x, y), 2)
