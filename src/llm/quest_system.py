from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING, List, Optional

import core.constants as c
from core.utils import parse_response_quest_analysis
from game.entities.buildings import random_open_coordinates
from game.entities.items import Item, item_type_from_name, roll_bonus, roll_rarity
from game.entities.npcs import NPC
from game.quest import COUNTED_QUEST_TYPES, Quest
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator

QUEST_TYPES = (
    "fetch",
    "kill_mob",
    "loot_mob",
    "recover_stolen",
    "slay_boss",
    "clear_camp",
    "steal",
    "deliver",
)


class QuestSystem:
    def __init__(self, items, player, npcs):
        self.items: List[Item] = items
        self.player: Player = player
        self.npcs: List[NPC] = npcs
        self.active_quests: List[Quest] = []
        # Set by Game once the world exists; slay_boss quests need it to spawn the boss.
        self.world = None
        # Set by Game too: a finished quest is worth writing to disk on the spot.
        self.on_complete = None

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

    def _pick_recipient(self, giver: NPC) -> Optional[NPC]:
        """Who a delivery is for: someone else already living in the world, named, still on
        speaking terms with the player, and as far from the giver as the world allows, so a
        delivery is a journey rather than a walk across the plaza."""
        candidates = [npc for npc in self.npcs if npc is not giver and npc.name and not npc.hostile]
        if not candidates:
            return None
        return max(candidates, key=lambda npc: npc.distance_to_point((giver.x, giver.y)))

    def analyze_conversation_for_quest(self, conversation_history: str) -> dict:
        """Returns {has_quest, quest_type, quest_description, item_name, monster_hint,
        kill_count, reward_item}. `has_quest` already accounts for the player's answer: a
        task the player turned down is not a quest, however clearly the NPC offered it."""
        system_prompt = (
            "You are a conversation analyzer for an RPG game. "
            "Analyze the conversation and determine whether the NPC gave the player a quest, "
            "and whether the player agreed to do it. "
            "A quest is one of: "
            "fetch (bring back a specific item), "
            "kill_mob (kill a number of a kind of monster or creature), "
            "loot_mob (kill monsters of a kind until a specific item drops from them), "
            "recover_stolen (recover a specific item that was stolen from the NPC by someone else), "
            "slay_boss (defeat a single powerful named boss, beast or warlord terrorizing the area), "
            "clear_camp (wipe out a bandit camp in the wilds), "
            "steal (steal a specific item from a neighbour's house), "
            "deliver (carry a specific item to another person and come back). "
            "Set player_accepted to false if the player refused, changed the subject, left without "
            "answering, or only listened to a rumour or a complaint. "
            "Reply ONLY with valid JSON, with no extra text."
        )

        json_format = (
            '{"has_quest": true/false, "player_accepted": true/false,'
            ' "quest_type": "fetch/kill_mob/loot_mob/recover_stolen/slay_boss/clear_camp/steal/deliver",'
            ' "quest_description": "short description",'
            ' "item_name": "item to fetch, loot, recover, steal or deliver, empty otherwise",'
            ' "monster_hint": "kind of monster or creature involved, empty for fetch/recover_stolen",'
            ' "kill_count": "number to kill, only for kill_mob",'
            ' "reward_item": "item the NPC will give as reward, empty string if only coins"}'
        )
        no_quest = (
            "{'has_quest': false, 'player_accepted': false, 'quest_type': '', 'quest_description': '',"
            " 'item_name': '', 'monster_hint': '', 'kill_count': '', 'reward_item': ''}"
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
                boss_name=boss.display_name,
                kill_count=1,
                reward_item_name=reward_item_name,
            )

        elif quest_type == "clear_camp":
            # No world to look through, or no camp still held anywhere near: drop the quest
            # rather than send the player after a place that doesn't exist.
            camp = self.world.find_bandit_camp(npc.x, npc.y) if self.world else None
            if camp is None:
                return
            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name="",
                quest_type="clear_camp",
                target_poi_id=camp.id,
                target_x=camp.x,
                target_y=camp.y,
                kill_count=1,
                reward_item_name=reward_item_name,
            )

        elif quest_type == "steal":
            if not quest_info.get("item_name"):
                return
            house = self.world.house_to_rob(npc) if self.world else None
            if house is None:
                return
            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name=self._strip_article(quest_info["item_name"]),
                quest_type="steal",
                target_building_id=house.id,
                target_x=house.x,
                target_y=house.y,
                reward_item_name=reward_item_name,
            )

        elif quest_type == "deliver":
            if not quest_info.get("item_name"):
                return
            recipient = self._pick_recipient(npc)
            if recipient is None:
                return
            # The parcel is handed over as the quest is given, so the player is carrying it
            # from the first step: a delivery is a walk, not a hunt for the thing to deliver.
            item_name = self._strip_article(quest_info["item_name"])
            parcel = Item(self.player.x, self.player.y, item_name)
            parcel.picked_up = True
            if self.player.add_item(parcel) is parcel:
                self.items.append(parcel)
            quest = Quest(
                npc_name=npc.name,
                description=description,
                item_name=item_name,
                item=parcel,
                quest_type="deliver",
                recipient_npc_name=recipient.name,
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

    def carried_item(self, quest: Quest) -> Optional[Item]:
        """The item in the player's bag that hands this quest in, or None.

        The exact object the quest spawned counts, and so does anything else by that name:
        the NPC asked for a thing, not for one particular instance of it, and matching on
        identity alone meant a player who brought back the right item was told about the
        job all over again.
        """
        if quest.item is not None and quest.item in self.player.inventory:
            return quest.item
        name = (quest.item_name or "").strip().lower()
        if not name:
            return None
        return next((item for item in self.player.inventory if item.name.strip().lower() == name), None)

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

    def on_camp_cleared(self, poi_id: str) -> None:
        """Complete the objective of any clear_camp quest sent after this camp."""
        for quest in self.active_quests:
            if quest.quest_type == "clear_camp" and quest.target_poi_id == poi_id:
                quest.kills_done = quest.kill_count

    def on_theft(self, building_id: str) -> Optional[Item]:
        """Hand over the item a steal quest was after, if this is the house it named. The
        item only exists once the chest it was supposed to be in has actually been opened."""
        for quest in self.active_quests:
            if quest.quest_type != "steal" or quest.item is not None:
                continue
            if quest.target_building_id != building_id:
                continue
            stolen = Item(self.player.x, self.player.y, quest.item_name)
            stolen.picked_up = True
            quest.item = stolen
            if self.player.add_item(stolen) is stolen:
                self.items.append(stolen)
            return stolen
        return None

    def on_delivery(self, npc: NPC) -> Optional[Quest]:
        """Hand a parcel over to the person it was for, when the player talks to them. The
        quest itself is still handed in to whoever gave it: the reward is theirs to pay."""
        for quest in self.active_quests:
            if quest.quest_type != "deliver" or quest.recipient_npc_name != npc.name:
                continue
            if quest.kills_done >= quest.kill_count or quest.item is None:
                continue
            if quest.item not in self.player.inventory:
                continue
            self.player.inventory.remove(quest.item)
            if quest.item in self.items:
                self.items.remove(quest.item)
            quest.kills_done = quest.kill_count
            return quest
        return None

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

        if quest.quest_type in COUNTED_QUEST_TYPES:
            if quest.kills_done < quest.kill_count:
                return
        else:
            handed_in = self.carried_item(quest)
            if handed_in is None:
                return
            # A stack (potions, arrows) gives up one unit rather than the whole pile.
            if handed_in.quantity > 1:
                handed_in.quantity -= 1
            else:
                self.player.inventory.remove(handed_in)
                if handed_in in self.items:
                    self.items.remove(handed_in)

            # The one the quest spawned is gone from the world too, wherever it was lying,
            # so a fetch handed in with another copy doesn't leave a duplicate out there.
            if quest.item is not None and quest.item is not handed_in and quest.item in self.items:
                self.items.remove(quest.item)

        if quest.reward_item_name:
            rtype = item_type_from_name(quest.reward_item_name)
            # A quest reward should be equippable and useful, not a do-nothing trinket;
            # anything the name can't classify becomes an accessory.
            if rtype == "misc":
                rtype = "accessory"
            rarity = roll_rarity(self._reward_weights(npc))
            rbonus = roll_bonus(rtype, rarity)
            # A single flask is a thin reward for a whole quest, so potions come in a handful.
            quantity = random.randint(2, 3) if rtype == "potion" else 1
            reward_item = Item(
                self.player.x, self.player.y, quest.reward_item_name, rtype, rbonus, rarity, quantity=quantity
            )
            reward_item.picked_up = True
            # Potions merge into a stack the player already carries; only a genuinely new
            # entry belongs in the master item list its id resolves through on reload.
            if self.player.add_item(reward_item) is reward_item:
                self.items.append(reward_item)

        quest.is_completed = True
        npc.affinity = min(c.Affinity.MAX, npc.affinity + c.Affinity.QUEST_COMPLETE_BONUS)

        if quest in self.active_quests:
            self.active_quests.remove(quest)

        if self.on_complete is not None:
            self.on_complete()
