from __future__ import annotations

import random
import threading
from typing import TYPE_CHECKING, List

import core.constants as c
from core.utils import random_coordinates
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.items import Item
    from game.entities.player import Player
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World:
    def __init__(self, save_system: SaveSystem, context_window: ContextMenu):
        self.floor_details = [
            (*random_coordinates(), random.choice(["stone", "flower"])) for _ in range(c.World.NB_DETAILS)
        ]

        self.npcs: List[NPC] = [NPC(*random_coordinates()) for _ in range(c.World.NB_NPCS)]
        self.monsters: List[Monster] = [Monster(*random_coordinates()) for _ in range(c.World.NB_MONSTERS)]
        self.items: List[Item] = []

        self.save_system = save_system
        self.context_window = context_window
        self.context = self.save_system.load("context", None)
        if self.context is None:
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            self.context_window.toggle(self.context)

    def _generate_context(self):
        system_prompt = (
            "You create worlds for an RPG. "
            "Each world must contain one original detail that can serve as a starting point for quests."
        )
        prompt = (
            "In a single very short sentence, describe an RPG world starting with 'The game takes place...' "
            "The sentence must contain one original detail that can serve as a starting point for adventures."
        )
        self.context = generate_response_queued(prompt, system_prompt, "Context generation")
        print(f"~~~ Generated this context: {self.context}")
        self.save_system.update("context", self.context)

        self.context_window.toggle(self.context)

    def talk_npc(self, player: Player):
        if self.context is None:
            return

        pos = player.get_pos(c.Player.INTERACTION_DISTANCE)
        for npc in self.npcs:
            if npc.distance_to_point(pos) < c.Player.INTERACTION_DISTANCE + c.Entities.NPC_SIZE // 2:
                return npc

    def handle_attack(self, player: Player, quest_system: QuestSystem):
        player.start_attack_anim()
        pos = player.get_pos(c.Player.ATTACK_REACH)

        for monster in self.monsters:
            if monster.distance_to_point(pos) < c.Player.ATTACK_REACH + c.Monster.SIZE // 2:
                if monster.receive_damage(c.Player.ATTACK_DAMAGE):
                    self.monsters.remove(monster)
                    return

        for npc in self.npcs:
            if npc.distance_to_point(pos) < c.Player.ATTACK_REACH + c.Entities.NPC_SIZE // 2:
                if npc.receive_damage(c.Player.ATTACK_DAMAGE):
                    # Drop any quest this NPC was offering so it can't become uncompletable
                    quest_system.remove_quest(npc)
                    self.npcs.remove(npc)
                    return

    def pickup_item(self, player: Player):
        for item in self.items:
            if not item.picked_up and item.distance_to_point(player.get_pos()) < c.Player.INTERACTION_DISTANCE:
                return item

    def update(self, player: Player, dt):
        for monster in self.monsters:
            monster.move(player, dt)
