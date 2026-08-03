from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from core.screen_fx import get_vignette
from game.entities.entities import Entity
from game.entities.items import POTION_EFFECT_LABELS, potion_duration, potion_magnitude, rarity_color
from game.entities.stats import Stats

if TYPE_CHECKING:
    from core.save import SaveSystem


EQUIP_SLOT_ATTRS = {
    "melee_weapon": "equipped_melee_weapon_id",
    "ranged_weapon": "equipped_ranged_weapon_id",
    "armor": "equipped_armor_id",
    "accessory": "equipped_accessory_id",
}


def _item_outline(item) -> tuple:
    """Border colour for gear drawn on the character: rarity colour, black for common."""
    return c.Colors.BLACK if item.rarity == "common" else rarity_color(item.rarity)


def _equip_slot(item) -> str | None:
    """Which equip slot an item belongs to. Weapons split into a melee and a ranged
    slot by archetype (constants.weapon_archetype), so a bow and a sword can be
    carried and equipped at the same time instead of fighting over one slot."""
    if item.item_type == "weapon":
        return "ranged_weapon" if c.weapon_archetype(item.name).ranged else "melee_weapon"
    if item.item_type in ("armor", "accessory"):
        return item.item_type
    return None


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
        self.equipped_melee_weapon_id = equipped.get("melee_weapon")
        self.equipped_ranged_weapon_id = equipped.get("ranged_weapon")
        # Migrate a pre-dual-slot save: the old single "weapon" key was always a melee
        # weapon in practice, since ranged combat had no separate slot to get stuck in.
        if equipped.get("weapon") and self.equipped_melee_weapon_id is None:
            self.equipped_melee_weapon_id = equipped["weapon"]
        self.equipped_armor_id = equipped.get("armor")
        self.equipped_accessory_id = equipped.get("accessory")

        saved = save_system.load("player", None)
        if saved:
            self.x = saved["x"]
            self.y = saved["y"]
            self.hp = saved["hp"]

        # Wall-clock timestamp (not a frame counter) so the post-death weakness survives
        # quitting to the main menu or relaunching, rather than being a free reset.
        self.death_debuff_until = save_system.load("death_debuff_until", 0.0)

        # Potion buffs: {effect: {"until": wall-clock seconds, "magnitude": float}}.
        # Wall-clock for the same reason as above, so quitting doesn't bank buff time.
        self.buffs = {
            effect: data
            for effect, data in save_system.load("buffs", {}).items()
            if data.get("until", 0.0) > time.time()
        }

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
            if blocked is not None and blocked(self.x + step_x, self.y, radius):
                step_x = 0
            self.x += step_x
            if blocked is not None and blocked(self.x, self.y + step_y, radius):
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
        """Add an item to the inventory, merging a stackable (ammo, potion) into a matching
        stack. Potions only merge with the same rarity, since rarity is what makes one
        healing potion stronger than another."""
        existing = None
        if item.item_type == "ammo":
            existing = next((i for i in self.inventory if i.item_type == "ammo" and i.name == item.name), None)
        elif item.item_type == "potion":
            existing = next(
                (
                    i
                    for i in self.inventory
                    if i.item_type == "potion"
                    and i.name == item.name
                    and i.rarity == item.rarity
                    and i.potion_effect == item.potion_effect
                ),
                None,
            )
        if existing is not None:
            existing.quantity += item.quantity
            return existing
        self.inventory.append(item)
        return item

    def quick_potions(self) -> list:
        """The potions bound to the HUD number keys, in inventory order."""
        return [item for item in self.inventory if item.item_type == "potion"][: c.Potions.QUICK_SLOTS]

    def equipped_ids(self) -> dict:
        return {
            "melee_weapon": self.equipped_melee_weapon_id,
            "ranged_weapon": self.equipped_ranged_weapon_id,
            "armor": self.equipped_armor_id,
            "accessory": self.equipped_accessory_id,
        }

    def equipped_item(self, slot: str):
        item_id = getattr(self, EQUIP_SLOT_ATTRS[slot])
        if item_id is None:
            return None
        return next((item for item in self.inventory if item.id == item_id), None)

    def equip(self, item):
        """Equip the item into its slot (no toggle), replacing whatever is there."""
        slot = _equip_slot(item)
        if slot is None:
            return
        setattr(self, EQUIP_SLOT_ATTRS[slot], item.id)
        self.save_system.update("equipped", self.equipped_ids())

    def is_upgrade(self, item) -> bool:
        """True if the item is equippable and beats (or fills an empty) its slot."""
        slot = _equip_slot(item)
        if slot is None:
            return False
        equipped = self.equipped_item(slot)
        return item.bonus > (equipped.bonus if equipped else -1)

    def toggle_equip(self, item):
        """Equip the item into its slot, or unequip it if it's already there."""
        slot = _equip_slot(item)
        if slot is None:
            return
        attr = EQUIP_SLOT_ATTRS[slot]
        setattr(self, attr, None if getattr(self, attr) == item.id else item.id)
        self.save_system.update("equipped", self.equipped_ids())

    def unequip_if_equipped(self, item):
        """Clears an item's slot before it leaves the inventory (sold, dropped, etc)."""
        slot = _equip_slot(item)
        attr = EQUIP_SLOT_ATTRS.get(slot)
        if attr and getattr(self, attr) == item.id:
            setattr(self, attr, None)
            self.save_system.update("equipped", self.equipped_ids())

    def weapon_bonus(self, ranged: bool = False) -> int:
        item = self.equipped_item("ranged_weapon" if ranged else "melee_weapon")
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

    def _weapon_affix(self, name: str, ranged: bool = False) -> float:
        item = self.equipped_item("ranged_weapon" if ranged else "melee_weapon")
        return item.affixes.get(name, 0) if item else 0

    def _armor_affix(self, name: str) -> float:
        item = self.equipped_item("armor")
        return item.affixes.get(name, 0) if item else 0

    def crit_bonus(self, ranged: bool = False) -> float:
        return self._weapon_affix("crit", ranged) + self.accessory_bonus("crit") * c.Stats.ACCESSORY_CRIT_PER_BONUS

    def lifesteal_frac(self, ranged: bool = False) -> float:
        acc = self.accessory_bonus("lifesteal") * c.Stats.ACCESSORY_LIFESTEAL_PER_BONUS
        return self._weapon_affix("lifesteal", ranged) + acc

    def burn_damage(self, ranged: bool = False) -> int:
        return int(self._weapon_affix("burn", ranged))

    def execute_threshold(self, ranged: bool = False) -> float:
        return self._weapon_affix("execute", ranged)

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

    # --- potions and buffs -----------------------------------------------------

    def use_potion(self, item) -> str | None:
        """Drink one potion off the stack. Returns a short label of what it did, or None
        if it would be wasted (a heal at full hp), leaving the potion untouched."""
        if item.item_type != "potion" or item.quantity <= 0:
            return None

        effect = item.potion_effect or "heal"
        magnitude = potion_magnitude(effect, item.rarity)

        if effect == "heal":
            healed = min(self.max_hp - self.hp, self.max_hp * magnitude)
            if healed <= 0:
                return None
            self.heal(healed)
            label = f"+{round(healed)} HP"
        else:
            duration = potion_duration(item.rarity)
            self.apply_buff(effect, magnitude, duration)
            label = f"{POTION_EFFECT_LABELS[effect].capitalize()} {round(duration)}s"

        item.quantity -= 1
        if item.quantity <= 0 and item in self.inventory:
            self.inventory.remove(item)

        play_sound("potion_drink")
        get_particles().spawn_burst(self.x, self.y, item.color, count=14, speed=3, life=450, size=4, gravity=0.25)
        get_floating_text().spawn(self.x, self.y - c.Player.SIZE / 2, label, item.color)
        return label

    def apply_buff(self, effect: str, magnitude: float, duration_s: float):
        """Start or refresh a timed buff. Drinking a second potion of the same effect
        restarts the clock and keeps the stronger magnitude instead of stacking both."""
        current = self.buffs.get(effect)
        if current is not None and current["until"] > time.time():
            magnitude = max(magnitude, current["magnitude"])
        self.buffs[effect] = {"until": time.time() + duration_s, "magnitude": magnitude}
        self.save_system.update("buffs", self.buffs)

    def buff_magnitude(self, effect: str, default: float = 0.0) -> float:
        data = self.buffs.get(effect)
        if data is None or data["until"] <= time.time():
            return default
        return data["magnitude"]

    def active_buffs(self) -> list:
        """(effect, seconds left, magnitude) for every live buff, soonest to expire first."""
        now = time.time()
        live = [(e, d["until"] - now, d["magnitude"]) for e, d in self.buffs.items() if d["until"] > now]
        return sorted(live, key=lambda buff: buff[1])

    def speed_multiplier(self) -> float:
        base = self.stats.speed_multiplier() + self.accessory_bonus("speed") * c.Stats.ACCESSORY_SPEED_PER_BONUS
        return base * self.buff_magnitude("swiftness", 1.0)

    def regen_rate(self) -> float:
        accessory = self.accessory_bonus("regen") * c.Stats.ACCESSORY_REGEN_PER_BONUS
        return self.stats.regen_rate() + accessory + self.buff_magnitude("regen")

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

        reduction = self.armor_bonus() + self.stats.damage_reduction() + int(self.buff_magnitude("stoneskin"))
        actual = max(damage - reduction, 1)
        self.hp -= actual
        self.last_damage_ms = pygame.time.get_ticks()
        play_sound("player_hurt")
        get_decals().spawn(self.x, self.y, radius=c.Decals.PLAYER_HURT_RADIUS)
        get_particles().spawn_burst(self.x, self.y, c.Colors.RED, count=8, speed=4, life=350, size=4, gravity=0.3)
        get_floating_text().spawn(self.x, self.y - c.Player.SIZE / 2, str(actual), (255, 90, 90), big=True)
        get_shake().add(c.Combat.PLAYER_HURT_SHAKE)
        get_vignette().trigger(c.Combat.PLAYER_HURT_VIGNETTE)

        # Thorns reflects flat damage back at a melee attacker, but never lands the kill.
        thorns = self.thorns_damage()
        if source is not None and thorns > 0 and getattr(source, "hp", 0) > 0:
            source.hp = max(1, source.hp - thorns)
            get_particles().spawn_burst(source.x, source.y, (220, 220, 120), count=6, speed=3, life=300, size=3)

    def gain_coins(self, amount: int):
        """Add coins from loot, boosted by the coin-find accessory."""
        self.add_coins(round(amount * self.coin_find_mult()))

    def is_shaken(self) -> bool:
        """True while the post-death weakness from apply_death_penalty is still active."""
        return time.time() < self.death_debuff_until

    def damage_multiplier(self) -> float:
        weakness = c.Death.DEBUFF_DAMAGE_MULT if self.is_shaken() else 1.0
        return weakness * self.buff_magnitude("strength", 1.0)

    def apply_death_penalty(self) -> int:
        """Dock a share of coins and start the post-respawn weakness timer. Returns the
        number of coins lost, for the game-over screen to report."""
        loss = int(self.coins * c.Death.COIN_LOSS_PCT)
        self.add_coins(-loss)
        # Whatever was coursing through the player's veins died with them.
        self.buffs = {}
        self.save_system.update("buffs", self.buffs)
        self.death_debuff_until = time.time() + c.Death.DEBUFF_DURATION_S
        self.save_system.update("death_debuff_until", self.death_debuff_until)
        return loss

    def gear(self) -> dict:
        """What the equipped items look like on the character, for draw_human: a weapon
        per hand (shape from its archetype), an armour ring, an accessory gem. Colours
        come from the item itself, borders from its rarity."""
        gear = {}
        for slot in ("melee_weapon", "ranged_weapon"):
            item = self.equipped_item(slot)
            if item is not None:
                gear[slot.split("_")[0]] = {
                    "kind": c.weapon_archetype(item.name).name,
                    "color": item.color,
                    "outline": _item_outline(item),
                }
        for slot in ("armor", "accessory"):
            item = self.equipped_item(slot)
            if item is not None:
                gear[slot] = {"color": item.color, "outline": _item_outline(item)}
        return gear

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
            gear=self.gear(),
        )
