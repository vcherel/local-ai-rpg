from __future__ import annotations

import random

import core.constants as c
from game.entities.items import Item, rarity_tier, roll_bonus

WEAPON_LOOT_NAMES = ["Rusty Dagger", "Notched Axe", "Old Bow", "Wooden Club", "Bent Spear"]
ARMOR_LOOT_NAMES = ["Worn Shield", "Leather Vest", "Battered Helmet", "Chainmail Scraps", "Tattered Cloak"]
ACCESSORY_LOOT_NAMES = ["Tarnished Ring", "Cracked Amulet", "Old Talisman", "Faded Pendant", "Bent Brooch"]
AMMO_LOOT_NAME = "Arrows"
# One name per potion effect; items.potion_effect_from_name reads the effect back out.
POTION_LOOT_NAMES = [
    "Healing Potion",
    "Potion of Regeneration",
    "Potion of Strength",
    "Potion of Swiftness",
    "Stoneskin Potion",
]
# Healing shows up twice as often as any single buff, so heals stay the common find.
POTION_LOOT_WEIGHTS = [6, 3, 3, 3, 3]

LOOT_TYPES = ["weapon", "armor", "accessory", "ammo", "potion"]


def _roll_loot_item(x, y, rarity: str, ammo_range: tuple[int, int]) -> Item:
    """Pick a random item of the given rarity: gear, a bundle of arrows, or a potion.

    The item type is weighted by rarity tier so a legendary roll favours weapon/armor/
    accessory over ammo or a potion, and reflects better in the arrows a stack contains.
    """
    tier = rarity_tier(rarity)
    tier_index = c.Rarity.TIERS.index(tier)
    weights = c.LootBox.TYPE_WEIGHTS_BY_TIER[tier_index]
    item_type = random.choices(LOOT_TYPES, weights)[0]
    quantity = 1
    if item_type == "ammo":
        name = AMMO_LOOT_NAME
        lo, hi = ammo_range
        quantity = round(random.randint(lo, hi) * tier.price_mult)
    elif item_type == "potion":
        name = random.choices(POTION_LOOT_NAMES, POTION_LOOT_WEIGHTS)[0]
    else:
        name = random.choice(
            {"weapon": WEAPON_LOOT_NAMES, "armor": ARMOR_LOOT_NAMES, "accessory": ACCESSORY_LOOT_NAMES}[item_type]
        )
    return Item(x, y, name, item_type, roll_bonus(item_type, rarity), rarity, quantity=quantity)


def open_lootbox(x, y, rarity: str) -> tuple[int, Item | None]:
    """Roll a lootbox's contents: coins plus a chance at a weapon, armor, accessory, ammo or potion.

    The box's rarity scales the coins and is inherited by the contained item.
    """
    tier = rarity_tier(rarity)
    tier_index = c.Rarity.TIERS.index(tier)
    coins = round(random.randint(c.LootBox.COIN_MIN, c.LootBox.COIN_MAX) * tier.price_mult)

    item = None
    if random.random() < c.LootBox.ITEM_CHANCE_BY_TIER[tier_index]:
        item = _roll_loot_item(x, y, rarity, (8, 16))
        item.picked_up = True

    return coins, item


def break_crate() -> tuple[int, Item | None]:
    """Contents of a smashed crate (shop or tavern): a few coins and a small chance of a common item.

    Coins are credited straight away; the item (if any) is left for the caller to place
    on the floor at the crate's position for the player to walk over and collect.
    """
    coins = random.randint(c.Buildings.CRATE_COIN_MIN, c.Buildings.CRATE_COIN_MAX)

    item = None
    if random.random() < c.Buildings.CRATE_ITEM_CHANCE:
        item = _roll_loot_item(0, 0, "common", (5, 10))

    return coins, item
