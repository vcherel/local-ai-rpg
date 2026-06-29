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

    def to_dict(self) -> dict:
        return {
            "npc_name": self.npc_name,
            "description": self.description,
            "item_name": self.item_name,
            "item_id": self.item.id if self.item else None,
            "is_completed": self.is_completed,
            "reward_coins": self.reward_coins,
            "reward_item_name": self.reward_item_name,
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
        )
