from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Dict, Optional

import pygame

import core.constants as c
from core.utils import random_color
from game.entities.entities import Entity
from game.quest import Quest

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.items import Item
    from llm.name_generator import NPCNameGenerator


class NPC(Entity):
    def __init__(self, x, y):
        super().__init__(x, y, random_color(), c.Entities.NPC_SIZE, c.Entities.NPC_HP, c.Entities.NPC_HP)
        self.name = None
        self.quest: Optional[Quest] = None

    @property
    def has_active_quest(self):
        return self.quest is not None and not self.quest.is_completed

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "name": self.name,
            "hp": self.hp,
            "color": list(self.color),
            "orientation": self.orientation,
            "quest": self.quest.to_dict() if self.quest else None,
        }

    @classmethod
    def from_dict(cls, data: dict, items_by_id: Dict[str, Item]) -> NPC:
        npc = cls(data["x"], data["y"])
        npc.name = data["name"]
        npc.hp = data["hp"]
        npc.color = tuple(data["color"])
        npc.orientation = data["orientation"]
        if data["quest"]:
            npc.quest = Quest.from_dict(data["quest"], items_by_id)
        return npc

    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if self.name is None:
            self.name = npc_name_generator.get_name()

    def draw(self, screen: pygame.Surface, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        super().draw(
            screen,
            screen_x,
            screen_y,
            c.Entities.NPC_SIZE,
            self.color,
            self.orientation,
            bar_width=60,
            bar_height=8,
            health_bar_offset=10,
        )

        if self.has_active_quest:
            font = pygame.font.Font(None, 45)
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(screen_x, screen_y - c.Entities.NPC_SIZE // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)

        display_name = self.name or ""
        if display_name:
            name_surface = c.Fonts.small.render(display_name, True, c.Colors.WHITE)
            name_rect = name_surface.get_rect(center=(screen_x, screen_y + c.Entities.NPC_SIZE // 2 + 30))
            bg_rect = name_rect.inflate(10, 4)
            bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg_surface, c.Colors.TRANSPARENT, bg_surface.get_rect(), border_radius=6)
            screen.blit(bg_surface, bg_rect)
            screen.blit(name_surface, name_rect)
