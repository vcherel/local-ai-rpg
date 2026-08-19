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
from game.entities.items import (
    POTION_EFFECT_LABELS,
    potion_duration,
    potion_magnitude,
    rarity_color,
    rarity_tier,
)
from game.entities.stats import Stats

if TYPE_CHECKING:
    from core.save import SaveSystem


# Every equip slot the player has, in the order the save writes them. `Player.equipped`
# is a dict on exactly these keys holding the id of what is in each, so a slot is read and
# written by its own name everywhere instead of through an attribute looked up off a table.
EQUIP_SLOT_NAMES = (
    "melee_weapon",
    "melee_weapon_2",
    "ranged_weapon",
    "offhand",
    "armor",
    "accessory",
    "ammo",
)

# The two melee slots, in bar order. Both are equipped at once and `Player.active_melee`
# indexes which of them swings; carrying a spear beside a sword is a choice of stance made
# before the fight rather than a trip through the inventory during it.
MELEE_SLOTS = ("melee_weapon", "melee_weapon_2")

# Held down to raise the shield. A hold rather than a toggle, so blocking is something
# you do for the blow you saw coming instead of a stance you leave switched on.
BLOCK_KEY = pygame.K_SPACE


def _item_outline(item) -> tuple:
    """Border colour for gear drawn on the character: rarity colour, black for common."""
    return c.Colors.BLACK if item.rarity == "common" else rarity_color(item.rarity)


# What to call an attacker that has nothing to be called: a villager the name generator
# has not reached yet, or anything else that lands a blow without a name of its own. Keyed
# by class name rather than by the classes themselves, which `player.py` does not import.
_GENERIC_SOURCE_NAMES = {
    "NPC": "a villager",
    "Monster": "a monster",
    "Boss": "a monster",
    "Critter": "an animal",
    "Projectile": "a stray shot",
    "BearTrap": "a bear trap",
}


def _damage_source_name(source) -> str:
    """What to call whatever just hit the player, on the death screen. A boss goes by its
    full title, a villager by their name, anything else by its species. An arrow goes by
    its shooter (`source_name`) rather than by nothing at all, which used to leave the death
    screen blaming whatever last touched the player in melee; damage with no attacker behind
    it (a shrine's curse, a burn) names nobody and leaves the last one.

    Anything that *is* an attacker always answers with something, even when it has no name:
    a nameless villager returning "" used to leave the last name standing, so the death
    screen blamed the dog the player had fought earlier for a blow the farmer landed."""
    if source is None:
        return ""
    if isinstance(source, str):
        return source
    for attr in ("display_name", "name", "source_name"):
        value = getattr(source, attr, None)
        if value:
            return str(value)
    kind_name = getattr(getattr(source, "kind", None), "name", "")
    return str(kind_name) if kind_name else _GENERIC_SOURCE_NAMES.get(type(source).__name__, "something")


def _equip_slot(item) -> str | None:
    """Which kind of slot an item belongs to. Weapons split into a melee and a ranged
    slot by archetype (constants.weapon_archetype), so a bow and a sword can be
    carried and equipped at the same time instead of fighting over one slot. A melee
    weapon answers with the first melee slot; which of the two it actually goes into is
    `Player._target_slot`'s call, since that depends on what is already held."""
    if item.item_type == "weapon":
        return "ranged_weapon" if c.weapon_archetype(item.name).ranged else "melee_weapon"
    if item.item_type == "shield":
        return "offhand"
    if item.item_type in ("armor", "accessory", "ammo"):
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

        saved_equipped = save_system.load("equipped", {})
        self.equipped = {slot: saved_equipped.get(slot) for slot in EQUIP_SLOT_NAMES}

        # The weapon bar the number keys switch between. It sits on top of the melee and
        # ranged slots rather than replacing them: selecting a bar slot routes that weapon
        # into whichever of the two its archetype belongs to, so a bow and a sword stay
        # carried at once and combat never has to ask which one is "active".
        bar = save_system.load("weapon_bar", [])
        self.weapon_bar = (list(bar) + [None] * c.Player.WEAPON_SLOTS)[: c.Player.WEAPON_SLOTS]

        # Which of the two melee slots swings. Combat asks `active_melee_weapon()` rather
        # than reading a slot directly, so both weapons stay visibly equipped and switching
        # between them is one key rather than an unequip and a re-equip.
        self.active_melee = 1 if save_system.load("active_melee", 0) else 0

        # The potions the HUD quick keys drink, chosen the way the weapon bar is: a list of
        # ids rather than whatever happens to sit first in the bag, so a healing potion does
        # not slide off the bar the moment a nicer-sounding elixir is picked up.
        potion_bar = save_system.load("potion_bar", [])
        self.potion_bar = (list(potion_bar) + [None] * c.Potions.QUICK_SLOTS)[: c.Potions.QUICK_SLOTS]

        # Shield state, all session-only: whether the shield is up this frame, how much
        # guard is left to absorb hits with, and the moment a broken guard comes back.
        self.blocking = False
        self.guard = c.Shield.GUARD_MAX
        self.guard_broken_until_ms = 0
        self.last_guard_use_ms = 0
        # Whether the player is in water this frame, set by move() and read by the renderer.
        self.swimming = False

        saved = save_system.load("player", None)
        if saved:
            self.x = saved["x"]
            self.y = saved["y"]
            self.hp = saved["hp"]

        # Wall-clock timestamp (not a frame counter) so the post-death weakness survives
        # quitting to the main menu or relaunching, rather than being a free reset.
        self.death_debuff_until = save_system.load("death_debuff_until", 0.0)

        # Guardian's Ward (legendary armour affix): wall-clock cooldown, persisted for the
        # same reason as the death debuff, so quitting can't reset the proc early.
        self.guardian_ward_cooldown_until = save_system.load("guardian_ward_cooldown_until", 0.0)
        self.guardian_ward_invuln_until = 0.0

        # Spawn grace: nothing lands until this wall-clock time. Session-only and deliberately
        # not persisted, unlike the debuff and the ward cooldown: it is granted on every entry
        # into the world anyway, so there is nothing a save could bank or lose.
        self.invuln_until = 0.0

        # What last landed a blow on the player, named the way the death screen says it.
        # Session-only: read once, between the killing hit and the screen it feeds.
        self.last_hit_by = ""

        # Rampage (legendary weapon affix): landed-hit counter per weapon slot, session-only.
        self._rampage_streak = {"melee_weapon": 0, "ranged_weapon": 0}

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

    def move(self, camera_pos, dt, blocked=None, in_water=False):
        keys = pygame.key.get_pressed()

        self._update_guard(keys, dt)

        running = bool(keys[pygame.K_LSHIFT]) and not self.blocking
        base_speed = c.Player.RUN_SPEED if running else c.Player.SPEED
        actual_speed = base_speed * self.speed_multiplier()
        if self.blocking:
            actual_speed *= c.Shield.SPEED_MULT
        # Water is crossed, not walked over: the penalty is heavy at first and eases off as
        # the swimming stat trains, never quite to walking pace, so a bridge keeps its job.
        self.swimming = in_water
        if in_water:
            actual_speed *= self.stats.swim_multiplier()

        forward = keys[pygame.K_z] or keys[pygame.K_w]
        # Caught in a bear trap: still aiming, still swinging, still being hit, just not
        # going anywhere until the jaws let go.
        moving = (forward or keys[pygame.K_s]) and not self.rooted

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

            # Running is what trains speed; plain walking does not. Swimming is trained by
            # the only thing anyone ever learns it from: being in the water.
            if running:
                self.stats.train("speed", c.Stats.XP_PER_RUN_FRAME * move_factor)
            if in_water:
                self.stats.train("swimming", c.Stats.XP_PER_SWIM_FRAME * move_factor)

        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - c.Screen.ORIGIN_X
        dy = mouse_y - c.Screen.ORIGIN_Y
        self.orientation = math.atan2(dx, -dy)

        self.update_attack_anim(dt, self.attack_swing_mult)

        # Keep the xp-gain accessory's multiplier live for every stat.train call this frame.
        self.stats.xp_bonus = self.xp_gain_mult()

        self.max_hp = self.effective_max_hp()
        self.hp = min(self.hp, self.max_hp)
        if self.hp < self.max_hp:
            # A regen potion works the moment it's drunk, that's what it's for. Everything
            # passive (vitality, accessory, the regen-while-still armour affix) stays shut
            # off until the player has gone REGEN_DELAY_MS without being hit, so healing up
            # is something you earn by disengaging rather than by waiting out a fight.
            regen = self.buff_magnitude("regen")
            if pygame.time.get_ticks() - self.last_damage_ms >= c.Player.REGEN_DELAY_MS:
                regen += self.passive_regen_rate() + (0.0 if moving else self.regen_still_bonus())
            self.hp = min(self.hp + regen * dt, self.max_hp)

    # --- shield and guard ------------------------------------------------------

    def has_shield(self) -> bool:
        return self.equipped_item("offhand") is not None

    def guard_broken(self) -> bool:
        return pygame.time.get_ticks() < self.guard_broken_until_ms

    def block_fraction(self) -> float:
        """Share of a frontal blow the equipped shield turns away, from its bonus."""
        shield = self.equipped_item("offhand")
        if shield is None:
            return 0.0
        return min(c.Shield.BLOCK_MAX, c.Shield.BLOCK_BASE + shield.bonus * c.Shield.BLOCK_PER_BONUS)

    def _update_guard(self, keys, dt):
        """Raise or lower the shield from the held key, and trickle the guard meter back
        once it has been left alone long enough. A broken guard stays down until its
        timer runs out, which is the window the player pays for holding block too long."""
        now = pygame.time.get_ticks()
        self.blocking = bool(keys[BLOCK_KEY]) and self.has_shield() and not self.guard_broken()
        if self.blocking:
            self.last_guard_use_ms = now
            return
        if now - self.last_guard_use_ms >= c.Shield.GUARD_REGEN_DELAY_MS:
            self.guard = min(c.Shield.GUARD_MAX, self.guard + c.Shield.GUARD_REGEN_PER_S * dt / 1000.0)

    def _blocks_hit(self, source) -> bool:
        """True when a raised shield actually covers this blow: it has to come from within
        the shield's arc of where the player is facing. A hit with no known origin (a burn,
        a trap) is never blocked, and neither is one taken from behind."""
        if not self.blocking or source is None:
            return False
        sx, sy = getattr(source, "x", None), getattr(source, "y", None)
        if sx is None or sy is None:
            return False
        # `orientation` is measured from straight up, clockwise: the forward vector is
        # (sin, -cos), the same one Player.get_pos projects a swing along.
        facing = math.atan2(-math.cos(self.orientation), math.sin(self.orientation))
        incoming = math.atan2(sy - self.y, sx - self.x)
        delta = abs((incoming - facing + math.pi) % (2 * math.pi) - math.pi)
        return delta <= math.radians(c.Shield.ARC_DEG) / 2

    def _absorb_with_shield(self, damage: float, source) -> float:
        """Run an incoming hit past the raised shield, returning what still gets through.

        What the shield stops is taken out of the guard meter; a hit that empties it breaks
        the guard, and that hit lands in full. So a big blow can be eaten once but not twice.
        """
        if not self._blocks_hit(source):
            return damage
        self.last_guard_use_ms = pygame.time.get_ticks()
        absorbed = damage * self.block_fraction()
        if absorbed >= self.guard:
            self.guard = 0.0
            self.guard_broken_until_ms = pygame.time.get_ticks() + c.Shield.GUARD_BREAK_MS
            self.blocking = False
            play_sound("crate_break")
            get_shake().add(c.Shield.GUARD_BREAK_SHAKE)
            get_floating_text().spawn(self.x, self.y - c.Player.SIZE / 2, "Guard broken!", (255, 150, 60), big=True)
            return damage
        self.guard -= absorbed
        play_sound("hit")
        get_particles().spawn_burst(self.x, self.y, (200, 220, 255), count=8, speed=4, life=300, size=3)
        get_floating_text().spawn(self.x, self.y - c.Player.SIZE / 2, "Blocked", (160, 210, 255))
        return damage - absorbed

    def add_item(self, item):
        """Add an item to the inventory, merging a stackable (ammo, potion) into a matching
        stack. Both only merge with the same rarity: rarity is what makes one healing potion
        stronger than another, and what makes a legendary quiver worth more than a common
        one. Merging across rarities silently threw the better item away. A potion also has
        to promise the same effect, since the name alone doesn't always settle that."""
        existing = None
        if item.item_type in ("ammo", "potion"):
            existing = next(
                (
                    i
                    for i in self.inventory
                    if i.item_type == item.item_type
                    and i.name == item.name
                    and i.rarity == item.rarity
                    and i.potion_effect == item.potion_effect
                ),
                None,
            )
        if existing is not None:
            existing.quantity += item.quantity
            self._auto_slot(existing)
            return existing
        self.inventory.append(item)
        self._auto_slot(item)
        return item

    def _auto_slot(self, item):
        """Put a supply where it is used from without a trip through the inventory: arrows
        load themselves when nothing is loaded (or the loaded stack is spent), and a potion
        takes a free quickbar slot. Neither ever displaces a choice the player already made."""
        if item.item_type == "ammo":
            loaded = self.equipped_item("ammo")
            if loaded is None or loaded.quantity <= 0:
                self.equipped["ammo"] = item.id
                self.save_system.update("equipped", self.equipped_ids())
        elif item.item_type == "potion" and item.id not in self.potion_bar and None in self.potion_bar:
            self.potion_bar[self.potion_bar.index(None)] = item.id
            self._save_potion_bar()

    def restock_bars(self):
        """Fill any free quickbar slot and any empty ammo slot from what is already carried.
        Run once the saved inventory has been relinked: a bag loaded from a save made before
        the quickbar was a choice would otherwise open with nothing on it."""
        for item in self.inventory:
            self._auto_slot(item)

    # --- potion quickbar --------------------------------------------------------
    # The same arrangement as the weapon bar, and for the same reason: what the quick keys
    # reach for is a choice the player makes and the save keeps, not a side effect of the
    # order things were picked up in.

    def _save_potion_bar(self):
        self.save_system.update("potion_bar", self.potion_bar)

    def quick_potions(self) -> list:
        """The potions bound to the HUD quick keys, None per empty slot. An id that no
        longer resolves (the stack was drunk or sold) is cleared on the way past."""
        by_id = {item.id: item for item in self.inventory}
        potions = []
        for index, item_id in enumerate(self.potion_bar):
            item = by_id.get(item_id) if item_id else None
            if item_id and item is None:
                self.potion_bar[index] = None
            potions.append(item)
        return potions

    def cycle_potion_slot(self, item):
        """Move a potion along the quickbar one slot per call, off the end and back to
        nothing. The manual assignment behind right-clicking a potion in the inventory."""
        if item.item_type != "potion":
            return
        if item.id in self.potion_bar:
            index = self.potion_bar.index(item.id)
            self.potion_bar[index] = None
            target = index + 1
        elif None in self.potion_bar:
            target = self.potion_bar.index(None)
        else:
            target = 0
        if target < len(self.potion_bar):
            self.potion_bar[target] = item.id
        self._save_potion_bar()

    def ready_ammo(self):
        """The quiver a shot would actually spend: the one in the ammo slot, else the
        cheapest carried. The fallback is what stops a stocked player being unable to
        shoot once a chosen stack runs dry, and the HUD count reads the same thing the
        shot does, so what is shown is never a quiver other than the one being fired."""
        loaded = self.equipped_item("ammo")
        if loaded is not None and loaded.quantity > 0:
            return loaded
        return min(
            (item for item in self.inventory if item.item_type == "ammo" and item.quantity > 0),
            key=lambda item: rarity_tier(item.rarity).price_mult,
            default=None,
        )

    def ammo_count(self) -> int:
        ammo = self.ready_ammo()
        return ammo.quantity if ammo else 0

    def equipped_ids(self) -> dict:
        return dict(self.equipped)

    def equipped_item(self, slot: str):
        item_id = self.equipped[slot]
        if item_id is None:
            return None
        return next((item for item in self.inventory if item.id == item_id), None)

    def _target_slot(self, item) -> str | None:
        """The slot an item is actually equipped into. Only melee has a choice to make: a
        free slot is filled before anything is displaced, and with both full it is the
        weapon in hand that gets replaced rather than the spare being carried for later."""
        slot = _equip_slot(item)
        if slot != "melee_weapon":
            return slot
        for melee_slot in MELEE_SLOTS:
            if self.equipped[melee_slot] is None:
                return melee_slot
        return self.active_melee_slot()

    def equip(self, item):
        """Equip the item into its slot (no toggle), replacing whatever is there."""
        slot = self._target_slot(item)
        if slot is None:
            return
        displaced = self.equipped[slot]
        self.equipped[slot] = item.id
        if slot in MELEE_SLOTS:
            # Equipping a weapon means wanting to use it, so the slot it landed in is the
            # one that swings; the other stays equipped as the spare.
            self._set_active_melee(MELEE_SLOTS.index(slot))
        self.save_system.update("equipped", self.equipped_ids())
        if slot in MELEE_SLOTS or slot == "ranged_weapon":
            self._add_to_weapon_bar(item.id, displaced)

    # --- melee slots ------------------------------------------------------------
    # Two melee weapons are carried at once and one of them swings. Nothing reads a melee
    # slot by name: combat, the affix helpers and the drawn gear all go through
    # `active_melee_weapon`, so the swap is a single index rather than gear changing hands.

    def active_melee_slot(self) -> str:
        return MELEE_SLOTS[self.active_melee]

    def active_melee_weapon(self):
        return self.equipped_item(self.active_melee_slot())

    def _set_active_melee(self, index: int):
        self.active_melee = index
        self.save_system.update("active_melee", self.active_melee)

    def swap_melee(self):
        """Switch to the other melee slot, if there is anything in it. Returns the weapon
        now in hand, or None when there is no second weapon to switch to."""
        other = 1 - self.active_melee
        item = self.equipped_item(MELEE_SLOTS[other])
        if item is None:
            return None
        self._set_active_melee(other)
        return item

    # --- weapon bar ------------------------------------------------------------
    # A short list of weapon ids the number keys switch between. Only the bar is stored;
    # what a slot does when pressed is decided by the weapon's archetype at the time, so
    # the bar never has to be kept in step with the melee/ranged slots.

    def _save_weapon_bar(self):
        self.save_system.update("weapon_bar", self.weapon_bar)

    def _add_to_weapon_bar(self, item_id: str, displaced_id: str | None = None):
        """Put a newly equipped weapon on the bar: into the slot holding the weapon it
        just pushed out of its equip slot, else the first free slot, else the last one."""
        if item_id in self.weapon_bar:
            return
        if displaced_id is not None and displaced_id in self.weapon_bar:
            index = self.weapon_bar.index(displaced_id)
        elif None in self.weapon_bar:
            index = self.weapon_bar.index(None)
        else:
            index = len(self.weapon_bar) - 1
        self.weapon_bar[index] = item_id
        self._save_weapon_bar()

    def _drop_from_weapon_bar(self, item_id: str):
        if item_id in self.weapon_bar:
            self.weapon_bar[self.weapon_bar.index(item_id)] = None
            self._save_weapon_bar()

    def weapon_bar_items(self) -> list:
        """The bar as items, None per empty slot. An id that no longer resolves (the
        weapon was sold from another screen) is cleared on the way past."""
        by_id = {item.id: item for item in self.inventory}
        items = []
        for index, item_id in enumerate(self.weapon_bar):
            item = by_id.get(item_id) if item_id else None
            if item_id and item is None:
                self.weapon_bar[index] = None
            items.append(item)
        return items

    def cycle_weapon_slot(self, item):
        """Move a weapon along the bar one slot per call, off the end and back to nothing.
        This is the manual assignment behind right-clicking a weapon in the inventory."""
        if item.item_type != "weapon":
            return
        if item.id in self.weapon_bar:
            index = self.weapon_bar.index(item.id)
            self.weapon_bar[index] = None
            target = index + 1
        elif None in self.weapon_bar:
            # A free slot first, so the common case of filling the bar up never costs
            # the player a weapon they had already put on it.
            target = self.weapon_bar.index(None)
        else:
            target = 0
        if target < len(self.weapon_bar):
            self.weapon_bar[target] = item.id
        self._save_weapon_bar()

    def select_weapon(self, slot: int):
        """Draw the weapon on bar slot `slot`: already equipped, it is simply the one that
        swings from now on; otherwise it is equipped into the slot its archetype belongs to.
        Returns the item, or None if that bar slot is empty."""
        items = self.weapon_bar_items()
        if slot >= len(items) or items[slot] is None:
            return None
        item = items[slot]
        for equip_slot, equipped_id in self.equipped.items():
            if equipped_id == item.id:
                if equip_slot in MELEE_SLOTS:
                    self._set_active_melee(MELEE_SLOTS.index(equip_slot))
                return item
        self.equip(item)
        return item

    def equipped_slot_of(self, item) -> str | None:
        """The slot an item is currently in, or None if it isn't equipped."""
        return next((slot for slot, equipped_id in self.equipped.items() if equipped_id == item.id), None)

    def is_upgrade(self, item) -> bool:
        """True if the item is equippable and beats (or fills an empty) its slot. Ammo is
        equippable but never an upgrade: which quiver is loaded is a choice, not a power
        level, and prompting "press F to equip" over every bundle of arrows is noise. A
        melee weapon is measured against the weaker of the two melee slots, since that is
        the one it would push out."""
        slot = _equip_slot(item)
        if slot is None or slot == "ammo":
            return False
        if slot == "melee_weapon":
            held = [self.equipped_item(melee_slot) for melee_slot in MELEE_SLOTS]
            if any(weapon is None for weapon in held):
                return True
            return item.bonus > min(weapon.bonus for weapon in held)
        equipped = self.equipped_item(slot)
        return item.bonus > (equipped.bonus if equipped else -1)

    def _clear_slot(self, slot: str):
        """Empty an equip slot. Emptying the melee slot that was in hand falls back to the
        other one, so putting a weapon away never leaves the player barehanded next to the
        spare they are still carrying."""
        self.equipped[slot] = None
        if slot == self.active_melee_slot() and self.equipped_item(MELEE_SLOTS[1 - self.active_melee]) is not None:
            self._set_active_melee(1 - self.active_melee)
        self.save_system.update("equipped", self.equipped_ids())

    def toggle_equip(self, item):
        """Equip the item into its slot, or unequip it if it's already there."""
        slot = self.equipped_slot_of(item)
        if slot is not None:
            self._clear_slot(slot)
        elif _equip_slot(item) is not None:
            self.equip(item)

    def unequip_if_equipped(self, item):
        """Clears an item's slot before it leaves the inventory (sold, dropped, etc)."""
        slot = self.equipped_slot_of(item)
        if slot is not None:
            self._clear_slot(slot)
        self._drop_from_weapon_bar(item.id)
        if item.id in self.potion_bar:
            self.potion_bar[self.potion_bar.index(item.id)] = None
            self._save_potion_bar()

    def _best_loadout(self) -> dict:
        """The strongest thing carried for every slot it could go in, judged on bonus alone,
        the way `is_upgrade` judges a pickup. Ammo is left out (which quiver is loaded is a
        choice, not a power level) and so is anything unequippable."""
        candidates: dict[str, list] = {}
        for item in self.inventory:
            kind = _equip_slot(item)
            if kind is None or kind == "ammo":
                continue
            candidates.setdefault(kind, []).append(item)

        loadout = {}
        for kind, items in candidates.items():
            best = sorted(items, key=lambda item: (-item.bonus, item.name))
            # Melee takes the two best, one per slot, so the same weapon can never end up
            # held in both hands.
            slots = MELEE_SLOTS if kind == "melee_weapon" else (kind,)
            for index, slot in enumerate(slots):
                loadout[slot] = best[index] if index < len(best) else None
        return loadout

    def pending_upgrades(self) -> int:
        """How many slots `auto_equip_best` would actually change: what the button offers,
        rather than how many upgrades are lying in the bag (three swords are one upgrade)."""
        loadout = self._best_loadout()
        return sum(1 for slot, item in loadout.items() if item is not None and self.equipped[slot] != item.id)

    def auto_equip_best(self) -> list:
        """Put the best loadout on. Returns the items newly equipped, for the caller to
        report."""
        changed = []
        for slot, item in self._best_loadout().items():
            wanted = item.id if item is not None else None
            if self.equipped[slot] == wanted:
                continue
            self.equipped[slot] = wanted
            if item is not None:
                changed.append(item)
                if slot in MELEE_SLOTS or slot == "ranged_weapon":
                    self._add_to_weapon_bar(item.id)

        if self.active_melee_weapon() is None:
            self._set_active_melee(1 - self.active_melee)
        self.save_system.update("equipped", self.equipped_ids())
        return changed

    def weapon_bonus(self, ranged: bool = False) -> int:
        item = self.equipped_item("ranged_weapon") if ranged else self.active_melee_weapon()
        return item.bonus if item else 0

    def armor_bonus(self) -> int:
        """Flat damage reduction from what's worn and what's carried: a shield protects
        a little even slung on the arm, and a lot more when it's actually raised."""
        worn = self.equipped_item("armor")
        shield = self.equipped_item("offhand")
        return (worn.bonus if worn else 0) + (shield.bonus if shield else 0)

    def accessory_bonus(self, flavor: str) -> int:
        item = self.equipped_item("accessory")
        if not item:
            return 0
        if item.accessory_flavor == flavor:
            return item.bonus
        # "avarice" (legendary-only) grants both coin find and xp gain from one relic.
        if item.accessory_flavor == "avarice" and flavor in ("coinfind", "xpgain"):
            return item.bonus
        return 0

    # --- affix effects ---------------------------------------------------------
    # Weapon/armour effects come from the equipped item's rolled affixes; accessories
    # contribute through their single flavor. Helpers combine both into one value.

    def _weapon_affix(self, name: str, ranged: bool = False) -> float:
        item = self.equipped_item("ranged_weapon") if ranged else self.active_melee_weapon()
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

    def rampage_trigger(self, ranged: bool = False) -> bool:
        """Counts a landed melee hit / fired shot toward Rampage; True on the Nth that
        should land as a guaranteed, amplified crit."""
        if not self._weapon_affix("rampage", ranged):
            return False
        slot = "ranged_weapon" if ranged else "melee_weapon"
        self._rampage_streak[slot] += 1
        if self._rampage_streak[slot] >= c.Affixes.RAMPAGE_EVERY_N_HITS:
            self._rampage_streak[slot] = 0
            return True
        return False

    def bloodlust_mult(self) -> float:
        """Bloodlust's on-kill damage buff magnitude, from whichever equipped weapon (if
        any) carries it."""
        return max(self._weapon_affix("bloodlust", False), self._weapon_affix("bloodlust", True))

    def chainstrike_frac(self, ranged: bool = False) -> float:
        return self._weapon_affix("chainstrike", ranged)

    def guardian_ward_threshold(self) -> float:
        return self._armor_affix("guardian_ward")

    def retribution_frac(self) -> float:
        return self._armor_affix("retribution")

    def coin_find_mult(self) -> float:
        return 1.0 + self.accessory_bonus("coinfind") * c.Stats.ACCESSORY_COINFIND_PER_BONUS

    def xp_gain_mult(self) -> float:
        return 1.0 + self.accessory_bonus("xpgain") * c.Stats.ACCESSORY_XP_PER_BONUS

    def loot_luck(self) -> float:
        """How far the luck accessory leans the rarity ladder up, passed to
        items.roll_rarity wherever the player's own actions roll loot."""
        return self.accessory_bonus("luck") * c.Stats.ACCESSORY_LUCK_PER_BONUS

    def pierce_count(self) -> int:
        """Each point of the pierce accessory's bonus lets a projectile pass through one
        more target, so the bonus is used raw rather than scaled by a per-point constant."""
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
            if item.id in self.potion_bar:
                self.potion_bar[self.potion_bar.index(item.id)] = None
                self._save_potion_bar()

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

    def clear_buffs(self):
        """Drop every timed buff at once. Death ends them, and so does a night's sleep:
        neither is a way to carry a potion into the next fight."""
        self.buffs = {}
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
        weakness = c.Death.DEBUFF_SPEED_MULT if self.is_weakened() else 1.0
        return base * weakness * self.buff_magnitude("swiftness", 1.0)

    def effective_max_hp(self) -> int:
        """Max health as it stands right now: what vitality has earned, cut back while the
        post-death weakness lasts. Dying takes something off you until you shake it off."""
        base = self.stats.max_hp()
        return round(base * c.Death.DEBUFF_MAX_HP_MULT) if self.is_weakened() else base

    def passive_regen_rate(self) -> float:
        """Regen from vitality and gear, the part held back by the out-of-combat delay.
        A regen potion is added on top of it in `move`, and is never delayed."""
        accessory = self.accessory_bonus("regen") * c.Stats.ACCESSORY_REGEN_PER_BONUS
        return self.stats.regen_rate() + accessory

    def buy_multiplier(self) -> float:
        return max(c.Stats.BUY_FLOOR, self.stats.buy_multiplier())

    def sell_multiplier(self) -> float:
        return min(c.Stats.SELL_CEILING, self.stats.sell_multiplier())

    def add_coins(self, amount):
        self.coins += amount
        self.save_system.update("coins", self.coins)

    def receive_damage(self, damage, source=None):
        now = time.time()
        # Spawn grace: the few seconds after arriving in the world or coming back from a
        # death, so a respawn can never chain straight into the next one.
        if now < self.invuln_until:
            get_particles().spawn_burst(self.x, self.y, c.Colors.WHITE, count=4, speed=3, life=250, size=3)
            return

        # Guardian's Ward: while its brief invulnerability window is up, nothing lands.
        if now < self.guardian_ward_invuln_until:
            get_particles().spawn_burst(self.x, self.y, (255, 215, 120), count=6, speed=3, life=250, size=3)
            return

        # Armour's dodge affix can shrug a hit off entirely.
        if self.dodge_chance() and random.random() < self.dodge_chance():
            get_particles().spawn_burst(self.x, self.y, c.Colors.WHITE, count=5, speed=3, life=250, size=3)
            return

        # A raised shield eats its share of a frontal blow before anything else looks at it.
        damage = self._absorb_with_shield(damage, source)

        attacker = _damage_source_name(source)
        if attacker:
            self.last_hit_by = attacker

        # Taking hits trains resistance and, more slowly, vitality.
        self.stats.train("resistance", c.Stats.XP_PER_DAMAGE_TAKEN)
        self.stats.train("vitality", c.Stats.XP_PER_DAMAGE_TAKEN * 0.5)
        self.max_hp = self.effective_max_hp()

        reduction = self.armor_bonus() + self.stats.damage_reduction() + int(self.buff_magnitude("stoneskin"))
        actual = max(damage - reduction, 1)
        old_hp = self.hp

        # Guardian's Ward: a hit that would actually kill instead leaves hp at the affix's
        # floor and opens the invulnerability window, then goes on cooldown. Only a lethal
        # hit, as the affix promises: triggering on any hit that merely dropped the player
        # below the floor made it a passive health floor and could even hand back hp.
        ward_threshold = self.guardian_ward_threshold()
        warded = ward_threshold > 0 and now >= self.guardian_ward_cooldown_until and old_hp - actual <= 0
        if warded:
            # Never above what the player had a moment ago: a ward that fires while they
            # are already under its floor saves them, it doesn't hand back health (which
            # would also pop a negative damage number, `lost` being what they actually lost).
            self.hp = min(old_hp, round(self.max_hp * ward_threshold))
            self.guardian_ward_invuln_until = now + c.Affixes.GUARDIAN_WARD_INVULN_S
            self.guardian_ward_cooldown_until = now + c.Affixes.GUARDIAN_WARD_COOLDOWN_S
            self.save_system.update("guardian_ward_cooldown_until", self.guardian_ward_cooldown_until)
        else:
            self.hp -= actual
        # What the player actually lost, which the ward clamp can make smaller than `actual`.
        lost = old_hp - self.hp

        self.last_damage_ms = pygame.time.get_ticks()
        play_sound("player_hurt")
        get_decals().spawn(self.x, self.y, radius=c.Decals.PLAYER_HURT_RADIUS)
        get_particles().spawn_burst(self.x, self.y, c.Colors.RED, count=8, speed=4, life=350, size=4, gravity=0.3)
        if warded:
            get_particles().spawn_burst(
                self.x, self.y, (255, 215, 120), count=22, speed=6, life=600, size=5, gravity=0.2
            )
            get_floating_text().spawn(self.x, self.y - c.Player.SIZE / 2, "Guardian's Ward!", (255, 215, 120), big=True)
        else:
            get_floating_text().spawn(self.x, self.y - c.Player.SIZE / 2, str(lost), (255, 90, 90), big=True)
        get_shake().add(c.Combat.PLAYER_HURT_SHAKE)
        get_vignette().trigger(c.Combat.PLAYER_HURT_VIGNETTE)

        # Thorns reflects flat damage back at a melee attacker, but never lands the kill.
        thorns = self.thorns_damage()
        if source is not None and thorns > 0 and getattr(source, "hp", 0) > 0:
            source.hp = max(1, source.hp - thorns)
            get_particles().spawn_burst(source.x, source.y, (220, 220, 120), count=6, speed=3, life=300, size=3)

        # Retribution reflects a fraction of the raw incoming damage, so a hard-hitting
        # attacker takes a hard-hitting reflection back; still stops short of the kill.
        retribution = self.retribution_frac()
        if source is not None and retribution > 0 and getattr(source, "hp", 0) > 0:
            reflect = max(1, int(damage * retribution))
            source.hp = max(1, source.hp - reflect)
            get_particles().spawn_burst(source.x, source.y, (255, 90, 40), count=8, speed=4, life=350, size=3)

    def gain_coins(self, amount: int):
        """Add coins from loot, boosted by the coin-find accessory."""
        self.add_coins(round(amount * self.coin_find_mult()))

    def is_weakened(self) -> bool:
        """True while the post-death weakness from apply_death_penalty is still active."""
        return time.time() < self.death_debuff_until

    def weakness_remaining(self) -> float:
        """Seconds left on the post-death weakness, for the HUD chip. 0 when not weakened."""
        return max(0.0, self.death_debuff_until - time.time())

    def apply_weakness(self, duration_s: float):
        """Start (or extend) the weakness the HUD shows as "Weakened". Dying is one source,
        an angry shrine is the other; both run through this so there is a single timer."""
        self.death_debuff_until = max(self.death_debuff_until, time.time() + duration_s)
        self.save_system.update("death_debuff_until", self.death_debuff_until)
        self.max_hp = self.effective_max_hp()

    def clear_death_debuff(self):
        """End the post-death weakness early, the way a night at a fire or an inn would."""
        self.death_debuff_until = 0.0
        self.save_system.update("death_debuff_until", self.death_debuff_until)

    def damage_multiplier(self) -> float:
        weakness = c.Death.DEBUFF_DAMAGE_MULT if self.is_weakened() else 1.0
        return weakness * self.buff_magnitude("strength", 1.0) * self.buff_magnitude("bloodlust", 1.0)

    def apply_death_penalty(self) -> int:
        """Dock a share of coins and start the post-respawn weakness timer. Returns the
        number of coins lost, for the game-over screen to report."""
        loss = int(self.coins * c.Death.COIN_LOSS_PCT)
        self.add_coins(-loss)
        # Whatever was coursing through the player's veins died with them.
        self.clear_buffs()
        self.apply_weakness(c.Death.DEBUFF_DURATION_S)
        self.guard = c.Shield.GUARD_MAX
        self.guard_broken_until_ms = 0
        return loss

    def gear(self) -> dict:
        """What the equipped items look like on the character, for draw_human: a weapon
        per hand (shape from its archetype), an armour ring, an accessory gem. Colours
        come from the item itself, borders from its rarity."""
        gear = {}
        # The melee weapon drawn in hand is the one that would swing, not both of them:
        # the spare is carried, not held.
        for hand, item in (("melee", self.active_melee_weapon()), ("ranged", self.equipped_item("ranged_weapon"))):
            if item is not None:
                gear[hand] = {
                    "kind": c.weapon_archetype(item.name).name,
                    "color": item.color,
                    "outline": _item_outline(item),
                }
        for slot in ("armor", "accessory"):
            item = self.equipped_item(slot)
            if item is not None:
                gear[slot] = {"color": item.color, "outline": _item_outline(item)}
        shield = self.equipped_item("offhand")
        if shield is not None:
            gear["offhand"] = {
                "color": shield.color,
                "outline": _item_outline(shield),
                # Raised, it swings across the front of the body, which is the only
                # readout the player gets that the block is actually up.
                "raised": self.blocking,
            }
        return gear

    def grant_spawn_grace(self):
        """Open the untouchable window the player arrives in the world with."""
        self.invuln_until = time.time() + c.Death.SPAWN_GRACE_S

    def end_spawn_grace(self):
        """Swinging or shooting spends the window: it is there to get the player out of
        whatever killed them, not to let them open a fight for free."""
        self.invuln_until = 0.0

    def _draw_spawn_grace(self, screen):
        """The window is worth nothing if the player can't see it. A ring pulsing round the
        body, fading as the last of it runs out, so its end is read rather than discovered."""
        left = self.invuln_until - time.time()
        if left <= 0:
            return
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 90.0)
        alpha = int(min(left / c.Death.SPAWN_GRACE_S, 1.0) * (90 + 90 * pulse))
        radius = c.Player.SIZE // 2 + 12 + int(4 * pulse)
        halo = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(halo, (*c.Colors.WHITE, alpha), (radius + 2, radius + 2), radius, 3)
        screen.blit(halo, halo.get_rect(center=(c.Screen.ORIGIN_X, c.Screen.ORIGIN_Y)))

    def draw(self, screen):
        self._draw_spawn_grace(screen)
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
            bar_color=c.Colors.RED,
            bar_border_width=4,
            gear=self.gear(),
        )
