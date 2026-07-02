from __future__ import annotations

import random

import core.constants as c
from game.entities.items import Item

WEAPON_LOOT_NAMES = ["Rusty Dagger", "Notched Axe", "Old Bow", "Wooden Club", "Bent Spear"]
ARMOR_LOOT_NAMES = ["Worn Shield", "Leather Vest", "Battered Helmet", "Chainmail Scraps", "Tattered Cloak"]


def open_lootbox(x, y) -> tuple[int, Item | None]:
    """Roll a lootbox's contents: coins plus a chance at a weapon or armor item."""
    coins = random.randint(c.LootBox.COIN_MIN, c.LootBox.COIN_MAX)

    item = None
    if random.random() < c.LootBox.ITEM_CHANCE:
        if random.random() < 0.5:
            name = random.choice(WEAPON_LOOT_NAMES)
            bonus = random.randint(*c.LootBox.WEAPON_BONUS_RANGE)
            item = Item(x, y, name, "weapon", bonus)
        else:
            name = random.choice(ARMOR_LOOT_NAMES)
            bonus = random.randint(*c.LootBox.ARMOR_BONUS_RANGE)
            item = Item(x, y, name, "armor", bonus)
        item.picked_up = True

    return coins, item
