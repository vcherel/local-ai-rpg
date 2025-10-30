import random
import threading
from typing import List
from core.save import SaveSystem
from core.utils import random_coordinates
import core.constants as c
from game.entities import NPC, Monster, Player
from game.items import Item
from llm.llm_request_queue import generate_response_queued
from ui.context_window import ContextWindow


class World:
    def __init__(self, save_system: SaveSystem, context_window: ContextWindow):        
        # Terrain details
        self.floor_details = [
            (*random_coordinates(), random.choice(["stone", "flower"]))
            for _ in range(c.World.NB_DETAILS)
        ]

        # Entities
        self.npcs: List[NPC] = [NPC(*random_coordinates()) for _ in range(c.World.NB_NPCS)]
        self.monsters: List[Monster] = [Monster(*random_coordinates()) for _ in range(c.World.NB_MONSTERS)]
        self.items: List[Item] = []

        # Context
        self.save_system = save_system
        self.context_window = context_window
        self.context = self.save_system.load("context", None)
        if self.context is None:
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            self.context_window.toggle(self.context)

    def _generate_context(self):
        system_prompt = (
            "Tu crées des mondes pour un RPG. "
            "Chaque monde doit contenir un détail original qui peut servir de point de départ pour des quêtes."
        )
        prompt = (
            "En une seule phrase très courte, décris un monde RPG avec un ou élément intéressant pour des quêtes."
        )
        self.context = generate_response_queued(prompt, system_prompt, "Context generation")
        self.save_system.update("context", self.context)
        self.context_window.toggle(self.context)

    def talk_npc(self, player: Player):
        """Check for nearby NPCs and interact"""
        if self.context is None:
            # Context not ready yet, skip
            return
        
        for npc in self.npcs:
            if npc.distance_to_point((player.x, player.y)) < c.Player.INTERACTION_DISTANCE:
                return npc
            
    def handle_attack(self, pos):
        """Check if a creature was attacked and apply damage or remove it."""
        # TODO: unify entity classes
        for monster in self.monsters:
            if monster.distance_to_point(pos) < c.Player.ATTACK_REACH:
                if monster.receive_damage(c.Player.ATTACK_DAMAGE):
                    # Monster died
                    self.monsters.remove(monster)
                return
            
        for npc in self.npcs:
            if npc.distance_to_point(pos) < c.Player.ATTACK_REACH:
                if npc.receive_damage(c.Player.ATTACK_DAMAGE):
                    # NPC died
                    self.npcs.remove(npc)
                return
        return
    
    def pickup_item(self, player: Player):
        """Check for nearby items and pick them up"""
        for item in self.items:
            if not item.picked_up and item.distance_to_point((player.x, player.y)) < c.Player.INTERACTION_DISTANCE:
                return item
