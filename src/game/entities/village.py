from __future__ import annotations

import math
import random
from itertools import pairwise
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.damage_fx import draw_cracks
from game.entities.buildings import Building
from game.entities.village_layout import grounds_reach, tier_for
from game.entities.village_sites import site_grounds_radius
from game.entities.village_streets import StreetGrid, taper_from_gate, walk_lane

if TYPE_CHECKING:
    from core.camera import Camera


def _wall_piece(mid: tuple, along_x: bool, offset: float, length: float, depth: float) -> pygame.Rect:
    """A block of wall `length` long, `offset` along its side of the ring from the gateway
    in the middle of it. `mid` is that gateway and `along_x` which way the side runs."""
    rect = pygame.Rect(0, 0, round(length), round(depth)) if along_x else pygame.Rect(0, 0, round(depth), round(length))
    rect.center = (round(mid[0] + offset), round(mid[1])) if along_x else (round(mid[0]), round(mid[1] + offset))
    return rect


def _point_to_segment(x, y, start, end) -> float:
    """How far (x, y) lies off the segment `start`-`end`. A leaf is a plank on a hinge, so
    what it stands in the way of is measured from its line rather than from a box round it:
    a box round a leaf halfway open covers most of the gateway it is halfway out of."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    span = dx * dx + dy * dy
    if span <= 0.0:
        return math.hypot(x - start[0], y - start[1])
    t = max(0.0, min(1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / span))
    return math.hypot(x - (start[0] + t * dx), y - (start[1] + t * dy))


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
        # The lanes between the houses, laid by `plan_streets` from the buildings once the
        # world holds them: one lane per tuple, as the corners it turns and the width it has
        # at each. Session-only: the buildings they are worn between are saved, so the same
        # streets come back with them.
        self.streets: tuple = ()
        # The lanes walked into points and bucketed on a grid, built the first time anything
        # asks what is standing on one (`street_at`) and dropped whenever they are laid
        # again.
        self._lane_cells: dict | None = None
        # How well defended this one is, rolled once from how far out it stands and how big
        # it is, then persisted like the wall itself. Everything that differs between a
        # border hamlet and a deep wilds town reads this and nothing else.
        self.tier = tier_for(x, y, size) if tier is None else int(tier)
        # Whether this one stands a wall, which is its tier and no longer its size: what
        # buys a palisade is the walk out, so a hamlet in the deep wilds has one and the
        # village next to the starting town does not. Persisted, like everything else about
        # a village: the wall is part of what the place is, not something rederived.
        self.defended = self.tier >= c.Villages.WALL_TIER
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
        # And shut for the night, which is a different thing: the leaves are closed but no
        # beam is across them, so anyone on either side works one open with a press
        # (`push_open`) and walks through. Set every frame from the clock by
        # `World._work_gates`, so it is never saved.
        self.shut_for_night = False
        self.gate_broken: set[int] = set()
        self.gate_hp: dict[int, int] = {}
        # How far each leaf has actually swung, 0 shut and 1 wide open, and how long a gate
        # somebody has been let through still stands open for. Both session-only: a gate's
        # position is drawn from `barred`, which is itself worked out afresh every frame.
        self.gate_frac: dict[int, float] = {}
        self.gate_hold: dict[int, float] = {}
        # How much of the going-over animation a gate just beaten down has left to play.
        # Session-only for the same reason: a gate broken in an earlier session comes back
        # already lying flat, which is exactly what `gate_broken` says.
        self.gate_falling: dict[int, float] = {}
        self._defences = None
        # The worn patches round the plaza, rolled on first draw (`_trodden_earth`).
        self._earth: tuple | None = None
        # What is pinned to the board on the plaza rim, and when it was last pinned there
        # (`WorldSocial.board_offers`). Session-only, like the lanes: a notice nobody took
        # is not something a save has to carry, and the board is re-read on the next visit.
        self.notices: list = []
        self.notices_rolled_at: float = 0.0
        # Where the board stands, rolled once (`board_pos`). Kept because collision asks for
        # it on every mover's frame and a seeded Random per call is not free.
        self._board_pos: tuple[float, float] | None = None

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

    def board_pos(self) -> tuple[float, float]:
        """Where this settlement's notice board stands: on the rim of its own plaza, in a
        direction rolled off the village so the same town always has it in the same corner
        and a street is worth learning. Never in the middle, which is the well's."""
        if self._board_pos is None:
            rng = random.Random(f"board:{self.chunk[0]},{self.chunk[1]}")
            angle = rng.uniform(0, 2 * math.pi)
            reach = c.Villages.PLAZA_RADIUS * c.Board.PLAZA_FRACTION
            self._board_pos = (
                self.x + math.cos(angle) * reach,
                self.y + math.sin(angle) * reach * c.Villages.PLAZA_SQUASH,
            )
        return self._board_pos

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    @property
    def grounds_radius(self) -> float:
        """How far this settlement's grounds reach (`village_layout.grounds_reach`)."""
        return grounds_reach(self.radius, self.extent_x, self.extent_y, self.tier)

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

            for side in (-1, 1):
                walls.append(_wall_piece(mid, along_x, side * (gate / 2 + run / 2), run, thickness))
                # The gatehouse: the wall thickened where it meets the gateway, so a gate
                # reads as a way through something rather than a hole in a fence. Solid like
                # the rest, which is all navigation needs to know about it.
                walls.append(_wall_piece(mid, along_x, side * (gate / 2 + house / 2), house, thickness * 2.0))
                if self.tier >= c.Villages.SPIKE_TIER:
                    spikes.extend(self._stakes(mid, (nx, ny), along_x, side, gate, run))
                if self.tier >= c.Villages.DITCH_TIER:
                    trench = _wall_piece(mid, along_x, side * (gate / 2 + run / 2), run, c.Villages.DITCH_WIDTH)
                    trench.center = (
                        trench.centerx + nx * c.Villages.DITCH_OFFSET,
                        trench.centery + ny * c.Villages.DITCH_OFFSET,
                    )
                    ditch.append(trench)
            leaf = _wall_piece(mid, along_x, 0, gate, thickness)
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
        A gate is shut either because the settlement wants somebody out (`barred`) or
        because it is night (`shut_for_night`); the difference is not in the leaf but in
        what it takes to move it, which is `push_open` against `lift_bar`. A broken one
        never shuts again."""
        return (self.barred or self.shut_for_night) and index not in self.gate_broken

    def gate_ajar(self, index: int) -> bool:
        """Whether this gateway is being held open for somebody. A barred gate is still a
        wall to everything that collides with it; this is only ever true of a gate one of
        the settlement's own people is walking through (`World.pass_gate_for`)."""
        return self.gate_hold.get(index, 0.0) > 0.0

    def lift_bar(self, index: int):
        """The player heaving the beam up from the inside. The same held-open gate its own
        people walk through (`let_through`), held longer: the bar is off, the leaves swing,
        and it drops back into place a moment later.

        This is the way out of a town that has shut itself, and the reason breaking a gate is
        no longer the only one. It is slow to earn (`Game._lift_gate`) rather than slow to
        use: a beam is either up or it is not."""
        self.hold_open(index, c.Villages.GATE_LIFT_HOLD_MS)

    def push_open(self, index: int):
        """A gate shut for the night, shouldered open. No beam is across it, so this is one
        press rather than the hold a bar takes: the cost of a curfew is a beat at the gate,
        not a way in that has to be earned."""
        self.hold_open(index, c.Villages.GATE_LIFT_HOLD_MS)

    def let_through(self, index: int):
        """Work a shut gate open for a moment. Its people know their own gate: they lift the
        bar, walk out, and it shuts behind them, which is why the player hammering on the far
        side of a *barred* one is still shut out."""
        self.hold_open(index, c.Villages.GATE_HOLD_MS)

    def hold_open(self, index: int, ms: float):
        """Hold one shut gateway open for `ms`, whoever is walking through it. The one place
        a leaf is ever worked against what the settlement wants, so a bar lifted, a villager
        let through and a night gate shouldered aside are three labels on one act."""
        if self.gate_closed(index):
            self.gate_hold[index] = ms

    def advance_gates(self, dt, listener=None):
        """Carry every leaf one frame towards where it should be standing.

        `gate_closed` flips the instant a settlement turns and this is the leaf catching up
        with it, so it is the leaf and not the intention that is walked into
        (`gate_leaf_hit`). A gate that shuts on the frame it is barred is a wall appearing
        out of nothing; one that swings is a gate.

        Opening is heavy and shutting is heavier still, and the leaf lands with a thud: which of the
        two is happening is something the player should be able to hear from the street.
        `listener` is where they are standing, so a town over the hill shuts up quietly.
        """
        for index in range(len(self.defences()["gates"])):
            if self.gate_falling.get(index, 0.0) > 0.0:
                self.gate_falling[index] -= dt
            if self.gate_hold.get(index, 0.0) > 0.0:
                self.gate_hold[index] -= dt
            shut = self.gate_closed(index) and not self.gate_ajar(index)
            frac = self.gate_frac.get(index, 0.0 if shut else 1.0)
            step = dt / (c.Villages.GATE_CLOSE_MS if shut else c.Villages.GATE_SWING_MS)
            moved = max(0.0, frac - step) if shut else min(1.0, frac + step)
            self.gate_frac[index] = moved
            if shut and frac > 0.0 and moved <= 0.0 and self._within_earshot(index, listener):
                play_sound("gate_close")

    def _within_earshot(self, index: int, listener) -> bool:
        """Whether whoever is listening is close enough to this gateway to hear it work."""
        if listener is None:
            return False
        gate = self.defences()["gates"][index]["rect"]
        return math.hypot(listener[0] - gate.centerx, listener[1] - gate.centery) < c.Villages.GATE_SOUND_RANGE

    def gate_fall_progress(self, index: int) -> float:
        """How far through going over a just-broken gate is, 0 the moment it gave and 1 once
        there is nothing left standing in the gateway."""
        left = self.gate_falling.get(index, 0.0)
        if left <= 0.0:
            return 1.0
        return 1.0 - left / c.Villages.GATE_BREAK_MS

    def gate_open_frac(self, index: int) -> float:
        """How far this gate is drawn open, 0 to 1."""
        return self.gate_frac.get(index, 0.0 if self.gate_closed(index) else 1.0)

    def gate_leaves(self, index: int) -> list[dict]:
        """Where this gateway's two leaves actually are this frame: each one's hinge, the
        pair of axes it is written in (`axis` along the gateway from the hinge inwards,
        `normal` into the settlement), how far it has swung off the gateway's line, and how
        long and how thick it is.

        The one account of where a leaf is standing. It is what the leaves are drawn from
        and what they are collided against, so a gate halfway shut on screen is halfway shut
        to walk into as well."""
        gate = self.defences()["gates"][index]
        gx, gy = gate["pos"]
        along_x = gate["along_x"]
        leaf = gate["rect"]
        half = c.Villages.GATE_WIDTH / 2
        thickness = leaf.height if along_x else leaf.width
        theta = math.radians(c.Villages.GATE_SWING_DEG) * self.gate_open_frac(index)
        # Both leaves swing back into the settlement, so an open gateway reads as a way
        # through from either side of the wall rather than as a leaf lying across one.
        toward_middle = math.copysign(1.0, (self.y - gy) if along_x else (self.x - gx))
        normal = (0.0, toward_middle) if along_x else (toward_middle, 0.0)
        if index in self.gate_broken:
            # Going over rather than swinging: the leaves are kicked the other way, outward
            # off their hinges, shrinking as they go flat. Not the same picture as opening,
            # which is the whole point of working it out at all.
            falling = self.gate_fall_progress(index)
            theta = -math.radians(c.Villages.GATE_BREAK_DEG) * falling
            thickness *= 1.0 - falling * 0.55
            half *= 1.0 - falling * 0.25
        leaves = []
        for side in (-1, 1):
            hinge = (gx + side * half, gy) if along_x else (gx, gy + side * half)
            axis = (-side, 0.0) if along_x else (0.0, -side)
            leaves.append(
                {
                    "hinge": hinge,
                    "axis": axis,
                    "normal": normal,
                    "theta": theta,
                    "length": half,
                    "thickness": thickness,
                }
            )
        return leaves

    def gate_leaf_hit(self, index: int, x, y, radius: float) -> bool:
        """Whether a body of `radius` standing at (x, y) is up against one of this gateway's
        leaves, where the leaves are now rather than where the gate wants them.

        `gate_closed` flips on the frame a settlement bars itself or the light goes, and the
        leaves are still out in the gateway swinging towards each other. What is walked into
        is the plank, not the intention: until the two of them meet, the gap between them is
        a gap, and until they are folded back a gate reported open is still in the way."""
        if index in self.gate_broken:
            # Beaten down: the leaves are off their hinges and the gateway is a hole.
            return False
        if self.gate_open_frac(index) >= c.Villages.GATE_LEAF_CLEAR:
            # Folded right back against the inside of its own wall, which is already solid.
            return False
        for leaf in self.gate_leaves(index):
            hinge, (ax, ay), (nx, ny) = leaf["hinge"], leaf["axis"], leaf["normal"]
            reach = leaf["length"]
            cos, sin = math.cos(leaf["theta"]), math.sin(leaf["theta"])
            tip = (
                hinge[0] + (ax * cos + nx * sin) * reach,
                hinge[1] + (ay * cos + ny * sin) * reach,
            )
            if _point_to_segment(x, y, hinge, tip) < radius + leaf["thickness"] / 2:
                return True
        return False

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
        self.gate_falling[index] = c.Villages.GATE_BREAK_MS
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
        """The well in the middle of the plaza and the notice board on its rim are solid, and
        so is the wall around a walled town, its towers and whatever of a gate's leaves
        stands in the gateway; everything else in a village is a building, collided against
        by the buildings themselves."""
        if math.hypot(self.x - x, self.y - y) < c.Villages.WELL_RADIUS + radius:
            return True
        bx, by = self.board_pos()
        if math.hypot(bx - x, by - y) < c.Board.BLOCK_RADIUS + radius:
            return True
        if not self.defended:
            return False
        defences = self.defences()
        for tower in defences["towers"]:
            if math.hypot(tower[0] - x, tower[1] - y) < self.tower_radius + radius:
                return True
        for index in range(len(defences["gates"])):
            if self.gate_leaf_hit(index, x, y, radius):
                return True
        for wall in defences["walls"]:
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

    def street_reach(self) -> float:
        """How far out the settlement's own lanes run: to where a road arriving from the
        next village stops.

        A road is aimed at the grounds of a settlement that may not have been built yet, so
        it stops at the worst case its site could have reached (`site_grounds_radius`) while
        the gate stands at the real wall, which is nearer in. The village closes that gap
        from its own side rather than the road guessing at extents it cannot know."""
        return max(self.grounds_radius, site_grounds_radius(*self.chunk))

    def gateways(self) -> tuple[tuple[float, float, float], ...]:
        """Where the roads from the neighbouring settlements stop outside this one and how
        wide each is there, which is where and what its own lanes have to reach for the two
        to read as one thing.

        Only the sides a road actually arrives on: a lane run out of every gate whether
        anything met it or not left four stubs of packed earth trailing off into the grass.
        Which gate each one belongs to is not decided here, since the lane back in is found
        rather than laid (`StreetGrid`) and the way in is through the nearest gateway."""
        # Imported here rather than at the top: the roads are laid out from the settlement
        # sites this file owns, so terrain.py is the half of the pair that imports first.
        from game.entities.terrain import road_ends_at

        return road_ends_at(self.x, self.y, *self.chunk)

    def plan_streets(self, buildings: list[Building]):
        """Wear the lanes between the houses: one from the plaza out to every front door,
        one out through every gate to where the road from the next village stops, plus the
        ring round the square they all leave from.

        A lane is routed round the buildings rather than run straight at the door
        (`StreetGrid`): the straight line the lanes used to be was laid over whatever house
        stood between the plaza and the door it was going to, which read as a street running
        through somebody's front room. Every lane is walked back off one cost fill from the
        plaza and they are all worked out in the same pass (`StreetGrid.trace`), so where two
        of them share ground they are the same stretch of it: what is laid down is a trunk
        with branches off it rather than a spoke per door.

        Kept as the few corners each lane turns rather than as a line of blobs: laid blob by
        blob a lane was a string of beads with a scalloped edge, which is not what trodden
        earth looks like however closely the beads are strung. Each corner carries the width
        the lane has there, which is what a lane out of a gate is tapered by and what the
        drawing reads its colour and its verge off (`_lane_look`).

        Held on the village for the session rather than saved, and worked out from where the
        buildings actually ended up rather than from the slot grid they started on: the
        buildings are in the save, so the same lanes come back with them. Drawn here rather
        than generated into a chunk's scenery because a street belongs to the settlement and
        reaches into whichever chunks it likes, and nothing solid grows on village grounds
        for it to have to be kept clear of anyway."""
        width = float(c.Villages.STREET_WIDTH)
        lanes: list[tuple] = []
        # Every lane leaves from the edge of the plaza itself rather than from a circle
        # drawn round it: a ring laid outside the square left a hoop of untrodden grass
        # between the two.
        rim, squash = c.Villages.PLAZA_RADIUS, c.Villages.PLAZA_SQUASH

        def on_rim(angle: float) -> tuple[float, float]:
            return self.x + math.cos(angle) * rim, self.y + math.sin(angle) * rim * squash

        grid = StreetGrid(self, buildings)
        doors = [b.door_front() for b in buildings if b.has_door]
        gates = self.gateways()
        routes = grid.trace([*doors, *[(gx, gy) for gx, gy, _ in gates]])
        # A stretch two lanes share is one stretch of earth: laid once, whichever of them
        # was asked for it first.
        laid = set()
        for i, door in enumerate(doors):
            # Nothing found its way in: the lane it always had, straight at the plaza.
            stretches = routes.get(i) or [[door, on_rim(math.atan2(door[1] - self.y, door[0] - self.x))]]
            for stretch in stretches:
                lane = tuple((x, y, width) for x, y in stretch)
                if lane not in laid:
                    laid.add(lane)
                    lanes.append(lane)
        for j, (_end_x, _end_y, road_width) in enumerate(gates):
            # No fallback out here: a lane that could not find a gateway would be laid
            # through the wall, and a road stopping at the ditch says more than that.
            stretches = routes.get(len(doors) + j)
            if stretches is not None:
                route = [point for k, stretch in enumerate(stretches) for point in stretch[k > 0 :]]
                lanes.append(taper_from_gate(route, road_width))
        step = c.Villages.STREET_STEP
        ring = [on_rim(i * step / rim) for i in range(int(2 * math.pi * rim // step) + 1)]
        lanes.append(tuple((x, y, width) for x, y in ring))
        self.streets = tuple(lanes)
        self._lane_cells = None

    def street_at(self, x: float, y: float, margin: float = 0.0) -> bool:
        """Whether (x, y) stands on the settlement's trodden earth: one of its lanes, or the
        plaza they all leave from. The grounds are the whole place, this is the ground the
        place is actually walked on, which is what the wilderness has to keep off.

        The lanes of a town are a few hundred paces of earth and this is asked once per tuft
        of grass in every chunk around it, so they are walked once into points on a grid
        whose cell is as wide as the widest reach anything asks about: the answer is always
        in the nine cells around the point."""
        if not self.streets:
            return False
        reach = c.Villages.STREET_WIDTH + margin
        rx = c.Villages.PLAZA_RADIUS + reach
        ry = c.Villages.PLAZA_RADIUS * c.Villages.PLAZA_SQUASH + reach
        if ((x - self.x) / rx) ** 2 + ((y - self.y) / ry) ** 2 < 1:
            return True
        cell = self._lane_cell()
        if self._lane_cells is None:
            self._lane_cells = {}
            for lane in self.streets:
                for lx, ly, lw in walk_lane(lane, c.Villages.STREET_STEP):
                    self._lane_cells.setdefault((int(lx // cell), int(ly // cell)), []).append((lx, ly, lw))
        gx, gy = int(x // cell), int(y // cell)
        return any(
            math.hypot(x - lx, y - ly) < lw + margin
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for lx, ly, lw in self._lane_cells.get((gx + dx, gy + dy), ())
        )

    @staticmethod
    def _lane_cell() -> int:
        """The grid `street_at` buckets the lanes on: as wide as the widest reach anything
        asks about, which is what makes the nine cells round a point the whole search. A lane
        out of a gate is worn to the width of the road arriving there, so that is the widest
        anything on this ground ever is."""
        return max(c.Villages.STREET_WIDTH, c.Scenery.ROAD_WIDTH[1]) + c.Scenery.STREET_CLEARANCE

    @staticmethod
    def _lane_look(width: float, edge: bool) -> tuple[tuple, float]:
        """What a lane looks like where it is this wide, as the colour and how far out it
        reaches. A lane is trodden earth, a road is wider, lighter and verged, and the one
        worn out of a gate is both at either end of it: the whole look follows the one
        number that already tapers, so the two tracks never meet as a step."""
        narrow, widest = c.Villages.STREET_WIDTH, c.Scenery.ROAD_WIDTH[1]
        blend = max(0.0, min(1.0, (width - narrow) / max(1.0, widest - narrow)))
        near, far = (
            (c.Villages.STREET_EDGE_COLOR, c.Scenery.ROAD_VERGE_COLOR)
            if edge
            else (c.Villages.PLAZA_COLOR, c.Scenery.ROAD_MAIN_COLOR)
        )
        color = tuple(round(a + (b - a) * blend) for a, b in zip(near, far, strict=True))
        if not edge:
            return color, width
        return color, width + c.Villages.STREET_EDGE + (c.Scenery.ROAD_VERGE - c.Villages.STREET_EDGE) * blend

    def _draw_streets(self, screen: pygame.Surface, camera: Camera):
        """A settlement's lanes, as one connected surface in two passes over the whole
        network: the worn edge under, then the trodden earth over it. Two passes and not two
        per stretch, for the reason a road's verge is a kind of its own
        (`Scenery._draw_path`): a stretch that drew both painted its own edge over the middle
        of the one before it.

        Only what is on screen is drawn, the same rule everything else in the world is drawn
        by, and the camera offset is asked for once: a town's lanes are the one loop here
        long enough for the call itself to cost something."""
        view = screen.get_rect().inflate(c.Scenery.ROAD_WIDTH[1] * 4, c.Scenery.ROAD_WIDTH[1] * 4)
        ox, oy = camera.world_to_screen(0, 0)
        stretches = []
        for lane in self.streets:
            for (ax, ay, aw), (bx, by, bw) in pairwise(lane):
                start = (round(ax + ox), round(ay + oy))
                end = (round(bx + ox), round(by + oy))
                if view.clipline(start, end):
                    stretches.append((start, end, (aw + bw) / 2))
        for edge in (True, False):
            for start, end, width in stretches:
                color, reach = self._lane_look(width, edge)
                pygame.draw.line(screen, color, start, end, max(2, round(reach * 2)))
                # The joints rounded off, so a lane turning a corner is worn round it rather
                # than mitred like something laid out with a rule.
                pygame.draw.circle(screen, color, start, round(reach))
                pygame.draw.circle(screen, color, end, round(reach))

    def _trodden_earth(self) -> tuple:
        """The worn patches round the edge of the plaza, as offsets from the middle of it.
        Rolled once from the village's position, so they hold still as the camera pans and
        the roll is not made again every frame."""
        if self._earth is not None:
            return self._earth
        rng = random.Random(f"plaza:{self.x},{self.y}")
        width = c.Villages.PLAZA_RADIUS * 2
        height = round(c.Villages.PLAZA_RADIUS * 2 * c.Villages.PLAZA_SQUASH)
        blobs = []
        for _ in range(14):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(0.4, 1.0)
            blobs.append((math.cos(angle) * width / 2 * dist, math.sin(angle) * height / 2 * dist, rng.randint(4, 11)))
        self._earth = tuple(blobs)
        return self._earth

    def draw(self, screen: pygame.Surface, camera: Camera, darkness: float = 0.0):
        """The plaza: packed earth and a well. The name is the minimap strip's job; written on
        the ground it was one more label lying over the street.

        `darkness` is the sky (`DayNightCycle.darkness`): the only thing about a village that
        is drawn differently after dark is the fire on its wall, and a fire is worth nothing
        at noon."""
        self._draw_streets(screen, camera)
        cx, cy = camera.world_to_screen(self.x, self.y)
        rim = c.Villages.PLAZA_RADIUS
        plaza = pygame.Rect(0, 0, rim * 2, round(rim * 2 * c.Villages.PLAZA_SQUASH))
        plaza.center = (round(cx), round(cy))
        pygame.draw.ellipse(screen, c.Villages.PLAZA_COLOR, plaza)

        darker = tuple(round(v * 0.88) for v in c.Villages.PLAZA_COLOR)
        for dx, dy, radius in self._trodden_earth():
            pygame.draw.circle(screen, darker, (round(cx + dx), round(cy + dy)), radius)

        self._draw_well(screen, (round(cx), round(cy)))
        self._draw_board(screen, camera)
        self._draw_defences(screen, camera, darkness)

    def _draw_defences(self, screen: pygame.Surface, camera: Camera, darkness: float = 0.0):
        """The wall and everything that belongs to it, drawn under whatever walks over the
        ground. A palisade is a row of sharpened logs, a stone wall is coursed blocks: the
        material is how far out the settlement stands, read before anything is fought.

        A town's wall stands further out than the screen is wide, so most of what is here is
        somewhere behind the player: every piece is measured against the view before it is
        drawn, and a stretch of wall lays only the courses actually in it."""
        defences = self.defences()
        if not defences["walls"]:
            return
        view = screen.get_rect()
        offset = camera.world_to_screen(0, 0)
        self._draw_ditch(screen, view, offset, defences["ditch"])
        self._draw_wall(screen, view, offset, defences["walls"])
        self._draw_spikes(screen, view, offset, defences["spikes"])
        self._draw_gateways(screen, camera, view, offset, defences["gates"], darkness)
        self._draw_towers(screen, view, offset, defences["towers"], darkness)

    @staticmethod
    def _draw_ditch(screen: pygame.Surface, view: pygame.Rect, offset, trenches):
        """A lip of turned earth round the edge and a darker floor, so a ditch reads as
        something dug rather than as a shadow lying on the grass."""
        ox, oy = offset
        for trench in trenches:
            rect = pygame.Rect(round(trench.left + ox), round(trench.top + oy), trench.width, trench.height)
            if not view.colliderect(rect):
                continue
            pygame.draw.rect(screen, (104, 88, 62), rect)
            pygame.draw.rect(screen, c.Villages.DITCH_COLOR, rect.inflate(-10, -10))
            pygame.draw.rect(screen, (56, 46, 32), rect.inflate(-26, -26))

    def _draw_wall(self, screen: pygame.Surface, view: pygame.Rect, offset, walls):
        """The wall itself, coursed. Only the courses standing in the view: a wall runs the
        length of the town and the screen holds a fraction of it."""
        ox, oy = offset
        stone = self.wall_style == "stone"
        body = c.Villages.WALL_STONE if stone else c.Villages.WALL_COLOR
        top = c.Villages.WALL_STONE_TOP if stone else c.Villages.WALL_TOP
        edge = (78, 76, 70) if stone else (68, 52, 34)
        for wall in walls:
            rect = pygame.Rect(round(wall.left + ox), round(wall.top + oy), wall.width, wall.height)
            if not view.colliderect(rect):
                continue
            pygame.draw.rect(screen, body, rect)
            along_x = rect.width > rect.height
            span = rect.width if along_x else rect.height
            step = 18 if stone else 14
            seen = view.clip(rect)
            start = (seen.left - rect.left) if along_x else (seen.top - rect.top)
            stop = (seen.right - rect.left) if along_x else (seen.bottom - rect.top)
            # Kept on the same 4-then-every-`step` grid the whole wall is coursed on, so a
            # block sits where it would have whichever end of the wall is on screen.
            first = 4 + max(0, (start - 4) // step) * step
            for offset_along in range(first, min(max(5, span - 4), stop + step), step):
                block = (
                    pygame.Rect(rect.left + offset_along, rect.top, step - 4, rect.height)
                    if along_x
                    else pygame.Rect(rect.left, rect.top + offset_along, rect.width, step - 4)
                )
                pygame.draw.rect(screen, top, block)
                pygame.draw.rect(screen, edge, block, 1)
            pygame.draw.rect(screen, edge, rect, 2)

    @staticmethod
    def _draw_spikes(screen: pygame.Surface, view: pygame.Rect, offset, spikes):
        """The stakes planted outside the wall. Each is drawn from its base upwards, so one
        planted below the screen still has its point on it: the margin goes the way the
        stake does."""
        ox, oy = offset
        length = c.Villages.SPIKE_LENGTH
        left, top_edge, right, bottom = view.left - 8, view.top - 8, view.right + 8, view.bottom + length
        for sx, sy in spikes:
            px, py = sx + ox, sy + oy
            if not (left <= px <= right and top_edge <= py <= bottom):
                continue
            base = (round(px), round(py))
            pygame.draw.circle(screen, (52, 42, 30), base, 6)
            pygame.draw.line(screen, (62, 48, 32), base, (base[0], base[1] - length), 8)
            pygame.draw.line(screen, c.Villages.SPIKE_COLOR, base, (base[0], base[1] - length), 5)
            # The point, catching the light: a stake read from above is a pale tip.
            pygame.draw.line(screen, (238, 230, 210), (base[0], base[1] - length), (base[0], base[1] - length + 6), 3)

    def _draw_gateways(self, screen: pygame.Surface, camera: Camera, view: pygame.Rect, offset, gates, darkness):
        """Each gateway with whatever its tier hangs and lights beside it. A gateway is drawn
        from its middle out, so it counts as on screen from a leaf's length outside the
        view."""
        ox, oy = offset
        reach = c.Villages.GATE_WIDTH
        for index, gate in enumerate(gates):
            gx, gy = gate["pos"]
            if (
                abs(gx + ox - view.centerx) > view.width / 2 + reach
                or abs(gy + oy - view.centery) > view.height / 2 + reach
            ):
                continue
            self._draw_gate(screen, camera, index, gate)
            if self.tier >= c.Villages.BANNER_TIER:
                self._draw_banners(screen, (gx + ox, gy + oy), gate["along_x"])
            if self.tier >= c.Villages.BRAZIER_TIER:
                # Standing in front of the two gatehouses rather than in the gateway: a
                # fire in the middle of the way through is a fire in everybody's way, and it
                # would be drawn over the leaves it is meant to light.
                out = self.wall_thickness / 2 + 20
                away = math.copysign(1.0, (gy - self.y) if gate["along_x"] else (gx - self.x))
                for side in (-1, 1):
                    shift = side * (c.Villages.GATE_WIDTH / 2 + c.Villages.GATEHOUSE / 2)
                    if gate["along_x"]:
                        spot = (gx + shift + ox, gy + away * out + oy)
                    else:
                        spot = (gx + away * out + ox, gy + shift + oy)
                    self._draw_brazier(screen, spot, darkness)

    def _draw_towers(self, screen: pygame.Surface, view: pygame.Rect, offset, towers, darkness):
        """The corner drums, read from above as a rim of crenellations. A bigger drum carries
        more of them rather than the same eight stretched round it, which is most of what
        makes a tier 2 tower read as heavier and not merely nearer."""
        ox, oy = offset
        radius = self.tower_radius
        for tx, ty in towers:
            sx, sy = tx + ox, ty + oy
            tower = pygame.Rect(round(sx - radius - 4), round(sy - radius - 4), radius * 2 + 8, radius * 2 + 8)
            if not view.colliderect(tower):
                continue
            pygame.draw.circle(screen, (60, 52, 44), (round(sx), round(sy)), radius + 3)
            pygame.draw.circle(screen, c.Villages.TOWER_STONE, (round(sx), round(sy)), radius)
            pygame.draw.circle(screen, (104, 100, 94), (round(sx), round(sy)), round(radius * 0.6))
            merlons = 8 if radius < 60 else 12
            for i in range(merlons):
                angle = 2 * math.pi * i / merlons
                block = pygame.Rect(0, 0, 14, 14)
                block.center = (round(sx + math.cos(angle) * radius), round(sy + math.sin(angle) * radius))
                pygame.draw.rect(screen, (168, 164, 156), block)
                pygame.draw.rect(screen, (70, 66, 60), block, 1)
            if self.tier >= c.Villages.BRAZIER_TIER:
                self._draw_brazier(screen, (sx, sy), darkness)

    def _draw_banners(self, screen: pygame.Surface, center, along_x: bool):
        """The settlement's colours hung either side of a gateway, from tier 1.

        Nothing but a look, and the cheapest one there is: two rectangles on the gatehouse
        say a place is kept before the player is near enough to count its guards. The colour
        is rolled off the village's own position, so a town flies the same one every time it
        is walked up to."""
        sx, sy = center
        color = c.Villages.BANNER_COLORS[hash((round(self.x), round(self.y))) % len(c.Villages.BANNER_COLORS)]
        shade = tuple(round(v * 0.7) for v in color)
        for side in (-1, 1):
            shift = side * (c.Villages.GATE_WIDTH / 2 + c.Villages.GATEHOUSE / 2)
            cx = sx + (shift if along_x else 0)
            cy = sy + (0 if along_x else shift)
            cloth = pygame.Rect(0, 0, 14, 30) if along_x else pygame.Rect(0, 0, 30, 14)
            cloth.center = (round(cx), round(cy))
            pygame.draw.rect(screen, color, cloth)
            pygame.draw.rect(screen, shade, cloth, 2)
            # The point at the bottom of a hanging banner, which is what stops it reading as
            # a crate sitting on the wall.
            tip = (cloth.centerx, cloth.bottom + 7) if along_x else (cloth.right + 7, cloth.centery)
            tail = (
                [(cloth.left, cloth.bottom), (cloth.right, cloth.bottom), tip]
                if along_x
                else [(cloth.right, cloth.top), (cloth.right, cloth.bottom), tip]
            )
            pygame.draw.polygon(screen, color, tail)

    @staticmethod
    def _draw_brazier(screen: pygame.Surface, center, darkness: float):
        """A fire in a stone bowl, standing at a gate or on a tower from tier 2.

        Drawn cold in daylight and lit as the sky goes: the glow is the one thing in a
        village that answers the clock, and a town seen across a field at night is a ring of
        embers before it is anything else."""
        sx, sy = round(center[0]), round(center[1])
        if darkness > 0.15:
            radius = c.Villages.BRAZIER_RADIUS
            glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            for step in range(4, 0, -1):
                pygame.draw.circle(
                    glow, (*c.Villages.BRAZIER_GLOW, round(16 * darkness)), (radius, radius), radius * step / 4
                )
            screen.blit(glow, (sx - radius, sy - radius))
        pygame.draw.circle(screen, (48, 44, 40), (sx, sy), 12)
        pygame.draw.circle(screen, c.Villages.BRAZIER_STONE, (sx, sy), 10)
        if darkness > 0.15:
            pygame.draw.circle(screen, (196, 76, 34), (sx, sy), 7)
            pygame.draw.circle(screen, c.Villages.BRAZIER_FLAME, (sx, sy), 4)

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

        falling = self.gate_fall_progress(index)
        if index in self.gate_broken and falling >= 1.0:
            # Beaten down and gone over: the gateway is a hole for good and there is nothing
            # left to hang.
            return

        # `fallen` only darkens the wood toward the ground it is landing on; the swing
        # itself, broken or not, is `gate_leaves`.
        fallen = falling if index in self.gate_broken else 0.0
        for leaf_at in self.gate_leaves(index):
            self._draw_leaf(
                screen,
                camera,
                leaf_at["hinge"],
                leaf_at["axis"],
                leaf_at["normal"],
                leaf_at["theta"],
                leaf_at["length"],
                leaf_at["thickness"],
                fallen=fallen,
            )

        health = self.gate_health(index)
        if health < 1.0 and self.gate_open_frac(index) < 0.05:
            leaf = gate["rect"]
            lx, ly = camera.world_to_screen(leaf.left, leaf.top)
            rect = pygame.Rect(round(lx), round(ly), leaf.width, leaf.height)
            draw_cracks(screen, rect, health, self.gate_key(index))

    @staticmethod
    def _draw_leaf(
        screen, camera: Camera, hinge, axis, normal, theta: float, length: float, thickness: float, fallen: float = 0.0
    ):
        """One leaf, hung on `hinge` and swung `theta` off the line of the gateway.

        Written in the leaf's own two axes (`axis` along the gateway from the hinge inwards,
        `normal` into the settlement) so the same few lines hang all eight leaves of a town,
        whichever of the four walls they are in and whichever way round they open.

        `fallen` is how far through going over a broken leaf is: it only darkens the wood
        toward the ground it is landing on, since the swing itself is the caller's."""
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
        shade = 1.0 - fallen * 0.5
        pygame.draw.polygon(screen, tuple(round(v * shade) for v in c.Villages.GATE_LEAF), corners)
        pygame.draw.polygon(screen, tuple(round(v * shade) for v in (46, 34, 22)), corners, 3)
        for offset in range(20, max(21, int(length)), 22):
            pygame.draw.line(screen, (66, 48, 30), point(offset, -edge), point(offset, edge), 2)

    def _draw_board(self, screen: pygame.Surface, camera: Camera):
        """The notice board on the plaza rim: two posts, a plank face and the notices pinned
        to it. Drawn as a thing standing up rather than as a mark on the ground, since it is
        the one piece of village furniture the player walks up to and reads."""
        bx, by = camera.world_to_screen(*self.board_pos())
        width, height = c.Board.BOARD_W, c.Board.BOARD_H
        # The shadow on the earth is what makes it stand up rather than lie printed on the
        # plaza: laid down first, at the foot of the posts, and left where it is.
        shadow = pygame.Surface((width + 8, 14), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 70), shadow.get_rect())
        screen.blit(shadow, (round(bx - (width + 8) / 2), round(by + 2)))
        for side in (-1, 1):
            post = pygame.Rect(0, 0, 6, c.Board.POST_HEIGHT)
            post.midtop = (round(bx + side * (width // 2 - 4)), round(by - c.Board.POST_HEIGHT + 10))
            pygame.draw.rect(screen, c.Board.POST_COLOR, post)
        face = pygame.Rect(0, 0, width, height)
        face.midbottom = (round(bx), round(by - c.Board.POST_HEIGHT + 34))
        pygame.draw.rect(screen, c.Board.BOARD_COLOR, face)
        # Planks rather than a panel: the seams are the difference between a board and a
        # slab at the distance the whole plaza is read from.
        for offset in range(face.width // 4, face.width, face.width // 4):
            seam_x = face.left + offset
            pygame.draw.line(screen, c.Board.SEAM_COLOR, (seam_x, face.top + 2), (seam_x, face.bottom - 2), 1)
        pygame.draw.rect(screen, (74, 54, 34), face, 2)
        # A shingle header over the top, overhanging both posts. Nothing else in a village
        # has this outline, which is the whole point of it.
        roof = pygame.Rect(0, 0, width + 12, c.Board.ROOF_H)
        roof.midbottom = (face.centerx, face.top + 2)
        pygame.draw.rect(screen, c.Board.ROOF_COLOR, roof, border_radius=2)
        pygame.draw.rect(screen, (46, 34, 22), roof, 1, border_radius=2)
        # A scrap of paper per notice actually pinned to it, so a board somebody has cleared
        # out reads as bare boards from across the plaza.
        for index, _notice in enumerate(self.notices[:3]):
            note = pygame.Rect(0, 0, 14, 16)
            note.topleft = (face.left + 6 + index * 18, face.top + 8 + (index % 2) * 4)
            pygame.draw.rect(screen, c.Board.NOTICE_COLOR, note)
            pygame.draw.rect(screen, (150, 142, 124), note, 1)

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
