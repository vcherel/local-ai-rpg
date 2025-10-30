import math
import random
import pygame

import core.constants as c

class Entity:
    """Base class for all positioned entities in the world"""
    def __init__(self, x, y, color, size, hp, max_hp):
        self.x = x
        self.y = y
        self.orientation = random.uniform(0, 2 * math.pi)
        self.color = color
        self.size = size
        self.hp = hp
        self.max_hp = max_hp
        self.attack_in_progress = False
        self.attack_progress = 0.0
        self.attack_hand = "left"
        
    def receive_damage(self, damage):
        """Returns True if the entity died"""
        self.hp -= damage
        return self.hp <= 0

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])
    
    def draw_health_bar(self, screen, x, y, width, height, color):
        pygame.draw.rect(screen, c.Colors.MENU_BACKGROUND, (x, y, width, height))
        ratio = max(self.hp / self.max_hp, 0)
        pygame.draw.rect(screen, color, (x, y, width * ratio, height))
        pygame.draw.rect(screen, c.Colors.BORDER, (x, y, width, height), 2)

    def start_attack_anim(self):
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = random.choice(["left", "right"])

    def update_attack_anim(self, dt):
        if self.attack_in_progress:
            self.attack_progress += dt * c.Entities.SWING_SPEED
            if self.attack_progress >= 1.0:
                self.attack_progress = 0.0
                self.attack_in_progress = False


def draw_human(surface: pygame.Surface, x: int, y: int, size: int, color: tuple, angle: float, attack_progress: float = 0.0, attack_hand: str = None):
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
