from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.entities.items import Item

# Quest types finished by a counter rather than by an item changing hands: a number of kills,
# one boss, one camp emptied, one parcel delivered. Everything that asks "is this quest done"
# reads this list, so a new counted type reaches the dialogue prompt, the hand-in check and
# the map arrow at once.
COUNTED_QUEST_TYPES = ("kill_mob", "slay_boss", "clear_camp", "deliver")


@dataclass
class Quest:
    npc_name: str
    description: str
    item_name: str
    item: Item | None = None
    is_completed: bool = False
    reward_coins: int = 0
    reward_item_name: str = ""
    # "fetch" (bring back item_name), "kill_mob" (kill kill_count of target_monster_kind),
    # "loot_mob" (kill target_monster_kind until item_name drops), "recover_stolen"
    # (item_name is held by the NPC named thief_npc_name until they're defeated),
    # "slay_boss" (defeat the boss whose quest_tag equals target_monster_kind),
    # "clear_camp" (empty the bandit camp whose POI id is target_poi_id), "steal" (take
    # item_name from the chest of the house whose id is target_building_id) or "deliver"
    # (carry item_name to the NPC named recipient_npc_name, then come back).
    quest_type: str = "fetch"
    target_monster_kind: str = ""
    # Display name of a slay_boss target. target_monster_kind stays the internal spawn
    # tag that links quest to boss; this is what the UI shows, refreshed once the boss's
    # name comes back from the LLM.
    boss_name: str = ""
    kill_count: int = 0
    kills_done: int = 0
    thief_npc_name: str = ""
    target_poi_id: str = ""
    target_building_id: str = ""
    recipient_npc_name: str = ""
    # Where a clear_camp or steal quest points on the map. Written down when the quest is
    # given: a camp and a house both stand still, and the camp may well be out in a chunk
    # nobody has loaded, so there is nothing to look the position up from later.
    target_x: float | None = None
    target_y: float | None = None

    def to_dict(self) -> dict:
        return {
            "npc_name": self.npc_name,
            "description": self.description,
            "item_name": self.item_name,
            "item_id": self.item.id if self.item else None,
            "is_completed": self.is_completed,
            "reward_coins": self.reward_coins,
            "reward_item_name": self.reward_item_name,
            "quest_type": self.quest_type,
            "target_monster_kind": self.target_monster_kind,
            "boss_name": self.boss_name,
            "kill_count": self.kill_count,
            "kills_done": self.kills_done,
            "thief_npc_name": self.thief_npc_name,
            "target_poi_id": self.target_poi_id,
            "target_building_id": self.target_building_id,
            "recipient_npc_name": self.recipient_npc_name,
            "target_x": self.target_x,
            "target_y": self.target_y,
        }

    @classmethod
    def from_dict(cls, data: dict, items_by_id: dict[str, Item]) -> Quest:
        return cls(
            npc_name=data["npc_name"],
            description=data["description"],
            item_name=data["item_name"],
            item=items_by_id.get(data["item_id"]),
            is_completed=data["is_completed"],
            reward_coins=data["reward_coins"],
            reward_item_name=data["reward_item_name"],
            quest_type=data.get("quest_type", "fetch"),
            target_monster_kind=data.get("target_monster_kind", ""),
            boss_name=data.get("boss_name", ""),
            kill_count=data.get("kill_count", 0),
            kills_done=data.get("kills_done", 0),
            thief_npc_name=data.get("thief_npc_name", ""),
            target_poi_id=data.get("target_poi_id", ""),
            target_building_id=data.get("target_building_id", ""),
            recipient_npc_name=data.get("recipient_npc_name", ""),
            target_x=data.get("target_x"),
            target_y=data.get("target_y"),
        )
