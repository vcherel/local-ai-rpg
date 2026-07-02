from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.utils import random_color

if TYPE_CHECKING:
    from core.camera import Camera

WEAPON_KEYWORDS = {
    "sword",
    "axe",
    "blade",
    "dagger",
    "bow",
    "spear",
    "knife",
    "club",
    "mace",
    "staff",
    "lance",
    "hammer",
}
ARMOR_KEYWORDS = {
    "shield",
    "armor",
    "vest",
    "helmet",
    "mail",
    "plate",
    "cloak",
    "buckler",
    "breastplate",
    "gauntlets",
    "greaves",
}

WEAPON_COLOR = (220, 140, 40)
ARMOR_COLOR = (100, 180, 220)
LOOTBOX_COLOR = (150, 100, 50)


def item_type_from_name(name: str) -> str:
    lower = name.lower()
    if any(kw in lower for kw in WEAPON_KEYWORDS):
        return "weapon"
    if any(kw in lower for kw in ARMOR_KEYWORDS):
        return "armor"
    return "misc"


class Item:
    def __init__(self, x, y, name, item_type: str = "misc", bonus: int = 0):
        self.id = uuid.uuid4().hex
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.name = name
        self.item_type = item_type
        self.bonus = bonus
        if item_type == "weapon":
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in WEAPON_COLOR)
            self.shape = "sword"
        elif item_type == "armor":
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in ARMOR_COLOR)
            self.shape = "shield"
        elif item_type == "lootbox":
            self.color = LOOTBOX_COLOR
            self.shape = "chest"
        else:
            self.color = random_color()
            self.shape = random.choice(["circle", "triangle", "pentagon", "star"])
        self.picked_up = False

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "angle": self.angle,
            "name": self.name,
            "item_type": self.item_type,
            "bonus": self.bonus,
            "color": list(self.color),
            "shape": self.shape,
            "picked_up": self.picked_up,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Item:
        item = cls(data["x"], data["y"], data["name"], data["item_type"], data["bonus"])
        item.id = data["id"]
        item.angle = data["angle"]
        item.color = tuple(data["color"])
        item.shape = data["shape"]
        item.picked_up = data["picked_up"]
        return item

    def draw(self, surface: pygame.Surface, camera: Camera = None, x=None, y=None):
        draw_x = x if x is not None else self.x
        draw_y = y if y is not None else self.y

        if camera:
            screen_x, screen_y = camera.world_to_screen(draw_x, draw_y)
            visual_angle = self.angle
        else:
            screen_x, screen_y = draw_x, draw_y
            visual_angle = 0

        center = (screen_x, screen_y)
        size = c.Entities.ITEM_SIZE // 2
        border_width = 2

        padding = size + border_width + 4
        surface_size = c.Entities.ITEM_SIZE + padding * 2
        item_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        item_center = (surface_size // 2, surface_size // 2)

        draw_shape_with_border(item_surface, self.shape, item_center, size, self.color, border_width)

        rotated_surface = pygame.transform.rotate(item_surface, math.degrees(-visual_angle))
        rect = rotated_surface.get_rect(center=center)

        surface.blit(rotated_surface, rect.topleft)


def draw_shape_with_border(surface, shape, center, size, color, border_width):
    cx, cy = center
    if shape == "circle":
        pygame.draw.circle(surface, c.Colors.BLACK, center, size + border_width)
        pygame.draw.circle(surface, color, center, size)
    elif shape == "sword":
        points = [
            (cx, cy - size),
            (cx + size * 0.4, cy - size * 0.15),
            (cx + size * 0.15, cy + size * 0.35),
            (cx, cy + size * 0.55),
            (cx - size * 0.15, cy + size * 0.35),
            (cx - size * 0.4, cy - size * 0.15),
        ]
        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)
        pygame.draw.polygon(surface, color, points)
    elif shape == "shield":
        points = [
            (cx - size * 0.65, cy - size * 0.45),
            (cx + size * 0.65, cy - size * 0.45),
            (cx + size * 0.65, cy + size * 0.15),
            (cx, cy + size * 0.7),
            (cx - size * 0.65, cy + size * 0.15),
        ]
        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)
        pygame.draw.polygon(surface, color, points)
    elif shape == "chest":
        half_w, half_h = size * 0.75, size * 0.55
        rect = pygame.Rect(0, 0, half_w * 2, half_h * 2)
        rect.center = center
        pygame.draw.rect(surface, c.Colors.BLACK, rect.inflate(border_width * 2, border_width * 2))
        pygame.draw.rect(surface, color, rect)
        lid_y = rect.top + rect.height * 0.4
        pygame.draw.line(surface, c.Colors.BLACK, (rect.left, lid_y), (rect.right, lid_y), border_width)
        pygame.draw.circle(surface, c.Colors.BLACK, (cx, int(lid_y)), max(2, size // 8))
    else:
        if shape == "triangle":
            points = get_polygon_points(center, size, 3)
        elif shape == "pentagon":
            points = get_polygon_points(center, size, 5)
        elif shape == "star":
            points = get_polygon_points(center, size, 10, inner_radius_factor=0.5)
        else:
            raise ValueError(f"Unknown shape: {shape}")

        pygame.draw.polygon(surface, c.Colors.BLACK, points, border_width)
        pygame.draw.polygon(surface, color, points)


def get_polygon_points(center, size, num_points, inner_radius_factor=None):
    points = []
    for i in range(num_points):
        angle = i * (360 / num_points)
        if inner_radius_factor and i % 2 == 1:
            r = size * inner_radius_factor
        else:
            r = size
        x = center[0] + r * math.sin(math.radians(angle))
        y = center[1] - r * math.cos(math.radians(angle))
        points.append((x, y))
    return points
