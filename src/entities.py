import colorsys
import math
import queue
import threading
import pygame
import random
import time
from typing import List

import constants as c
from llm_request_queue import generate_response_queued

def random_color():
    h = random.random()
    s = 0.6 + 0.4 * random.random()  # moderate to high saturation
    l = 0.5 + 0.2 * random.random()  # mid to bright
    r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
    return (r, g, b)

class NPCNameGenerator:
    """Background generator for NPC names"""
    
    def __init__(self):
        self.name_queue = queue.Queue(maxsize=1)  # Only keep 1 name ready
        self.is_generating = False
        self.lock = threading.Lock()
        
        # Start generating the first name immediately
        self._start_generation()
    
    def _start_generation(self):
        """Start a background thread to generate a name"""
        with self.lock:
            if self.is_generating or not self.name_queue.empty():
                return  # Already generating or have a name ready
            
            self.is_generating = True
        
        thread = threading.Thread(target=self._generate_name_background, daemon=True)
        thread.start()
    
    def _generate_name_background(self):
        system_prompt = "Tu es un générateur de PNJ pour un RPG. Réponds uniquement avec UN prénom et/ou UNE profession, sur une seule ligne, sans répétition, sans explication."
        prompt = "Génère un prénom et/ou une profession pour un PNJ de RPG."
        
        # Use the queued function to avoid blocking
        name = generate_response_queued(prompt, system_prompt)
            
        # Put result in queue (will block if queue is full, but we set maxsize=1)
        self.name_queue.put(name.strip())
    
        with self.lock:
            self.is_generating = False
    
    def get_name(self) -> str:
        """
        Get a generated name (waits if necessary), then start generating the next one.
        """
        # Wait until a name is ready
        name = self.name_queue.get()
        
        # Start generating the next name in background
        self._start_generation()
        
        return name


# Global instance
_npc_name_generator = None

def get_npc_name_generator() -> NPCNameGenerator:
    """Get or create the global NPC name generator"""
    global _npc_name_generator
    if _npc_name_generator is None:
        _npc_name_generator = NPCNameGenerator()
    return _npc_name_generator


class NPC:
    def __init__(self, x, y, npc_id):
        self.x = x
        self.y = y
        self.color = random_color()
        self.id = npc_id
        self.has_active_quest = False
        self.quest_content = None
        self.quest_item: Item = None
        self.quest_complete = False
        
        # NPCs start without a specific name
        self.name = None
        self.has_been_named = False
    
    def assign_name(self):
        if not self.has_been_named:
            self.name = get_npc_name_generator().get_name()
            self.has_been_named = True
    
    def get_display_name(self) -> str:
        if self.has_been_named and self.name:
            return self.name
        return ""
    
    def draw(self, screen: pygame.Surface, camera_x, camera_y):
        screen_x = self.x - camera_x - c.Size.NPC // 2
        screen_y = self.y - camera_y - c.Size.NPC // 2
        
        # Draw black border
        border_thickness = 2
        pygame.draw.rect(
            screen,
            c.Colors.BLACK,
            (screen_x - border_thickness, screen_y - border_thickness,
             c.Size.NPC + border_thickness * 2, c.Size.NPC + border_thickness * 2)
        )
        
        # Draw NPC
        pygame.draw.rect(screen, self.color, (screen_x, screen_y, c.Size.NPC, c.Size.NPC))
        
        # Draw exclamation mark if has quest
        if self.has_active_quest and not self.quest_complete:
            font = pygame.font.Font(None, 45)
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(screen_x + c.Size.NPC // 2, screen_y - 25 + bob_offset))
            screen.blit(text, text_rect)
        
        # Draw name label
        name_font = pygame.font.SysFont("arial", 16)
        display_name = self.get_display_name()
        name_surface = name_font.render(display_name, True, c.Colors.WHITE)
        name_rect = name_surface.get_rect(center=(screen_x + c.Size.NPC // 2, screen_y + c.Size.NPC + 15))
        
        if self.has_been_named:
            bg_rect = name_rect.inflate(10, 4)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg_surface, (0, 0, 0, 180), bg_surface.get_rect(), border_radius=6)
            screen.blit(bg_surface, bg_rect)
            screen.blit(name_surface, name_rect)

    
    def distance_to_player(self, player):
        return ((self.x - player.x)**2 + (self.y - player.y)**2)**0.5

class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.angle = 0

        self.inventory: List[Item] = []
        self.coins = 0
    
    def move(self, dx, dy, world_width, world_height, world_mouse_x, world_mouse_y):
        # Avoid moving out of bounds
        new_x = max(c.Size.PLAYER//2, min(self.x + dx, world_width - c.Size.PLAYER//2))
        new_y = max(c.Size.PLAYER//2, min(self.y + dy, world_height - c.Size.PLAYER//2))
        self.x = new_x
        self.y = new_y

        # Update facing direction
        self.angle = math.atan2(world_mouse_y - self.y, world_mouse_x - self.x)
    
    def draw(self, screen, camera_x, camera_y):
        screen_x = self.x - camera_x - c.Size.PLAYER // 2
        screen_y = self.y - camera_y - c.Size.PLAYER // 2
        border_thickness = 2  # thickness of the white border

        # Create player surface with per-pixel alpha
        player_surf = pygame.Surface(
            (c.Size.PLAYER + border_thickness * 2, c.Size.PLAYER + border_thickness * 2),
            pygame.SRCALPHA
        )

        # Draw white border
        pygame.draw.rect(
            player_surf,
            c.Colors.WHITE,
            (0, 0, c.Size.PLAYER + border_thickness * 2, c.Size.PLAYER + border_thickness * 2)
        )

        # Draw inner black square
        pygame.draw.rect(
            player_surf,
            c.Colors.BLACK,
            (border_thickness, border_thickness, c.Size.PLAYER, c.Size.PLAYER)
        )

        # Rotate the player surface around its center
        rotated_surf = pygame.transform.rotate(player_surf, -math.degrees(self.angle))
        rect = rotated_surf.get_rect(center=(screen_x + c.Size.PLAYER // 2, screen_y + c.Size.PLAYER // 2))
        screen.blit(rotated_surf, rect)

        # Draw direction arrow
        arrow_distance = 50
        arrow_size = 10
        arrow_alpha = 128

        center_x = screen_x + c.Size.PLAYER / 2
        center_y = screen_y + c.Size.PLAYER / 2
        arrow_x = center_x + math.cos(self.angle) * arrow_distance
        arrow_y = center_y + math.sin(self.angle) * arrow_distance

        left_x = arrow_x + math.cos(self.angle + math.pi * 0.75) * arrow_size
        left_y = arrow_y + math.sin(self.angle + math.pi * 0.75) * arrow_size
        right_x = arrow_x + math.cos(self.angle - math.pi * 0.75) * arrow_size
        right_y = arrow_y + math.sin(self.angle - math.pi * 0.75) * arrow_size

        arrow_surface = pygame.Surface((screen.get_width(), screen.get_height()), pygame.SRCALPHA)
        pygame.draw.polygon(
            arrow_surface,
            (255, 255, 255, arrow_alpha),
            [(arrow_x, arrow_y), (left_x, left_y), (right_x, right_y)]
        )
        screen.blit(arrow_surface, (0, 0))

class Item:
    def __init__(self, x, y, name):
        self.x = x
        self.y = y
        self.name = name
        self.color = random_color()
        self.shape = random.choice(["circle", "triangle", "pentagon", "star"])
        self.picked_up = False
    
    def draw(self, screen, camera_x, camera_y):        
        screen_x = self.x - camera_x - c.Size.ITEM // 2
        screen_y = self.y - camera_y - c.Size.ITEM // 2
        center = (screen_x + c.Size.ITEM // 2, screen_y + c.Size.ITEM // 2)
        size = c.Size.ITEM // 2
        
        if self.shape == "circle":
            pygame.draw.circle(screen, c.Colors.BLACK, center, size, 2)
            pygame.draw.circle(screen, self.color, center, size - 1)
        elif self.shape == "triangle":
            points = [
                (center[0], center[1] - size),
                (center[0] - size, center[1] + size),
                (center[0] + size, center[1] + size)
            ]
            pygame.draw.polygon(screen, c.Colors.BLACK, points, 2)
            pygame.draw.polygon(screen, self.color, points)
        elif self.shape == "pentagon":
            points = [
                (center[0], center[1] - size),
                (center[0] - size * 0.95, center[1] - size * 0.31),
                (center[0] - size * 0.59, center[1] + size * 0.81),
                (center[0] + size * 0.59, center[1] + size * 0.81),
                (center[0] + size * 0.95, center[1] - size * 0.31)
            ]
            pygame.draw.polygon(screen, c.Colors.BLACK, points, 2)
            pygame.draw.polygon(screen, self.color, points)
        elif self.shape == "star":
            points = []
            for i in range(10):
                angle = i * 36
                r = size if i % 2 == 0 else size / 2
                x = center[0] + r * math.sin(math.radians(angle))
                y = center[1] - r * math.cos(math.radians(angle))
                points.append((x, y))
            pygame.draw.polygon(screen, c.Colors.BLACK, points, 2)
            pygame.draw.polygon(screen, self.color, points)
    
    def distance_to_player(self, player):
        return math.hypot(self.x - player.x, self.y - player.y)
