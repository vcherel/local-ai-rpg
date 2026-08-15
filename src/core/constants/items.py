from dataclasses import dataclass


@dataclass(frozen=True)
class RarityTier:
    name: str
    color: tuple
    weight: float
    weapon_bonus: tuple
    armor_bonus: tuple
    accessory_bonus: tuple
    price_mult: float


@dataclass(frozen=True)
class Rarity:
    TIERS: tuple = (
        RarityTier("common", (200, 200, 200), 50, (1, 2), (1, 1), (1, 2), 1.0),
        RarityTier("uncommon", (96, 200, 96), 27, (3, 4), (2, 2), (3, 4), 1.5),
        RarityTier("rare", (90, 150, 255), 14, (5, 7), (3, 3), (5, 7), 2.5),
        RarityTier("epic", (190, 105, 240), 7, (8, 10), (4, 5), (8, 10), 4.0),
        # Weight kept low on purpose: a legendary should feel like an event, not a
        # regular find. Its power comes from a signature effect (Affixes) rather than
        # from showing up often.
        RarityTier("legendary", (255, 150, 40), 0.5, (11, 14), (6, 7), (11, 14), 6.0),
    )
    # Quest rewards skip the low tiers so completing a quest always feels worth it, but
    # legendary still stays a rare highlight rather than the default quest payout.
    QUEST_REWARD_WEIGHTS: tuple = (0, 0, 60, 30, 3)


@dataclass(frozen=True)
class LootBox:
    # Chance a slain monster drops a lootbox.
    DROP_CHANCE: float = 0.2
    COIN_MIN: int = 3
    COIN_MAX: int = 12
    # Chance the box also contains an item on top of coins, indexed by rarity tier
    # (common..legendary), so a legendary box is far less likely to be coins only.
    ITEM_CHANCE_BY_TIER: tuple = (0.35, 0.45, 0.60, 0.80, 1.0)
    # Item type roll weights (weapon, armor, accessory, ammo, potion), indexed by rarity
    # tier. Common stays an even split; higher tiers skew hard toward gear so a legendary
    # box is unlikely to hand back "just" a stack of arrows or a potion.
    TYPE_WEIGHTS_BY_TIER: tuple = (
        (1, 1, 1, 1, 1),
        (2, 2, 2, 1, 1),
        (3, 3, 3, 1, 1),
        (4, 4, 4, 1, 1),
        (5, 5, 5, 1, 1),
    )


@dataclass(frozen=True)
class Potions:
    """Drinkable consumables (item_type "potion"). Every table is indexed by rarity
    tier (common..legendary), so a legendary flask of the same name is simply stronger.

    "heal" restores hp on the spot; the other four start a timed buff held on the
    player (`Player.buffs`) and read back by the matching multiplier helpers.
    """

    HEAL_FRAC: tuple = (0.25, 0.40, 0.55, 0.70, 0.90)  # fraction of max hp restored at once
    REGEN_RATE: tuple = (0.0025, 0.0035, 0.0045, 0.006, 0.008)  # extra hp/ms while active
    STRENGTH_MULT: tuple = (1.15, 1.25, 1.40, 1.60, 1.90)  # damage dealt multiplier
    SWIFTNESS_MULT: tuple = (1.12, 1.20, 1.30, 1.45, 1.60)  # move speed multiplier
    STONESKIN_REDUCTION: tuple = (2, 4, 6, 9, 13)  # flat damage reduction on top of armour

    # How long a buff lasts, in seconds. Unused by "heal", which is instant. Long enough
    # that a potion is drunk in preparation rather than in a panic: a common flask covers
    # one skirmish, a legendary one covers a boss fight and the walk into it.
    DURATION_S: tuple = (45.0, 70.0, 100.0, 140.0, 190.0)

    # Worth before the rarity multiplier, used by items.base_value for shop pricing.
    BASE_VALUE: int = 15

    # Liquid colour per effect, tinting the flask icon so a potion reads at a glance.
    COLORS = {
        "heal": (214, 62, 72),
        "regen": (92, 208, 118),
        "strength": (232, 132, 46),
        "swiftness": (88, 198, 234),
        "stoneskin": (172, 172, 188),
    }

    # Potions the player can drink straight from the HUD. The number row went to the
    # weapon bar, so the quickbar sits on the letters under the movement hand instead.
    QUICK_SLOTS: int = 4
    QUICK_KEYS: tuple = ("q", "r", "t", "y")


@dataclass(frozen=True)
class Affixes:
    """Special effects rolled onto weapons and armour, on top of their flat bonus.

    Every table is indexed by rarity tier (common..legendary); a value of 0 at the
    common tier means the affix can't roll there. COUNT_BY_TIER caps how many distinct
    affixes an item of each tier carries.
    """

    COUNT_BY_TIER: tuple = (0, 1, 1, 2, 3)

    WEAPON_POOL: tuple = ("lifesteal", "burn", "crit", "execute")
    ARMOR_POOL: tuple = ("thorns", "dodge", "regen_still")

    # Weapon affixes.
    LIFESTEAL: tuple = (0.0, 0.06, 0.09, 0.12, 0.15)  # fraction of damage dealt healed back
    BURN: tuple = (0, 2, 3, 4, 6)  # damage per burn tick
    CRIT: tuple = (0.0, 0.06, 0.09, 0.13, 0.18)  # added crit chance
    EXECUTE: tuple = (0.0, 0.08, 0.11, 0.15, 0.20)  # kill a non-boss left below this fraction of max hp

    # Burn timing is fixed; only the per-tick damage scales with rarity.
    BURN_TICKS: int = 4
    BURN_INTERVAL_MS: int = 500

    # Armour affixes.
    THORNS: tuple = (0, 2, 3, 5, 8)  # flat damage reflected to a melee attacker
    DODGE: tuple = (0.0, 0.05, 0.08, 0.12, 0.16)  # chance to take no damage from a hit
    REGEN_STILL: tuple = (0.0, 0.002, 0.003, 0.005, 0.008)  # extra hp/ms regen while standing still

    # Legendary signature effects: build-defining, not just bigger numbers. Every
    # legendary weapon/armour guarantees exactly one of these on top of its normal
    # affix rolls (roll_affixes in items.py), so a legendary always feels distinct
    # from an epic instead of just having one more line of the same pool.
    WEAPON_LEGENDARY_POOL: tuple = ("rampage", "bloodlust", "chainstrike")
    ARMOR_LEGENDARY_POOL: tuple = ("guardian_ward", "retribution")

    # Rampage: every Nth landed hit (melee) or shot fired (ranged) is a guaranteed,
    # amplified crit.
    RAMPAGE_EVERY_N_HITS: int = 4
    RAMPAGE_BONUS_MULT: float = 1.75  # extra multiplier stacked on top of the normal crit

    # Bloodlust: killing anything with this weapon buffs damage for a while, refreshed
    # (not stacked) by the next kill.
    BLOODLUST_DAMAGE_MULT: float = 1.3
    BLOODLUST_DURATION_S: float = 8.0

    # Chain Strike: a landed hit also strikes the nearest other enemy within range.
    CHAINSTRIKE_DAMAGE_FRAC: float = 0.6
    CHAINSTRIKE_RADIUS: float = 220.0

    # Guardian's Ward: a lethal-looking hit instead clamps hp at this fraction of max and
    # grants a brief window of total invulnerability, on an internal cooldown.
    GUARDIAN_WARD_HP_FRAC: float = 0.2
    GUARDIAN_WARD_INVULN_S: float = 2.0
    GUARDIAN_WARD_COOLDOWN_S: float = 45.0

    # Retribution: reflects a fraction of incoming damage back at a melee attacker
    # (before armour reduction), unlike flat Thorns this scales with how hard the hit was.
    RETRIBUTION_REFLECT_FRAC: float = 0.2
