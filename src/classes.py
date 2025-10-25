import math
import pygame
import random

import constants as c
from functions import random_color


class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.inventory = []
        self.coins = 0
    
    def move(self, dx, dy, world_width, world_height):
        new_x = max(c.Size.PLAYER//2, min(self.x + dx, world_width - c.Size.PLAYER//2))
        new_y = max(c.Size.PLAYER//2, min(self.y + dy, world_height - c.Size.PLAYER//2))
        self.x = new_x
        self.y = new_y
    
    def draw(self, screen, camera_x, camera_y):
        screen_x = self.x - camera_x - c.Size.PLAYER // 2
        screen_y = self.y - camera_y - c.Size.PLAYER // 2
        border_thickness = 2  # thickness of the white border

        # Draw white border
        pygame.draw.rect(
            screen,
            c.Colors.WHITE,
            (screen_x - border_thickness, screen_y - border_thickness,
            c.Size.PLAYER + border_thickness * 2, c.Size.PLAYER + border_thickness * 2)
        )

        # Draw main black rectangle
        pygame.draw.rect(screen, c.Colors.BLACK, (screen_x, screen_y, c.Size.PLAYER, c.Size.PLAYER))
    

class NPC:
    def __init__(self, x, y, npc_id):
        self.x = x
        self.y = y
        self.color = random_color()
        self.id = npc_id
        self.has_active_quest = False
        self.quest_content = None
        self.quest_item_name = None
        self.quest_complete = False
        
    def draw(self, screen, camera_x, camera_y):
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
            font = pygame.font.Font(None, 30)
            text = font.render("!", True, c.Colors.YELLOW)
            screen.blit(text, (screen_x + c.Size.NPC // 2 - 5, screen_y - 20))
    
    def distance_to_player(self, player):
        return ((self.x - player.x)**2 + (self.y - player.y)**2)**0.5


class Item:
    def __init__(self, x, y, name):
        self.x = x
        self.y = y
        self.name = name
        self.color = random_color()
        self.shape = random.choice(["circle", "triangle", "pentagon", "star"])
        self.picked_up = False
    
    def draw(self, screen, camera_x, camera_y):
        if not self.picked_up:
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
                    angle = i * 36  # 360 / 10
                    r = size if i % 2 == 0 else size / 2
                    x = center[0] + r * math.sin(math.radians(angle))
                    y = center[1] - r * math.cos(math.radians(angle))
                    points.append((x, y))
                pygame.draw.polygon(screen, c.Colors.BLACK, points, 2)
                pygame.draw.polygon(screen, self.color, points)
    
    def distance_to_player(self, player):
        return math.hypot(self.x - player.x, self.y - player.y)