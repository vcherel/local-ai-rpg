from __future__ import annotations

import math
import random
from functools import lru_cache
from typing import TYPE_CHECKING, List, Optional, Tuple

import pygame

import core.constants as c
from game.entities.buildings import Building

if TYPE_CHECKING:
    from core.camera import Camera


class Village:
    """A cluster of buildings around an open plaza, the shape every settlement takes.

    The village itself owns nothing but the plaza: its buildings live in the world's one
    building list like any other, so collision, interiors, NPCs and saving all work exactly
    as they did when the world had a single scattered town. What this class adds is the
    centre the cluster is built around, the name the LLM gives it, and whether the player
    has walked into it yet.
    """

    def __init__(self, x, y, chunk: Tuple[int, int], size: str = "village", radius: int = 700, extent: int = 0):
        self.x = x
        self.y = y
        # The chunk that owns this village, and its identity in the save: a chunk that
        # already has one never generates a second.
        self.chunk = (int(chunk[0]), int(chunk[1]))
        self.size = size
        self.radius = radius
        self.name: Optional[str] = None
        self.discovered = False
        # Whether this one stands a palisade. Rolled from the size when the settlement is
        # built and then persisted, like everything else about a village: the wall is part
        # of what the place is, not something rederived from a seed.
        self.defended = size in c.Villages.WALLED_SIZES
        # How far the outermost wall of the outermost building stands from the middle. The
        # palisade is set from this rather than from `radius`, which is a diagonal and would
        # leave a field of nothing between the last house and the wall.
        self.extent = extent or radius
        self._defences = None

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    @property
    def grounds_radius(self) -> float:
        """How far the settlement's grounds reach. A walled town's grounds run out to its
        palisade, not to the last house inside it: the wall, its towers and whoever is
        posted on them are part of the place, so the same one call decides who turns on the
        player, who defends it, where nothing hostile may be stood up and how far the trees
        are cut back."""
        if not self.defended:
            return self.radius
        return max(self.radius, self.extent + c.Villages.WALL_MARGIN + c.Villages.TOWER_RADIUS)

    def contains_point(self, x, y) -> bool:
        return math.hypot(self.x - x, self.y - y) <= self.grounds_radius

    def defences(self) -> dict:
        """The palisade: its wall segments, the middle of each gate, and its towers. Built
        once from the village's own radius, so nothing about it has to be saved.

        A square ring split by four gates, rather than an unbroken circle, for two reasons:
        a chaser routes round a rectangle already (`World._detour_corner`), and a gate on
        every side means walling a town in never turns an approach into a dead end."""
        if self._defences is not None:
            return self._defences
        if not self.defended:
            self._defences = {"walls": [], "gates": [], "towers": []}
            return self._defences

        half = self.extent + c.Villages.WALL_MARGIN
        thickness = c.Villages.WALL_THICKNESS
        gate = c.Villages.GATE_WIDTH
        run = (2 * half - gate) / 2  # one stretch of wall, gate to corner
        walls, gates, towers = [], [], []
        for nx, ny in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            # The middle of this side, and the two stretches either side of its gateway.
            mid = (self.x + nx * half, self.y + ny * half)
            gates.append(mid)
            for side in (-1, 1):
                offset = side * (gate / 2 + run / 2)
                if nx:
                    rect = pygame.Rect(0, 0, thickness, run)
                    rect.center = (round(mid[0]), round(mid[1] + offset))
                else:
                    rect = pygame.Rect(0, 0, run, thickness)
                    rect.center = (round(mid[0] + offset), round(mid[1]))
                walls.append(rect)
        for cx in (-1, 1):
            for cy in (-1, 1):
                towers.append((self.x + cx * half, self.y + cy * half))
        self._defences = {"walls": walls, "gates": gates, "towers": towers}
        return self._defences

    def blocks(self, x, y, radius) -> bool:
        """The well in the middle of the plaza is solid, and so is the palisade around a
        walled town; everything else in a village is a building, collided against by the
        buildings themselves."""
        if math.hypot(self.x - x, self.y - y) < c.Villages.WELL_RADIUS + radius:
            return True
        if not self.defended:
            return False
        defences = self.defences()
        for tower in defences["towers"]:
            if math.hypot(tower[0] - x, tower[1] - y) < c.Villages.TOWER_RADIUS + radius:
                return True
        for wall in defences["walls"]:
            nearest_x = min(max(x, wall.left), wall.right)
            nearest_y = min(max(y, wall.top), wall.bottom)
            if math.hypot(x - nearest_x, y - nearest_y) < radius:
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "chunk": list(self.chunk),
            "size": self.size,
            "radius": self.radius,
            "extent": self.extent,
            "name": self.name,
            "discovered": self.discovered,
            "defended": self.defended,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Village:
        village = cls(
            data["x"],
            data["y"],
            data["chunk"],
            data.get("size", "village"),
            data.get("radius", 700),
            data.get("extent", 0),
        )
        village.name = data.get("name")
        village.discovered = data.get("discovered", False)
        village.defended = data.get("defended", village.defended)
        return village

    def draw(self, screen: pygame.Surface, camera: Camera):
        """The plaza: packed earth and a well. The name is the minimap strip's job; written on
        the ground it was one more label lying over the street."""
        cx, cy = camera.world_to_screen(self.x, self.y)
        plaza = pygame.Rect(0, 0, c.Villages.PLAZA_RADIUS * 2, round(c.Villages.PLAZA_RADIUS * 1.5))
        plaza.center = (round(cx), round(cy))
        pygame.draw.ellipse(screen, c.Villages.PLAZA_COLOR, plaza)

        # Trodden earth around the edge of the plaza, seeded from the village position so
        # it holds still as the camera pans.
        rng = random.Random(f"plaza:{self.x},{self.y}")
        darker = tuple(round(v * 0.88) for v in c.Villages.PLAZA_COLOR)
        for _ in range(14):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(0.4, 1.0)
            px = cx + math.cos(angle) * plaza.width / 2 * dist
            py = cy + math.sin(angle) * plaza.height / 2 * dist
            pygame.draw.circle(screen, darker, (round(px), round(py)), rng.randint(4, 11))

        self._draw_well(screen, (round(cx), round(cy)))
        self._draw_defences(screen, camera)

    def _draw_defences(self, screen: pygame.Surface, camera: Camera):
        """The palisade and its towers, drawn under everything that walks over the ground.
        Stakes along the top of each stretch, so a wall reads as a row of sharpened logs
        rather than as a brown bar, and a gate reads as a gap with a post either side."""
        defences = self.defences()
        if not defences["walls"]:
            return

        for wall in defences["walls"]:
            sx, sy = camera.world_to_screen(wall.left, wall.top)
            rect = pygame.Rect(round(sx), round(sy), wall.width, wall.height)
            pygame.draw.rect(screen, c.Villages.WALL_COLOR, rect)
            along_x = rect.width > rect.height
            span = rect.width if along_x else rect.height
            for offset in range(4, span - 4, 14):
                log = (
                    pygame.Rect(rect.left + offset, rect.top, 10, rect.height)
                    if along_x
                    else pygame.Rect(rect.left, rect.top + offset, rect.width, 10)
                )
                pygame.draw.rect(screen, c.Villages.WALL_TOP, log)
                pygame.draw.rect(screen, (74, 56, 38), log, 1)
            pygame.draw.rect(screen, (68, 52, 34), rect, 2)

        # The gateposts: the ends of the two stretches either side of each gap, marked so a
        # way through is visible from across the field.
        for gx, gy in defences["gates"]:
            sx, sy = camera.world_to_screen(gx, gy)
            for side in (-1, 1):
                horizontal = abs(gx - self.x) < abs(gy - self.y)
                post = pygame.Rect(0, 0, 14, 14)
                shift = side * c.Villages.GATE_WIDTH / 2
                post.center = (round(sx + shift), round(sy)) if horizontal else (round(sx), round(sy + shift))
                pygame.draw.rect(screen, c.Villages.GATE_POST, post)
                pygame.draw.rect(screen, (52, 40, 28), post, 2)

        for tx, ty in defences["towers"]:
            sx, sy = camera.world_to_screen(tx, ty)
            radius = c.Villages.TOWER_RADIUS
            pygame.draw.circle(screen, (60, 52, 44), (round(sx), round(sy)), radius + 3)
            pygame.draw.circle(screen, c.Villages.TOWER_STONE, (round(sx), round(sy)), radius)
            pygame.draw.circle(screen, (104, 100, 94), (round(sx), round(sy)), round(radius * 0.6))
            # Crenellations, read from above as blocks around the rim.
            for i in range(8):
                angle = i * math.pi / 4
                block = pygame.Rect(0, 0, 14, 14)
                block.center = (round(sx + math.cos(angle) * radius), round(sy + math.sin(angle) * radius))
                pygame.draw.rect(screen, (168, 164, 156), block)
                pygame.draw.rect(screen, (70, 66, 60), block, 1)

    @staticmethod
    def _draw_well(screen: pygame.Surface, center):
        cx, cy = center
        radius = c.Villages.WELL_RADIUS
        pygame.draw.circle(screen, c.Villages.WELL_STONE, (cx, cy), radius)
        pygame.draw.circle(screen, (92, 90, 84), (cx, cy), radius, 3)
        pygame.draw.circle(screen, (40, 58, 74), (cx, cy), radius - 10)
        # Two posts and the beam they carry, read from above as a bar across the shaft.
        for side in (-1, 1):
            post = pygame.Rect(0, 0, 8, radius * 2 + 10)
            post.center = (cx + side * (radius - 4), cy)
            pygame.draw.rect(screen, (96, 68, 42), post)
        beam = pygame.Rect(0, 0, radius * 2 + 6, 8)
        beam.center = (cx, cy - radius - 2)
        pygame.draw.rect(screen, (120, 86, 52), beam)


@lru_cache(maxsize=4096)
def _region_site(rx: int, ry: int) -> Optional[Tuple[int, int, int, int]]:
    """The chunk one region settles and where in it, as (cx, cy, x, y), or None for an empty
    region. Pure function of the region coordinates."""
    region = c.Villages.REGION_CHUNKS
    rng = random.Random(f"village:{rx},{ry}")
    if rng.random() > c.Villages.REGION_CHANCE:
        return None

    cx = rx * region + rng.randrange(region)
    cy = ry * region + rng.randrange(region)
    size = c.World.CHUNK_SIZE
    margin = c.Villages.CHUNK_MARGIN
    x = cx * size + rng.randint(margin, size - margin)
    y = cy * size + rng.randint(margin, size - margin)

    center = c.World.WORLD_SIZE // 2
    if math.hypot(x - center, y - center) < c.Villages.MIN_DIST_FROM_SPAWN:
        return None
    return cx, cy, x, y


@lru_cache(maxsize=4096)
def village_site(cx: int, cy: int) -> Optional[Tuple[int, int]]:
    """Where the village belonging to chunk (cx, cy) stands, or None if it holds none.

    One region of REGION_CHUNKS x REGION_CHUNKS chunks settles a single chunk, and a region
    whose site lands too close to a neighbouring region's yields to it, so two settlements
    can't end up back to back across a region border. All of it is a pure function of the
    coordinates: the same chunk always offers the same site, whether or not the village
    behind it has been generated yet, which is also why the answer is cached: chunk
    loading, landmark placement and the roads between settlements all ask it repeatedly
    for the same coordinates.
    """
    region = c.Villages.REGION_CHUNKS
    rx, ry = math.floor(cx / region), math.floor(cy / region)
    site = _region_site(rx, ry)
    if site is None or (site[0], site[1]) != (cx, cy):
        return None

    for nx in range(rx - 1, rx + 2):
        for ny in range(ry - 1, ry + 2):
            # Ties are broken by region order, the same way from wherever this is asked.
            if (nx, ny) >= (rx, ry):
                continue
            other = _region_site(nx, ny)
            if other is not None and math.hypot(site[2] - other[2], site[3] - other[3]) < c.Villages.MIN_GAP:
                return None
    return site[2], site[3]


def sites_near_chunk(cx: int, cy: int, chunk_radius: int) -> List[Tuple[int, int]]:
    """Every village site within `chunk_radius` chunks of (cx, cy), generated or not.

    Sites are a pure function of their region, so this answers the same thing from
    anywhere: what the roads between settlements are drawn from, and cheap enough to ask
    on every chunk load because it walks regions rather than chunks.
    """
    region = c.Villages.REGION_CHUNKS
    sites: List[Tuple[int, int]] = []
    for rx in range(math.floor((cx - chunk_radius) / region), math.floor((cx + chunk_radius) / region) + 1):
        for ry in range(math.floor((cy - chunk_radius) / region), math.floor((cy + chunk_radius) / region) + 1):
            site = _region_site(rx, ry)
            # Asked back through village_site so a region that stands down for a neighbour
            # is left out here too, and no road is drawn to a village that never exists.
            if site is not None and village_site(site[0], site[1]) is not None:
                sites.append((site[2], site[3]))
    return sites


def _building_kinds(composition: dict, rng: random.Random) -> List[str]:
    """The buildings a settlement of this composition is made of, biggest first: the
    tavern and the shops take the slots nearest the plaza, the houses spread out behind."""
    kinds: List[str] = []
    for kind in ("tavern", "shop", "house"):
        low, high = composition[kind]
        kinds.extend([kind] * rng.randint(low, high))
    return kinds


def _plaza_slots(count: int, rng: random.Random) -> List[Tuple[float, float]]:
    """Offsets from the plaza for `count` buildings: a grid centred on the village with its
    middle slot left open, ordered nearest the plaza first and jittered so the result reads
    as a settlement rather than a spreadsheet."""
    columns = max(2, math.ceil(math.sqrt(count + 1)))
    rows = math.ceil((count + 1) / columns)
    slots = []
    for row in range(rows):
        for column in range(columns):
            ox = (column - (columns - 1) / 2) * c.Villages.SLOT_W
            oy = (row - (rows - 1) / 2) * c.Villages.SLOT_H
            slots.append((ox, oy))

    slots.sort(key=lambda slot: math.hypot(*slot))
    slots = slots[1:]  # the middle slot is the plaza itself
    jitter = c.Villages.SLOT_JITTER
    return [(ox + rng.uniform(-jitter, jitter), oy + rng.uniform(-jitter, jitter)) for ox, oy in slots[:count]]


def _facing_towards_plaza(ox: float, oy: float) -> str:
    """Which wall a building at this offset from the plaza puts its door in: the one facing
    the middle of the village. A settlement whose doors all opened south read as a warehouse
    yard; doors onto the square make the plaza the street it is meant to be."""
    if abs(ox) > abs(oy):
        return "W" if ox > 0 else "E"
    return "N" if oy > 0 else "S"


def _build(x, y, chunk, size: str, composition: dict, rng: random.Random) -> Tuple[Village, List[Building]]:
    kinds = _building_kinds(composition, rng)
    slots = _plaza_slots(len(kinds), rng)
    buildings = [
        Building(round(x + ox), round(y + oy), kind, facing=_facing_towards_plaza(ox, oy))
        for kind, (ox, oy) in zip(kinds, slots)
    ]
    radius = round(max((math.hypot(ox, oy) for ox, oy in slots), default=0) + c.Villages.SLOT_W / 2)
    extent = round(
        max(
            (max(abs(b.x - x) + b.w / 2, abs(b.y - y) + b.h / 2) for b in buildings),
            default=c.Villages.PLAZA_RADIUS,
        )
    )
    return Village(x, y, chunk, size, radius, extent), buildings


def generate_village(x, y, chunk: Tuple[int, int]) -> Tuple[Village, List[Building]]:
    """Lay out the village that chunk (cx, cy) offers. Called once, the first time the
    player walks into range; after that the result lives in the save like the starting town."""
    rng = random.Random(f"village-layout:{chunk[0]},{chunk[1]}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS)
    size = rng.choices(sizes, weights=weights)[0]
    return _build(x, y, chunk, size, c.Villages.COMPOSITION[size], rng)


def generate_starting_world() -> Tuple[Village, List[Building]]:
    """The village the player starts next to, plus the ruined landmark standing alone out
    in the settled ring. Rolled fresh per new game rather than seeded, so two playthroughs
    don't open on the same town."""
    center = c.World.WORLD_SIZE // 2
    angle = random.uniform(0, 2 * math.pi)
    distance = c.Villages.START_DISTANCE_FROM_CENTER
    x = round(center + math.cos(angle) * distance)
    y = round(center + math.sin(angle) * distance)
    chunk = (int(x // c.World.CHUNK_SIZE), int(y // c.World.CHUNK_SIZE))
    village, buildings = _build(x, y, chunk, "town", c.Villages.START_COMPOSITION, random.Random())

    landmark = _place_landmark(village, buildings)
    if landmark is not None:
        buildings.append(landmark)
    return village, buildings


def _place_landmark(village: Village, buildings: List[Building]) -> Optional[Building]:
    """The ancient ruin: out on the far side of the settled ring, well clear of the village
    and a long way from the spawn point, since its guardian is a boss and shouldn't be
    waiting on the doorstep (Boss.LANDMARK_MIN_DISTANCE, its own floor rather than the
    ordinary building clearance)."""
    center = c.World.WORLD_SIZE // 2
    margin = c.Buildings.EDGE_MARGIN
    for _ in range(120):
        x = random.randint(margin, c.World.WORLD_SIZE - margin)
        y = random.randint(margin, c.World.WORLD_SIZE - margin)
        if math.hypot(x - center, y - center) < c.Boss.LANDMARK_MIN_DISTANCE:
            continue
        if village.distance_to_point((x, y)) < village.radius + c.Buildings.MIN_GAP:
            continue
        candidate = Building(x, y, "landmark")
        gap = c.Buildings.MIN_GAP
        if any(candidate.rect.inflate(gap * 2, gap * 2).colliderect(other.rect) for other in buildings):
            continue
        return candidate
    return None
