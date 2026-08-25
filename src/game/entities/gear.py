"""Drawing for the gear a character visibly carries: a weapon in each hand, an
armour ring on the body, an accessory gem on the chest.

Everything here draws in the character's local, unrotated space (body centred,
forward is -y). `draw_human` calls into it before rotating the sprite, so gear
turns with the facing and follows the swinging arm for free.
"""

import math

import pygame

import core.constants as c
from game.entities.item_icons import draw_shape_with_border

# Visual length of a weapon as a multiple of the character size. Roughly tracks the
# archetype's reach so a spear reads as long and a dagger as short.
WEAPON_LENGTH = {
    "dagger": 0.75,
    "knife": 0.6,
    "sword": 1.15,
    "axe": 1.05,
    "hatchet": 0.8,
    "hammer": 1.0,
    "mace": 1.0,
    "club": 0.95,
    "spear": 2.4,
    "pitchfork": 2.2,
    "halberd": 2.3,
    "staff": 1.55,
    "bow": 1.0,
    "pole": 1.9,
    "boomerang": 0.8,
    "tool": 1.25,
    "hoe": 1.35,
    "rake": 1.35,
    "scythe": 1.7,
    "sickle": 0.7,
    "shovel": 1.4,
    "broom": 1.4,
    "poker": 1.2,
    "tongs": 1.0,
    "rolling_pin": 0.7,
    "bomb": 0.5,
}

GRIP_COLOR = (85, 62, 40)
STRING_COLOR = (215, 210, 195)

REST_ANGLE = 0.35  # radians the weapon tilts outward from straight ahead at rest
SWING_ARC = 1.9  # radians swept inward over an attack animation


def weapon_length(kind: str, size: int) -> float:
    return size * WEAPON_LENGTH.get(kind, 1.0)


def gear_padding(gear: dict, size: int) -> int:
    """Extra room the sprite surface needs so a held weapon isn't clipped."""
    lengths = [weapon_length(gear[slot]["kind"], size) for slot in ("hand1", "hand2") if gear.get(slot)]
    if gear.get("offhand"):
        lengths.append(size * 1.1)
    return int(max(lengths, default=0)) + 6


def _rotate(points, angle: float, origin):
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    ox, oy = origin
    return [(ox + px * cos_a - py * sin_a, oy + px * sin_a + py * cos_a) for px, py in points]


def _bezier(start, control, end, steps=10):
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        points.append(
            (
                u * u * start[0] + 2 * u * t * control[0] + t * t * end[0],
                u * u * start[1] + 2 * u * t * control[1] + t * t * end[1],
            )
        )
    return points


# Every weapon shape, in weapon-local space: grip at (0, 0), tip toward -y, sized by the
# blade length `L`. Each part is (kind, geometry, style) where style picks the colour:
# "metal" takes the item colour with a rarity-coloured border, "grip" and "string" are
# fixed. Pure data, so adding a weapon family is a row here rather than a branch.
_WEAPON_PARTS = {
    "bow": lambda L: [
        ("lines", ((-L * 0.4, -L * 0.3), (L * 0.4, -L * 0.3)), "string"),
        ("lines", _bezier((-L * 0.4, -L * 0.3), (0, -L * 1.45), (L * 0.4, -L * 0.3)), "metal"),
    ],
    "staff": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.86)), "grip"),
        ("circle", ((0, -L * 0.9), L * 0.14), "metal"),
    ],
    # A long shaft capped at both ends: what a pole hits with is its weight, so nothing on
    # it comes to a point.
    "pole": lambda L: [
        ("lines", ((0, L * 0.34), (0, -L * 0.82)), "grip"),
        ("poly", [(-L * 0.16, -L * 0.78), (L * 0.16, -L * 0.78), (L * 0.16, -L), (-L * 0.16, -L)], "metal"),
        ("poly", [(-L * 0.14, L * 0.3), (L * 0.14, L * 0.3), (L * 0.14, L * 0.44), (-L * 0.14, L * 0.44)], "metal"),
    ],
    # Held out at the elbow of the blade, the way it is thrown.
    "boomerang": lambda L: [
        (
            "poly",
            [
                (-L * 0.15, L * 0.1),
                (-L * 0.55, -L * 0.75),
                (-L * 0.2, -L * 0.95),
                (L * 0.1, -L * 0.2),
                (L * 0.85, L * 0.15),
                (L * 0.7, L * 0.5),
            ],
            "metal",
        ),
    ],
    "spear": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.82)), "grip"),
        ("poly", [(-L * 0.1, -L * 0.78), (0, -L), (L * 0.1, -L * 0.78)], "metal"),
    ],
    "hammer": lambda L: [
        ("lines", ((0, L * 0.08), (0, -L * 0.72)), "grip"),
        ("poly", [(-L * 0.3, -L * 0.68), (L * 0.3, -L * 0.68), (L * 0.3, -L * 0.98), (-L * 0.3, -L * 0.98)], "metal"),
    ],
    "axe": lambda L: [
        ("lines", ((0, L * 0.08), (0, -L * 0.96)), "grip"),
        ("poly", [(L * 0.04, -L * 0.96), (L * 0.5, -L * 0.82), (L * 0.5, -L * 0.54), (L * 0.04, -L * 0.6)], "metal"),
    ],
    "dagger": lambda L: [
        ("lines", ((0, L * 0.08), (0, -L * 0.28)), "grip"),
        (
            "poly",
            [(-L * 0.14, -L * 0.26), (L * 0.14, -L * 0.26), (L * 0.14, -L * 0.34), (-L * 0.14, -L * 0.34)],
            "metal",
        ),
        (
            "poly",
            [(-L * 0.09, -L * 0.34), (L * 0.09, -L * 0.34), (L * 0.09, -L * 0.84), (0, -L), (-L * 0.09, -L * 0.84)],
            "metal",
        ),
    ],
    # A haft with a crosspiece head: a hoe, a rake, a poker, whatever was on the wall.
    "tool": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.86)), "grip"),
        (
            "poly",
            [(-L * 0.22, -L * 0.84), (L * 0.22, -L * 0.84), (L * 0.22, -L * 0.96), (-L * 0.22, -L * 0.96)],
            "metal",
        ),
    ],
    # A haft with the head set across the top, hanging over one side: what a field is
    # worked with, and the reason a hoe never reads as a short axe.
    "hoe": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.9)), "grip"),
        ("poly", [(0, -L * 0.86), (L * 0.42, -L * 0.86), (L * 0.42, -L * 0.98), (0, -L * 0.98)], "metal"),
    ],
    "rake": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.88)), "grip"),
        ("lines", ((-L * 0.26, -L * 0.88), (L * 0.26, -L * 0.88)), "metal"),
        *[("lines", ((x, -L * 0.88), (x, -L * 0.72)), "metal") for x in (-L * 0.26, -L * 0.09, L * 0.09, L * 0.26)],
    ],
    # The blade comes off the bottom of the snath and sweeps away: a scythe is read by how
    # far to one side it reaches, not by its shaft.
    "scythe": lambda L: [
        ("lines", ((0, L * 0.15), (0, -L * 0.82)), "grip"),
        ("lines", _bezier((0, -L * 0.8), (L * 0.55, -L * 0.75), (L * 0.78, -L * 0.3)), "metal"),
    ],
    "sickle": lambda L: [
        ("lines", ((0, L * 0.2), (0, -L * 0.2)), "grip"),
        ("lines", _bezier((0, -L * 0.2), (L * 0.75, -L * 0.5), (L * 0.15, -L * 0.95)), "metal"),
    ],
    "shovel": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.7)), "grip"),
        (
            "poly",
            [(-L * 0.2, -L * 0.68), (L * 0.2, -L * 0.68), (L * 0.16, -L * 0.94), (0, -L), (-L * 0.16, -L * 0.94)],
            "metal",
        ),
    ],
    "broom": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.66)), "grip"),
        ("poly", [(-L * 0.1, -L * 0.64), (L * 0.1, -L * 0.64), (L * 0.26, -L), (-L * 0.26, -L)], "metal"),
    ],
    # A bent iron rod: no head at all, which is the point of somebody defending a house
    # with what was in the fireplace.
    "poker": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.86)), "metal"),
        ("lines", ((0, -L * 0.86), (L * 0.22, -L * 0.98)), "metal"),
    ],
    "tongs": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.5)), "grip"),
        ("lines", ((0, -L * 0.5), (-L * 0.2, -L)), "metal"),
        ("lines", ((0, -L * 0.5), (L * 0.2, -L)), "metal"),
    ],
    "rolling_pin": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.15)), "grip"),
        (
            "poly",
            [(-L * 0.22, -L * 0.15), (L * 0.22, -L * 0.15), (L * 0.22, -L * 0.85), (-L * 0.22, -L * 0.85)],
            "metal",
        ),
        ("lines", ((0, -L * 0.85), (0, -L)), "grip"),
    ],
    # Three long tines: a pitchfork thrusts like a spear and looks like nothing else.
    "pitchfork": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.74)), "grip"),
        ("lines", ((-L * 0.14, -L * 0.74), (L * 0.14, -L * 0.74)), "metal"),
        *[("lines", ((x, -L * 0.74), (x, -L)), "metal") for x in (-L * 0.14, 0, L * 0.14)],
    ],
    # A spear that also carries an axe head, which is the whole of what a halberd is.
    "halberd": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.82)), "grip"),
        ("poly", [(-L * 0.07, -L * 0.8), (0, -L), (L * 0.07, -L * 0.8)], "metal"),
        ("poly", [(L * 0.04, -L * 0.82), (L * 0.34, -L * 0.72), (L * 0.34, -L * 0.5), (L * 0.04, -L * 0.58)], "metal"),
    ],
    "hatchet": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.9)), "grip"),
        ("poly", [(L * 0.04, -L * 0.92), (L * 0.42, -L * 0.8), (L * 0.42, -L * 0.56), (L * 0.04, -L * 0.62)], "metal"),
    ],
    # A ball of iron on a short haft, with the flanges that tell it from a club.
    "mace": lambda L: [
        ("lines", ((0, L * 0.1), (0, -L * 0.66)), "grip"),
        ("circle", ((0, -L * 0.8), L * 0.2), "metal"),
        *[
            (
                "poly",
                [(0, -L * 0.8), (dx * L * 0.34, -L * 0.8 + dy * L * 0.34), (dx * L * 0.1, -L * 0.8 - dy * L * 0.1)],
                "metal",
            )
            for dx, dy in ((-1, 0), (1, 0), (0, -1))
        ],
    ],
    # No head and no edge: a length of wood, thicker at the end that does the work.
    "club": lambda L: [
        (
            "poly",
            [(-L * 0.08, L * 0.12), (L * 0.08, L * 0.12), (L * 0.2, -L * 0.95), (-L * 0.2, -L * 0.95)],
            "wood",
        ),
    ],
    "knife": lambda L: [
        ("lines", ((0, L * 0.12), (0, -L * 0.2)), "grip"),
        (
            "poly",
            [(-L * 0.1, -L * 0.2), (L * 0.1, -L * 0.2), (L * 0.06, -L * 0.86), (0, -L), (-L * 0.06, -L * 0.86)],
            "metal",
        ),
    ],
    # Held rather than swung: a shell in the fist with the fuse standing off it.
    "bomb": lambda L: [
        ("circle", ((0, -L * 0.45), L * 0.45), "metal"),
        ("lines", ((0, -L * 0.9), (L * 0.3, -L * 1.2)), "string"),
    ],
    "sword": lambda L: [
        ("lines", ((0, L * 0.08), (0, -L * 0.2)), "grip"),
        (
            "poly",
            [(-L * 0.19, -L * 0.18), (L * 0.19, -L * 0.18), (L * 0.19, -L * 0.27), (-L * 0.19, -L * 0.27)],
            "metal",
        ),
        (
            "poly",
            [(-L * 0.1, -L * 0.27), (L * 0.1, -L * 0.27), (L * 0.1, -L * 0.86), (0, -L), (-L * 0.1, -L * 0.86)],
            "metal",
        ),
    ],
}


def _weapon_parts(kind: str, length: float) -> list:
    """The primitives making up a weapon, sized to `length`. Anything whose archetype has no
    silhouette of its own falls back to the sword."""
    return _WEAPON_PARTS.get(kind, _WEAPON_PARTS["sword"])(length)


def draw_weapon(surface, hand_pos, spec: dict, size: int, hand: str, attack_progress: float):
    """Draw a held weapon anchored at the hand, swept inward by the swing animation."""
    length = weapon_length(spec["kind"], size)
    if length <= 0:
        return

    # A bow is held square to the aim; everything else rests tilted outward.
    rest = 0.12 if spec["kind"] == "bow" else REST_ANGLE
    angle = rest - math.sin(attack_progress * math.pi) * SWING_ARC
    if hand == "left":
        angle = -angle

    color, outline = spec["color"], spec["outline"]
    for part, geometry, style in _weapon_parts(spec["kind"], length):
        if part == "circle":
            (cx, cy), radius = geometry
            center = _rotate([(cx, cy)], angle, hand_pos)[0]
            pygame.draw.circle(surface, outline, center, int(radius) + 2)
            pygame.draw.circle(surface, color, center, int(radius))
        elif part == "poly":
            points = _rotate(geometry, angle, hand_pos)
            fill = GRIP_COLOR if style == "wood" else color
            pygame.draw.polygon(surface, fill, points)
            pygame.draw.polygon(surface, c.Colors.BLACK if style == "wood" else outline, points, 2)
        else:  # a shaft, a bow stave or its string
            points = _rotate(geometry, angle, hand_pos)
            if style == "grip":
                pygame.draw.lines(surface, c.Colors.BLACK, False, points, 6)
                pygame.draw.lines(surface, GRIP_COLOR, False, points, 4)
            elif style == "string":
                pygame.draw.lines(surface, STRING_COLOR, False, points, 2)
            else:
                pygame.draw.lines(surface, outline, False, points, 6)
                pygame.draw.lines(surface, color, False, points, 3)


def draw_shield(surface, body_center, spec: dict, size: int):
    """Draw the shield strapped to the offhand side of the body.

    It is worn, not held: on the arm's side of the torso while it is down, swung round in
    front of that shoulder while it is raised. That side is where it actually protects
    (`Player._blocks_hit` reads the same wedge), so what the player sees on the sprite is
    what the damage maths does, and turning the shield onto a blow is a real thing to do.

    Left is the offhand in this sprite: forward is -y and the offhand arm sits at -x, so
    the shield hangs off the body's left and swings forward from there.
    """
    raised = spec.get("raised")
    width, height = size * 0.66, size * 0.86
    if raised:
        cx = body_center[0] - size * 0.34
        cy = body_center[1] - size * 0.52
    else:
        cx = body_center[0] - size * 0.62
        cy = body_center[1] + size * 0.08
        width, height = width * 0.9, height * 0.9

    face = [
        (cx - width / 2, cy - height / 2),
        (cx + width / 2, cy - height / 2),
        (cx + width / 2, cy + height * 0.1),
        (cx, cy + height / 2),
        (cx - width / 2, cy + height * 0.1),
    ]
    pygame.draw.polygon(surface, spec["color"], face)
    pygame.draw.polygon(surface, spec["outline"], face, 2)
    pygame.draw.circle(surface, spec["outline"], (int(cx), int(cy - height * 0.1)), max(2, int(size * 0.09)), 2)


def draw_armor_band(surface, center, size: int, color, outline):
    """A ring on the body in the armour's colour, so worn armour reads from any facing."""
    radius = int(size * 0.36)
    pygame.draw.circle(surface, outline, center, radius + 2, 3)
    pygame.draw.circle(surface, color, center, radius, 3)


def draw_accessory(surface, center, size: int, color, outline):
    """A small gem on the chest, in the accessory's colour."""
    draw_shape_with_border(surface, "gem", center, max(3, int(size * 0.15)), color, 2, outline)
