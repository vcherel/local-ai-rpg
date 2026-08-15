from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING, Dict, List, Optional

import pygame

import core.constants as c
from core.utils import random_color
from game.entities.entities import Entity
from game.entities.items import AMMO_BUNDLE, Item, item_type_from_name, rarity_tier, roll_bonus, roll_rarity
from game.entities.wander import Wander
from game.quest import Quest

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator

# How the NPC feels about the player, worst first: the prompt hint fed to their dialogue and
# the dot drawn by their name. One ladder, so the two can't drift apart.
AFFINITY_TIERS = (
    (20, "You dislike the player and are cold, curt, or suspicious of them. ", (200, 60, 60)),
    (40, "You are wary of the player and not particularly warm towards them. ", (200, 140, 60)),
    (60, "", (180, 180, 180)),
    (80, "You like the player and are warm and friendly towards them. ", (120, 200, 120)),
    (
        None,
        "You consider the player a close friend and are especially warm, generous, and open with them. ",
        (255, 200, 60),
    ),
)


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
        self.wander = Wander(
            c.Entities.NPC_WANDER_SPEED,
            c.Entities.NPC_WANDER_RADIUS,
            c.Entities.NPC_IDLE_MIN_MS,
            c.Entities.NPC_IDLE_MAX_MS,
        )
        self.affinity = c.Affinity.START
        # Turned on the player, along with the rest of their village (World.provoke_village).
        # A hostile villager stops wandering, stops trading and comes at the player with
        # whatever is to hand. Anger is a countdown (wall clock, so quitting can't wait it
        # out for free) rather than a state: a scuffle is lived down. A killing is not, and
        # sets `grudge` instead, which no clock ever clears (World.hold_grudge).
        self.hostile_until = 0.0
        self.grudge = False
        self.attack_ready_ms = 0
        # Whether this one takes up arms when a monster walks into their settlement, rolled
        # off their home so the same house always sends the same person out. Cached because
        # it is asked every frame.
        self._militia: Optional[bool] = None

    @property
    def hostile(self) -> bool:
        return self.grudge or time.time() < self.hostile_until

    @property
    def anger_remaining(self) -> float:
        """Seconds until this one calms down; 0 when calm, inf on a grudge."""
        if self.grudge:
            return math.inf
        return max(0.0, self.hostile_until - time.time())

    def anger(self, seconds: float, permanent: bool = False):
        """Turn on the player for a while. A fresh offence adds to whatever is left rather
        than replacing it, up to a ceiling: keep swinging and they keep hating you, but the
        clock never runs so long that the settlement is written off for the save."""
        if permanent:
            self.grudge = True
        self.affinity = c.Affinity.MIN
        self.hostile_until = time.time() + min(self.anger_remaining + seconds, c.Villages.ANGER_CAP_S)

    def _cool_off(self):
        """Called each frame: the moment the countdown runs out, put a little goodwill back.
        Not all of it. They will trade with the player again and remember why they stopped."""
        if self.hostile_until and not self.hostile:
            self.hostile_until = 0.0
            self.affinity = max(self.affinity, c.Affinity.FORGIVEN)

    @property
    def is_militia(self) -> bool:
        """Whether this one meets a monster in the street or runs from it. Merchants never
        fight: their stock is their life, and a shopkeeper with a sword is a different game."""
        if self._militia is None:
            seed = f"militia:{round(self.home[0])}:{round(self.home[1])}"
            self._militia = not self.is_merchant and random.Random(seed).random() < c.Villages.MILITIA_FRACTION
        return self._militia

    def sees(self, x: float, y: float, radius: float) -> bool:
        """Whether (x, y) falls inside this one's field of view: near enough, and inside the
        wedge they are actually facing. Sprites face up, so the facing angle is the drawn
        orientation less a quarter turn."""
        if self.distance_to_point((x, y)) > radius:
            return False
        facing = self.orientation - math.pi / 2
        bearing = math.atan2(y - self.y, x - self.x)
        offset = abs((bearing - facing + math.pi) % (2 * math.pi) - math.pi)
        return offset <= math.radians(c.Crime.VIEW_CONE_DEG) / 2

    @property
    def can_talk(self) -> bool:
        """False once this NPC has turned on the player: no conversation, no shop, no
        quest hand-in from someone trying to kill you."""
        return not self.hostile

    @property
    def has_active_quest(self):
        return self.quest is not None and not self.quest.is_completed

    def _affinity_tier(self) -> tuple:
        return next(tier for tier in AFFINITY_TIERS if tier[0] is None or self.affinity < tier[0])

    def affinity_descriptor(self) -> str:
        """A prompt hint reflecting how the NPC feels about the player, or "" when neutral."""
        return self._affinity_tier()[1]

    def affinity_tier_color(self) -> tuple:
        return self._affinity_tier()[2]

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
            # Absolute wall clock, like the rest cooldowns: quitting while a village is
            # angry must not be a way of waiting the anger out.
            "hostile_until": self.hostile_until,
            "grudge": self.grudge,
            "affinity": self.affinity,
            "shop_ready": self.shop_ready,
            "home": list(self.home),
            "shop_items": [{**item.to_dict(), "shop_price": self.shop_prices[item.id]} for item in self.shop_items],
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
        npc.is_merchant = data["is_merchant"]
        npc.is_thief = data.get("is_thief", False)
        # A save from before anger had a clock recorded it as a plain flag; those villagers
        # were angry for good, so they load as a grudge rather than silently forgiving.
        npc.hostile_until = data.get("hostile_until", 0.0)
        npc.grudge = data.get("grudge", data.get("hostile", False))
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
        self.shop_items.clear()
        self.shop_prices.clear()

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

    def update(self, player: Player, dt, blocked=None, waypoint=None, target=None, refuge=None, face_player=True):
        """One frame of this villager's life, returning the damage their swing just landed
        on `target` (0 for none) so the world can resolve it: the same villager can be
        swinging at the player or at a monster in their street, and only the world knows
        which lists to take the blow off.

        The world decides what they are doing and hands it in: `target` is who they are
        fighting, `refuge` a point to run to (a frightened villager heading for a door), and
        `face_player` False keeps them looking where they were, which is what stops a vision
        cone from pointing at the player no matter where they stand."""
        self._cool_off()
        if target is not None:
            return self._hunt(target, dt, blocked, waypoint)
        if refuge is not None:
            self._run_to(refuge, dt, blocked)
            return 0

        if (
            face_player
            and not self.hostile
            and self.distance_to_point(player.get_pos()) < (c.Entities.NPC_WANDER_PAUSE_DISTANCE)
        ):
            # atan2(dy, dx) measures from the x-axis; sprites face up, so rotate a quarter turn
            self.orientation = math.atan2(player.y - self.y, player.x - self.x) + math.pi / 2
            return 0

        moved_angle = self.wander.step(self, dt, self.home, c.Entities.NPC_SIZE / 2, blocked)
        # Face the way it actually moved, not the way it wanted to: a slider looks along
        # the wall, and one pinned against a building stops staring straight into it.
        if moved_angle is not None:
            self.orientation = moved_angle + math.pi / 2
        return 0

    def _step_towards(self, point, dt, blocked, speed_mult: float = 1.0) -> float:
        """Walk at a point, sliding along whatever is in the way. Returns the heading."""
        angle = math.atan2(point[1] - self.y, point[0] - self.x)
        radius = c.Entities.NPC_SIZE / 2
        speed = c.Entities.NPC_HOSTILE_SPEED * speed_mult * dt * c.TARGET_FPS / 1000.0
        step_x, step_y = math.cos(angle) * speed, math.sin(angle) * speed
        if blocked is not None and blocked(self.x + step_x, self.y, radius):
            step_x = 0
        self.x += step_x
        if blocked is not None and blocked(self.x, self.y + step_y, radius):
            step_y = 0
        self.y += step_y
        return angle

    def _run_to(self, refuge, dt, blocked=None):
        """A villager with no stomach for the fight, making for the nearest door. They stop
        once they are on the spot rather than jittering on it."""
        if self.distance_to_point(refuge) <= c.Entities.NPC_ATTACK_RANGE:
            return
        self.orientation = self._step_towards(refuge, dt, blocked) + math.pi / 2

    def _hunt(self, target, dt, blocked=None, waypoint=None) -> int:
        """Walk at whatever this one is fighting and swing when it is in reach, returning the
        damage landed this frame. Deliberately simpler than a monster's chase: villagers are
        farmers with sticks, not hunters. They walk at the target (round a wall when the
        world hands them a waypoint) and hit whatever comes into range."""
        dist = self.distance_to_point((target.x, target.y))
        goal = waypoint if waypoint is not None else (target.x, target.y)
        angle = math.atan2(goal[1] - self.y, goal[0] - self.x)
        self.orientation = angle + math.pi / 2

        if dist > c.Entities.NPC_ATTACK_RANGE:
            self._step_towards(goal, dt, blocked)

        damage = 0
        now = pygame.time.get_ticks()
        if dist <= c.Entities.NPC_ATTACK_RANGE + target.size // 2 and now >= self.attack_ready_ms:
            self.attack_ready_ms = now + c.Entities.NPC_ATTACK_COOLDOWN_MS
            self.start_attack_anim()
            damage = c.Entities.NPC_DAMAGE

        self.update_attack_anim(dt)
        return damage

    def _badge(self) -> Optional[tuple]:
        """(font, symbol, color) for the marker floating over this NPC's head, or None."""
        if self.hostile:
            return c.Fonts.badge, "!", c.Colors.RED
        if self.has_active_quest:
            return c.Fonts.badge, "!", c.Colors.YELLOW
        if self.is_thief:
            return c.Fonts.badge, "?", (190, 70, 220)
        if self.is_merchant:
            color = (100, 255, 100) if self.shop_ready else (120, 120, 80)
            return c.Fonts.badge_small, "$", color
        return None

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

        badge = self._badge()
        if badge is not None:
            font, symbol, color = badge
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render(symbol, True, color)
            text_rect = text.get_rect(center=(screen_x, screen_y - c.Entities.NPC_SIZE // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)

        if self.name:
            name_surface = c.Fonts.small.render(self.name, True, c.Colors.WHITE)
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
