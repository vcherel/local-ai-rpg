from __future__ import annotations

import re
from typing import List, TYPE_CHECKING

from core.utils import parse_response_quest_analysis, random_coordinates
from game.entities.items import Item
from game.quest import Quest
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from game.entities.npcs import NPC
    from game.entities.player import Player


class QuestSystem:
    """Manages quest generation, completion, and rewards"""
    def __init__(self, items, player):
        self.items: List[Item] = items
        self.player: Player = player
        self.active_quests: List[Quest] = []  # Track all active quests
    
    def analyze_conversation_for_quest(self, conversation_history: str) -> dict:
        """
        Analyze conversation to detect if a quest was given.
        Returns dict with: {has_quest: bool, quest_description: str, item_name: str}
        """
        system_prompt = (
            "Tu es un analyseur de conversation pour un jeu RPG. "
            "Analyse la conversation et détermine si le PNJ a donné une quête au joueur. "
            "Une quête implique que le PNJ demande au joueur de rapporter un objet spécifique. "
            "Réponds UNIQUEMENT avec un JSON valide, sans texte supplémentaire."
        )
        
        prompt = (
            f"Conversation:\n{conversation_history}\n\n"
            f"Analyste cette conversation. Réponds avec ce format JSON exact:\n"
            f'{{"has_quest": true/false, "quest_description": "description brève", "item_name": "nom de l\'objet"}}\n'
            f"Si pas de quête, utilise: {{'has_quest': false, 'quest_description': '', 'item_name': ''}}"
        )
        
        response = generate_response_queued(prompt, system_prompt, "Conversation analyze")
        return parse_response_quest_analysis(response)
    
    def create_quest_from_analysis(self, npc: NPC, quest_info: dict):
        """Create and register a quest item based on analysis"""
        if not quest_info['has_quest'] or not quest_info['item_name']:
            return
        
        # Clean item name
        item_name: str = quest_info['item_name'].strip()
        # Remove articles
        for article in ['le ', 'la ', "l'", 'un ', 'une ', 'des ']:
            if item_name.lower().startswith(article):
                item_name = item_name[len(article):]
                break
        
        # Create quest item
        quest_item = Item(*random_coordinates(), item_name)
        self.items.append(quest_item)
        
        # Create quest object
        quest = Quest(
            npc_name=npc.name,
            description=quest_info['quest_description'],
            item_name=item_name,
            item=quest_item
        )
        
        # Assign quest to NPC and track it
        npc.quest = quest
        self.active_quests.append(quest)
    
    def extract_and_give_reward(self, last_message: str) -> int:
        """Extract coin reward from completion message and give to player"""
        # First try direct number extraction
        match = re.search(r'\b(\d+)\b', last_message)
        if match:
            reward = int(match.group(1))
            self.player.add_coins(reward)
            return reward
        
        # Fall back to LLM extraction
        system_prompt = "Tu es un assistant d'extraction. Réponds seulement avec un nombre."
        prompt = f"Combien de pièces dans ce texte : '{last_message}' ?"
        reward_str = generate_response_queued(prompt, system_prompt, "Extract reward")
        print(f"~~~ Extracted reward : {reward_str} ~~~")
        
        reward_str = re.sub(r'[^\d]', '', reward_str)
        if reward_str:
            reward = int(reward_str)
            if reward > 0:
                self.player.add_coins(reward)
                return reward
        return 0
    
    def complete_quest(self, npc: NPC):
        """Complete quest: remove item from world/inventory and reset NPC state"""
        if not npc.quest or not npc.quest.item:
            return
        
        quest = npc.quest
        
        # Remove item from player inventory
        if quest.item in self.player.inventory:
            self.player.inventory.remove(quest.item)
        
        # Remove item from world (in case it wasn't picked up yet)
        if quest.item in self.items:
            self.items.remove(quest.item)
        
        # Mark quest as completed
        quest.is_completed = True
        
        # Remove from active quests
        if quest in self.active_quests:
            self.active_quests.remove(quest)
