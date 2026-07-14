from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from game.entities.items import Item


@dataclass
class Quest:
    npc_name: str
    description: str
    item_name: str
    item: Optional[Item] = None
    is_completed: bool = False
    reward_coins: int = 0
    reward_item_name: str = ""
    # "fetch" (bring back item_name), "kill_mob" (kill kill_count of target_monster_kind),
    # "loot_mob" (kill target_monster_kind until item_name drops), or "recover_stolen"
    # (item_name is held by the NPC named thief_npc_name until they're defeated).
    quest_type: str = "fetch"
    target_monster_kind: str = ""
    kill_count: int = 0
    kills_done: int = 0
    thief_npc_name: str = ""

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
            "kill_count": self.kill_count,
            "kills_done": self.kills_done,
            "thief_npc_name": self.thief_npc_name,
        }

    @classmethod
    def from_dict(cls, data: dict, items_by_id: Dict[str, Item]) -> Quest:
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
            kill_count=data.get("kill_count", 0),
            kills_done=data.get("kills_done", 0),
            thief_npc_name=data.get("thief_npc_name", ""),
        )
