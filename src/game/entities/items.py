import math
import random

import pygame
from core.camera import Camera
import core.constants as c
from core.utils import random_color


class Item:
    """The items we can take from the ground and have in inventory"""

    def __init__(self, x, y, name):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.name = name
        self.color = random_color()
        self.shape = random.choice(["circle", "triangle", "pentagon", "star"])
        self.picked_up = False
    
    def draw(self, surface: pygame.Surface, camera: Camera=None, x=None, y=None):
        """Draw item with correct position"""
        # Determine position
        draw_x = x if x is not None else self.x
        draw_y = y if y is not None else self.y
        
        if camera:
            # Convert world position to screen position
            screen_x, screen_y = camera.world_to_screen(draw_x, draw_y)
            visual_angle = self.angle
        else:
            screen_x, screen_y = draw_x, draw_y
            visual_angle = 0  # default angle when no camera
        
        center = (screen_x, screen_y)
        size = c.World.ITEM_SIZE // 2
        border_width = 2  # outline thickness
        
        # Add generous padding to prevent clipping during rotation
        padding = size + border_width + 4
        surface_size = c.World.ITEM_SIZE + padding * 2
        item_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        item_center = (surface_size // 2, surface_size // 2)
        
        # Draw the shape centered on the padded surface
        draw_shape_with_border(item_surface, self.shape, item_center, size, self.color, border_width)
        
        # Rotate with enough space around edges
        rotated_surface = pygame.transform.rotate(item_surface, math.degrees(-visual_angle))
        rect = rotated_surface.get_rect(center=center)
        
        # Blit to screen
        surface.blit(rotated_surface, rect.topleft)
    
    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])


def draw_shape_with_border(surface, shape, center, size, color, border_width):
    """Draw a shape with a border"""
    if shape == "circle":
        pygame.draw.circle(surface, c.Colors.BLACK, center, size + border_width - 5)
        pygame.draw.circle(surface, color, center, size - 5)
    elif shape == "triangle":
        points = [
            (center[0], center[1] - size),
            (center[0] - size, center[1] + size),
            (center[0] + size, center[1] + size)
        ]
        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)
        pygame.draw.polygon(surface, color, points)
    elif shape == "pentagon":
        points = [
            (center[0], center[1] - size),
            (center[0] - size * 0.95, center[1] - size * 0.31),
            (center[0] - size * 0.59, center[1] + size * 0.81),
            (center[0] + size * 0.59, center[1] + size * 0.81),
            (center[0] + size * 0.95, center[1] - size * 0.31)
        ]
        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)
        pygame.draw.polygon(surface, color, points)
    elif shape == "star":
        points = []
        for i in range(10):
            angle = i * 36
            r = size if i % 2 == 0 else size / 2
            x = center[0] + r * math.sin(math.radians(angle))
            y = center[1] - r * math.cos(math.radians(angle))
            points.append((x, y))
        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)    
        pygame.draw.polygon(surface, color, points)
