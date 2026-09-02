"""What a settlement is made of, as slots on the ground, before anything is built.

Pure arithmetic over a seed and a size: how many buildings of which kinds a place holds,
where the ring of slots around its plaza falls, and which kind lands on which slot. Nothing
here knows about a `Village` or a `Building`, which is what lets `village_sites` ask how
big a settlement *could* get without building one.
"""

from __future__ import annotations

import math
import random

import core.constants as c


def tier_for(x, y, size: str) -> int:
    """How well defended a settlement standing here is. Distance from the world centre
    first, since that is the game's one measure of depth, nudged by how much there is
    to defend: a deep hamlet is still a hamlet and a town is worth a better wall."""
    center = c.World.WORLD_SIZE // 2
    distance = math.hypot(x - center, y - center)
    tier = sum(1 for threshold in c.Villages.TIER_DISTANCES if distance >= threshold)
    tier += c.Villages.TIER_SIZE_BONUS.get(size, 0)
    return max(0, min(c.Villages.MAX_TIER, tier))


def grounds_reach(radius: float, extent_x: float, extent_y: float, tier: int) -> float:
    """How far the grounds of a settlement of this shape and tier reach.

    A walled town's grounds run out to its wall, not to the last house inside it: the wall,
    its towers and whoever is posted on them are part of the place, so the same one answer
    decides who turns on the player, who defends it, where nothing hostile may be stood up
    and how far the trees are cut back. The stakes and the ditch outside the wall are
    counted in, since they belong to the settlement as much as the gate does.

    Takes the shape rather than a `Village` because `village_sites` has to ask how far a
    settlement would reach before there is one to ask.
    """
    if tier < c.Villages.WALL_TIER:
        return radius
    half_x = extent_x + c.Villages.WALL_MARGIN
    half_y = extent_y + c.Villages.WALL_MARGIN
    # The corner towers stand at the diagonal, further out than any side of the wall:
    # anything short of that leaves the towers and whoever is posted in them outside
    # the settlement they belong to, which is how a tower guard ended up unable to
    # take his own village's side.
    corner = math.hypot(half_x, half_y) + c.Villages.TOWER_RADIUS_BY_TIER[tier]
    outworks = max(half_x, half_y) + c.Villages.DITCH_OFFSET + c.Villages.DITCH_WIDTH
    if tier < c.Villages.DITCH_TIER:
        outworks = 0.0
    return max(radius, corner, outworks)


def composition_for(size: str, tier: int) -> dict:
    """What a settlement of this size and tier is made of.

    The size says what kind of place it is, the tier says how much of it there is: a deep
    wilds village carries the same shape as a near one with more houses in it and a second
    shop, so walking out is visible as a skyline before it is anything else. Both ends of
    each range move together, so what was a roll stays a roll."""
    composition = dict(c.Villages.COMPOSITION[size])
    extra = c.Villages.EXTRA_BUILDINGS_BY_TIER[max(0, min(tier, len(c.Villages.EXTRA_BUILDINGS_BY_TIER) - 1))]
    for kind, more in extra.items():
        low, high = composition[kind]
        composition[kind] = (low + more, high + more)
    return composition


def building_kinds(composition: dict, rng: random.Random) -> list[str]:
    """The buildings a settlement of this composition is made of, biggest first: the
    tavern and the shops take the slots nearest the plaza, the houses spread out behind."""
    kinds: list[str] = []
    for kind in ("tavern", "shop", "house"):
        low, high = composition[kind]
        kinds.extend([kind] * rng.randint(low, high))
    return kinds


def assign_slots(kinds: list[str], slots: list[tuple[float, float]]) -> list[tuple[str, tuple[float, float]]]:
    """Which slot each building takes.

    The slot list runs from the plaza outward and the kinds run biggest first, so handing
    them out in order put every tavern a town had on the same corner of the square. The
    specials are dealt first and never within `SPECIAL_MIN_GAP` of another of their own
    kind, which is what spreads the two shops and the taverns round the settlement; the
    houses then fill whatever is left, still nearest the plaza first."""
    free = list(slots)
    taken: dict[str, list[tuple[float, float]]] = {}
    placed: list[tuple[str, tuple[float, float]]] = []
    for kind in [k for k in kinds if k != "house"]:
        mine = taken.setdefault(kind, [])

        def distance(slot, mine=mine):
            return min((math.dist(slot, other) for other in mine), default=math.inf)

        # The nearest slot to the plaza that is far enough from this kind's own; if the
        # settlement is too small to hold one, whichever slot is furthest from them.
        choice = next((slot for slot in free if distance(slot) >= c.Villages.SPECIAL_MIN_GAP), None)
        if choice is None:
            choice = max(free, key=distance)
        free.remove(choice)
        mine.append(choice)
        placed.append((kind, choice))
    # Whichever runs out first stops it: there are as many houses left as there are
    # free slots only when the composition happens to fill the grid exactly.
    placed.extend(zip([k for k in kinds if k == "house"], free, strict=False))
    return placed


def plaza_slots(count: int, rng: random.Random) -> list[tuple[float, float]]:
    """Offsets from the plaza for `count` buildings: a grid centred on the village with the
    middle of it left open, ordered nearest the plaza first and jittered so the result reads
    as a settlement rather than a spreadsheet.

    The open middle is a keep-out rather than "the first slot in the list": a grid with an
    even number of columns has no centre slot at all, so dropping the nearest one deleted an
    arbitrary house and left the four around it free to reach across the well."""
    slots: list[tuple[float, float]] = []
    spare = 1
    while len(slots) < count:
        columns = max(2, math.ceil(math.sqrt(count + spare)))
        rows = math.ceil((count + spare) / columns)
        slots = []
        for row in range(rows):
            for column in range(columns):
                ox = (column - (columns - 1) / 2) * c.Villages.SLOT_W
                oy = (row - (rows - 1) / 2) * c.Villages.SLOT_H
                if abs(ox) < c.Villages.SLOT_W and abs(oy) < c.Villages.SLOT_H / 2:
                    continue
                slots.append((ox, oy))
        spare += 1

    slots.sort(key=lambda slot: math.hypot(*slot))
    jitter = c.Villages.SLOT_JITTER
    return [(ox + rng.uniform(-jitter, jitter), oy + rng.uniform(-jitter, jitter)) for ox, oy in slots[:count]]
