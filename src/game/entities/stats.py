from __future__ import annotations

import core.constants as c


class Stats:
    """Use-based character progression.

    Every stat starts at level 1 and gains XP from a matching action. All effects
    are pure functions of the current level, so growing a stat never requires
    migrating saved data.
    """

    def __init__(self, saved: dict | None = None):
        self.level = {name: 1 for name in c.Stats.NAMES}
        self.xp = {name: 0.0 for name in c.Stats.NAMES}
        if saved:
            self.level = {name: saved["level"][name] for name in c.Stats.NAMES}
            self.xp = {name: saved["xp"][name] for name in c.Stats.NAMES}

    def to_dict(self) -> dict:
        return {"level": self.level, "xp": self.xp}

    def xp_to_next(self, name: str) -> float:
        return c.Stats.BASE_XP * (c.Stats.XP_GROWTH ** (self.level[name] - 1))

    def train(self, name: str, amount: float) -> int:
        """Add XP to a stat, applying any level-ups. Returns the number gained."""
        self.xp[name] += amount
        gained = 0
        while self.xp[name] >= self.xp_to_next(name):
            self.xp[name] -= self.xp_to_next(name)
            self.level[name] += 1
            gained += 1
        return gained

    def attack_bonus(self) -> int:
        return (self.level["strength"] - 1) * c.Stats.STRENGTH_PER_LEVEL

    def damage_reduction(self) -> int:
        return (self.level["resistance"] - 1) * c.Stats.RESISTANCE_PER_LEVEL

    def speed_multiplier(self) -> float:
        return 1.0 + (self.level["speed"] - 1) * c.Stats.SPEED_PER_LEVEL

    def max_hp(self) -> int:
        return c.Player.HP + (self.level["vitality"] - 1) * c.Stats.VITALITY_HP_PER_LEVEL

    def regen_rate(self) -> float:
        return c.Player.REGEN_RATE + (self.level["vitality"] - 1) * c.Stats.VITALITY_REGEN_PER_LEVEL

    def buy_multiplier(self) -> float:
        return max(c.Stats.BUY_FLOOR, 1.0 - (self.level["bartering"] - 1) * c.Stats.BARTER_PER_LEVEL)

    def sell_multiplier(self) -> float:
        return min(c.Stats.SELL_CEILING, 1.0 + (self.level["bartering"] - 1) * c.Stats.BARTER_PER_LEVEL)
