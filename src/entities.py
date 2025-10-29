import math
import time
import pygame
import random
from typing import List

import core.constants as c
from core.camera import Camera
from core.save import SaveSystem
from core.utils import random_color
from items import Item
from llm.name_generator import NPCNameGenerator

def draw_character(surface: pygame.Surface, x: int, y: int, size: int, color: tuple, angle: float, attack_progress: float = 0.0, attack_hand: str = None):
    """Draw a character with body and arms, including attack animation."""
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

    def draw_arm(cx):
        pygame.draw.circle(char_surf, c.Colors.BLACK, (cx, arm_y), arm_radius)
        pygame.draw.circle(char_surf, color, (cx, arm_y), arm_radius - border_thickness)

    # Left arm
    left_arm_x = arm_radius + distance_arm
    if attack_hand == "left":
        # extend arm during attack
        left_arm_x += int(attack_progress * 10)  # extend outward
    draw_arm(left_arm_x)

    # Right arm
    right_arm_x = size + border_thickness * 2 + extra_space * 2 - arm_radius - distance_arm
    if attack_hand == "right":
        # extend arm during attack
        right_arm_x -= int(attack_progress * 10)
    draw_arm(right_arm_x)

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
        # Position
        self.x = c.Game.WORLD_SIZE // 2
        self.y = c.Game.WORLD_SIZE // 2
        self.orientation = 0

        # Inventory
        self.save_system: SaveSystem = save_system
        self.inventory: List[Item] = []
        self.coins = coins

        # Action
        self.is_running = False
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
            self.attack_progress += dt * 0.01  # speed of swing
            if self.attack_progress >= 1.0:
                self.attack_progress = 0.0
                self.attack_in_progress = False
    
    def move(self, distance, angle, orientation):
        """Move player in the direction they are facing"""
        run_mul = 2 if self.is_running else 1

        dx = -math.sin(angle) * distance * run_mul
        dy = -math.cos(angle) * distance * run_mul

        self.x += dx
        self.y += dy

        self.orientation = orientation

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
