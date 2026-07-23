from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.particles import get_particles
from game.entities.entities import Entity
from game.entities.stats import Stats

if TYPE_CHECKING:
    from core.save import SaveSystem


EQUIP_SLOT_ATTRS = {
    "weapon": "equipped_weapon_id",
    "armor": "equipped_armor_id",
    "accessory": "equipped_accessory_id",
}


class Player(Entity):
    def __init__(self, save_system, coins):
        super().__init__(
            c.World.WORLD_SIZE // 2, c.World.WORLD_SIZE // 2, c.Colors.PLAYER, c.Player.SIZE, c.Player.HP, c.Player.HP
        )

        self.save_system: SaveSystem = save_system
        self.inventory = []
        self.coins = coins

        # Earliest tick at which the next swing is allowed, and the current weapon's
        # animation speed. Both are set by World.handle_attack.
        self.attack_ready_ms = 0
        self.attack_swing_mult = 1.0

        self.stats = Stats(save_system.load("stats", None))
        self.max_hp = self.stats.max_hp()
        self.hp = self.max_hp

        equipped = save_system.load("equipped", {})
        self.equipped_weapon_id = equipped.get("weapon")
        self.equipped_armor_id = equipped.get("armor")
        self.equipped_accessory_id = equipped.get("accessory")

        saved = save_system.load("player", None)
        if saved:
            self.x = saved["x"]
            self.y = saved["y"]
            self.hp = saved["hp"]

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "hp": self.hp}

    def save_stats(self):
        self.save_system.update("stats", self.stats.to_dict())

    def get_pos(self, distance=None):
        if distance is not None:
            attack_x = self.x + math.sin(self.orientation) * distance
            attack_y = self.y - math.cos(self.orientation) * distance
            return (attack_x, attack_y)
        return (self.x, self.y)

    def move(self, camera_pos, dt, blocked=None):
        keys = pygame.key.get_pressed()

        running = bool(keys[pygame.K_LSHIFT])
        base_speed = c.Player.RUN_SPEED if running else c.Player.SPEED
        actual_speed = base_speed * self.speed_multiplier()

        forward = keys[pygame.K_z] or keys[pygame.K_w]
        moving = forward or keys[pygame.K_s]

        if moving:
            mouse_x, mouse_y = pygame.mouse.get_pos()

            world_mouse_x = mouse_x - c.Screen.ORIGIN_X + camera_pos[0]
            world_mouse_y = mouse_y - c.Screen.ORIGIN_Y + camera_pos[1]

            dx = world_mouse_x - self.x
            dy = world_mouse_y - self.y
            dist = math.hypot(dx, dy)

            if dist != 0:
                dx /= dist
                dy /= dist

            speed = actual_speed if forward else -actual_speed / 1.5
            move_factor = dt * c.TARGET_FPS / 1000.0
            step_x = dx * speed * move_factor
            step_y = dy * speed * move_factor
            # Move one axis at a time so a wall on one axis lets the player slide along it.
            radius = c.Player.SIZE / 2
            if blocked is not None and blocked(self.x + step_x, self.y, radius, True):
                step_x = 0
            self.x += step_x
            if blocked is not None and blocked(self.x, self.y + step_y, radius, True):
                step_y = 0
            self.y += step_y

            # Running is what trains speed; plain walking does not.
            if running:
                self.stats.train("speed", c.Stats.XP_PER_RUN_FRAME * move_factor)

        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - c.Screen.ORIGIN_X
        dy = mouse_y - c.Screen.ORIGIN_Y
        self.orientation = math.atan2(dx, -dy)

        self.update_attack_anim(dt, self.attack_swing_mult)

        # Keep the xp-gain accessory's multiplier live for every stat.train call this frame.
        self.stats.xp_bonus = self.xp_gain_mult()

        self.max_hp = self.stats.max_hp()
        if self.hp < self.max_hp:
            # Standing still lets the regen-while-still armour affix top up faster.
            regen = self.regen_rate() + (0.0 if moving else self.regen_still_bonus())
            self.hp = min(self.hp + regen * dt, self.max_hp)

    def add_item(self, item):
        """Add an item to the inventory, merging ammo into an existing stack of the same name."""
        if item.item_type == "ammo":
            existing = next((i for i in self.inventory if i.item_type == "ammo" and i.name == item.name), None)
            if existing is not None:
                existing.quantity += item.quantity
                return existing
        self.inventory.append(item)
        return item

    def equipped_ids(self) -> dict:
        return {
            "weapon": self.equipped_weapon_id,
            "armor": self.equipped_armor_id,
            "accessory": self.equipped_accessory_id,
        }

    def equipped_item(self, item_type: str):
        item_id = getattr(self, EQUIP_SLOT_ATTRS[item_type])
        if item_id is None:
            return None
        return next((item for item in self.inventory if item.id == item_id), None)

    def equip(self, item):
        """Equip the item into its slot (no toggle), replacing whatever is there."""
        attr = EQUIP_SLOT_ATTRS.get(item.item_type)
        if attr is None:
            return
        setattr(self, attr, item.id)
        self.save_system.update("equipped", self.equipped_ids())

    def is_upgrade(self, item) -> bool:
        """True if the item is equippable and beats (or fills an empty) its slot."""
        if item.item_type not in EQUIP_SLOT_ATTRS:
            return False
        equipped = self.equipped_item(item.item_type)
        return item.bonus > (equipped.bonus if equipped else -1)

    def toggle_equip(self, item):
        """Equip the item into its slot, or unequip it if it's already there."""
        attr = EQUIP_SLOT_ATTRS.get(item.item_type)
        if attr is None:
            return
        setattr(self, attr, None if getattr(self, attr) == item.id else item.id)
        self.save_system.update("equipped", self.equipped_ids())

    def unequip_if_equipped(self, item):
        """Clears an item's slot before it leaves the inventory (sold, dropped, etc)."""
        attr = EQUIP_SLOT_ATTRS.get(item.item_type)
        if attr and getattr(self, attr) == item.id:
            setattr(self, attr, None)
            self.save_system.update("equipped", self.equipped_ids())

    def weapon_bonus(self) -> int:
        item = self.equipped_item("weapon")
        return item.bonus if item else 0

    def armor_bonus(self) -> int:
        item = self.equipped_item("armor")
        return item.bonus if item else 0

    def accessory_bonus(self, flavor: str) -> int:
        item = self.equipped_item("accessory")
        if item and item.accessory_flavor == flavor:
            return item.bonus
        return 0

    # --- affix effects ---------------------------------------------------------
    # Weapon/armour effects come from the equipped item's rolled affixes; accessories
    # contribute through their single flavor. Helpers combine both into one value.

    def _weapon_affix(self, name: str) -> float:
        item = self.equipped_item("weapon")
        return item.affixes.get(name, 0) if item else 0

    def _armor_affix(self, name: str) -> float:
        item = self.equipped_item("armor")
        return item.affixes.get(name, 0) if item else 0

    def crit_bonus(self) -> float:
        return self._weapon_affix("crit") + self.accessory_bonus("crit") * c.Stats.ACCESSORY_CRIT_PER_BONUS

    def lifesteal_frac(self) -> float:
        acc = self.accessory_bonus("lifesteal") * c.Stats.ACCESSORY_LIFESTEAL_PER_BONUS
        return self._weapon_affix("lifesteal") + acc

    def burn_damage(self) -> int:
        return int(self._weapon_affix("burn"))

    def execute_threshold(self) -> float:
        return self._weapon_affix("execute")

    def thorns_damage(self) -> int:
        return int(self._armor_affix("thorns"))

    def dodge_chance(self) -> float:
        return self._armor_affix("dodge")

    def regen_still_bonus(self) -> float:
        return self._armor_affix("regen_still")

    def coin_find_mult(self) -> float:
        return 1.0 + self.accessory_bonus("coinfind") * c.Stats.ACCESSORY_COINFIND_PER_BONUS

    def xp_gain_mult(self) -> float:
        return 1.0 + self.accessory_bonus("xpgain") * c.Stats.ACCESSORY_XP_PER_BONUS

    def pierce_count(self) -> int:
        return self.accessory_bonus("pierce")

    def heal(self, amount: float):
        self.hp = min(self.hp + amount, self.max_hp)

    def speed_multiplier(self) -> float:
        return self.stats.speed_multiplier() + self.accessory_bonus("speed") * c.Stats.ACCESSORY_SPEED_PER_BONUS

    def regen_rate(self) -> float:
        return self.stats.regen_rate() + self.accessory_bonus("regen") * c.Stats.ACCESSORY_REGEN_PER_BONUS

    def buy_multiplier(self) -> float:
        luck = self.accessory_bonus("luck") * c.Stats.ACCESSORY_LUCK_PER_BONUS
        return max(c.Stats.BUY_FLOOR, self.stats.buy_multiplier() - luck)

    def sell_multiplier(self) -> float:
        luck = self.accessory_bonus("luck") * c.Stats.ACCESSORY_LUCK_PER_BONUS
        return min(c.Stats.SELL_CEILING, self.stats.sell_multiplier() + luck)

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

    def receive_damage(self, damage, source=None):
        # Armour's dodge affix can shrug a hit off entirely.
        if self.dodge_chance() and random.random() < self.dodge_chance():
            get_particles().spawn_burst(self.x, self.y, c.Colors.WHITE, count=5, speed=3, life=250, size=3)
            return

        # Taking hits trains resistance and, more slowly, vitality.
        self.stats.train("resistance", c.Stats.XP_PER_DAMAGE_TAKEN)
        self.stats.train("vitality", c.Stats.XP_PER_DAMAGE_TAKEN * 0.5)
        self.max_hp = self.stats.max_hp()

        reduction = self.armor_bonus() + self.stats.damage_reduction()
        actual = max(damage - reduction, 1)
        self.hp -= actual
        self.last_damage_ms = pygame.time.get_ticks()
        play_sound("player_hurt")
        get_particles().spawn_burst(self.x, self.y, c.Colors.RED, count=8, speed=4, life=350, size=4)
        get_shake().add(c.Combat.PLAYER_HURT_SHAKE)

        # Thorns reflects flat damage back at a melee attacker, but never lands the kill.
        thorns = self.thorns_damage()
        if source is not None and thorns > 0 and getattr(source, "hp", 0) > 0:
            source.hp = max(1, source.hp - thorns)
            get_particles().spawn_burst(source.x, source.y, (220, 220, 120), count=6, speed=3, life=300, size=3)

    def gain_coins(self, amount: int):
        """Add coins from loot, boosted by the coin-find accessory."""
        self.add_coins(round(amount * self.coin_find_mult()))

    def draw(self, screen):
        super().draw(
            screen,
            c.Screen.ORIGIN_X,
            c.Screen.ORIGIN_Y,
            c.Player.SIZE,
            c.Colors.PLAYER,
            self.orientation,
            self.attack_progress,
            self.attack_hand,
            bar_width=800,
            bar_height=30,
            health_bar_offset=360,
            bar_color=c.Colors.GREEN,
            bar_border_width=4,
        )
