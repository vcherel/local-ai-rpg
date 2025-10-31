import math
import pygame

import core.constants as c

class LoadingIndicator:
    """Visual loading indicator for LLM background treatments"""
    
    def __init__(self, screen, x, y):
        self.angle = 0
        self.speed = 5  # Rotation speed
        self.screen: pygame.Surface = screen
        self.x = x
        self.y = y
    
    def update(self):
        """Update the rotation angle"""
        self.angle = (self.angle + self.speed) % 360

    def draw_task_indicator(self, task_count):
        # Semi-transparent background
        bg_surface = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.circle(bg_surface, (0, 0, 0, 180), (20, 20), 18)
        pygame.draw.circle(bg_surface, (255, 200, 100, 220), (20, 20), 18, 2)

        # Glow ring for visibility
        pygame.draw.circle(bg_surface, (255, 240, 180, 100), (20, 20), 20, 4)

        self.screen.blit(bg_surface, (self.x - 20, self.y - 20))

        # Spinner
        self.draw_spinner(12, (255, 240, 200))

        # Task count number
        text = c.Fonts.button.render(str(task_count), True, (255, 255, 200))
        text_rect = text.get_rect(center=(self.x, self.y))
        self.screen.blit(text, text_rect)

    def draw_spinner(self, radius, color):
        num_segments = 12
        segment_angle = 360 / num_segments

        for i in range(num_segments):
            # Create trailing effect
            angle_offset = segment_angle * i
            current_angle = (self.angle + angle_offset) % 360
            opacity = int(255 * ((i + 1) / num_segments))  # fade tail

            # Compute arc positions
            start_angle = math.radians(current_angle)
            end_angle = math.radians(current_angle + segment_angle * 0.6)

            # Blend color with alpha
            arc_color = (*color[:3], opacity)

            # Build arc points
            points = []
            steps = 6
            for step in range(steps + 1):
                angle = start_angle + (end_angle - start_angle) * (step / steps)
                px = self.x + math.cos(angle) * radius
                py = self.y + math.sin(angle) * radius
                points.append((px, py))

            # Use an intermediate surface to support alpha
            arc_surface = pygame.Surface((radius * 2 + 6, radius * 2 + 6), pygame.SRCALPHA)
            offset_points = [(px - self.x + radius + 3, py - self.y + radius + 3) for px, py in points]
            pygame.draw.lines(arc_surface, arc_color, False, offset_points, 3)
            self.screen.blit(arc_surface, (self.x - radius - 3, self.y - radius - 3))
