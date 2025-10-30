import math
import pygame
import random
from typing import List

import core.constants as c
from core.camera import Camera
from core.save import SaveSystem
from game.entities.entities import draw_human
from game.entities.items import Item


class Player:
    """The unique player of the game"""

    def __init__(self, save_system, coins):
        # Position
        self.x = c.World.WORLD_SIZE // 2
        self.y = c.World.WORLD_SIZE // 2
        self.orientation = 0

        # Inventory
        self.save_system: SaveSystem = save_system
        self.inventory: List[Item] = []
        self.coins = coins

        # Action
        self.attack_in_progress = False
        self.attack_progress = 0.0  # 0.0 -> 1.0
        self.attack_hand = "left"  # or "right"

        # Combat
        self.hp = c.Player.HP

    def start_attack_anim(self):
        """Start an attack animation with a random hand"""
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = random.choice(["left", "right"])

    def update_attack_anim(self, dt):
        """Update attack animation progress"""
        if self.attack_in_progress:
            self.attack_progress += dt * 0.008  # speed of swing
            if self.attack_progress >= 1.0:
                self.attack_progress = 0.0
                self.attack_in_progress = False

    def get_attack_pos(self):
        """Return the world position of the player's attack (tip of the swing)."""
        # Attack tip position in world coordinates (forward from player)
        attack_x = self.x + math.sin(self.orientation) * c.Player.ATTACK_REACH
        attack_y = self.y - math.cos(self.orientation) * c.Player.ATTACK_REACH
        return (attack_x, attack_y)

    def move(self, camera: Camera, clock: pygame.time.Clock):
        """Move player toward mouse position"""
        keys = pygame.key.get_pressed()

        # Running state
        actual_speed = c.Player.RUN_SPEED if keys[pygame.K_LSHIFT] else c.Player.SPEED

        # Forward/back movement relative to mouse
        if keys[pygame.K_z] or keys[pygame.K_s]:
            # Mouse position on screen
            mouse_x, mouse_y = pygame.mouse.get_pos()

            # Convert mouse screen position to world coordinates
            world_mouse_x = mouse_x - c.Screen.ORIGIN_X + camera.x
            world_mouse_y = mouse_y - c.Screen.ORIGIN_Y + camera.y

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
        dt = clock.get_time()
        self.update_attack_anim(dt)

    def draw(self, screen: pygame.Surface, show_reach=False):
            """Draw player at screen bottom center, looking towards mouse"""
            draw_human(screen,
                        c.Screen.ORIGIN_X,
                        c.Screen.ORIGIN_Y,
                        c.Player.SIZE,
                        c.Colors.PLAYER,
                        self.orientation,
                        self.attack_progress,
                        self.attack_hand)
            
            if show_reach:
                # Calculate attack reach position on screen
                screen_attack_x = c.Screen.ORIGIN_X + math.sin(self.orientation) * c.Player.ATTACK_REACH
                screen_attack_y = c.Screen.ORIGIN_Y - math.cos(self.orientation) * c.Player.ATTACK_REACH
                
                # Draw translucent reach circle
                reach_surface = pygame.Surface((c.Player.ATTACK_REACH * 2, c.Player.ATTACK_REACH * 2), pygame.SRCALPHA)
                pygame.draw.circle(
                    reach_surface,
                    (255, 0, 0, 80),  # RGBA with alpha
                    (c.Player.ATTACK_REACH, c.Player.ATTACK_REACH),
                    c.Player.ATTACK_REACH,
                    2  # thickness
                )
                screen.blit(reach_surface, (screen_attack_x - c.Player.ATTACK_REACH, screen_attack_y - c.Player.ATTACK_REACH))

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)
