from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.utils import frames
from game.entities.item_icons import draw_shape_with_border

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
    "cudgel",
    "pole",
    "boomerang",
    "chakram",
}
AMMO_KEYWORDS = {"arrow", "bolt"}
# What the two throwables are called. "mine" and "charge" are laid on the ground and wait;
# everything else here is lit and thrown. Which of the two an item is, is read off its name
# by `bomb_kind` and nowhere else.
BOMB_KEYWORDS = {"bomb", "grenade", "mine", "charge", "firepot"}
MINE_KEYWORDS = {"mine", "charge", "trap"}
ARMOR_KEYWORDS = {
    "armor",
    "vest",
    "helmet",
    "mail",
    "plate",
    "cloak",
    "breastplate",
    "gauntlets",
    "greaves",
}
# Shields live in their own offhand slot and are raised to block, so they are their own
# item type rather than a second kind of body armour.
SHIELD_KEYWORDS = {"shield", "buckler", "targe", "aegis", "pavise"}
POTION_KEYWORDS = {
    "potion",
    "elixir",
    "flask",
    "draught",
    "draft",
    "tonic",
    "vial",
    "brew",
    "philter",
}
ACCESSORY_KEYWORDS = {
    "ring",
    "amulet",
    "necklace",
    "charm",
    "trinket",
    "pendant",
    "talisman",
    "bracelet",
    "brooch",
}

WEAPON_COLOR = (220, 140, 40)
ARMOR_COLOR = (100, 180, 220)
ACCESSORY_COLOR = (230, 200, 60)
LOOTBOX_COLOR = (150, 100, 50)
AMMO_COLOR = (180, 140, 90)
VALUABLE_COLOR = (235, 205, 80)
# What a valuable is, read off its name: everything the world calls loot worth selling used
# to be one yellow disc, so a bag of them said nothing about what was in it. First match
# wins, and anything unrecognised is still a coin.
VALUABLE_KEYWORDS = (
    ("goblet", "goblet"),
    ("chalice", "goblet"),
    ("cup", "goblet"),
    ("flagon", "goblet"),
    ("idol", "idol"),
    ("statue", "idol"),
    ("figurine", "idol"),
    ("carving", "idol"),
    ("totem", "idol"),
    ("relic", "idol"),
    ("ingot", "ingot"),
    ("bar", "ingot"),
    ("nugget", "ingot"),
    ("ore", "ingot"),
    ("bullion", "ingot"),
    ("skull", "skull"),
    ("bone", "skull"),
    ("fang", "skull"),
    ("tooth", "skull"),
    ("horn", "skull"),
    ("crown", "crown"),
    ("circlet", "crown"),
    ("tiara", "crown"),
    ("diadem", "crown"),
    ("gem", "gem"),
    ("jewel", "gem"),
    ("crystal", "gem"),
    ("ruby", "gem"),
    ("emerald", "gem"),
    ("sapphire", "gem"),
    ("diamond", "gem"),
    ("opal", "gem"),
    ("pearl", "gem"),
    ("shard", "gem"),
)
# The metal or the stone each of them is made of, so a family of shapes is a family of
# colours too. Anything not named here takes VALUABLE_COLOR.
VALUABLE_COLORS = {
    "goblet": (214, 176, 96),
    "idol": (176, 150, 118),
    "ingot": (226, 226, 232),
    "skull": (228, 222, 204),
    "crown": (244, 214, 108),
    "gem": (120, 200, 220),
}
# A dropped purse, drawn brighter than a valuable so a pile of coins reads as money.
COIN_COLOR = (255, 215, 60)

ACCESSORY_FLAVORS = ("speed", "regen", "luck", "crit", "lifesteal", "coinfind", "xpgain", "pierce")
# Legendary-only accessory flavor: a chance to combine coin find and xp gain into one
# relic instead of picking a single flavor, its own signature effect like the weapon/
# armour legendary pools.
LEGENDARY_ACCESSORY_FLAVORS = ("avarice",)
LEGENDARY_ACCESSORY_FLAVOR_CHANCE = 0.4

# Name keyword -> potion effect. First match wins, so the order matters only in that
# every keyword here is unambiguous; anything unmatched falls back to plain healing.
POTION_EFFECT_KEYWORDS = (
    ("heal", "heal"),
    ("health", "heal"),
    ("life", "heal"),
    ("cure", "heal"),
    ("regen", "regen"),
    ("renew", "regen"),
    ("mend", "regen"),
    ("strength", "strength"),
    ("might", "strength"),
    ("rage", "strength"),
    ("fury", "strength"),
    ("power", "strength"),
    ("swift", "swiftness"),
    ("speed", "swiftness"),
    ("haste", "swiftness"),
    ("wind", "swiftness"),
    ("stone", "stoneskin"),
    ("iron", "stoneskin"),
    ("bulwark", "stoneskin"),
    ("guard", "stoneskin"),
    ("shield", "stoneskin"),
)

# How many arrows a single loot roll or shop bundle grants.
AMMO_BUNDLE = 20


def icon_shape(item_type: str, name: str) -> str:
    """The icon an item draws as. A weapon takes the shape of its archetype, so a bow, an
    axe and a dagger are told apart at a glance instead of all being one generic sword,
    and body armour gets its own cuirass rather than borrowing the shield's outline."""
    if item_type == "weapon":
        return c.weapon_archetype(name).name
    if item_type == "armor":
        return "cuirass"
    if item_type == "shield":
        return "shield"
    if item_type == "accessory":
        return "gem"
    if item_type == "lootbox":
        return "chest"
    if item_type == "ammo":
        return "arrow"
    if item_type == "potion":
        return "flask"
    if item_type == "bomb":
        return "bomb"
    return valuable_shape(name)


def valuable_shape(name: str) -> str:
    """Which of the valuables' silhouettes a piece of salvage draws as. Adding one is a row
    in VALUABLE_KEYWORDS and a row in `_SHAPES`, never a branch."""
    lower = name.lower()
    for keyword, shape in VALUABLE_KEYWORDS:
        if keyword in lower:
            return shape
    return "coin"


def bomb_kind(name: str) -> str:
    """Which of the two throwables an item is: a "mine" laid on the ground and waited on,
    or a "grenade" lit and thrown. Read off the name, so adding one is a keyword rather
    than a branch."""
    lower = name.lower()
    return "mine" if any(kw in lower for kw in MINE_KEYWORDS) else "grenade"


def item_type_from_name(name: str) -> str:
    lower = name.lower()
    if any(kw in lower for kw in AMMO_KEYWORDS):
        return "ammo"
    # Before weapons, so a "Powder Charge" is something to throw rather than something to
    # swing, and before potions, so a "Fire Pot" is not a drink.
    if any(kw in lower for kw in BOMB_KEYWORDS):
        return "bomb"
    # Potions come before weapons/armour so an "Elixir of the Blade" stays a drink.
    if any(kw in lower for kw in POTION_KEYWORDS):
        return "potion"
    if any(kw in lower for kw in WEAPON_KEYWORDS):
        return "weapon"
    # Shields before armour: a "Shield of the Bear" is something you hold, not something
    # you wear, and it goes in the offhand slot rather than the armour one.
    if any(kw in lower for kw in SHIELD_KEYWORDS):
        return "shield"
    if any(kw in lower for kw in ARMOR_KEYWORDS):
        return "armor"
    if any(kw in lower for kw in ACCESSORY_KEYWORDS):
        return "accessory"
    return "misc"


# The inventory's blocks, in the order the bag reads: what you fight with (melee, then
# ranged), what you wear, then supplies and the junk you are carrying to a merchant.
INVENTORY_SECTIONS = ("Melee", "Ranged", "Shields", "Armour", "Trinkets", "Supplies", "Valuables")


def inventory_section(item: Item) -> str:
    """Which block of the inventory an item belongs in. Melee and ranged are the same
    `item_type` and are told apart by archetype, which is why this is a function rather
    than a table keyed by type."""
    if item.item_type == "weapon":
        return "Ranged" if c.weapon_archetype(item.name).ranged else "Melee"
    return {
        "shield": "Shields",
        "armor": "Armour",
        "accessory": "Trinkets",
        "potion": "Supplies",
        "ammo": "Supplies",
        "bomb": "Supplies",
    }.get(item.item_type, "Valuables")


def roll_accessory_flavor(rarity: str) -> str:
    """Which single effect an accessory grants. A legendary has a real chance at the
    exclusive "avarice" flavor instead of the usual pool, on top of already rolling the
    biggest bonus range for its slot."""
    if rarity == "legendary" and random.random() < LEGENDARY_ACCESSORY_FLAVOR_CHANCE:
        return random.choice(LEGENDARY_ACCESSORY_FLAVORS)
    return random.choice(ACCESSORY_FLAVORS)


def rarity_tier(rarity: str) -> c.RarityTier:
    for tier in c.Rarity.TIERS:
        if tier.name == rarity:
            return tier
    raise ValueError(f"Unknown rarity: {rarity}")


def roll_rarity(weights: tuple | None = None, luck: float = 0.0) -> str:
    """Roll an item's rarity. `luck` (Player.loot_luck) makes every step up the ladder
    (1 + luck) times as likely as the one below it, so a lucky player finds better things
    rather than more of them; the shape of the curve is unchanged, it just leans up."""
    if weights is None:
        weights = tuple(tier.weight for tier in c.Rarity.TIERS)
    if luck:
        weights = tuple(weight * (1.0 + luck) ** i for i, weight in enumerate(weights))
    return random.choices(c.Rarity.TIERS, weights)[0].name


def rarity_color(rarity: str) -> tuple:
    return rarity_tier(rarity).color


def roll_bonus(item_type: str, rarity: str) -> int:
    tier = rarity_tier(rarity)
    if item_type == "weapon":
        return random.randint(*tier.weapon_bonus)
    # A shield's bonus does double duty: flat damage reduction like armour, and how much
    # of a frontal blow it turns away when raised (Player.block_fraction).
    if item_type in ("armor", "shield"):
        return random.randint(*tier.armor_bonus)
    if item_type == "accessory":
        return random.randint(*tier.accessory_bonus)
    return 0


# Per-affix rarity-indexed magnitude table, resolved from constants.
_AFFIX_TABLE = {
    "lifesteal": c.Affixes.LIFESTEAL,
    "burn": c.Affixes.BURN,
    "crit": c.Affixes.CRIT,
    "execute": c.Affixes.EXECUTE,
    "thorns": c.Affixes.THORNS,
    "dodge": c.Affixes.DODGE,
    "regen_still": c.Affixes.REGEN_STILL,
}


# Legendary-only affixes: a single fixed magnitude each, since they never roll at any
# other tier and so need no rarity-indexed table.
_LEGENDARY_AFFIX_TABLE = {
    "rampage": c.Affixes.RAMPAGE_BONUS_MULT,
    "bloodlust": c.Affixes.BLOODLUST_DAMAGE_MULT,
    "chainstrike": c.Affixes.CHAINSTRIKE_DAMAGE_FRAC,
    "guardian_ward": c.Affixes.GUARDIAN_WARD_HP_FRAC,
    "retribution": c.Affixes.RETRIBUTION_REFLECT_FRAC,
}


def roll_affixes(item_type: str, rarity: str) -> dict:
    """Roll a weapon's or armour's special effects: {affix_id: magnitude}. Other types get none.

    A legendary item guarantees exactly one signature effect from the tier-exclusive
    legendary pool (a build-defining mechanic, not just a bigger number), then fills any
    remaining affix slots from the normal shared pool as usual.
    """
    if item_type == "weapon":
        pool, legendary_pool = c.Affixes.WEAPON_POOL, c.Affixes.WEAPON_LEGENDARY_POOL
    elif item_type == "armor":
        pool, legendary_pool = c.Affixes.ARMOR_POOL, c.Affixes.ARMOR_LEGENDARY_POOL
    else:
        return {}
    tier_index = c.Rarity.TIERS.index(rarity_tier(rarity))
    count = min(c.Affixes.COUNT_BY_TIER[tier_index], len(pool))
    if count <= 0:
        return {}

    affixes = {}
    if rarity == "legendary" and legendary_pool:
        signature = random.choice(legendary_pool)
        affixes[signature] = _LEGENDARY_AFFIX_TABLE[signature]
        count -= 1

    if count > 0:
        chosen = random.sample(pool, min(count, len(pool)))
        affixes.update({affix: _AFFIX_TABLE[affix][tier_index] for affix in chosen})
    return affixes


# Human-readable one-liners for each affix, given its rolled magnitude.
def affix_label(affix: str, magnitude) -> str:
    if affix == "lifesteal":
        return f"Lifesteal {round(magnitude * 100)}%"
    if affix == "burn":
        return f"Burn {magnitude}/tick"
    if affix == "crit":
        return f"+{round(magnitude * 100)}% crit"
    if affix == "execute":
        return f"Execute below {round(magnitude * 100)}% hp"
    if affix == "thorns":
        return f"Thorns {magnitude}"
    if affix == "dodge":
        return f"+{round(magnitude * 100)}% dodge"
    if affix == "regen_still":
        return "Regen while still"
    if affix == "rampage":
        return f"Every {c.Affixes.RAMPAGE_EVERY_N_HITS}th attack is a guaranteed, amplified crit"
    if affix == "bloodlust":
        return f"Kills grant +{round((magnitude - 1) * 100)}% damage for {round(c.Affixes.BLOODLUST_DURATION_S)}s"
    if affix == "chainstrike":
        return f"Hits pulse out, striking every nearby foe for {round(magnitude * 100)}% damage"
    if affix == "guardian_ward":
        return f"A lethal hit instead leaves you at {round(magnitude * 100)}% hp, briefly invulnerable"
    if affix == "retribution":
        return f"Reflects {round(magnitude * 100)}% of damage taken"
    return affix


# Short description of an accessory flavor's effect, for tooltips.
ACCESSORY_FLAVOR_LABELS = {
    "speed": "speed",
    "regen": "regen",
    "luck": "luck (rarer loot)",
    "crit": "crit",
    "lifesteal": "lifesteal",
    "coinfind": "coin find",
    "xpgain": "xp gain",
    "pierce": "arrow pierce",
    "avarice": "avarice (coin find + xp)",
}


# --- potions ------------------------------------------------------------------

POTION_EFFECT_LABELS = {
    "heal": "healing",
    "regen": "regeneration",
    "strength": "strength",
    "swiftness": "swiftness",
    "stoneskin": "stoneskin",
    "bloodlust": "bloodlust",  # shares the buff-chip HUD with potion buffs (Player.buffs)
}

_POTION_TABLE = {
    "heal": c.Potions.HEAL_FRAC,
    "regen": c.Potions.REGEN_RATE,
    "strength": c.Potions.STRENGTH_MULT,
    "swiftness": c.Potions.SWIFTNESS_MULT,
    "stoneskin": c.Potions.STONESKIN_REDUCTION,
}


def potion_effect_from_name(name: str) -> str:
    """Which effect a potion's name promises. Anything unrecognised heals."""
    lower = name.lower()
    for keyword, effect in POTION_EFFECT_KEYWORDS:
        if keyword in lower:
            return effect
    return "heal"


def potion_magnitude(effect: str, rarity: str) -> float:
    table = _POTION_TABLE.get(effect, c.Potions.HEAL_FRAC)
    return table[c.Rarity.TIERS.index(rarity_tier(rarity))]


def potion_duration(rarity: str) -> float:
    """Buff lifetime in seconds. Meaningless for the instant heal."""
    return c.Potions.DURATION_S[c.Rarity.TIERS.index(rarity_tier(rarity))]


def potion_description(item: Item) -> str:
    """One line describing what drinking this potion does, for tooltips and shop rows."""
    effect = item.potion_effect or "heal"
    magnitude = potion_magnitude(effect, item.rarity)
    seconds = round(potion_duration(item.rarity))
    if effect == "heal":
        return f"Restores {round(magnitude * 100)}% of max HP"
    if effect == "regen":
        return f"Regenerates {round(magnitude * 1000, 1)} HP/s for {seconds}s"
    if effect == "strength":
        return f"+{round((magnitude - 1) * 100)}% damage for {seconds}s"
    if effect == "swiftness":
        return f"+{round((magnitude - 1) * 100)}% move speed for {seconds}s"
    if effect == "stoneskin":
        return f"+{int(magnitude)} armor for {seconds}s"
    return POTION_EFFECT_LABELS.get(effect, effect)


def base_value(item: Item) -> int:
    """Base sell/worth value before shop multipliers, used by the shop and inventory tooltip.

    Kept low against how much gear the world drops: a bag of salvage is pocket money, and
    a quest, a cache or a boss is what actually pays."""
    if item.item_type in ("weapon", "armor", "shield", "accessory"):
        base = max(4, item.bonus * 6)
    elif item.item_type == "ammo":
        base = 2
    elif item.item_type == "potion":
        base = c.Potions.BASE_VALUE
    elif item.item_type == "bomb":
        base = c.Bombs.BASE_VALUE
    else:  # misc valuables are worth selling in their own right
        base = 20
    return round(base * rarity_tier(item.rarity).price_mult)


class Item:
    def __init__(
        self,
        x,
        y,
        name,
        item_type: str = "misc",
        bonus: int = 0,
        rarity: str | None = None,
        accessory_flavor: str | None = None,
        quantity: int = 1,
        potion_effect: str | None = None,
    ):
        self.id = uuid.uuid4().hex
        self.x = x
        self.y = y
        self.angle = random.uniform(0, 2 * math.pi)
        self.name = name
        self.item_type = item_type
        self.bonus = bonus
        self.rarity = rarity or roll_rarity()
        self.accessory_flavor = accessory_flavor
        self.potion_effect = potion_effect
        # Ammo, potions and bombs stack; every other item keeps quantity 1.
        self.quantity = quantity
        # Rolled before the colour: a valuable's metal follows the shape its name gave it.
        self.shape = icon_shape(item_type, name)
        if item_type == "weapon":
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in WEAPON_COLOR)
        elif item_type in ("armor", "shield"):
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in ARMOR_COLOR)
        elif item_type == "accessory":
            if self.accessory_flavor is None:
                self.accessory_flavor = roll_accessory_flavor(self.rarity)
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in ACCESSORY_COLOR)
        elif item_type == "lootbox":
            self.color = LOOTBOX_COLOR
        elif item_type == "coins":
            # A purse lying on the ground. Never enters the inventory: walking into it
            # credits the coins, which is what "quantity" holds.
            self.color = COIN_COLOR
        elif item_type == "ammo":
            self.color = AMMO_COLOR
        elif item_type == "bomb":
            self.color = c.Bombs.BODY_COLOR
        elif item_type == "potion":
            if self.potion_effect is None:
                self.potion_effect = potion_effect_from_name(name)
            self.color = c.Potions.COLORS[self.potion_effect]
        else:  # misc: something to sell, drawn as whatever its name says it is
            self.color = VALUABLE_COLORS.get(self.shape, VALUABLE_COLOR)
        # Weapons and armour carry rolled special effects; everything else stays {}.
        self.affixes = roll_affixes(item_type, self.rarity)
        self.picked_up = False
        # Set by start_pop_anim for items that should hop out of a source (a smashed
        # crate, say) and settle into place instead of just appearing.
        self.pop_start_ms = None
        self.pop_from = (0.0, 0.0)
        # How fast the magnet is currently dragging this item at the player, ramped up by
        # magnet_toward while they are close and reset the moment they walk out of range.
        self.magnet_speed = 0.0

    def start_pop_anim(self, from_x, from_y):
        """Animate the item hopping out from (from_x, from_y) to its resting spot at (self.x, self.y)."""
        self.pop_start_ms = pygame.time.get_ticks()
        self.pop_from = (from_x - self.x, from_y - self.y)

    def magnet_toward(self, px, py, dt) -> bool:
        """Drag the item at the player and report whether it has reached them. The caller
        has already decided the item is in range, so this is only the pull itself: loot is
        collected by walking near it, and nothing on the ground answers a key any more.

        An item still hopping out of whatever dropped it is left alone until it settles,
        so a purse reads as falling off the body before it flies at you."""
        if self.pop_start_ms is not None:
            return False
        dx, dy = px - self.x, py - self.y
        distance = math.hypot(dx, dy)
        if distance <= c.Player.MAGNET_CATCH:
            return True
        self.magnet_speed = min(
            c.Player.MAGNET_SPEED_MAX,
            max(self.magnet_speed, c.Player.MAGNET_SPEED_START) + c.Player.MAGNET_ACCEL * dt,
        )
        step = min(distance, self.magnet_speed * frames(dt))
        self.x += dx / distance * step
        self.y += dy / distance * step
        return distance - step <= c.Player.MAGNET_CATCH

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
            "rarity": self.rarity,
            "accessory_flavor": self.accessory_flavor,
            "potion_effect": self.potion_effect,
            "quantity": self.quantity,
            "affixes": self.affixes,
            "color": list(self.color),
            "shape": self.shape,
            "picked_up": self.picked_up,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Item:
        item = cls(
            data["x"],
            data["y"],
            data["name"],
            data["item_type"],
            data["bonus"],
            data["rarity"],
            data.get("accessory_flavor"),
            data.get("quantity", 1),
            data.get("potion_effect"),
        )
        item.id = data["id"]
        item.angle = data["angle"]
        item.color = tuple(data["color"])
        # The icon is recomputed rather than restored, so a save written before weapons
        # were drawn per archetype picks up the new shapes instead of keeping its old
        # generic sword. Nothing about an item's identity lives in `shape`.
        item.shape = icon_shape(item.item_type, item.name)
        # Restore saved effects rather than the fresh ones __init__ rolled; old saves have none.
        item.affixes = data.get("affixes", {})
        item.picked_up = data["picked_up"]
        return item

    def draw(self, surface: pygame.Surface, camera: Camera = None, x=None, y=None):
        draw_x = x if x is not None else self.x
        draw_y = y if y is not None else self.y

        if self.pop_start_ms is not None:
            elapsed = pygame.time.get_ticks() - self.pop_start_ms
            if elapsed >= c.Entities.DROP_POP_MS:
                self.pop_start_ms = None
            else:
                t = elapsed / c.Entities.DROP_POP_MS
                ease = 1 - (1 - t) ** 3
                hop = math.sin(t * math.pi) * c.Entities.DROP_POP_HEIGHT
                draw_x += self.pop_from[0] * (1 - ease)
                draw_y += self.pop_from[1] * (1 - ease) - hop

        if camera:
            screen_x, screen_y = camera.world_to_screen(draw_x, draw_y)
            visual_angle = self.angle
        else:
            screen_x, screen_y = draw_x, draw_y
            visual_angle = 0

        size = c.Entities.ITEM_SIZE // 2
        border_width = 2

        if camera:
            # Loot lying in the grass has to be spotted from across the screen: it sits on a
            # shadow, rides a slow bob, and anything above common pulses a halo in its
            # rarity colour. Skipped for HUD/menu icons, which are drawn without a camera.
            phase = pygame.time.get_ticks() / 1000.0 + (self.x + self.y) * 0.01
            self._draw_ground_marker(surface, screen_x, screen_y, size, phase)
            screen_y -= round(math.sin(phase * 2.2) * c.Entities.LOOT_BOB_HEIGHT)

        center = (screen_x, screen_y)

        padding = size + border_width + 4
        surface_size = c.Entities.ITEM_SIZE + padding * 2
        item_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        item_center = (surface_size // 2, surface_size // 2)

        tier = rarity_tier(self.rarity)
        tier_index = c.Rarity.TIERS.index(tier)
        if tier_index >= 2:
            pygame.draw.circle(item_surface, (*tier.color, 70), item_center, size + 5)
        border_color = c.Colors.BLACK if self.rarity == "common" else tier.color

        draw_shape_with_border(item_surface, self.shape, item_center, size, self.color, border_width, border_color)

        rotated_surface = pygame.transform.rotate(item_surface, math.degrees(-visual_angle))
        rect = rotated_surface.get_rect(center=center)

        surface.blit(rotated_surface, rect.topleft)

    def _draw_ground_marker(self, surface: pygame.Surface, screen_x, screen_y, size, phase):
        """The shadow and pulsing halo under a dropped item, so loot reads as loot from a
        distance instead of blending into the grass."""
        tier = rarity_tier(self.rarity)
        glow_color = c.Colors.BLACK if self.rarity == "common" else tier.color
        radius = size + c.Entities.LOOT_GLOW_RADIUS
        pulse = (math.sin(phase * 2.2) + 1) / 2

        glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        alpha = round(c.Entities.LOOT_GLOW_ALPHA_MIN + pulse * c.Entities.LOOT_GLOW_ALPHA_SWING)
        pygame.draw.circle(glow, (*glow_color, alpha), (radius, radius), radius)
        pygame.draw.circle(glow, (*glow_color, min(255, alpha * 2)), (radius, radius), radius, 2)
        surface.blit(glow, (screen_x - radius, screen_y - radius))

        shadow = pygame.Surface((size * 2, size), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 70), shadow.get_rect())
        surface.blit(shadow, (screen_x - size, screen_y + size // 2))
