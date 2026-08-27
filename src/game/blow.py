from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Blow:
    """How one blow landed, apart from who it landed on and for how much.

    Every path that hurts a monster or a villager (a swing, an arrow, a blast, a chain, a
    boss's slam) ends in `WorldCombat._resolve_monster_hit` or `_resolve_npc_hit`, and each
    one used to spell the same six keywords out again. They travel together and mean
    nothing apart, so they are one value.

    `kb_dir` is the (dx, dy) the blow throws along, `blocked` the collision test that shove
    is spent through, `by_player` whether the player is credited and answerable for it, and
    `source` whatever struck: only ever read for a blow the player did not land, so the
    victim knows what to turn on.
    """

    crit: bool = False
    shake: float = 0.0
    knockback: float = 0.0
    kb_dir: tuple | None = None
    blocked: Callable | None = None
    by_player: bool = True
    source: Any = None


# The blow nothing was said about: no crit, no shove, no shake, the player's own doing.
PLAIN_BLOW = Blow()
