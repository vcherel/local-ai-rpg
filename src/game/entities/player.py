from __future__ import annotations

import math
import pygame
from typing import TYPE_CHECKING

import core.constants as c
from game.entities.entities import Entity

if TYPE_CHECKING:
    from core.save import SaveSystem


class Player(Entity):
    """The unique player of the game"""
    def __init__(self, save_system, coins):
        super().__init__(c.World.WORLD_SIZE//2, c.World.WORLD_SIZE//2, c.Colors.PLAYER, c.Player.SIZE, c.Player.HP, c.Player.HP)

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
        """Move player toward mouse position"""
        keys = pygame.key.get_pressed()

        # Running state
        actual_speed = c.Player.RUN_SPEED if keys[pygame.K_LSHIFT] else c.Player.SPEED

        # Forward/back movement relative to mouse
        if keys[pygame.K_z] or keys[pygame.K_s]:
            # Mouse position on screen
            mouse_x, mouse_y = pygame.mouse.get_pos()

            # Convert mouse screen position to world coordinates
            world_mouse_x = mouse_x - c.Screen.ORIGIN_X + camera_pos[0]
            world_mouse_y = mouse_y - c.Screen.ORIGIN_Y + camera_pos[1]

            # Vector from player to mouse
            dx = world_mouse_x - self.x
            dy = world_mouse_y - self.y
            dist = math.hypot(dx, dy)

            if dist != 0:
                dx /= dist
                dy /= dist

            # Forward/backward
            speed = actual_speed if keys[pygame.K_z] else -actual_speed / 2
            self.x += dx * speed
            self.y += dy * speed

        # Update player orientation toward mouse
        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - c.Screen.ORIGIN_X
        dy = mouse_y - c.Screen.ORIGIN_Y
        self.orientation = math.atan2(dx, -dy)

        # Attacking state
        self.update_attack_anim(dt)

        # Health regeneration
        if self.hp < c.Player.HP:
            self.hp = min(self.hp + c.Player.REGEN_RATE * dt, c.Player.HP)

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

    def receive_damage(self, damage):
        self.hp -= damage

    def draw(self, screen, show_reach=False, show_interaction=False, show_detection=False):
        # Draw player using Entity base logic
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
            health_bar_offset=360
        )

        # Optional overlays
        if show_reach:
            draw_circle(screen, c.Player.ATTACK_REACH, (255, 0, 0, 80), self.orientation)
        if show_interaction:
            draw_circle(screen, c.Player.INTERACTION_DISTANCE, (0, 255, 0, 80), self.orientation)
        if show_detection:
            draw_circle(screen, c.World.DETECTION_RANGE, (0, 0, 255, 80))


def draw_circle(screen: pygame.Surface, radius, color, origin_x=c.Screen.ORIGIN_X, origin_y=c.Screen.ORIGIN_Y, orientation=None):
    if orientation is not None:
        # Calculate reach position
        origin_x = origin_x + math.sin(orientation) * radius
        origin_y = origin_y - math.cos(orientation) * radius
                
    # Create translucent surface
    reach_surface = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    pygame.draw.circle(
        reach_surface,
        color,
        (radius, radius),
        radius,
        2  # thickness
    )
                
    # Blit to main screen
    screen.blit(reach_surface, (origin_x - radius, origin_y - radius))
