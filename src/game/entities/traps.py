from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Iterable, List, Tuple

import pygame

import core.constants as c
from game.entities.village import sites_near_chunk

if TYPE_CHECKING:
    from core.camera import Camera


class BearTrap:
    """One hunter's trap lying in the grass, set and waiting.

    Placed by nobody the player can talk to and aimed at nothing in particular: it shuts on
    whatever stands on it first, and the player is no exception. What it costs is a bite of
    health and, mostly, the seconds it holds you where you are, which is the only thing in
    the world that stops something moving without a wall.

    Streamed with its chunk from the coordinates alone, like a POI, so the map stays
    endless; the one thing a player can change about it (having sprung it) is what the
    world saves, keyed by `id`.
    """

    # What `Player._damage_source_name` calls it on the death screen.
    name = "a bear trap"

    def __init__(self, x: float, y: float, chunk: Tuple[int, int], sprung: bool = False):
        self.x = x
        self.y = y
        self.chunk = (int(chunk[0]), int(chunk[1]))
        self.sprung = sprung

    @property
    def id(self) -> str:
        return f"{self.chunk[0]}:{self.chunk[1]}:{round(self.x)},{round(self.y)}"

    def catches(self, x: float, y: float, radius: float) -> bool:
        """Whether something of that size standing there has put a foot in the jaws."""
        if self.sprung:
            return False
        reach = c.Traps.TRIGGER_RADIUS + radius
        dx, dy = self.x - x, self.y - y
        return dx * dx + dy * dy < reach * reach

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def draw(self, screen: pygame.Surface, camera: Camera):
        cx, cy = camera.world_to_screen(self.x, self.y)
        center = (round(cx), round(cy))
        radius = c.Traps.SIZE // 2
        if self.sprung:
            # Shut on nothing: two closed jaws lying flat, so ground already paid for reads
            # as safe from a distance.
            pygame.draw.circle(screen, c.Traps.SPRUNG_COLOR, center, round(radius * 0.7))
            pygame.draw.line(screen, (60, 58, 54), (center[0] - radius, cy), (center[0] + radius, cy), 4)
            return

        pygame.draw.circle(screen, c.Traps.PLATE_COLOR, center, radius)
        pygame.draw.circle(screen, (52, 50, 46), center, radius, 2)
        # The ring of teeth, the one thing that says this is a trap and not a stone.
        for step in range(10):
            angle = 2 * math.pi * step / 10
            base = (cx + math.cos(angle) * radius * 0.8, cy + math.sin(angle) * radius * 0.8)
            tip = (cx + math.cos(angle) * radius * 1.25, cy + math.sin(angle) * radius * 1.25)
            pygame.draw.line(screen, c.Traps.JAW_COLOR, base, tip, 3)
        pygame.draw.circle(screen, (66, 64, 60), center, round(radius * 0.35))


def traps_for_chunk(cx: int, cy: int, buildings: Iterable, scenery: Iterable) -> List[BearTrap]:
    """Every trap set in one chunk, rolled from its coordinates alone.

    Traps belong to a settlement's hunting ground rather than to the map at large: a chunk
    with no village site in the right band around it holds none, however deep in the woods
    it is, because out there nobody would ever come back to check the line.
    """
    reach = math.ceil(c.Traps.MAX_FROM_VILLAGE / c.World.CHUNK_SIZE) + 1
    sites = sites_near_chunk(cx, cy, reach)
    if not sites:
        return []

    rng = random.Random(f"traps:{cx},{cy}")
    size = c.World.CHUNK_SIZE
    footprints = [b.rect.inflate(c.Traps.CLEARANCE * 2, c.Traps.CLEARANCE * 2) for b in buildings]
    solids = [(s.x, s.y, max(s.blocking_radius, s.water_reach)) for s in scenery if s.blocking_radius or s.water_reach]

    traps: List[BearTrap] = []
    for _ in range(rng.randint(*c.Traps.PER_CHUNK)):
        x = cx * size + rng.uniform(0, size)
        y = cy * size + rng.uniform(0, size)
        distance = min(math.hypot(x - sx, y - sy) for sx, sy in sites)
        if not c.Traps.MIN_FROM_VILLAGE <= distance <= c.Traps.MAX_FROM_VILLAGE:
            continue
        if any(rect.collidepoint(x, y) for rect in footprints):
            continue
        # Never under a trunk or in the water: a trap has to be somewhere something can
        # actually walk, and one nobody can step on is one nobody can avoid either.
        if any(math.hypot(x - sx, y - sy) < radius + c.Traps.TRIGGER_RADIUS for sx, sy, radius in solids):
            continue
        traps.append(BearTrap(x, y, (cx, cy)))
    return traps
