import math
import time
import pygame

import core.constants as c
from core.camera import Camera
from core.utils import random_color
from game.entities.entities import Entity, draw_human
from llm.name_generator import NPCNameGenerator


class NPC(Entity):
    """The NPCs we can talk with"""
    def __init__(self, x, y):
        super().__init__(x, y, random_color(), c.Entities.NPC_SIZE,
                         c.Entities.NPC_HP, c.Entities.NPC_HP)
        self.name = None
        self.has_active_quest = False
        self.quest_item = None
    
    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if self.name is None:
            self.name = npc_name_generator.get_name()
    
    def get_display_name(self) -> str:
        if self.name:
            return self.name
        return ""

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        
        draw_human(screen, screen_x, screen_y, c.Entities.NPC_SIZE, self.color, self.orientation)

        # Health Bar
        bar_width = 60
        bar_height = 8
        x = screen_x - bar_width // 2
        y = screen_y + c.Entities.NPC_HP // 2 + 10
        self.draw_health_bar(screen, x, y, bar_width, bar_height, self.color)
        
        # Exclamation mark for active quests
        if self.has_active_quest:
            font = pygame.font.Font(None, 45)
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(screen_x, screen_y - c.Entities.NPC_SIZE // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)
        
        # Name label
        display_name = self.get_display_name()
        if display_name:
            name_font = pygame.font.SysFont("arial", 16)
            name_surface = name_font.render(display_name, True, c.Colors.WHITE)
            name_rect = name_surface.get_rect(center=(screen_x, screen_y + c.Entities.NPC_SIZE // 2 + 15))
            
            # Background box
            bg_rect = name_rect.inflate(10, 4)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg_surface, (0, 0, 0, 180), bg_surface.get_rect(), border_radius=6)
            screen.blit(bg_surface, bg_rect)
            
            # Draw name
            screen.blit(name_surface, name_rect)
