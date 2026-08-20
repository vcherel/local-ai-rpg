from __future__ import annotations

import math
import random
from functools import lru_cache
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.damage_fx import draw_cracks
from game.entities.buildings import Building

if TYPE_CHECKING:
    from core.camera import Camera


class Village:
    """A cluster of buildings around an open plaza, the shape every settlement takes.

    The village itself owns nothing but the plaza: its buildings live in the world's one
    building list like any other, so collision, interiors, NPCs and saving all work exactly
    as they did when the world had a single scattered town. What this class adds is the
    centre the cluster is built around, the name the LLM gives it, and whether the player
    has walked into it yet.
    """

    def __init__(
        self,
        x,
        y,
        chunk: tuple[int, int],
        size: str = "village",
        radius: int = 700,
        extent: int = 0,
        extent_y: int = 0,
        tier: int | None = None,
    ):
        self.x = x
        self.y = y
        # The chunk that owns this village, and its identity in the save: a chunk that
        # already has one never generates a second.
        self.chunk = (int(chunk[0]), int(chunk[1]))
        self.size = size
        self.radius = radius
        self.name: str | None = None
        self.discovered = False
        # How well defended this one is, rolled once from how far out it stands and how big
        # it is, then persisted like the wall itself. Everything that differs between a
        # border hamlet and a deep wilds town reads this and nothing else.
        self.tier = self._tier_for(x, y, size) if tier is None else int(tier)
        # Whether this one stands a wall. Rolled from the size when the settlement is
        # built and then persisted, like everything else about a village: the wall is part
        # of what the place is, not something rederived from a seed.
        self.defended = size in c.Villages.WALLED_SIZES
        # How far the outermost wall of the outermost building stands from the middle, per
        # axis. The wall is set from these rather than from `radius`, which is a diagonal
        # and would leave a field of nothing between the last house and the palisade; two
        # of them rather than one, so a settlement that spread out sideways is walled in a
        # rectangle that follows it instead of a square around its longest side.
        self.extent_x = extent or radius
        self.extent_y = extent_y or self.extent_x
        # The gates stand open while the settlement has nothing to fear and are barred the
        # moment it turns on the player (`World.bar_gates`). Barred, a gate is the one part
        # of a wall that gives: `gate_broken` is persisted like a beaten-down front door,
        # the damage a standing one has taken is session-only like a crate's.
        self.barred = False
        self.gate_broken: set[int] = set()
        self.gate_hp: dict[int, int] = {}
        # How far each leaf has actually swung, 0 shut and 1 wide open, and how long a gate
        # somebody has been let through still stands open for. Both session-only: a gate's
        # position is drawn from `barred`, which is itself worked out afresh every frame.
        self.gate_frac: dict[int, float] = {}
        self.gate_hold: dict[int, float] = {}
        self._defences = None

    @staticmethod
    def _tier_for(x, y, size: str) -> int:
        """How well defended a settlement standing here is. Distance from the world centre
        first, since that is the game's one measure of depth, nudged by how much there is
        to defend: a deep hamlet is still a hamlet and a town is worth a better wall."""
        center = c.World.WORLD_SIZE // 2
        distance = math.hypot(x - center, y - center)
        tier = sum(1 for threshold in c.Villages.TIER_DISTANCES if distance >= threshold)
        tier += c.Villages.TIER_SIZE_BONUS.get(size, 0)
        return max(0, min(c.Villages.MAX_TIER, tier))

    @property
    def extent(self) -> int:
        """The settlement's footprint as one number, for everything that wants a radius."""
        return max(self.extent_x, self.extent_y)

    @property
    def wall_style(self) -> str:
        return c.Villages.WALL_STYLE_BY_TIER[self.tier]

    @property
    def wall_thickness(self) -> int:
        return c.Villages.WALL_THICKNESS_BY_TIER[self.tier]

    @property
    def tower_radius(self) -> int:
        return c.Villages.TOWER_RADIUS_BY_TIER[self.tier]

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    @property
    def grounds_radius(self) -> float:
        """How far the settlement's grounds reach. A walled town's grounds run out to its
        wall, not to the last house inside it: the wall, its towers and whoever is posted on
        them are part of the place, so the same one call decides who turns on the player,
        who defends it, where nothing hostile may be stood up and how far the trees are cut
        back. The stakes and the ditch outside the wall are counted in, since they belong to
        the settlement as much as the gate does."""
        if not self.defended:
            return self.radius
        half_x = self.extent_x + c.Villages.WALL_MARGIN
        half_y = self.extent_y + c.Villages.WALL_MARGIN
        # The corner towers stand at the diagonal, further out than any side of the wall:
        # anything short of that leaves the towers and whoever is posted in them outside
        # the settlement they belong to, which is how a tower guard ended up unable to
        # take his own village's side.
        corner = math.hypot(half_x, half_y) + self.tower_radius
        outworks = max(half_x, half_y) + c.Villages.DITCH_OFFSET + c.Villages.DITCH_WIDTH
        if self.tier < c.Villages.DITCH_TIER:
            outworks = 0.0
        return max(self.radius, corner, outworks)

    def contains_point(self, x, y) -> bool:
        return math.hypot(self.x - x, self.y - y) <= self.grounds_radius

    def defences(self) -> dict:
        """The wall: its stretches, its gates, its towers, and the stakes and ditch outside
        it. Built once from the village's own footprint and tier, so nothing about it has to
        be saved beyond which gates have been broken.

        A ring split by four gates, rather than an unbroken circle, for two reasons: a chaser
        routes round a rectangle already (`World._detour_corner`), and a gate on every side
        means walling a town in never turns an approach into a dead end. What the tier
        changes is what it is built of and what stands outside it, never the way in."""
        if self._defences is not None:
            return self._defences
        if not self.defended:
            self._defences = {"walls": [], "gates": [], "towers": [], "spikes": [], "ditch": []}
            return self._defences

        half_x = self.extent_x + c.Villages.WALL_MARGIN
        half_y = self.extent_y + c.Villages.WALL_MARGIN
        thickness = self.wall_thickness
        gate = c.Villages.GATE_WIDTH
        house = c.Villages.GATEHOUSE
        walls, gates, towers, spikes, ditch = [], [], [], [], []

        for nx, ny in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            along_x = nx == 0  # the wall on this side runs along x
            half_along = half_x if along_x else half_y
            mid = (self.x + nx * half_x, self.y + ny * half_y)
            run = half_along - gate / 2  # one stretch, gate edge to corner

            def piece(offset: float, length: float, depth: float) -> pygame.Rect:
                """A block of wall `length` long, `offset` along the side from its gateway."""
                rect = (
                    pygame.Rect(0, 0, round(length), round(depth))
                    if along_x
                    else pygame.Rect(0, 0, round(depth), round(length))
                )
                rect.center = (
                    (round(mid[0] + offset), round(mid[1])) if along_x else (round(mid[0]), round(mid[1] + offset))
                )
                return rect

            for side in (-1, 1):
                walls.append(piece(side * (gate / 2 + run / 2), run, thickness))
                # The gatehouse: the wall thickened where it meets the gateway, so a gate
                # reads as a way through something rather than a hole in a fence. Solid like
                # the rest, which is all navigation needs to know about it.
                walls.append(piece(side * (gate / 2 + house / 2), house, thickness * 2.0))
                if self.tier >= c.Villages.SPIKE_TIER:
                    spikes.extend(self._stakes(mid, (nx, ny), along_x, side, gate, run))
                if self.tier >= c.Villages.DITCH_TIER:
                    trench = piece(side * (gate / 2 + run / 2), run, c.Villages.DITCH_WIDTH)
                    trench.center = (
                        trench.centerx + nx * c.Villages.DITCH_OFFSET,
                        trench.centery + ny * c.Villages.DITCH_OFFSET,
                    )
                    ditch.append(trench)
            leaf = piece(0, gate, thickness)
            gates.append({"pos": mid, "rect": leaf, "along_x": along_x})

        for cx in (-1, 1):
            for cy in (-1, 1):
                towers.append((self.x + cx * half_x, self.y + cy * half_y))
        self._defences = {"walls": walls, "gates": gates, "towers": towers, "spikes": spikes, "ditch": ditch}
        return self._defences

    @staticmethod
    def _stakes(mid, normal, along_x: bool, side: int, gate: float, run: float) -> list:
        """A row of sharpened stakes standing off one stretch of wall, outside it."""
        nx, ny = normal
        out = c.Villages.SPIKE_OFFSET
        points = []
        step = c.Villages.SPIKE_SPACING
        count = max(0, int(run // step))
        for i in range(count):
            offset = side * (gate / 2 + step / 2 + i * step)
            px = mid[0] + (offset if along_x else 0) + nx * out
            py = mid[1] + (0 if along_x else offset) + ny * out
            points.append((px, py))
        return points

    # ------------------------------------------------------------------ gates

    def gate_closed(self, index: int) -> bool:
        """True while this gateway is shut: a wall to anything trying to walk through it.
        A gate is only ever shut because the settlement wants the player out (or something
        else in the street), and a broken one never shuts again."""
        return self.barred and index not in self.gate_broken

    def gate_ajar(self, index: int) -> bool:
        """Whether this gateway is being held open for somebody. A barred gate is still a
        wall to everything that collides with it; this is only ever true of a gate one of
        the settlement's own people is walking through (`World.pass_gate_for`)."""
        return self.gate_hold.get(index, 0.0) > 0.0

    def let_through(self, index: int):
        """Work a barred gate open for a moment. Its people know their own gate: they lift
        the bar, walk out, and it shuts behind them, which is why the player hammering on
        the far side of it is still shut out."""
        if self.gate_closed(index):
            self.gate_hold[index] = c.Villages.GATE_HOLD_MS

    def advance_gates(self, dt):
        """Carry every leaf one frame towards where it should be standing.

        Nothing here is collided against: `gate_closed` flips the instant a settlement turns,
        and this is the leaf catching up with it. A gate that shuts on the frame it is barred
        is a wall appearing out of nothing; one that swings is a gate."""
        for index in range(len(self.defences()["gates"])):
            if self.gate_hold.get(index, 0.0) > 0.0:
                self.gate_hold[index] -= dt
            shut = self.gate_closed(index) and not self.gate_ajar(index)
            frac = self.gate_frac.get(index, 0.0 if shut else 1.0)
            step = dt / c.Villages.GATE_SWING_MS
            self.gate_frac[index] = max(0.0, frac - step) if shut else min(1.0, frac + step)

    def gate_open_frac(self, index: int) -> float:
        """How far this gate is drawn open, 0 to 1."""
        return self.gate_frac.get(index, 0.0 if self.gate_closed(index) else 1.0)

    def gate_side_point(self, index: int, x, y, radius: float, across: bool) -> tuple:
        """(x, y) stepped clear of this gate's leaf along the gateway's own line: to the far
        side of it when `across` (somebody being let through), to the nearer side otherwise
        (whatever a gate is being barred on top of).

        Never a ring search, for the reason a doorway is never one either
        (`Building.clear_of_door`): the gateway is the one gap in that wall, so the way out
        of it is a single step in or a single step out, not a hunt for open ground."""
        gate = self.defences()["gates"][index]
        leaf = gate["rect"]
        depth = (leaf.height if gate["along_x"] else leaf.width) / 2 + radius + 2
        if gate["along_x"]:
            side = 1.0 if y >= leaf.centery else -1.0
            return x, leaf.centery + (-side if across else side) * depth
        side = 1.0 if x >= leaf.centerx else -1.0
        return leaf.centerx + (-side if across else side) * depth, y

    def gate_between(self, index: int, ax, ay, bx, by) -> bool:
        """Whether this gate's leaf is what stands between two points, meaning they are on
        opposite sides of the line the gateway is cut in.

        `contains_point` cannot answer this and reading it as though it could is what left a
        pack standing quietly at a barred gate: the grounds are a circle drawn round the
        whole settlement and reach well past the wall on each axis, so two bodies either
        side of the north gate are both standing in them."""
        gate = self.defences()["gates"][index]
        leaf = gate["rect"]
        if gate["along_x"]:
            return (ay - leaf.centery) * (by - leaf.centery) < 0
        return (ax - leaf.centerx) * (bx - leaf.centerx) < 0

    def gate_key(self, index: int) -> str:
        """Identity of one gate for `core.damage_fx`, which is keyed by string."""
        return f"gate:{self.chunk[0]}:{self.chunk[1]}:{index}"

    def gate_at(self, x, y, reach: float) -> int | None:
        """The barred gate a blow at (x, y) lands on, or None. The only part of a wall that
        answers a swing at all."""
        for index, gate in enumerate(self.defences()["gates"]):
            if not self.gate_closed(index):
                continue
            rect = gate["rect"]
            nearest_x = min(max(x, rect.left), rect.right)
            nearest_y = min(max(y, rect.top), rect.bottom)
            if math.hypot(x - nearest_x, y - nearest_y) < reach:
                return index
        return None

    def damage_gate(self, index: int, damage: int) -> bool:
        """Land a blow on a barred gate. True on the blow that finally puts it through, from
        then on the gateway is a hole for good, exactly like a beaten-down front door."""
        if not self.gate_closed(index):
            return False
        remaining = self.gate_hp.get(index, c.Villages.GATE_HP) - damage
        if remaining > 0:
            self.gate_hp[index] = remaining
            return False
        self.gate_hp.pop(index, None)
        self.gate_broken.add(index)
        return True

    def gate_health(self, index: int) -> float:
        """How much of this gate is left, as a fraction, for the cracks drawn over it."""
        return self.gate_hp.get(index, c.Villages.GATE_HP) / c.Villages.GATE_HP

    # ------------------------------------------------------------------ terrain

    def spike_hit(self, x, y, radius: float) -> bool:
        """Whether a body standing here is in the stakes outside the wall."""
        if not self.defended or self.tier < c.Villages.SPIKE_TIER:
            return False
        reach = c.Villages.SPIKE_RADIUS + radius
        return any(math.hypot(x - sx, y - sy) < reach for sx, sy in self.defences()["spikes"])

    def in_ditch(self, x, y) -> bool:
        """Whether this point lies in the ditch dug outside the wall. Like water, a ditch
        costs speed rather than passage: it slows an approach, it never stops one."""
        if not self.defended or self.tier < c.Villages.DITCH_TIER:
            return False
        return any(trench.collidepoint(x, y) for trench in self.defences()["ditch"])

    def blocks(self, x, y, radius) -> bool:
        """The well in the middle of the plaza is solid, and so is the wall around a walled
        town, its towers and any gate currently barred; everything else in a village is a
        building, collided against by the buildings themselves."""
        if math.hypot(self.x - x, self.y - y) < c.Villages.WELL_RADIUS + radius:
            return True
        if not self.defended:
            return False
        defences = self.defences()
        for tower in defences["towers"]:
            if math.hypot(tower[0] - x, tower[1] - y) < self.tower_radius + radius:
                return True
        solids = list(defences["walls"])
        solids += [gate["rect"] for index, gate in enumerate(defences["gates"]) if self.gate_closed(index)]
        for wall in solids:
            nearest_x = min(max(x, wall.left), wall.right)
            nearest_y = min(max(y, wall.top), wall.bottom)
            if math.hypot(x - nearest_x, y - nearest_y) < radius:
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "chunk": list(self.chunk),
            "size": self.size,
            "radius": self.radius,
            "extent": self.extent_x,
            "extent_y": self.extent_y,
            "tier": self.tier,
            "name": self.name,
            "discovered": self.discovered,
            "defended": self.defended,
            "gate_broken": sorted(self.gate_broken),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Village:
        village = cls(
            data["x"],
            data["y"],
            data["chunk"],
            data.get("size", "village"),
            data.get("radius", 700),
            data.get("extent", 0),
            data.get("extent_y", 0),
            data.get("tier"),
        )
        village.name = data.get("name")
        village.discovered = data.get("discovered", False)
        village.defended = data.get("defended", village.defended)
        village.gate_broken = set(data.get("gate_broken", []))
        return village

    def draw(self, screen: pygame.Surface, camera: Camera):
        """The plaza: packed earth and a well. The name is the minimap strip's job; written on
        the ground it was one more label lying over the street."""
        cx, cy = camera.world_to_screen(self.x, self.y)
        plaza = pygame.Rect(0, 0, c.Villages.PLAZA_RADIUS * 2, round(c.Villages.PLAZA_RADIUS * 1.5))
        plaza.center = (round(cx), round(cy))
        pygame.draw.ellipse(screen, c.Villages.PLAZA_COLOR, plaza)

        # Trodden earth around the edge of the plaza, seeded from the village position so
        # it holds still as the camera pans.
        rng = random.Random(f"plaza:{self.x},{self.y}")
        darker = tuple(round(v * 0.88) for v in c.Villages.PLAZA_COLOR)
        for _ in range(14):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(0.4, 1.0)
            px = cx + math.cos(angle) * plaza.width / 2 * dist
            py = cy + math.sin(angle) * plaza.height / 2 * dist
            pygame.draw.circle(screen, darker, (round(px), round(py)), rng.randint(4, 11))

        self._draw_well(screen, (round(cx), round(cy)))
        self._draw_defences(screen, camera)

    def _draw_defences(self, screen: pygame.Surface, camera: Camera):
        """The wall and everything that belongs to it, drawn under whatever walks over the
        ground. A palisade is a row of sharpened logs, a stone wall is coursed blocks: the
        material is how far out the settlement stands, read before anything is fought."""
        defences = self.defences()
        if not defences["walls"]:
            return

        stone = self.wall_style == "stone"
        body = c.Villages.WALL_STONE if stone else c.Villages.WALL_COLOR
        top = c.Villages.WALL_STONE_TOP if stone else c.Villages.WALL_TOP
        edge = (78, 76, 70) if stone else (68, 52, 34)

        for trench in defences["ditch"]:
            sx, sy = camera.world_to_screen(trench.left, trench.top)
            rect = pygame.Rect(round(sx), round(sy), trench.width, trench.height)
            # A lip of turned earth round the edge and a darker floor, so a ditch reads as
            # something dug rather than as a shadow lying on the grass.
            pygame.draw.rect(screen, (104, 88, 62), rect)
            pygame.draw.rect(screen, c.Villages.DITCH_COLOR, rect.inflate(-10, -10))
            pygame.draw.rect(screen, (56, 46, 32), rect.inflate(-26, -26))

        for wall in defences["walls"]:
            sx, sy = camera.world_to_screen(wall.left, wall.top)
            rect = pygame.Rect(round(sx), round(sy), wall.width, wall.height)
            pygame.draw.rect(screen, body, rect)
            along_x = rect.width > rect.height
            span = rect.width if along_x else rect.height
            step = 18 if stone else 14
            for offset in range(4, max(5, span - 4), step):
                block = (
                    pygame.Rect(rect.left + offset, rect.top, step - 4, rect.height)
                    if along_x
                    else pygame.Rect(rect.left, rect.top + offset, rect.width, step - 4)
                )
                pygame.draw.rect(screen, top, block)
                pygame.draw.rect(screen, edge, block, 1)
            pygame.draw.rect(screen, edge, rect, 2)

        for sx, sy in defences["spikes"]:
            px, py = camera.world_to_screen(sx, sy)
            length = c.Villages.SPIKE_LENGTH
            base = (round(px), round(py))
            pygame.draw.circle(screen, (52, 42, 30), base, 6)
            pygame.draw.line(screen, (62, 48, 32), base, (base[0], base[1] - length), 8)
            pygame.draw.line(screen, c.Villages.SPIKE_COLOR, base, (base[0], base[1] - length), 5)
            # The point, catching the light: a stake read from above is a pale tip.
            pygame.draw.line(screen, (238, 230, 210), (base[0], base[1] - length), (base[0], base[1] - length + 6), 3)

        for index, gate in enumerate(defences["gates"]):
            self._draw_gate(screen, camera, index, gate)

        for tx, ty in defences["towers"]:
            sx, sy = camera.world_to_screen(tx, ty)
            radius = self.tower_radius
            pygame.draw.circle(screen, (60, 52, 44), (round(sx), round(sy)), radius + 3)
            pygame.draw.circle(screen, c.Villages.TOWER_STONE, (round(sx), round(sy)), radius)
            pygame.draw.circle(screen, (104, 100, 94), (round(sx), round(sy)), round(radius * 0.6))
            # Crenellations, read from above as blocks around the rim.
            for i in range(8):
                angle = i * math.pi / 4
                block = pygame.Rect(0, 0, 14, 14)
                block.center = (round(sx + math.cos(angle) * radius), round(sy + math.sin(angle) * radius))
                pygame.draw.rect(screen, (168, 164, 156), block)
                pygame.draw.rect(screen, (70, 66, 60), block, 1)

    def _draw_gate(self, screen: pygame.Surface, camera: Camera, index: int, gate: dict):
        """One gateway: its two posts, and the pair of leaves hung between them at whatever
        angle they have swung to. Shut is the two of them meeting in the middle of the gap,
        open is both swung back inside the wall, and everything between is `advance_gates`
        carrying them from one to the other."""
        gx, gy = gate["pos"]
        sx, sy = camera.world_to_screen(gx, gy)
        along_x = gate["along_x"]
        for side in (-1, 1):
            post = pygame.Rect(0, 0, 18, 18)
            shift = side * c.Villages.GATE_WIDTH / 2
            post.center = (round(sx + shift), round(sy)) if along_x else (round(sx), round(sy + shift))
            pygame.draw.rect(screen, c.Villages.GATE_POST, post)
            pygame.draw.rect(screen, (52, 40, 28), post, 2)

        if index in self.gate_broken:
            # Beaten down: the gateway is a hole for good and there is nothing left to hang.
            return

        leaf = gate["rect"]
        half = c.Villages.GATE_WIDTH / 2
        thickness = leaf.height if along_x else leaf.width
        theta = math.radians(c.Villages.GATE_SWING_DEG) * self.gate_open_frac(index)
        # Both leaves swing back into the settlement, so an open gateway reads as a way
        # through from either side of the wall rather than as a leaf lying across one.
        toward_middle = math.copysign(1.0, (self.y - gy) if along_x else (self.x - gx))
        normal = (0.0, toward_middle) if along_x else (toward_middle, 0.0)
        for side in (-1, 1):
            hinge = (gx + side * half, gy) if along_x else (gx, gy + side * half)
            axis = (-side, 0.0) if along_x else (0.0, -side)
            self._draw_leaf(screen, camera, hinge, axis, normal, theta, half, thickness)

        health = self.gate_health(index)
        if health < 1.0 and self.gate_open_frac(index) < 0.05:
            lx, ly = camera.world_to_screen(leaf.left, leaf.top)
            rect = pygame.Rect(round(lx), round(ly), leaf.width, leaf.height)
            draw_cracks(screen, rect, health, self.gate_key(index))

    @staticmethod
    def _draw_leaf(screen, camera: Camera, hinge, axis, normal, theta: float, length: float, thickness: float):
        """One leaf, hung on `hinge` and swung `theta` off the line of the gateway.

        Written in the leaf's own two axes (`axis` along the gateway from the hinge inwards,
        `normal` into the settlement) so the same few lines hang all eight leaves of a town,
        whichever of the four walls they are in and whichever way round they open."""
        cos, sin = math.cos(theta), math.sin(theta)

        def point(along: float, across: float):
            a = along * cos - across * sin
            b = along * sin + across * cos
            return camera.world_to_screen(
                hinge[0] + axis[0] * a + normal[0] * b,
                hinge[1] + axis[1] * a + normal[1] * b,
            )

        edge = thickness / 2
        corners = [point(0, -edge), point(length, -edge), point(length, edge), point(0, edge)]
        pygame.draw.polygon(screen, c.Villages.GATE_LEAF, corners)
        pygame.draw.polygon(screen, (46, 34, 22), corners, 3)
        for offset in range(20, int(length), 22):
            pygame.draw.line(screen, (66, 48, 30), point(offset, -edge), point(offset, edge), 2)

    @staticmethod
    def _draw_well(screen: pygame.Surface, center):
        cx, cy = center
        radius = c.Villages.WELL_RADIUS
        pygame.draw.circle(screen, c.Villages.WELL_STONE, (cx, cy), radius)
        pygame.draw.circle(screen, (92, 90, 84), (cx, cy), radius, 3)
        pygame.draw.circle(screen, (40, 58, 74), (cx, cy), radius - 10)
        # Two posts and the beam they carry, read from above as a bar across the shaft.
        for side in (-1, 1):
            post = pygame.Rect(0, 0, 8, radius * 2 + 10)
            post.center = (cx + side * (radius - 4), cy)
            pygame.draw.rect(screen, (96, 68, 42), post)
        beam = pygame.Rect(0, 0, radius * 2 + 6, 8)
        beam.center = (cx, cy - radius - 2)
        pygame.draw.rect(screen, (120, 86, 52), beam)


@lru_cache(maxsize=4096)
def _region_site(rx: int, ry: int) -> tuple[int, int, int, int] | None:
    """The chunk one region settles and where in it, as (cx, cy, x, y), or None for an empty
    region. Pure function of the region coordinates."""
    region = c.Villages.REGION_CHUNKS
    rng = random.Random(f"village:{rx},{ry}")
    if rng.random() > c.Villages.REGION_CHANCE:
        return None

    cx = rx * region + rng.randrange(region)
    cy = ry * region + rng.randrange(region)
    size = c.World.CHUNK_SIZE
    margin = c.Villages.CHUNK_MARGIN
    x = cx * size + rng.randint(margin, size - margin)
    y = cy * size + rng.randint(margin, size - margin)

    center = c.World.WORLD_SIZE // 2
    if math.hypot(x - center, y - center) < c.Villages.MIN_DIST_FROM_SPAWN:
        return None
    return cx, cy, x, y


@lru_cache(maxsize=4096)
def village_site(cx: int, cy: int) -> tuple[int, int] | None:
    """Where the village belonging to chunk (cx, cy) stands, or None if it holds none.

    One region of REGION_CHUNKS x REGION_CHUNKS chunks settles a single chunk, and a region
    whose site lands too close to a neighbouring region's yields to it, so two settlements
    can't end up back to back across a region border. All of it is a pure function of the
    coordinates: the same chunk always offers the same site, whether or not the village
    behind it has been generated yet, which is also why the answer is cached: chunk
    loading, landmark placement and the roads between settlements all ask it repeatedly
    for the same coordinates.
    """
    region = c.Villages.REGION_CHUNKS
    rx, ry = math.floor(cx / region), math.floor(cy / region)
    site = _region_site(rx, ry)
    if site is None or (site[0], site[1]) != (cx, cy):
        return None

    for nx in range(rx - 1, rx + 2):
        for ny in range(ry - 1, ry + 2):
            # Ties are broken by region order, the same way from wherever this is asked.
            if (nx, ny) >= (rx, ry):
                continue
            other = _region_site(nx, ny)
            if other is not None and math.hypot(site[2] - other[2], site[3] - other[3]) < c.Villages.MIN_GAP:
                return None
    return site[2], site[3]


@lru_cache(maxsize=8)
def _worst_case_footprint(size: str) -> tuple[int, int, int]:
    """The biggest (radius, extent_x, extent_y) a settlement of this size can lay out.

    Rolled without an rng: every count is taken at its maximum, every building at its
    largest and the jitter at its worst, so the answer is an upper bound on a village that
    has not been generated yet rather than a guess at the one that will be."""
    composition = c.Villages.START_COMPOSITION if size == "start" else c.Villages.COMPOSITION[size]
    count = sum(high for _low, high in composition.values())
    slots = _plaza_slots(count, random.Random(0))
    jitter = c.Villages.SLOT_JITTER
    kinds = [kind for kind, (_low, high) in composition.items() if high]
    max_w = max(c.Buildings.SIZES[kind][0][1] for kind in kinds)
    max_h = max(c.Buildings.SIZES[kind][1][1] for kind in kinds)
    radius = round(max((math.hypot(ox, oy) for ox, oy in slots), default=0) + jitter + c.Villages.SLOT_W / 2)
    extent_x = round(max((abs(ox) for ox, _oy in slots), default=0) + jitter + max_w / 2)
    extent_y = round(max((abs(oy) for _ox, oy in slots), default=0) + jitter + max_h / 2)
    return radius, extent_x, extent_y


@lru_cache(maxsize=4096)
def site_grounds_radius(cx: int, cy: int) -> float:
    """How far the grounds of the village chunk (cx, cy) offers will reach, asked before the
    settlement exists. 0 for a chunk that holds no site.

    A pure function of the coordinates like `village_site` itself: the size is the first
    draw `generate_village` makes off the same seed, and the footprint is that size at its
    largest. Anything placed in the wilderness (a landmark, a graveyard) clears this rather
    than clearing the site point by a fixed distance, which is how a row of tombstones
    ended up against a town's gate."""
    site = village_site(cx, cy)
    if site is None:
        return 0.0
    rng = random.Random(f"village-layout:{cx},{cy}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS)
    size = rng.choices(sizes, weights=weights)[0]
    radius, extent_x, extent_y = _worst_case_footprint(size)
    return Village(site[0], site[1], (cx, cy), size, radius, extent_x, extent_y).grounds_radius


def sites_near_chunk(cx: int, cy: int, chunk_radius: int) -> list[tuple[int, int]]:
    """Every village site within `chunk_radius` chunks of (cx, cy), generated or not, as
    plain points. `settlements_near_chunk` is the same walk with each site's chunk and the
    reach of its grounds kept, which is what a road needs to stop at a gate rather than
    running through the houses behind it."""
    return [(x, y) for x, y, _, _, _ in settlements_near_chunk(cx, cy, chunk_radius)]


@lru_cache(maxsize=512)
def settlements_near_chunk(cx: int, cy: int, chunk_radius: int) -> tuple[tuple[float, float, int, int, float], ...]:
    """Every village site within `chunk_radius` chunks of (cx, cy), generated or not, as
    (x, y, chunk x, chunk y, grounds radius).

    Sites are a pure function of their region, so this answers the same thing from
    anywhere: what the roads between settlements are drawn from, and cheap enough to ask
    on every chunk load because it walks regions rather than chunks.
    """
    region = c.Villages.REGION_CHUNKS
    sites: list[tuple[float, float, int, int, float]] = []
    for rx in range(math.floor((cx - chunk_radius) / region), math.floor((cx + chunk_radius) / region) + 1):
        for ry in range(math.floor((cy - chunk_radius) / region), math.floor((cy + chunk_radius) / region) + 1):
            site = _region_site(rx, ry)
            # Asked back through village_site so a region that stands down for a neighbour
            # is left out here too, and no road is drawn to a village that never exists.
            if site is not None and village_site(site[0], site[1]) is not None:
                sites.append((site[2], site[3], site[0], site[1], site_grounds_radius(site[0], site[1])))
    return tuple(sites)


def _building_kinds(composition: dict, rng: random.Random) -> list[str]:
    """The buildings a settlement of this composition is made of, biggest first: the
    tavern and the shops take the slots nearest the plaza, the houses spread out behind."""
    kinds: list[str] = []
    for kind in ("tavern", "shop", "house"):
        low, high = composition[kind]
        kinds.extend([kind] * rng.randint(low, high))
    return kinds


def _plaza_slots(count: int, rng: random.Random) -> list[tuple[float, float]]:
    """Offsets from the plaza for `count` buildings: a grid centred on the village with the
    middle of it left open, ordered nearest the plaza first and jittered so the result reads
    as a settlement rather than a spreadsheet.

    The open middle is a keep-out rather than "the first slot in the list": a grid with an
    even number of columns has no centre slot at all, so dropping the nearest one deleted an
    arbitrary house and left the four around it free to reach across the well."""
    slots: list[tuple[float, float]] = []
    spare = 1
    while len(slots) < count:
        columns = max(2, math.ceil(math.sqrt(count + spare)))
        rows = math.ceil((count + spare) / columns)
        slots = []
        for row in range(rows):
            for column in range(columns):
                ox = (column - (columns - 1) / 2) * c.Villages.SLOT_W
                oy = (row - (rows - 1) / 2) * c.Villages.SLOT_H
                if abs(ox) < c.Villages.SLOT_W and abs(oy) < c.Villages.SLOT_H / 2:
                    continue
                slots.append((ox, oy))
        spare += 1

    slots.sort(key=lambda slot: math.hypot(*slot))
    jitter = c.Villages.SLOT_JITTER
    return [(ox + rng.uniform(-jitter, jitter), oy + rng.uniform(-jitter, jitter)) for ox, oy in slots[:count]]


def _clear_of_plaza(building: Building, center: tuple[float, float]) -> bool:
    """Push a building out until nothing it is built of covers the plaza.

    Measured off `bounds` rather than off the slot offset: a wing grows out to one side, so
    the middle of what the building actually covers is not where its main block stands, and
    an L used to reach over the well while its rect sat clear of it. Whichever axis needs
    the smaller shove is the one that gives, so a house steps off the square rather than
    being flung to the edge of the village. Returns whether the building had to move."""
    keep = c.Villages.PLAZA_RADIUS
    bounds = building.bounds
    dx = bounds.centerx - center[0]
    dy = bounds.centery - center[1]
    need_x = keep + bounds.width / 2 - abs(dx)
    need_y = keep + bounds.height / 2 - abs(dy)
    if need_x <= 0 or need_y <= 0:
        return False
    # Rounded up rather than to nearest: half a pixel of plaza left under a wall is still
    # a wall on the square.
    if need_x <= need_y:
        building.x += math.ceil(need_x) * (1 if dx >= 0 else -1)
    else:
        building.y += math.ceil(need_y) * (1 if dy >= 0 else -1)
    building.reset_geometry()
    return True


def _facing_towards_plaza(ox: float, oy: float) -> str:
    """Which wall a building at this offset from the plaza puts its door in: the one facing
    the middle of the village. A settlement whose doors all opened south read as a warehouse
    yard; doors onto the square make the plaza the street it is meant to be."""
    if abs(ox) > abs(oy):
        return "W" if ox > 0 else "E"
    return "N" if oy > 0 else "S"


def _separate(buildings: list[Building], center: tuple[float, float], gap: int = 90):
    """Push buildings off each other and off the plaza, outward from the middle of the
    village. The plaza and the well in the middle of it belong to the settlement: a house
    standing on the well made the one thing every village has impossible to walk up to.

    The grid the slots come off is spaced for a plain rect; a building with a wing on it is
    wider than its slot, and two of them side by side used to end up sharing ground, which
    is a broken room rather than a tight street. Everything is measured off `bounds`, whose
    middle is not the building's own (x, y) once it has a wing: overlap resolved off the
    rect centres moved a pair the wrong way as often as not, which is how two Ls stayed
    interlocked however many passes ran. Each pass shoves the one further from the plaza,
    so the settlement spreads outward instead of the layout shifting off centre."""
    for _ in range(c.Villages.SEPARATE_PASSES):
        # The plaza is settled first and re-settled every pass: shoving one house off its
        # neighbour can put it back over the square, and both shoves point outward, so
        # taking them in turn settles rather than fighting.
        moved = any([_clear_of_plaza(building, center) for building in buildings])
        order = sorted(buildings, key=lambda b: math.hypot(b.x - center[0], b.y - center[1]))
        for i, first in enumerate(order):
            for second in order[i + 1 :]:
                a, b = first.bounds.inflate(gap, gap), second.bounds
                if not a.colliderect(b):
                    continue
                dx = b.centerx - a.centerx
                dy = b.centery - a.centery
                overlap_x = (a.width + b.width) / 2 - abs(dx)
                overlap_y = (a.height + b.height) / 2 - abs(dy)
                if overlap_x <= overlap_y:
                    second.x += round(math.copysign(overlap_x, dx or (second.x - first.x) or 1.0))
                else:
                    second.y += round(math.copysign(overlap_y, dy or (second.y - first.y) or 1.0))
                second.reset_geometry()
                moved = True
        if not moved:
            return


def _build(x, y, chunk, size: str, composition: dict, rng: random.Random) -> tuple[Village, list[Building]]:
    kinds = _building_kinds(composition, rng)
    slots = _plaza_slots(len(kinds), rng)
    buildings = []
    for kind, (ox, oy) in zip(kinds, slots):
        building = Building(round(x + ox), round(y + oy), kind, facing=_facing_towards_plaza(ox, oy))
        buildings.append(building)
    _separate(buildings, (x, y))

    radius = round(max((math.hypot(b.x - x, b.y - y) for b in buildings), default=0) + c.Villages.SLOT_W / 2)
    extent_x = round(
        max((max(abs(b.bounds.left - x), abs(b.bounds.right - x)) for b in buildings), default=c.Villages.PLAZA_RADIUS)
    )
    extent_y = round(
        max((max(abs(b.bounds.top - y), abs(b.bounds.bottom - y)) for b in buildings), default=c.Villages.PLAZA_RADIUS)
    )
    return Village(x, y, chunk, size, radius, extent_x, extent_y), buildings


def generate_village(x, y, chunk: tuple[int, int]) -> tuple[Village, list[Building]]:
    """Lay out the village that chunk (cx, cy) offers. Called once, the first time the
    player walks into range; after that the result lives in the save like the starting town."""
    rng = random.Random(f"village-layout:{chunk[0]},{chunk[1]}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS)
    size = rng.choices(sizes, weights=weights)[0]
    return _build(x, y, chunk, size, c.Villages.COMPOSITION[size], rng)


def generate_starting_world() -> tuple[Village, list[Building]]:
    """The village the player starts next to, plus the ruined landmark standing alone out
    in the settled ring. Rolled fresh per new game rather than seeded, so two playthroughs
    don't open on the same town."""
    center = c.World.WORLD_SIZE // 2
    angle = random.uniform(0, 2 * math.pi)
    distance = c.Villages.START_DISTANCE_FROM_CENTER
    x = round(center + math.cos(angle) * distance)
    y = round(center + math.sin(angle) * distance)
    chunk = (int(x // c.World.CHUNK_SIZE), int(y // c.World.CHUNK_SIZE))
    village, buildings = _build(x, y, chunk, "town", c.Villages.START_COMPOSITION, random.Random())

    landmark = _place_landmark(village, buildings)
    if landmark is not None:
        buildings.append(landmark)
    return village, buildings


def _place_landmark(village: Village, buildings: list[Building]) -> Building | None:
    """The ancient ruin: out on the far side of the settled ring, well clear of the village
    and a long way from the spawn point, since its guardian is a boss and shouldn't be
    waiting on the doorstep (Boss.MIN_DIST_FROM_START, the floor under every boss rather
    than the ordinary building clearance)."""
    center = c.World.WORLD_SIZE // 2
    margin = c.Buildings.EDGE_MARGIN
    for _ in range(120):
        x = random.randint(margin, c.World.WORLD_SIZE - margin)
        y = random.randint(margin, c.World.WORLD_SIZE - margin)
        if math.hypot(x - center, y - center) < c.Boss.MIN_DIST_FROM_START:
            continue
        if village.distance_to_point((x, y)) < village.grounds_radius + c.Buildings.MIN_GAP:
            continue
        candidate = Building(x, y, "landmark")
        gap = c.Buildings.MIN_GAP
        if any(candidate.bounds.inflate(gap * 2, gap * 2).colliderect(other.bounds) for other in buildings):
            continue
        return candidate
    return None
