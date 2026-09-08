from __future__ import annotations

import time

import core.constants as c


class PlayerBonuses:
    """Every number the player's gear, accessories and buffs are worth.

    Mixed into `Player`, which owns the equip slots, the buff dict and the stats these read
    through. Split out because it is one job (reading a rolled affix or a live buff and
    handing back a number) written twenty-odd times over, and because it was most of what
    stood between the movement at the top of `player.py` and the damage at the bottom.

    Nothing here decides anything: what an affix *does* when it fires lives with the blow
    that fired it (`game/combat.py`), and what a buff costs to drink lives with the potion.
    """

    def weapon_bonus(self, hand: int = 0) -> int:
        item = self.hand_weapon(hand)
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

    def _weapon_affix(self, name: str, hand: int = 0) -> float:
        item = self.hand_weapon(hand)
        return item.affixes.get(name, 0) if item else 0

    def _armor_affix(self, name: str) -> float:
        item = self.equipped_item("armor")
        return item.affixes.get(name, 0) if item else 0

    def crit_bonus(self, hand: int = 0) -> float:
        return self._weapon_affix("crit", hand) + self.accessory_bonus("crit") * c.Stats.ACCESSORY_CRIT_PER_BONUS

    def lifesteal_frac(self, hand: int = 0) -> float:
        acc = self.accessory_bonus("lifesteal") * c.Stats.ACCESSORY_LIFESTEAL_PER_BONUS
        return self._weapon_affix("lifesteal", hand) + acc

    def burn_damage(self, hand: int = 0) -> int:
        return int(self._weapon_affix("burn", hand))

    def execute_threshold(self, hand: int = 0) -> float:
        return self._weapon_affix("execute", hand)

    def thorns_damage(self) -> int:
        return int(self._armor_affix("thorns"))

    def dodge_chance(self) -> float:
        return self._armor_affix("dodge")

    def regen_still_bonus(self) -> float:
        return self._armor_affix("regen_still")

    def rampage_trigger(self, hand: int = 0) -> bool:
        """Counts a landed hit / fired shot toward Rampage; True on the Nth that should
        land as a guaranteed, amplified crit."""
        if not self._weapon_affix("rampage", hand):
            return False
        slot = self.hand_slot(hand)
        self._rampage_streak[slot] += 1
        if self._rampage_streak[slot] >= c.Affixes.RAMPAGE_EVERY_N_HITS:
            self._rampage_streak[slot] = 0
            return True
        return False

    def bloodlust_mult(self) -> float:
        """Bloodlust's on-kill damage buff magnitude, from whichever weapon in hand (if
        either) carries it."""
        return max(self._weapon_affix("bloodlust", hand) for hand in range(c.Player.HANDS))

    def chainstrike_frac(self, hand: int = 0) -> float:
        return self._weapon_affix("chainstrike", hand)

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
        return base * self.weakness_mult(c.Death.DEBUFF_SPEED_MULT) * self.buff_magnitude("swiftness", 1.0)

    def effective_max_hp(self) -> int:
        """Max health as it stands right now: what vitality has earned, cut back by however
        much of the post-death weakness is left. Read every frame in `move`, so the pool
        grows back as the weakness fades rather than snapping whole at the end of it."""
        return round(self.stats.max_hp() * self.weakness_mult(c.Death.DEBUFF_MAX_HP_MULT))

    def passive_regen_rate(self) -> float:
        """Regen from vitality and gear, the part held back by the out-of-combat delay.
        A regen potion is added on top of it in `move`, and is never delayed."""
        accessory = self.accessory_bonus("regen") * c.Stats.ACCESSORY_REGEN_PER_BONUS
        return self.stats.regen_rate() + accessory

    def buy_multiplier(self) -> float:
        return max(c.Stats.BUY_FLOOR, self.stats.buy_multiplier())

    def sell_multiplier(self) -> float:
        return min(c.Stats.SELL_CEILING, self.stats.sell_multiplier())
