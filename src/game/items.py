import math
import random

import pygame
from core.camera import Camera
import core.constants as c
from core.utils import random_color


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
    
    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])
