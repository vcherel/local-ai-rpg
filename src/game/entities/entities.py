import math
import pygame

import core.constants as c

# TODO : unify classes
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
