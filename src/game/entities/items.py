from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING

import pygame

import core.constants as c

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
AMMO_KEYWORDS = {"arrow", "bolt"}
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


def item_type_from_name(name: str) -> str:
    lower = name.lower()
    if any(kw in lower for kw in AMMO_KEYWORDS):
        return "ammo"
    # Potions come before weapons/armour so an "Elixir of the Blade" stays a drink.
    if any(kw in lower for kw in POTION_KEYWORDS):
        return "potion"
    if any(kw in lower for kw in WEAPON_KEYWORDS):
        return "weapon"
    if any(kw in lower for kw in ARMOR_KEYWORDS):
        return "armor"
    if any(kw in lower for kw in ACCESSORY_KEYWORDS):
        return "accessory"
    return "misc"


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


def roll_rarity(weights: tuple = None) -> str:
    if weights is None:
        weights = tuple(tier.weight for tier in c.Rarity.TIERS)
    return random.choices(c.Rarity.TIERS, weights)[0].name


def rarity_color(rarity: str) -> tuple:
    return rarity_tier(rarity).color


def roll_bonus(item_type: str, rarity: str) -> int:
    tier = rarity_tier(rarity)
    if item_type == "weapon":
        return random.randint(*tier.weapon_bonus)
    if item_type == "armor":
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
        return f"Hits also strike a nearby foe for {round(magnitude * 100)}% damage"
    if affix == "guardian_ward":
        return f"A lethal hit instead leaves you at {round(magnitude * 100)}% hp, briefly invulnerable"
    if affix == "retribution":
        return f"Reflects {round(magnitude * 100)}% of damage taken"
    return affix


# Short description of an accessory flavor's effect, for tooltips.
ACCESSORY_FLAVOR_LABELS = {
    "speed": "speed",
    "regen": "regen",
    "luck": "luck",
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


def potion_description(item: "Item") -> str:
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


def base_value(item: "Item") -> int:
    """Base sell/worth value before shop multipliers, used by the shop and inventory tooltip."""
    if item.item_type in ("weapon", "armor", "accessory"):
        base = max(5, item.bonus * 10)
    elif item.item_type == "ammo":
        base = 2
    elif item.item_type == "potion":
        base = c.Potions.BASE_VALUE
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
        rarity: str = None,
        accessory_flavor: str = None,
        quantity: int = 1,
        potion_effect: str = None,
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
        # Ammo and potions stack; every other item keeps quantity 1.
        self.quantity = quantity
        if item_type == "weapon":
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in WEAPON_COLOR)
            self.shape = "sword"
        elif item_type == "armor":
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in ARMOR_COLOR)
            self.shape = "shield"
        elif item_type == "accessory":
            if self.accessory_flavor is None:
                self.accessory_flavor = roll_accessory_flavor(self.rarity)
            self.color = tuple(max(0, min(255, v + random.randint(-20, 20))) for v in ACCESSORY_COLOR)
            self.shape = "gem"
        elif item_type == "lootbox":
            self.color = LOOTBOX_COLOR
            self.shape = "chest"
        elif item_type == "ammo":
            self.color = AMMO_COLOR
            self.shape = "arrow"
        elif item_type == "potion":
            if self.potion_effect is None:
                self.potion_effect = potion_effect_from_name(name)
            self.color = c.Potions.COLORS[self.potion_effect]
            self.shape = "flask"
        else:  # misc: a valuable to sell, drawn as a coin so it reads clearly
            self.color = VALUABLE_COLOR
            self.shape = "coin"
        # Weapons and armour carry rolled special effects; everything else stays {}.
        self.affixes = roll_affixes(item_type, self.rarity)
        self.picked_up = False
        # Set by start_pop_anim for items that should hop out of a source (a smashed
        # crate, say) and settle into place instead of just appearing.
        self.pop_start_ms = None
        self.pop_from = (0.0, 0.0)

    def start_pop_anim(self, from_x, from_y):
        """Animate the item hopping out from (from_x, from_y) to its resting spot at (self.x, self.y)."""
        self.pop_start_ms = pygame.time.get_ticks()
        self.pop_from = (from_x - self.x, from_y - self.y)

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
        item.shape = data["shape"]
        # Restore saved effects rather than the fresh ones __init__ rolled; old saves have none.
        item.affixes = data.get("affixes", {})
        item.picked_up = data["picked_up"]
        # Old saves stored misc items as random polygons; normalise them to the coin look.
        if item.item_type == "misc":
            item.color = VALUABLE_COLOR
            item.shape = "coin"
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

        center = (screen_x, screen_y)
        size = c.Entities.ITEM_SIZE // 2
        border_width = 2

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


def draw_shape_with_border(surface, shape, center, size, color, border_width, border_color=None):
    if border_color is None:
        border_color = c.Colors.BLACK
    cx, cy = center
    if shape == "circle":
        pygame.draw.circle(surface, border_color, center, size + border_width)
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
        pygame.draw.polygon(surface, color, points)
        pygame.draw.polygon(surface, border_color, points, border_width)
    elif shape == "shield":
        points = [
            (cx - size * 0.65, cy - size * 0.45),
            (cx + size * 0.65, cy - size * 0.45),
            (cx + size * 0.65, cy + size * 0.15),
            (cx, cy + size * 0.7),
            (cx - size * 0.65, cy + size * 0.15),
        ]
        pygame.draw.polygon(surface, color, points)
        pygame.draw.polygon(surface, border_color, points, border_width)
    elif shape == "gem":
        points = [
            (cx, cy - size),
            (cx + size * 0.65, cy),
            (cx, cy + size),
            (cx - size * 0.65, cy),
        ]
        pygame.draw.polygon(surface, color, points)
        pygame.draw.polygon(surface, border_color, points, border_width)
    elif shape == "arrow":
        pygame.draw.line(surface, border_color, (cx, cy - size), (cx, cy + size * 0.6), border_width + 2)
        pygame.draw.line(surface, color, (cx, cy - size), (cx, cy + size * 0.6), border_width)
        head = [(cx, cy - size), (cx - size * 0.35, cy - size * 0.35), (cx + size * 0.35, cy - size * 0.35)]
        pygame.draw.polygon(surface, color, head)
        pygame.draw.polygon(surface, border_color, head, 1)
        fletch = [
            (cx, cy + size * 0.3),
            (cx - size * 0.3, cy + size * 0.6),
            (cx, cy + size * 0.45),
            (cx + size * 0.3, cy + size * 0.6),
        ]
        pygame.draw.polygon(surface, color, fletch)
        pygame.draw.polygon(surface, border_color, fletch, 1)
    elif shape == "flask":
        # Round-bottomed bottle: `color` is the liquid, the glass and cork are fixed.
        glass = (226, 234, 240)
        body_r = size * 0.6
        body_c = (int(cx), int(cy + size * 0.28))
        neck_w = max(3, size * 0.36)
        neck = pygame.Rect(int(cx - neck_w / 2), int(cy - size * 0.85), int(neck_w), int(size * 0.8))
        pygame.draw.rect(surface, border_color, neck.inflate(border_width * 2, 0))
        pygame.draw.rect(surface, glass, neck)
        pygame.draw.circle(surface, border_color, body_c, int(body_r + border_width))
        pygame.draw.circle(surface, color, body_c, int(body_r))
        # Glint on the glass, so a filled bottle doesn't read as a plain ball.
        pygame.draw.circle(
            surface,
            glass,
            (int(cx - body_r * 0.35), int(body_c[1] - body_r * 0.35)),
            max(1, int(size * 0.13)),
        )
        cork = pygame.Rect(int(cx - neck_w * 0.85), int(cy - size * 1.1), int(neck_w * 1.7), max(3, int(size * 0.3)))
        pygame.draw.rect(surface, (168, 122, 74), cork)
        pygame.draw.rect(surface, border_color, cork, max(1, border_width - 1))
    elif shape == "coin":
        pygame.draw.circle(surface, border_color, center, size + border_width)
        pygame.draw.circle(surface, color, center, size)
        # Inner ring plus a small highlight so it reads as a minted coin, not a plain disc.
        pygame.draw.circle(surface, border_color, center, int(size * 0.62), max(1, border_width - 1))
        pygame.draw.circle(
            surface,
            tuple(min(255, v + 40) for v in color),
            (int(cx - size * 0.28), int(cy - size * 0.28)),
            max(2, size // 6),
        )
    elif shape == "chest":
        half_w, half_h = size * 0.75, size * 0.55
        rect = pygame.Rect(0, 0, half_w * 2, half_h * 2)
        rect.center = center
        pygame.draw.rect(surface, border_color, rect.inflate(border_width * 2, border_width * 2))
        pygame.draw.rect(surface, color, rect)
        lid_y = rect.top + rect.height * 0.4
        pygame.draw.line(surface, c.Colors.BLACK, (rect.left, lid_y), (rect.right, lid_y), border_width)
        pygame.draw.circle(surface, c.Colors.BLACK, (cx, int(lid_y)), max(2, size // 8))
