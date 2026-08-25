"""The vector art an item icon is drawn from.

Kept apart from `items.py`, which owns what an item *is*: the shape is chosen there
(`items.icon_shape`) and drawn here, so a search for an item's behaviour never lands in a
hundred lines of polygon coordinates and vice versa. One function per string `icon_shape`
can return, gathered into `_SHAPES` at the bottom, the way `monster_art.py` holds the
silhouettes a monster kind can name.

Each shape draws in icon-local terms it is handed: `icon.at(fx, fy)` is a point given as a
fraction of `size` from the centre, `icon.thin` is the border width for the small details.
"""

import math
from dataclasses import dataclass

import pygame

import core.constants as c

# Wood and leather on a weapon's haft and grip. Fixed rather than taken from the item's
# colour, so the metal head stands out against the handle instead of the whole icon being
# one silhouette in one tint.
HAFT_COLOR = (138, 96, 58)
GRIP_COLOR = (92, 62, 44)


@dataclass(frozen=True)
class _Icon:
    """One icon's drawing frame: where it sits, how big it is and what it is painted in."""

    surface: pygame.Surface
    center: tuple
    cx: float
    cy: float
    size: float
    color: tuple
    border_color: tuple
    border_width: int
    thin: int

    def at(self, fx: float, fy: float) -> tuple:
        """A point given as a fraction of `size` from the icon's centre."""
        return (self.cx + self.size * fx, self.cy + self.size * fy)


def _poly(surface, points, color, border_color, border_width):
    pygame.draw.polygon(surface, color, points)
    pygame.draw.polygon(surface, border_color, points, border_width)


def _draw_circle(icon: _Icon):
    pygame.draw.circle(icon.surface, icon.border_color, icon.center, icon.size + icon.border_width)
    pygame.draw.circle(icon.surface, icon.color, icon.center, icon.size)


def _draw_sword(icon: _Icon):
    # Straight blade with a crossguard, wrapped grip and pommel.
    pygame.draw.line(icon.surface, GRIP_COLOR, icon.at(0, 0.25), icon.at(0, 0.85), max(3, int(icon.size * 0.22)))
    pygame.draw.circle(icon.surface, icon.color, icon.at(0, 0.92), max(2, int(icon.size * 0.16)))
    pygame.draw.circle(icon.surface, icon.border_color, icon.at(0, 0.92), max(2, int(icon.size * 0.16)), icon.thin)
    guard = [icon.at(-0.62, 0.16), icon.at(0.62, 0.16), icon.at(0.62, 0.32), icon.at(-0.62, 0.32)]
    _poly(icon.surface, guard, icon.color, icon.border_color, icon.thin)
    blade = [icon.at(0, -1.0), icon.at(0.24, -0.6), icon.at(0.24, 0.18), icon.at(-0.24, 0.18), icon.at(-0.24, -0.6)]
    _poly(icon.surface, blade, icon.color, icon.border_color, icon.border_width)


def _draw_dagger(icon: _Icon):
    # A short blade over an oversized handle: the proportions, not the outline, are
    # what stop it reading as a small sword.
    pygame.draw.line(icon.surface, GRIP_COLOR, icon.at(0, 0.28), icon.at(0, 0.78), max(4, int(icon.size * 0.26)))
    pygame.draw.circle(icon.surface, icon.color, icon.at(0, 0.88), max(3, int(icon.size * 0.18)))
    pygame.draw.circle(icon.surface, icon.border_color, icon.at(0, 0.88), max(3, int(icon.size * 0.18)), icon.thin)
    guard = [icon.at(-0.55, 0.1), icon.at(0.55, 0.1), icon.at(0.55, 0.28), icon.at(-0.55, 0.28)]
    _poly(icon.surface, guard, icon.color, icon.border_color, icon.thin)
    blade = [icon.at(0, -0.62), icon.at(0.28, -0.2), icon.at(0.28, 0.12), icon.at(-0.28, 0.12), icon.at(-0.28, -0.2)]
    _poly(icon.surface, blade, icon.color, icon.border_color, icon.border_width)


def _draw_axe(icon: _Icon):
    haft = [icon.at(-0.22, -0.98), icon.at(0.04, -0.98), icon.at(0.04, 0.98), icon.at(-0.22, 0.98)]
    _poly(icon.surface, haft, HAFT_COLOR, icon.border_color, icon.thin)
    # A single bit gripping the haft over a short eye and flaring into horns above
    # and below it. Without the horns the head is just a blob on a pole, which reads
    # as a pennant rather than an axe.
    head = [
        icon.at(-0.02, -0.9),
        icon.at(0.5, -1.0),
        icon.at(0.95, -0.55),
        icon.at(1.0, -0.1),
        icon.at(0.62, 0.28),
        icon.at(0.28, 0.1),
        icon.at(-0.02, -0.35),
    ]
    _poly(icon.surface, head, icon.color, icon.border_color, icon.border_width)


def _draw_hammer(icon: _Icon):
    haft = [icon.at(-0.14, -0.7), icon.at(0.14, -0.7), icon.at(0.14, 0.98), icon.at(-0.14, 0.98)]
    _poly(icon.surface, haft, HAFT_COLOR, icon.border_color, icon.thin)
    # Tall and narrow rather than wide and flat, which read as a signpost.
    head = [icon.at(-0.56, -0.98), icon.at(0.56, -0.98), icon.at(0.56, -0.24), icon.at(-0.56, -0.24)]
    _poly(icon.surface, head, icon.color, icon.border_color, icon.border_width)
    pygame.draw.line(icon.surface, icon.border_color, icon.at(-0.2, -0.98), icon.at(-0.2, -0.24), icon.thin)
    pygame.draw.line(icon.surface, icon.border_color, icon.at(0.2, -0.98), icon.at(0.2, -0.24), icon.thin)


def _draw_spear(icon: _Icon):
    haft = [icon.at(-0.13, -0.4), icon.at(0.13, -0.4), icon.at(0.13, 1.0), icon.at(-0.13, 1.0)]
    _poly(icon.surface, haft, HAFT_COLOR, icon.border_color, icon.thin)
    # A leaf blade with shoulders, long enough to be the thing you notice: a small
    # diamond on a pole is indistinguishable from the staff's orb at icon size.
    point = [
        icon.at(0, -1.0),
        icon.at(0.34, -0.5),
        icon.at(0.2, -0.28),
        icon.at(0, -0.2),
        icon.at(-0.2, -0.28),
        icon.at(-0.34, -0.5),
    ]
    _poly(icon.surface, point, icon.color, icon.border_color, icon.border_width)


def _draw_pole(icon: _Icon):
    # A full-length shaft with a metal band at each end and nothing sharp anywhere on
    # it, which is the whole reading of the weapon: it hits with its weight.
    haft = [icon.at(-0.16, -1.0), icon.at(0.16, -1.0), icon.at(0.16, 1.0), icon.at(-0.16, 1.0)]
    _poly(icon.surface, haft, HAFT_COLOR, icon.border_color, icon.thin)
    for band_y in (-0.98, 0.62):
        band = [
            icon.at(-0.28, band_y),
            icon.at(0.28, band_y),
            icon.at(0.28, band_y + 0.36),
            icon.at(-0.28, band_y + 0.36),
        ]
        _poly(icon.surface, band, icon.color, icon.border_color, icon.border_width)


def _draw_boomerang(icon: _Icon):
    # A chevron of even width rather than a stick with something on the end: the bend
    # is the whole silhouette, and it is the one weapon in the bag with no handle.
    chevron = [
        icon.at(-0.95, 0.62),
        icon.at(0, -0.92),
        icon.at(0.95, 0.62),
        icon.at(0.5, 0.78),
        icon.at(0, -0.18),
        icon.at(-0.5, 0.78),
    ]
    _poly(icon.surface, chevron, icon.color, icon.border_color, icon.border_width)


def _draw_staff(icon: _Icon):
    haft = [icon.at(-0.13, -0.4), icon.at(0.13, -0.4), icon.at(0.13, 1.0), icon.at(-0.13, 1.0)]
    _poly(icon.surface, haft, HAFT_COLOR, icon.border_color, icon.thin)
    orb = icon.at(0, -0.6)
    radius = max(3, int(icon.size * 0.38))
    pygame.draw.circle(icon.surface, icon.border_color, orb, radius + icon.thin)
    pygame.draw.circle(icon.surface, icon.color, orb, radius)
    glint = tuple(min(255, v + 60) for v in icon.color)
    pygame.draw.circle(icon.surface, glint, icon.at(-0.14, -0.72), max(1, int(icon.size * 0.12)))


def _draw_bow(icon: _Icon):
    # A curved limb with the string drawn straight across it, the one weapon
    # silhouette that isn't a stick with something on the end.
    rect = pygame.Rect(0, 0, int(icon.size * 1.4), int(icon.size * 2))
    rect.center = icon.at(-0.2, 0)
    pygame.draw.arc(
        icon.surface,
        icon.border_color,
        rect.inflate(icon.border_width, icon.border_width),
        -math.pi / 2,
        math.pi / 2,
        icon.border_width + 2,
    )
    pygame.draw.arc(icon.surface, icon.color, rect, -math.pi / 2, math.pi / 2, max(2, icon.border_width))
    pygame.draw.line(icon.surface, (235, 232, 220), icon.at(-0.2, -1.0), icon.at(-0.2, 1.0), max(1, icon.thin))


def _draw_cuirass(icon: _Icon):
    # Body armour: shoulders, a neck dip and a waisted torso, so it stops reading
    # as a second shield.
    torso = [
        icon.at(-0.72, -0.5),
        icon.at(-0.3, -0.62),
        icon.at(0, -0.42),
        icon.at(0.3, -0.62),
        icon.at(0.72, -0.5),
        icon.at(0.56, 0.3),
        icon.at(0.34, 0.86),
        icon.at(-0.34, 0.86),
        icon.at(-0.56, 0.3),
    ]
    _poly(icon.surface, torso, icon.color, icon.border_color, icon.border_width)
    pygame.draw.line(icon.surface, icon.border_color, icon.at(0, -0.42), icon.at(0, 0.84), icon.thin)
    belt = [icon.at(-0.6, 0.24), icon.at(0.6, 0.24), icon.at(0.57, 0.44), icon.at(-0.57, 0.44)]
    _poly(icon.surface, belt, GRIP_COLOR, icon.border_color, 1)


def _draw_shield(icon: _Icon):
    points = [
        (icon.cx - icon.size * 0.65, icon.cy - icon.size * 0.6),
        (icon.cx + icon.size * 0.65, icon.cy - icon.size * 0.6),
        (icon.cx + icon.size * 0.65, icon.cy + icon.size * 0.15),
        (icon.cx, icon.cy + icon.size * 0.85),
        (icon.cx - icon.size * 0.65, icon.cy + icon.size * 0.15),
    ]
    _poly(icon.surface, points, icon.color, icon.border_color, icon.border_width)
    # A spine down the middle and a raised boss: the two things that tell a shield
    # from a breastplate once the icon is down to a handful of pixels.
    pygame.draw.line(icon.surface, icon.border_color, icon.at(0, -0.6), icon.at(0, 0.85), icon.thin)
    pygame.draw.circle(icon.surface, icon.border_color, icon.at(0, -0.05), max(3, int(icon.size * 0.24)))
    boss = tuple(min(255, v + 55) for v in icon.color)
    pygame.draw.circle(icon.surface, boss, icon.at(0, -0.05), max(2, int(icon.size * 0.16)))


def _draw_gem(icon: _Icon):
    points = [
        (icon.cx, icon.cy - icon.size),
        (icon.cx + icon.size * 0.65, icon.cy),
        (icon.cx, icon.cy + icon.size),
        (icon.cx - icon.size * 0.65, icon.cy),
    ]
    pygame.draw.polygon(icon.surface, icon.color, points)
    pygame.draw.polygon(icon.surface, icon.border_color, points, icon.border_width)


def _draw_arrow(icon: _Icon):
    cx, cy, size = icon.cx, icon.cy, icon.size
    pygame.draw.line(icon.surface, icon.border_color, (cx, cy - size), (cx, cy + size * 0.6), icon.border_width + 2)
    pygame.draw.line(icon.surface, icon.color, (cx, cy - size), (cx, cy + size * 0.6), icon.border_width)
    head = [(cx, cy - size), (cx - size * 0.35, cy - size * 0.35), (cx + size * 0.35, cy - size * 0.35)]
    pygame.draw.polygon(icon.surface, icon.color, head)
    pygame.draw.polygon(icon.surface, icon.border_color, head, 1)
    fletch = [
        (cx, cy + size * 0.3),
        (cx - size * 0.3, cy + size * 0.6),
        (cx, cy + size * 0.45),
        (cx + size * 0.3, cy + size * 0.6),
    ]
    pygame.draw.polygon(icon.surface, icon.color, fletch)
    pygame.draw.polygon(icon.surface, icon.border_color, fletch, 1)


def _draw_flask(icon: _Icon):
    cx, cy, size = icon.cx, icon.cy, icon.size
    # Round-bottomed bottle: `color` is the liquid, the glass and cork are fixed.
    glass = (226, 234, 240)
    body_r = size * 0.6
    body_c = (int(cx), int(cy + size * 0.28))
    neck_w = max(3, size * 0.36)
    neck = pygame.Rect(int(cx - neck_w / 2), int(cy - size * 0.85), int(neck_w), int(size * 0.8))
    pygame.draw.rect(icon.surface, icon.border_color, neck.inflate(icon.border_width * 2, 0))
    pygame.draw.rect(icon.surface, glass, neck)
    pygame.draw.circle(icon.surface, icon.border_color, body_c, int(body_r + icon.border_width))
    pygame.draw.circle(icon.surface, icon.color, body_c, int(body_r))
    # Glint on the glass, so a filled bottle doesn't read as a plain ball.
    pygame.draw.circle(
        icon.surface,
        glass,
        (int(cx - body_r * 0.35), int(body_c[1] - body_r * 0.35)),
        max(1, int(size * 0.13)),
    )
    cork = pygame.Rect(int(cx - neck_w * 0.85), int(cy - size * 1.1), int(neck_w * 1.7), max(3, int(size * 0.3)))
    pygame.draw.rect(icon.surface, (168, 122, 74), cork)
    pygame.draw.rect(icon.surface, icon.border_color, cork, max(1, icon.border_width - 1))


def _draw_coin(icon: _Icon):
    pygame.draw.circle(icon.surface, icon.border_color, icon.center, icon.size + icon.border_width)
    pygame.draw.circle(icon.surface, icon.color, icon.center, icon.size)
    # Inner ring plus a small highlight so it reads as a minted coin, not a plain disc.
    pygame.draw.circle(
        icon.surface, icon.border_color, icon.center, int(icon.size * 0.62), max(1, icon.border_width - 1)
    )
    pygame.draw.circle(
        icon.surface,
        tuple(min(255, v + 40) for v in icon.color),
        (int(icon.cx - icon.size * 0.28), int(icon.cy - icon.size * 0.28)),
        max(2, icon.size // 6),
    )


def _draw_chest(icon: _Icon):
    half_w, half_h = icon.size * 0.75, icon.size * 0.55
    rect = pygame.Rect(0, 0, half_w * 2, half_h * 2)
    rect.center = icon.center
    pygame.draw.rect(icon.surface, icon.border_color, rect.inflate(icon.border_width * 2, icon.border_width * 2))
    pygame.draw.rect(icon.surface, icon.color, rect)
    lid_y = rect.top + rect.height * 0.4
    pygame.draw.line(icon.surface, c.Colors.BLACK, (rect.left, lid_y), (rect.right, lid_y), icon.border_width)
    pygame.draw.circle(icon.surface, c.Colors.BLACK, (icon.cx, int(lid_y)), max(2, icon.size // 8))


def _draw_bomb(icon: _Icon):
    """A round shell with a lit fuse: the same silhouette the thing has on the ground, so
    what is in the bag reads as what will be lying in the grass."""
    body = int(icon.size * 0.78)
    pygame.draw.circle(icon.surface, icon.border_color, icon.center, body + icon.border_width)
    pygame.draw.circle(icon.surface, icon.color, icon.center, body)
    pygame.draw.circle(
        icon.surface,
        tuple(min(255, v + 45) for v in icon.color),
        (int(icon.cx - body * 0.3), int(icon.cy - body * 0.3)),
        max(2, body // 4),
    )
    neck = (icon.cx, icon.cy - body)
    tip = (icon.cx + icon.size * 0.5, icon.cy - icon.size * 1.15)
    pygame.draw.line(icon.surface, c.Colors.BLACK, neck, tip, max(2, icon.border_width))
    pygame.draw.circle(icon.surface, c.Bombs.FUSE_COLOR, (int(tip[0]), int(tip[1])), max(2, icon.size // 5))


_SHAPES = {
    "bomb": _draw_bomb,
    "circle": _draw_circle,
    "sword": _draw_sword,
    "dagger": _draw_dagger,
    "axe": _draw_axe,
    "hammer": _draw_hammer,
    "spear": _draw_spear,
    "pole": _draw_pole,
    "boomerang": _draw_boomerang,
    "staff": _draw_staff,
    "bow": _draw_bow,
    "cuirass": _draw_cuirass,
    "shield": _draw_shield,
    "gem": _draw_gem,
    "arrow": _draw_arrow,
    "flask": _draw_flask,
    "coin": _draw_coin,
    "chest": _draw_chest,
}


def draw_shape_with_border(surface, shape, center, size, color, border_width, border_color=None):
    """Draw one item icon. `shape` is whatever `items.icon_shape` returned for it."""
    draw = _SHAPES.get(shape)
    if draw is None:
        return
    cx, cy = center
    draw(
        _Icon(
            surface=surface,
            center=center,
            cx=cx,
            cy=cy,
            size=size,
            color=color,
            border_color=border_color if border_color is not None else c.Colors.BLACK,
            border_width=border_width,
            thin=max(1, border_width - 1),
        )
    )
