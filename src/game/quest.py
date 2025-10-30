from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from game.entities.items import Item


@dataclass
class Quest:
    """Represents a quest given by an NPC"""
    npc_name: str
    description: str
    item_name: str
    item: Optional[Item] = None
    is_completed: bool = False
    reward_coins: int = 0
