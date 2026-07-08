from __future__ import annotations

import re
from typing import TYPE_CHECKING, List

import core.constants as c
from core.utils import parse_response_quest_analysis
from game.entities.buildings import random_open_coordinates
from game.entities.items import Item, item_type_from_name, roll_bonus, roll_rarity
from game.quest import Quest
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from game.entities.npcs import NPC
    from game.entities.player import Player


class QuestSystem:
    def __init__(self, items, player):
        self.items: List[Item] = items
        self.player: Player = player
        self.active_quests: List[Quest] = []

    def analyze_conversation_for_quest(self, conversation_history: str) -> dict:
        """Returns {has_quest: bool, quest_description: str, item_name: str}"""
        system_prompt = (
            "You are a conversation analyzer for an RPG game. "
            "Analyze the conversation and determine whether the NPC gave the player a quest. "
            "A quest means the NPC asks the player to bring back a specific item. "
            "Reply ONLY with valid JSON, with no extra text."
        )

        json_format = (
            '{"has_quest": true/false, "quest_description": "short description",'
            ' "item_name": "item the player must fetch",'
            ' "reward_item": "item the NPC will give as reward, empty string if only coins"}'
        )
        no_quest = "{'has_quest': false, 'quest_description': '', 'item_name': '', 'reward_item': ''}"
        prompt = (
            f"Conversation:\n{conversation_history}\n\n"
            f"Analyze this conversation. Reply with this exact JSON format:\n"
            f"{json_format}\n"
            f"If there is no quest, use: {no_quest}"
        )

        response = generate_response_queued(prompt, system_prompt, "Conversation analyze")
        return parse_response_quest_analysis(response)

    def create_quest_from_analysis(self, npc: NPC, quest_info: dict):
        if not quest_info["has_quest"] or not quest_info["item_name"]:
            return

        item_name: str = quest_info["item_name"].strip()
        for article in ["the ", "a ", "an ", "some "]:
            if item_name.lower().startswith(article):
                item_name = item_name[len(article) :]
                break

        reward_item_name: str = quest_info.get("reward_item", "").strip()
        for article in ["the ", "a ", "an ", "some "]:
            if reward_item_name.lower().startswith(article):
                reward_item_name = reward_item_name[len(article) :]
                break

        quest_item = Item(*random_open_coordinates(), item_name)
        self.items.append(quest_item)

        quest = Quest(
            npc_name=npc.name,
            description=quest_info["quest_description"],
            item_name=item_name,
            item=quest_item,
            reward_item_name=reward_item_name,
        )

        npc.quest = quest
        self.active_quests.append(quest)

    def extract_and_give_reward(self, last_message: str) -> int:
        # Prefer a number explicitly tied to a coin/reward word, so we don't pick up
        # an unrelated count like "I lost 3 sheep, here are 50 coins".
        coin_match = re.search(
            r"(\d+)\s*(?:coins?|gold|pieces?)|(?:reward|coins?|gold)\D{0,15}?(\d+)",
            last_message,
            re.IGNORECASE,
        )
        if coin_match:
            reward = int(coin_match.group(1) or coin_match.group(2))
            self.player.add_coins(reward)
            return reward

        # No coin-tagged number in the text, ask the model to extract it
        system_prompt = "You are an extraction assistant. Reply only with a number."
        prompt = f"How many coins are in this text: '{last_message}'?"
        reward_str = generate_response_queued(prompt, system_prompt, "Extract reward")

        reward_str = re.sub(r"[^\d]", "", reward_str)
        if reward_str:
            reward = int(reward_str)
            if reward > 0:
                self.player.add_coins(reward)
                return reward
        return 0

    def remove_quest(self, npc: NPC):
        """Drop an NPC's quest entirely (e.g. when the quest giver dies)."""
        quest = npc.quest
        if not quest:
            return

        if quest.item in self.player.inventory:
            self.player.inventory.remove(quest.item)
        if quest.item in self.items:
            self.items.remove(quest.item)
        if quest in self.active_quests:
            self.active_quests.remove(quest)

        npc.quest = None

    def complete_quest(self, npc: NPC):
        if not npc.quest or not npc.quest.item:
            return

        quest = npc.quest

        if quest.item in self.player.inventory:
            self.player.inventory.remove(quest.item)

        # Remove item from world (in case it wasn't picked up yet)
        if quest.item in self.items:
            self.items.remove(quest.item)

        if quest.reward_item_name:
            rtype = item_type_from_name(quest.reward_item_name)
            rarity = roll_rarity(c.Rarity.QUEST_REWARD_WEIGHTS)
            rbonus = roll_bonus(rtype, rarity)
            reward_item = Item(self.player.x, self.player.y, quest.reward_item_name, rtype, rbonus, rarity)
            reward_item.picked_up = True
            self.items.append(reward_item)
            self.player.inventory.append(reward_item)

        quest.is_completed = True

        if quest in self.active_quests:
            self.active_quests.remove(quest)
