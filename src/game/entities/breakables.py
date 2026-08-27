from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.damage_fx import draw_cracks, get_damage_fx, tint

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.buildings import Building


class Breakable:
    """A standalone outdoor prop the player can smash: a loot-bearing barrel, a powder keg
    that goes off, or one of the things planted around a doorstep (a bush, a flower bed, a
    herb patch, a sapling), scattered near a house, shop or tavern. Unlike interior shop
    crates it carries no broken/debris state; once smashed it's simply gone for the rest of
    the session."""

    def __init__(self, x, y, kind="barrel", hp=None):
        self.x = x
        self.y = y
        self.kind = kind
        # What it takes to break: persisted, so a barrel worked half-way down stays that
        # way across a save rather than healing itself while the player is in a menu.
        self.max_hp = c.Breakables.HP.get(kind, c.Breakables.DEFAULT_HP)
        self.hp = self.max_hp if hp is None else hp

    @property
    def loot(self) -> bool:
        return self.kind == "barrel"

    @property
    def damage_key(self) -> str:
        """Identity for `core.damage_fx`. Keyed by position rather than by object, like
        everything else in that registry, and a breakable never moves."""
        return f"breakable:{round(self.x)},{round(self.y)}"

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "kind": self.kind, "hp": self.hp}

    @classmethod
    def from_dict(cls, data: dict) -> Breakable:
        return cls(data["x"], data["y"], data.get("kind", "barrel"), data.get("hp"))

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        fx = get_damage_fx()
        # A prop that has just been struck flinches away from the blow, and a hard one
        # carries the cracks of everything it has taken so far: how battered it looks is
        # how close it is to giving.
        offset = fx.offset(self.damage_key)
        flash = fx.flash(self.damage_key)
        center = (round(sx) + offset[0], round(sy) + offset[1])
        hp_frac = max(0.0, min(1.0, self.hp / self.max_hp))
        # Seeded from the world position (stable) rather than the screen position (which
        # pans every frame), so the planting doesn't jitter as the camera moves.
        rng = random.Random(f"{self.x},{self.y}")
        _DRAWERS.get(self.kind, Breakable._draw_barrel)(self, screen, center, rng, hp_frac, flash)

    def _draw_wear(self, screen: pygame.Surface, center, hp_frac: float, width: int):
        body = pygame.Rect(0, 0, width, int(width * 1.3))
        body.center = center
        draw_cracks(screen, body, hp_frac, f"{self.x},{self.y}")

    def _draw_barrel(self, screen: pygame.Surface, center, _rng, hp_frac: float, flash: float):
        w, h = c.Breakables.SIZE, int(c.Breakables.SIZE * 1.3)
        body = pygame.Rect(0, 0, w, h)
        body.center = center
        pygame.draw.rect(screen, tint((112, 76, 42), flash), body, border_radius=5)
        pygame.draw.rect(screen, (66, 44, 24), body, 2, border_radius=5)
        for frac in (0.28, 0.72):
            band_y = round(body.top + body.height * frac)
            pygame.draw.line(screen, (66, 44, 24), (body.left + 2, band_y), (body.right - 2, band_y), 3)
        self._draw_wear(screen, center, hp_frac, c.Breakables.SIZE)

    def _draw_powder_keg(self, screen: pygame.Surface, center, _rng, hp_frac: float, flash: float):
        """A keg of black powder: squatter and darker than a barrel, iron-banded, with a
        fuse out of the lid. It has to be told apart from an ordinary barrel at a glance,
        because walking up and hitting one is a very different decision."""
        w, h = round(c.Breakables.SIZE * 1.15), round(c.Breakables.SIZE * 1.15)
        body = pygame.Rect(0, 0, w, h)
        body.center = center
        pygame.draw.rect(screen, tint((58, 46, 40), flash), body, border_radius=6)
        pygame.draw.rect(screen, (30, 24, 20), body, 2, border_radius=6)
        for frac in (0.25, 0.75):
            band_y = round(body.top + body.height * frac)
            pygame.draw.line(screen, (128, 118, 104), (body.left + 2, band_y), (body.right - 2, band_y), 3)
        # Fuse, curling off the top, with a bright tip so the eye lands on it.
        fuse_base = (body.centerx, body.top + 2)
        pygame.draw.lines(
            screen,
            (162, 138, 96),
            False,
            [fuse_base, (body.centerx + 5, body.top - 6), (body.centerx - 2, body.top - 12)],
            2,
        )
        pygame.draw.circle(screen, (255, 190, 90), (body.centerx - 2, body.top - 12), 3)
        self._draw_wear(screen, center, hp_frac, int(c.Breakables.SIZE * 1.15))

    def _draw_bush(self, screen: pygame.Surface, center, rng: random.Random, hp_frac: float, flash: float):
        """A planted prop shows its damage by losing bulk rather than by cracking: the
        clumps shrink as it is hacked at, so a half-cleared bush reads as half cleared."""
        cx, cy = center
        radius = c.Breakables.SIZE // 2 * (0.5 + 0.5 * hp_frac)
        offsets = [(0, 0), (-radius * 0.5, radius * 0.2), (radius * 0.5, radius * 0.2), (0, -radius * 0.35)]
        for ox, oy in offsets:
            r = round(radius * rng.uniform(0.55, 0.75))
            leaf_color = (60 + rng.randint(-10, 15), 120 + rng.randint(-10, 20), 55 + rng.randint(-10, 10))
            pygame.draw.circle(screen, tint(leaf_color, flash), (round(cx + ox), round(cy + oy)), r)
            pygame.draw.circle(screen, (35, 75, 32), (round(cx + ox), round(cy + oy)), r, 1)

    def _draw_flowerbed(self, screen: pygame.Surface, center, rng: random.Random, hp_frac: float, flash: float):
        """A tilled bed with a few blooms in it, the thing most likely to be growing by a
        village door. Blooms are trampled off it one by one as it takes hits."""
        cx, cy = center
        size = c.Breakables.SIZE
        soil = pygame.Rect(0, 0, round(size * 1.2), round(size * 0.55))
        soil.center = (cx, cy + size // 5)
        pygame.draw.ellipse(screen, tint((98, 72, 48), flash), soil)
        pygame.draw.ellipse(screen, (68, 50, 34), soil, 2)
        palette = ((228, 96, 112), (236, 202, 92), (170, 128, 220), (240, 240, 232))
        color = rng.choice(palette)
        # The count is rolled in full and then trimmed, so damage takes blooms away
        # instead of rearranging the ones that are left.
        for _ in range(max(1, round(rng.randint(4, 6) * hp_frac))):
            ox = rng.uniform(-size * 0.45, size * 0.45)
            oy = rng.uniform(-size * 0.18, size * 0.12)
            stem_bottom = (round(cx + ox), round(cy + oy + 8))
            head = (round(cx + ox), round(cy + oy - 4))
            pygame.draw.line(screen, (66, 108, 52), stem_bottom, head, 2)
            pygame.draw.circle(screen, color, head, rng.randint(3, 5))
            pygame.draw.circle(screen, (250, 236, 160), head, 1)

    def _draw_herbs(self, screen: pygame.Surface, center, rng: random.Random, hp_frac: float, flash: float):
        """A kitchen patch: low, ragged, no flowers to speak of."""
        cx, cy = center
        size = c.Breakables.SIZE
        for _ in range(max(1, round(rng.randint(5, 8) * hp_frac))):
            ox = rng.uniform(-size * 0.4, size * 0.4)
            base = (round(cx + ox), round(cy + size * 0.25))
            height = rng.randint(10, 18)
            lean = rng.uniform(-5, 5)
            green = (72 + rng.randint(-12, 12), 116 + rng.randint(-14, 18), 58 + rng.randint(-10, 12))
            pygame.draw.line(screen, tint(green, flash), base, (round(base[0] + lean), base[1] - height), 3)

    def _draw_sapling(self, screen: pygame.Surface, center, rng: random.Random, hp_frac: float, flash: float):
        """A young tree somebody planted: a thin trunk and a small crown, small enough to
        read as part of the garden rather than as wilderness."""
        cx, cy = center
        size = c.Breakables.SIZE
        pygame.draw.line(screen, tint((104, 78, 48), flash), (cx, cy + size // 2), (cx, cy - 4), 4)
        for _ in range(max(1, round(rng.randint(3, 4) * hp_frac))):
            ox = rng.uniform(-size * 0.3, size * 0.3)
            oy = rng.uniform(-size * 0.45, -size * 0.1)
            leaf = (58 + rng.randint(-10, 12), 118 + rng.randint(-12, 20), 54 + rng.randint(-8, 10))
            pygame.draw.circle(screen, leaf, (round(cx + ox), round(cy + oy)), rng.randint(8, 12))


# What draws each kind, named explicitly rather than off the kind's own name, the same table
# `scenery.py` and `monster_art.py` use. Anything not listed is drawn as a barrel, which is
# what a save made before the clay pots were replaced holds.
_DRAWERS = {
    "barrel": Breakable._draw_barrel,
    "powder": Breakable._draw_powder_keg,
    "bush": Breakable._draw_bush,
    "flowerbed": Breakable._draw_flowerbed,
    "herbs": Breakable._draw_herbs,
    "sapling": Breakable._draw_sapling,
}


def _pick_kind(rng: random.Random) -> str:
    kinds, weights = zip(*c.Breakables.KIND_WEIGHTS, strict=True)
    return rng.choices(kinds, weights=weights)[0]


def generate_breakables(buildings: list[Building]) -> list[Breakable]:
    """Scatter a few barrels and plantings just outside each house/shop/tavern (never the
    landmark), deterministic per building so they stay put across a save/reload."""
    result: list[Breakable] = []
    # Every doorstep in the settlement, not only this building's own: a barrel dropped in
    # front of the neighbour's door is as much in the way as one in front of your own.
    doorsteps = [step for b in buildings if (step := b.doorstep(c.Villages.DOORSTEP_CLEAR)) is not None]
    for building in buildings:
        if building.kind == "landmark":
            continue
        rng = random.Random(f"{building.id}-breakable")
        count = rng.randint(c.Breakables.PER_BUILDING_MIN, c.Breakables.PER_BUILDING_MAX)
        for _ in range(count):
            for _attempt in range(10):
                angle = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(max(building.w, building.h) / 2 + 25, max(building.w, building.h) / 2 + 80)
                x = building.x + math.cos(angle) * dist
                y = building.y + math.sin(angle) * dist
                if any(step.collidepoint(x, y) for step in doorsteps):
                    continue
                # `covers` rather than `blocks`: the floor of a room is not solid, and a
                # wing sticks out further than the ring this is rolled in, which is how a
                # crate came to be standing in somebody's back room.
                if any(b.covers(x, y, c.Breakables.SIZE / 2) for b in buildings):
                    continue
                result.append(Breakable(x, y, _pick_kind(rng)))
                break
    return result
