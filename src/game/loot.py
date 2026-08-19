from __future__ import annotations

import random

import core.constants as c
from game.entities.items import Item, rarity_tier, roll_bonus, roll_rarity

# One name per weapon family, since the family is what the weapon plays like: the name is
# what `constants.weapon_archetype` reads the whole feel profile back out of.
WEAPON_LOOT_NAMES = [
    "Rusty Dagger",
    "Notched Axe",
    "Old Bow",
    "Wooden Club",
    "Bent Spear",
    "Iron Cudgel",
    "Carved Boomerang",
    "Ember Staff",
    "Rime Staff",
    "Storm Staff",
]
ARMOR_LOOT_NAMES = ["Leather Vest", "Battered Helmet", "Chainmail Scraps", "Tattered Cloak", "Padded Jerkin"]
SHIELD_LOOT_NAMES = ["Worn Shield", "Oak Buckler", "Banded Targe", "Dented Kite Shield", "Iron Pavise"]
# Share of armour rolls that come up as an offhand shield instead of body armour, so a
# shield is a normal find rather than something the player has to go shopping for.
SHIELD_SHARE = 0.35
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
        if item_type == "armor" and random.random() < SHIELD_SHARE:
            item_type = "shield"
        name = random.choice(
            {
                "weapon": WEAPON_LOOT_NAMES,
                "armor": ARMOR_LOOT_NAMES,
                "shield": SHIELD_LOOT_NAMES,
                "accessory": ACCESSORY_LOOT_NAMES,
            }[item_type]
        )
    return Item(x, y, name, item_type, roll_bonus(item_type, rarity), rarity, quantity=quantity)


# Asking price before the rarity multiplier, per item type, matching the 5 to 80 range
# the LLM is asked for so a fallback shop doesn't price differently from a generated one.
SHOP_BASE_PRICES = {"weapon": 30, "armor": 28, "shield": 30, "accessory": 25, "ammo": 25, "potion": 15, "misc": 20}


def roll_shop_stock(count: int) -> list[dict]:
    """Roll a merchant's stock locally, used when the LLM's list for that shop is unusable.

    Returns entries in the shape NPC.set_shop expects, so a fallback shop is stocked with
    the same item tables the world drops as loot instead of leaving the merchant empty.
    """
    stock = []
    for _ in range(count):
        item = _roll_loot_item(0, 0, roll_rarity(), (10, 20))
        base = SHOP_BASE_PRICES.get(item.item_type, 20)
        stock.append(
            {
                "name": item.name,
                "item_type": item.item_type,
                "rarity": item.rarity,
                "price": round(base * random.uniform(0.7, 1.3)),
                "quantity": item.quantity,
            }
        )
    return stock


def roll_reward_item(x, y, rarity: str) -> Item:
    """A piece of gear for a quest whose NPC promised no item of their own. Public where
    _roll_loot_item is not, because the harder quest types pay in gear whatever the
    conversation happened to say.
    """
    return _roll_loot_item(x, y, rarity, (10, 20))


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


def loot_villager(merchant: bool = False, luck: float = 0.0) -> tuple[int, Item | None]:
    """What a killed villager was carrying: their purse, and sometimes one of their own
    possessions.

    A merchant carries a merchant's purse and a better chance of something worth having,
    since their stock is the reason they are out on the street at all. Nothing here is
    generous: robbing a village is meant to be a decision with a price, not an income.
    """
    lo, hi = c.Entities.VILLAGER_COIN_RANGE
    coins = random.randint(lo, hi)
    chance = c.Entities.VILLAGER_ITEM_CHANCE
    if merchant:
        coins = round(coins * c.Entities.MERCHANT_COIN_MULT)
        chance = c.Entities.MERCHANT_ITEM_CHANCE

    item = None
    if random.random() < chance:
        item = _roll_loot_item(0, 0, roll_rarity(luck=luck) if merchant else "common", (6, 12))

    return coins, item


def open_poi_cache(luck: float = 0.0) -> tuple[int, Item | None]:
    """Contents of a wilderness point-of-interest cache (ruins or camp): better coins,
    a better chance of an item, and the item's rarity is rolled properly instead of
    staying pinned to common, since these take more effort to find than a house's crate.
    """
    coins = random.randint(c.PointsOfInterest.CACHE_COIN_MIN, c.PointsOfInterest.CACHE_COIN_MAX)

    item = None
    if random.random() < c.PointsOfInterest.CACHE_ITEM_CHANCE:
        item = _roll_loot_item(0, 0, roll_rarity(luck=luck), (10, 20))

    return coins, item
