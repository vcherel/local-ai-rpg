from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import core.constants as c
from game.entities.entities import Entity

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player


class Monster(Entity):
    """The monsters we can fight"""
    def __init__(self, x, y):
        super().__init__(x, y, c.Colors.RED, c.Monster.SIZE, c.Monster.HP, c.Monster.HP)
        self.target_offset = (random.uniform(-15, 15), random.uniform(-15, 15))

    def start_attack_anim(self, dist):
        """Return True in case of hit to the player"""
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = random.choice(["left", "right"])

            if dist < c.Monster.ATTACK_RANGE + c.Player.SIZE // 2:
                return True
        
        return False

    def move(self, player: Player, dt):
        # Calculate vector to player
        dx = player.x + self.target_offset[0] - self.x
        dy = player.y + self.target_offset[1] - self.y
        dist = math.hypot(dx, dy)

        # Angle toward player
        self.orientation = math.atan2(dy, dx)

        # Move toward player if not too close and if in range
        if c.Monster.ATTACK_RANGE < dist < c.World.DETECTION_RANGE + c.Player.SIZE // 2:
            self.x += math.cos(self.orientation) * c.Monster.SPEED
            self.y += math.sin(self.orientation) * c.Monster.SPEED

        # Attack player if close enough
        if dist < c.Monster.ATTACK_RANGE * 10:
            hit = self.start_attack_anim(dist)
            if hit:
                player.receive_damage(c.Monster.DAMAGE)
            
        # Look at player
        self.orientation += math.pi / 2
    
        # Attacking state
        self.update_attack_anim(dt)

    def draw(self, screen, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        super().draw(
            screen,
            screen_x,
            screen_y,
            c.Monster.SIZE,
            c.Colors.RED,
            self.orientation,
            self.attack_progress,
            self.attack_hand,
            bar_width=60,
            bar_height=8,
            health_bar_offset=10
        )
