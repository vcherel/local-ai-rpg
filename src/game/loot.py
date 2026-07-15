from __future__ import annotations

import random

import core.constants as c
from game.entities.items import Item, rarity_tier, roll_bonus

WEAPON_LOOT_NAMES = ["Rusty Dagger", "Notched Axe", "Old Bow", "Wooden Club", "Bent Spear"]
ARMOR_LOOT_NAMES = ["Worn Shield", "Leather Vest", "Battered Helmet", "Chainmail Scraps", "Tattered Cloak"]
ACCESSORY_LOOT_NAMES = ["Tarnished Ring", "Cracked Amulet", "Old Talisman", "Faded Pendant", "Bent Brooch"]
AMMO_LOOT_NAME = "Arrows"


def open_lootbox(x, y, rarity: str) -> tuple[int, Item | None]:
    """Roll a lootbox's contents: coins plus a chance at a weapon, armor, accessory or ammo item.

    The box's rarity scales the coins and is inherited by the contained item.
    """
    tier = rarity_tier(rarity)
    coins = round(random.randint(c.LootBox.COIN_MIN, c.LootBox.COIN_MAX) * tier.price_mult)

    item = None
    if random.random() < c.LootBox.ITEM_CHANCE:
        item_type = random.choice(["weapon", "armor", "accessory", "ammo"])
        if item_type == "ammo":
            name = AMMO_LOOT_NAME
        else:
            name = random.choice(
                {"weapon": WEAPON_LOOT_NAMES, "armor": ARMOR_LOOT_NAMES, "accessory": ACCESSORY_LOOT_NAMES}[item_type]
            )
        item = Item(x, y, name, item_type, roll_bonus(item_type, rarity), rarity)
        item.picked_up = True

    return coins, item
