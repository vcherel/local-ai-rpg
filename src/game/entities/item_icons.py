"""The vector art an item icon is drawn from.

Kept apart from `items.py`, which owns what an item *is*: the shape is chosen there
(`items.icon_shape`) and drawn here, so a search for an item's behaviour never lands in a
hundred lines of polygon coordinates and vice versa. Every branch of
`draw_shape_with_border` matches one string `icon_shape` can return.
"""

import math

import pygame

import core.constants as c

# Wood and leather on a weapon's haft and grip. Fixed rather than taken from the item's
# colour, so the metal head stands out against the handle instead of the whole icon being
# one silhouette in one tint.
HAFT_COLOR = (138, 96, 58)
GRIP_COLOR = (92, 62, 44)


def _poly(surface, points, color, border_color, border_width):
    pygame.draw.polygon(surface, color, points)
    pygame.draw.polygon(surface, border_color, points, border_width)


def draw_shape_with_border(surface, shape, center, size, color, border_width, border_color=None):
    if border_color is None:
        border_color = c.Colors.BLACK
    cx, cy = center
    thin = max(1, border_width - 1)

    def at(fx, fy):
        """A point given as a fraction of `size` from the icon's centre."""
        return (cx + size * fx, cy + size * fy)

    if shape == "circle":
        pygame.draw.circle(surface, border_color, center, size + border_width)
        pygame.draw.circle(surface, color, center, size)
    elif shape == "sword":
        # Straight blade with a crossguard, wrapped grip and pommel.
        pygame.draw.line(surface, GRIP_COLOR, at(0, 0.25), at(0, 0.85), max(3, int(size * 0.22)))
        pygame.draw.circle(surface, color, at(0, 0.92), max(2, int(size * 0.16)))
        pygame.draw.circle(surface, border_color, at(0, 0.92), max(2, int(size * 0.16)), thin)
        guard = [at(-0.62, 0.16), at(0.62, 0.16), at(0.62, 0.32), at(-0.62, 0.32)]
        _poly(surface, guard, color, border_color, thin)
        blade = [at(0, -1.0), at(0.24, -0.6), at(0.24, 0.18), at(-0.24, 0.18), at(-0.24, -0.6)]
        _poly(surface, blade, color, border_color, border_width)
    elif shape == "dagger":
        # A short blade over an oversized handle: the proportions, not the outline, are
        # what stop it reading as a small sword.
        pygame.draw.line(surface, GRIP_COLOR, at(0, 0.28), at(0, 0.78), max(4, int(size * 0.26)))
        pygame.draw.circle(surface, color, at(0, 0.88), max(3, int(size * 0.18)))
        pygame.draw.circle(surface, border_color, at(0, 0.88), max(3, int(size * 0.18)), thin)
        guard = [at(-0.55, 0.1), at(0.55, 0.1), at(0.55, 0.28), at(-0.55, 0.28)]
        _poly(surface, guard, color, border_color, thin)
        blade = [at(0, -0.62), at(0.28, -0.2), at(0.28, 0.12), at(-0.28, 0.12), at(-0.28, -0.2)]
        _poly(surface, blade, color, border_color, border_width)
    elif shape == "axe":
        haft = [at(-0.22, -0.98), at(0.04, -0.98), at(0.04, 0.98), at(-0.22, 0.98)]
        _poly(surface, haft, HAFT_COLOR, border_color, thin)
        # A single bit gripping the haft over a short eye and flaring into horns above
        # and below it. Without the horns the head is just a blob on a pole, which reads
        # as a pennant rather than an axe.
        head = [
            at(-0.02, -0.9),
            at(0.5, -1.0),
            at(0.95, -0.55),
            at(1.0, -0.1),
            at(0.62, 0.28),
            at(0.28, 0.1),
            at(-0.02, -0.35),
        ]
        _poly(surface, head, color, border_color, border_width)
    elif shape == "hammer":
        haft = [at(-0.14, -0.7), at(0.14, -0.7), at(0.14, 0.98), at(-0.14, 0.98)]
        _poly(surface, haft, HAFT_COLOR, border_color, thin)
        # Tall and narrow rather than wide and flat, which read as a signpost.
        head = [at(-0.56, -0.98), at(0.56, -0.98), at(0.56, -0.24), at(-0.56, -0.24)]
        _poly(surface, head, color, border_color, border_width)
        pygame.draw.line(surface, border_color, at(-0.2, -0.98), at(-0.2, -0.24), thin)
        pygame.draw.line(surface, border_color, at(0.2, -0.98), at(0.2, -0.24), thin)
    elif shape == "spear":
        haft = [at(-0.13, -0.4), at(0.13, -0.4), at(0.13, 1.0), at(-0.13, 1.0)]
        _poly(surface, haft, HAFT_COLOR, border_color, thin)
        # A leaf blade with shoulders, long enough to be the thing you notice: a small
        # diamond on a pole is indistinguishable from the staff's orb at icon size.
        point = [at(0, -1.0), at(0.34, -0.5), at(0.2, -0.28), at(0, -0.2), at(-0.2, -0.28), at(-0.34, -0.5)]
        _poly(surface, point, color, border_color, border_width)
    elif shape == "staff":
        haft = [at(-0.13, -0.4), at(0.13, -0.4), at(0.13, 1.0), at(-0.13, 1.0)]
        _poly(surface, haft, HAFT_COLOR, border_color, thin)
        orb = at(0, -0.6)
        radius = max(3, int(size * 0.38))
        pygame.draw.circle(surface, border_color, orb, radius + thin)
        pygame.draw.circle(surface, color, orb, radius)
        pygame.draw.circle(surface, tuple(min(255, v + 60) for v in color), at(-0.14, -0.72), max(1, int(size * 0.12)))
    elif shape == "bow":
        # A curved limb with the string drawn straight across it, the one weapon
        # silhouette that isn't a stick with something on the end.
        rect = pygame.Rect(0, 0, int(size * 1.4), int(size * 2))
        rect.center = at(-0.2, 0)
        pygame.draw.arc(
            surface, border_color, rect.inflate(border_width, border_width), -math.pi / 2, math.pi / 2, border_width + 2
        )
        pygame.draw.arc(surface, color, rect, -math.pi / 2, math.pi / 2, max(2, border_width))
        pygame.draw.line(surface, (235, 232, 220), at(-0.2, -1.0), at(-0.2, 1.0), max(1, thin))
    elif shape == "cuirass":
        # Body armour: shoulders, a neck dip and a waisted torso, so it stops reading
        # as a second shield.
        torso = [
            at(-0.72, -0.5),
            at(-0.3, -0.62),
            at(0, -0.42),
            at(0.3, -0.62),
            at(0.72, -0.5),
            at(0.56, 0.3),
            at(0.34, 0.86),
            at(-0.34, 0.86),
            at(-0.56, 0.3),
        ]
        _poly(surface, torso, color, border_color, border_width)
        pygame.draw.line(surface, border_color, at(0, -0.42), at(0, 0.84), thin)
        belt = [at(-0.6, 0.24), at(0.6, 0.24), at(0.57, 0.44), at(-0.57, 0.44)]
        _poly(surface, belt, GRIP_COLOR, border_color, 1)
    elif shape == "shield":
        points = [
            (cx - size * 0.65, cy - size * 0.6),
            (cx + size * 0.65, cy - size * 0.6),
            (cx + size * 0.65, cy + size * 0.15),
            (cx, cy + size * 0.85),
            (cx - size * 0.65, cy + size * 0.15),
        ]
        _poly(surface, points, color, border_color, border_width)
        # A spine down the middle and a raised boss: the two things that tell a shield
        # from a breastplate once the icon is down to a handful of pixels.
        pygame.draw.line(surface, border_color, at(0, -0.6), at(0, 0.85), thin)
        pygame.draw.circle(surface, border_color, at(0, -0.05), max(3, int(size * 0.24)))
        pygame.draw.circle(surface, tuple(min(255, v + 55) for v in color), at(0, -0.05), max(2, int(size * 0.16)))
    elif shape == "gem":
        points = [
            (cx, cy - size),
            (cx + size * 0.65, cy),
            (cx, cy + size),
            (cx - size * 0.65, cy),
        ]
        pygame.draw.polygon(surface, color, points)
        pygame.draw.polygon(surface, border_color, points, border_width)
    elif shape == "arrow":
        pygame.draw.line(surface, border_color, (cx, cy - size), (cx, cy + size * 0.6), border_width + 2)
        pygame.draw.line(surface, color, (cx, cy - size), (cx, cy + size * 0.6), border_width)
        head = [(cx, cy - size), (cx - size * 0.35, cy - size * 0.35), (cx + size * 0.35, cy - size * 0.35)]
        pygame.draw.polygon(surface, color, head)
        pygame.draw.polygon(surface, border_color, head, 1)
        fletch = [
            (cx, cy + size * 0.3),
            (cx - size * 0.3, cy + size * 0.6),
            (cx, cy + size * 0.45),
            (cx + size * 0.3, cy + size * 0.6),
        ]
        pygame.draw.polygon(surface, color, fletch)
        pygame.draw.polygon(surface, border_color, fletch, 1)
    elif shape == "flask":
        # Round-bottomed bottle: `color` is the liquid, the glass and cork are fixed.
        glass = (226, 234, 240)
        body_r = size * 0.6
        body_c = (int(cx), int(cy + size * 0.28))
        neck_w = max(3, size * 0.36)
        neck = pygame.Rect(int(cx - neck_w / 2), int(cy - size * 0.85), int(neck_w), int(size * 0.8))
        pygame.draw.rect(surface, border_color, neck.inflate(border_width * 2, 0))
        pygame.draw.rect(surface, glass, neck)
        pygame.draw.circle(surface, border_color, body_c, int(body_r + border_width))
        pygame.draw.circle(surface, color, body_c, int(body_r))
        # Glint on the glass, so a filled bottle doesn't read as a plain ball.
        pygame.draw.circle(
            surface,
            glass,
            (int(cx - body_r * 0.35), int(body_c[1] - body_r * 0.35)),
            max(1, int(size * 0.13)),
        )
        cork = pygame.Rect(int(cx - neck_w * 0.85), int(cy - size * 1.1), int(neck_w * 1.7), max(3, int(size * 0.3)))
        pygame.draw.rect(surface, (168, 122, 74), cork)
        pygame.draw.rect(surface, border_color, cork, max(1, border_width - 1))
    elif shape == "coin":
        pygame.draw.circle(surface, border_color, center, size + border_width)
        pygame.draw.circle(surface, color, center, size)
        # Inner ring plus a small highlight so it reads as a minted coin, not a plain disc.
        pygame.draw.circle(surface, border_color, center, int(size * 0.62), max(1, border_width - 1))
        pygame.draw.circle(
            surface,
            tuple(min(255, v + 40) for v in color),
            (int(cx - size * 0.28), int(cy - size * 0.28)),
            max(2, size // 6),
        )
    elif shape == "chest":
        half_w, half_h = size * 0.75, size * 0.55
        rect = pygame.Rect(0, 0, half_w * 2, half_h * 2)
        rect.center = center
        pygame.draw.rect(surface, border_color, rect.inflate(border_width * 2, border_width * 2))
        pygame.draw.rect(surface, color, rect)
        lid_y = rect.top + rect.height * 0.4
        pygame.draw.line(surface, c.Colors.BLACK, (rect.left, lid_y), (rect.right, lid_y), border_width)
        pygame.draw.circle(surface, c.Colors.BLACK, (cx, int(lid_y)), max(2, size // 8))
