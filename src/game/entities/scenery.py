from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from game.entities.village import settlements_near_chunk, sites_near_chunk

if TYPE_CHECKING:
    from core.camera import Camera


class Scenery:
    """One piece of wilderness: a tree, a boulder, a tuft of grass, a pond, a stretch of
    road. Streamed with its chunk and thrown away with it, exactly like the floor details,
    so none of it is saved and nothing the player does can change it.

    Its whole shape is rolled once here, from its world position, and kept: the drawing
    code then only reads it back, so a copse holds still while the camera pans and costs
    nothing per frame beyond the circles it puts on the screen.
    """

    def __init__(
        self,
        x: float,
        y: float,
        kind: str,
        chunk: tuple[int, int],
        size: float = 0.0,
        biome: str = "plain",
        angle: float = 0.0,
    ):
        self.x = x
        self.y = y
        self.kind = kind
        # Only a bridge uses this: which way its deck lies, taken from the river it spans.
        self.angle = angle
        # Only the ground patches read this: everything else looks the same wherever it
        # grows, but the colour of the ground is the whole point of a biome.
        self.biome = biome
        # The chunk that generated this, not the one it happens to stand in: a cluster can
        # spill over a border, and it has to be unloaded by whoever made it.
        self.chunk = chunk
        self.size = size
        self.blocking_radius = c.Scenery.BLOCK_RADIUS.get(kind, 0)
        self.ground = kind in c.Scenery.GROUND_KINDS
        self._shape = self._roll_shape()
        # How far this piece reaches, for the water and bridge lookups: nothing about water
        # blocks, so it needs a footprint of its own rather than borrowing blocking_radius.
        self.water_reach = self._water_reach()

    def _water_reach(self) -> float:
        if self.kind in c.Scenery.WATER_KINDS:
            return self._shape.get("reach", self.size)
        if self.kind == "bridge":
            return max(self.size, c.Scenery.BRIDGE_WIDTH) / 2
        return 0.0

    def covers(self, x: float, y: float) -> bool:
        """Whether this piece of water (or bridge) has that point under it. A pond and a lake
        are ellipses, a river blob and a bridge deck are tested on their own axes; all three
        answer the one question `World.water_at` asks."""
        dx, dy = x - self.x, y - self.y
        if self.kind == "bridge":
            angle = self._shape["angle"]
            along = dx * math.cos(angle) + dy * math.sin(angle)
            across = -dx * math.sin(angle) + dy * math.cos(angle)
            return abs(along) <= self.size / 2 and abs(across) <= c.Scenery.BRIDGE_WIDTH / 2
        if self.kind == "river":
            reach = self.size
            return dx * dx + dy * dy < reach * reach
        if self.kind not in ("pond", "lake"):
            return False
        # A pond is a clutch of overlapping ellipses rather than one: the shape that is
        # swum in has to be the shape that was drawn, so every lobe is asked.
        return any(((dx - ox) / rx) ** 2 + ((dy - oy) / ry) ** 2 < 1.0 for ox, oy, rx, ry in self._shape["lobes"])

    @property
    def canopy_radius(self) -> float:
        """How far the leaves of a tree reach, or 0 for anything that is not a canopy. The
        lobes are rolled out past the radius they were rolled from, so the margin is part
        of the answer rather than a fudge at the call site."""
        if self.kind not in c.Scenery.CANOPY_KINDS:
            return 0.0
        return self._shape["radius"] * c.Scenery.CANOPY_COVER_MARGIN

    def shades(self, x: float, y: float) -> bool:
        """Whether a body standing at (x, y) is under this canopy, and therefore whether the
        canopy has to fade to stay out of its way."""
        reach = self.canopy_radius
        if not reach:
            return False
        dx, dy = x - self.x, y - self.y
        return dx * dx + dy * dy < reach * reach

    def blocks(self, x: float, y: float, radius: float) -> bool:
        # Squared distance rather than hypot: this runs for every solid thing near every
        # entity's every step, and a wood holds a lot more of them than a village holds
        # buildings.
        if not self.blocking_radius:
            return False
        dx, dy = self.x - x, self.y - y
        reach = self.blocking_radius + radius
        return dx * dx + dy * dy < reach * reach

    # ------------------------------------------------------------------ shape

    def _roll_shape(self) -> dict:
        rng = random.Random(f"{self.kind}:{round(self.x)},{round(self.y)}")
        if self.kind in ("tree", "pine"):
            return self._roll_canopy(rng)
        if self.kind == "boulder":
            return self._roll_boulder(rng)
        if self.kind in ("grass", "reeds"):
            return self._roll_blades(rng)
        if self.kind == "flowers":
            return self._roll_flowers(rng)
        if self.kind == "pebbles":
            return self._roll_pebbles(rng)
        if self.kind in ("pond", "lake"):
            return self._roll_pond(rng, c.Scenery.LAKE_RADIUS if self.kind == "lake" else c.Scenery.POND_RADIUS)
        if self.kind == "bridge":
            return self._roll_bridge(rng)
        if self.kind == "patch":
            return self._roll_patch(rng)
        if self.kind == "stump":
            return {"radius": rng.randint(11, 15), "rings": rng.randint(2, 3)}
        return {}

    def _roll_canopy(self, rng: random.Random) -> dict:
        pine = self.kind == "pine"
        radius = rng.randint(34, 52) if not pine else rng.randint(28, 40)
        base = (46, 96, 44) if not pine else (34, 72, 52)
        lobes = []
        for _ in range(5 if not pine else 4):
            ox = rng.uniform(-radius * 0.45, radius * 0.45)
            oy = rng.uniform(-radius * 0.45, radius * 0.45)
            r = round(radius * rng.uniform(0.55, 0.8))
            shade = rng.randint(-14, 16)
            color = tuple(max(0, min(255, v + shade)) for v in base)
            lobes.append((ox, oy, r, color))
        # Sorted so the biggest lobes go down first and the small bright ones read as the
        # lit top of the canopy rather than being buried under them.
        lobes.sort(key=lambda lobe: -lobe[2])
        return {"radius": radius, "lobes": lobes, "trunk": rng.randint(7, 10)}

    @staticmethod
    def _roll_boulder(rng: random.Random) -> dict:
        radius = rng.randint(26, 38)
        points = []
        count = rng.randint(6, 8)
        for i in range(count):
            angle = 2 * math.pi * i / count + rng.uniform(-0.15, 0.15)
            r = radius * rng.uniform(0.78, 1.0)
            points.append((math.cos(angle) * r, math.sin(angle) * r))
        grey = rng.randint(122, 148)
        return {"points": points, "color": (grey, grey - 4, grey - 12), "radius": radius}

    def _roll_blades(self, rng: random.Random) -> dict:
        reeds = self.kind == "reeds"
        blades = []
        for _ in range(rng.randint(4, 7)):
            ox = rng.uniform(-11, 11)
            height = rng.randint(9, 15) if not reeds else rng.randint(18, 28)
            lean = rng.uniform(-4, 4)
            green = (74, 122, 58) if not reeds else (96, 118, 62)
            shade = rng.randint(-12, 14)
            blades.append((ox, height, lean, tuple(max(0, min(255, v + shade)) for v in green)))
        return {"blades": blades}

    @staticmethod
    def _roll_flowers(rng: random.Random) -> dict:
        palette = ((226, 214, 96), (222, 128, 156), (168, 150, 226), (232, 236, 226))
        color = rng.choice(palette)
        heads = [(rng.uniform(-13, 13), rng.uniform(-10, 10), rng.randint(2, 4)) for _ in range(rng.randint(4, 7))]
        return {"color": color, "heads": heads}

    @staticmethod
    def _roll_pebbles(rng: random.Random) -> dict:
        stones = []
        for _ in range(rng.randint(3, 5)):
            grey = rng.randint(118, 142)
            stones.append((rng.uniform(-14, 14), rng.uniform(-9, 9), rng.randint(3, 6), (grey, grey, grey - 6)))
        return {"stones": stones}

    def _roll_patch(self, rng: random.Random) -> dict:
        rx = rng.randint(*c.Scenery.PATCH_RADIUS)
        ry = round(rx * rng.uniform(0.5, 0.85))
        shades = c.Scenery.PATCH_COLORS[self.biome]
        mult = shades[rng.randrange(len(shades))]
        color = tuple(max(0, min(255, round(c.Colors.GREEN[i] * mult[i]))) for i in range(3))
        # A couple of lobes rather than one clean ellipse, so the edge of a patch reads as
        # ground giving way to other ground and not as a painted circle.
        lobes = [(0.0, 0.0, 1.0)]
        for _ in range(rng.randint(1, 3)):
            lobes.append((rng.uniform(-rx * 0.6, rx * 0.6), rng.uniform(-ry * 0.6, ry * 0.6), rng.uniform(0.4, 0.7)))
        return {"rx": rx, "ry": ry, "color": color, "lobes": lobes}

    def _roll_pond(self, rng: random.Random, radius: tuple) -> dict:
        """Still water as a clutch of overlapping ellipses. One clean ellipse gave every
        pond and every lake on the map the same egg, which reads as a decal dropped on the
        ground rather than as a shore."""
        lake = self.kind == "lake"
        rx = rng.randint(*radius)
        ry = round(rx * rng.uniform(0.55, 0.85))
        lobes = [(0.0, 0.0, float(rx), float(ry))]
        for _ in range(rng.randint(2, 4) if lake else rng.randint(1, 3)):
            lx = rx * rng.uniform(0.4, 0.75)
            ly = ry * rng.uniform(0.45, 0.9)
            lobes.append((rng.uniform(-rx * 0.7, rx * 0.7), rng.uniform(-ry * 0.7, ry * 0.7), lx, ly))
        reach = max(max(abs(ox) + lx, abs(oy) + ly) for ox, oy, lx, ly in lobes)
        return {"lobes": lobes, "reach": reach}

    def _roll_bridge(self, rng: random.Random) -> dict:
        planks = [(t, rng.uniform(-2, 2)) for t in range(-4, 5)]
        return {"angle": self.angle, "planks": planks}

    # ------------------------------------------------------------------ drawing

    def draw(self, screen: pygame.Surface, camera: Camera, alpha: int = 255):
        """`alpha` under 255 is a canopy with something standing under it: the tree is drawn
        onto its own small layer and blitted see-through, so whatever is walking beneath it
        is never lost behind the leaves."""
        sx, sy = camera.world_to_screen(self.x, self.y)
        center = (round(sx), round(sy))
        drawer = _DRAWERS.get(self.kind)
        if drawer is None:
            return
        if alpha >= 255:
            drawer(self, screen, center)
            return
        reach = round(self.canopy_radius) + 20
        layer = pygame.Surface((reach * 2, reach * 2), pygame.SRCALPHA)
        drawer(self, layer, (reach, reach))
        layer.set_alpha(alpha)
        screen.blit(layer, (center[0] - reach, center[1] - reach))

    def _draw_path(self, screen, center):
        pygame.draw.circle(screen, c.Scenery.ROAD_COLOR, center, round(self.size))

    def _draw_patch(self, screen, center):
        cx, cy = center
        for ox, oy, scale in self._shape["lobes"]:
            rect = pygame.Rect(0, 0, round(self._shape["rx"] * 2 * scale), round(self._shape["ry"] * 2 * scale))
            rect.center = (round(cx + ox), round(cy + oy))
            pygame.draw.ellipse(screen, self._shape["color"], rect)

    def _draw_pond(self, screen, center):
        # Bank, then body, then deep, each in one pass over every lobe. Drawing all three
        # per lobe would let the next lobe's bank paint over the last lobe's middle, which
        # is the artefact that made a river read as a row of scales.
        cx, cy = center
        for color, scale in zip(c.Scenery.WATER_COLORS, (1.0, 0.9, 0.5)):
            for ox, oy, rx, ry in self._shape["lobes"]:
                rect = pygame.Rect(0, 0, max(2, round(rx * 2 * scale)), max(2, round(ry * 2 * scale)))
                rect.center = (round(cx + ox), round(cy + oy))
                pygame.draw.ellipse(screen, color, rect)

    def _draw_lake(self, screen, center):
        self._draw_pond(screen, center)

    def _draw_river(self, screen, center):
        # One blob of the course, and only its bank: the body and the deep middle stand at
        # the same points as their own kinds and are laid down in their own passes (see
        # c.Scenery.GROUND_KINDS). Blobs sit well inside each other's width, so a blob that
        # drew all three layers itself would paint its bank over its neighbour's middle.
        pygame.draw.circle(screen, c.Scenery.WATER_COLORS[0], center, round(self.size))

    def _draw_river_body(self, screen, center):
        pygame.draw.circle(screen, c.Scenery.WATER_COLORS[1], center, round(self.size * 0.84))

    def _draw_river_deep(self, screen, center):
        pygame.draw.circle(screen, c.Scenery.WATER_COLORS[2], center, round(self.size * 0.52))

    def _draw_bridge(self, screen, center):
        cx, cy = center
        angle = self._shape["angle"]
        along = (math.cos(angle), math.sin(angle))
        across = (-math.sin(angle), math.cos(angle))
        half_len = self.size / 2
        half_wid = c.Scenery.BRIDGE_WIDTH / 2

        def point(a, b):
            return (round(cx + along[0] * a + across[0] * b), round(cy + along[1] * a + across[1] * b))

        deck = [
            point(-half_len, -half_wid),
            point(half_len, -half_wid),
            point(half_len, half_wid),
            point(-half_len, half_wid),
        ]
        pygame.draw.polygon(screen, c.Scenery.BRIDGE_COLOR, deck)
        for step, jitter in self._shape["planks"]:
            offset = step * half_len / 4.5 + jitter
            pygame.draw.line(screen, c.Scenery.BRIDGE_PLANK_COLOR, point(offset, -half_wid), point(offset, half_wid), 2)
        for side in (-half_wid, half_wid):
            pygame.draw.line(screen, c.Scenery.BRIDGE_RAIL_COLOR, point(-half_len, side), point(half_len, side), 4)

    def _draw_blades(self, screen, center):
        cx, cy = center
        for ox, height, lean, color in self._shape["blades"]:
            start = (round(cx + ox), cy)
            pygame.draw.line(screen, color, start, (round(cx + ox + lean), round(cy - height)), 2)

    def _draw_flowers(self, screen, center):
        cx, cy = center
        for ox, oy, r in self._shape["heads"]:
            pos = (round(cx + ox), round(cy + oy))
            pygame.draw.line(screen, (72, 112, 56), pos, (pos[0], pos[1] + 6), 1)
            pygame.draw.circle(screen, self._shape["color"], pos, r)

    def _draw_pebbles(self, screen, center):
        cx, cy = center
        for ox, oy, r, color in self._shape["stones"]:
            pygame.draw.circle(screen, color, (round(cx + ox), round(cy + oy)), r)

    def _draw_stump(self, screen, center):
        radius = self._shape["radius"]
        pygame.draw.circle(screen, (104, 76, 48), center, radius)
        pygame.draw.circle(screen, (74, 52, 32), center, radius, 2)
        for ring in range(1, self._shape["rings"] + 1):
            pygame.draw.circle(screen, (128, 96, 62), center, round(radius * ring / (self._shape["rings"] + 1)), 1)

    def _draw_boulder(self, screen, center):
        cx, cy = center
        points = [(cx + px, cy + py) for px, py in self._shape["points"]]
        shadow = [(x + 4, y + 6) for x, y in points]
        pygame.draw.polygon(screen, (52, 62, 44), shadow)
        pygame.draw.polygon(screen, self._shape["color"], points)
        pygame.draw.polygon(screen, tuple(round(v * 0.66) for v in self._shape["color"]), points, 2)
        highlight = [(cx + px * 0.45 - 4, cy + py * 0.45 - 5) for px, py in self._shape["points"]]
        pygame.draw.polygon(screen, tuple(min(255, round(v * 1.16)) for v in self._shape["color"]), highlight)

    def _draw_canopy(self, screen, center):
        cx, cy = center
        radius = self._shape["radius"]
        shadow = pygame.Rect(0, 0, round(radius * 1.7), round(radius * 1.1))
        shadow.center = (cx + 8, cy + 12)
        pygame.draw.ellipse(screen, (48, 68, 40), shadow)
        pygame.draw.circle(screen, (88, 62, 38), (cx, cy), self._shape["trunk"])
        for ox, oy, r, color in self._shape["lobes"]:
            pygame.draw.circle(screen, color, (round(cx + ox), round(cy + oy)), r)


# What draws each kind of scenery. An explicit table rather than a name looked up off the
# kind, so a search for "_draw_boulder" finds both where it is written and where it is
# used, and a kind with nothing to draw is simply absent. Grass and reeds are the same
# blades, a tree and a pine the same canopy: only the shape rolled for them differs.
_DRAWERS = {
    "path": Scenery._draw_path,
    "patch": Scenery._draw_patch,
    "pond": Scenery._draw_pond,
    "lake": Scenery._draw_lake,
    "river": Scenery._draw_river,
    "river_body": Scenery._draw_river_body,
    "river_deep": Scenery._draw_river_deep,
    "bridge": Scenery._draw_bridge,
    "grass": Scenery._draw_blades,
    "reeds": Scenery._draw_blades,
    "flowers": Scenery._draw_flowers,
    "pebbles": Scenery._draw_pebbles,
    "stump": Scenery._draw_stump,
    "boulder": Scenery._draw_boulder,
    "tree": Scenery._draw_canopy,
    "pine": Scenery._draw_canopy,
}


def _pick(weights: Sequence[tuple[str, int]], rng: random.Random) -> str:
    names, values = zip(*weights)
    return rng.choices(names, weights=values)[0]


Endpoint = tuple[float, float, float]  # x, y, how much of the far end is left alone
Route = tuple[Endpoint, Endpoint, str]  # from, to, "road" or "path"


def road_points_for_chunk(cx: int, cy: int) -> list[tuple[float, float, float]]:
    """The packed earth of every road and footpath crossing this chunk, as (x, y, width).

    The network is drawn from three pure functions of the coordinates (`village_site`,
    `site_grounds_radius`, `poi_site`), so the same track appears in every chunk it crosses
    with no cross-chunk bookkeeping: a chunk works out which routes come near it and lays
    down the stretch that falls inside its own bounds.

    Routing is three rules. A road stops at the gate side of a settlement's grounds instead
    of running through its houses and its wall; anywhere it would pass through a third
    settlement it bows around it (`_dodge_grounds`); and nothing solid is ever generated
    within `ROAD_CLEARANCE` of a blob, which is what keeps a wood from growing across a
    road rather than the road having to pick its way through the wood.
    """
    size = c.World.CHUNK_SIZE
    bounds = pygame.Rect(cx * size, cy * size, size, size).inflate(c.Scenery.ROAD_WOBBLE * 2, c.Scenery.ROAD_WOBBLE * 2)
    sites = settlements_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS)

    points: list[tuple[float, float, float]] = []
    for route in _routes_near_chunk(cx, cy):
        points.extend(_route_blobs(route, bounds, sites))
    return points


def _routes_near_chunk(cx: int, cy: int) -> list[Route]:
    """Every route that might cross this chunk, each one asked of the place it leaves from
    rather than of the chunk asking, so two chunks either side of a border never disagree
    about whether a road exists."""
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
    return list(routes.values())


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


def _route_blobs(route: Route, bounds: pygame.Rect, sites) -> list[tuple[float, float, float]]:
    """One route's packed earth, or nothing at all when it stays clear of this chunk.

    The line is bent by a seeded sine so a road reads as a track somebody wore into the
    ground rather than as a ruler laid across the map, pinched back to nothing at each end
    so it still meets what it joins.
    """
    (ax, ay, a_clear), (bx, by, b_clear), kind = route
    start = _approach(ax, ay, a_clear, bx, by)
    end = _approach(bx, by, b_clear, ax, ay)
    length = math.dist(start, end)
    if length < 1 or not _crosses(bounds, start, end):
        return []

    rng = random.Random(f"{kind}:{start}:{end}")
    phase = rng.uniform(0, 2 * math.pi)
    waves = rng.uniform(0.8, 1.8)
    # How far a road may wander follows how far it is going: two sites a chunk apart have
    # no room to bend, and a road crossing several has to earn its length or it reads as a
    # ruler laid between two villages.
    amplitude = rng.uniform(0.55, 1.0) * c.Scenery.ROAD_WOBBLE * min(1.0, length / c.Scenery.ROAD_WOBBLE_FULL)
    detail_phase = rng.uniform(0, 2 * math.pi)
    detail_waves = rng.uniform(4.0, 7.0)
    width_range = c.Scenery.PATH_WIDTH if kind == "path" else c.Scenery.ROAD_WIDTH
    dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length

    points: list[tuple[float, float, float]] = []
    for step in range(0, int(length), c.Scenery.ROAD_STEP):
        t = step / length
        # One long wave for where the road goes, a shorter one over it for how it got there.
        bend = math.sin(phase + t * waves * 2 * math.pi) * amplitude
        bend += math.sin(detail_phase + t * detail_waves * 2 * math.pi) * amplitude * c.Scenery.ROAD_DETAIL
        bend *= math.sin(math.pi * t)
        x = start[0] + dx * step - dy * bend
        y = start[1] + dy * step + dx * bend
        if not bounds.collidepoint(x, y):
            continue
        x, y = _dodge_grounds(x, y, -dy, dx, sites, route)
        points.append((x, y, rng.uniform(*width_range)))
    return points


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


def _dodge_grounds(x: float, y: float, nx: float, ny: float, sites, route: Route) -> tuple[float, float]:
    """Push a point of road out of any settlement's grounds it would otherwise run through,
    sideways along the road's own normal.

    Its two ends are exempt: a road is *meant* to arrive at those, and it already stops at
    their gate. Anything else in the way is a third village the track never had any reason
    to be cut through."""
    for sx, sy, _, _, radius in sites:
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


def river_points_for_chunk(cx: int, cy: int) -> tuple[Blobs, Blobs]:
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
    sites = sites_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS)

    water: list[tuple[float, float, float]] = []
    bridges: list[tuple[float, float, float]] = []
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
                    bridges.append((x, y, flow + math.pi / 2, _deck_length(width)))
    return water, bridges


def _dodge_villages(x: float, y: float, axis: int, sites: Sequence[tuple[int, int]]) -> tuple[float, float]:
    """Push a point of river out of any settlement it would run through, sideways.

    A river that stops at the village wall and starts again past it reads as two rivers;
    one that bows around the place reads as why the place is there. The push is faded out
    over the length of the bow rather than applied wherever the point happens to be inside
    the circle, since a course that snapped back to its lane the instant it cleared the
    last house left a notch cut out of the water."""
    clearance = c.Scenery.RIVER_VILLAGE_CLEARANCE
    for sx, sy in sites:
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


def _road_crossings(roads, river, bridges) -> list[tuple[float, float, float, float]]:
    """A bridge wherever a road runs into a river, one per crossing.

    A road that stops at the bank and picks up on the far side is a road nobody built, so
    the crossing is put where the two lines meet. Anywhere the lane's own bridges already
    cover is left alone."""
    if not roads or not river:
        return []
    found: list[tuple[float, float, float, float]] = []
    taken = list(bridges)
    for i, (rx, ry, _) in enumerate(roads):
        wet = min(river, key=lambda blob: math.hypot(rx - blob[0], ry - blob[1]))
        if math.hypot(rx - wet[0], ry - wet[1]) > wet[2]:
            continue
        if any(math.hypot(wet[0] - bx, wet[1] - by) < _deck_length(wet[2] * 2) for bx, by, _, _ in taken):
            continue
        # The deck lies along the road, which is what makes it a crossing rather than a
        # plank dropped in the water at whatever angle the lane runs.
        heading = _road_heading(roads, i)
        if heading is None:
            continue
        found.append((wet[0], wet[1], heading, _deck_length(wet[2] * 2)))
        taken.append(found[-1])
    return found


def _road_heading(roads, i: int) -> float | None:
    """Which way the road is running at point `i`, taken from the next point far enough
    along it to give a direction. Road blobs are laid closer together than they are wide,
    so the next one along says nothing on its own."""
    x, y, _ = roads[i]
    for j in range(i + 1, min(i + 12, len(roads))):
        ox, oy, _ = roads[j]
        dist = math.hypot(ox - x, oy - y)
        if 20 < dist < 200:
            return math.atan2(oy - y, ox - x)
    return None


@lru_cache(maxsize=256)
def _chunk_terrain(cx: int, cy: int) -> tuple[tuple, tuple, tuple]:
    """One chunk's roads, river and crossings, as (road blobs, water blobs, bridges).

    Kept because a chunk needs its neighbours' bridges as well as its own: nothing solid
    may stand at the end of a deck, and a deck laid near a chunk seam is walked onto from
    the chunk next door, so nine of these are asked per chunk loaded and each answer is
    reused by eight of them. All of it is a pure function of the coordinates like the
    scenery it feeds, so a chunk streaming back in costs the lookup and nothing more.
    """
    roads = tuple(road_points_for_chunk(cx, cy))
    river, lane_bridges = river_points_for_chunk(cx, cy)
    bridges = tuple(lane_bridges) + tuple(_road_crossings(roads, river, lane_bridges))
    return roads, tuple(river), bridges


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
        (bx, by, math.hypot(length, c.Scenery.BRIDGE_WIDTH) / 2 + c.Scenery.BRIDGE_CLEARANCE)
        for ox in (-1, 0, 1)
        for oy in (-1, 0, 1)
        for bx, by, _, length in _chunk_terrain(cx + ox, cy + oy)[2]
    ]

    # Circles nothing at all may stand in, and circles only solid things are kept out of.
    solid_zones = [(b.x, b.y, max(b.w, b.h) / 2 + c.Scenery.CLEARANCE_BUILDING) for b in buildings]
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
            if clear_of_places(x, y) and not any(math.hypot(x - rx, y - ry) < piece.water_reach for rx, ry, _ in roads):
                still.append(piece)

    water = list(river) + [(p.x, p.y, p.water_reach) for p in still]

    def in_water(x: float, y: float, margin: float = 0.0) -> bool:
        return any(math.hypot(x - wx, y - wy) < radius + margin for wx, wy, radius in water)

    items = [Scenery(x, y, "path", chunk, size=width, biome=biome) for x, y, width in roads if not in_water(x, y)]
    # Three pieces per blob of river: the water itself, and the two layers of colour that
    # are drawn in their own passes over it, since one blob painting all three would paint
    # over its neighbour (see Scenery._draw_river).
    for kind in ("river", "river_body", "river_deep"):
        items += [Scenery(x, y, kind, chunk, size=radius, biome=biome) for x, y, radius in river]
    items += still
    # A crossing wherever the lane says so, plus one wherever a road runs into the water:
    # that is where anybody would have built one, and it keeps a road from stopping dead.
    # Both kinds are already in `bridges`, rolled by `_chunk_terrain`.
    for bx, by, angle, length in bridges:
        items.append(Scenery(bx, by, "bridge", chunk, size=length, biome=biome, angle=angle))

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
        return all(math.hypot(x - rx, y - ry) >= width + c.Scenery.ROAD_CLEARANCE for rx, ry, width in roads)

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
        if not item.blocking_radius:
            continue
        reach = item.blocking_radius + pad
        for gx in range(int((item.x - reach) // cell), int((item.x + reach) // cell) + 1):
            for gy in range(int((item.y - reach) // cell), int((item.y + reach) // cell) + 1):
                index.setdefault((gx, gy), []).append(item)
    return index
