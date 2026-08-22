from __future__ import annotations

import math
import random

import core.constants as c
from core.utils import frames
from game.entities.entities import step_towards


class Wander:
    """Idle-then-stroll movement, shared by NPCs and wildlife.

    Both pick a random spot near an anchor, walk to it sliding along any wall in the way,
    then idle for a random delay before picking the next one. They differ only in their
    tuning, where the anchor sits (an NPC's home vs a critter's current position) and how
    a movement angle maps onto their sprite's facing, so the owner holds one of these and
    applies the returned angle itself.
    """

    def __init__(self, speed: float, radius: float, idle_min_ms: float, idle_max_ms: float):
        self.speed = speed
        self.radius = radius
        self.idle_min_ms = idle_min_ms
        self.idle_max_ms = idle_max_ms
        self.target = None
        self.idle_timer = random.uniform(idle_min_ms, idle_max_ms)

    def interrupt(self):
        """Drop the current target and pick a fresh one on the next step, e.g. once a
        fleeing critter has settled down somewhere new."""
        self.target = None
        self.idle_timer = 0.0

    def _rest(self):
        self.target = None
        self.idle_timer = random.uniform(self.idle_min_ms, self.idle_max_ms)

    def _pick(self, anchor, radius, blocked) -> tuple | None:
        """Somewhere to stroll to: a random spot within `radius` of the anchor that the
        owner could actually stand on, or None if a few tries found nowhere."""
        for _ in range(c.Entities.WANDER_PICK_TRIES):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(0, self.radius)
            spot = (anchor[0] + math.cos(angle) * dist, anchor[1] + math.sin(angle) * dist)
            if blocked is None or not blocked(spot[0], spot[1], radius):
                return spot
        return None

    def step(self, entity, dt, anchor, radius, blocked) -> float | None:
        """Advance the owner one frame. Returns the angle it actually moved along, or None
        if it stayed put (idling, arriving, or pinned flat against a wall)."""
        if self.target is None:
            self.idle_timer -= dt
            if self.idle_timer <= 0:
                self.target = self._pick(anchor, radius, blocked)
                if self.target is None:
                    # Hemmed in on every side this time: idle again and try later, rather
                    # than set off at a spot that can never be reached.
                    self._rest()
            return None

        dx = self.target[0] - entity.x
        dy = self.target[1] - entity.y
        step = self.speed * frames(dt)
        if math.hypot(dx, dy) <= step:
            # The spot was clear when it was picked; the world moves in the meantime (a
            # village is built, a door is shut), and arriving is the one movement here that
            # does not test the ground it lands on.
            if blocked is None or not blocked(self.target[0], self.target[1], radius):
                entity.x, entity.y = self.target
            self._rest()
            return None

        step_x, step_y = step_towards(entity, math.atan2(dy, dx), step, blocked, radius)

        # If a wall swallowed most of the intended step, stop grinding against it and repick.
        if math.hypot(step_x, step_y) < step * 0.25:
            self._rest()
        if not step_x and not step_y:
            return None
        return math.atan2(step_y, step_x)
