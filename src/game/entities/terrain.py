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
from collections.abc import Iterable, Iterator, Sequence
from functools import lru_cache
from typing import NamedTuple

import pygame

import core.constants as c
from game.entities.scenery import Scenery
from game.entities.village_sites import register_site_cache, registered_keepouts, settlements_near_chunk


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
    names, values = zip(*weights, strict=True)
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
    return _blobs_in_chunk(cx, cy, _routes_near_chunk(cx, cy))


@lru_cache(maxsize=512)
def road_blobs_for_chunk(cx: int, cy: int) -> tuple[RoadBlob, ...]:
    """The same stretch of packed earth as `road_points_for_chunk`, with the footpaths left
    out: the roads between settlements and nothing else.

    Its own function because a landmark stands down where a road passes (`poi_site`), and
    the footpaths are drawn *from* the landmarks: asking for the whole network there would
    ask a chunk's landmark whether it exists in order to decide whether it exists."""
    return tuple(_blobs_in_chunk(cx, cy, _settlement_routes(cx, cy)))


def _blobs_in_chunk(cx: int, cy: int, routes: list[Route]) -> list[RoadBlob]:
    """The stretch of each of `routes` that falls inside this chunk."""
    size = c.World.CHUNK_SIZE
    bounds = pygame.Rect(cx * size, cy * size, size, size).inflate(c.Scenery.ROAD_WOBBLE * 2, c.Scenery.ROAD_WOBBLE * 2)

    points: list[RoadBlob] = []
    for route in routes:
        line = _route_line(route)
        # Nearly every route in the region misses this chunk entirely, and walking one is
        # hundreds of blobs: the cheap test is worth making before the walk.
        if not line or not _crosses(bounds, (line[0].x, line[0].y), (line[-1].x, line[-1].y)):
            continue
        points.extend(blob for blob in line if bounds.collidepoint(blob.x, blob.y))
    return points


def _settlement_routes(cx: int, cy: int) -> list[Route]:
    """The roads near this chunk: settlement to settlement, no footpaths."""
    routes: dict[tuple, Route] = {}
    for x, y, scx, scy, radius in settlements_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS):
        for route in _roads_from_site(x, y, scx, scy, radius):
            routes[_route_key(route)] = route
    return [routes[key] for key in sorted(routes)]


def _routes_near_chunk(cx: int, cy: int) -> list[Route]:
    """Every route that might cross this chunk, each one asked of the place it leaves from
    rather than of the chunk asking, so two chunks either side of a border never disagree
    about whether a road exists. In route-key order, so every chunk sees them the same way
    round and a crossing shared by two of them is settled the same way in both."""
    routes: dict[tuple, Route] = {_route_key(route): route for route in _settlement_routes(cx, cy)}
    reach = c.Scenery.PATH_CHUNK_RADIUS
    for gx in range(cx - reach, cx + reach + 1):
        for gy in range(cy - reach, cy + reach + 1):
            route = _path_from_poi(gx, gy)
            if route is not None:
                routes[_route_key(route)] = route
    return [routes[key] for key in sorted(routes)]


def road_ends_at(x: float, y: float, cx: int, cy: int) -> tuple[tuple[float, float, float, float], ...]:
    """Where every road leaving this settlement stops, which is the outside of one of its
    gateways (`_approach`), how wide the road is where it stops and which way it runs off
    from there.

    A settlement lays its own lanes out to these (`Village.gateways`): the road stops at
    the grounds the site *could* have reached, since it is drawn from the map rather than
    from a village that may not have been built yet, and only the village itself knows
    where its wall actually stands. The width goes with the point because the lane is worn
    out to it at the road's own width and narrows on the way in: a road is twice a lane
    wide and a track that changed width at the gate read as two tracks meeting there. The
    heading goes with it because the lane laps a width over the road to hide the round cap
    it ends in, and a road that leaves the gate at an angle is not lapped by a lane walking
    backwards along its own straight line."""
    ends = []
    for route in _settlement_routes(cx, cy):
        for at_start, (near, far) in ((True, route[:2]), (False, route[1::-1])):
            if math.dist((near[0], near[1]), (x, y)) >= 1:
                continue
            line = _route_line(route)
            blob = (line[0] if at_start else line[-1]) if line else None
            width = blob.width if blob else float(c.Scenery.ROAD_WIDTH[0])
            away = math.atan2(far[1] - near[1], far[0] - near[0])
            heading = (blob.heading + (0.0 if at_start else math.pi)) if blob else away
            ends.append((*_approach(near[0], near[1], near[2], far[0], far[1]), width, heading))
    return tuple(ends)


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
    from game.entities.poi import poi_footprint, poi_site

    site = poi_site(cx, cy)
    if site is None:
        return None
    x, y, kind = site

    reach = c.Scenery.PATH_CHUNK_RADIUS
    ends: list[Endpoint] = [(sx, sy, radius) for sx, sy, _, _, radius in settlements_near_chunk(cx, cy, reach)]
    for gx in range(cx - reach, cx + reach + 1):
        for gy in range(cy - reach, cy + reach + 1):
            other = poi_site(gx, gy) if (gx, gy) != (cx, cy) else None
            if other is not None:
                ends.append((other[0], other[1], poi_footprint(other[2]) + c.PointsOfInterest.PATH_MARGIN))

    end = min(ends, key=lambda e: math.dist((x, y), (e[0], e[1])), default=None)
    if end is None or math.dist((x, y), (end[0], end[1])) > c.Scenery.PATH_MAX_LENGTH:
        return None
    # A path stops at the edge of what the landmark covers, not at its centre point: aimed
    # at the middle of a graveyard it was laid through the stones.
    return (x, y, poi_footprint(kind) + c.PointsOfInterest.PATH_MARGIN), end, "path"


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
    # How far a road may wander follows how far it is going: two sites a chunk apart have
    # no room to bend, and a road crossing several has to earn its length or it reads as a
    # ruler laid between two villages. Never nothing, though, and never more than a share of
    # the distance: the first left every short road perfectly straight and the second would
    # have a long one wandering back the way it came.
    ramp = max(c.Scenery.ROAD_WOBBLE_FLOOR, min(1.0, length / c.Scenery.ROAD_WOBBLE_FULL))
    amplitude = min(rng.uniform(0.55, 1.0) * c.Scenery.ROAD_WOBBLE * ramp, length * c.Scenery.ROAD_WOBBLE_MAX_FRAC)
    bend_layers = _bend_layers(rng)
    width_lo, width_hi = c.Scenery.PATH_WIDTH if kind == "path" else c.Scenery.ROAD_WIDTH
    base = rng.uniform(width_lo, width_hi)
    swell_phase, edge_phase = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length

    places: list[tuple[float, float, float]] = []
    for step in range(0, int(length), c.Scenery.ROAD_STEP):
        t = step / length
        # Where the road goes: layered noise across the straight line, tapered back into it
        # at each end so it still meets the gate square.
        bend = _bend_at(bend_layers, t) * amplitude * _taper(t)
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


def _bend_layers(rng: random.Random) -> tuple:
    """The layers a route's wander is made of: a handful of offsets per layer, each layer
    twice as fine and half as wide as the one before it.

    A road bent by a sine is a bow, and a bow held at both ends is an arc laid between two
    villages, which is what the map used to be full of. Noise has no shape of its own, so
    what comes out is a track that leans one way, comes back, and hesitates on the way,
    which is what a line worn by feet looks like from above.
    """
    layers = []
    for octave in range(c.Scenery.ROAD_OCTAVES):
        count = c.Scenery.ROAD_BEND_POINTS * 2**octave
        layers.append((tuple(rng.uniform(-1.0, 1.0) for _ in range(count + 1)), 0.5**octave))
    # Normalised, so the amplitude asked for is the amplitude that comes out whatever the
    # layers add up to.
    total = sum(weight for _, weight in layers)
    return tuple((values, weight / total) for values, weight in layers)


def _bend_at(layers: tuple, t: float) -> float:
    """How far off the straight line the route is at `t`, 0 to 1 along it. Each layer is read
    between its two nearest offsets on a smoothstep, so what comes out is a curve rather than
    a set of corners."""
    total = 0.0
    for values, weight in layers:
        span = len(values) - 1
        place = t * span
        i = min(int(place), span - 1)
        f = place - i
        f = f * f * (3 - 2 * f)
        total += (values[i] * (1 - f) + values[i + 1] * f) * weight
    return total


def _taper(t: float) -> float:
    """How much of the bend survives at `t`: all of it down the middle, none of it at either
    end. A road meets a gate square and a landmark head on; everything between those is free
    to wander, which is the opposite of the old pinch that straightened the whole route in
    order to fix its two ends."""
    edge = c.Scenery.ROAD_END_TAPER
    near = min(t, 1.0 - t) / edge
    return min(1.0, max(0.0, near))


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
        # Stood on the road rather than on the middle of the water: a road crossing off the
        # centre of a blob was given a deck shifted sideways off its own line, which the
        # track then ran onto from the side. The span is the wet run's own length as well
        # as the water's width, since a crossing taken at an angle is the longer of the two.
        blob, _water = wet_run[len(wet_run) // 2]
        widest = max(w[2] for _b, w in wet_run)
        run_length = math.dist((wet_run[0][0].x, wet_run[0][0].y), (wet_run[-1][0].x, wet_run[-1][0].y))
        decks.append(Deck(blob.x, blob.y, blob.heading, _deck_length(max(widest * 2, run_length))))

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
    into the water beside one a lane had already laid, the deck that is there is moved onto
    the road and turned along it rather than a second one being built next to it: a bridge
    is where a track meets a river, so the track decides where it stands and which way it
    lies.
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
                # Stood where the road crosses rather than where the lane had already put
                # one: a bridge is where a track meets a river, so the track decides both
                # where it lies and which way. Left where it was, the deck the road was
                # merged into could be a hundred paces upstream of the road that is
                # supposed to be walking over it.
                decks[near] = Deck(deck.x, deck.y, deck.angle, max(decks[near].length, deck.length))
    return roads, _chunk_river(cx, cy)[0], tuple(deck for deck in decks if bounds.collidepoint(deck.x, deck.y))


def _bridge_gap(one: Deck, other: Deck) -> float:
    """How close two crossings are allowed to stand: never nearer than either of them is
    long, and never nearer than `BRIDGE_MIN_GAP` whatever their size."""
    return max(c.Scenery.BRIDGE_MIN_GAP, one.length, other.length)


def _keep_off_zones(buildings, villages, pois) -> tuple[list, list]:
    """The circles nothing solid may stand in, and the circles nothing at all may.

    Reaching past the doorstep as well as past the walls: the clear ground in front of a
    door is the one piece of a building nothing at all may stand on, and it sticks out
    further than the wall clearance does. A landmark keeps the wood off everything it
    covers, not off its centre point: trees grew up between a graveyard's stones when the
    clearance was one number for every kind.
    """
    from game.entities.poi import poi_footprint

    keep_off = max(c.Scenery.CLEARANCE_BUILDING, c.Villages.DOORSTEP_CLEAR)
    solid_zones = [(b.x, b.y, max(b.w, b.h) / 2 + keep_off) for b in buildings]
    solid_zones += [(p.x, p.y, max(c.Scenery.CLEARANCE_POI, poi_footprint(p.kind))) for p in pois]
    open_zones = [(v.x, v.y, v.grounds_radius + c.Scenery.CLEARANCE_VILLAGE) for v in villages]
    return solid_zones, open_zones


def _still_water(cx, cy, rng, biome: str, chunk: tuple[int, int], roads, zones) -> list[Scenery]:
    """The ponds and the lake of one chunk, placed before anything else so nothing is
    planted in them. A pond and a lake are the same thing at two scales, and both are
    crossed the way a river is, so neither is laid where a road already runs."""
    still = []
    size = c.World.CHUNK_SIZE
    for kind, count in (
        ("pond", rng.randint(0, 2) if biome == "wetland" else 0),
        ("lake", 1 if rng.random() < c.Scenery.LAKE_CHANCE[biome] else 0),
    ):
        for _ in range(count):
            x = cx * size + rng.uniform(0, size)
            y = cy * size + rng.uniform(0, size)
            piece = Scenery(x, y, kind, chunk, biome=biome)
            crossed = any(math.hypot(x - blob.x, y - blob.y) < piece.water_reach for blob in roads)
            clear = not any(math.hypot(x - zx, y - zy) < radius for zx, zy, radius in zones)
            if clear and not crossed:
                still.append(piece)
    return still


def _lay_ways(chunk: tuple[int, int], biome: str, roads, river, still, decks, bridges, in_water) -> list[Scenery]:
    """Everything drawn as ground: the roads, the water, and the crossings over it.

    A road between two settlements and a footpath out to a landmark are the same blobs at
    two scales and in two colours: the road is what the player is meant to see from across
    a field and follow, the path is a line worn in the grass. A road stands twice, as its
    verge and as its band, so each is laid down in a pass of its own over the whole chunk:
    a blob that drew both painted its verge over the band of the blob before it (see
    `Scenery._draw_path`). The earth is laid right up to a crossing and under its planks: a
    road that stopped at the bank left the deck's two landings standing on nothing, since a
    deck reaches past the water it spans. Nothing shows for it, a deck being wider than the
    widest road.
    """
    items = [
        Scenery(blob.x, blob.y, kind, chunk, size=blob.width, biome=biome, angle=blob.heading)
        for blob in roads
        if not in_water(blob.x, blob.y) or any(deck.covers(blob.x, blob.y) for deck in decks)
        for kind in (("road_verge", "road") if blob.kind == "road" else (blob.kind,))
    ]
    # Three pieces per body of water, running or still: the water itself, and the two layers
    # of colour drawn in their own passes over it, since one body painting all three would
    # paint over its neighbour (see Scenery.WATER_LAYERS).
    for kind in c.Scenery.WATER_LAYERS["river"]:
        items += [Scenery(x, y, kind, chunk, size=radius, biome=biome) for x, y, radius in river]
    for piece in still:
        items.append(piece)
        items += [
            Scenery(piece.x, piece.y, kind, chunk, biome=biome) for kind in c.Scenery.WATER_LAYERS[piece.kind][1:]
        ]
    # A crossing wherever the lane says so, plus one wherever a road runs into the water:
    # that is where anybody would have built one, and it keeps a road from stopping dead.
    # Both kinds are already in `bridges`, rolled by `_chunk_terrain`; the neighbours' decks
    # were only ever borrowed to keep this chunk's ground clear at the end of one.
    own = {(deck.x, deck.y) for deck in bridges}
    items += [deck for deck in decks if (deck.x, deck.y) in own]
    return items


def _grow_cover(cx, cy, rng, biome: str, chunk: tuple[int, int], roads, villages, is_free) -> list[Scenery]:
    """The biome's own clumps grown over the chunk once the ground is settled.

    In clusters rather than scattered evenly, which is what makes a wood a wood. Decoration
    keeps off a road's band and off a settlement's lanes and plaza, and off nothing else:
    the tufts are drawn over the roads rather than under them, so grass that ignored one
    grew through it, and what a village draws as trodden earth is trodden earth.
    """
    items = []
    size = c.World.CHUNK_SIZE
    for kind, clusters, members, spread in c.Scenery.BIOMES[biome]:
        solid = kind in c.Scenery.BLOCK_RADIUS
        decor = kind in c.Scenery.DECOR_KINDS
        for _ in range(rng.randint(*clusters)):
            gx = cx * size + rng.uniform(0, size)
            gy = cy * size + rng.uniform(0, size)
            for _ in range(rng.randint(*members)):
                x = gx + rng.uniform(-spread, spread)
                y = gy + rng.uniform(-spread, spread)
                if not is_free(x, y, solid):
                    continue
                if decor and any(v.street_at(x, y, c.Scenery.STREET_CLEARANCE) for v in villages):
                    continue
                if decor and any(math.hypot(x - blob.x, y - blob.y) < blob.width for blob in roads):
                    continue
                items.append(Scenery(x, y, kind, chunk, biome=biome))
    return items


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

    Four passes in order, each of which the next one has to be able to see: what is kept
    off, the standing water, the ways over the ground, and the cover grown on what is left.
    """
    rng = random.Random(f"scenery:{cx},{cy}")
    chunk = (cx, cy)

    biome = _pick(c.Scenery.BIOME_WEIGHTS, rng)
    roads, river, bridges = _chunk_terrain(cx, cy)
    # Every deck within reach of this chunk, its own and its neighbours', as ground no
    # trunk or boulder may stand on: a crossing walled in at the end of it is worse than
    # no crossing at all, because the player walked over to use it.
    decks = [
        Scenery(deck.x, deck.y, "bridge", chunk, size=deck.length, biome=biome, angle=deck.angle)
        for ox in (-1, 0, 1)
        for oy in (-1, 0, 1)
        for deck in _chunk_terrain(cx + ox, cy + oy)[2]
    ]
    bridge_zones = [(deck.x, deck.y, deck.block_reach + c.Scenery.BRIDGE_CLEARANCE) for deck in decks]
    solid_zones, open_zones = _keep_off_zones(buildings, villages, pois)

    still = _still_water(cx, cy, rng, biome, chunk, roads, solid_zones + open_zones)
    water = list(river) + [(p.x, p.y, p.water_reach) for p in still]

    def in_water(x: float, y: float, margin: float = 0.0) -> bool:
        return any(math.hypot(x - wx, y - wy) < radius + margin for wx, wy, radius in water)

    def is_free(x: float, y: float, solid: bool) -> bool:
        for zx, zy, radius in solid_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        # Nothing grows out of open water, and a trunk keeps off the bank as well: what
        # blocks must never stand where it would wall a crossing in.
        if in_water(x, y, c.Scenery.RIVER_BANK_CLEARANCE if solid else 0.0):
            return False
        if not solid:
            return True
        for zx, zy, radius in bridge_zones + open_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        return all(math.hypot(x - blob.x, y - blob.y) >= blob.width + c.Scenery.ROAD_CLEARANCE for blob in roads)

    items = _lay_ways(chunk, biome, roads, river, still, decks, bridges, in_water)
    return items + _grow_cover(cx, cy, rng, biome, chunk, roads, villages, is_free)


def index_cells(x: float, y: float, reach: float) -> Iterator[tuple[int, int]]:
    """Every cell of the fine lookup grid something of this size standing here reaches into.

    Deliberately finer than the chunk grid the buildings use: a forest chunk holds dozens of
    trunks and the lookups run several times per entity per frame, so they have to land on a
    handful of pieces rather than on the whole wood."""
    cell = c.Scenery.INDEX_CELL
    for gx in range(int((x - reach) // cell), int((x + reach) // cell) + 1):
        for gy in range(int((y - reach) // cell), int((y + reach) // cell) + 1):
            yield gx, gy


def blocking_cells(item: Scenery) -> Iterator[tuple[int, int]]:
    """Where one solid piece is filed for `World.blocked`. Nothing for a piece that stops
    nobody, which is what a stump and a broken boulder are."""
    if not item.block_reach:
        return
    yield from index_cells(item.x, item.y, item.block_reach + c.Scenery.INDEX_PAD)


def water_cells(item: Scenery) -> Iterator[tuple[int, int]]:
    """The same for water and the bridges over it. A grid of its own because water is the
    opposite of a wall: nothing is stopped by it, everything is slowed in it."""
    if not item.water_reach:
        return
    yield from index_cells(item.x, item.y, item.water_reach + c.Scenery.INDEX_PAD)


# Everything in here is laid out from the village sites, so all of it has to be forgotten
# when a world registers a settlement the region grid never offered (`village_sites.py`).
for _clear in (
    _roads_from_site.cache_clear,
    _path_from_poi.cache_clear,
    _route_line.cache_clear,
    _route_crossings.cache_clear,
    _dodge_circles.cache_clear,
    road_blobs_for_chunk.cache_clear,
    _chunk_river.cache_clear,
    _chunk_terrain.cache_clear,
):
    register_site_cache(_clear)
