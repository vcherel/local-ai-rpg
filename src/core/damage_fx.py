"""How a prop that has been hit but has not broken yet shows it.

Every breakable in the game has a hit-point pool, and until now the only sign a blow had
landed on one was a puff of particles: the barrel itself looked untouched right up to the
swing that cleared it. This module is the missing half of that feedback, and it is
deliberately one place rather than four, so a cracked crate, a cracked barrel and a
cracked cache all read the same way.

Two parts, both session-only:

- `get_damage_fx()`, a registry of recent blows keyed by a string, because the things that
  take them are not all objects: a `Breakable` is, but a crate or a window is an index into
  a building's layout. Anything drawing a damaged prop asks for the flinch offset and the
  flash under that key.
- `draw_cracks`, the wear itself, seeded so it stays put as the camera pans and growing as
  the pool empties.
"""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c


class DamageFx:
    """Recent blows on props, keyed by an arbitrary string.

    Timestamps only: the entry is a `pygame.time.get_ticks()` value and an angle, and
    anything older than `DamageFx.FLASH_MS` is dropped on the next hit, so the dict stays
    the size of what is currently being smashed rather than of everything ever smashed.
    """

    def __init__(self):
        self._hits: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, angle: float = 0.0):
        """Record a blow landing on the prop under `key`, arriving along `angle`."""
        now = pygame.time.get_ticks()
        self._hits = {k: v for k, v in self._hits.items() if now - v[0] < c.DamageFx.FLASH_MS}
        self._hits[key] = (now, angle)

    def _amount(self, key: str) -> tuple[float, float]:
        """(0..1 strength of the flash, angle it came from), 0 once it has faded."""
        entry = self._hits.get(key)
        if entry is None:
            return 0.0, 0.0
        elapsed = pygame.time.get_ticks() - entry[0]
        if elapsed >= c.DamageFx.FLASH_MS:
            return 0.0, 0.0
        return 1.0 - elapsed / c.DamageFx.FLASH_MS, entry[1]

    def offset(self, key: str) -> tuple[int, int]:
        """Pixels to shove the prop's drawing by, so it flinches away from the blow."""
        amount, angle = self._amount(key)
        if amount <= 0:
            return 0, 0
        distance = c.DamageFx.FLASH_OFFSET * amount
        return round(math.sin(angle) * distance), round(-math.cos(angle) * distance)

    def flash(self, key: str) -> float:
        """0..1 white blended over the prop right after it was struck."""
        return self._amount(key)[0]


def tint(color: tuple, flash: float) -> tuple:
    """`color` blended toward the flash colour by `flash` (0..1)."""
    if flash <= 0:
        return color
    return tuple(
        round(chan + (target - chan) * flash) for chan, target in zip(color, c.DamageFx.FLASH_COLOR, strict=True)
    )


def draw_cracks(screen: pygame.Surface, rect: pygame.Rect, hp_frac: float, seed):
    """Jagged splits across a hard prop (crate, barrel, cache, keg), the count growing as
    its hit points run out. Nothing is drawn at full health, so the wear itself is the
    readout: how battered it looks is how close it is to giving.

    `seed` must be a world-space value rather than a screen one, or the cracks crawl
    across the prop as the camera pans.
    """
    count = round(c.DamageFx.MAX_CRACKS * (1.0 - max(0.0, min(1.0, hp_frac))))
    if count <= 0:
        return
    rng = random.Random(f"{seed}-cracks")
    for i in range(count):
        # Each crack keeps its own seed slice, so losing more health adds splits rather
        # than redrawing a different set of them.
        start = (rng.uniform(rect.left + 2, rect.right - 2), rng.uniform(rect.top + 2, rect.bottom - 2))
        points = [start]
        angle = rng.uniform(0, 2 * math.pi)
        for _ in range(3):
            angle += rng.uniform(-0.7, 0.7)
            length = rng.uniform(4, max(5.0, rect.width * 0.28))
            last = points[-1]
            points.append((last[0] + math.cos(angle) * length, last[1] + math.sin(angle) * length))
        clamped = [(min(max(px, rect.left), rect.right), min(max(py, rect.top), rect.bottom)) for px, py in points]
        pygame.draw.lines(screen, c.DamageFx.CRACK_COLOR, False, clamped, 2 if i == 0 else 1)


_damage_fx = None


def get_damage_fx() -> DamageFx:
    global _damage_fx
    if _damage_fx is None:
        _damage_fx = DamageFx()
    return _damage_fx
