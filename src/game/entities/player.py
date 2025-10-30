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

    def get_pos(self, distance=None):
        if distance is not None:
            attack_x = self.x + math.sin(self.orientation) * distance
            attack_y = self.y - math.cos(self.orientation) * distance
            return (attack_x, attack_y)
        return (self.x, self.y)

    def start_attack_anim(self):
        """Start an attack animation with a random hand"""
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = random.choice(["left", "right"])

    def update_attack_anim(self, dt):
        """Update attack animation progress"""
        if self.attack_in_progress:
            self.attack_progress += dt * c.Entities.SWING_SPEED 
            if self.attack_progress >= 1.0:
                self.attack_progress = 0.0
                self.attack_in_progress = False

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

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

    def receive_damage(self, damage):
        self.hp -= damage

    def draw(self, screen: pygame.Surface, show_reach=False, show_interaction=False, show_detection=False):
            """Draw player at screen bottom center, looking towards mouse"""
            draw_human(screen,
                        c.Screen.ORIGIN_X,
                        c.Screen.ORIGIN_Y,
                        c.Player.SIZE,
                        c.Colors.PLAYER,
                        self.orientation,
                        self.attack_progress,
                        self.attack_hand)
            
            # Health bar
            bar_width = 800
            bar_height = 30
            margin_bottom = 30  # distance from bottom edge
            x = c.Screen.WIDTH // 2 - bar_width // 2
            y = c.Screen.HEIGHT - margin_bottom - bar_height

            # Background
            pygame.draw.rect(screen, c.Colors.MENU_BACKGROUND, (x, y, bar_width, bar_height))
            # Fill according to HP
            health_ratio = max(self.hp / c.Player.HP, 0)
            pygame.draw.rect(screen, c.Colors.GREEN, (x, y, bar_width * health_ratio, bar_height))
            # Border
            pygame.draw.rect(screen, c.Colors.BORDER, (x, y, bar_width, bar_height), 5)

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