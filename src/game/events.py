from __future__ import annotations

import math
import random
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

import core.constants as c
from core.utils import parse_response_quest_analysis
from game.entities.items import Item
from game.entities.npcs import NPC
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from game.entities.player import Player
    from game.world import World
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem


class EventSystem:
    """Rolls random world events on a cooldown: wandering merchants, treasure, blood nights,
    rumors and village crises. Owned by World, which supplies the state each event mutates."""

    def __init__(self, world: World, notify: Callable[[str, tuple], None]):
        self.world = world
        self.notify = notify
        self.cooldown = random.uniform(*c.Events.INTERVAL_RANGE_MS)

        self.wandering_merchant: Optional[NPC] = None
        self.merchant_timer = 0.0
        self.blood_night_timer = 0.0

    @property
    def blood_night_active(self) -> bool:
        return self.blood_night_timer > 0

    def update(self, dt, player: Player, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        self._tick_merchant(dt)
        if self.blood_night_timer > 0:
            self.blood_night_timer = max(0.0, self.blood_night_timer - dt)

        self.cooldown -= dt
        if self.cooldown > 0:
            return
        self.cooldown = random.uniform(*c.Events.INTERVAL_RANGE_MS)
        self._trigger_random_event(player, quest_system, npc_name_generator)

    # ------------------------------------------------------------------ scheduling

    def _trigger_random_event(self, player: Player, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        if self.world.context is None:
            return  # World lore isn't ready yet; every event either quotes it or needs a settled world.

        kinds = [
            ("treasure", c.Events.WEIGHT_TREASURE),
            ("rumor", c.Events.WEIGHT_RUMOR),
            ("prophetic_rumor", c.Events.WEIGHT_PROPHETIC_RUMOR),
            ("crisis", c.Events.WEIGHT_CRISIS),
        ]
        if self.wandering_merchant is None:
            kinds.append(("merchant", c.Events.WEIGHT_MERCHANT))
        if not self.blood_night_active:
            kinds.append(("blood_night", c.Events.WEIGHT_BLOOD_NIGHT))

        kind = random.choices([k for k, _ in kinds], weights=[w for _, w in kinds])[0]

        if kind == "merchant":
            self._spawn_wandering_merchant(player)
        elif kind == "treasure":
            if random.random() < c.Events.PRESAGE_CHANCE:
                threading.Thread(target=self._treasure_with_presage, args=(player,), daemon=True).start()
            else:
                self._spawn_treasure(player)
        elif kind == "blood_night":
            if random.random() < c.Events.PRESAGE_CHANCE:
                threading.Thread(target=self._blood_night_with_presage, daemon=True).start()
            else:
                self._start_blood_night()
        elif kind == "rumor":
            threading.Thread(target=self._generate_rumor, daemon=True).start()
        elif kind == "prophetic_rumor":
            threading.Thread(target=self._generate_prophetic_rumor, args=(player,), daemon=True).start()
        elif kind == "crisis":
            threading.Thread(target=self._generate_crisis, args=(quest_system, npc_name_generator), daemon=True).start()

    def _point_near_player(self, player: Player, min_dist, max_dist, radius):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(min_dist, max_dist)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.world.blocked(x, y, radius):
                return x, y
        return None

    def _generate_lore_line(self, instruction: str) -> str:
        system_prompt = "You write short atmospheric lines for an RPG world. Reply with one short sentence only."
        prompt = f"World: {self.world.context}\n{instruction}"
        text = generate_response_queued(prompt, system_prompt, "Event flavor text") or ""
        return text.strip().strip('"').split("\n")[0]

    # ------------------------------------------------------------------ wandering merchant

    def _spawn_wandering_merchant(self, player: Player):
        pos = self._point_near_player(
            player, c.Events.MERCHANT_MIN_DIST, c.Events.MERCHANT_MAX_DIST, c.Entities.NPC_SIZE / 2
        )
        if pos is None:
            return
        npc = NPC(*pos)
        npc.is_merchant = True
        npc.color = c.Colors.MERCHANT
        npc.home = pos
        self.world.npcs.append(npc)
        self.wandering_merchant = npc
        self.merchant_timer = c.Events.MERCHANT_DURATION_MS
        self.notify("A traveling merchant has set up camp nearby", c.Colors.MERCHANT)
        threading.Thread(target=self.world.generate_merchant_shop, args=(npc,), daemon=True).start()

    def _tick_merchant(self, dt):
        if self.wandering_merchant is None:
            return
        self.merchant_timer -= dt
        if self.merchant_timer <= 0:
            if self.wandering_merchant in self.world.npcs:
                self.world.npcs.remove(self.wandering_merchant)
            self.wandering_merchant = None

    # ------------------------------------------------------------------ treasure cache

    def _spawn_treasure(self, player: Player, message: str = None):
        pos = self._point_near_player(
            player, c.Events.TREASURE_MIN_DIST, c.Events.TREASURE_MAX_DIST, c.Entities.ITEM_SIZE / 2
        )
        if pos is None:
            return
        self.world.items.append(Item(*pos, "Lootbox", "lootbox"))
        self.notify(message or "Something glints in the distance...", c.Colors.YELLOW)

    def _treasure_with_presage(self, player: Player):
        text = self._generate_lore_line(
            "In one short sentence, hint that a hidden treasure lies somewhere nearby, without revealing "
            "an exact location."
        )
        self.notify(text or "Whispers speak of treasure hidden nearby...", c.Colors.YELLOW)
        time.sleep(random.uniform(*c.Events.PRESAGE_DELAY_RANGE_S))
        self._spawn_treasure(player, "The treasure appears, right where the whispers pointed")

    # ------------------------------------------------------------------ blood night

    def _start_blood_night(self):
        self.blood_night_timer = c.Events.BLOOD_NIGHT_DURATION_MS
        self.notify("A blood night falls: monsters grow bolder and loot flows more freely", c.Colors.RED)

    def _blood_night_with_presage(self):
        text = self._generate_lore_line("In one short ominous sentence, warn that a night of blood is coming soon.")
        self.notify(text or "Something dark is coming with the night...", c.Colors.RED)
        time.sleep(random.uniform(*c.Events.PRESAGE_DELAY_RANGE_S))
        self._start_blood_night()

    # ------------------------------------------------------------------ rumors

    def _generate_rumor(self):
        text = self._generate_lore_line("Generate a short rumor a villager might whisper, for flavor only.")
        if text:
            self.notify(f"Rumor: {text}", c.Colors.CYAN)

    def _generate_prophetic_rumor(self, player: Player):
        text = self._generate_lore_line(
            "Generate a short rumor claiming a treasure is hidden somewhere in this world, like a "
            "villager's gossip, without giving exact directions."
        )
        self.notify(f"Rumor: {text}" if text else "A villager's rumor mentions a hidden treasure...", c.Colors.CYAN)
        time.sleep(random.uniform(*c.Events.PROPHECY_DELAY_RANGE_S))
        self._spawn_treasure(player, "The rumor was true: treasure glints somewhere out there")

    # ------------------------------------------------------------------ village crisis

    def _generate_crisis(self, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        candidates = [npc for npc in self.world.npcs if not npc.is_merchant and not npc.has_active_quest]
        if not candidates:
            return
        npc = random.choice(candidates)
        npc.assign_name(npc_name_generator)

        system_prompt = "You create small crises for RPG villagers. Reply ONLY with valid JSON, no extra text."
        json_format = (
            '{"has_quest": true, "quest_description": "short description of the problem", '
            '"item_name": "item the player must fetch to help", '
            '"reward_item": "item given as reward, empty string if only coins"}'
        )
        prompt = (
            f"World: {self.world.context}\n"
            f"{npc.name} suddenly faces an urgent problem that an adventurer could solve by fetching an item. "
            f"Reply with this exact JSON format:\n{json_format}"
        )
        response = generate_response_queued(prompt, system_prompt, "Village crisis", raw=True)
        quest_info = parse_response_quest_analysis(response)
        quest_system.create_quest_from_analysis(npc, quest_info, npc_name_generator)
        if npc.quest:
            self.notify(f"{npc.name} has an urgent problem, seek them out", c.Colors.YELLOW)
