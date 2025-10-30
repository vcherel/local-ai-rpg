from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame
import core.constants as c
from core.utils import random_color

if TYPE_CHECKING:
    from core.camera import Camera


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
            
    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])

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
        size = c.Entities.ITEM_SIZE // 2
        border_width = 2  # outline thickness
        
        # Add generous padding to prevent clipping during rotation
        padding = size + border_width + 4
        surface_size = c.Entities.ITEM_SIZE + padding * 2
        item_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        item_center = (surface_size // 2, surface_size // 2)
        
        # Draw the shape centered on the padded surface
        draw_shape_with_border(item_surface, self.shape, item_center, size, self.color, border_width)
        
        # Rotate with enough space around edges
        rotated_surface = pygame.transform.rotate(item_surface, math.degrees(-visual_angle))
        rect = rotated_surface.get_rect(center=center)
        
        # Blit to screen
        surface.blit(rotated_surface, rect.topleft)

def draw_shape_with_border(surface, shape, center, size, color, border_width):
    """Draw a shape with a border using get_polygon_points"""
    if shape == "circle":
        pygame.draw.circle(surface, c.Colors.BLACK, center, size + border_width)
        pygame.draw.circle(surface, color, center, size)
    else:
        if shape == "triangle":
            points = get_polygon_points(center, size, 3)
        elif shape == "pentagon":
            points = get_polygon_points(center, size, 5)
        elif shape == "star":
            points = get_polygon_points(center, size, 10, inner_radius_factor=0.5)
        else:
            raise ValueError(f"Unknown shape: {shape}")

        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)
        pygame.draw.polygon(surface, color, points)

def get_polygon_points(center, size, num_points, inner_radius_factor=None):
    """Generate points for regular polygons or stars"""
    points = []
    for i in range(num_points):
        angle = i * (360 / num_points)
        if inner_radius_factor and i % 2 == 1:
            r = size * inner_radius_factor
        else:
            r = size
        x = center[0] + r * math.sin(math.radians(angle))
        y = center[1] - r * math.cos(math.radians(angle))
        points.append((x, y))
    return points
