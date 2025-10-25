import threading
from queue import Queue
from typing import Callable, Optional
import math
import pygame


class BackgroundTaskManager:
    """Manages background tasks to avoid race conditions"""
    
    def __init__(self):
        self.active_tasks = []
        self.task_queue = Queue()
        self.lock = threading.Lock()
    
    def add_task(self, func: Callable, callback: Optional[Callable] = None):
        """Add a task to run in background. Callback runs on main thread."""
        task = {
            'thread': None,
            'func': func,
            'callback': callback,
            'completed': False,
            'result': None
        }
        
        def wrapper():
            try:
                result = func()
                with self.lock:
                    task['result'] = result
                    task['completed'] = True
                    if callback:
                        self.task_queue.put(lambda: callback(result))
            except Exception as e:
                print(f"Background task error: {e}")
                with self.lock:
                    task['completed'] = True
        
        task['thread'] = threading.Thread(target=wrapper, daemon=True)
        
        with self.lock:
            self.active_tasks.append(task)
        
        task['thread'].start()
    
    def process_callbacks(self):
        """Process completed task callbacks on main thread"""
        while not self.task_queue.empty():
            callback = self.task_queue.get()
            callback()
        
        # Clean up completed tasks
        with self.lock:
            self.active_tasks = [t for t in self.active_tasks if not t['completed']]


class LoadingIndicator:
    """Visual loading indicator for various game states"""
    
    def __init__(self):
        self.angle = 0
        self.speed = 5  # Rotation speed
    
    def update(self):
        """Update the rotation angle"""
        self.angle = (self.angle + self.speed) % 360
    
    def draw_spinner(self, screen, x, y, radius=12, color=(255, 255, 255)):
        """Draw a rotating spinner at the specified position"""
        # Draw arc segments to create spinner effect
        num_segments = 8
        for i in range(num_segments):
            angle_offset = (360 / num_segments) * i
            current_angle = (self.angle + angle_offset) % 360
            
            # Calculate opacity based on position (trailing effect)
            opacity = int(255 * (i / num_segments))
            
            # Calculate arc position
            start_angle = math.radians(current_angle)
            end_angle = math.radians(current_angle + 45)
            
            # Draw arc segment
            arc_color = (*color[:3], opacity) if len(color) == 4 else color
            
            # Create points for the arc
            points = []
            steps = 5
            for step in range(steps + 1):
                angle = start_angle + (end_angle - start_angle) * (step / steps)
                px = x + math.cos(angle) * radius
                py = y + math.sin(angle) * radius
                points.append((px, py))
            
            # Draw the arc as a thick line
            if len(points) > 1:
                pygame.draw.lines(screen, arc_color, False, points, 3)
    
    def draw_llm_indicator(self, screen, x, y):
        """Draw LLM loading indicator (top right position)"""
        # Background circle
        pygame.draw.circle(screen, (0, 0, 0, 180), (x, y), 18)
        pygame.draw.circle(screen, (100, 100, 255), (x, y), 18, 2)
        
        # Spinner
        self.draw_spinner(screen, x, y, 12, (100, 150, 255))
        
        # Text
        font = pygame.font.SysFont("arial", 14)
        text = font.render("LLM", True, (200, 200, 255))
        text_rect = text.get_rect(center=(x, y))
        screen.blit(text, text_rect)
    
    def draw_task_indicator(self, screen, x, y, task_count):
        """Draw background task indicator"""
        # Background circle
        pygame.draw.circle(screen, (0, 0, 0, 180), (x, y), 18)
        pygame.draw.circle(screen, (255, 200, 100), (x, y), 18, 2)
        
        # Spinner
        self.draw_spinner(screen, x, y, 12, (255, 220, 150))
        
        # Task count
        font = pygame.font.SysFont("arial", 16, bold=True)
        text = font.render(str(task_count), True, (255, 230, 180))
        text_rect = text.get_rect(center=(x, y))
        screen.blit(text, text_rect)
