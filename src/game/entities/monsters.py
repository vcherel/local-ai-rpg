from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import core.constants as c
from game.entities.entities import Entity

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player


def pick_monster_kind(distance_from_center: float) -> c.MonsterKind:
    """Pick a kind unlocked at this distance from the world center; weaker kinds stay more common."""
    eligible = [kind for kind in c.MONSTER_KINDS if distance_from_center >= kind.min_distance]
    return random.choices(eligible, weights=[kind.weight for kind in eligible])[0]


class Monster(Entity):
    def __init__(self, x, y, kind: c.MonsterKind = c.MONSTER_KINDS[0]):
        super().__init__(x, y, kind.color, kind.size, kind.hp, kind.hp)
        self.kind = kind
        self.target_offset = (random.uniform(-15, 15), random.uniform(-15, 15))

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "hp": self.hp, "kind": self.kind.name}

    @classmethod
    def from_dict(cls, data: dict) -> Monster:
        kind = next((k for k in c.MONSTER_KINDS if k.name == data["kind"]), c.MONSTER_KINDS[0])
        monster = cls(data["x"], data["y"], kind)
        monster.hp = data["hp"]
        return monster

    def start_attack_anim(self, dist):
        """Return True in case of hit to the player"""
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = random.choice(["left", "right"])

            if dist < self.kind.attack_range + c.Player.SIZE // 2:
                return True

        return False

    def move(self, player: Player, dt, blocked=None):
        dx = player.x + self.target_offset[0] - self.x
        dy = player.y + self.target_offset[1] - self.y
        dist = math.hypot(dx, dy)

        self.orientation = math.atan2(dy, dx)

        if self.kind.attack_range < dist < c.World.DETECTION_RANGE + c.Player.SIZE // 2:
            move_factor = dt * c.TARGET_FPS / 1000.0
            step_x = math.cos(self.orientation) * self.kind.speed * move_factor
            step_y = math.sin(self.orientation) * self.kind.speed * move_factor
            radius = self.kind.size / 2
            # Move one axis at a time so a wall on one axis lets the monster slide along it.
            if blocked is not None and blocked(self.x + step_x, self.y, radius):
                step_x = 0
            self.x += step_x
            if blocked is not None and blocked(self.x, self.y + step_y, radius):
                step_y = 0
            self.y += step_y

        if dist < self.kind.attack_range * 10:
            hit = self.start_attack_anim(dist)
            if hit:
                player.receive_damage(self.kind.damage)

        # atan2(dy, dx) measures from the x-axis; sprites face up, so rotate a quarter turn
        self.orientation += math.pi / 2

        self.update_attack_anim(dt)

    def draw(self, screen, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        super().draw(
            screen,
            screen_x,
            screen_y,
            self.kind.size,
            self.kind.color,
            self.orientation,
            self.attack_progress,
            self.attack_hand,
            bar_width=60,
            bar_height=8,
            health_bar_offset=10,
        )
