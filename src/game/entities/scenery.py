from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Iterable, List, Sequence, Tuple

import pygame

import core.constants as c
from game.entities.village import sites_near_chunk

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

    def __init__(self, x: float, y: float, kind: str, chunk: Tuple[int, int], size: float = 0.0, biome: str = "plain"):
        self.x = x
        self.y = y
        self.kind = kind
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
        if self.kind == "pond":
            return self._roll_pond(rng)
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

    @staticmethod
    def _roll_pond(rng: random.Random) -> dict:
        rx = rng.randint(*c.Scenery.POND_RADIUS)
        ry = round(rx * rng.uniform(0.55, 0.8))
        return {"rx": rx, "ry": ry}

    # ------------------------------------------------------------------ drawing

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        center = (round(sx), round(sy))
        drawer = getattr(self, f"_draw_{self.kind}", None)
        if drawer is not None:
            drawer(screen, center)

    def _draw_path(self, screen, center):
        pygame.draw.circle(screen, c.Scenery.ROAD_COLOR, center, round(self.size))

    def _draw_patch(self, screen, center):
        cx, cy = center
        for ox, oy, scale in self._shape["lobes"]:
            rect = pygame.Rect(0, 0, round(self._shape["rx"] * 2 * scale), round(self._shape["ry"] * 2 * scale))
            rect.center = (round(cx + ox), round(cy + oy))
            pygame.draw.ellipse(screen, self._shape["color"], rect)

    def _draw_pond(self, screen, center):
        rect = pygame.Rect(0, 0, self._shape["rx"] * 2, self._shape["ry"] * 2)
        rect.center = center
        pygame.draw.ellipse(screen, (70, 96, 96), rect)
        pygame.draw.ellipse(screen, (58, 106, 122), rect.inflate(-10, -8))
        pygame.draw.ellipse(screen, (96, 148, 158), rect.inflate(-rect.width // 2, -rect.height // 2))

    def _draw_grass(self, screen, center):
        self._draw_blades(screen, center)

    def _draw_reeds(self, screen, center):
        self._draw_blades(screen, center)

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

    def _draw_tree(self, screen, center):
        self._draw_canopy(screen, center)

    def _draw_pine(self, screen, center):
        self._draw_canopy(screen, center)

    def _draw_canopy(self, screen, center):
        cx, cy = center
        radius = self._shape["radius"]
        shadow = pygame.Rect(0, 0, round(radius * 1.7), round(radius * 1.1))
        shadow.center = (cx + 8, cy + 12)
        pygame.draw.ellipse(screen, (48, 68, 40), shadow)
        pygame.draw.circle(screen, (88, 62, 38), (cx, cy), self._shape["trunk"])
        for ox, oy, r, color in self._shape["lobes"]:
            pygame.draw.circle(screen, color, (round(cx + ox), round(cy + oy)), r)


def _pick(weights: Sequence[Tuple[str, int]], rng: random.Random) -> str:
    names, values = zip(*weights)
    return rng.choices(names, weights=values)[0]


def road_points_for_chunk(cx: int, cy: int) -> List[Tuple[float, float, float]]:
    """The packed earth of every road crossing this chunk, as (x, y, width) blobs.

    Each village site is joined to its nearest neighbour, both sites being pure functions
    of their region, so the same road appears in every chunk it crosses without any
    cross-chunk bookkeeping. The line is bent by a seeded sine so a road reads as a track
    somebody wore into the ground rather than as a ruler laid across the map.
    """
    sites = sites_near_chunk(cx, cy, c.Scenery.ROAD_SITE_CHUNK_RADIUS)
    if len(sites) < 2:
        return []

    edges = set()
    for site in sites:
        nearest = min((other for other in sites if other != site), key=lambda o: math.dist(site, o))
        edges.add(tuple(sorted((site, nearest))))

    size = c.World.CHUNK_SIZE
    bounds = pygame.Rect(cx * size, cy * size, size, size).inflate(c.Scenery.ROAD_WOBBLE * 2, c.Scenery.ROAD_WOBBLE * 2)
    points: List[Tuple[float, float, float]] = []
    for start, end in edges:
        length = math.dist(start, end)
        if length < 1:
            continue
        rng = random.Random(f"road:{start}:{end}")
        phase = rng.uniform(0, 2 * math.pi)
        waves = rng.uniform(1.0, 2.5)
        amplitude = rng.uniform(0.4, 1.0) * c.Scenery.ROAD_WOBBLE
        dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
        for step in range(0, int(length), c.Scenery.ROAD_STEP):
            t = step / length
            bend = math.sin(phase + t * waves * 2 * math.pi) * amplitude * math.sin(math.pi * t)
            x = start[0] + dx * step - dy * bend
            y = start[1] + dy * step + dx * bend
            if not bounds.collidepoint(x, y):
                continue
            width = rng.uniform(*c.Scenery.ROAD_WIDTH)
            points.append((x, y, width))
    return points


def generate_chunk_scenery(
    cx: int,
    cy: int,
    buildings: Iterable,
    villages: Iterable,
    pois: Iterable,
) -> List[Scenery]:
    """Everything growing or lying in one chunk, rolled from its coordinates alone.

    The chunk picks a single biome first, which is what makes a wood a wood: scattering
    every kind evenly over every chunk gives texture, not places. Villages, buildings and
    landmarks push cover away so nothing grows through a wall or over a campfire, and the
    roads through the chunk are laid first so nothing solid ever stands on one.
    """
    rng = random.Random(f"scenery:{cx},{cy}")
    size = c.World.CHUNK_SIZE
    chunk = (cx, cy)

    biome = _pick(c.Scenery.BIOME_WEIGHTS, rng)
    roads = road_points_for_chunk(cx, cy)
    items = [Scenery(x, y, "path", chunk, size=width, biome=biome) for x, y, width in roads]

    # Circles nothing at all may stand in, and circles only solid things are kept out of.
    solid_zones = [(b.x, b.y, max(b.w, b.h) / 2 + c.Scenery.CLEARANCE_BUILDING) for b in buildings]
    solid_zones += [(p.x, p.y, c.Scenery.CLEARANCE_POI) for p in pois]
    open_zones = [(v.x, v.y, v.radius + c.Scenery.CLEARANCE_VILLAGE) for v in villages]

    def free(x: float, y: float, solid: bool) -> bool:
        for zx, zy, radius in solid_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        if not solid:
            return True
        for zx, zy, radius in open_zones:
            if math.hypot(x - zx, y - zy) < radius:
                return False
        for rx, ry, width in roads:
            if math.hypot(x - rx, y - ry) < width + c.Scenery.ROAD_CLEARANCE:
                return False
        return True

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
