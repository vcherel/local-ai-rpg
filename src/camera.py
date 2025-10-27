import math


class RotatingCamera:
    """Handles mouse-based world rotation"""
    
    def __init__(self):
        self.rotation_angle = 0  # Current rotation in radians
        self.target_angle = 0    # Target rotation based on mouse
        self.rotation_speed = 0.05  # Smoothing factor (0-1, lower = smoother)
        
    def update(self, mouse_x, mouse_y, screen_width, screen_height):
        """Update rotation based on mouse position"""
        # Calculate normalized mouse position (-1 to 1)
        center_x = screen_width / 2
        center_y = screen_height / 2
        
        # Calculate offset from center
        offset_x = (mouse_x - center_x) / center_x
        offset_y = (mouse_y - center_y) / center_y
        
        # Calculate target rotation angle
        self.target_angle = offset_x
        
        # Smooth interpolation towards target
        angle_diff = self.target_angle - self.rotation_angle
        self.rotation_angle += angle_diff * self.rotation_speed
        
    def rotate_point(self, x, y, origin_x, origin_y):
        """Rotate a point around an origin"""
        # Translate to origin
        translated_x = x - origin_x
        translated_y = y - origin_y
        
        # Rotate
        cos_angle = math.cos(self.rotation_angle)
        sin_angle = math.sin(self.rotation_angle)
        
        rotated_x = translated_x * cos_angle - translated_y * sin_angle
        rotated_y = translated_x * sin_angle + translated_y * cos_angle
        
        # Translate back
        return rotated_x + origin_x, rotated_y + origin_y