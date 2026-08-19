from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera

ARROW_COLOR = (180, 140, 90)
BOLT_COLOR = (150, 90, 230)
# A stone out of an angry villager's hand: what a crowd with no weapons throws.
STONE_COLOR = (140, 136, 128)


class Projectile:
    """A fired arrow travelling in a straight line until it hits, hits a wall, or runs out
    of range.

    The one thing that does not travel straight is a boomerang: at the end of its throw
    (or at the first wall) it turns and comes home to whoever threw it, striking on the
    way back what it missed on the way out. It is the same object throughout, so every hit
    test, every affix and the drawing all treat both legs as one shot.
    """

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
        max_range=None,
    ):
        self.x = x
        self.y = y
        self.angle = angle
        self.vx = math.sin(angle) * c.Projectile.SPEED
        self.vy = -math.cos(angle) * c.Projectile.SPEED
        self.damage = damage
        self.style = style  # "arrow", "bolt" (glowing magic orb), "boomerang" or "stone"
        # What this shot does on top of its damage, set by an elemental staff and read
        # once it lands ("" for anything else). The weapon may be swapped mid-flight, so
        # the effect travels with the shot rather than being looked up again on the hit.
        self.element = ""
        # A boomerang's thrower, and whether it is already on the way back to them.
        self.owner = None
        self.returning = False
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
        # How far this one carries. Its own rather than one number for everything in flight:
        # the player's bow outranges a monster's, and a stone out of a fist outranges neither.
        self.max_range = c.Projectile.RANGE if max_range is None else max_range
        self.dead = False

    def update(self, dt, blocked=None):
        """Advance one frame, in hops no longer than the projectile is wide.

        Stepping the whole frame at once let an arrow cross a wall in a single move when
        the framerate dipped: the speed is 14px at 60fps but twice that at 30, and a wall
        shell is 16px thick. Substepping means a wall stops a shot at any framerate."""
        move_factor = dt * c.TARGET_FPS / 1000.0
        if self.returning:
            self._steer_home()
        total_x = self.vx * move_factor
        total_y = self.vy * move_factor
        distance = math.hypot(total_x, total_y)
        steps = max(1, math.ceil(distance / c.Projectile.SIZE))
        for _ in range(steps):
            self.x += total_x / steps
            self.y += total_y / steps
            self.traveled += distance / steps
            if self.returning:
                # Caught: the throw is over. It comes home over whatever it flew out
                # across, walls included, because it is returning to a hand and not to a
                # place, and it never runs out of range on the way.
                owner = (self.owner.x, self.owner.y)
                if self.distance_to_point(owner) < c.Boomerang.CATCH_DISTANCE:
                    self.dead = True
                    return
                continue
            if self.traveled >= self.max_range:
                if self.turn_back():
                    return
                self.dead = True
                return
            if blocked is not None and blocked(self.x, self.y, c.Projectile.SIZE):
                # A wall turns a boomerang early rather than eating it.
                if self.turn_back():
                    return
                self.dead = True
                return

    def turn_back(self) -> bool:
        """Send a boomerang home, and report that the shot is not over. Anything else
        simply stops, which is what the caller does with a False."""
        if self.style != "boomerang" or self.returning or self.owner is None:
            return False
        self.returning = True
        self.traveled = 0.0
        # Forgets what it already struck, so the return leg is a second pass rather than a
        # flight through the bodies it went out through.
        self.hit_ids = set() if self.owner_id is None else {self.owner_id}
        self.pierce = c.Boomerang.PIERCE
        return True

    def _steer_home(self):
        """Aim a returning boomerang at whoever threw it, wherever they have run to."""
        dx, dy = self.owner.x - self.x, self.owner.y - self.y
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        speed = c.Projectile.SPEED * c.Boomerang.RETURN_SPEED_MULT
        self.vx, self.vy = dx / dist * speed, dy / dist * speed
        self.angle = math.atan2(dx, -dy)

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])

    def draw(self, screen, camera: Camera = None):
        if camera is not None:
            x, y = camera.world_to_screen(self.x, self.y)
        else:
            x, y = self.x, self.y

        if self.style == "stone":
            pygame.draw.circle(screen, (60, 58, 54), (int(x), int(y)), 5)
            pygame.draw.circle(screen, self.color, (int(x), int(y)), 4)
            return

        if self.style == "boomerang":
            # A flat curved blade spinning about its own middle: the spin is what tells it
            # from an arrow at a glance, and it is drawn off the distance flown so it never
            # needs a clock of its own.
            spin = self.traveled / 26.0
            arm = 9
            for offset in (0.0, 2.1):
                a = spin + offset
                tip = (x + math.sin(a) * arm, y - math.cos(a) * arm)
                pygame.draw.line(screen, (70, 50, 25), (x, y), tip, 5)
                pygame.draw.line(screen, self.color, (x, y), tip, 3)
            return

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
