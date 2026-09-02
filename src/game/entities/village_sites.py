"""Where settlements stand on the endless map, asked before any of them is built.

A pure function of chunk coordinates (`village_site`), plus the registry a world uses to
put on the map the two things no region grid ever offered: the starting town and the
landmark ruin. Everything laid out in the wilderness (roads, rivers, footpaths, landmarks)
routes against what is answered here, so this has to answer for a settlement that does not
exist yet as readily as for one that does.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

import core.constants as c
from game.entities.village_layout import composition_for, grounds_reach, plaza_slots, tier_for

# Settlements the region grid never offered, and circles nothing may be laid through, both
# registered by the world that holds them. The starting town is rolled per playthrough
# rather than out of a region, and the landmark ruin stands alone in the settled ring: both
# were invisible to everything laid out from `village_site`, which is how a road came to be
# drawn through a house, a river through a plaza and a signpost into the middle of a town.
#
# Registration is not a hole in the rule that a chunk is a pure function of its
# coordinates: it happens once, when a world is created or loaded, before a single chunk is
# generated, and every cache that answers off the sites is dropped when it does.
_registered: dict[tuple[int, int], tuple[float, float, float]] = {}
_keepouts: list[tuple[float, float, float]] = []
_SITE_CACHES: list = []


def register_site_cache(clear):
    """Hand over a cache that answers off the village sites, to be dropped whenever they
    change. Anything cached on `village_site`, `poi_site` or the routes between them has to
    be in here or it will go on describing a world with no starting town in it."""
    _SITE_CACHES.append(clear)


def _invalidate_sites():
    for clear in (
        _region_sites.cache_clear,
        _site_reach.cache_clear,
        village_site.cache_clear,
        site_grounds_radius.cache_clear,
    ):
        clear()
    settlements_near_chunk.cache_clear()
    for clear in _SITE_CACHES:
        clear()


def clear_registered_sites():
    _registered.clear()
    _keepouts.clear()
    _invalidate_sites()


def register_settlement(chunk: tuple[int, int], x: float, y: float, grounds_radius: float):
    """Put a settlement on the map the roads, the rivers and the landmarks are laid out
    against. The chunk it is registered under holds it instead of whatever its region
    offered, so nothing is ever generated twice in the same chunk."""
    _registered[(int(chunk[0]), int(chunk[1]))] = (float(x), float(y), float(grounds_radius))
    _invalidate_sites()


def register_keepout(x: float, y: float, radius: float):
    """A circle roads and rivers bow around but never lead to: the landmark ruin. A
    settlement is somewhere to go, a ruin in a field is something to route past."""
    _keepouts.append((float(x), float(y), float(radius)))
    _invalidate_sites()


def registered_keepouts() -> tuple[tuple[float, float, float], ...]:
    return tuple(_keepouts)


def register_world_sites(villages, buildings):
    """Register everything one world holds that its own region grid never offered. Called
    once when a world is created or loaded, before any chunk is generated: after this the
    terrain knows about the starting town and its ruin, and a chunk is a pure function of
    its coordinates again for the rest of the session."""
    clear_registered_sites()
    for village in villages:
        if village_site(*village.chunk) is None:
            register_settlement(village.chunk, village.x, village.y, village.grounds_radius)
    for building in buildings:
        if building.kind == "landmark":
            register_keepout(building.x, building.y, max(building.w, building.h) / 2 + c.Buildings.MIN_GAP)


def _settle_chance(distance: float, near: float, far: float) -> float:
    """One of the two settling chances at this distance from the world centre, eased out to
    `REGION_FAR_DISTANCE` and flat past it."""
    return near + (far - near) * min(1.0, distance / c.Villages.REGION_FAR_DISTANCE)


def _min_gap(x: float, y: float) -> float:
    """How much empty wilderness two settlements have to leave between them here.

    It closes up with distance for the same reason the settling chance opens up: raising
    the chance alone changed nothing at all, because every extra site landed inside a
    neighbour's gap and stood down again. Read off the middle of the two sites being
    compared, so both of them get the same answer whichever one is asking."""
    center = c.World.WORLD_SIZE // 2
    distance = math.hypot(x - center, y - center)
    return _settle_chance(distance, c.Villages.MIN_GAP, c.Villages.MIN_GAP_FAR)


@lru_cache(maxsize=4096)
def _site_reach(cx: int, cy: int, x: int, y: int) -> float:
    """How far the grounds of a settlement standing here would reach at its largest.

    The same answer `site_grounds_radius` gives, worked out without asking whether the
    chunk offers a site at all: two sites standing too close is decided from how much
    ground each of them would take, and `village_site` is the thing being decided, so it
    cannot also be the thing that is asked."""
    rng = random.Random(f"village-layout:{cx},{cy}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS, strict=True)
    size = rng.choices(sizes, weights=weights)[0]
    tier = tier_for(x, y, size)
    radius, extent_x, extent_y = worst_case_footprint(size, tier)
    return grounds_reach(radius, extent_x, extent_y, tier)


def _too_close(one: tuple[int, int, int, int], other: tuple[int, int, int, int]) -> bool:
    """Whether two sites stand too near each other to both be settled, as (cx, cy, x, y).

    Two rules, whichever is the greater: a floor of empty wilderness that closes up as the
    map gets busier, and the grounds themselves, which must never overlap. A gap in
    pixels alone let two towns' walls end up in each other, since how much ground a
    settlement takes is its size and not a constant."""
    mid = ((one[2] + other[2]) / 2, (one[3] + other[3]) / 2)
    reach = _site_reach(*one) + _site_reach(*other)
    return math.dist((one[2], one[3]), (other[2], other[3])) < max(_min_gap(*mid), reach)


@lru_cache(maxsize=4096)
def _region_sites(rx: int, ry: int) -> tuple[tuple[int, int, int, int], ...]:
    """Every chunk this region settles and where in it, as (cx, cy, x, y). Pure function of
    the region coordinates.

    How likely a region is to settle at all, and whether it settles a second chunk, are both
    read off how far out it stands: the region grid is fixed, so density is the one lever
    there is, and the deep wilds were as thinly peopled as the ring round the starting town
    while being very much larger. Both rolls are made whatever the answer, so a region's
    sequence does not shift when the ramp is retuned."""
    region = c.Villages.REGION_CHUNKS
    size = c.World.CHUNK_SIZE
    center = c.World.WORLD_SIZE // 2
    distance = math.hypot((rx + 0.5) * region * size - center, (ry + 0.5) * region * size - center)
    chances = (
        _settle_chance(distance, c.Villages.REGION_CHANCE, c.Villages.REGION_CHANCE_FAR),
        _settle_chance(distance, c.Villages.REGION_SECOND_CHANCE, c.Villages.REGION_SECOND_CHANCE_FAR),
    )

    rng = random.Random(f"village:{rx},{ry}")
    margin = c.Villages.CHUNK_MARGIN
    sites: list[tuple[int, int, int, int]] = []
    for slot, chance in enumerate(chances):
        settles = rng.random() <= chance
        cx = rx * region + rng.randrange(region)
        cy = ry * region + rng.randrange(region)
        if slot and sites:
            # The second one goes in the corner of the region furthest from the first
            # rather than being rolled: two points dropped anywhere in a region this size
            # are usually nearer each other than the gap allows, so a second site rolled
            # freely was a second site that always stood down again.
            cx = rx * region + (0 if sites[0][0] - rx * region >= region / 2 else region - 1)
            cy = ry * region + (0 if sites[0][1] - ry * region >= region / 2 else region - 1)
        x = cx * size + rng.randint(margin, size - margin)
        y = cy * size + rng.randint(margin, size - margin)
        if not settles:
            continue
        if math.hypot(x - center, y - center) < c.Villages.MIN_DIST_FROM_SPAWN:
            continue
        # The second site of a region stands down for the first exactly as a whole region
        # stands down for its neighbour, and never shares its chunk.
        if any((cx, cy) == other[:2] or _too_close((cx, cy, x, y), other) for other in sites):
            continue
        sites.append((cx, cy, x, y))
    return tuple(sites)


@lru_cache(maxsize=4096)
def village_site(cx: int, cy: int) -> tuple[int, int] | None:
    """Where the village belonging to chunk (cx, cy) stands, or None if it holds none.

    One region of REGION_CHUNKS x REGION_CHUNKS chunks settles one chunk, or two out in the
    wilds, and a site landing too close to a neighbouring region's yields to it, so two
    settlements can't end up back to back across a region border. All of it is a pure
    function of the coordinates: the same chunk always offers the same site, whether or not
    the village behind it has been generated yet, which is also why the answer is cached:
    chunk loading, landmark placement and the roads between settlements all ask it
    repeatedly for the same coordinates.

    A chunk a world registered a settlement into (`register_settlement`) answers with that
    instead: the starting town is rolled per playthrough rather than out of a region, and
    everything laid out against the sites has to know it is there.
    """
    registered = _registered.get((cx, cy))
    if registered is not None:
        return round(registered[0]), round(registered[1])

    region = c.Villages.REGION_CHUNKS
    rx, ry = math.floor(cx / region), math.floor(cy / region)
    site = next((s for s in _region_sites(rx, ry) if (s[0], s[1]) == (cx, cy)), None)
    if site is None:
        return None

    for _chunk, (ox, oy, radius) in _registered.items():
        if math.hypot(site[2] - ox, site[3] - oy) < max(c.Villages.MIN_GAP, radius + c.Villages.MIN_GAP / 2):
            return None
    for nx in range(rx - 1, rx + 2):
        for ny in range(ry - 1, ry + 2):
            # Ties are broken by region order, the same way from wherever this is asked.
            if (nx, ny) >= (rx, ry):
                continue
            for other in _region_sites(nx, ny):
                if _too_close(site, other):
                    return None
    return site[2], site[3]


@lru_cache(maxsize=32)
def worst_case_footprint(size: str, tier: int = 0) -> tuple[int, int, int]:
    """The biggest (radius, extent_x, extent_y) a settlement of this size and tier can lay
    out.

    Rolled without an rng: every count is taken at its maximum, every building at its
    largest and the jitter at its worst, so the answer is an upper bound on a village that
    has not been generated yet rather than a guess at the one that will be. The tier is in
    it because it is worth houses (`Villages.EXTRA_BUILDINGS_BY_TIER`): a bound taken off
    the size alone is not a bound at all once a deep wilds village is half again as big."""
    composition = c.Villages.START_COMPOSITION if size == "start" else composition_for(size, tier)
    count = sum(high for _low, high in composition.values())
    slots = plaza_slots(count, random.Random(0))
    jitter = c.Villages.SLOT_JITTER
    kinds = [kind for kind, (_low, high) in composition.items() if high]
    max_w = max(c.Buildings.SIZES[kind][0][1] for kind in kinds)
    max_h = max(c.Buildings.SIZES[kind][1][1] for kind in kinds)
    radius = round(max((math.hypot(ox, oy) for ox, oy in slots), default=0) + jitter + c.Villages.SLOT_W / 2)
    extent_x = round(max((abs(ox) for ox, _oy in slots), default=0) + jitter + max_w / 2)
    extent_y = round(max((abs(oy) for _ox, oy in slots), default=0) + jitter + max_h / 2)
    return radius, extent_x, extent_y


@lru_cache(maxsize=4096)
def site_grounds_radius(cx: int, cy: int) -> float:
    """How far the grounds of the village chunk (cx, cy) offers will reach, asked before the
    settlement exists. 0 for a chunk that holds no site.

    A pure function of the coordinates like `village_site` itself: the size is the first
    draw `generate_village` makes off the same seed, and the footprint is that size at its
    largest. Anything placed in the wilderness (a landmark, a graveyard) clears this rather
    than clearing the site point by a fixed distance, which is how a row of tombstones
    ended up against a town's gate. A registered settlement already exists, so it answers
    with the grounds it actually has."""
    registered = _registered.get((cx, cy))
    if registered is not None:
        return registered[2]
    site = village_site(cx, cy)
    if site is None:
        return 0.0
    return _site_reach(cx, cy, site[0], site[1])


def sites_near_chunk(cx: int, cy: int, chunk_radius: int) -> list[tuple[int, int]]:
    """Every village site within `chunk_radius` chunks of (cx, cy), generated or not, as
    plain points. `settlements_near_chunk` is the same walk with each site's chunk and the
    reach of its grounds kept, which is what a road needs to stop at a gate rather than
    running through the houses behind it."""
    return [(x, y) for x, y, _, _, _ in settlements_near_chunk(cx, cy, chunk_radius)]


@lru_cache(maxsize=512)
def settlements_near_chunk(cx: int, cy: int, chunk_radius: int) -> tuple[tuple[float, float, int, int, float], ...]:
    """Every village site within `chunk_radius` chunks of (cx, cy), generated or not, as
    (x, y, chunk x, chunk y, grounds radius).

    Sites are a pure function of their region, so this answers the same thing from
    anywhere: what the roads between settlements are drawn from, and cheap enough to ask
    on every chunk load because it walks regions rather than chunks.
    """
    region = c.Villages.REGION_CHUNKS
    sites: list[tuple[float, float, int, int, float]] = []
    for rx in range(math.floor((cx - chunk_radius) / region), math.floor((cx + chunk_radius) / region) + 1):
        for ry in range(math.floor((cy - chunk_radius) / region), math.floor((cy + chunk_radius) / region) + 1):
            for site in _region_sites(rx, ry):
                # Asked back through village_site so a region that stands down for a
                # neighbour is left out here too, and no road is drawn to a village that
                # never exists.
                if village_site(site[0], site[1]) is not None:
                    sites.append((site[2], site[3], site[0], site[1], site_grounds_radius(site[0], site[1])))
    for chunk, (x, y, radius) in _registered.items():
        if max(abs(chunk[0] - cx), abs(chunk[1] - cy)) <= chunk_radius:
            sites.append((x, y, chunk[0], chunk[1], radius))
    return tuple(sites)
