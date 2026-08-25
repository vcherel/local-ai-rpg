from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.damage_fx import draw_cracks

if TYPE_CHECKING:
    from core.camera import Camera


class Scenery:
    """One piece of wilderness: a tree, a boulder, a tuft of grass, a pond, a stretch of
    road. Streamed with its chunk and thrown away with it, exactly like the floor details,
    so none of it is saved and nothing the player does can change it.

    Its whole shape is rolled once here, from its world position, and kept: the drawing
    code then only reads it back, so a copse holds still while the camera pans and costs
    nothing per frame beyond the circles it puts on the screen.
    """

    def __init__(
        self,
        x: float,
        y: float,
        kind: str,
        chunk: tuple[int, int],
        size: float = 0.0,
        biome: str = "plain",
        angle: float = 0.0,
    ):
        self.x = x
        self.y = y
        self.kind = kind
        # Only a bridge uses this: which way its deck lies, taken from the river it spans.
        self.angle = angle
        # Only the ground patches read this: everything else looks the same wherever it
        # grows, but the colour of the ground is the whole point of a biome.
        self.biome = biome
        # The chunk that generated this, not the one it happens to stand in: a cluster can
        # spill over a border, and it has to be unloaded by whoever made it.
        self.chunk = chunk
        self.size = size
        self.blocking_radius = c.Scenery.BLOCK_RADIUS.get(kind, 0)
        # How far this piece can stop something, which is not its blocking radius for a
        # bridge: a deck is walked over and only its two rails are solid, so the whole span
        # has to reach the collision index while nothing about its middle blocks.
        self.block_reach = self.blocking_radius
        self.ground = kind in c.Scenery.GROUND_KINDS
        self._shape = self._roll_shape()
        # How far this piece reaches, for the water and bridge lookups: nothing about water
        # blocks, so it needs a footprint of its own rather than borrowing blocking_radius.
        self.water_reach = self._water_reach()
        # A tree is the one piece of wilderness the player can argue with: it takes hits,
        # comes down, and leaves a stump standing where it was. `key` is what the world
        # remembers a felled one by (`World.felled`), filled in by whoever generated the
        # chunk; everything else here is None on anything that is not a tree.
        self.key = ""
        self.hp = c.Trees.HP if kind in c.Scenery.CANOPY_KINDS else 0
        self.felled = False
        self.fell_start_ms = None
        if kind == "bridge":
            self.block_reach = math.hypot(self.size, c.Scenery.BRIDGE_WIDTH + c.Scenery.BRIDGE_RAIL * 2) / 2

    def _water_reach(self) -> float:
        if self.kind in c.Scenery.WATER_KINDS:
            return self._shape.get("reach", self.size)
        if self.kind == "bridge":
            return max(self.size, c.Scenery.BRIDGE_WIDTH + c.Scenery.BRIDGE_RAIL * 2) / 2
        return 0.0

    def covers(self, x: float, y: float) -> bool:
        """Whether this piece of water (or bridge) has that point under it. A pond and a lake
        are ellipses, a river blob and a bridge deck are tested on their own axes; all three
        answer the one question `World.water_at` asks."""
        dx, dy = x - self.x, y - self.y
        if self.kind == "bridge":
            angle = self._shape["angle"]
            along = dx * math.cos(angle) + dy * math.sin(angle)
            across = -dx * math.sin(angle) + dy * math.cos(angle)
            # The rails count as deck: a body pressed against one is standing on the
            # crossing, not wading beside it.
            return abs(along) <= self.size / 2 and abs(across) <= c.Scenery.BRIDGE_WIDTH / 2 + c.Scenery.BRIDGE_RAIL
        if self.kind == "river":
            reach = self.size
            return dx * dx + dy * dy < reach * reach
        if self.kind not in ("pond", "lake"):
            return False
        # A pond is a clutch of overlapping ellipses rather than one: the shape that is
        # swum in has to be the shape that was drawn, so every lobe is asked.
        return any(((dx - ox) / rx) ** 2 + ((dy - oy) / ry) ** 2 < 1.0 for ox, oy, rx, ry in self._shape["lobes"])

    @property
    def canopy_radius(self) -> float:
        """How far the leaves of a tree reach, or 0 for anything that is not a canopy. The
        lobes are rolled out past the radius they were rolled from, so the margin is part
        of the answer rather than a fudge at the call site. A felled tree has no leaves
        left to reach anywhere."""
        if self.kind not in c.Scenery.CANOPY_KINDS or self.felled:
            return 0.0
        return self._shape["radius"] * c.Scenery.CANOPY_COVER_MARGIN

    @property
    def choppable(self) -> bool:
        return self.kind in c.Scenery.CANOPY_KINDS and not self.felled

    def fell(self):
        """Bring the tree down. What is left is a stump: nothing to walk around, nothing to
        hide under, and something still standing there so the wood reads as cut rather than
        as scenery that quietly vanished."""
        self.felled = True
        self.hp = 0
        self.fell_start_ms = pygame.time.get_ticks()
        self.blocking_radius = 0.0
        self.block_reach = 0.0

    def shades(self, x: float, y: float) -> bool:
        """Whether a body standing at (x, y) is under this canopy, and therefore whether the
        canopy has to fade to stay out of its way."""
        reach = self.canopy_radius
        if not reach:
            return False
        dx, dy = x - self.x, y - self.y
        return dx * dx + dy * dy < reach * reach

    def blocks(self, x: float, y: float, radius: float) -> bool:
        if self.kind == "bridge":
            return self._rail_blocks(x, y, radius)
        # Squared distance rather than hypot: this runs for every solid thing near every
        # entity's every step, and a wood holds a lot more of them than a village holds
        # buildings.
        if not self.blocking_radius:
            return False
        dx, dy = self.x - x, self.y - y
        reach = self.blocking_radius + radius
        return dx * dx + dy * dy < reach * reach

    def _rail_blocks(self, x: float, y: float, radius: float) -> bool:
        """Whether a body of `radius` is walking into one of a deck's rails. The deck itself
        is ordinary ground and its two ends are open: the only solid part of a bridge is the
        bar down either side, which is what keeps a crossing a crossing rather than a strip
        of floor over the water somebody can wander off."""
        angle = self._shape["angle"]
        dx, dy = x - self.x, y - self.y
        along = abs(dx * math.cos(angle) + dy * math.sin(angle))
        across = abs(-dx * math.sin(angle) + dy * math.cos(angle))
        rail = c.Scenery.BRIDGE_RAIL
        off_end = max(0.0, along - self.size / 2)
        off_rail = abs(across - (c.Scenery.BRIDGE_WIDTH + rail) / 2)
        return math.hypot(off_end, off_rail) < radius + rail / 2

    # ------------------------------------------------------------------ shape

    def _roll_shape(self) -> dict:
        rng = random.Random(f"{self.kind}:{round(self.x)},{round(self.y)}")
        if self.kind in ("tree", "pine"):
            return self._roll_canopy(rng)
        if self.kind == "boulder":
            return self._roll_boulder(rng)
        if self.kind in ("grass", "reeds"):
            return self._roll_blades(rng)
        if self.kind == "flowers":
            return self._roll_flowers(rng)
        if self.kind == "pebbles":
            return self._roll_pebbles(rng)
        if self.kind in ("pond", "lake"):
            return self._roll_pond(rng, c.Scenery.LAKE_RADIUS if self.kind == "lake" else c.Scenery.POND_RADIUS)
        if self.kind == "bridge":
            return self._roll_bridge(rng)
        if self.kind == "patch":
            return self._roll_patch(rng)
        if self.kind == "stump":
            return {"radius": rng.randint(11, 15), "rings": rng.randint(2, 3)}
        return {}

    def _roll_canopy(self, rng: random.Random) -> dict:
        pine = self.kind == "pine"
        radius = rng.randint(34, 52) if not pine else rng.randint(28, 40)
        base = (46, 96, 44) if not pine else (34, 72, 52)
        lobes = []
        for _ in range(5 if not pine else 4):
            ox = rng.uniform(-radius * 0.45, radius * 0.45)
            oy = rng.uniform(-radius * 0.45, radius * 0.45)
            r = round(radius * rng.uniform(0.55, 0.8))
            shade = rng.randint(-14, 16)
            color = tuple(max(0, min(255, v + shade)) for v in base)
            lobes.append((ox, oy, r, color))
        # Sorted so the biggest lobes go down first and the small bright ones read as the
        # lit top of the canopy rather than being buried under them.
        lobes.sort(key=lambda lobe: -lobe[2])
        return {"radius": radius, "lobes": lobes, "trunk": rng.randint(7, 10)}

    @staticmethod
    def _roll_boulder(rng: random.Random) -> dict:
        radius = rng.randint(26, 38)
        points = []
        count = rng.randint(6, 8)
        for i in range(count):
            angle = 2 * math.pi * i / count + rng.uniform(-0.15, 0.15)
            r = radius * rng.uniform(0.78, 1.0)
            points.append((math.cos(angle) * r, math.sin(angle) * r))
        grey = rng.randint(122, 148)
        return {"points": points, "color": (grey, grey - 4, grey - 12), "radius": radius}

    def _roll_blades(self, rng: random.Random) -> dict:
        reeds = self.kind == "reeds"
        blades = []
        for _ in range(rng.randint(4, 7)):
            ox = rng.uniform(-11, 11)
            height = rng.randint(9, 15) if not reeds else rng.randint(18, 28)
            lean = rng.uniform(-4, 4)
            green = (74, 122, 58) if not reeds else (96, 118, 62)
            shade = rng.randint(-12, 14)
            blades.append((ox, height, lean, tuple(max(0, min(255, v + shade)) for v in green)))
        return {"blades": blades}

    @staticmethod
    def _roll_flowers(rng: random.Random) -> dict:
        palette = ((226, 214, 96), (222, 128, 156), (168, 150, 226), (232, 236, 226))
        color = rng.choice(palette)
        heads = [(rng.uniform(-13, 13), rng.uniform(-10, 10), rng.randint(2, 4)) for _ in range(rng.randint(4, 7))]
        return {"color": color, "heads": heads}

    @staticmethod
    def _roll_pebbles(rng: random.Random) -> dict:
        stones = []
        for _ in range(rng.randint(3, 5)):
            grey = rng.randint(118, 142)
            stones.append((rng.uniform(-14, 14), rng.uniform(-9, 9), rng.randint(3, 6), (grey, grey, grey - 6)))
        return {"stones": stones}

    def _roll_patch(self, rng: random.Random) -> dict:
        rx = rng.randint(*c.Scenery.PATCH_RADIUS)
        ry = round(rx * rng.uniform(0.5, 0.85))
        shades = c.Scenery.PATCH_COLORS[self.biome]
        mult = shades[rng.randrange(len(shades))]
        color = tuple(max(0, min(255, round(c.Colors.GREEN[i] * mult[i]))) for i in range(3))
        # A couple of lobes rather than one clean ellipse, so the edge of a patch reads as
        # ground giving way to other ground and not as a painted circle.
        lobes = [(0.0, 0.0, 1.0)]
        for _ in range(rng.randint(1, 3)):
            lobes.append((rng.uniform(-rx * 0.6, rx * 0.6), rng.uniform(-ry * 0.6, ry * 0.6), rng.uniform(0.4, 0.7)))
        return {"rx": rx, "ry": ry, "color": color, "lobes": lobes}

    def _roll_pond(self, rng: random.Random, radius: tuple) -> dict:
        """Still water as a clutch of overlapping ellipses. One clean ellipse gave every
        pond and every lake on the map the same egg, which reads as a decal dropped on the
        ground rather than as a shore."""
        lake = self.kind == "lake"
        rx = rng.randint(*radius)
        ry = round(rx * rng.uniform(0.55, 0.85))
        lobes = [(0.0, 0.0, float(rx), float(ry))]
        for _ in range(rng.randint(2, 4) if lake else rng.randint(1, 3)):
            lx = rx * rng.uniform(0.4, 0.75)
            ly = ry * rng.uniform(0.45, 0.9)
            lobes.append((rng.uniform(-rx * 0.7, rx * 0.7), rng.uniform(-ry * 0.7, ry * 0.7), lx, ly))
        reach = max(max(abs(ox) + lx, abs(oy) + ly) for ox, oy, lx, ly in lobes)
        return {"lobes": lobes, "reach": reach}

    def _roll_bridge(self, rng: random.Random) -> dict:
        planks = [(t, rng.uniform(-2, 2)) for t in range(-4, 5)]
        return {"angle": self.angle, "planks": planks}

    # ------------------------------------------------------------------ drawing

    def draw(self, screen: pygame.Surface, camera: Camera, alpha: int = 255):
        """`alpha` under 255 is a canopy with something standing under it: the tree is drawn
        onto its own small layer and blitted see-through, so whatever is walking beneath it
        is never lost behind the leaves."""
        sx, sy = camera.world_to_screen(self.x, self.y)
        center = (round(sx), round(sy))
        drawer = _DRAWERS.get(self.kind)
        if drawer is None:
            return
        if alpha >= 255:
            drawer(self, screen, center)
            return
        reach = round(self.canopy_radius) + 20
        layer = pygame.Surface((reach * 2, reach * 2), pygame.SRCALPHA)
        drawer(self, layer, (reach, reach))
        layer.set_alpha(alpha)
        screen.blit(layer, (center[0] - reach, center[1] - reach))
        # The trunk goes back on at full strength over the faded leaves: the canopy fades so
        # the player can be seen under it, but the trunk is what actually stops them, and a
        # see-through obstacle is a wall you walk into twice.
        if self.blocking_radius:
            pygame.draw.circle(screen, (88, 62, 38), center, round(self.blocking_radius))
            pygame.draw.circle(screen, (58, 40, 24), center, round(self.blocking_radius), 2)

    def _draw_path(self, screen, center):
        """One stretch of track: a bar laid along the way the route runs, as long as the gap
        to the next blob, with a round end so two of them join without a notch. Drawn as a
        line of circles it was a string of beads, which is not what a worn path looks like
        however closely the beads are strung."""
        half = c.Scenery.ROAD_STEP / 2 + 1
        dx, dy = math.cos(self.angle) * half, math.sin(self.angle) * half
        start = (round(center[0] - dx), round(center[1] - dy))
        end = (round(center[0] + dx), round(center[1] + dy))

        def stretch(color, radius):
            pygame.draw.line(screen, color, start, end, max(2, round(radius * 2)))
            pygame.draw.circle(screen, color, center, round(radius))

        # A road between two settlements is the one track meant to be seen from a distance
        # and followed, so it is laid wider, in its own colour, on a trodden verge; a
        # footpath out to a landmark is a line worn in the grass and nothing more.
        if self.kind == "road":
            stretch(c.Scenery.ROAD_VERGE_COLOR, self.size + c.Scenery.ROAD_VERGE)
            stretch(c.Scenery.ROAD_MAIN_COLOR, self.size)
            return
        stretch(c.Scenery.ROAD_COLOR, self.size)

    def _draw_patch(self, screen, center):
        cx, cy = center
        for ox, oy, scale in self._shape["lobes"]:
            rect = pygame.Rect(0, 0, round(self._shape["rx"] * 2 * scale), round(self._shape["ry"] * 2 * scale))
            rect.center = (round(cx + ox), round(cy + oy))
            pygame.draw.ellipse(screen, self._shape["color"], rect)

    def _draw_pond(self, screen, center):
        # Bank, then body, then deep, each in one pass over every lobe. Drawing all three
        # per lobe would let the next lobe's bank paint over the last lobe's middle, which
        # is the artefact that made a river read as a row of scales.
        cx, cy = center
        for color, scale in zip(c.Scenery.WATER_COLORS, (1.0, 0.9, 0.5)):
            for ox, oy, rx, ry in self._shape["lobes"]:
                rect = pygame.Rect(0, 0, max(2, round(rx * 2 * scale)), max(2, round(ry * 2 * scale)))
                rect.center = (round(cx + ox), round(cy + oy))
                pygame.draw.ellipse(screen, color, rect)

    def _draw_lake(self, screen, center):
        self._draw_pond(screen, center)

    def _draw_river(self, screen, center):
        # One blob of the course, and only its bank: the body and the deep middle stand at
        # the same points as their own kinds and are laid down in their own passes (see
        # c.Scenery.GROUND_KINDS). Blobs sit well inside each other's width, so a blob that
        # drew all three layers itself would paint its bank over its neighbour's middle.
        pygame.draw.circle(screen, c.Scenery.WATER_COLORS[0], center, round(self.size))

    def _draw_river_body(self, screen, center):
        pygame.draw.circle(screen, c.Scenery.WATER_COLORS[1], center, round(self.size * 0.84))

    def _draw_river_deep(self, screen, center):
        pygame.draw.circle(screen, c.Scenery.WATER_COLORS[2], center, round(self.size * 0.52))

    def _draw_bridge(self, screen, center):
        cx, cy = center
        angle = self._shape["angle"]
        along = (math.cos(angle), math.sin(angle))
        across = (-math.sin(angle), math.cos(angle))
        half_len = self.size / 2
        half_wid = c.Scenery.BRIDGE_WIDTH / 2

        def point(a, b):
            return (round(cx + along[0] * a + across[0] * b), round(cy + along[1] * a + across[1] * b))

        deck = [
            point(-half_len, -half_wid),
            point(half_len, -half_wid),
            point(half_len, half_wid),
            point(-half_len, half_wid),
        ]
        pygame.draw.polygon(screen, c.Scenery.BRIDGE_COLOR, deck)
        for step, jitter in self._shape["planks"]:
            offset = step * half_len / 4.5 + jitter
            pygame.draw.line(screen, c.Scenery.BRIDGE_PLANK_COLOR, point(offset, -half_wid), point(offset, half_wid), 2)
        # Drawn where they stand: the rails are solid (`_rail_blocks`), so the bar on the
        # screen is the bar a body walks into.
        rail = c.Scenery.BRIDGE_RAIL
        for side in (-1, 1):
            offset = side * (half_wid + rail / 2)
            pygame.draw.line(
                screen, c.Scenery.BRIDGE_RAIL_COLOR, point(-half_len, offset), point(half_len, offset), rail
            )

    def _draw_blades(self, screen, center):
        cx, cy = center
        for ox, height, lean, color in self._shape["blades"]:
            start = (round(cx + ox), cy)
            pygame.draw.line(screen, color, start, (round(cx + ox + lean), round(cy - height)), 2)

    def _draw_flowers(self, screen, center):
        cx, cy = center
        for ox, oy, r in self._shape["heads"]:
            pos = (round(cx + ox), round(cy + oy))
            pygame.draw.line(screen, (72, 112, 56), pos, (pos[0], pos[1] + 6), 1)
            pygame.draw.circle(screen, self._shape["color"], pos, r)

    def _draw_pebbles(self, screen, center):
        cx, cy = center
        for ox, oy, r, color in self._shape["stones"]:
            pygame.draw.circle(screen, color, (round(cx + ox), round(cy + oy)), r)

    def _draw_stump(self, screen, center):
        radius = self._shape["radius"]
        pygame.draw.circle(screen, (104, 76, 48), center, radius)
        pygame.draw.circle(screen, (74, 52, 32), center, radius, 2)
        for ring in range(1, self._shape["rings"] + 1):
            pygame.draw.circle(screen, (128, 96, 62), center, round(radius * ring / (self._shape["rings"] + 1)), 1)

    def _draw_boulder(self, screen, center):
        cx, cy = center
        points = [(cx + px, cy + py) for px, py in self._shape["points"]]
        shadow = [(x + 4, y + 6) for x, y in points]
        pygame.draw.polygon(screen, (52, 62, 44), shadow)
        pygame.draw.polygon(screen, self._shape["color"], points)
        pygame.draw.polygon(screen, tuple(round(v * 0.66) for v in self._shape["color"]), points, 2)
        highlight = [(cx + px * 0.45 - 4, cy + py * 0.45 - 5) for px, py in self._shape["points"]]
        pygame.draw.polygon(screen, tuple(min(255, round(v * 1.16)) for v in self._shape["color"]), highlight)

    def _draw_canopy(self, screen, center):
        cx, cy = center
        radius = self._shape["radius"]
        if self.felled:
            self._draw_fallen(screen, center)
            return
        shadow = pygame.Rect(0, 0, round(radius * 1.7), round(radius * 1.1))
        shadow.center = (cx + 8, cy + 12)
        pygame.draw.ellipse(screen, (48, 68, 40), shadow)
        pygame.draw.circle(screen, (88, 62, 38), (cx, cy), self._shape["trunk"])
        for ox, oy, r, color in self._shape["lobes"]:
            pygame.draw.circle(screen, color, (round(cx + ox), round(cy + oy)), r)
        # What is left of it, so a tree worth two more swings looks like one.
        self._draw_wear(screen, center)

    def _draw_wear(self, screen, center):
        """The cuts taken out of a standing tree, through the same crack system every other
        hit-point pool in the world wears down through (`core/damage_fx.py`)."""
        if self.hp >= c.Trees.HP:
            return
        radius = round(self._shape["trunk"])
        body = pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2)
        draw_cracks(screen, body, max(0.0, self.hp / c.Trees.HP), self.key or f"{self.x},{self.y}")

    def _draw_fallen(self, screen, center):
        """A stump, and the tree still going over for the moment after it was cut: the
        canopy leans away and drops out of sight, so a wood coming down is something the
        player watches happen rather than a trunk that blinks into a stump."""
        cx, cy = center
        radius = self._shape["radius"]
        trunk = round(self._shape["trunk"])
        elapsed = pygame.time.get_ticks() - (self.fell_start_ms or 0)
        if self.fell_start_ms is not None and elapsed < c.Trees.FALL_MS:
            lean = (elapsed / c.Trees.FALL_MS) ** 2
            offset = round(radius * 1.8 * lean)
            for ox, oy, r, color in self._shape["lobes"]:
                faded = tuple(round(v * (1.0 - lean * 0.4)) for v in color)
                pygame.draw.circle(screen, faded, (round(cx + ox + offset), round(cy + oy + offset // 2)), r)
        pygame.draw.circle(screen, c.Trees.STUMP_COLOR, (cx, cy), trunk)
        pygame.draw.circle(screen, (58, 40, 24), (cx, cy), trunk, 2)
        pygame.draw.circle(screen, (128, 96, 62), (cx, cy), max(1, round(trunk * 0.5)), 1)


# What draws each kind of scenery. An explicit table rather than a name looked up off the
# kind, so a search for "_draw_boulder" finds both where it is written and where it is
# used, and a kind with nothing to draw is simply absent. Grass and reeds are the same
# blades, a tree and a pine the same canopy: only the shape rolled for them differs.
_DRAWERS = {
    "path": Scenery._draw_path,
    "road": Scenery._draw_path,
    "patch": Scenery._draw_patch,
    "pond": Scenery._draw_pond,
    "lake": Scenery._draw_lake,
    "river": Scenery._draw_river,
    "river_body": Scenery._draw_river_body,
    "river_deep": Scenery._draw_river_deep,
    "bridge": Scenery._draw_bridge,
    "grass": Scenery._draw_blades,
    "reeds": Scenery._draw_blades,
    "flowers": Scenery._draw_flowers,
    "pebbles": Scenery._draw_pebbles,
    "stump": Scenery._draw_stump,
    "boulder": Scenery._draw_boulder,
    "tree": Scenery._draw_canopy,
    "pine": Scenery._draw_canopy,
}
