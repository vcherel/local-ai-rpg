from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from game.entities.entities import Entity

if TYPE_CHECKING:
    from core.save import SaveSystem


class Player(Entity):
    def __init__(self, save_system, coins):
        super().__init__(
            c.World.WORLD_SIZE // 2, c.World.WORLD_SIZE // 2, c.Colors.PLAYER, c.Player.SIZE, c.Player.HP, c.Player.HP
        )

        self.save_system: SaveSystem = save_system
        self.inventory = []
        self.coins = coins

    def get_pos(self, distance=None):
        if distance is not None:
            attack_x = self.x + math.sin(self.orientation) * distance
            attack_y = self.y - math.cos(self.orientation) * distance
            return (attack_x, attack_y)
        return (self.x, self.y)

    def move(self, camera_pos, dt):
        keys = pygame.key.get_pressed()

        actual_speed = c.Player.RUN_SPEED if keys[pygame.K_LSHIFT] else c.Player.SPEED

        forward = keys[pygame.K_z] or keys[pygame.K_w]

        if forward or keys[pygame.K_s]:
            mouse_x, mouse_y = pygame.mouse.get_pos()

            world_mouse_x = mouse_x - c.Screen.ORIGIN_X + camera_pos[0]
            world_mouse_y = mouse_y - c.Screen.ORIGIN_Y + camera_pos[1]

            dx = world_mouse_x - self.x
            dy = world_mouse_y - self.y
            dist = math.hypot(dx, dy)

            if dist != 0:
                dx /= dist
                dy /= dist

            speed = actual_speed if forward else -actual_speed / 1.5
            move_factor = dt * c.TARGET_FPS / 1000.0
            self.x += dx * speed * move_factor
            self.y += dy * speed * move_factor
            self.clamp_to_world()

        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - c.Screen.ORIGIN_X
        dy = mouse_y - c.Screen.ORIGIN_Y
        self.orientation = math.atan2(dx, -dy)

        self.update_attack_anim(dt)

        if self.hp < c.Player.HP:
            self.hp = min(self.hp + c.Player.REGEN_RATE * dt, c.Player.HP)

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

    def receive_damage(self, damage):
        self.hp -= damage

    def draw(self, screen):
        super().draw(
            screen,
            c.Screen.ORIGIN_X,
            c.Screen.ORIGIN_Y,
            c.Player.SIZE,
            c.Colors.PLAYER,
            self.orientation,
            self.attack_progress,
            self.attack_hand,
            bar_width=800,
            bar_height=30,
            health_bar_offset=360,
        )
