import math
import time
import pygame
import random
from typing import List

import core.constants as c
from core.camera import Camera
from core.save import SaveSystem
from core.utils import random_color
from game.items import Item
from llm.name_generator import NPCNameGenerator

def draw_character(surface: pygame.Surface, x: int, y: int, size: int, color: tuple, angle: float, attack_progress: float = 0.0, attack_hand: str = None):
    """Draw a character with body and arms, including attack animation."""
    border_thickness = 2
    arm_radius = size // 3.5
    extra_space = arm_radius * 2
    
    # Make surface larger to accommodate rotation
    base_width = size + border_thickness * 2 + extra_space * 2
    base_height = size + border_thickness * 2
    
    # Add padding for rotation (diagonal of the surface)
    padding = int(math.sqrt(base_width**2 + base_height**2) - min(base_width, base_height)) // 2 + 10
    
    char_surf = pygame.Surface(
        (base_width + padding * 2, base_height + padding * 2),
        pygame.SRCALPHA
    )
    
    x_offset = extra_space + padding
    y_offset = padding
    
    # Draw body with border
    pygame.draw.circle(
        char_surf, c.Colors.BLACK,
        (x_offset + size // 2 + border_thickness, y_offset + size // 2 + border_thickness),
        size // 2 + border_thickness
    )
    pygame.draw.circle(
        char_surf, color,
        (x_offset + size // 2 + border_thickness, y_offset + size // 2 + border_thickness),
        size // 2
    )
    
    # Draw arms
    arm_y = y_offset + (size + border_thickness * 2) // 3.5
    distance_arm = 10
    
    def draw_arm(cx, cy):
        pygame.draw.circle(char_surf, c.Colors.BLACK, (cx, cy), arm_radius)
        pygame.draw.circle(char_surf, color, (cx, cy), arm_radius - border_thickness)
    
    # Left arm
    left_arm_x = padding + arm_radius + distance_arm
    left_arm_y = arm_y
    if attack_hand == "left":
        left_arm_x += int(attack_progress * 15)
        left_arm_y -= int(attack_progress * 15)
    draw_arm(left_arm_x, left_arm_y)
    
    # Right arm
    right_arm_x = base_width + padding - arm_radius - distance_arm
    right_arm_y = arm_y
    if attack_hand == "right":
        right_arm_x -= int(attack_progress * 15)
        right_arm_y -= int(attack_progress * 15)
    draw_arm(right_arm_x, right_arm_y)
    
    # Rotate if needed
    if angle != 0:
        char_surf = pygame.transform.rotate(char_surf, math.degrees(-angle))
    
    # Blit to main surface
    rect = char_surf.get_rect(center=(x, y))
    surface.blit(char_surf, rect)

class NPC:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.color = random_color()

        # Name (not attributed initially)
        self.name = None

        # Quest
        self.has_active_quest = False
        self.quest_content = None
        self.quest_item: Item = None
        self.quest_complete = False
    
    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if self.name is None:
            self.name = npc_name_generator.get_name()
    
    def get_display_name(self) -> str:
        if self.name:
            return self.name
        return ""

    def draw(self, screen: pygame.Surface, camera: Camera):
        rotated_x, rotated_y = camera.rotate_point(self.x, self.y)
        real_angle = self.angle + camera.angle
        
        draw_character(screen, rotated_x, rotated_y, c.Size.NPC, self.color, real_angle)
        
        # Exclamation mark for active quests
        if self.has_active_quest and not self.quest_complete:
            font = pygame.font.Font(None, 45)
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(rotated_x, rotated_y - c.Size.NPC // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)
        
        # Name label
        display_name = self.get_display_name()
        if display_name:
            name_font = pygame.font.SysFont("arial", 16)
            name_surface = name_font.render(display_name, True, c.Colors.WHITE)
            name_rect = name_surface.get_rect(center=(rotated_x, rotated_y + c.Size.NPC // 2 + 15))
            
            # Background box
            bg_rect = name_rect.inflate(10, 4)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg_surface, (0, 0, 0, 180), bg_surface.get_rect(), border_radius=6)
            screen.blit(bg_surface, bg_rect)
            
            # Draw name
            screen.blit(name_surface, name_rect)

    def distance_to_player(self, player):
        return ((self.x - player.x)**2 + (self.y - player.y)**2)**0.5

class Player:
    def __init__(self, save_system, coins):
        # Position
        self.x = c.Game.WORLD_SIZE // 2
        self.y = c.Game.WORLD_SIZE // 2
        self.orientation = 0

        # Inventory
        self.save_system: SaveSystem = save_system
        self.inventory: List[Item] = []
        self.coins = coins

        # Action
        self.attack_in_progress = False
        self.attack_progress = 0.0  # 0.0 -> 1.0
        self.attack_hand = "left"  # or "right"

    def start_attack(self):
        """Start an attack animation with a random hand"""
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = random.choice(["left", "right"])

    def update_attack(self, dt):
        """Update attack animation progress"""
        if self.attack_in_progress:
            self.attack_progress += dt * 0.008  # speed of swing
            if self.attack_progress >= 1.0:
                self.attack_progress = 0.0
                self.attack_in_progress = False
        
    
    def move(self, camera: Camera, clock: pygame.time.Clock):
        """Move player toward mouse position"""
        keys = pygame.key.get_pressed()

        # Running state
        actual_speed = c.Game.PLAYER_RUN_SPEED if keys[pygame.K_LSHIFT] else c.Game.PLAYER_SPEED

        # Forward/back movement relative to mouse
        if keys[pygame.K_z] or keys[pygame.K_s]:
            # Mouse position on screen
            mouse_x, mouse_y = pygame.mouse.get_pos()

            # Convert mouse screen position to world coordinates
            world_mouse_x = (mouse_x - c.Screen.ORIGIN_X) * math.cos(-camera.angle) - (mouse_y - c.Screen.ORIGIN_Y) * math.sin(-camera.angle) + camera.x
            world_mouse_y = (mouse_x - c.Screen.ORIGIN_X) * math.sin(-camera.angle) + (mouse_y - c.Screen.ORIGIN_Y) * math.cos(-camera.angle) + camera.y

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

        # Rotate camera using Q/D
        if keys[pygame.K_q]:
            camera.update_angle(c.Game.PLAYER_TURN_SPEED)
        if keys[pygame.K_d]:
            camera.update_angle(-c.Game.PLAYER_TURN_SPEED)

        # Update player orientation toward mouse
        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - c.Screen.ORIGIN_X
        dy = mouse_y - c.Screen.ORIGIN_Y
        self.orientation = math.atan2(dx, -dy)

        # Attacking state
        dt = clock.get_time()
        self.update_attack(dt)


    def draw(self, screen: pygame.Surface):
        """Draw player at screen bottom center, looking towards mouse"""
        draw_character(screen,
                       c.Screen.ORIGIN_X,
                       c.Screen.ORIGIN_Y,
                       c.Size.PLAYER,
                       c.Colors.PLAYER,
                       self.orientation,
                       self.attack_progress,
                       self.attack_hand)

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

class Monster:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)

    def draw(self, screen: pygame.Surface, camera: Camera):
        rotated_x, rotated_y = camera.rotate_point(self.x, self.y)
        real_angle = self.angle + camera.angle

        draw_character(screen, rotated_x, rotated_y, c.Size.MONSTER, c.Colors.RED, real_angle)

    def distance_to_player(self, player):
        return ((self.x - player.x)**2 + (self.y - player.y)**2)**0.5
