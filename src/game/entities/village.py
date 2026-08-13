from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List, Optional, Tuple

import pygame

import core.constants as c
from game.entities.buildings import Building, draw_label

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

    def __init__(self, x, y, chunk: Tuple[int, int], size: str = "village", radius: int = 700):
        self.x = x
        self.y = y
        # The chunk that owns this village, and its identity in the save: a chunk that
        # already has one never generates a second.
        self.chunk = (int(chunk[0]), int(chunk[1]))
        self.size = size
        self.radius = radius
        self.name: Optional[str] = None
        self.discovered = False

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def contains_point(self, x, y) -> bool:
        return math.hypot(self.x - x, self.y - y) <= self.radius

    def blocks(self, x, y, radius) -> bool:
        """The well in the middle of the plaza is solid; everything else in a village is a
        building, collided against by the buildings themselves."""
        return math.hypot(self.x - x, self.y - y) < c.Villages.WELL_RADIUS + radius

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "chunk": list(self.chunk),
            "size": self.size,
            "radius": self.radius,
            "name": self.name,
            "discovered": self.discovered,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Village:
        village = cls(data["x"], data["y"], data["chunk"], data.get("size", "village"), data.get("radius", 700))
        village.name = data.get("name")
        village.discovered = data.get("discovered", False)
        return village

    def draw(self, screen: pygame.Surface, camera: Camera):
        """The plaza: packed earth, a well, and the village name once it has been found."""
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

        if self.name and self.discovered:
            # Well below the plaza, so it doesn't sit under whoever is standing at the well.
            draw_label(screen, self.name, (cx, cy + plaza.height / 2 + 54))

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


def village_site(cx: int, cy: int) -> Optional[Tuple[int, int]]:
    """Where the village belonging to chunk (cx, cy) stands, or None if it holds none.

    One region of REGION_CHUNKS x REGION_CHUNKS chunks settles a single chunk, and a region
    whose site lands too close to a neighbouring region's yields to it, so two settlements
    can't end up back to back across a region border. All of it is a pure function of the
    coordinates: the same chunk always offers the same site, whether or not the village
    behind it has been generated yet.
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


def _build(x, y, chunk, size: str, composition: dict, rng: random.Random) -> Tuple[Village, List[Building]]:
    kinds = _building_kinds(composition, rng)
    slots = _plaza_slots(len(kinds), rng)
    buildings = [Building(round(x + ox), round(y + oy), kind) for kind, (ox, oy) in zip(kinds, slots)]
    radius = round(max((math.hypot(ox, oy) for ox, oy in slots), default=0) + c.Villages.SLOT_W / 2)
    return Village(x, y, chunk, size, radius), buildings


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
    """The ancient ruin: somewhere in the settled ring, well clear of the village and of
    the spawn point, since its guardian shouldn't be waiting on the doorstep."""
    center = c.World.WORLD_SIZE // 2
    margin = c.Buildings.EDGE_MARGIN
    for _ in range(60):
        x = random.randint(margin, c.World.WORLD_SIZE - margin)
        y = random.randint(margin, c.World.WORLD_SIZE - margin)
        if math.hypot(x - center, y - center) < c.Buildings.SPAWN_CLEARANCE:
            continue
        if village.distance_to_point((x, y)) < village.radius + c.Buildings.MIN_GAP:
            continue
        candidate = Building(x, y, "landmark")
        gap = c.Buildings.MIN_GAP
        if any(candidate.rect.inflate(gap * 2, gap * 2).colliderect(other.rect) for other in buildings):
            continue
        return candidate
    return None
