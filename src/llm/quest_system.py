from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING, List, Optional

import core.constants as c
from core.utils import parse_response_quest_analysis
from game.entities.buildings import random_open_coordinates
from game.entities.items import Item, item_type_from_name, roll_bonus, roll_rarity
from game.entities.npcs import NPC
from game.quest import Quest
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator

QUEST_TYPES = ("fetch", "kill_mob", "loot_mob", "recover_stolen", "slay_boss")


class QuestSystem:
    def __init__(self, items, player, npcs):
        self.items: List[Item] = items
        self.player: Player = player
        self.npcs: List[NPC] = npcs
        self.active_quests: List[Quest] = []
        # Set by Game once the world exists; slay_boss quests need it to spawn the boss.
        self.world = None

    @staticmethod
    def _strip_article(name: str) -> str:
        name = name.strip()
        for article in ["the ", "a ", "an ", "some "]:
            if name.lower().startswith(article):
                return name[len(article) :]
        return name

    @staticmethod
    def _resolve_monster_kind(hint: str) -> c.MonsterKind:
        hint_lower = hint.lower()
        for kind in c.MONSTER_KINDS:
            if kind.name.lower() in hint_lower or hint_lower in kind.name.lower():
                return kind
        return random.choices(c.MONSTER_KINDS, weights=[kind.weight for kind in c.MONSTER_KINDS])[0]

    def analyze_conversation_for_quest(self, conversation_history: str) -> dict:
        """Returns {has_quest, quest_type, quest_description, item_name, monster_hint, kill_count, reward_item}"""
        system_prompt = (
            "You are a conversation analyzer for an RPG game. "
            "Analyze the conversation and determine whether the NPC gave the player a quest. "
            "A quest is one of: "
            "fetch (bring back a specific item), "
            "kill_mob (kill a number of a kind of monster or creature), "
            "loot_mob (kill monsters of a kind until a specific item drops from them), "
            "recover_stolen (recover a specific item that was stolen from the NPC by someone else), "
            "slay_boss (defeat a single powerful named boss, beast or warlord terrorizing the area). "
            "Reply ONLY with valid JSON, with no extra text."
        )

        json_format = (
            '{"has_quest": true/false, "quest_type": "fetch/kill_mob/loot_mob/recover_stolen/slay_boss",'
            ' "quest_description": "short description",'
            ' "item_name": "item to fetch, loot or recover, empty for kill_mob",'
            ' "monster_hint": "kind of monster or creature involved, empty for fetch/recover_stolen",'
            ' "kill_count": "number to kill, only for kill_mob",'
            ' "reward_item": "item the NPC will give as reward, empty string if only coins"}'
        )
        no_quest = (
            "{'has_quest': false, 'quest_type': '', 'quest_description': '', 'item_name': '',"
            " 'monster_hint': '', 'kill_count': '', 'reward_item': ''}"
        )
        prompt = (
            f"Conversation:\n{conversation_history}\n\n"
            f"Analyze this conversation. Reply with this exact JSON format:\n"
            f"{json_format}\n"
            f"If there is no quest, use: {no_quest}"
        )

        response = generate_response_queued(prompt, system_prompt, "Conversation analyze")
        return parse_response_quest_analysis(response)

    def create_quest_from_analysis(self, npc: NPC, quest_info: dict, npc_name_generator: NPCNameGenerator):
        if not quest_info["has_quest"]:
            return

        quest_type = quest_info.get("quest_type") or "fetch"
        if quest_type not in QUEST_TYPES:
            quest_type = "fetch"

        reward_item_name = self._strip_article(quest_info.get("reward_item", ""))
        description = quest_info["quest_description"]

        if quest_type == "kill_mob":
            if not quest_info.get("monster_hint"):
                return
            kind = self._resolve_monster_kind(quest_info["monster_hint"])
            try:
                kill_count = int(quest_info.get("kill_count") or 0)
            except ValueError:
                kill_count = 0
            if kill_count <= 0:
                kill_count = random.randint(3, 5)

            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name="",
                quest_type="kill_mob",
                target_monster_kind=kind.name,
                kill_count=kill_count,
                reward_item_name=reward_item_name,
            )

        elif quest_type == "loot_mob":
            if not quest_info.get("item_name") or not quest_info.get("monster_hint"):
                return
            kind = self._resolve_monster_kind(quest_info["monster_hint"])

            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name=self._strip_article(quest_info["item_name"]),
                quest_type="loot_mob",
                target_monster_kind=kind.name,
                reward_item_name=reward_item_name,
            )

        elif quest_type == "slay_boss":
            # No world reference means we can't place the boss; drop the quest rather than
            # leave an untargetable objective.
            if self.world is None:
                return
            boss = self.world.spawn_boss_for_quest()
            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name="",
                quest_type="slay_boss",
                target_monster_kind=boss.quest_tag,
                kill_count=1,
                reward_item_name=reward_item_name,
            )

        elif quest_type == "recover_stolen":
            if not quest_info.get("item_name"):
                return
            # A fresh NPC, not one the player may have already met, so turning them
            # into a target on sight doesn't retroactively make a friendly NPC hostile.
            thief = NPC(*random_open_coordinates())
            thief.assign_name(npc_name_generator)
            thief.is_thief = True
            self.npcs.append(thief)

            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name=self._strip_article(quest_info["item_name"]),
                quest_type="recover_stolen",
                thief_npc_name=thief.name,
                reward_item_name=reward_item_name,
            )

        else:
            if not quest_info.get("item_name"):
                return
            item_name = self._strip_article(quest_info["item_name"])
            quest_item = Item(*random_open_coordinates(), item_name)
            self.items.append(quest_item)

            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name=item_name,
                item=quest_item,
                reward_item_name=reward_item_name,
            )

        npc.quest = quest
        self.active_quests.append(quest)

    def on_monster_killed(self, monster_kind_name: str, x: float, y: float) -> Optional[Item]:
        """Progress kill_mob quests and drop a matching loot_mob quest's item, if any."""
        dropped_item = None
        for quest in self.active_quests:
            if quest.target_monster_kind != monster_kind_name:
                continue
            if quest.quest_type == "kill_mob":
                quest.kills_done += 1
            elif quest.quest_type == "loot_mob" and quest.item is None:
                dropped_item = Item(x, y, quest.item_name)
                quest.item = dropped_item
        return dropped_item

    def on_boss_killed(self, boss) -> None:
        """Complete the objective of any slay_boss quest targeting this boss."""
        for quest in self.active_quests:
            if quest.quest_type == "slay_boss" and quest.target_monster_kind == boss.quest_tag:
                quest.kills_done = quest.kill_count

    def on_npc_killed(self, npc: NPC) -> Optional[Item]:
        """Drop the stolen item this NPC was carrying, if they're the thief of an active quest."""
        for quest in self.active_quests:
            if quest.quest_type == "recover_stolen" and quest.thief_npc_name == npc.name and quest.item is None:
                dropped_item = Item(npc.x, npc.y, quest.item_name)
                quest.item = dropped_item
                return dropped_item
        return None

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

        if quest.quest_type == "recover_stolen" and quest.item is None:
            thief = next((n for n in self.npcs if n.name == quest.thief_npc_name), None)
            if thief is not None:
                thief.is_thief = False

        if quest.item in self.player.inventory:
            self.player.inventory.remove(quest.item)
        if quest.item in self.items:
            self.items.remove(quest.item)
        if quest in self.active_quests:
            self.active_quests.remove(quest)

        npc.quest = None

    def _reward_weights(self, npc: NPC) -> tuple:
        """Persuasion-shifted quest reward weights, further skewed by this NPC's affinity."""
        common, uncommon, rare, epic, legendary = self.player.stats.quest_reward_weights()
        shift = min(
            c.Affinity.MAX_WEIGHT_SHIFT,
            max(0.0, npc.affinity - c.Affinity.START) * c.Affinity.WEIGHT_SHIFT_PER_POINT,
        )
        return (common, uncommon, max(0.0, rare - shift), epic, legendary + shift)

    def complete_quest(self, npc: NPC):
        quest = npc.quest
        if not quest:
            return

        if quest.quest_type in ("kill_mob", "slay_boss"):
            if quest.kills_done < quest.kill_count:
                return
        else:
            if not quest.item:
                return
            if quest.item in self.player.inventory:
                self.player.inventory.remove(quest.item)

            # Remove item from world (in case it wasn't picked up yet)
            if quest.item in self.items:
                self.items.remove(quest.item)

        if quest.reward_item_name:
            rtype = item_type_from_name(quest.reward_item_name)
            rarity = roll_rarity(self._reward_weights(npc))
            rbonus = roll_bonus(rtype, rarity)
            reward_item = Item(self.player.x, self.player.y, quest.reward_item_name, rtype, rbonus, rarity)
            reward_item.picked_up = True
            self.items.append(reward_item)
            self.player.inventory.append(reward_item)

        quest.is_completed = True

        if quest in self.active_quests:
            self.active_quests.remove(quest)
