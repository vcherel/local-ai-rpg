import pygame

from core.camera import Camera
import core.constants as c
from game.entities.entities import Entity, draw_human


class Monster(Entity):
    """The monsters we can kill"""

    def __init__(self, x, y):
        super().__init__(x, y)
        self.hp = c.World.MONSTER_HP

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        draw_human(screen, screen_x, screen_y, c.World.MONSTER_SIZE, c.Colors.RED, self.angle)
