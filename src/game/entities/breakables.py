from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.buildings import Building


class Breakable:
    """A standalone outdoor prop the player can smash: a loot-bearing barrel, or one of
    the things planted around a doorstep (a bush, a flower bed, a herb patch, a sapling),
    scattered near a house, shop or tavern. Unlike interior shop crates it carries no
    broken/debris state; once smashed it's simply gone for the rest of the session."""

    def __init__(self, x, y, kind="barrel", hp=None):
        self.x = x
        self.y = y
        self.kind = kind
        # What it takes to break: persisted, so a barrel worked half-way down stays that
        # way across a save rather than healing itself while the player is in a menu.
        self.hp = c.Breakables.HP.get(kind, c.Breakables.DEFAULT_HP) if hp is None else hp

    @property
    def loot(self) -> bool:
        return self.kind == "barrel"

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "kind": self.kind, "hp": self.hp}

    @classmethod
    def from_dict(cls, data: dict) -> "Breakable":
        return cls(data["x"], data["y"], data.get("kind", "barrel"), data.get("hp"))

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        center = (round(sx), round(sy))
        # Seeded from the world position (stable) rather than the screen position (which
        # pans every frame), so the planting doesn't jitter as the camera moves.
        rng = random.Random(f"{self.x},{self.y}")
        if self.kind == "bush":
            self._draw_bush(screen, center, rng)
        elif self.kind == "flowerbed":
            self._draw_flowerbed(screen, center, rng)
        elif self.kind == "herbs":
            self._draw_herbs(screen, center, rng)
        elif self.kind == "sapling":
            self._draw_sapling(screen, center, rng)
        elif self.kind == "pot":
            # Only ever reached by a save made before the clay pots were replaced by
            # something growing; new villages never roll one.
            self._draw_pot(screen, center)
        else:
            self._draw_barrel(screen, center)

    @staticmethod
    def _draw_barrel(screen: pygame.Surface, center):
        w, h = c.Breakables.SIZE, int(c.Breakables.SIZE * 1.3)
        body = pygame.Rect(0, 0, w, h)
        body.center = center
        pygame.draw.rect(screen, (112, 76, 42), body, border_radius=5)
        pygame.draw.rect(screen, (66, 44, 24), body, 2, border_radius=5)
        for frac in (0.28, 0.72):
            band_y = round(body.top + body.height * frac)
            pygame.draw.line(screen, (66, 44, 24), (body.left + 2, band_y), (body.right - 2, band_y), 3)

    @staticmethod
    def _draw_pot(screen: pygame.Surface, center):
        cx, cy = center
        size = round(c.Breakables.SIZE * 0.75)
        body = pygame.Rect(0, 0, size, round(size * 0.85))
        body.center = (cx, cy + size // 6)
        pygame.draw.rect(screen, (168, 92, 56), body, border_radius=6)
        pygame.draw.rect(screen, (110, 58, 34), body, 2, border_radius=6)
        rim = pygame.Rect(0, 0, round(size * 1.05), round(size * 0.22))
        rim.center = (cx, body.top + 2)
        pygame.draw.ellipse(screen, (188, 112, 70), rim)
        pygame.draw.ellipse(screen, (110, 58, 34), rim, 2)

    @staticmethod
    def _draw_bush(screen: pygame.Surface, center, rng: random.Random):
        cx, cy = center
        radius = c.Breakables.SIZE // 2
        offsets = [(0, 0), (-radius * 0.5, radius * 0.2), (radius * 0.5, radius * 0.2), (0, -radius * 0.35)]
        for ox, oy in offsets:
            r = round(radius * rng.uniform(0.55, 0.75))
            leaf_color = (60 + rng.randint(-10, 15), 120 + rng.randint(-10, 20), 55 + rng.randint(-10, 10))
            pygame.draw.circle(screen, leaf_color, (round(cx + ox), round(cy + oy)), r)
            pygame.draw.circle(screen, (35, 75, 32), (round(cx + ox), round(cy + oy)), r, 1)

    @staticmethod
    def _draw_flowerbed(screen: pygame.Surface, center, rng: random.Random):
        """A tilled bed with a few blooms in it, the thing most likely to be growing by a
        village door."""
        cx, cy = center
        size = c.Breakables.SIZE
        soil = pygame.Rect(0, 0, round(size * 1.2), round(size * 0.55))
        soil.center = (cx, cy + size // 5)
        pygame.draw.ellipse(screen, (98, 72, 48), soil)
        pygame.draw.ellipse(screen, (68, 50, 34), soil, 2)
        palette = ((228, 96, 112), (236, 202, 92), (170, 128, 220), (240, 240, 232))
        color = rng.choice(palette)
        for _ in range(rng.randint(4, 6)):
            ox = rng.uniform(-size * 0.45, size * 0.45)
            oy = rng.uniform(-size * 0.18, size * 0.12)
            stem_bottom = (round(cx + ox), round(cy + oy + 8))
            head = (round(cx + ox), round(cy + oy - 4))
            pygame.draw.line(screen, (66, 108, 52), stem_bottom, head, 2)
            pygame.draw.circle(screen, color, head, rng.randint(3, 5))
            pygame.draw.circle(screen, (250, 236, 160), head, 1)

    @staticmethod
    def _draw_herbs(screen: pygame.Surface, center, rng: random.Random):
        """A kitchen patch: low, ragged, no flowers to speak of."""
        cx, cy = center
        size = c.Breakables.SIZE
        for _ in range(rng.randint(5, 8)):
            ox = rng.uniform(-size * 0.4, size * 0.4)
            base = (round(cx + ox), round(cy + size * 0.25))
            height = rng.randint(10, 18)
            lean = rng.uniform(-5, 5)
            green = (72 + rng.randint(-12, 12), 116 + rng.randint(-14, 18), 58 + rng.randint(-10, 12))
            pygame.draw.line(screen, green, base, (round(base[0] + lean), base[1] - height), 3)

    @staticmethod
    def _draw_sapling(screen: pygame.Surface, center, rng: random.Random):
        """A young tree somebody planted: a thin trunk and a small crown, small enough to
        read as part of the garden rather than as wilderness."""
        cx, cy = center
        size = c.Breakables.SIZE
        pygame.draw.line(screen, (104, 78, 48), (cx, cy + size // 2), (cx, cy - 4), 4)
        for _ in range(rng.randint(3, 4)):
            ox = rng.uniform(-size * 0.3, size * 0.3)
            oy = rng.uniform(-size * 0.45, -size * 0.1)
            leaf = (58 + rng.randint(-10, 12), 118 + rng.randint(-12, 20), 54 + rng.randint(-8, 10))
            pygame.draw.circle(screen, leaf, (round(cx + ox), round(cy + oy)), rng.randint(8, 12))


def _pick_kind(rng: random.Random) -> str:
    kinds, weights = zip(*c.Breakables.KIND_WEIGHTS)
    return rng.choices(kinds, weights=weights)[0]


def generate_breakables(buildings: List["Building"]) -> List[Breakable]:
    """Scatter a few barrels and plantings just outside each house/shop/tavern (never the
    landmark), deterministic per building so they stay put across a save/reload."""
    result: List[Breakable] = []
    for building in buildings:
        if building.kind == "landmark":
            continue
        rng = random.Random(f"{building.id}-breakable")
        door_zone = building.door_zone()
        count = rng.randint(c.Breakables.PER_BUILDING_MIN, c.Breakables.PER_BUILDING_MAX)
        for _ in range(count):
            for _attempt in range(10):
                angle = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(max(building.w, building.h) / 2 + 25, max(building.w, building.h) / 2 + 80)
                x = building.x + math.cos(angle) * dist
                y = building.y + math.sin(angle) * dist
                if door_zone is not None and door_zone.inflate(50, 50).collidepoint(x, y):
                    continue
                if any(b.blocks(x, y, c.Breakables.SIZE / 2) for b in buildings):
                    continue
                result.append(Breakable(x, y, _pick_kind(rng)))
                break
    return result
