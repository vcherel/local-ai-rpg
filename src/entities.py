import colorsys
import math
import queue
import threading
import time
import pygame
import random
from typing import List

import constants as c
from camera import Camera
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
        self.angle = random.uniform(0, 2 * math.pi)
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

    def draw(self, screen: pygame.Surface, camera: Camera):
        """Draw NPC with correct rotation relative to camera"""
        # Rotate NPC position by camera
        rotated_x, rotated_y = camera.rotate_point(self.x, self.y)
        
        npc_size = c.Size.NPC
        border_thickness = 2
        
        # NPC surface
        npc_surface = pygame.Surface(
            (npc_size + border_thickness*2, npc_size + border_thickness*2),
            pygame.SRCALPHA
        )
        pygame.draw.rect(
            npc_surface,
            c.Colors.BLACK,
            (0, 0, npc_size + border_thickness*2, npc_size + border_thickness*2)
        )
        pygame.draw.rect(
            npc_surface,
            self.color,
            (border_thickness, border_thickness, npc_size, npc_size)
        )
        
        # Add camera angle to NPC angle to maintain world-space orientation
        visual_angle = self.angle + camera.angle
        rotated_surface = pygame.transform.rotate(npc_surface, math.degrees(-visual_angle))
        rect = rotated_surface.get_rect(center=(rotated_x, rotated_y))
        screen.blit(rotated_surface, rect.topleft)
        
        # Exclamation mark for active quests
        if self.has_active_quest and not self.quest_complete:
            font = pygame.font.Font(None, 45)
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(rotated_x, rotated_y - npc_size // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)
        
        # Name label
        display_name = self.get_display_name()
        if display_name:
            name_font = pygame.font.SysFont("arial", 16)
            name_surface = name_font.render(display_name, True, c.Colors.WHITE)
            name_rect = name_surface.get_rect(center=(rotated_x, rotated_y + npc_size // 2 + 15))
            
            # Background box
            bg_rect = name_rect.inflate(10, 4)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg_surface, (0, 0, 0, 180), bg_surface.get_rect(), border_radius=6)
            screen.blit(bg_surface, bg_rect)
            
            # Draw name
            screen.blit(name_surface, name_rect)

    def distance_to_player(self, player):
        return ((self.x - player.x)**2 + (self.y - player.y)**2)**0.5

class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.inventory: List[Item] = []
        self.coins = 0
    
    def move(self, distance, angle):
        """Move player in the direction they are facing"""
        dx = -math.sin(angle) * distance
        dy = -math.cos(angle) * distance

        self.x += dx
        self.y += dy

    def draw(self, screen: pygame.Surface):
        """Draw player at screen center, always facing up"""        
        border_thickness = 2
        
        # Create player surface
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
        
        # Player is always drawn facing up
        rect = player_surf.get_rect(center=(c.Screen.ORIGIN_X, c.Screen.ORIGIN_Y))
        screen.blit(player_surf, rect)
        
        # Draw direction arrow pointing up
        arrow_distance = 50
        arrow_size = 10
        arrow_alpha = 128
        
        arrow_x = c.Screen.ORIGIN_X
        arrow_y = c.Screen.ORIGIN_Y - arrow_distance
        
        left_x = arrow_x - arrow_size
        left_y = arrow_y + arrow_size
        
        right_x = arrow_x + arrow_size
        right_y = arrow_y + arrow_size
        
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
        self.angle = random.uniform(0, 2 * math.pi)
        self.name = name
        self.color = random_color()
        self.shape = random.choice(["circle", "triangle", "pentagon", "star"])
        self.picked_up = False
    
    def draw(self, screen: pygame.Surface, camera: Camera):
        """Draw item with correct rotation relative to camera"""
        # Rotate item position by camera
        rotated_x, rotated_y = camera.rotate_point(self.x, self.y)
        center = (rotated_x, rotated_y)
        size = c.Size.ITEM // 2
        border = 2  # outline thickness

        # Compute visual angle (world-space + camera rotation)
        visual_angle = self.angle + camera.angle

        # Add generous padding to prevent clipping during rotation
        padding = size + border + 4
        surface_size = c.Size.ITEM + padding * 2
        item_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        item_center = (surface_size // 2, surface_size // 2)

        # Draw the shape centered on the padded surface
        if self.shape == "circle":
            pygame.draw.circle(item_surface, c.Colors.BLACK, item_center, size + border)
            pygame.draw.circle(item_surface, self.color, item_center, size)
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
        screen.blit(rotated_surface, rect.topleft)

    def distance_to_player(self, player):
        return math.hypot(self.x - player.x, self.y - player.y)
