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

# TODO : divide files
# TODO : unify classes
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

        self.name = None # Not attributed initially
        self.hp = c.World.NPC_HP

        # Quest
        self.has_active_quest = False
        self.quest_content = None
        self.quest_item: Item = None
    
    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if self.name is None:
            self.name = npc_name_generator.get_name()
    
    def get_display_name(self) -> str:
        if self.name:
            return self.name
        return ""

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        
        draw_character(screen, screen_x, screen_y, c.World.NPC_SIZE, self.color, self.angle)
        
        # Exclamation mark for active quests
        if self.has_active_quest:
            font = pygame.font.Font(None, 45)
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(screen_x, screen_y - c.World.NPC_SIZE // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)
        
        # Name label
        display_name = self.get_display_name()
        if display_name:
            name_font = pygame.font.SysFont("arial", 16)
            name_surface = name_font.render(display_name, True, c.Colors.WHITE)
            name_rect = name_surface.get_rect(center=(screen_x, screen_y + c.World.NPC_SIZE // 2 + 15))
            
            # Background box
            bg_rect = name_rect.inflate(10, 4)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg_surface, (0, 0, 0, 180), bg_surface.get_rect(), border_radius=6)
            screen.blit(bg_surface, bg_rect)
            
            # Draw name
            screen.blit(name_surface, name_rect)
    
    def receive_damage(self, damage):
        """Returns True if the NPC died"""
        self.hp -= damage
        if self.hp <= 1:
            return True
        return False

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])


class Player:
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
            draw_character(screen,
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


class Monster:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.hp = c.World.MONSTER_HP

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        draw_character(screen, screen_x, screen_y, c.World.MONSTER_SIZE, c.Colors.RED, self.angle)
    
    def receive_damage(self, damage):
        """Returns True if the monster died"""
        self.hp -= damage
        if self.hp <= 1:
            return True
        return False

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])
