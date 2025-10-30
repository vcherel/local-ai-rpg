import math
import random
import pygame

from core.camera import Camera
import core.constants as c
from game.entities.entities import draw_human


class Monster:
    """The monsters we can kill"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.hp = c.World.MONSTER_HP

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        draw_human(screen, screen_x, screen_y, c.World.MONSTER_SIZE, c.Colors.RED, self.angle)
    
    def receive_damage(self, damage):
        """Returns True if the monster died"""
        self.hp -= damage
        if self.hp <= 1:
            return True
        return False

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])
