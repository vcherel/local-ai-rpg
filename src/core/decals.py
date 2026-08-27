"""Ground decals: blood splats left behind by hits and kills, and the prints tracked out
of them.

One global, session-only system, the same pattern as ParticleSystem: it draws during
both outdoor and interior rendering, so a splat left mid-fight in a room is still
there if the player steps out and back in. Capped so a long fight can't grow the
list forever.

Each splat is painted into its own little surface once at spawn and then blitted, so a
smear can be stretched and turned along the blow that made it without costing a rotate
per frame. The shape is a torn polygon rather than an ellipse: blood does not land in
circles, and the difference between a splat and a sticker is the edge.

What a wound looks like is the weapon's business, so the recipes live in `_SPLAT_STYLES`
below, one row per weapon family: a dagger leaves specks, a sword a wide smear, a spear a
narrow throw, a hammer a burst. A kill takes the same row and doubles down on it.

Blood on the ground is also something to stand in: every splat marks its cell as wet for
a few seconds (`_wet`), and anything walking through a wet cell picks it up and prints it
out again step by step until the soles run dry.
"""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c

# One row per weapon family, naming what its wounds look like. Multipliers on the base
# splash, so tuning the whole system stays a matter of the constants and tuning one
# weapon stays a matter of its row.
_SPLAT_STYLES = {
    # A quick blade barely opens anything: a few specks close to the body.
    "light": {"pool": 0.55, "count": 0.6, "spread": 70.0, "distance": 0.7, "drop": 0.7, "arcs": 0, "stretch": 0.9},
    # A swung edge throws a wide arc of it sideways.
    "slash": {"pool": 1.0, "count": 1.25, "spread": 160.0, "distance": 1.1, "drop": 1.0, "arcs": 1, "stretch": 1.7},
    # A thrust puts a narrow jet out the far side.
    "pierce": {"pool": 0.8, "count": 0.85, "spread": 32.0, "distance": 1.7, "drop": 0.85, "arcs": 1, "stretch": 2.4},
    # A heavy head bursts rather than cuts: short, fat, and all over the ground it stood on.
    "heavy": {"pool": 1.4, "count": 1.5, "spread": 130.0, "distance": 0.9, "drop": 1.45, "arcs": 1, "stretch": 1.1},
    # Something arriving at speed from a distance: a cone of fine spatter carrying on past.
    "shot": {"pool": 0.6, "count": 0.75, "spread": 48.0, "distance": 1.3, "drop": 0.65, "arcs": 0, "stretch": 1.6},
    # Anything with no weapon behind it: a fall, a burn tick, a trap, a monster's own bite.
    "generic": {"pool": 1.0, "count": 1.0, "spread": 110.0, "distance": 1.0, "drop": 1.0, "arcs": 0, "stretch": 1.2},
}

# Which family swings like what. Keyed by `WeaponArchetype.name`, so a new weapon family
# is a row here rather than a branch at the call site.
_STYLE_BY_WEAPON = {
    "dagger": "light",
    "tool": "light",
    "unarmed": "light",
    "sword": "slash",
    "axe": "slash",
    "pole": "slash",
    "hammer": "heavy",
    "spear": "pierce",
    "bow": "shot",
    "crossbow": "shot",
    "staff": "shot",
}


def style_for_weapon(arch) -> str:
    """The splat recipe a weapon archetype bleeds by. Unknown families bleed generically."""
    if arch is None:
        return "generic"
    return _STYLE_BY_WEAPON.get(getattr(arch, "name", ""), "generic")


class Decal:
    __slots__ = ("alpha", "angle", "life", "max_life", "surface", "x", "y")

    def __init__(self, x, y, radius, color, life, stretch: float = 1.0, angle: float = 0.0, shape: str = "splat"):
        self.x = x
        self.y = y
        self.life = life
        self.max_life = life
        self.angle = angle
        # What `set_alpha` was last given. Setting it costs as much as the blit does and a
        # splat only changes opacity while it is drying out, so it is set when it moves.
        self.alpha = -1
        painter = _print_surface if shape == "print" else _splat_surface
        self.surface = painter(radius, color, stretch, angle)


def _torn_blob(surface, cx, cy, rx, ry, color):
    """One lobe of a splat: a ring of points at a jittered radius, so the outline comes out
    torn instead of drawn with a compass."""
    steps = random.randint(9, 13)
    points = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        jitter = random.uniform(1.0 - c.Decals.RAGGED, 1.0 + c.Decals.RAGGED)
        points.append((cx + math.cos(a) * rx * jitter, cy + math.sin(a) * ry * jitter))
    pygame.draw.polygon(surface, color, points)


def _splat_surface(radius, color, stretch, angle) -> pygame.Surface:
    """A few overlapping torn lobes plus the drops thrown off them, drawn once. `stretch`
    pulls the whole thing along the blow's direction, which is what turns a splat into a
    smear."""
    radius = max(1.0, radius)
    long_r = radius * stretch
    pad = round(radius * 0.9) + 4
    size = (round(long_r * 2 + pad * 2), round(radius * 2 + pad * 2))
    surface = pygame.Surface(size, pygame.SRCALPHA)
    cx, cy = size[0] / 2, size[1] / 2

    for _ in range(random.randint(3, 5)):
        r = random.uniform(radius * 0.45, radius)
        # Along the smear, not around it: offsets scale with the stretch so the extra
        # length is filled in rather than leaving one blob at each end.
        ox = random.uniform(-long_r * 0.5, long_r * 0.5)
        oy = random.uniform(-radius * 0.45, radius * 0.45)
        tint = tuple(max(0, min(255, v + random.randint(-16, 16))) for v in color)
        _torn_blob(surface, cx + ox, cy + oy, r * max(1.0, stretch * 0.7), r, tint)

    # The thin tail a thrown droplet leaves behind it, only worth drawing on a smear.
    if stretch > 1.4:
        _torn_blob(surface, cx, cy, long_r * 0.9, max(1.0, radius * 0.28), color)

    # The drops that came off the edges. A splat with nothing around it reads as a shape
    # somebody placed; these are what make it look thrown.
    for _ in range(random.randint(2, 5)):
        dx = random.uniform(-long_r, long_r)
        dy = random.uniform(-radius, radius) * 1.25
        drop = max(1.0, radius * random.uniform(0.10, 0.26))
        _torn_blob(surface, cx + dx, cy + dy, drop, drop, color)

    if angle:
        surface = pygame.transform.rotate(surface, -math.degrees(angle))
    return surface


def _print_surface(radius, color, _stretch, angle) -> pygame.Surface:
    """One bloody footprint: a sole and the toes in front of it, pointing the way it walked."""
    radius = max(2.0, radius)
    long_r = radius * 1.6
    pad = 4
    size = (round(long_r * 2 + pad * 2), round(radius * 2 + pad * 2))
    surface = pygame.Surface(size, pygame.SRCALPHA)
    cx, cy = size[0] / 2, size[1] / 2
    _torn_blob(surface, cx - long_r * 0.25, cy, long_r * 0.7, radius * 0.75, color)
    for step in (-1, 0, 1):
        _torn_blob(surface, cx + long_r * 0.6, cy + step * radius * 0.45, radius * 0.22, radius * 0.22, color)
    if angle:
        surface = pygame.transform.rotate(surface, -math.degrees(angle))
    return surface


class DecalSystem:
    def __init__(self):
        self.decals: list[Decal] = []
        # Which ground is still wet enough to be trodden in, as cell -> when it dries.
        # A grid rather than a search through the splats: this is asked of every walker
        # every frame, and the answer is only ever "is there blood right here".
        self._wet: dict[tuple[int, int], float] = {}
        # Per walker, how much blood is on the soles and where the last print went down.
        self._soles: dict = {}
        self._prints: dict = {}
        self._sides: dict = {}

    # ------------------------------------------------------------------ splats

    def spawn(self, x, y, radius=10, color=(130, 18, 18), life=None, stretch=1.0, angle=0.0, shape="splat"):
        self.decals.append(Decal(x, y, radius, color, life or c.Decals.LIFE_MS, stretch, angle, shape))
        if len(self.decals) > c.Decals.MAX_COUNT:
            self.decals.pop(0)
        if shape == "splat" and radius >= c.Decals.WET_MIN_RADIUS:
            self._wet[self._cell(x, y)] = pygame.time.get_ticks() + c.Decals.WET_MS

    def splash(self, x, y, style="generic", direction=None, fatal=False, boss=False, color=None):
        """The whole picture of one wound: the pool where it landed, the fan thrown along the
        blow, and, on a kill, the long arterial throws over the top of both.

        `style` is the weapon family's row in `_SPLAT_STYLES`; `direction` the blow's
        (dx, dy) unit vector, so the mess points away from the attacker instead of ringing
        the body. A kill takes the same recipe several times over, because the difference
        between a hit and a kill is meant to be legible from across the clearing."""
        recipe = _SPLAT_STYLES.get(style, _SPLAT_STYLES["generic"])
        color = color or c.Decals.BLOOD_COLOR
        scale = c.Decals.BOSS_SCALE if boss else (c.Decals.KILL_SCALE if fatal else 1.0)
        pool = (c.Decals.KILL_RADIUS if fatal else c.Decals.HIT_RADIUS) * recipe["pool"] * (1.5 if boss else 1.0)

        self.spawn(x, y, radius=pool, color=color, stretch=1.0 + (recipe["stretch"] - 1.0) * 0.4)
        near, far = c.Decals.SPRAY_DISTANCE
        small, big = c.Decals.SPRAY_RADIUS
        self.spawn_spray(
            x,
            y,
            direction,
            count=max(2, round(c.Decals.SPRAY_COUNT * recipe["count"] * scale)),
            distance=(near * recipe["distance"], far * recipe["distance"] * scale),
            radius=(small * recipe["drop"], big * recipe["drop"] * (1.3 if fatal else 1.0)),
            spread_deg=recipe["spread"],
            stretch=recipe["stretch"],
            color=color,
        )
        if not fatal:
            return
        arcs = (c.Decals.BOSS_ARCS if boss else c.Decals.KILL_ARCS) + recipe["arcs"]
        length = c.Decals.BOSS_ARC_LENGTH if boss else c.Decals.ARC_LENGTH
        self.spawn_arcs(x, y, direction, count=arcs, length=length, color=color)

    def spawn_spray(
        self,
        x,
        y,
        direction=None,
        count=8,
        distance=(16.0, 105.0),
        radius=(3.0, 9.0),
        color=None,
        spread_deg=None,
        stretch=1.0,
    ):
        """A fan of droplets flung out from a wound, thinning out with distance.

        `direction` is the blow's (dx, dy) unit vector: the spray goes that way, away from
        the attacker, so a death reads as directional. Without one (a burn tick, an execute)
        it sprays all round instead. Droplets land farther out but smaller, the way a real
        splatter falls off, and the ones thrown hardest land as smears pointing the way they
        travelled rather than as tidy dots.
        """
        base = math.atan2(direction[1], direction[0]) if direction else 0.0
        spread = math.radians(spread_deg if spread_deg is not None else c.Decals.SPRAY_SPREAD_DEG)
        if not direction:
            spread = 2 * math.pi
        near, far = distance
        small, big = radius
        for _ in range(count):
            angle = base + random.uniform(-spread / 2, spread / 2)
            # Squaring the roll clusters droplets near the body, with a few thrown wide.
            reach = random.random() ** 2
            dist = near + (far - near) * reach
            self.spawn(
                x + math.cos(angle) * dist,
                y + math.sin(angle) * dist,
                radius=big - (big - small) * reach,
                color=color or c.Decals.BLOOD_COLOR,
                stretch=1.0 + reach * c.Decals.SMEAR_STRETCH * stretch,
                angle=angle,
            )

    def spawn_arcs(self, x, y, direction=None, count=3, length=(70.0, 190.0), color=None):
        """The long throws: a handful of arterial streaks laid out from the body, each a
        line of shrinking drops rather than one shape, so it reads as blood travelling."""
        base = math.atan2(direction[1], direction[0]) if direction else random.uniform(0, 2 * math.pi)
        spread = math.radians(c.Decals.ARC_SPREAD_DEG)
        near, far = length
        for _ in range(count):
            angle = base + random.uniform(-spread / 2, spread / 2)
            reach = random.uniform(near, far)
            drops = max(3, round(reach / 24))
            for step in range(drops):
                t = (step + 1) / drops
                jitter = random.uniform(-9, 9)
                self.spawn(
                    x + math.cos(angle) * reach * t - math.sin(angle) * jitter,
                    y + math.sin(angle) * reach * t + math.cos(angle) * jitter,
                    radius=max(2.0, 8.0 * (1.0 - t * 0.65)),
                    color=color or c.Decals.BLOOD_COLOR,
                    stretch=1.7 + t,
                    angle=angle,
                )

    # ------------------------------------------------------------------ footprints

    @staticmethod
    def _cell(x, y) -> tuple[int, int]:
        size = c.Decals.WET_CELL
        return (int(x // size), int(y // size))

    def _standing_in_blood(self, x, y) -> bool:
        return self._wet.get(self._cell(x, y), 0.0) > pygame.time.get_ticks()

    def track_walkers(self, walkers):
        """Carry every body that can walk blood about one frame on.

        `walkers` is an iterable of (key, x, y): the player and whatever is near enough to
        be worth the bookkeeping. The three dicts are rebuilt from it each call, so a body
        that has died or streamed out takes its entry with it rather than leaking one.
        """
        soles, prints, sides = {}, {}, {}
        for key, x, y in walkers:
            charge = self._soles.get(key, 0.0)
            if self._standing_in_blood(x, y):
                charge = 1.0
            last = self._prints.get(key)
            side = self._sides.get(key, 1)
            if charge > 0.0 and last is not None:
                dx, dy = x - last[0], y - last[1]
                travelled = math.hypot(dx, dy)
                if travelled >= c.Decals.FOOT_STRIDE:
                    angle = math.atan2(dy, dx)
                    # Feet fall either side of the line walked, not down the middle of it.
                    offset = c.Decals.FOOT_OFFSET * side
                    self.spawn(
                        x - math.sin(angle) * offset,
                        y + math.cos(angle) * offset,
                        radius=c.Decals.FOOT_RADIUS * (0.55 + 0.45 * charge),
                        life=c.Decals.FOOT_LIFE_MS,
                        angle=angle,
                        shape="print",
                    )
                    side = -side
                    charge = max(0.0, charge - c.Decals.FOOT_FADE_PER_STEP)
                    last = (x, y)
            if last is None or math.hypot(x - last[0], y - last[1]) >= c.Decals.FOOT_STRIDE:
                last = (x, y)
            if charge > 0.0:
                soles[key] = charge
            prints[key] = last
            sides[key] = side
        self._soles, self._prints, self._sides = soles, prints, sides

    # ------------------------------------------------------------------ frame

    def update(self, dt):
        alive = []
        for d in self.decals:
            d.life -= dt
            if d.life > 0:
                alive.append(d)
        self.decals = alive
        if len(self._wet) > c.Decals.WET_MAX_CELLS:
            now = pygame.time.get_ticks()
            self._wet = {cell: dry for cell, dry in self._wet.items() if dry > now}

    def draw(self, surface, camera, hidden=None):
        """`hidden(x, y)` is the same rule entities and items are drawn by
        (GameRenderer._hidden_indoors): a splat on another building's floor is under a roof
        that is still on, so it must not be painted over the top of that roof."""
        for d in self.decals:
            if hidden is not None and hidden(d.x, d.y):
                continue
            screen_x, screen_y = camera.world_to_screen(d.x, d.y)
            rect = d.surface.get_rect(center=(round(screen_x), round(screen_y)))
            if not rect.colliderect(surface.get_rect()):
                continue
            fade_start = d.max_life * 0.25
            fade = min(1.0, d.life / fade_start) if d.life < fade_start else 1.0
            alpha = int(c.Decals.ALPHA * fade)
            if alpha != d.alpha:
                d.alpha = alpha
                d.surface.set_alpha(alpha)
            surface.blit(d.surface, rect)


_system = None


def get_decals() -> DecalSystem:
    global _system
    if _system is None:
        _system = DecalSystem()
    return _system
