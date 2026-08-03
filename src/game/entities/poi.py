from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.buildings import Building


class PointOfInterest:
    """A wilderness landmark scattered between towns, so exploring away from the beaten
    path finds something worth the detour. "ruins" and "camp" are smashable loot
    caches (game.loot.open_poi_cache); "shrine" is pure discovery flavor, no loot,
    just a one-time line of text the first time the player walks up to it.
    """

    def __init__(self, x, y, kind="ruins"):
        self.x = x
        self.y = y
        self.kind = kind
        self.looted = False
        self.discovered = False  # shrine only: has its flavor line already been shown

    @property
    def has_loot(self) -> bool:
        return self.kind in ("ruins", "camp")

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "kind": self.kind, "looted": self.looted, "discovered": self.discovered}

    @classmethod
    def from_dict(cls, data: dict) -> "PointOfInterest":
        poi = cls(data["x"], data["y"], data.get("kind", "ruins"))
        poi.looted = data.get("looted", False)
        poi.discovered = data.get("discovered", False)
        return poi

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        center = (round(sx), round(sy))
        if self.kind == "camp":
            self._draw_camp(screen, center)
        elif self.kind == "shrine":
            self._draw_shrine(screen, center)
        else:
            self._draw_ruins(screen, center)

    def _draw_ruins(self, screen, center):
        size = c.PointsOfInterest.SIZE
        # Seeded from world position, stable across camera panning; fewer, smaller
        # stones once looted so a cleared ruin visibly reads as picked over.
        rng = random.Random(f"{self.x},{self.y}")
        count = 4 if self.looted else 6
        max_r = (6, 9) if self.looted else (8, 16)
        for _ in range(count):
            ox = rng.uniform(-size * 0.5, size * 0.5)
            oy = rng.uniform(-size * 0.3, size * 0.3)
            r = rng.randint(*max_r)
            pos = (round(center[0] + ox), round(center[1] + oy))
            pygame.draw.circle(screen, (140, 138, 130), pos, r)
            pygame.draw.circle(screen, (95, 93, 86), pos, r, 2)

    def _draw_camp(self, screen, center):
        cx, cy = center
        tent_w, tent_h = 46, 34
        tent = [(cx - tent_w // 2, cy + tent_h // 2), (cx, cy - tent_h // 2), (cx + tent_w // 2, cy + tent_h // 2)]
        pygame.draw.polygon(screen, (150, 120, 80), tent)
        pygame.draw.polygon(screen, (95, 72, 45), tent, 2)
        flap = [(cx, cy - tent_h // 2), (cx, cy + tent_h // 2), (cx - 8, cy + tent_h // 2)]
        pygame.draw.polygon(screen, (110, 85, 55), flap)

        fire_pos = (cx + 40, cy + 12)
        pygame.draw.circle(screen, (90, 60, 40), fire_pos, 11)
        if not self.looted:
            pygame.draw.circle(screen, (230, 130, 40), fire_pos, 6)
            pygame.draw.circle(screen, (250, 200, 80), fire_pos, 3)
        else:
            pygame.draw.circle(screen, (70, 65, 60), fire_pos, 6)

    def _draw_shrine(self, screen, center):
        cx, cy = center
        base = pygame.Rect(0, 0, 30, 12)
        base.center = (cx, cy + 20)
        pygame.draw.rect(screen, (150, 148, 140), base)
        pygame.draw.rect(screen, (105, 103, 96), base, 2)
        pillar = pygame.Rect(0, 0, 16, 40)
        pillar.center = (cx, cy - 4)
        pygame.draw.rect(screen, (170, 168, 158), pillar)
        pygame.draw.rect(screen, (110, 108, 100), pillar, 2)
        top = pygame.Rect(0, 0, 24, 10)
        top.center = (cx, cy - 26)
        pygame.draw.rect(screen, (190, 185, 140), top)
        pygame.draw.rect(screen, (110, 108, 100), top, 2)


def _pick_kind() -> str:
    kinds, weights = zip(*c.PointsOfInterest.KIND_WEIGHTS)
    return random.choices(kinds, weights=weights)[0]


def generate_pois(buildings: List["Building"]) -> List[PointOfInterest]:
    """Scatter wilderness points of interest across the map, away from buildings, the
    world center and each other, so exploring away from town finds something worth
    the detour."""
    result: List[PointOfInterest] = []
    center = c.World.WORLD_SIZE // 2
    margin = c.Buildings.EDGE_MARGIN
    for _ in range(c.PointsOfInterest.COUNT):
        for _attempt in range(40):
            x = random.randint(margin, c.World.WORLD_SIZE - margin)
            y = random.randint(margin, c.World.WORLD_SIZE - margin)
            if math.hypot(x - center, y - center) < c.PointsOfInterest.MIN_DIST_FROM_CENTER:
                continue
            if any(
                math.hypot(x - b.x, y - b.y) < max(b.w, b.h) / 2 + c.PointsOfInterest.MIN_DIST_FROM_BUILDING
                for b in buildings
            ):
                continue
            if any(math.hypot(x - p.x, y - p.y) < c.PointsOfInterest.MIN_DIST_FROM_OTHER for p in result):
                continue
            result.append(PointOfInterest(x, y, _pick_kind()))
            break
    return result
