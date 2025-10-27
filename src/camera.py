import math

import constants as c

class Camera:
    """Handles world rotation"""
    def __init__(self):
        self.angle = 0
        self.x = 0
        self.y = 0

    def update_angle(self, delta_angle):
        """Simplest update"""
        self.angle += delta_angle

    def update_position(self, x, y):
        """Update camera position"""
        self.x = x
        self.y = y
    
    def rotate_point(self, x, y):
        """Rotate a point around an origin"""
        # Translate to origin (we remove camera position too)
        translated_x = x - c.Screen.ORIGIN_X - self.x
        translated_y = y - c.Screen.ORIGIN_Y - self.y
        
        # Rotate
        cos_angle = math.cos(self.angle)
        sin_angle = math.sin(self.angle)
        
        rotated_x = translated_x * cos_angle - translated_y * sin_angle
        rotated_y = translated_x * sin_angle + translated_y * cos_angle
        
        # Translate back
        return rotated_x + c.Screen.ORIGIN_X, rotated_y + c.Screen.ORIGIN_Y
