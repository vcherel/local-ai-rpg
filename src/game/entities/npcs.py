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
        # True for an NPC spawned to hold a recover_stolen quest's item; shows a marker
        # so the player can spot them without already knowing where to look.
        self.is_thief = False
        self.shop_items: List[Item] = []
        self.shop_prices: Dict[str, int] = {}
        self.shop_ready = False
        self.home = (x, y)
        self.wander_target = None
        self.idle_timer = random.uniform(c.Entities.NPC_IDLE_MIN_MS, c.Entities.NPC_IDLE_MAX_MS)
        self.affinity = c.Affinity.START

    @property
    def has_active_quest(self):
        return self.quest is not None and not self.quest.is_completed

    def affinity_descriptor(self) -> str:
        """A prompt hint reflecting how the NPC feels about the player, or "" when neutral."""
        if self.affinity < 20:
            return "You dislike the player and are cold, curt, or suspicious of them. "
        if self.affinity < 40:
            return "You are wary of the player and not particularly warm towards them. "
        if self.affinity < 60:
            return ""
        if self.affinity < 80:
            return "You like the player and are warm and friendly towards them. "
        return "You consider the player a close friend and are especially warm, generous, and open with them. "

    def affinity_tier_color(self) -> tuple:
        if self.affinity < 20:
            return (200, 60, 60)
        if self.affinity < 40:
            return (200, 140, 60)
        if self.affinity < 60:
            return (180, 180, 180)
        if self.affinity < 80:
            return (120, 200, 120)
        return (255, 200, 60)

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
            "is_thief": self.is_thief,
            "affinity": self.affinity,
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
        npc.is_thief = data.get("is_thief", False)
        npc.affinity = data.get("affinity", c.Affinity.START)
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
        from game.entities.items import AMMO_BUNDLE

        for entry in shop_data:
            item_type = entry.get("item_type") or item_type_from_name(entry["name"])
            rarity = entry.get("rarity") or roll_rarity()
            quantity = entry.get("quantity", AMMO_BUNDLE if item_type == "ammo" else 1)
            item = Item(0, 0, entry["name"], item_type, roll_bonus(item_type, rarity), rarity, quantity=quantity)
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
            # Face the way it actually moved, not the way it wanted to: a slider looks along
            # the wall, and one pinned against a building stops staring straight into it.
            if step_x or step_y:
                self.orientation = math.atan2(step_y, step_x) + math.pi / 2
            # If a wall swallowed most of the intended step, stop grinding against it and repick.
            if math.hypot(step_x, step_y) < step * 0.25:
                self.wander_target = None
                self.idle_timer = random.uniform(c.Entities.NPC_IDLE_MIN_MS, c.Entities.NPC_IDLE_MAX_MS)

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
        elif self.is_thief:
            font = pygame.font.Font(None, 45)
            text = font.render("?", True, (190, 70, 220))
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

            # Only shown once the player's actions have actually moved the relationship,
            # so untouched NPCs don't clutter the world with a neutral marker.
            if self.affinity != c.Affinity.START:
                pygame.draw.circle(screen, self.affinity_tier_color(), (bg_rect.left - 8, bg_rect.centery), 5)
