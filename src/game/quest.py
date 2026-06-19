from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

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
