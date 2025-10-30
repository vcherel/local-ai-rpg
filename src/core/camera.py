import core.constants as c

class Camera:
    """Handles world-to-screen translation only"""
    def __init__(self):
        self.x = 0  # Player's world x
        self.y = 0  # Player's world y
    
    def update_position(self, x, y):
        """Update camera position"""
        self.x = x
        self.y = y
    
    def world_to_screen(self, x, y):
        """Convert world coordinates to screen coordinates"""
        screen_x = x - self.x + c.Screen.ORIGIN_X
        screen_y = y - self.y + c.Screen.ORIGIN_Y
        return screen_x, screen_y
