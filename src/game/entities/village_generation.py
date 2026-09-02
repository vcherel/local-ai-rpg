"""Building one settlement: the slots turned into buildings standing on ground.

`generate_village` is the endless map\'s settlements, rolled off the site seed and kept by
`World._ensure_village`. `generate_starting_world` is the one exception to that, rolled per
playthrough and registered onto the map rather than found on it.
"""

from __future__ import annotations

import math
import random

import core.constants as c
from game.entities.buildings import Building
from game.entities.village import Village
from game.entities.village_layout import assign_slots, building_kinds, composition_for, plaza_slots, tier_for
from game.entities.village_sites import (
    clear_registered_sites,
    register_world_sites,
    settlements_near_chunk,
    worst_case_footprint,
)


def _clear_of_plaza(building: Building, center: tuple[float, float]) -> bool:
    """Push a building out until nothing it is built of covers the plaza.

    Measured off `bounds` rather than off the slot offset: a wing grows out to one side, so
    the middle of what the building actually covers is not where its main block stands, and
    an L used to reach over the well while its rect sat clear of it. Whichever axis needs
    the smaller shove is the one that gives, so a house steps off the square rather than
    being flung to the edge of the village. Returns whether the building had to move."""
    keep = c.Villages.PLAZA_RADIUS
    bounds = building.bounds
    dx = bounds.centerx - center[0]
    dy = bounds.centery - center[1]
    need_x = keep + bounds.width / 2 - abs(dx)
    need_y = keep + bounds.height / 2 - abs(dy)
    if need_x <= 0 or need_y <= 0:
        return False
    # Rounded up rather than to nearest: half a pixel of plaza left under a wall is still
    # a wall on the square.
    if need_x <= need_y:
        building.x += math.ceil(need_x) * (1 if dx >= 0 else -1)
    else:
        building.y += math.ceil(need_y) * (1 if dy >= 0 else -1)
    building.reset_geometry()
    return True


def _facing_towards_plaza(ox: float, oy: float) -> str:
    """Which wall a building at this offset from the plaza puts its door in: the one facing
    the middle of the village. A settlement whose doors all opened south read as a warehouse
    yard; doors onto the square make the plaza the street it is meant to be."""
    if abs(ox) > abs(oy):
        return "W" if ox > 0 else "E"
    return "N" if oy > 0 else "S"


def _clear_doorsteps(buildings: list[Building], center: tuple[float, float]) -> bool:
    """Push whatever is standing on somebody's doorstep off it.

    Keeping the boxes apart is not the same as leaving the doors usable: two buildings a
    clear stride apart still block each other if one of them opens onto the other's wall.
    Whichever of the pair stands further from the plaza gives way, so the settlement spreads
    outward exactly as it does when two footprints overlap. Returns whether anything moved."""
    moved = False
    for building in buildings:
        step = building.doorstep(c.Villages.DOORSTEP_CLEAR)
        if step is None:
            continue
        nx, ny = building.outward()
        for other in buildings:
            if other is building or not step.colliderect(other.bounds):
                continue
            bounds = other.bounds
            if nx:
                push = (step.right - bounds.left) if nx > 0 else (bounds.right - step.left)
            else:
                push = (step.bottom - bounds.top) if ny > 0 else (bounds.bottom - step.top)
            far = max((building, other), key=lambda b: math.hypot(b.x - center[0], b.y - center[1]))
            # The one that gives way is either shoved out of the apron or walked backwards
            # away from it, taking its own door with it.
            sign = 1 if far is other else -1
            if nx:
                far.x += round(push * nx * sign)
            else:
                far.y += round(push * ny * sign)
            far.reset_geometry()
            moved = True
    return moved


def _separate(buildings: list[Building], center: tuple[float, float], gap: int = 90):
    """Push buildings off each other and off the plaza, outward from the middle of the
    village. The plaza and the well in the middle of it belong to the settlement: a house
    standing on the well made the one thing every village has impossible to walk up to.

    The grid the slots come off is spaced for a plain rect; a building with a wing on it is
    wider than its slot, and two of them side by side used to end up sharing ground, which
    is a broken room rather than a tight street. Everything is measured off `bounds`, whose
    middle is not the building's own (x, y) once it has a wing: overlap resolved off the
    rect centres moved a pair the wrong way as often as not, which is how two Ls stayed
    interlocked however many passes ran. Each pass shoves the one further from the plaza,
    so the settlement spreads outward instead of the layout shifting off centre."""
    for _ in range(c.Villages.SEPARATE_PASSES):
        # The plaza is settled first and re-settled every pass: shoving one house off its
        # neighbour can put it back over the square, and both shoves point outward, so
        # taking them in turn settles rather than fighting.
        moved = any([_clear_of_plaza(building, center) for building in buildings])
        moved = _clear_doorsteps(buildings, center) or moved
        order = sorted(buildings, key=lambda b: math.hypot(b.x - center[0], b.y - center[1]))
        for i, first in enumerate(order):
            for second in order[i + 1 :]:
                a, b = first.bounds.inflate(gap, gap), second.bounds
                if not a.colliderect(b):
                    continue
                dx = b.centerx - a.centerx
                dy = b.centery - a.centery
                overlap_x = (a.width + b.width) / 2 - abs(dx)
                overlap_y = (a.height + b.height) / 2 - abs(dy)
                if overlap_x <= overlap_y:
                    second.x += round(math.copysign(overlap_x, dx or (second.x - first.x) or 1.0))
                else:
                    second.y += round(math.copysign(overlap_y, dy or (second.y - first.y) or 1.0))
                second.reset_geometry()
                moved = True
        if not moved:
            return


def _build(x, y, chunk, size: str, composition: dict, rng: random.Random) -> tuple[Village, list[Building]]:
    kinds = building_kinds(composition, rng)
    slots = plaza_slots(len(kinds), rng)
    buildings = []
    for kind, (ox, oy) in assign_slots(kinds, slots):
        building = Building(round(x + ox), round(y + oy), kind, facing=_facing_towards_plaza(ox, oy))
        buildings.append(building)
    _separate(buildings, (x, y))

    radius = round(max((math.hypot(b.x - x, b.y - y) for b in buildings), default=0) + c.Villages.SLOT_W / 2)
    extent_x = round(
        max((max(abs(b.bounds.left - x), abs(b.bounds.right - x)) for b in buildings), default=c.Villages.PLAZA_RADIUS)
    )
    extent_y = round(
        max((max(abs(b.bounds.top - y), abs(b.bounds.bottom - y)) for b in buildings), default=c.Villages.PLAZA_RADIUS)
    )
    # The lanes are not laid here: they run out to where the roads from the neighbouring
    # settlements stop, and a village rolled per playthrough is not on the map the roads
    # are drawn from until it is registered. Whoever puts it in the world plans them.
    village = Village(x, y, chunk, size, radius, extent_x, extent_y)
    for building in buildings:
        # Which settlement's tier lights this one's windows after dark. A building out in
        # the wilderness keeps -1 and is never lit: nobody lives in a ruin.
        building.village_tier = village.tier
    return village, buildings


def generate_village(x, y, chunk: tuple[int, int]) -> tuple[Village, list[Building]]:
    """Lay out the village that chunk (cx, cy) offers. Called once, the first time the
    player walks into range; after that the result lives in the save like the starting town."""
    rng = random.Random(f"village-layout:{chunk[0]},{chunk[1]}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS, strict=True)
    size = rng.choices(sizes, weights=weights)[0]
    # The tier is worked out before anything is laid out, because it is worth houses: it is
    # the same answer `Village` gives itself, asked one step early.
    return _build(x, y, chunk, size, composition_for(size, tier_for(x, y, size)), rng)


def generate_starting_world() -> tuple[Village, list[Building]]:
    """The village the player starts next to, plus the ruined landmark standing alone out
    in the settled ring. Rolled fresh per new game rather than seeded, so two playthroughs
    don't open on the same town.

    The spot is chosen off the water rather than wherever the angle fell: the rivers are a
    pure function of their lane, so they can be asked about before the town exists, and a
    settlement that has to be built round a river bend is one the river was never asked
    about. Once it stands it is registered (`register_world_sites`), which is what makes
    everything else laid out from the sites bow around it."""
    # Imported here rather than at the top: the terrain is laid out from the village sites
    # this module owns, so it is the terrain that imports this and not the other way round.
    from game.entities.terrain import water_near

    clear_registered_sites()
    center = c.World.WORLD_SIZE // 2
    distance = c.Villages.START_DISTANCE_FROM_CENTER
    reach = worst_case_footprint("start")[0] + c.Scenery.RIVER_VILLAGE_MARGIN
    for attempt in range(24):
        angle = random.uniform(0, 2 * math.pi)
        x = round(center + math.cos(angle) * distance)
        y = round(center + math.sin(angle) * distance)
        if attempt < 20 and water_near(x, y, reach):
            continue
        break
    chunk = (int(x // c.World.CHUNK_SIZE), int(y // c.World.CHUNK_SIZE))
    village, buildings = _build(x, y, chunk, "town", c.Villages.START_COMPOSITION, random.Random())

    landmark = _place_landmark(village, buildings)
    if landmark is not None:
        buildings.append(landmark)
    register_world_sites([village], buildings)
    return village, buildings


def _place_landmark(village: Village, buildings: list[Building]) -> Building | None:
    """The ancient ruin: out on the far side of the settled ring, well clear of the village
    and a long way from the spawn point, since its guardian is a boss and shouldn't be
    waiting on the doorstep (Boss.MIN_DIST_FROM_START, the floor under every boss rather
    than the ordinary building clearance).

    Clear of every *other* settlement too, planned ones included, and by a boss's clearance
    rather than a building's: the ruin is the one place in the world a boss stands from the
    first frame of the save, so it is placed where a boss is allowed to be. A ruin that
    fails that is a ruin with nothing guarding it."""
    center = c.World.WORLD_SIZE // 2
    margin = c.Buildings.EDGE_MARGIN
    size = c.World.CHUNK_SIZE
    reach = math.ceil(c.Boss.MIN_DIST_FROM_VILLAGE / size) + 2
    # More tries than a building's usual handful: the ruin has to clear every settlement in
    # the region by a boss's distance rather than a wall's, and the settled ring is not
    # large. A world with no ruin in it is a world with no guardian and no lore stone.
    for _ in range(400):
        x = random.randint(margin, c.World.WORLD_SIZE - margin)
        y = random.randint(margin, c.World.WORLD_SIZE - margin)
        if math.hypot(x - center, y - center) < c.Boss.MIN_DIST_FROM_START:
            continue
        if village.distance_to_point((x, y)) < village.grounds_radius + c.Boss.MIN_DIST_FROM_VILLAGE:
            continue
        chunk = (int(x // size), int(y // size))
        if any(
            math.hypot(x - sx, y - sy) - radius < c.Boss.MIN_DIST_FROM_VILLAGE
            for sx, sy, _, _, radius in settlements_near_chunk(*chunk, reach)
        ):
            continue
        candidate = Building(x, y, "landmark")
        gap = c.Buildings.MIN_GAP
        if any(candidate.bounds.inflate(gap * 2, gap * 2).colliderect(other.bounds) for other in buildings):
            continue
        return candidate
    return None
