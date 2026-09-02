"""Where a boss is stood up, and the name the model gives it.

Mixed into `World`, on the same entity lists. A boss arrives rather than appearing, and
none is ever stood up near the start, near a settlement's grounds or on somebody's floor:
every spawn in the game goes through `boss_spawn_ok`, the landmark guardian included. How
many exist at once and how often one is rolled are both ramps on distance from the centre.
"""

from __future__ import annotations

import math
import random
import threading
from typing import TYPE_CHECKING

import core.constants as c
from game.entities.boss import Boss
from game.entities.village_sites import settlements_near_chunk
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from game.entities.buildings import Building
    from game.entities.player import Player


class WorldBosses:
    """Boss spawning, its caps and its keep-outs, and the names the model writes for them."""

    def spawn_boss(
        self,
        x,
        y,
        template: c.BossKind = None,
        quest_tag: str | None = None,
        announce: str | None = None,
        name: str = "",
    ) -> Boss:
        """Create a boss, register it, and kick off LLM naming. `announce`, if given, is a
        message template shown once the name is ready (use '{name}' for the boss's name).

        `name` is one that has already been generated: a cave's warden is stood back up
        every time anybody walks down to its vault, and asking the model to rename the same
        creature on every visit would be a call a session for a name nobody wanted changed."""
        boss = Boss(x, y, template or random.choice(c.BOSS_KINDS), quest_tag=quest_tag)
        self.bosses.append(boss)
        if name:
            boss.set_identity(name)
        elif self.context:
            threading.Thread(target=self._generate_boss_identity, args=(boss, announce), daemon=True).start()
        return boss

    def boss_spawn_ok(self, x, y) -> bool:
        """Whether a boss may be stood up here. Every way one is spawned asks this: a boss
        never despawns, so anywhere it lands is somewhere it stays.

        A settlement is not one of those places, and neither is the ground the player starts
        on. A monster wandering into a village is a fight the militia can have; a boss
        standing in the plaza of the first town is the run over before it started.

        Distance from a settlement is measured off its grounds and against the site registry
        rather than the villages built so far, because a village a chunk away has not been
        generated yet and a boss put down next to where one is going to stand is the same
        mistake made a minute later. The world's own spawn margin is what keeps a wolf out
        of the fields; a boss is held the far side of them (`Boss.MIN_DIST_FROM_VILLAGE`)."""
        center = c.World.WORLD_SIZE // 2
        if math.hypot(x - center, y - center) < c.Boss.MIN_DIST_FROM_START:
            return False
        if self.settlement_distance(x, y) < c.Boss.MIN_DIST_FROM_VILLAGE:
            return False
        if self.building_at(x, y) is not None:
            return False
        return not self.blocked(x, y, c.MONSTER_MAX_SIZE)

    @staticmethod
    def settlement_distance(x, y) -> float:
        """How far (x, y) lies past the grounds of the nearest settlement, asked of the sites
        rather than of the villages built so far: a town three chunks out has not been
        generated yet and is no less somewhere people live. Infinite where there is nothing
        within reach at all."""
        size = c.World.CHUNK_SIZE
        chunk = (int(x // size), int(y // size))
        # The clearance in chunks, plus two for the largest grounds a town can have.
        reach = math.ceil(c.Boss.MIN_DIST_FROM_VILLAGE / size) + 2
        nearest = float("inf")
        for site_x, site_y, _, _, radius in settlements_near_chunk(*chunk, reach):
            nearest = min(nearest, math.hypot(x - site_x, y - site_y) - radius)
        return nearest

    def wild_bosses(self) -> int:
        """How many of the bosses standing in the world count towards the cap: the ones that
        are the wilds' own population rather than fixtures put somewhere for a reason
        (`Boss.counts_against_cap`)."""
        return sum(1 for boss in self.bosses if boss.counts_against_cap)

    def boss_cap(self, player: Player) -> int:
        """How many bosses the world holds at once around the player: one on the settled
        ring, up to `Boss.MAX_ACTIVE_FAR` out in the deep wilds. The same shape as the
        roaming monster cap and for the same reason. Difficulty is how many there are and
        which kinds they are, never what one of them is made of."""
        near, far = c.Boss.MAX_ACTIVE_NEAR, c.Boss.MAX_ACTIVE_FAR
        return round(near + (far - near) * self._danger_ratio(player))

    @staticmethod
    def _danger_ratio(player: Player) -> float:
        """Where the player stands between the settled ring and the deep wilds, 0 to 1."""
        center = c.World.WORLD_SIZE // 2
        distance = math.hypot(player.x - center, player.y - center)
        span = max(c.Boss.DENSITY_FAR_DISTANCE - c.Boss.ROAM_MIN_DISTANCE, 1)
        return min(max((distance - c.Boss.ROAM_MIN_DISTANCE) / span, 0.0), 1.0)

    def _spawn_landmark_boss(self):
        """A guardian waits at the ruined landmark from the very first world. It's named
        later, once the world context has finished generating.

        It goes through `boss_spawn_ok` like every other boss: the ruin is placed clear of
        the starting town, but "clear" for a building is a few hundred paces and "clear" for
        a boss is the far side of the fields, and this one is standing there from the first
        frame of the save."""
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None:
            return
        # In front of the ruin if that is allowed, and otherwise as near to it as a boss may
        # legally stand: the guardian belongs to the landmark, and the clearance it is held
        # to is measured from a settlement rather than from the stone it guards.
        spot = self._guardian_spot(landmark)
        if spot is not None:
            # It belongs to the ruin and it never leaves it, so it is not one of the bosses
            # the wilds are counted to hold around the player.
            self.spawn_boss(*spot).fixture = True

    def _guardian_spot(self, landmark: Building) -> tuple[float, float] | None:
        front = (landmark.x, landmark.y + landmark.h / 2 + 90)
        if self.boss_spawn_ok(*front):
            return front
        step = max(landmark.w, landmark.h) / 2 + 90
        return self.ring_search(landmark.x, landmark.y, step, c.Boss.GUARDIAN_SEARCH_RINGS, self.boss_spawn_ok)

    def spawn_boss_for_quest(self) -> Boss:
        """Spawn a boss out in the dangerous outer wilds as a quest hunt target.

        The band starts at `Boss.QUEST_SPAWN_MIN_DISTANCE`, well past where roaming ones
        begin, and runs outward from there. The world has no edge, so it is deliberately not
        clamped to the settled ring: hunting one is meant to be a walk past everything the
        player already knows.
        """
        center = c.World.WORLD_SIZE // 2
        x = y = center
        for _ in range(20):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(
                c.Boss.QUEST_SPAWN_MIN_DISTANCE, c.Boss.QUEST_SPAWN_MIN_DISTANCE + c.Boss.QUEST_SPAWN_BAND
            )
            x = center + math.cos(angle) * dist
            y = center + math.sin(angle) * dist
            if self.boss_spawn_ok(x, y):
                break
        # A boss never despawns, so unlike a monster it can't be left standing in a wall
        # if every roll was blocked: whatever came out of the loop is stepped clear first.
        x, y = self.free_spot_near(x, y, c.MONSTER_MAX_SIZE)
        tag = f"quest_boss_{random.randint(1000, 9999)}"
        return self.spawn_boss(x, y, quest_tag=tag)

    def _generate_boss_identity(self, boss: Boss, announce: str | None = None):
        system_prompt = (
            "You name bosses for a dark fantasy RPG. Reply with only the name, optionally as "
            "'Name, the Epithet'. No quotes, no other text."
        )
        prompt = f"World: {self.context}\nName {boss.template.flavor}. 2 to 5 words."
        text = generate_response_queued(prompt, system_prompt, "Boss naming") or ""
        boss.set_identity(text)
        self.sync_quest_boss_names()
        self.persist_world()
        if announce and self.notify:
            self.notify(announce.format(name=boss.name), c.Colors.BOSS_BAR)

    def sync_quest_boss_names(self):
        """Copy each boss's display name onto the slay_boss quest hunting it.

        The quest links to its boss by `target_monster_kind` holding the internal spawn
        tag ("quest_boss_1234"), which is never fit to show; naming happens later on a
        background thread, so the quest picks the real name up from here.
        """
        by_tag = {boss.quest_tag: boss for boss in self.bosses if boss.quest_tag}
        for npc in self.npcs:
            quest = npc.quest
            if quest is None or quest.quest_type != "slay_boss":
                continue
            boss = by_tag.get(quest.target_monster_kind)
            if boss is not None:
                quest.boss_name = boss.display_name

    def _maybe_spawn_roaming_boss(self, player: Player):
        if self.wild_bosses() >= self.boss_cap(player):
            return
        center = c.World.WORLD_SIZE // 2
        if math.hypot(player.x - center, player.y - center) < c.Boss.ROAM_MIN_DISTANCE:
            return
        ratio = self._danger_ratio(player)
        chance = c.Boss.ROAM_CHANCE_NEAR + (c.Boss.ROAM_CHANCE_FAR - c.Boss.ROAM_CHANCE_NEAR) * ratio
        chance *= c.DayNight.NIGHT_BOSS_ROAM_MULT if self.daynight.is_night else 1.0
        if random.random() > chance:
            return
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_SPAWN_MIN_DIST, c.Boss.ROAM_SPAWN_MAX_DIST)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if self.boss_spawn_ok(x, y):
                self.spawn_boss(x, y, announce="A roaming terror, {name}, prowls the wilds")
                return
