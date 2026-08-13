"""Drawing for the gear a character visibly carries: a weapon in each hand, an
armour ring on the body, an accessory gem on the chest.

Everything here draws in the character's local, unrotated space (body centred,
forward is -y). `draw_human` calls into it before rotating the sprite, so gear
turns with the facing and follows the swinging arm for free.
"""

import math

import pygame

import core.constants as c
from game.entities.items import draw_shape_with_border

# Visual length of a weapon as a multiple of the character size. Roughly tracks the
# archetype's reach so a spear reads as long and a dagger as short.
WEAPON_LENGTH = {
    "dagger": 0.75,
    "sword": 1.15,
    "axe": 1.05,
    "hammer": 1.0,
    "spear": 2.4,
    "staff": 1.55,
    "bow": 1.0,
}

GRIP_COLOR = (85, 62, 40)
STRING_COLOR = (215, 210, 195)

REST_ANGLE = 0.35  # radians the weapon tilts outward from straight ahead at rest
SWING_ARC = 1.9  # radians swept inward over an attack animation


def weapon_length(kind: str, size: int) -> float:
    return size * WEAPON_LENGTH.get(kind, 1.0)


def gear_padding(gear: dict, size: int) -> int:
    """Extra room the sprite surface needs so a held weapon isn't clipped."""
    lengths = [weapon_length(gear[slot]["kind"], size) for slot in ("melee", "ranged") if gear.get(slot)]
    if gear.get("offhand"):
        lengths.append(size * 0.9)
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


def _weapon_parts(kind: str, length: float) -> list:
    """Primitives making up a weapon, in weapon-local space: grip at (0, 0), tip toward -y.

    Each part is (kind, geometry, style) where style picks the colour: "metal" takes the
    item colour with a rarity-coloured border, "grip" and "string" are fixed.
    """
    L = length
    if kind == "bow":
        tips = ((-L * 0.4, -L * 0.3), (L * 0.4, -L * 0.3))
        stave = _bezier(tips[0], (0, -L * 1.45), tips[1])
        return [
            ("lines", tips, "string"),
            ("lines", stave, "metal"),
        ]
    if kind == "staff":
        return [
            ("lines", ((0, L * 0.12), (0, -L * 0.86)), "grip"),
            ("circle", ((0, -L * 0.9), L * 0.14), "metal"),
        ]
    if kind == "spear":
        return [
            ("lines", ((0, L * 0.1), (0, -L * 0.82)), "grip"),
            ("poly", [(-L * 0.1, -L * 0.78), (0, -L), (L * 0.1, -L * 0.78)], "metal"),
        ]
    if kind == "hammer":
        return [
            ("lines", ((0, L * 0.08), (0, -L * 0.72)), "grip"),
            (
                "poly",
                [(-L * 0.3, -L * 0.68), (L * 0.3, -L * 0.68), (L * 0.3, -L * 0.98), (-L * 0.3, -L * 0.98)],
                "metal",
            ),
        ]
    if kind == "axe":
        return [
            ("lines", ((0, L * 0.08), (0, -L * 0.96)), "grip"),
            (
                "poly",
                [(L * 0.04, -L * 0.96), (L * 0.5, -L * 0.82), (L * 0.5, -L * 0.54), (L * 0.04, -L * 0.6)],
                "metal",
            ),
        ]
    if kind == "dagger":
        return [
            ("lines", ((0, L * 0.08), (0, -L * 0.28)), "grip"),
            (
                "poly",
                [(-L * 0.14, -L * 0.26), (L * 0.14, -L * 0.26), (L * 0.14, -L * 0.34), (-L * 0.14, -L * 0.34)],
                "metal",
            ),
            (
                "poly",
                [
                    (-L * 0.09, -L * 0.34),
                    (L * 0.09, -L * 0.34),
                    (L * 0.09, -L * 0.84),
                    (0, -L),
                    (-L * 0.09, -L * 0.84),
                ],
                "metal",
            ),
        ]
    # sword, and any weapon whose archetype falls back to one
    return [
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
    ]


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
            pygame.draw.polygon(surface, color, points)
            pygame.draw.polygon(surface, outline, points, 2)
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


def draw_shield(surface, hand_pos, body_center, spec: dict, size: int):
    """Draw the offhand shield: carried out at the arm's side while it's down, swung
    across the front of the body while it's raised, which is how the player reads that
    the block is actually up."""
    raised = spec.get("raised")
    width, height = size * 0.62, size * 0.78
    if raised:
        cx = (hand_pos[0] + body_center[0]) / 2
        cy = body_center[1] - size * 0.5
    else:
        cx, cy = hand_pos[0], hand_pos[1] + size * 0.1
        width, height = width * 0.85, height * 0.85

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
