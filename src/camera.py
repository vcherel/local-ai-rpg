import math

import constants as c

class Camera:
    """Handles world rotation"""
    def __init__(self):
        self.angle = 0
        self.x = 0  # Player's world x
        self.y = 0  # Player's world y

    def update_angle(self, delta_angle):
        """Simplest update"""
        self.angle += delta_angle

    def update_position(self, x, y):
        """Update camera position"""
        self.x = x
        self.y = y
    
    def rotate_point(self, x, y):
        """Rotate a world point around the player's screen position"""
        translated_x = x - self.x
        translated_y = y - self.y
        
        # Rotate
        cos_angle = math.cos(self.angle)
        sin_angle = math.sin(self.angle)
        rotated_x = translated_x * cos_angle - translated_y * sin_angle
        rotated_y = translated_x * sin_angle + translated_y * cos_angle
        
        # Place relative to player's screen position
        return rotated_x + c.Screen.ORIGIN_X, rotated_y + c.Screen.ORIGIN_Y
