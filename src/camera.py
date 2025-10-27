import math


class RotatingCamera:
    """Handles smooth world rotation based on player's facing direction"""
    def __init__(self):
        self.rotation_angle = 0  # Current rotation in radians
        self.target_angle = 0    # Target rotation based on player facing
        self.rotation_speed = 0.1  # Smoothing factor (0-1, higher = faster response)
    
    def update(self, player_angle):
        """Update rotation to match player's facing direction"""
        # We want to rotate the world opposite to player's facing direction
        # so the player appears to always face "up" on screen
        self.target_angle = -player_angle
        
        # Smooth interpolation towards target
        angle_diff = self.target_angle - self.rotation_angle
        
        # Handle angle wrapping (shortest path)
        if angle_diff > math.pi:
            angle_diff -= 2 * math.pi
        elif angle_diff < -math.pi:
            angle_diff += 2 * math.pi
        
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
