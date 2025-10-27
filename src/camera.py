import math


class RotatingCamera:
    """Handles world rotation"""
    def __init__(self):
        self.angle = 0

    def update(self, delta_angle):
        """Simplest update"""
        self.angle += delta_angle
    
    def rotate_point(self, x, y, origin_x, origin_y):
        """Rotate a point around an origin"""
        # Translate to origin
        translated_x = x - origin_x
        translated_y = y - origin_y
        
        # Rotate
        cos_angle = math.cos(self.angle)
        sin_angle = math.sin(self.angle)
        
        rotated_x = translated_x * cos_angle - translated_y * sin_angle
        rotated_y = translated_x * sin_angle + translated_y * cos_angle
        
        # Translate back
        return rotated_x + origin_x, rotated_y + origin_y
