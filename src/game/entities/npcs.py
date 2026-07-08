from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING, Dict, List, Optional

import pygame

import core.constants as c
from core.utils import random_color
from game.entities.entities import Entity
from game.quest import Quest

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.items import Item
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator


class NPC(Entity):
    def __init__(self, x, y):
        super().__init__(x, y, random_color(), c.Entities.NPC_SIZE, c.Entities.NPC_HP, c.Entities.NPC_HP)
        self.name = None
        self.quest: Optional[Quest] = None
        self.is_merchant = False
        self.shop_items: List[Item] = []
        self.shop_prices: Dict[str, int] = {}
        self.shop_ready = False
        self.home = (x, y)
        self.wander_target = None
        self.idle_timer = random.uniform(c.Entities.NPC_IDLE_MIN_MS, c.Entities.NPC_IDLE_MAX_MS)

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
            "is_merchant": self.is_merchant,
            "shop_ready": self.shop_ready,
            "home": list(self.home),
            "shop_items": [{**item.to_dict(), "shop_price": self.shop_prices[item.id]} for item in self.shop_items],
        }

    @classmethod
    def from_dict(cls, data: dict, items_by_id: Dict[str, Item]) -> NPC:
        from game.entities.items import Item

        npc = cls(data["x"], data["y"])
        npc.name = data["name"]
        npc.hp = data["hp"]
        npc.color = tuple(data["color"])
        npc.orientation = data["orientation"]
        if data["quest"]:
            npc.quest = Quest.from_dict(data["quest"], items_by_id)
        npc.is_merchant = data["is_merchant"]
        npc.shop_ready = data["shop_ready"]
        npc.home = tuple(data["home"])
        for entry in data["shop_items"]:
            price = entry["shop_price"]
            item_data = {k: v for k, v in entry.items() if k != "shop_price"}
            item = Item.from_dict(item_data)
            npc.shop_items.append(item)
            npc.shop_prices[item.id] = price
        return npc

    def set_shop(self, shop_data: list):
        from game.entities.items import Item, item_type_from_name, rarity_tier, roll_bonus, roll_rarity

        self.shop_items.clear()
        self.shop_prices.clear()
        for entry in shop_data:
            item_type = entry.get("item_type") or item_type_from_name(entry["name"])
            rarity = entry.get("rarity") or roll_rarity()
            item = Item(0, 0, entry["name"], item_type, roll_bonus(item_type, rarity), rarity)
            self.shop_items.append(item)
            self.shop_prices[item.id] = round(entry["price"] * rarity_tier(rarity).price_mult)
        self.shop_ready = True

    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if self.name is None:
            self.name = npc_name_generator.get_name()

    def update(self, player: Player, dt, blocked=None):
        if self.distance_to_point(player.get_pos()) < c.Entities.NPC_WANDER_PAUSE_DISTANCE:
            # atan2(dy, dx) measures from the x-axis; sprites face up, so rotate a quarter turn
            self.orientation = math.atan2(player.y - self.y, player.x - self.x) + math.pi / 2
            return

        if self.wander_target is None:
            self.idle_timer -= dt
            if self.idle_timer <= 0:
                angle = random.uniform(0, 2 * math.pi)
                radius = random.uniform(0, c.Entities.NPC_WANDER_RADIUS)
                self.wander_target = (self.home[0] + math.cos(angle) * radius, self.home[1] + math.sin(angle) * radius)
            return

        dx = self.wander_target[0] - self.x
        dy = self.wander_target[1] - self.y
        step = c.Entities.NPC_WANDER_SPEED * dt * c.TARGET_FPS / 1000.0
        if math.hypot(dx, dy) <= step:
            self.x, self.y = self.wander_target
            self.wander_target = None
            self.idle_timer = random.uniform(c.Entities.NPC_IDLE_MIN_MS, c.Entities.NPC_IDLE_MAX_MS)
        else:
            angle = math.atan2(dy, dx)
            step_x = math.cos(angle) * step
            step_y = math.sin(angle) * step
            radius = c.Entities.NPC_SIZE / 2
            # Move one axis at a time so a wall on one axis lets the NPC slide along it.
            if blocked is not None and blocked(self.x + step_x, self.y, radius):
                step_x = 0
            self.x += step_x
            if blocked is not None and blocked(self.x, self.y + step_y, radius):
                step_y = 0
            self.y += step_y
            # A blocked NPC would otherwise loiter against a wall forever; drop the target so it repicks.
            if step_x == 0 and step_y == 0:
                self.wander_target = None
                self.idle_timer = random.uniform(c.Entities.NPC_IDLE_MIN_MS, c.Entities.NPC_IDLE_MAX_MS)
            self.orientation = angle + math.pi / 2

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

        bob_offset = math.sin(time.time() * 4) * 4
        if self.has_active_quest:
            font = pygame.font.Font(None, 45)
            text = font.render("!", True, c.Colors.YELLOW)
            text_rect = text.get_rect(center=(screen_x, screen_y - c.Entities.NPC_SIZE // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)
        elif self.is_merchant:
            font = pygame.font.Font(None, 40)
            color = (100, 255, 100) if self.shop_ready else (120, 120, 80)
            text = font.render("$", True, color)
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
