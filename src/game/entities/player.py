from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.particles import get_particles
from game.entities.entities import Entity
from game.entities.stats import Stats

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

        self.stats = Stats(save_system.load("stats", None))
        self.max_hp = self.stats.max_hp()
        self.hp = self.max_hp

        saved = save_system.load("player", None)
        if saved:
            self.x = saved["x"]
            self.y = saved["y"]
            self.hp = saved["hp"]

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "hp": self.hp}

    def save_stats(self):
        self.save_system.update("stats", self.stats.to_dict())

    def get_pos(self, distance=None):
        if distance is not None:
            attack_x = self.x + math.sin(self.orientation) * distance
            attack_y = self.y - math.cos(self.orientation) * distance
            return (attack_x, attack_y)
        return (self.x, self.y)

    def move(self, camera_pos, dt):
        keys = pygame.key.get_pressed()

        running = bool(keys[pygame.K_LSHIFT])
        base_speed = c.Player.RUN_SPEED if running else c.Player.SPEED
        actual_speed = base_speed * self.stats.speed_multiplier()

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

            # Running is what trains speed; plain walking does not.
            if running:
                self.stats.train("speed", c.Stats.XP_PER_RUN_FRAME * move_factor)

        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - c.Screen.ORIGIN_X
        dy = mouse_y - c.Screen.ORIGIN_Y
        self.orientation = math.atan2(dx, -dy)

        self.update_attack_anim(dt)

        self.max_hp = self.stats.max_hp()
        if self.hp < self.max_hp:
            self.hp = min(self.hp + self.stats.regen_rate() * dt, self.max_hp)

    def best_weapon_bonus(self) -> int:
        return max((item.bonus for item in self.inventory if item.item_type == "weapon"), default=0)

    def best_armor_bonus(self) -> int:
        return max((item.bonus for item in self.inventory if item.item_type == "armor"), default=0)

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

    def receive_damage(self, damage):
        # Taking hits trains resistance and, more slowly, vitality.
        self.stats.train("resistance", c.Stats.XP_PER_DAMAGE_TAKEN)
        self.stats.train("vitality", c.Stats.XP_PER_DAMAGE_TAKEN * 0.5)
        self.max_hp = self.stats.max_hp()

        reduction = self.best_armor_bonus() + self.stats.damage_reduction()
        actual = max(damage - reduction, 1)
        self.hp -= actual
        self.last_damage_ms = pygame.time.get_ticks()
        play_sound("player_hurt")
        get_particles().spawn_burst(self.x, self.y, c.Colors.RED, count=8, speed=4, life=350, size=4)

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
