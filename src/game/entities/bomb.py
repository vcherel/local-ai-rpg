from __future__ import annotations

import math

import pygame

import core.constants as c
from core.utils import frames

MINE = "mine"
GRENADE = "grenade"


class Bomb:
    """Something the player has put on the ground, or in the air, that is going to go off.

    Two kinds and one object, because the only difference between them is what they are
    waiting for. A mine is laid where the player is standing, arms itself once they have had
    time to step off it, and then goes off under the first thing that would fight them. A
    grenade is thrown at what the player is aiming at, travels there, and burns a fuse.

    Neither knows what an explosion does: both end in `WorldCombat.explode`, which is the
    same blast a powder keg makes, so the damage, the gore, the shake and what a village
    thinks of it are all decided in one place already.
    """

    def __init__(self, x: float, y: float, kind: str = GRENADE, angle: float = 0.0, distance: float = 0.0):
        self.x = x
        self.y = y
        self.kind = kind
        self.dead = False
        now = pygame.time.get_ticks()
        # A mine is not live the moment it leaves the hand: the player has to be able to
        # lay one and walk away from it.
        self.live_at_ms = now + (c.Bombs.ARM_MS if kind == MINE else 0)
        # A grenade's fuse only starts once it has landed, so it is a count from where it
        # comes down rather than from where it was thrown.
        self.fuse_at_ms = None
        self.expires_at_ms = now + c.Bombs.MINE_LIFETIME_MS if kind == MINE else None
        # A mine is put down rather than thrown, so it has no travel of its own at all.
        throwing = kind == GRENADE
        self.vx = math.sin(angle) * c.Bombs.THROW_SPEED if throwing else 0.0
        self.vy = -math.cos(angle) * c.Bombs.THROW_SPEED if throwing else 0.0
        self.to_travel = min(distance, c.Bombs.THROW_RANGE) if throwing else 0.0
        self.traveled = 0.0

    @property
    def armed(self) -> bool:
        return pygame.time.get_ticks() >= self.live_at_ms

    @property
    def in_flight(self) -> bool:
        return self.kind == GRENADE and self.traveled < self.to_travel

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: dict) -> Bomb:
        bomb = cls(data["x"], data["y"], data.get("kind", MINE))
        # A mine found where it was left is long since armed, and the clock on it starts
        # again: what the save keeps is that it is lying there, not how stale it is.
        bomb.live_at_ms = pygame.time.get_ticks()
        return bomb

    def update(self, dt, blocked=None) -> bool:
        """Advance one frame. Returns True when this one should go off now.

        A grenade flies in hops no longer than it is wide, the way a projectile does, so a
        wall stops it at any framerate rather than being crossed on a slow frame."""
        now = pygame.time.get_ticks()
        if self.expires_at_ms is not None and now >= self.expires_at_ms:
            # A mine nobody ever walked onto is eventually just litter.
            self.dead = True
            return False

        if self.in_flight:
            move = frames(dt)
            total_x, total_y = self.vx * move, self.vy * move
            distance = math.hypot(total_x, total_y)
            steps = max(1, math.ceil(distance / c.Bombs.SIZE))
            for _ in range(steps):
                self.x += total_x / steps
                self.y += total_y / steps
                self.traveled += distance / steps
                if self.traveled >= self.to_travel or (blocked is not None and blocked(self.x, self.y, c.Bombs.SIZE)):
                    # It has arrived, or bounced off whatever it was thrown into: either
                    # way it is on the ground and the fuse is burning.
                    self.traveled = self.to_travel
                    break
            if self.in_flight:
                return False

        if self.kind == GRENADE:
            if self.fuse_at_ms is None:
                self.fuse_at_ms = now + c.Bombs.FUSE_MS
            return now >= self.fuse_at_ms
        return False

    def triggered_by(self, bodies) -> bool:
        """Whether anything in `bodies` has stepped close enough to set a laid mine off.
        Only what would fight the player is offered here, so their own mine never goes off
        under their own feet."""
        if not self.armed:
            return False
        return any(math.hypot(body.x - self.x, body.y - self.y) < c.Bombs.TRIGGER_RADIUS for body in bodies)

    def draw(self, screen: pygame.Surface, camera):
        x, y = camera.world_to_screen(self.x, self.y)
        radius = c.Bombs.SIZE // 2
        pygame.draw.circle(screen, c.Colors.BLACK, (int(x), int(y)), radius + 2)
        pygame.draw.circle(screen, c.Bombs.BODY_COLOR, (int(x), int(y)), radius)

        now = pygame.time.get_ticks()
        if self.kind == MINE:
            # A laid mine blinks once it is live, and only then: what is on the ground is
            # readable, so walking a friend onto one is a plan rather than an accident.
            if not self.armed:
                return
            pulse = 0.5 + 0.5 * math.sin(now / 140.0)
            pygame.draw.circle(screen, c.Bombs.ARMED_COLOR, (int(x), int(y)), max(2, int(radius * 0.45 * pulse)))
            pygame.draw.circle(screen, c.Bombs.ARMED_COLOR, (int(x), int(y)), int(c.Bombs.TRIGGER_RADIUS), 1)
            return

        # A grenade's fuse burns down where anyone can see it: the spark climbs and the
        # shell flashes faster the closer it gets, so standing next to one is a decision.
        left = 1.0 if self.fuse_at_ms is None else max(0.0, (self.fuse_at_ms - now) / c.Bombs.FUSE_MS)
        spark = (int(x + radius * 0.7), int(y - radius * 1.4))
        pygame.draw.line(screen, c.Colors.BLACK, (int(x), int(y - radius)), spark, 2)
        flare = 0.5 + 0.5 * math.sin(now / max(40.0, 160.0 * left))
        pygame.draw.circle(screen, c.Bombs.FUSE_COLOR, spark, max(2, int(3 + 3 * flare)))
