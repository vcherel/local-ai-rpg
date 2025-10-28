import math
import time
import pygame
import random
from typing import List

import core.constants as c
from core.camera import Camera
from core.save import SaveSystem
from core.utils import random_color
from llm.name_generator import NPCNameGenerator

def draw_character(surface: pygame.Surface, x: int, y: int, size: int, color: tuple, angle: float):
    """Draw a character (player or NPC) with body and arms
    
    Args:
        angle: rotation angle in radians (0 = facing up)
    """
    border_thickness = 2
    arm_radius = size // 3.5
    extra_space = arm_radius * 2
    
    char_surf = pygame.Surface(
        (size + border_thickness * 2 + extra_space * 2, 
         size + border_thickness * 2),
        pygame.SRCALPHA
    )
    
    x_offset = extra_space

    # Draw body with border
    pygame.draw.circle(
        char_surf,
        c.Colors.BLACK,
        (x_offset + size // 2 + border_thickness, size // 2 + border_thickness),
        size // 2 + border_thickness
    )
    pygame.draw.circle(
        char_surf,
        color,
        (x_offset + size // 2 + border_thickness, size // 2 + border_thickness),
        size // 2
    )
    
    # Draw arms
    arm_y = (size + border_thickness * 2) // 3.5
    distance_arm = 10
    
    # Left arm
    left_arm_x = arm_radius + distance_arm
    pygame.draw.circle(char_surf, c.Colors.BLACK, (left_arm_x, arm_y), arm_radius)
    pygame.draw.circle(char_surf, color, (left_arm_x, arm_y), arm_radius - border_thickness)
    
    # Right arm
    right_arm_x = size + border_thickness * 2 + extra_space * 2 - arm_radius - distance_arm
    pygame.draw.circle(char_surf, c.Colors.BLACK, (right_arm_x, arm_y), arm_radius)
    pygame.draw.circle(char_surf, color, (right_arm_x, arm_y), arm_radius - border_thickness)

    # Rotate if needed
    if angle != 0:
        char_surf = pygame.transform.rotate(char_surf, math.degrees(-angle))
    
    # Blit to main surface
    rect = char_surf.get_rect(center=(x, y))
    surface.blit(char_surf, rect)

class NPC:
    def __init__(self, x, y, npc_id):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.color = random_color()
        self.id = npc_id
        self.has_active_quest = False
        self.quest_content = None
        self.quest_item: Item = None
        self.quest_complete = False
        
        # NPCs start without a specific name
        self.name = None
        self.has_been_named = False
    
    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if not self.has_been_named:
            self.name = npc_name_generator.get_name()
            self.has_been_named = True
    
    def get_display_name(self) -> str:
        if self.has_been_named and self.name:
            return self.name
        return ""

    def draw(self, screen: pygame.Surface, camera: Camera):
        """Draw NPC with correct rotation relative to camera"""
        # Rotate NPC position by camera
        rotated_x, rotated_y = camera.rotate_point(self.x, self.y)
        
        # Draw character
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
        self.x = c.Game.WORLD_SIZE // 2
        self.y = c.Game.WORLD_SIZE // 2

        self.save_system: SaveSystem = save_system
        self.inventory: List[Item] = []
        self.coins = coins

        self.is_running = False
    
    def move(self, distance, angle):
        """Move player in the direction they are facing"""
        run_mul = 2 if self.is_running else 1

        dx = -math.sin(angle) * distance * run_mul
        dy = -math.cos(angle) * distance * run_mul

        self.x += dx
        self.y += dy

    def draw(self, screen: pygame.Surface):
        """Draw player at screen bottom center, always facing up"""
        draw_character(screen, c.Screen.ORIGIN_X, c.Screen.ORIGIN_Y, c.Size.PLAYER, c.Colors.PLAYER, 0)

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

class Item:
    def __init__(self, x, y, name):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.name = name
        self.color = random_color()
        self.shape = random.choice(["circle", "triangle", "pentagon", "star"])
        self.picked_up = False
    
    def draw(self, surface: pygame.Surface, camera: Camera=None, x=None, y=None):
        """Draw item with correct rotation relative to camera"""
        # Determine position
        draw_x = x if x is not None else self.x
        draw_y = y if y is not None else self.y

        if camera:
            # Rotate item position by camera
            rotated_x, rotated_y = camera.rotate_point(draw_x, draw_y)
            visual_angle = self.angle + camera.angle
        else:
            rotated_x, rotated_y = draw_x, draw_y
            visual_angle = 0  # default angle when no camera

        center = (rotated_x, rotated_y)
        size = c.Size.ITEM // 2
        border = 2  # outline thickness

        # Add generous padding to prevent clipping during rotation
        padding = size + border + 4
        surface_size = c.Size.ITEM + padding * 2
        item_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        item_center = (surface_size // 2, surface_size // 2)

        # Draw the shape centered on the padded surface
        if self.shape == "circle":
            pygame.draw.circle(item_surface, c.Colors.BLACK, item_center, size + border - 5)
            pygame.draw.circle(item_surface, self.color, item_center, size - 5)
        elif self.shape == "triangle":
            points = [
                (item_center[0], item_center[1] - size),
                (item_center[0] - size, item_center[1] + size),
                (item_center[0] + size, item_center[1] + size)
            ]
            pygame.draw.polygon(item_surface, c.Colors.BLACK, points, border)
            pygame.draw.polygon(item_surface, self.color, points)
        elif self.shape == "pentagon":
            points = [
                (item_center[0], item_center[1] - size),
                (item_center[0] - size * 0.95, item_center[1] - size * 0.31),
                (item_center[0] - size * 0.59, item_center[1] + size * 0.81),
                (item_center[0] + size * 0.59, item_center[1] + size * 0.81),
                (item_center[0] + size * 0.95, item_center[1] - size * 0.31)
            ]
            pygame.draw.polygon(item_surface, c.Colors.BLACK, points, border)
            pygame.draw.polygon(item_surface, self.color, points)
        elif self.shape == "star":
            points = []
            for i in range(10):
                angle = i * 36
                r = size if i % 2 == 0 else size / 2
                x = item_center[0] + r * math.sin(math.radians(angle))
                y = item_center[1] - r * math.cos(math.radians(angle))
                points.append((x, y))
            pygame.draw.polygon(item_surface, c.Colors.BLACK, points, border)
            pygame.draw.polygon(item_surface, self.color, points)

        # Rotate with enough space around edges
        rotated_surface = pygame.transform.rotate(item_surface, math.degrees(-visual_angle))
        rect = rotated_surface.get_rect(center=center)

        # Blit to screen
        surface.blit(rotated_surface, rect.topleft)

    def distance_to_player(self, player):
        return math.hypot(self.x - player.x, self.y - player.y)
