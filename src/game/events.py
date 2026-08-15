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

RUMOR_COLOR = c.Minimap.RUMOR_COLOR


class EventSystem:
    """Rolls random world events on a cooldown: wandering merchants, treasure, blood nights,
    rumors and village crises. Owned by World, which supplies the state each event mutates.

    A rumour is not flavour text: it points at somewhere the player has never walked (or at
    a treasure it promises) and marks it on the minimap, so hearing one gives them somewhere
    to go rather than a panel to dismiss."""

    def __init__(self, world: World, notify: Callable[[str, tuple], None]):
        self.world = world
        self._notify = notify
        self.cooldown = random.uniform(*c.Events.INTERVAL_RANGE_MS)

        self.wandering_merchant: Optional[NPC] = None
        self.merchant_timer = 0.0
        self.blood_night_timer = 0.0

    @property
    def blood_night_active(self) -> bool:
        return self.blood_night_timer > 0

    @property
    def blood_intensity(self) -> float:
        """How far into the blood night the world is, 0 to 1, ramped at both ends.

        The one number behind everything the event changes: the sky tint, how fast monsters
        respawn and how freely loot drops all read it, so the night comes on and bleeds back
        out instead of snapping. Held at 1 through the middle of its duration."""
        if self.blood_night_timer <= 0:
            return 0.0
        fade = c.Events.BLOOD_NIGHT_FADE_MS
        elapsed = c.Events.BLOOD_NIGHT_DURATION_MS - self.blood_night_timer
        return max(0.0, min(1.0, elapsed / fade, self.blood_night_timer / fade))

    def notify(self, message: str, color: tuple):
        """Toast, unless the session is over. An event that waits on the LLM (every presage
        does) can finish long after the player has quit to the menu, and the toast widget it
        was handed belongs to that dead game, not to whatever is on screen now."""
        if not self.world.closed:
            self._notify(message, color)

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
        if len(self.world.bosses) < c.Boss.MAX_ACTIVE:
            kinds.append(("boss", c.Events.WEIGHT_BOSS))

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
        elif kind == "boss":
            if random.random() < c.Events.PRESAGE_CHANCE:
                threading.Thread(target=self._boss_event_with_presage, args=(player,), daemon=True).start()
            else:
                self._spawn_boss_event(player)
        elif kind == "rumor":
            threading.Thread(target=self._generate_rumor, args=(player,), daemon=True).start()
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
        self.world.start_shop_generation()

    def _tick_merchant(self, dt):
        if self.wandering_merchant is None:
            return
        self.merchant_timer -= dt
        if self.merchant_timer <= 0:
            if self.wandering_merchant in self.world.npcs:
                self.world.npcs.remove(self.wandering_merchant)
            self.wandering_merchant = None

    # ------------------------------------------------------------------ treasure cache

    def _spawn_treasure(self, player: Player, message: str = None, mark: str = ""):
        pos = self._point_near_player(
            player, c.Events.TREASURE_MIN_DIST, c.Events.TREASURE_MAX_DIST, c.Entities.ITEM_SIZE / 2
        )
        if pos is None:
            return
        self.world.items.append(Item(*pos, "Lootbox", "lootbox"))
        self.notify(message or "Something glints in the distance...", c.Colors.YELLOW)
        # Only a treasure a rumour promised gets a map mark: the promise is what makes it
        # a lead rather than a lucky find.
        if mark:
            self.world.mark_rumor(pos[0], pos[1], mark)

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

    # ------------------------------------------------------------------ boss

    def _spawn_boss_event(self, player: Player, message: str = None):
        if len(self.world.bosses) >= c.Boss.MAX_ACTIVE:
            return
        pos = self._point_near_player(
            player, c.Events.BOSS_EVENT_MIN_DIST, c.Events.BOSS_EVENT_MAX_DIST, c.MONSTER_MAX_SIZE
        )
        if pos is None:
            return
        self.world.spawn_boss(*pos, announce=message or "A monstrous presence, {name}, stirs nearby")

    def _boss_event_with_presage(self, player: Player):
        text = self._generate_lore_line(
            "In one short ominous sentence, warn that a terrible beast or boss is about to rise nearby."
        )
        self.notify(text or "The ground trembles with something monstrous...", c.Colors.BOSS_BAR)
        time.sleep(random.uniform(*c.Events.PRESAGE_DELAY_RANGE_S))
        self._spawn_boss_event(player, "{name} has risen, and it hungers")

    # ------------------------------------------------------------------ rumors

    def _generate_rumor(self, player: Player):
        """A rumour is a lead, not decoration: it names somewhere the player has never walked
        and puts it on the minimap. With nothing left unexplored nearby there is nothing to
        whisper about, so the event simply passes."""
        lead = self.world.unexplored_lead(player.x, player.y)
        if lead is None:
            return
        _, x, y, label = lead
        text = self._generate_lore_line(
            f"In at most 15 words, have a villager whisper a rumor about {label} out in the wilds."
        )
        whisper = text or f"someone speaks of {label} out in the wilds"
        self.notify(f"Rumour: {whisper} (marked on your map)", RUMOR_COLOR)
        self.world.mark_rumor(x, y, label)

    def _generate_prophetic_rumor(self, player: Player):
        text = self._generate_lore_line(
            "In at most 15 words, have a villager whisper that a treasure lies hidden out in the wilds, "
            "without giving exact directions."
        )
        self.notify(
            f"Rumour: {text or 'a treasure lies hidden somewhere out there'} (watch your map)",
            RUMOR_COLOR,
        )
        time.sleep(random.uniform(*c.Events.PROPHECY_DELAY_RANGE_S))
        self._spawn_treasure(player, "The rumor was true: treasure glints somewhere out there", mark="the treasure")

    # ------------------------------------------------------------------ village crisis

    def _village_angry(self, npc: NPC) -> bool:
        """Whether the settlement this one lives in has turned on the player. One furious
        neighbour is enough: the quest would send the player into a street that attacks them."""
        village = self.world.village_at(npc.x, npc.y)
        if village is None:
            return False
        return any(other.hostile for other in self.world.npcs if village.contains_point(other.x, other.y))

    def _generate_crisis(self, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        # Nobody who wants the player dead asks them for a favour, and neither does anyone
        # whose whole street has turned: a crisis quest from an angry village is a task that
        # can't be handed in, and this event was the last path that still handed one out.
        candidates = [
            npc
            for npc in self.world.npcs
            if not npc.is_merchant and not npc.has_active_quest and npc.can_talk and not self._village_angry(npc)
        ]
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
