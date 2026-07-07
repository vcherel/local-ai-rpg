from __future__ import annotations

import random

import core.constants as c
from game.entities.items import Item, rarity_tier, roll_bonus

WEAPON_LOOT_NAMES = ["Rusty Dagger", "Notched Axe", "Old Bow", "Wooden Club", "Bent Spear"]
ARMOR_LOOT_NAMES = ["Worn Shield", "Leather Vest", "Battered Helmet", "Chainmail Scraps", "Tattered Cloak"]


def open_lootbox(x, y, rarity: str) -> tuple[int, Item | None]:
    """Roll a lootbox's contents: coins plus a chance at a weapon or armor item.

    The box's rarity scales the coins and is inherited by the contained item.
    """
    tier = rarity_tier(rarity)
    coins = round(random.randint(c.LootBox.COIN_MIN, c.LootBox.COIN_MAX) * tier.price_mult)

    item = None
    if random.random() < c.LootBox.ITEM_CHANCE:
        if random.random() < 0.5:
            name = random.choice(WEAPON_LOOT_NAMES)
            item_type = "weapon"
        else:
            name = random.choice(ARMOR_LOOT_NAMES)
            item_type = "armor"
        item = Item(x, y, name, item_type, roll_bonus(item_type, rarity), rarity)
        item.picked_up = True

    return coins, item
