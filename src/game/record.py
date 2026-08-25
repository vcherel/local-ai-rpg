from __future__ import annotations

from typing import TYPE_CHECKING

import core.constants as c

if TYPE_CHECKING:
    from core.save import SaveSystem


class Record:
    """What the playthrough has added up to: how many times the player has died and how
    many quests they have handed in.

    Neither is a stat: they are not trained, they do not feed a bonus, and nothing in the
    world reads them to decide anything. They are the two numbers a player wants at the end
    of a run, which is why they live here rather than in `Stats`.

    Both pay out at milestones, and the two pay out in opposite directions. Quests pay in
    loot, because handing in the tenth errand should be worth something. Deaths pay in
    words: each milestone unlocks another tier of the canned death-screen lines
    (`Death.TAUNT_TIERS`), so the game gets more to say about you the worse you are at
    staying alive. A milestone is recorded once it has paid, so a reward is never handed
    out twice.
    """

    def __init__(self, save_system: SaveSystem):
        self.save_system = save_system
        self.deaths = save_system.load("deaths", 0)
        self.quests_done = save_system.load("quests_done", 0)
        paid = save_system.load("milestones", {})
        self.paid = {"quests": set(paid.get("quests", [])), "deaths": set(paid.get("deaths", []))}

    def _persist(self):
        self.save_system.update("deaths", self.deaths)
        self.save_system.update("quests_done", self.quests_done)
        self.save_system.update("milestones", {kind: sorted(reached) for kind, reached in self.paid.items()})

    def add_quest(self) -> tuple[int, str] | None:
        """Count a quest handed in. Returns (count, reward rarity) when that one crossed a
        milestone that has not paid yet, else None."""
        self.quests_done += 1
        reward = None
        for count, rarity in c.Milestones.QUESTS:
            if self.quests_done >= count and count not in self.paid["quests"]:
                self.paid["quests"].add(count)
                reward = (count, rarity)
        self._persist()
        return reward

    def add_death(self) -> int | None:
        """Count a death. Returns the milestone it crossed, or None: the caller uses it to
        say what the dying unlocked."""
        self.deaths += 1
        reached = None
        for count in c.Milestones.DEATHS:
            if self.deaths >= count and count not in self.paid["deaths"]:
                self.paid["deaths"].add(count)
                reached = count
        self._persist()
        return reached

    def taunt_pool(self) -> tuple:
        """Every canned death-screen line the player has unlocked. The first tier is there
        from the first death; each milestone passed adds the next one."""
        pool = list(c.Death.TAUNT_TIERS[0])
        for index, count in enumerate(c.Milestones.DEATHS, start=1):
            if index < len(c.Death.TAUNT_TIERS) and self.deaths >= count:
                pool.extend(c.Death.TAUNT_TIERS[index])
        return tuple(pool)
