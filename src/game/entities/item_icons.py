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


def _lit(color, amount: int = 46) -> tuple:
    """The lit face of a colour: what a highlight, a rim or a top face is painted in."""
    return tuple(min(255, v + amount) for v in color[:3])


def _shade(color, amount: int = 52) -> tuple:
    """The turned-away face of a colour, for the side of a bar or the inside of a bowl."""
    return tuple(max(0, v - amount) for v in color[:3])


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
    """A cut stone rather than a flat lozenge: a table across the top, the crown facets it is
    split into, and one facet left lit, which is what makes the outline read as faceted."""
    top, bottom = icon.cy - icon.size, icon.cy + icon.size
    girdle = icon.cy - icon.size * 0.25
    left, right = icon.cx - icon.size * 0.68, icon.cx + icon.size * 0.68
    table_l, table_r = icon.cx - icon.size * 0.3, icon.cx + icon.size * 0.3
    body = [(table_l, top), (table_r, top), (right, girdle), (icon.cx, bottom), (left, girdle)]
    pygame.draw.polygon(icon.surface, icon.color, body)
    # The table, then the pavilion below it: the stone in three tones, lightest on top.
    _poly(
        icon.surface,
        [(table_l, top), (table_r, top), (right, girdle), (left, girdle)],
        _lit(icon.color),
        icon.color,
        icon.thin,
    )
    pygame.draw.polygon(icon.surface, _shade(icon.color, 30), [(left, girdle), (icon.cx, bottom), (icon.cx, girdle)])
    for x in (table_l, table_r):
        pygame.draw.line(icon.surface, _shade(icon.color), (x, top), (icon.cx, bottom), icon.thin)
    pygame.draw.polygon(icon.surface, icon.border_color, body, icon.border_width)


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
    """A struck coin: a milled edge, a raised rim, a mark stamped into the face and the light
    coming off one side of it, so a purse of them reads as money rather than as discs."""
    pygame.draw.circle(icon.surface, icon.border_color, icon.center, icon.size + icon.border_width)
    pygame.draw.circle(icon.surface, icon.color, icon.center, icon.size)
    # Where the light falls: a bright arc along the top left edge and a dark one opposite,
    # which is what gives a flat disc a thickness.
    face = pygame.Rect(0, 0, icon.size * 2, icon.size * 2)
    face.center = icon.center
    band = max(2, int(icon.size * 0.22))
    pygame.draw.arc(icon.surface, _lit(icon.color, 40), face, math.pi * 0.35, math.pi * 1.05, band)
    pygame.draw.arc(icon.surface, _shade(icon.color, 30), face, math.pi * 1.35, math.pi * 2.05, band)
    # Milling: short ticks round the edge, which is the detail that says the thing was struck.
    for i in range(12):
        angle = i * math.pi / 6
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        pygame.draw.line(
            icon.surface,
            _shade(icon.color),
            (icon.cx + cos_a * icon.size * 0.82, icon.cy + sin_a * icon.size * 0.82),
            (icon.cx + cos_a * icon.size, icon.cy + sin_a * icon.size),
            icon.thin,
        )
    pygame.draw.circle(icon.surface, _shade(icon.color), icon.center, int(icon.size * 0.66), icon.thin)
    # The stamped face: a four-pointed mark, engraved rather than raised.
    mark = [icon.at(0, -0.4), icon.at(0.18, 0), icon.at(0, 0.4), icon.at(-0.18, 0)]
    _poly(icon.surface, mark, _shade(icon.color, 34), _shade(icon.color, 70), icon.thin)


def _draw_goblet(icon: _Icon):
    """A drinking cup off a rich table: bowl, stem and foot, with the rim caught by the light
    and the inside of the bowl darker than its outside."""
    bowl = [icon.at(-0.62, -0.7), icon.at(0.62, -0.7), icon.at(0.34, 0.05), icon.at(-0.34, 0.05)]
    _poly(icon.surface, bowl, icon.color, icon.border_color, icon.border_width)
    rim = pygame.Rect(0, 0, icon.size * 1.24, icon.size * 0.3)
    rim.center = icon.at(0, -0.7)
    pygame.draw.ellipse(icon.surface, _shade(icon.color, 40), rim)
    pygame.draw.ellipse(icon.surface, icon.border_color, rim, icon.thin)
    pygame.draw.line(icon.surface, _lit(icon.color), icon.at(-0.42, -0.5), icon.at(-0.26, -0.02), icon.thin)
    stem = pygame.Rect(0, 0, max(3, icon.size * 0.22), icon.size * 0.55)
    stem.midtop = icon.at(0, 0.02)
    pygame.draw.rect(icon.surface, icon.color, stem)
    pygame.draw.rect(icon.surface, icon.border_color, stem, icon.thin)
    foot = [icon.at(-0.55, 0.9), icon.at(0.55, 0.9), icon.at(0.3, 0.56), icon.at(-0.3, 0.56)]
    _poly(icon.surface, foot, icon.color, icon.border_color, icon.thin)


def _draw_idol(icon: _Icon):
    """A carved figure lifted out of a ruin: a squat body on a plinth with a cut face. Stone,
    so the tone is flat and the detail is engraved into it rather than shining off it."""
    plinth = pygame.Rect(0, 0, icon.size * 1.5, icon.size * 0.34)
    plinth.midbottom = icon.at(0, 1.0)
    pygame.draw.rect(icon.surface, _shade(icon.color, 34), plinth)
    pygame.draw.rect(icon.surface, icon.border_color, plinth, icon.thin)
    body = [icon.at(-0.5, 0.66), icon.at(-0.36, -0.2), icon.at(0.36, -0.2), icon.at(0.5, 0.66)]
    _poly(icon.surface, body, icon.color, icon.border_color, icon.border_width)
    head = pygame.Rect(0, 0, icon.size * 0.86, icon.size * 0.8)
    head.midbottom = icon.at(0, -0.16)
    pygame.draw.ellipse(icon.surface, icon.color, head)
    pygame.draw.ellipse(icon.surface, icon.border_color, head, icon.border_width)
    # The face and the arms folded across the chest, cut in as lines.
    for side in (-1, 1):
        pygame.draw.line(
            icon.surface, icon.border_color, icon.at(side * 0.2, -0.56), icon.at(side * 0.2, -0.44), icon.thin
        )
    pygame.draw.line(icon.surface, _shade(icon.color), icon.at(-0.3, 0.2), icon.at(0.3, 0.2), icon.thin)
    pygame.draw.line(icon.surface, _shade(icon.color), icon.at(-0.24, 0.42), icon.at(0.24, 0.42), icon.thin)


def _draw_ingot(icon: _Icon):
    """A cast bar seen from a corner: a lit top face, a front and a side in two darker tones,
    which is the whole reason it reads as a solid block of metal."""
    top = [icon.at(-0.5, -0.5), icon.at(0.62, -0.5), icon.at(0.86, -0.1), icon.at(-0.26, -0.1)]
    front = [icon.at(-0.26, -0.1), icon.at(0.86, -0.1), icon.at(0.86, 0.44), icon.at(-0.26, 0.44)]
    side = [icon.at(-0.5, -0.5), icon.at(-0.26, -0.1), icon.at(-0.26, 0.44), icon.at(-0.72, 0.04)]
    _poly(icon.surface, front, icon.color, icon.border_color, icon.border_width)
    _poly(icon.surface, side, _shade(icon.color), icon.border_color, icon.border_width)
    _poly(icon.surface, top, _lit(icon.color), icon.border_color, icon.border_width)
    pygame.draw.line(icon.surface, _lit(icon.color, 70), icon.at(-0.36, -0.36), icon.at(0.5, -0.36), icon.thin)


def _draw_skull(icon: _Icon):
    """A trophy skull: cranium, sunken sockets and a jaw. Sold rather than worn, so it is
    drawn small and whole instead of as a fragment."""
    cranium = pygame.Rect(0, 0, icon.size * 1.5, icon.size * 1.36)
    cranium.center = icon.at(0, -0.16)
    pygame.draw.ellipse(icon.surface, icon.color, cranium)
    pygame.draw.ellipse(icon.surface, icon.border_color, cranium, icon.border_width)
    jaw = [icon.at(-0.44, 0.34), icon.at(0.44, 0.34), icon.at(0.34, 0.8), icon.at(-0.34, 0.8)]
    _poly(icon.surface, jaw, _shade(icon.color, 24), icon.border_color, icon.border_width)
    for side in (-1, 1):
        socket = pygame.Rect(0, 0, icon.size * 0.44, icon.size * 0.42)
        socket.center = icon.at(side * 0.34, -0.24)
        pygame.draw.ellipse(icon.surface, icon.border_color, socket)
    _poly(
        icon.surface,
        [icon.at(0, 0.02), icon.at(0.13, 0.24), icon.at(-0.13, 0.24)],
        icon.border_color,
        icon.border_color,
        icon.thin,
    )
    for offset in (-0.2, 0.0, 0.2):
        pygame.draw.line(icon.surface, icon.border_color, icon.at(offset, 0.4), icon.at(offset, 0.74), icon.thin)


def _draw_crown(icon: _Icon):
    """Somebody's crown, in a bag on its way to a merchant: a banded circlet with three
    points and a stone set in the middle of the band."""
    points = [
        icon.at(-0.8, 0.36),
        icon.at(-0.8, -0.6),
        icon.at(-0.4, -0.16),
        icon.at(0, -0.76),
        icon.at(0.4, -0.16),
        icon.at(0.8, -0.6),
        icon.at(0.8, 0.36),
    ]
    _poly(icon.surface, points, icon.color, icon.border_color, icon.border_width)
    band = pygame.Rect(0, 0, icon.size * 1.6, icon.size * 0.4)
    band.midtop = icon.at(0, 0.2)
    pygame.draw.rect(icon.surface, _shade(icon.color, 30), band)
    pygame.draw.rect(icon.surface, icon.border_color, band, icon.thin)
    for tip in (icon.at(-0.8, -0.6), icon.at(0, -0.76), icon.at(0.8, -0.6)):
        pygame.draw.circle(icon.surface, _lit(icon.color, 60), tip, max(2, int(icon.size * 0.13)))
        pygame.draw.circle(icon.surface, icon.border_color, tip, max(2, int(icon.size * 0.13)), icon.thin)
    jewel = [icon.at(0, 0.22), icon.at(0.16, 0.4), icon.at(0, 0.58), icon.at(-0.16, 0.4)]
    _poly(icon.surface, jewel, (196, 62, 72), icon.border_color, icon.thin)


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
    "goblet": _draw_goblet,
    "idol": _draw_idol,
    "ingot": _draw_ingot,
    "skull": _draw_skull,
    "crown": _draw_crown,
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
