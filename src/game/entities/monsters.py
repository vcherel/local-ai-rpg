import math
import pygame

from core.camera import Camera
import core.constants as c
from game.entities.entities import Entity, draw_human


class Monster(Entity):
    """The monsters we can kill"""

    def __init__(self, x, y):
        super().__init__(x, y)
        self.hp = c.Entities.MONSTER_HP

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        draw_human(screen, screen_x, screen_y, c.Entities.MONSTER_SIZE, c.Colors.RED, self.angle)

    def attack_player(self, pos):
        # Calculate angle towards player
        dx = pos[0] - self.x
        dy = pos[1] - self.y
        self.angle = math.atan2(dy, dx)
        
        # Move in that direction
        self.x += math.cos(self.angle) * c.Entities.MONSTER_SPEED
        self.y += math.sin(self.angle) * c.Entities.MONSTER_SPEED

        self.angle += math.pi / 2
