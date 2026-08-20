"""The vector art behind every hostile creature, one function per silhouette.

A monster used to be a coloured circle with two smaller circles for arms, which meant a
slime, a skeleton and an ogre differed only in radius and hue. Here each kind gets a shape
its name can be read from, picked by `MonsterKind.shape`, exactly the way `CritterKind.shape`
decides whether an animal is drawn as a blob or as a standing quadruped.

Everything is drawn in the creature's own unrotated space, body centred and forward pointing
at -y, onto a square surface the caller then rotates: the same convention `gear.py` uses, so
a held weapon turns with the facing and swings with the arm for free.

Kept apart from `monsters.py` for the reason `item_icons.py` is kept apart from `items.py`:
a search for what a monster *does* should never land in a hundred lines of polygon coordinates.
"""

from __future__ import annotations

import math

import pygame

import core.constants as c
from game.entities.gear import draw_weapon, weapon_length

# Near-black used for every outline, so a silhouette holds together against grass, floorboards
# or a night tint alike.
OUTLINE = (18, 16, 18)
BONE = (226, 222, 208)

# A two-handed shooting weapon is carried in the left hand, everything else in the right, the
# same split the player's ranged and melee slots use.
_LEFT_HAND_WEAPONS = ("bow", "staff")


def weapon_hand(weapon: str) -> str:
    """Which arm holds this weapon, and therefore which one the swing animation must use:
    a monster that swings its empty hand while the axe hangs off the other one reads as broken."""
    return "left" if weapon in _LEFT_HAND_WEAPONS else "right"


def _shade(color, amount=55):
    return tuple(max(0, v - amount) for v in color[:3])


def _light(color, amount=40):
    return tuple(min(255, v + amount) for v in color[:3])


def _local(center, s):
    """Point at (forward, side) in the creature's own space, in surface coordinates. Both are
    multiples of the body size, forward is toward the facing."""
    cx, cy = center

    def at(forward, side):
        return (cx + side * s, cy - forward * s)

    return at


def _oval(center, width, height):
    rect = pygame.Rect(0, 0, max(2, round(width)), max(2, round(height)))
    rect.center = (round(center[0]), round(center[1]))
    return rect


def _circle(surface, color, pos, radius, width=0):
    pygame.draw.circle(surface, color, (round(pos[0]), round(pos[1])), max(1, round(radius)), width)


def _poly(surface, color, points, outline=OUTLINE, border=2):
    pygame.draw.polygon(surface, color, points)
    if border:
        pygame.draw.polygon(surface, outline, points, border)


def draw_monster(
    surface: pygame.Surface,
    x: int,
    y: int,
    size: int,
    color: tuple,
    angle: float,
    shape: str = "humanoid",
    *,
    attack_progress: float = 0.0,
    attack_hand: str | None = None,
    weapon: str = "",
    eye_color: tuple = (255, 120, 60),
    aggro: bool = False,
    phase: float = 0.0,
    nock: float = 0.0,
    walk: float = 0.0,
):
    """Draw one creature: its ground shadow, its silhouette, whatever it is holding and its eyes.

    `phase` offsets the idle breath so a pack does not pulse in unison, `aggro` is whether it
    has noticed the player (its eyes flare, the one warning it gives before it arrives), and
    `nock` is how close a bow is to loosing, drawn as the arrow being drawn back, and `walk`
    is how far through its stride it is (game/entities/entities.py `Gait`): the body rocks and
    lifts with it. Like the shadow, the breath and the eyes, the walk sits above the
    silhouette and is the same for every kind, because a thing that slides across the ground
    reads as wrong whatever shape it is."""
    breath = math.sin(pygame.time.get_ticks() / c.MonsterArt.BREATH_PERIOD_MS * math.tau + phase * math.tau)

    _draw_shadow(surface, x, y, size)

    # Room for the body plus whatever sticks out of the hand holding a weapon.
    span = int(size * 1.5 + (weapon_length(weapon, size) if weapon else 0.0)) + 10
    sprite = pygame.Surface((span * 2, span * 2), pygame.SRCALPHA)
    center = (span, span)

    def hand(hx, hy, which):
        """A hand at rest, or thrown forward and inward while that arm is mid-swing."""
        if which != attack_hand or attack_progress <= 0.0:
            return hx, hy
        reach = size * 0.45 * math.sin(attack_progress * math.pi)
        return (hx + reach if which == "left" else hx - reach, hy - reach)

    parts = _SHAPES.get(shape, _draw_humanoid)(sprite, center, size, color, breath, hand)

    held = parts.get("hands", {}).get(weapon_hand(weapon)) if weapon else None
    if held:
        # A monster's steel is rusted and plain; only a staff's head takes the creature's own
        # colour, since the light in it is the same light in its eyes.
        spec = {
            "kind": weapon,
            "color": eye_color if weapon == "staff" else c.MonsterArt.WEAPON_COLOR,
            "outline": c.MonsterArt.WEAPON_OUTLINE,
        }
        swinging = attack_progress if attack_hand == weapon_hand(weapon) else 0.0
        draw_weapon(sprite, held, spec, size, weapon_hand(weapon), swinging)
        if weapon == "bow" and nock > 0.0:
            _draw_nocked_arrow(sprite, held, size, nock)

    _draw_eyes(sprite, parts.get("eyes", ()), size * c.MonsterArt.EYE_RADIUS, eye_color, aggro)

    # The body rocks from side to side as it walks and lifts off the ground at each step.
    # The shadow was laid down before this and stays where it is, which is what sells it.
    lean = math.radians(c.Entities.GAIT_LEAN_DEG) * walk
    if angle or lean:
        sprite = pygame.transform.rotate(sprite, math.degrees(-(angle + lean)))
    surface.blit(sprite, sprite.get_rect(center=(x, y - walk * walk * c.Entities.GAIT_BOB)))


def _draw_shadow(surface, x, y, size):
    """The pool under the body. Without it every creature hovers a little above the ground."""
    width = max(4, round(size * c.MonsterArt.SHADOW_WIDTH))
    height = max(3, round(size * c.MonsterArt.SHADOW_HEIGHT))
    shadow = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow, (0, 0, 0, c.MonsterArt.SHADOW_ALPHA), shadow.get_rect())
    surface.blit(shadow, (round(x - width / 2), round(y - height / 2 + size * c.MonsterArt.SHADOW_OFFSET)))


def _draw_eyes(sprite, eyes, radius, color, aggro):
    """Two lit points on the front of the head, over a soft glow. This is what turns a shape
    into something looking back, and it doubles as a readout of which way it is facing."""
    if not eyes:
        return
    radius = max(2.0, radius * (c.MonsterArt.AGGRO_EYE_MULT if aggro else 1.0))
    glow_radius = max(2, round(radius * c.MonsterArt.EYE_GLOW_MULT))
    alpha = c.MonsterArt.AGGRO_GLOW_ALPHA if aggro else c.MonsterArt.EYE_GLOW_ALPHA
    glow = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
    pygame.draw.circle(glow, (*color, alpha), (glow_radius, glow_radius), glow_radius)
    for pos in eyes:
        sprite.blit(glow, (round(pos[0] - glow_radius), round(pos[1] - glow_radius)))
        _circle(sprite, color, pos, radius)
        _circle(sprite, _light(color, 70), pos, max(1.0, radius * 0.4))


def _draw_nocked_arrow(sprite, hand_pos, size, nock):
    """The arrow on the string, sliding back as the shot comes due. A ranged monster that
    shoots out of a still pose gives the player nothing to react to."""
    length = weapon_length("bow", size)
    pull = length * 0.3 * nock
    hx, hy = hand_pos
    tail = (hx, hy + length * 0.1 + pull)
    tip = (hx, hy - length * 0.72 + pull)
    pygame.draw.line(sprite, (96, 74, 52), tail, tip, 2)
    pygame.draw.polygon(sprite, BONE, [(tip[0] - 3, tip[1] + 7), (tip[0] + 3, tip[1] + 7), tip])


# --------------------------------------------------------------------------- silhouettes
# Each takes the sprite surface, the body centre, the base size, the creature's colour, the
# current breath (-1..1) and the `hand` placement helper, and returns the anchors the shared
# code needs back: where the hands ended up (for a weapon) and where the eyes go.


def _breathed(size, breath):
    return size * (1 + c.MonsterArt.BREATH_AMOUNT * breath)


def _draw_humanoid(sprite, center, size, color, breath, hand):
    """A cloaked, hooded raider: the archer and the bandit. Human enough to be read as a
    person who chose this, which is a different kind of unpleasant from a beast."""
    s = _breathed(size, breath)
    at = _local(center, s)
    shade = _shade(color, 45)

    _poly(sprite, shade, [at(0.06, -0.38), at(0.06, 0.38), at(-0.36, 0.44), at(-0.78, 0.0), at(-0.36, -0.44)])

    body = _oval(at(0.0, 0.0), s * 0.82, s * 0.9)
    pygame.draw.ellipse(sprite, color, body)
    pygame.draw.ellipse(sprite, OUTLINE, body, 2)

    hands = {"left": hand(*at(0.02, -0.5), "left"), "right": hand(*at(0.02, 0.5), "right")}
    for pos in hands.values():
        _circle(sprite, OUTLINE, pos, s * 0.2)
        _circle(sprite, shade, pos, s * 0.2 - 2)

    _poly(sprite, shade, [at(0.1, -0.34), at(0.62, 0.0), at(0.1, 0.34)])
    _poly(sprite, OUTLINE, [at(0.18, -0.2), at(0.44, 0.0), at(0.18, 0.2)], border=0)

    return {"hands": hands, "eyes": (at(0.3, -0.1), at(0.3, 0.1))}


def _draw_goblin(sprite, center, size, color, breath, hand):
    """Small, hunched and all ears, with a cleaver too big for it. The point of a goblin is
    that one is a nuisance and four are a problem, so it has to be recognisable in a crowd."""
    s = _breathed(size, breath)
    at = _local(center, s)
    shade, light = _shade(color, 50), _light(color, 25)

    for side in (-1, 1):
        _poly(sprite, light, [at(0.14, side * 0.2), at(0.02, side * 0.74), at(-0.16, side * 0.28)])

    body = _oval(at(-0.05, 0.0), s * 0.72, s * 0.76)
    pygame.draw.ellipse(sprite, color, body)
    pygame.draw.ellipse(sprite, OUTLINE, body, 2)

    hands = {"left": hand(*at(0.06, -0.42), "left"), "right": hand(*at(0.06, 0.42), "right")}
    for pos in hands.values():
        _circle(sprite, OUTLINE, pos, s * 0.16)
        _circle(sprite, shade, pos, s * 0.16 - 2)

    _circle(sprite, OUTLINE, at(0.3, 0.0), s * 0.27)
    _circle(sprite, light, at(0.3, 0.0), s * 0.27 - 2)
    _circle(sprite, shade, at(0.48, 0.0), s * 0.12)  # snout

    return {"hands": hands, "eyes": (at(0.34, -0.1), at(0.34, 0.1))}


def _draw_hulk(sprite, center, size, color, breath, hand):
    """Shoulders wider than it is long, a head sunk between them and arms that hang past the
    body: the troll, the ogre and the two heavy boss archetypes. Reads as mass before anything else."""
    s = _breathed(size, breath)
    at = _local(center, s)
    shade = _shade(color, 55)

    # One slab of a body, broad at the shoulders and tapering to the hips, rather than a
    # cluster of circles: the mass has to read as a single animal from a screen away.
    _poly(sprite, color, [at(0.36, -0.52), at(0.36, 0.52), at(-0.46, 0.4), at(-0.6, 0.0), at(-0.46, -0.4)])
    pygame.draw.ellipse(sprite, _light(color, 18), _oval(at(-0.1, 0.0), s * 0.5, s * 0.66))  # hunched back

    hands = {"left": hand(*at(0.52, -0.42), "left"), "right": hand(*at(0.52, 0.42), "right")}
    for side, key in ((-1, "left"), (1, "right")):
        shoulder = at(0.24, side * 0.46)
        pygame.draw.line(sprite, OUTLINE, shoulder, hands[key], max(5, round(s * 0.26)))
        pygame.draw.line(sprite, shade, shoulder, hands[key], max(3, round(s * 0.26) - 4))
        _circle(sprite, OUTLINE, hands[key], s * 0.16)
        _circle(sprite, shade, hands[key], s * 0.16 - 2)

    _circle(sprite, OUTLINE, at(0.5, 0.0), s * 0.23)
    _circle(sprite, shade, at(0.5, 0.0), s * 0.23 - 2)
    for side in (-1, 1):  # tusks pushing up out of the jaw
        pygame.draw.line(sprite, BONE, at(0.56, side * 0.08), at(0.72, side * 0.16), 3)

    return {"hands": hands, "eyes": (at(0.54, -0.08), at(0.54, 0.08))}


def _draw_skeleton(sprite, center, size, color, breath, hand):
    """Ribs over a hollow chest and a skull with lit sockets. Nothing here is a filled body:
    what makes a skeleton is the gaps, so the torso is drawn as the dark between the bones."""
    s = _breathed(size, breath)
    at = _local(center, s)
    bone = color
    cavity = (34, 31, 30)

    chest = _oval(at(-0.05, 0.0), s * 0.72, s * 0.86)
    pygame.draw.ellipse(sprite, cavity, chest)
    pygame.draw.ellipse(sprite, OUTLINE, chest, 2)

    pygame.draw.line(sprite, bone, at(0.28, 0.0), at(-0.4, 0.0), 3)  # spine
    for forward, width in ((0.16, 0.3), (0.0, 0.32), (-0.16, 0.26)):
        pygame.draw.line(sprite, bone, at(forward, -width), at(forward, width), 3)

    hands = {"left": hand(*at(0.02, -0.5), "left"), "right": hand(*at(0.02, 0.5), "right")}
    for side, key in ((-1, "left"), (1, "right")):
        pygame.draw.line(sprite, bone, at(0.1, side * 0.3), hands[key], 3)
        _circle(sprite, bone, hands[key], s * 0.11)

    _circle(sprite, OUTLINE, at(0.44, 0.0), s * 0.26)
    _circle(sprite, bone, at(0.44, 0.0), s * 0.26 - 2)
    pygame.draw.line(sprite, _shade(bone, 90), at(0.34, -0.14), at(0.34, 0.14), 2)  # jaw
    for side in (-1, 1):
        _circle(sprite, (20, 18, 20), at(0.48, side * 0.1), s * 0.09)

    return {"hands": hands, "eyes": (at(0.48, -0.1), at(0.48, 0.1))}


def _draw_wraith(sprite, center, size, color, breath, hand):
    """No legs and no edges: a hooded core over tatters that thin out behind it, drifting
    between two alphas as it breathes. The only creature in the world you can see through."""
    s = size
    at = _local(center, s)
    faint, solid = c.MonsterArt.WRAITH_ALPHA_MIN, c.MonsterArt.WRAITH_ALPHA_MAX
    alpha = round(faint + (breath + 1) / 2 * (solid - faint))

    for side in (-0.3, -0.1, 0.1, 0.3):
        tatter = [at(-0.15, side - 0.13), at(-0.15, side + 0.13), at(-0.62 - abs(side) * 0.4, side * 1.5)]
        pygame.draw.polygon(sprite, (*_shade(color, 40), max(30, alpha // 2)), tatter)

    core = _oval(at(0.05, 0.0), s * 0.78, s * 0.9)
    pygame.draw.ellipse(sprite, (*color, alpha), core)

    hands = {"left": at(0.05, -0.44), "right": at(0.05, 0.44)}
    for pos in hands.values():
        _circle(sprite, (*_light(color, 20), max(40, alpha - 40)), pos, s * 0.15)

    hood = [at(0.14, -0.3), at(0.56, 0.0), at(0.14, 0.3)]
    pygame.draw.polygon(sprite, (*_shade(color, 80), min(255, alpha + 40)), hood)
    pygame.draw.polygon(sprite, (12, 10, 16, 230), [at(0.2, -0.19), at(0.42, 0.0), at(0.2, 0.19)])

    return {"hands": hands, "eyes": (at(0.3, -0.1), at(0.3, 0.1))}


def _draw_blob(sprite, center, size, color, breath, hand):
    """The slime: a translucent mass that squashes and stretches instead of breathing, with a
    dark nucleus suspended in it and a couple of drips sliding off the back."""
    at = _local(center, size)
    squash = c.MonsterArt.BREATH_AMOUNT * 2 * breath

    for offset, radius in ((-0.55, 0.13), (-0.42, 0.09)):
        _circle(sprite, (*_shade(color, 30), 170), at(offset, offset * 0.4), size * radius)

    body = _oval(at(0.0, 0.0), size * (1 + squash), size * (1 - squash))
    pygame.draw.ellipse(sprite, (*_light(color, 15), 205), body)
    pygame.draw.ellipse(sprite, (*_shade(color, 70), 230), body, 2)

    pygame.draw.ellipse(sprite, (*_light(color, 90), 120), _oval(at(0.2, -0.22), size * 0.3, size * 0.2))
    _circle(sprite, (*_shade(color, 95), 220), at(-0.08, 0.0), size * 0.17)

    return {"eyes": (at(0.16, -0.17), at(0.16, 0.17))}


def _draw_beast(sprite, center, size, color, breath, hand):
    """The wolf: a standing quadruped with its hackles up. Drawn a little under its own size
    because it runs long rather than wide, the same reason wildlife has its own hit radius."""
    s = _breathed(size, breath) * 0.82
    at = _local(center, s)
    shade = _shade(color, 45)

    for forward, splay in ((0.36, 0.56), (-0.42, -0.62)):
        for side in (-1, 1):
            pygame.draw.line(sprite, shade, at(forward, side * 0.24), at(splay, side * 0.56), 5)

    # Wide at the shoulders, pinched at the waist: without the taper a quadruped seen from
    # above is a rounded rectangle, which reads as a beetle rather than as something hunting.
    flank = [
        at(0.5, -0.34),
        at(0.5, 0.34),
        at(0.14, 0.28),
        at(-0.22, 0.34),
        at(-0.56, 0.26),
        at(-0.72, 0.0),
        at(-0.56, -0.26),
        at(-0.22, -0.34),
        at(0.14, -0.28),
    ]
    _poly(sprite, color, flank)

    for forward in (0.3, 0.08, -0.16):  # hackles raised in a line down the spine
        _poly(sprite, _shade(color, 25), [at(forward, -0.08), at(forward + 0.11, 0.0), at(forward, 0.08)], border=0)

    pygame.draw.line(sprite, color, at(0.42, 0.0), at(0.86, 0.0), max(4, round(s * 0.26)))
    _circle(sprite, OUTLINE, at(0.94, 0.0), s * 0.27)
    _circle(sprite, color, at(0.94, 0.0), s * 0.27 - 2)
    _circle(sprite, shade, at(1.16, 0.0), s * 0.14)  # muzzle
    for side in (-1, 1):
        _poly(sprite, shade, [at(0.98, side * 0.16), at(1.16, side * 0.34), at(0.88, side * 0.3)], border=0)  # ears
        pygame.draw.line(sprite, BONE, at(1.2, side * 0.07), at(1.34, side * 0.13), 2)  # fangs
    pygame.draw.line(sprite, color, at(-0.72, 0.0), at(-1.02, 0.18), 4)  # tail

    return {"eyes": (at(1.02, -0.11), at(1.02, 0.11))}


def _draw_robed(sprite, center, size, color, breath, hand):
    """The hexer and the warlock boss: a robe flaring behind, sleeves instead of arms and a
    pointed hood with nothing under it but the light of whatever it is casting."""
    s = _breathed(size, breath)
    at = _local(center, s)
    shade = _shade(color, 60)

    _poly(sprite, color, [at(0.3, -0.3), at(0.3, 0.3), at(-0.5, 0.62), at(-0.66, 0.0), at(-0.5, -0.62)])
    pygame.draw.line(sprite, shade, at(-0.48, -0.58), at(-0.48, 0.58), 3)  # hem

    hands = {"left": hand(*at(0.0, -0.46), "left"), "right": hand(*at(0.0, 0.46), "right")}
    for pos in hands.values():
        _circle(sprite, OUTLINE, pos, s * 0.18)
        _circle(sprite, shade, pos, s * 0.18 - 2)

    _poly(sprite, shade, [at(0.2, -0.32), at(0.72, 0.0), at(0.2, 0.32)])
    _poly(sprite, OUTLINE, [at(0.26, -0.2), at(0.54, 0.0), at(0.26, 0.2)], border=0)

    return {"hands": hands, "eyes": (at(0.38, -0.1), at(0.38, 0.1))}


def _draw_creeper(sprite, center, size, color, breath, hand):
    """The creeper: a swollen sack of powder on four stubby legs, cracked open along the
    seams by the light of what is inside it. It carries nothing and it never swings, so the
    silhouette has to say "this is about to go off" on its own: bloated where everything else
    in the world is lean, and split by glowing fissures that read from across a clearing."""
    s = _breathed(size, breath) * 0.92
    at = _local(center, s)
    shade, light = _shade(color, 60), _light(color, 70)

    for forward, splay in ((0.3, 0.78), (-0.32, 0.86)):
        for side in (-1, 1):
            pygame.draw.line(sprite, shade, at(forward, side * 0.36), at(forward - 0.08, side * splay), 6)

    # Narrow at the head, bulging at the belly and tapering to a heavy rear: a sack that is
    # too full, rather than the near-circle a symmetrical body draws.
    _poly(
        sprite,
        color,
        [
            at(0.6, -0.2),
            at(0.6, 0.2),
            at(0.28, 0.46),
            at(-0.16, 0.6),
            at(-0.58, 0.36),
            at(-0.78, 0.0),
            at(-0.58, -0.36),
            at(-0.16, -0.6),
            at(0.28, -0.46),
        ],
    )

    # The fissures: the powder showing through, wider and brighter toward the full rear.
    for forward, spread in ((0.2, 0.28), (-0.1, 0.42), (-0.42, 0.3)):
        crack = [at(forward + 0.08, -spread), at(forward - 0.05, -spread * 0.3), at(forward + 0.05, spread * 0.3)]
        crack.append(at(forward - 0.08, spread))
        pygame.draw.lines(sprite, shade, False, crack, 5)
        pygame.draw.lines(sprite, light, False, crack, 2)

    _circle(sprite, OUTLINE, at(0.66, 0.0), s * 0.28)
    _circle(sprite, shade, at(0.66, 0.0), s * 0.28 - 2)

    return {"eyes": (at(0.72, -0.12), at(0.72, 0.12))}


_SHAPES = {
    "humanoid": _draw_humanoid,
    "goblin": _draw_goblin,
    "hulk": _draw_hulk,
    "skeleton": _draw_skeleton,
    "wraith": _draw_wraith,
    "blob": _draw_blob,
    "beast": _draw_beast,
    "robed": _draw_robed,
    "creeper": _draw_creeper,
}
