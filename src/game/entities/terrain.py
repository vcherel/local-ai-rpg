"""Where the wilderness comes from: the roads, rivers and clumps of scenery a chunk holds.

`scenery.py` owns what one piece of wilderness *is* and how it draws itself; this owns
where all of it stands. Both halves are per-chunk pure functions of `(cx, cy)` and nothing
in here is ever saved, which is the whole contract: walk away from a wood and back to it
and the same trees are in the same places because the same seed rolled them.

Roads and rivers are worked out from the settlements and landmarks near a chunk rather
than stored, so they join up across chunk borders without any of them knowing about each
other, and every one of these functions is cached on its coordinates because a chunk's
neighbours all ask the same questions of it.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import NamedTuple

import pygame

import core.constants as c
from game.entities.scenery import Scenery
from game.entities.village import register_site_cache, registered_keepouts, settlements_near_chunk


class RoadBlob(NamedTuple):
    """One step of packed earth along a route: where it is, how wide the track is there,
    which way the route runs through it, and whether it is a road between two settlements
    or a footpath out to a landmark.

    Named rather than a bare tuple because it is read outside this file (a travelling
    merchant is put down on one), and every field this has grown was added here and then
    silently broke whoever was unpacking it positionally somewhere else."""

    x: float
    y: float
    width: float
    heading: float
    kind: str


class Deck(NamedTuple):
    """One crossing: the middle of the deck, the way it lies, and how long it is."""

    x: float
    y: float
    angle: float
    length: float


def _pick(weights: Sequence[tuple[str, int]], rng: random.Random) -> str:
    names, values = zip(*weights)
    return rng.choices(names, weights=values)[0]


Endpoint = tuple[float, float, float]  # x, y, how much of the far end is left alone
Route = tuple[Endpoint, Endpoint, str]  # from, to, "road" or "path"


def road_points_for_chunk(cx: int, cy: int) -> list[RoadBlob]:
    """The packed earth of every road and footpath crossing this chunk, as
    (x, y, width, heading).

    The network is drawn from three pure functions of the coordinates (`village_site`,
    `site_grounds_radius`, `poi_site`), so the same track appears in every chunk it crosses
    with no cross-chunk bookkeeping: a chunk works out which routes come near it and keeps
    the stretch that falls inside its own bounds.

    Routing is three rules. A road stops at the gate side of a settlement's grounds instead
    of running through its houses and its wall; anywhere it would pass through a third
    settlement it bows around it (`_dodge_grounds`); and nothing solid is ever generated
    within `ROAD_CLEARANCE` of a blob, which is what keeps a wood from growing across a
    road rather than the road having to pick its way through the wood.
    """
    size = c.World.CHUNK_SIZE
    bounds = pygame.Rect(cx * size, cy * size, size, size).inflate(c.Scenery.ROAD_WOBBLE * 2, c.Scenery.ROAD_WOBBLE * 2)

    points: list[RoadBlob] = []
    for route in _routes_near_chunk(cx, cy):
        line = _route_line(route)
        # Nearly every route in the region misses this chunk entirely, and walking one is
        # hundreds of blobs: the cheap test is worth making before the walk.
        if not line or not _crosses(bounds, (line[0].x, line[0].y), (line[-1].x, line[-1].y)):
            continue
        points.extend(blob for blob in line if bounds.collidepoint(blob.x, blob.y))
    return points


def _routes_near_chunk(cx: int, cy: int) -> list[Route]:
    """Every route that might cross this chunk, each one asked of the place it leaves from
    rather than of the chunk asking, so two chunks either side of a border never disagree
    about whether a road exists. In route-key order, so every chunk sees them the same way
    round and a crossing shared by two of them is settled the same way in both."""
    routes: dict[tuple, Route] = {}
    for x, y, scx, scy, radius in settlements_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS):
        for route in _roads_from_site(x, y, scx, scy, radius):
            routes[_route_key(route)] = route
    reach = c.Scenery.PATH_CHUNK_RADIUS
    for gx in range(cx - reach, cx + reach + 1):
        for gy in range(cy - reach, cy + reach + 1):
            route = _path_from_poi(gx, gy)
            if route is not None:
                routes[_route_key(route)] = route
    return [routes[key] for key in sorted(routes)]


def _route_key(route: Route) -> tuple:
    """The same track asked for from either end is one track, not two laid on top of each
    other: a road and the footpath joining the same two places would double its width."""
    (ax, ay, _), (bx, by, _), kind = route
    return (*sorted(((round(ax), round(ay)), (round(bx), round(by)))), kind)


@lru_cache(maxsize=512)
def _roads_from_site(x: float, y: float, cx: int, cy: int, radius: float) -> tuple[Route, ...]:
    """The roads leaving one settlement: its nearest `ROAD_LINKS` neighbours within reach.

    More than one link is what turns a chain of villages into a network, and the cap on the
    length is what keeps a lone settlement in the deep wilds from being joined to a town
    half a world away by a road nobody would have cut.
    """
    others = [s for s in settlements_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS) if (s[0], s[1]) != (x, y)]
    others.sort(key=lambda s: math.dist((x, y), (s[0], s[1])))
    routes = []
    for ox, oy, _, _, oradius in others[: c.Scenery.ROAD_LINKS]:
        if math.dist((x, y), (ox, oy)) > c.Scenery.ROAD_MAX_LENGTH:
            break
        routes.append(((x, y, radius), (ox, oy, oradius), "road"))
    return tuple(routes)


@lru_cache(maxsize=2048)
def _path_from_poi(cx: int, cy: int) -> Route | None:
    """The footpath worn from this chunk's landmark to whatever it is nearest to: the
    settlement it stands outside, or the next landmark along.

    Nearest of the two rather than the settlement by preference, so a string of landmarks
    out in the wilds is joined into a track that leads somewhere instead of every one of
    them sending its own spoke back to the same village. A landmark with nothing within
    `PATH_MAX_LENGTH` keeps no path at all, which is what leaves the deep wilds trackless.
    """
    # Imported here rather than at the top: a landmark keeps out of the water, so poi.py
    # asks this module where the rivers run, and this is the other half of that pair.
    from game.entities.poi import poi_site

    site = poi_site(cx, cy)
    if site is None:
        return None
    x, y, _ = site

    reach = c.Scenery.PATH_CHUNK_RADIUS
    ends: list[Endpoint] = [(sx, sy, radius) for sx, sy, _, _, radius in settlements_near_chunk(cx, cy, reach)]
    for gx in range(cx - reach, cx + reach + 1):
        for gy in range(cy - reach, cy + reach + 1):
            other = poi_site(gx, gy) if (gx, gy) != (cx, cy) else None
            if other is not None:
                ends.append((other[0], other[1], c.Scenery.PATH_POI_CLEARANCE))

    end = min(ends, key=lambda e: math.dist((x, y), (e[0], e[1])), default=None)
    if end is None or math.dist((x, y), (end[0], end[1])) > c.Scenery.PATH_MAX_LENGTH:
        return None
    return (x, y, c.Scenery.PATH_POI_CLEARANCE), end, "path"


@lru_cache(maxsize=512)
def _route_line(route: Route) -> tuple[RoadBlob, ...]:
    """One whole route as (x, y, width, heading) every `ROAD_STEP` along it, end to end.

    The line is bent by a seeded sine so a road reads as a track somebody wore into the
    ground rather than as a ruler laid across the map, pinched back to nothing at each end
    so it still meets what it joins.

    The width is a wave along the route rather than a roll per blob: a track is a worn line
    of one width that swells and narrows as it goes, and a radius rolled fresh every step
    is what made a road read as a string of beads. Each blob carries the way the route runs
    where it stands, which is what lets one be drawn as a stretch of track (`_draw_path`)
    and what a bridge is squared onto.

    Held whole rather than per chunk: the same track has to come out the same on both sides
    of a seam, and the crossings it needs are counted along its whole length.
    """
    (ax, ay, a_clear), (bx, by, b_clear), kind = route
    start = _approach(ax, ay, a_clear, bx, by)
    end = _approach(bx, by, b_clear, ax, ay)
    length = math.dist(start, end)
    if length < 1:
        return ()

    size = c.World.CHUNK_SIZE
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    # The settlements are looked up from the route's own middle, not from whichever chunk
    # is asking: a track that bowed round a village in one chunk and not in the next was
    # two tracks meeting at the seam.
    sites = _dodge_circles(int(mid[0] // size), int(mid[1] // size))

    rng = random.Random(f"{kind}:{start}:{end}")
    phase = rng.uniform(0, 2 * math.pi)
    waves = rng.uniform(0.8, 1.8)
    # How far a road may wander follows how far it is going: two sites a chunk apart have
    # no room to bend, and a road crossing several has to earn its length or it reads as a
    # ruler laid between two villages.
    amplitude = rng.uniform(0.55, 1.0) * c.Scenery.ROAD_WOBBLE * min(1.0, length / c.Scenery.ROAD_WOBBLE_FULL)
    detail_phase = rng.uniform(0, 2 * math.pi)
    detail_waves = rng.uniform(4.0, 7.0)
    width_lo, width_hi = c.Scenery.PATH_WIDTH if kind == "path" else c.Scenery.ROAD_WIDTH
    base = rng.uniform(width_lo, width_hi)
    swell_phase, edge_phase = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length

    places: list[tuple[float, float, float]] = []
    for step in range(0, int(length), c.Scenery.ROAD_STEP):
        t = step / length
        # One long wave for where the road goes, a shorter one over it for how it got there.
        bend = math.sin(phase + t * waves * 2 * math.pi) * amplitude
        bend += math.sin(detail_phase + t * detail_waves * 2 * math.pi) * amplitude * c.Scenery.ROAD_DETAIL
        bend *= math.sin(math.pi * t)
        x = start[0] + dx * step - dy * bend
        y = start[1] + dy * step + dx * bend
        x, y = _dodge_grounds(x, y, -dy, dx, sites, route)
        # Where the track is broad and where it is worn thin, plus a shorter wave for an
        # edge that is walked rather than laid out.
        swell = math.sin(swell_phase + step / c.Scenery.ROAD_SWELL_PERIOD * 2 * math.pi)
        edge = math.sin(edge_phase + step / c.Scenery.ROAD_EDGE_PERIOD * 2 * math.pi)
        width = base * (1.0 + swell * c.Scenery.ROAD_SWELL + edge * c.Scenery.ROAD_EDGE_NOISE)
        places.append((x, y, width))

    return tuple(RoadBlob(x, y, width, _line_heading(places, i), kind) for i, (x, y, width) in enumerate(places))


def _line_heading(places: Sequence[tuple[float, float, float]], i: int) -> float:
    """Which way a route is running at one of its blobs, taken from the blob either side of
    it so a bend reads as a curve rather than as a corner."""
    ahead = places[min(i + 1, len(places) - 1)]
    behind = places[max(i - 1, 0)]
    if ahead is behind:
        return 0.0
    return math.atan2(ahead[1] - behind[1], ahead[0] - behind[0])


def _approach(x: float, y: float, clearance: float, toward_x: float, toward_y: float) -> tuple[float, float]:
    """Where a route meets one of its ends. A settlement is met at the middle of the side
    facing the other end, which is where its gate stands and where its grounds stop: a road
    that carried on to the plaza would have to be laid through the wall and the houses
    behind it. A landmark is simply left a little room."""
    if clearance <= 0:
        return x, y
    dx, dy = toward_x - x, toward_y - y
    if abs(dx) >= abs(dy):
        return x + math.copysign(clearance, dx), y
    return x, y + math.copysign(clearance, dy)


def _crosses(bounds: pygame.Rect, start, end) -> bool:
    """Whether a route comes anywhere near this chunk, tested as the distance from the
    chunk's centre to the segment. Laying out every road in the region per chunk is most of
    what a chunk load would cost otherwise, and nearly all of them are nowhere near it."""
    px, py = bounds.center
    ax, ay = start
    dx, dy = end[0] - ax, end[1] - ay
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
    reach = math.hypot(bounds.width, bounds.height) / 2 + c.Scenery.ROAD_WOBBLE
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t)) <= reach


@lru_cache(maxsize=512)
def _dodge_circles(cx: int, cy: int) -> tuple[tuple[float, float, float], ...]:
    """Everything a route near this chunk has to bow around, as (x, y, how far it reaches):
    the settlements it is not itself going to, and the standing ruins registered with the
    world. A road laid through the one building in the wilderness worth walking to is the
    same mistake as one laid through a village."""
    sites = [(x, y, radius) for x, y, _, _, radius in settlements_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS)]
    return tuple(sites + list(registered_keepouts()))


def _dodge_grounds(x: float, y: float, nx: float, ny: float, sites, route: Route) -> tuple[float, float]:
    """Push a point of road out of any settlement's grounds it would otherwise run through,
    sideways along the road's own normal.

    Its two ends are exempt: a road is *meant* to arrive at those, and it already stops at
    their gate. Anything else in the way is a third village the track never had any reason
    to be cut through."""
    for sx, sy, radius in sites:
        if any(math.dist((sx, sy), (ex, ey)) < 1 for ex, ey, _ in route[:2]):
            continue
        clear = radius + c.Scenery.ROAD_VILLAGE_CLEARANCE
        gap = math.hypot(x - sx, y - sy)
        if gap >= clear:
            continue
        side = 1.0 if (x - sx) * nx + (y - sy) * ny >= 0 else -1.0
        push = clear - gap
        x, y = x + nx * side * push, y + ny * side * push
    return x, y


Blobs = list[tuple[float, float, float]]


def river_points_for_chunk(cx: int, cy: int) -> tuple[Blobs, list[Deck]]:
    """The stretch of every river crossing this chunk, as (water blobs, bridge decks).

    Rivers run on lanes: a fixed multiple of the chunk grid, each lane a pure function of
    its own index, so a chunk lays down its own stretch with no idea what its neighbours
    did and the course still joins up across the seam. Nothing here blocks. Water is slow
    to cross (`World.water_at`), which is what leaves a bridge worth walking to.

    A lane bends around any settlement it would otherwise run through, and carries a bridge
    at fixed intervals whatever else is nearby, so a crossing is always findable. How broad
    the water is is rolled per lane (`RIVER_LANE_SCALE`) rather than shared: a brook and a
    river worth walking a long way to a bridge for are the same course at two scales, and a
    map where every river is the same width has only one of them on it.
    """
    size = c.World.CHUNK_SIZE
    span = c.Scenery.RIVER_LANE_CHUNKS * size
    bounds = pygame.Rect(cx * size, cy * size, size, size)
    reach = c.Scenery.RIVER_WOBBLE + max(c.Scenery.RIVER_WIDTH) * max(c.Scenery.RIVER_LANE_SCALE)
    sites = _dodge_circles(cx, cy)

    water: list[tuple[float, float, float]] = []
    bridges: list[Deck] = []
    for axis in (0, 1):  # 0: the river runs north-south, 1: east-west
        # The chunk's extent along the river's own direction, snapped to a global step grid
        # so both sides of a chunk border sample the very same points.
        run_start = bounds.top if axis == 0 else bounds.left
        run_end = bounds.bottom if axis == 0 else bounds.right
        cross_min = (bounds.left if axis == 0 else bounds.top) - reach
        cross_max = (bounds.right if axis == 0 else bounds.bottom) + reach

        for index in range(math.floor(cross_min / span), math.floor(cross_max / span) + 1):
            rng = random.Random(f"river:{axis}:{index}")
            if rng.random() > c.Scenery.RIVER_LANE_CHANCE:
                continue
            base = index * span
            phase, period = rng.uniform(0, 2 * math.pi), rng.uniform(1600, 3400)
            phase2, period2 = rng.uniform(0, 2 * math.pi), rng.uniform(500, 900)
            amplitude = rng.uniform(0.55, 1.0) * c.Scenery.RIVER_WOBBLE
            scale = rng.uniform(*c.Scenery.RIVER_LANE_SCALE)
            width_lo, width_hi = (w * scale for w in c.Scenery.RIVER_WIDTH)
            bridge_offset = rng.uniform(0, c.Scenery.BRIDGE_INTERVAL)

            step = c.Scenery.RIVER_STEP
            for t in range(int(run_start // step) * step, int(run_end) + step, step):
                bend = math.sin(phase + t / period) * amplitude + math.sin(phase2 + t / period2) * amplitude * 0.12
                cross = base + bend
                x, y = (cross, t) if axis == 0 else (t, cross)
                if not bounds.collidepoint(x, y):
                    continue
                # Bending round a village is done after the bounds test, so the point stays
                # the responsibility of the chunk that would have held it and no stretch of
                # river is generated twice or lost between two chunks.
                x, y = _dodge_villages(x, y, axis, sites)
                width = width_lo + (width_hi - width_lo) * (0.5 + 0.5 * math.sin(phase2 + t / period2))
                water.append((x, y, width / 2))
                if (t - bridge_offset) % c.Scenery.BRIDGE_INTERVAL < step:
                    # How fast the course is drifting sideways here, so the deck is laid
                    # square across the current rather than along the lane's nominal line.
                    slope = math.cos(phase + t / period) * amplitude / period
                    flow = math.atan2(1.0, slope) if axis == 0 else math.atan2(slope, 1.0)
                    bridges.append(Deck(x, y, flow + math.pi / 2, _deck_length(width)))
    return water, bridges


def _dodge_villages(x: float, y: float, axis: int, sites: Sequence[tuple[float, float, float]]) -> tuple[float, float]:
    """Push a point of river out of any settlement it would run through, sideways.

    A river that stops at the village wall and starts again past it reads as two rivers;
    one that bows around the place reads as why the place is there. The push is faded out
    over the length of the bow rather than applied wherever the point happens to be inside
    the circle, since a course that snapped back to its lane the instant it cleared the
    last house left a notch cut out of the water.

    How far it bows follows the settlement's own grounds rather than one number for every
    village there is: a town reaches out to its wall and its ditch, and a course that
    cleared a hamlet by a field's width ran straight through the middle of a big one."""
    for sx, sy, radius in sites:
        clearance = max(c.Scenery.RIVER_VILLAGE_CLEARANCE, radius + c.Scenery.RIVER_VILLAGE_MARGIN)
        dx, dy = x - sx, y - sy
        along = dy if axis == 0 else dx
        if math.hypot(dx, dy) >= clearance or abs(along) >= clearance:
            continue
        # Only the axis across the river's own direction may move: shifting it along its
        # course would bunch the blobs up instead of moving the water.
        side = 1.0 if (dx if axis == 0 else dy) >= 0 else -1.0
        span = math.sqrt(max(1.0, clearance * clearance - along * along))
        blend = 1.0 - (along / clearance) ** 2
        if axis == 0:
            x += ((sx + side * span) - x) * blend
        else:
            y += ((sy + side * span) - y) * blend
    return x, y


def _deck_length(width: float) -> float:
    """How long a deck has to be to span water this wide, with a landing at each end. A
    river's width is rolled per lane now, so one fixed deck either stopped short of the far
    bank of the big ones or stood on dry ground either side of the small ones."""
    return max(c.Scenery.BRIDGE_MIN_LENGTH, width * c.Scenery.BRIDGE_SPAN)


@lru_cache(maxsize=512)
def _chunk_river(cx: int, cy: int) -> tuple[tuple, tuple]:
    """One chunk's stretch of water and the crossings its lanes carry, kept because both
    the chunk itself and every route looking for somewhere to ford ask for them."""
    water, bridges = river_points_for_chunk(cx, cy)
    return tuple(water), tuple(bridges)


def water_near(x: float, y: float, radius: float) -> bool:
    """Whether any river runs within `radius` of this point. Asked before anything is
    placed that a river would spoil: the course is a pure function of its lane, so it can
    be answered about ground nobody has walked on yet."""
    size = c.World.CHUNK_SIZE
    cx, cy = int(x // size), int(y // size)
    reach = int(radius // size) + 1
    for ox in range(-reach, reach + 1):
        for oy in range(-reach, reach + 1):
            for blob in _chunk_river(cx + ox, cy + oy)[0]:
                if math.hypot(x - blob[0], y - blob[1]) < blob[2] + radius:
                    return True
    return False


def _water_under(x: float, y: float) -> tuple | None:
    """The river blob covering this point, or None on dry ground. The neighbouring chunks
    are asked as well as its own: a blob is generated by the chunk holding its middle and
    reaches out past the seam."""
    size = c.World.CHUNK_SIZE
    cx, cy = int(x // size), int(y // size)
    found = None
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for blob in _chunk_river(cx + ox, cy + oy)[0]:
                if math.hypot(x - blob[0], y - blob[1]) > blob[2]:
                    continue
                if found is None or blob[2] > found[2]:
                    found = blob
    return found


@lru_cache(maxsize=512)
def _route_crossings(route: Route) -> tuple[Deck, ...]:
    """One deck wherever a route runs into water, and exactly one: a road that stops at the
    bank and picks up on the far side is a road nobody built.

    Counted along the whole route rather than per chunk, which is what keeps a single ford
    from becoming a row of bridges. The blobs of a route that lie in water are one unbroken
    run per crossing, so a run is a crossing: the deck goes at the middle of it, laid along
    the road, and however many blobs the run holds it is still one bridge.
    """
    decks: list[Deck] = []
    run: list[tuple[RoadBlob, tuple]] = []

    def close(wet_run):
        if not wet_run:
            return
        blob, water = wet_run[len(wet_run) // 2]
        widest = max(w[2] for _b, w in wet_run)
        decks.append(Deck(water[0], water[1], blob.heading, _deck_length(widest * 2)))

    for blob in _route_line(route):
        water = _water_under(blob.x, blob.y)
        if water is None:
            close(run)
            run = []
        else:
            run.append((blob, water))
    close(run)
    return tuple(decks)


@lru_cache(maxsize=256)
def _chunk_terrain(cx: int, cy: int) -> tuple[tuple, tuple, tuple]:
    """One chunk's roads, river and crossings, as (road blobs, water blobs, bridges).

    Kept because a chunk needs its neighbours' bridges as well as its own: nothing solid
    may stand at the end of a deck, and a deck laid near a chunk seam is walked onto from
    the chunk next door, so nine of these are asked per chunk loaded and each answer is
    reused by eight of them. All of it is a pure function of the coordinates like the
    scenery it feeds, so a chunk streaming back in costs the lookup and nothing more.

    A deck belongs to the chunk its middle falls in, so no crossing is laid twice; the ones
    the neighbours hold are still counted, since two bridges either side of a seam are the
    same row of bridges the run-per-crossing rule is there to prevent.

    Two crossings never stand within `BRIDGE_MIN_GAP` of each other, and when a road runs
    into the water beside one a lane had already laid, the deck that is there is turned
    along the road rather than a second one being built next to it: a bridge is where a
    track meets a river, so the track decides which way it lies.
    """
    size = c.World.CHUNK_SIZE
    bounds = pygame.Rect(cx * size, cy * size, size, size)
    roads = tuple(road_points_for_chunk(cx, cy))

    # Every crossing this chunk's neighbourhood carries, taken in one fixed order so both
    # sides of a seam settle a conflict the same way: two lanes crossing each other laid
    # two decks over the same stretch of water, and a lane that yields yields everywhere.
    decks: list[Deck] = []
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for deck in _chunk_river(cx + ox, cy + oy)[1]:
                if not any(
                    math.hypot(deck.x - other.x, deck.y - other.y) < _bridge_gap(deck, other) for other in decks
                ):
                    decks.append(deck)
    for route in _routes_near_chunk(cx, cy):
        for deck in _route_crossings(route):
            near = next(
                (
                    i
                    for i, other in enumerate(decks)
                    if math.hypot(deck.x - other.x, deck.y - other.y) < _bridge_gap(deck, other)
                ),
                None,
            )
            if near is None:
                decks.append(deck)
            else:
                standing = decks[near]
                decks[near] = Deck(standing.x, standing.y, deck.angle, max(standing.length, deck.length))
    return roads, _chunk_river(cx, cy)[0], tuple(deck for deck in decks if bounds.collidepoint(deck.x, deck.y))


def _bridge_gap(one: Deck, other: Deck) -> float:
    """How close two crossings are allowed to stand: never nearer than either of them is
    long, and never nearer than `BRIDGE_MIN_GAP` whatever their size."""
    return max(c.Scenery.BRIDGE_MIN_GAP, one.length, other.length)


def generate_chunk_scenery(
    cx: int,
    cy: int,
    buildings: Iterable,
    villages: Iterable,
    pois: Iterable,
) -> list[Scenery]:
    """Everything growing or lying in one chunk, rolled from its coordinates alone.

    The chunk picks a single biome first, which is what makes a wood a wood: scattering
    every kind evenly over every chunk gives texture, not places. Villages, buildings and
    landmarks push cover away so nothing grows through a wall or over a campfire, and the
    roads and rivers through the chunk are laid first so nothing solid ever stands on one
    and nothing at all grows out of the water.
    """
    rng = random.Random(f"scenery:{cx},{cy}")
    size = c.World.CHUNK_SIZE
    chunk = (cx, cy)

    biome = _pick(c.Scenery.BIOME_WEIGHTS, rng)
    roads, river, bridges = _chunk_terrain(cx, cy)
    # Every deck within reach of this chunk, its own and its neighbours', as ground no
    # trunk or boulder may stand on: a crossing walled in at the end of it is worse than
    # no crossing at all, because the player walked over to use it.
    bridge_zones = [
        (deck.x, deck.y, math.hypot(deck.length, c.Scenery.BRIDGE_WIDTH) / 2 + c.Scenery.BRIDGE_CLEARANCE)
        for ox in (-1, 0, 1)
        for oy in (-1, 0, 1)
        for deck in _chunk_terrain(cx + ox, cy + oy)[2]
    ]

    # Circles nothing at all may stand in, and circles only solid things are kept out of.
    # Reaching past the doorstep as well as past the walls: the clear ground in front of a
    # door is the one piece of a building nothing at all may stand on, and it sticks out
    # further than the wall clearance does.
    keep_off = max(c.Scenery.CLEARANCE_BUILDING, c.Villages.DOORSTEP_CLEAR)
    solid_zones = [(b.x, b.y, max(b.w, b.h) / 2 + keep_off) for b in buildings]
    solid_zones += [(p.x, p.y, c.Scenery.CLEARANCE_POI) for p in pois]
    open_zones = [(v.x, v.y, v.grounds_radius + c.Scenery.CLEARANCE_VILLAGE) for v in villages]

    def clear_of_places(x: float, y: float) -> bool:
        return not any(math.hypot(x - zx, y - zy) < radius for zx, zy, radius in solid_zones + open_zones)

    # Standing water is placed before anything else so nothing is planted in it. A pond and
    # a lake are the same thing at two scales, and both are crossed the way a river is.
    still = []
    for kind, count in (
        ("pond", rng.randint(0, 2) if biome == "wetland" else 0),
        ("lake", 1 if rng.random() < c.Scenery.LAKE_CHANCE[biome] else 0),
    ):
        for _ in range(count):
            x = cx * size + rng.uniform(0, size)
            y = cy * size + rng.uniform(0, size)
            piece = Scenery(x, y, kind, chunk, biome=biome)
            on_road = any(math.hypot(x - blob.x, y - blob.y) < piece.water_reach for blob in roads)
            if clear_of_places(x, y) and not on_road:
                still.append(piece)

    water = list(river) + [(p.x, p.y, p.water_reach) for p in still]

    def in_water(x: float, y: float, margin: float = 0.0) -> bool:
        return any(math.hypot(x - wx, y - wy) < radius + margin for wx, wy, radius in water)

    # A road between two settlements and a footpath out to a landmark are the same blobs
    # at two scales and in two colours: the road is what the player is meant to see from
    # across a field and follow, the path is a line worn in the grass.
    items = [
        Scenery(blob.x, blob.y, blob.kind, chunk, size=blob.width, biome=biome, angle=blob.heading)
        for blob in roads
        if not in_water(blob.x, blob.y)
    ]
    # Three pieces per blob of river: the water itself, and the two layers of colour that
    # are drawn in their own passes over it, since one blob painting all three would paint
    # over its neighbour (see Scenery._draw_river).
    for kind in ("river", "river_body", "river_deep"):
        items += [Scenery(x, y, kind, chunk, size=radius, biome=biome) for x, y, radius in river]
    items += still
    # A crossing wherever the lane says so, plus one wherever a road runs into the water:
    # that is where anybody would have built one, and it keeps a road from stopping dead.
    # Both kinds are already in `bridges`, rolled by `_chunk_terrain`.
    for deck in bridges:
        items.append(Scenery(deck.x, deck.y, "bridge", chunk, size=deck.length, biome=biome, angle=deck.angle))

    def free(x: float, y: float, solid: bool) -> bool:
        for zx, zy, radius in solid_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        # Nothing grows out of open water, and a trunk keeps off the bank as well: what
        # blocks must never stand where it would wall a crossing in.
        if in_water(x, y, c.Scenery.RIVER_BANK_CLEARANCE if solid else 0.0):
            return False
        if not solid:
            return True
        for zx, zy, radius in bridge_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        for zx, zy, radius in open_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        return all(math.hypot(x - blob.x, y - blob.y) >= blob.width + c.Scenery.ROAD_CLEARANCE for blob in roads)

    for kind, clusters, members, spread in c.Scenery.BIOMES[biome]:
        solid = kind in c.Scenery.BLOCK_RADIUS
        for _ in range(rng.randint(*clusters)):
            gx = cx * size + rng.uniform(0, size)
            gy = cy * size + rng.uniform(0, size)
            for _ in range(rng.randint(*members)):
                x = gx + rng.uniform(-spread, spread)
                y = gy + rng.uniform(-spread, spread)
                if free(x, y, solid):
                    items.append(Scenery(x, y, kind, chunk, biome=biome))
    return items


def water_index(items: Iterable[Scenery]) -> dict:
    """Bucket the water and the bridges over it on the same fine grid the trunks use.

    Separate from `blocking_index` because water is the opposite of a wall: nothing is
    stopped by it, everything is slowed in it, so it needs a footprint of its own."""
    cell = c.Scenery.INDEX_CELL
    index: dict = {}
    for item in items:
        if not item.water_reach:
            continue
        reach = item.water_reach + c.Scenery.INDEX_PAD
        for gx in range(int((item.x - reach) // cell), int((item.x + reach) // cell) + 1):
            for gy in range(int((item.y - reach) // cell), int((item.y + reach) // cell) + 1):
                index.setdefault((gx, gy), []).append(item)
    return index


def blocking_index(items: Iterable[Scenery]) -> dict:
    """Bucket the solid scenery on a fine grid for `World.blocked`.

    Deliberately finer than the chunk grid the buildings use: a forest chunk holds dozens
    of trunks and `blocked` runs several times per entity per frame, so the lookup has to
    land on a handful of them rather than on the whole wood.
    """
    cell = c.Scenery.INDEX_CELL
    pad = c.Scenery.INDEX_PAD
    index: dict = {}
    for item in items:
        if not item.block_reach:
            continue
        reach = item.block_reach + pad
        for gx in range(int((item.x - reach) // cell), int((item.x + reach) // cell) + 1):
            for gy in range(int((item.y - reach) // cell), int((item.y + reach) // cell) + 1):
                index.setdefault((gx, gy), []).append(item)
    return index


# Everything in here is laid out from the village sites, so all of it has to be forgotten
# when a world registers a settlement the region grid never offered (`village.py`).
for _clear in (
    _roads_from_site.cache_clear,
    _path_from_poi.cache_clear,
    _route_line.cache_clear,
    _route_crossings.cache_clear,
    _dodge_circles.cache_clear,
    _chunk_river.cache_clear,
    _chunk_terrain.cache_clear,
):
    register_site_cache(_clear)
