from __future__ import annotations

import math
import random
from collections import deque
from functools import lru_cache
from itertools import pairwise
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
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
        # The lanes between the houses, laid by `plan_streets` from the buildings once the
        # world holds them. Session-only: the buildings they are worn between are saved,
        # so the same streets come back with them.
        self.streets: tuple = ()
        # How well defended this one is, rolled once from how far out it stands and how big
        # it is, then persisted like the wall itself. Everything that differs between a
        # border hamlet and a deep wilds town reads this and nothing else.
        self.tier = self._tier_for(x, y, size) if tier is None else int(tier)
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

        Nothing here is collided against: `gate_closed` flips the instant a settlement turns,
        and this is the leaf catching up with it. A gate that shuts on the frame it is barred
        is a wall appearing out of nothing; one that swings is a gate.

        Opening is quick and shutting is slow, and the leaf lands with a thud: which of the
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

    def street_reach(self) -> float:
        """How far out the settlement's own lanes run: to where a road arriving from the
        next village stops.

        A road is aimed at the grounds of a settlement that may not have been built yet, so
        it stops at the worst case its site could have reached (`site_grounds_radius`) while
        the gate stands at the real wall, which is nearer in. The village closes that gap
        from its own side rather than the road guessing at extents it cannot know."""
        return max(self.grounds_radius, site_grounds_radius(*self.chunk))

    def gateways(self) -> tuple[tuple[float, float], ...]:
        """Where the roads from the neighbouring settlements stop outside this one, which is
        where its own lanes have to reach for the two to read as one thing.

        Only the sides a road actually arrives on: a lane run out of every gate whether
        anything met it or not left four stubs of packed earth trailing off into the grass.
        Which gate each one belongs to is not decided here, since the lane back in is found
        rather than laid (`_StreetGrid`) and the way in is through the nearest gateway."""
        # Imported here rather than at the top: the roads are laid out from the settlement
        # sites this file owns, so terrain.py is the half of the pair that imports first.
        from game.entities.terrain import road_ends_at

        return road_ends_at(self.x, self.y, *self.chunk)

    def plan_streets(self, buildings: list[Building]):
        """Wear the lanes between the houses: one from the plaza out to every front door,
        one out through every gate to where the road from the next village stops, plus the
        ring round the square they all leave from.

        A lane is routed round the buildings rather than run straight at the door
        (`_StreetGrid`): the straight line the lanes used to be was laid over whatever house
        stood between the plaza and the door it was going to, which read as a street running
        through somebody's front room. Every lane is walked back off one flood fill from the
        plaza, so they join into one network on the way in instead of being a fan of spokes
        that happen to meet.

        Held on the village for the session rather than saved, and worked out from where the
        buildings actually ended up rather than from the slot grid they started on: the
        buildings are in the save, so the same lanes come back with them. Drawn here rather
        than generated into a chunk's scenery because a street belongs to the settlement and
        reaches into whichever chunks it likes, and nothing solid grows on village grounds
        for it to have to be kept clear of anyway."""
        street: list[tuple[float, float]] = []
        step = c.Villages.STREET_STEP
        # Every lane leaves from the edge of the plaza itself rather than from a circle
        # drawn round it: a ring laid outside the square left a hoop of untrodden grass
        # between the two.
        rim, squash = c.Villages.PLAZA_RADIUS, 0.75

        def on_rim(angle: float) -> tuple[float, float]:
            return self.x + math.cos(angle) * rim, self.y + math.sin(angle) * rim * squash

        def lay(route: list[tuple[float, float]]):
            for start, end in pairwise(route):
                length = math.dist(start, end)
                for i in range(int(length // step) + 1):
                    t = i * step / max(1.0, length)
                    street.append((start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t))
            street.append(route[-1])

        lanes = _StreetGrid(self, buildings)
        for building in buildings:
            if not building.has_door:
                continue
            door = building.door_front()
            # Nothing found its way in: the lane it always had, straight at the plaza.
            lay(lanes.route(door) or [door, on_rim(math.atan2(door[1] - self.y, door[0] - self.x))])
        for end in self.gateways():
            # No fallback out here: a lane that could not find a gateway would be laid
            # through the wall, and a road stopping at the ditch says more than that.
            route = lanes.route(end)
            if route is not None:
                lay(route)
        for i in range(int(2 * math.pi * rim // step) + 1):
            street.append(on_rim(i * step / rim))
        self.streets = tuple(street)

    def _draw_streets(self, screen: pygame.Surface, camera: Camera):
        """A settlement's lanes are a few hundred blobs and only the ones on screen are
        worth drawing, the same rule everything else in the world is drawn by."""
        width = c.Villages.STREET_WIDTH
        view = screen.get_rect().inflate(width * 2, width * 2)
        # The offset is asked of the camera once and added to every blob: a town's worth of
        # lanes is the one loop here long enough for the call itself to cost something.
        ox, oy = camera.world_to_screen(0, 0)
        left, top, right, bottom = view.left, view.top, view.right, view.bottom
        for x, y in self.streets:
            sx, sy = x + ox, y + oy
            if left <= sx <= right and top <= sy <= bottom:
                pygame.draw.circle(screen, c.Villages.PLAZA_COLOR, (round(sx), round(sy)), width)

    def _trodden_earth(self) -> tuple:
        """The worn patches round the edge of the plaza, as offsets from the middle of it.
        Rolled once from the village's position, so they hold still as the camera pans and
        the roll is not made again every frame."""
        if self._earth is not None:
            return self._earth
        rng = random.Random(f"plaza:{self.x},{self.y}")
        width = c.Villages.PLAZA_RADIUS * 2
        height = round(c.Villages.PLAZA_RADIUS * 1.5)
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
        plaza = pygame.Rect(0, 0, c.Villages.PLAZA_RADIUS * 2, round(c.Villages.PLAZA_RADIUS * 1.5))
        plaza.center = (round(cx), round(cy))
        pygame.draw.ellipse(screen, c.Villages.PLAZA_COLOR, plaza)

        darker = tuple(round(v * 0.88) for v in c.Villages.PLAZA_COLOR)
        for dx, dy, radius in self._trodden_earth():
            pygame.draw.circle(screen, darker, (round(cx + dx), round(cy + dy)), radius)

        self._draw_well(screen, (round(cx), round(cy)))
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

        stone = self.wall_style == "stone"
        body = c.Villages.WALL_STONE if stone else c.Villages.WALL_COLOR
        top = c.Villages.WALL_STONE_TOP if stone else c.Villages.WALL_TOP
        edge = (78, 76, 70) if stone else (68, 52, 34)
        view = screen.get_rect()
        ox, oy = camera.world_to_screen(0, 0)

        for trench in defences["ditch"]:
            rect = pygame.Rect(round(trench.left + ox), round(trench.top + oy), trench.width, trench.height)
            if not view.colliderect(rect):
                continue
            # A lip of turned earth round the edge and a darker floor, so a ditch reads as
            # something dug rather than as a shadow lying on the grass.
            pygame.draw.rect(screen, (104, 88, 62), rect)
            pygame.draw.rect(screen, c.Villages.DITCH_COLOR, rect.inflate(-10, -10))
            pygame.draw.rect(screen, (56, 46, 32), rect.inflate(-26, -26))

        for wall in defences["walls"]:
            rect = pygame.Rect(round(wall.left + ox), round(wall.top + oy), wall.width, wall.height)
            if not view.colliderect(rect):
                continue
            pygame.draw.rect(screen, body, rect)
            along_x = rect.width > rect.height
            span = rect.width if along_x else rect.height
            step = 18 if stone else 14
            # Only the courses standing in the view: a wall runs the length of the town and
            # the screen holds a fraction of it.
            seen = view.clip(rect)
            start = (seen.left - rect.left) if along_x else (seen.top - rect.top)
            stop = (seen.right - rect.left) if along_x else (seen.bottom - rect.top)
            # Kept on the same 4-then-every-`step` grid the whole wall is coursed on, so a
            # block sits where it would have whichever end of the wall is on screen.
            first = 4 + max(0, (start - 4) // step) * step
            for offset in range(first, min(max(5, span - 4), stop + step), step):
                block = (
                    pygame.Rect(rect.left + offset, rect.top, step - 4, rect.height)
                    if along_x
                    else pygame.Rect(rect.left, rect.top + offset, rect.width, step - 4)
                )
                pygame.draw.rect(screen, top, block)
                pygame.draw.rect(screen, edge, block, 1)
            pygame.draw.rect(screen, edge, rect, 2)

        length = c.Villages.SPIKE_LENGTH
        # A stake is drawn from its base upwards, so one planted below the screen still has
        # its point on it: the margin goes the way the stake does.
        left, top_edge, right, bottom = view.left - 8, view.top - 8, view.right + 8, view.bottom + length
        for sx, sy in defences["spikes"]:
            px, py = sx + ox, sy + oy
            if not (left <= px <= right and top_edge <= py <= bottom):
                continue
            base = (round(px), round(py))
            pygame.draw.circle(screen, (52, 42, 30), base, 6)
            pygame.draw.line(screen, (62, 48, 32), base, (base[0], base[1] - length), 8)
            pygame.draw.line(screen, c.Villages.SPIKE_COLOR, base, (base[0], base[1] - length), 5)
            # The point, catching the light: a stake read from above is a pale tip.
            pygame.draw.line(screen, (238, 230, 210), (base[0], base[1] - length), (base[0], base[1] - length + 6), 3)

        # A gateway is drawn from its middle out, so it counts as on screen from a leaf's
        # length outside the view.
        reach = c.Villages.GATE_WIDTH
        for index, gate in enumerate(defences["gates"]):
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

        radius = self.tower_radius
        for tx, ty in defences["towers"]:
            sx, sy = tx + ox, ty + oy
            tower = pygame.Rect(round(sx - radius - 4), round(sy - radius - 4), radius * 2 + 8, radius * 2 + 8)
            if not view.colliderect(tower):
                continue
            pygame.draw.circle(screen, (60, 52, 44), (round(sx), round(sy)), radius + 3)
            pygame.draw.circle(screen, c.Villages.TOWER_STONE, (round(sx), round(sy)), radius)
            pygame.draw.circle(screen, (104, 100, 94), (round(sx), round(sy)), round(radius * 0.6))
            # Crenellations, read from above as blocks around the rim. A bigger drum carries
            # more of them rather than the same eight stretched round it, which is most of
            # what makes a tier 2 tower read as heavier and not merely nearer.
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
            # off their hinges, shrinking as they go flat and darkening into the ground. Not
            # the same picture as opening, which is the whole point of drawing it at all.
            theta = -math.radians(c.Villages.GATE_BREAK_DEG) * falling
            thickness *= 1.0 - falling * 0.55
            half *= 1.0 - falling * 0.25
        for side in (-1, 1):
            hinge = (gx + side * half, gy) if along_x else (gx, gy + side * half)
            axis = (-side, 0.0) if along_x else (0.0, -side)
            fallen = falling if index in self.gate_broken else 0.0
            self._draw_leaf(screen, camera, hinge, axis, normal, theta, half, thickness, fallen=fallen)

        health = self.gate_health(index)
        if health < 1.0 and self.gate_open_frac(index) < 0.05:
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


# Settlements the region grid never offered, and circles nothing may be laid through, both
# registered by the world that holds them. The starting town is rolled per playthrough
# rather than out of a region, and the landmark ruin stands alone in the settled ring: both
# were invisible to everything laid out from `village_site`, which is how a road came to be
# drawn through a house, a river through a plaza and a signpost into the middle of a town.
#
# Registration is not a hole in the rule that a chunk is a pure function of its
# coordinates: it happens once, when a world is created or loaded, before a single chunk is
# generated, and every cache that answers off the sites is dropped when it does.
_registered: dict[tuple[int, int], tuple[float, float, float]] = {}
_keepouts: list[tuple[float, float, float]] = []
_SITE_CACHES: list = []


class _StreetGrid:
    """The ground inside a settlement a lane may be worn into: what the buildings and the
    wall leave free, as a grid, with the way back to the plaza already known from every
    cell of it.

    One flood fill out of the plaza answers every lane the place needs at once, which is
    what makes them read as a network: two doors on the same side of town walk back along
    the same lane instead of each wearing its own beside it. Built once per settlement and
    thrown away with the plan; nothing here is kept or saved.
    """

    def __init__(self, village: Village, buildings: list[Building]):
        self.step = c.Villages.STREET_GRID
        reach = village.street_reach() + self.step * 2
        self.origin = (village.x - reach, village.y - reach)
        self.span = int(reach * 2 // self.step) + 1
        keep = c.Villages.STREET_WIDTH
        # A lane keeps its own width off whatever it passes, so it is never drawn brushing
        # a wall. The gateways are the one gap left open: a gate leaf is not a stretch of
        # wall, which is what lets the fill find its own way out of a walled town.
        rects = [rect.inflate(keep * 2, keep * 2) for b in buildings for rect in b.footprint()]
        rects += [rect.inflate(keep, keep) for rect in village.defences()["walls"]]
        self.blocked: set[tuple[int, int]] = set()
        for rect in rects:
            self.blocked.update(self._cells_in(rect))
        self.parent = self._flood(village)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return int((x - self.origin[0]) // self.step), int((y - self.origin[1]) // self.step)

    def _point(self, cell: tuple[int, int]) -> tuple[float, float]:
        return self.origin[0] + (cell[0] + 0.5) * self.step, self.origin[1] + (cell[1] + 0.5) * self.step

    def _cells_in(self, rect: pygame.Rect):
        """Every cell of the grid standing on this rectangle."""
        left, top = self._cell(rect.left, rect.top)
        right, bottom = self._cell(rect.right, rect.bottom)
        for gx in range(left, right + 1):
            for gy in range(top, bottom + 1):
                if rect.collidepoint(self._point((gx, gy))):
                    yield gx, gy

    def _free(self, cell: tuple[int, int]) -> bool:
        return 0 <= cell[0] < self.span and 0 <= cell[1] < self.span and cell not in self.blocked

    def _flood(self, village: Village) -> dict:
        """Every cell the plaza can be walked to from, and which cell to take to get there.
        Eight ways out of a cell rather than four, so a lane running across the grain of the
        grid is a diagonal and not a staircase."""
        rim = c.Villages.PLAZA_RADIUS
        queue = deque()
        parent: dict[tuple[int, int], tuple[int, int] | None] = {}
        plaza = pygame.Rect(0, 0, rim * 2, round(rim * 1.5))
        plaza.center = (round(village.x), round(village.y))
        for cell in self._cells_in(plaza):
            if self._free(cell):
                parent[cell] = None
                queue.append(cell)
        while queue:
            gx, gy = queue.popleft()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    step = (gx + dx, gy + dy)
                    if (dx or dy) and step not in parent and self._free(step):
                        parent[step] = (gx, gy)
                        queue.append(step)
        return parent

    def route(self, end: tuple[float, float]) -> list[tuple[float, float]] | None:
        """The lane from the plaza out to one point, as the few corners it turns, or None
        for somewhere the plaza cannot be walked to at all."""
        start = self._nearest_free(end)
        if start is None:
            return None
        cells = [start]
        while self.parent[cells[-1]] is not None:
            cells.append(self.parent[cells[-1]])
        route = [end, *self._straighten([self._point(cell) for cell in cells])]
        walked = sum(math.dist(a, b) for a, b in pairwise(route))
        # A lane that has to go three times round the houses is not a lane anybody wore:
        # something is walled in, and the straight one it used to have says more.
        return route if walked <= math.dist(end, route[-1]) * c.Villages.STREET_DETOUR else None

    def _nearest_free(self, point: tuple[float, float]) -> tuple[int, int] | None:
        """The nearest cell to a doorstep (or a gateway) the plaza can be reached from. A
        door stands against its own wall, so the cell it is in is one the lane may not run
        through: the lane starts at the first one outside it."""
        gx, gy = self._cell(*point)
        for ring in range(6):
            best = min(
                (
                    (gx + dx, gy + dy)
                    for dx in range(-ring, ring + 1)
                    for dy in range(-ring, ring + 1)
                    if max(abs(dx), abs(dy)) == ring and (gx + dx, gy + dy) in self.parent
                ),
                key=lambda cell: math.dist(point, self._point(cell)),
                default=None,
            )
            if best is not None:
                return best
        return None

    def _straighten(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Cut the corners out of a route found on a grid: keep only the points it actually
        has to turn at. A lane laid cell by cell reads as a staircase however fine the grid
        is, and a village's lanes are the one place the player sees the grid at all."""
        kept = [points[0]]
        i = 0
        while i < len(points) - 1:
            far = i + 1
            for j in range(len(points) - 1, i, -1):
                if self._clear(points[i], points[j]):
                    far = j
                    break
            kept.append(points[far])
            i = far
        return kept

    def _clear(self, start: tuple[float, float], end: tuple[float, float]) -> bool:
        """Whether a lane laid straight between two points would run over anything."""
        length = math.dist(start, end)
        for i in range(int(length / (self.step / 2)) + 1):
            t = min(1.0, i * (self.step / 2) / max(1.0, length))
            at = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
            if not self._free(self._cell(*at)):
                return False
        return True


def register_site_cache(clear):
    """Hand over a cache that answers off the village sites, to be dropped whenever they
    change. Anything cached on `village_site`, `poi_site` or the routes between them has to
    be in here or it will go on describing a world with no starting town in it."""
    _SITE_CACHES.append(clear)


def _invalidate_sites():
    for clear in (
        _region_sites.cache_clear,
        _site_reach.cache_clear,
        village_site.cache_clear,
        site_grounds_radius.cache_clear,
    ):
        clear()
    settlements_near_chunk.cache_clear()
    for clear in _SITE_CACHES:
        clear()


def clear_registered_sites():
    _registered.clear()
    _keepouts.clear()
    _invalidate_sites()


def register_settlement(chunk: tuple[int, int], x: float, y: float, grounds_radius: float):
    """Put a settlement on the map the roads, the rivers and the landmarks are laid out
    against. The chunk it is registered under holds it instead of whatever its region
    offered, so nothing is ever generated twice in the same chunk."""
    _registered[(int(chunk[0]), int(chunk[1]))] = (float(x), float(y), float(grounds_radius))
    _invalidate_sites()


def register_keepout(x: float, y: float, radius: float):
    """A circle roads and rivers bow around but never lead to: the landmark ruin. A
    settlement is somewhere to go, a ruin in a field is something to route past."""
    _keepouts.append((float(x), float(y), float(radius)))
    _invalidate_sites()


def registered_keepouts() -> tuple[tuple[float, float, float], ...]:
    return tuple(_keepouts)


def register_world_sites(villages, buildings):
    """Register everything one world holds that its own region grid never offered. Called
    once when a world is created or loaded, before any chunk is generated: after this the
    terrain knows about the starting town and its ruin, and a chunk is a pure function of
    its coordinates again for the rest of the session."""
    clear_registered_sites()
    for village in villages:
        if village_site(*village.chunk) is None:
            register_settlement(village.chunk, village.x, village.y, village.grounds_radius)
    for building in buildings:
        if building.kind == "landmark":
            register_keepout(building.x, building.y, max(building.w, building.h) / 2 + c.Buildings.MIN_GAP)


def _settle_chance(distance: float, near: float, far: float) -> float:
    """One of the two settling chances at this distance from the world centre, eased out to
    `REGION_FAR_DISTANCE` and flat past it."""
    return near + (far - near) * min(1.0, distance / c.Villages.REGION_FAR_DISTANCE)


def _min_gap(x: float, y: float) -> float:
    """How much empty wilderness two settlements have to leave between them here.

    It closes up with distance for the same reason the settling chance opens up: raising
    the chance alone changed nothing at all, because every extra site landed inside a
    neighbour's gap and stood down again. Read off the middle of the two sites being
    compared, so both of them get the same answer whichever one is asking."""
    center = c.World.WORLD_SIZE // 2
    distance = math.hypot(x - center, y - center)
    return _settle_chance(distance, c.Villages.MIN_GAP, c.Villages.MIN_GAP_FAR)


@lru_cache(maxsize=4096)
def _site_reach(cx: int, cy: int, x: int, y: int) -> float:
    """How far the grounds of a settlement standing here would reach at its largest.

    The same answer `site_grounds_radius` gives, worked out without asking whether the
    chunk offers a site at all: two sites standing too close is decided from how much
    ground each of them would take, and `village_site` is the thing being decided, so it
    cannot also be the thing that is asked."""
    rng = random.Random(f"village-layout:{cx},{cy}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS)
    size = rng.choices(sizes, weights=weights)[0]
    radius, extent_x, extent_y = _worst_case_footprint(size, Village._tier_for(x, y, size))
    return Village(x, y, (cx, cy), size, radius, extent_x, extent_y).grounds_radius


def _too_close(one: tuple[int, int, int, int], other: tuple[int, int, int, int]) -> bool:
    """Whether two sites stand too near each other to both be settled, as (cx, cy, x, y).

    Two rules, whichever is the greater: a floor of empty wilderness that closes up as the
    map gets busier, and the grounds themselves, which must never overlap. A gap in
    pixels alone let two towns' walls end up in each other, since how much ground a
    settlement takes is its size and not a constant."""
    mid = ((one[2] + other[2]) / 2, (one[3] + other[3]) / 2)
    reach = _site_reach(*one) + _site_reach(*other)
    return math.dist((one[2], one[3]), (other[2], other[3])) < max(_min_gap(*mid), reach)


@lru_cache(maxsize=4096)
def _region_sites(rx: int, ry: int) -> tuple[tuple[int, int, int, int], ...]:
    """Every chunk this region settles and where in it, as (cx, cy, x, y). Pure function of
    the region coordinates.

    How likely a region is to settle at all, and whether it settles a second chunk, are both
    read off how far out it stands: the region grid is fixed, so density is the one lever
    there is, and the deep wilds were as thinly peopled as the ring round the starting town
    while being very much larger. Both rolls are made whatever the answer, so a region's
    sequence does not shift when the ramp is retuned."""
    region = c.Villages.REGION_CHUNKS
    size = c.World.CHUNK_SIZE
    center = c.World.WORLD_SIZE // 2
    distance = math.hypot((rx + 0.5) * region * size - center, (ry + 0.5) * region * size - center)
    chances = (
        _settle_chance(distance, c.Villages.REGION_CHANCE, c.Villages.REGION_CHANCE_FAR),
        _settle_chance(distance, c.Villages.REGION_SECOND_CHANCE, c.Villages.REGION_SECOND_CHANCE_FAR),
    )

    rng = random.Random(f"village:{rx},{ry}")
    margin = c.Villages.CHUNK_MARGIN
    sites: list[tuple[int, int, int, int]] = []
    for slot, chance in enumerate(chances):
        settles = rng.random() <= chance
        cx = rx * region + rng.randrange(region)
        cy = ry * region + rng.randrange(region)
        if slot and sites:
            # The second one goes in the corner of the region furthest from the first
            # rather than being rolled: two points dropped anywhere in a region this size
            # are usually nearer each other than the gap allows, so a second site rolled
            # freely was a second site that always stood down again.
            cx = rx * region + (0 if sites[0][0] - rx * region >= region / 2 else region - 1)
            cy = ry * region + (0 if sites[0][1] - ry * region >= region / 2 else region - 1)
        x = cx * size + rng.randint(margin, size - margin)
        y = cy * size + rng.randint(margin, size - margin)
        if not settles:
            continue
        if math.hypot(x - center, y - center) < c.Villages.MIN_DIST_FROM_SPAWN:
            continue
        # The second site of a region stands down for the first exactly as a whole region
        # stands down for its neighbour, and never shares its chunk.
        if any((cx, cy) == other[:2] or _too_close((cx, cy, x, y), other) for other in sites):
            continue
        sites.append((cx, cy, x, y))
    return tuple(sites)


@lru_cache(maxsize=4096)
def village_site(cx: int, cy: int) -> tuple[int, int] | None:
    """Where the village belonging to chunk (cx, cy) stands, or None if it holds none.

    One region of REGION_CHUNKS x REGION_CHUNKS chunks settles one chunk, or two out in the
    wilds, and a site landing too close to a neighbouring region's yields to it, so two
    settlements can't end up back to back across a region border. All of it is a pure
    function of the coordinates: the same chunk always offers the same site, whether or not
    the village behind it has been generated yet, which is also why the answer is cached:
    chunk loading, landmark placement and the roads between settlements all ask it
    repeatedly for the same coordinates.

    A chunk a world registered a settlement into (`register_settlement`) answers with that
    instead: the starting town is rolled per playthrough rather than out of a region, and
    everything laid out against the sites has to know it is there.
    """
    registered = _registered.get((cx, cy))
    if registered is not None:
        return round(registered[0]), round(registered[1])

    region = c.Villages.REGION_CHUNKS
    rx, ry = math.floor(cx / region), math.floor(cy / region)
    site = next((s for s in _region_sites(rx, ry) if (s[0], s[1]) == (cx, cy)), None)
    if site is None:
        return None

    for _chunk, (ox, oy, radius) in _registered.items():
        if math.hypot(site[2] - ox, site[3] - oy) < max(c.Villages.MIN_GAP, radius + c.Villages.MIN_GAP / 2):
            return None
    for nx in range(rx - 1, rx + 2):
        for ny in range(ry - 1, ry + 2):
            # Ties are broken by region order, the same way from wherever this is asked.
            if (nx, ny) >= (rx, ry):
                continue
            for other in _region_sites(nx, ny):
                if _too_close(site, other):
                    return None
    return site[2], site[3]


@lru_cache(maxsize=32)
def _worst_case_footprint(size: str, tier: int = 0) -> tuple[int, int, int]:
    """The biggest (radius, extent_x, extent_y) a settlement of this size and tier can lay
    out.

    Rolled without an rng: every count is taken at its maximum, every building at its
    largest and the jitter at its worst, so the answer is an upper bound on a village that
    has not been generated yet rather than a guess at the one that will be. The tier is in
    it because it is worth houses (`Villages.EXTRA_BUILDINGS_BY_TIER`): a bound taken off
    the size alone is not a bound at all once a deep wilds village is half again as big."""
    composition = c.Villages.START_COMPOSITION if size == "start" else _composition_for(size, tier)
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
    ended up against a town's gate. A registered settlement already exists, so it answers
    with the grounds it actually has."""
    registered = _registered.get((cx, cy))
    if registered is not None:
        return registered[2]
    site = village_site(cx, cy)
    if site is None:
        return 0.0
    return _site_reach(cx, cy, site[0], site[1])


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
            for site in _region_sites(rx, ry):
                # Asked back through village_site so a region that stands down for a
                # neighbour is left out here too, and no road is drawn to a village that
                # never exists.
                if village_site(site[0], site[1]) is not None:
                    sites.append((site[2], site[3], site[0], site[1], site_grounds_radius(site[0], site[1])))
    for chunk, (x, y, radius) in _registered.items():
        if max(abs(chunk[0] - cx), abs(chunk[1] - cy)) <= chunk_radius:
            sites.append((x, y, chunk[0], chunk[1], radius))
    return tuple(sites)


def _composition_for(size: str, tier: int) -> dict:
    """What a settlement of this size and tier is made of.

    The size says what kind of place it is, the tier says how much of it there is: a deep
    wilds village carries the same shape as a near one with more houses in it and a second
    shop, so walking out is visible as a skyline before it is anything else. Both ends of
    each range move together, so what was a roll stays a roll."""
    composition = dict(c.Villages.COMPOSITION[size])
    extra = c.Villages.EXTRA_BUILDINGS_BY_TIER[max(0, min(tier, len(c.Villages.EXTRA_BUILDINGS_BY_TIER) - 1))]
    for kind, more in extra.items():
        low, high = composition[kind]
        composition[kind] = (low + more, high + more)
    return composition


def _building_kinds(composition: dict, rng: random.Random) -> list[str]:
    """The buildings a settlement of this composition is made of, biggest first: the
    tavern and the shops take the slots nearest the plaza, the houses spread out behind."""
    kinds: list[str] = []
    for kind in ("tavern", "shop", "house"):
        low, high = composition[kind]
        kinds.extend([kind] * rng.randint(low, high))
    return kinds


def _assign_slots(kinds: list[str], slots: list[tuple[float, float]]) -> list[tuple[str, tuple[float, float]]]:
    """Which slot each building takes.

    The slot list runs from the plaza outward and the kinds run biggest first, so handing
    them out in order put every tavern a town had on the same corner of the square. The
    specials are dealt first and never within `SPECIAL_MIN_GAP` of another of their own
    kind, which is what spreads the two shops and the taverns round the settlement; the
    houses then fill whatever is left, still nearest the plaza first."""
    free = list(slots)
    taken: dict[str, list[tuple[float, float]]] = {}
    placed: list[tuple[str, tuple[float, float]]] = []
    for kind in [k for k in kinds if k != "house"]:
        mine = taken.setdefault(kind, [])

        def distance(slot, mine=mine):
            return min((math.dist(slot, other) for other in mine), default=math.inf)

        # The nearest slot to the plaza that is far enough from this kind's own; if the
        # settlement is too small to hold one, whichever slot is furthest from them.
        choice = next((slot for slot in free if distance(slot) >= c.Villages.SPECIAL_MIN_GAP), None)
        if choice is None:
            choice = max(free, key=distance)
        free.remove(choice)
        mine.append(choice)
        placed.append((kind, choice))
    placed.extend(zip([k for k in kinds if k == "house"], free))
    return placed


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


def _clear_doorsteps(buildings: list[Building], center: tuple[float, float]) -> bool:
    """Push whatever is standing on somebody's doorstep off it.

    Keeping the boxes apart is not the same as leaving the doors usable: two buildings a
    clear stride apart still block each other if one of them opens onto the other's wall.
    Whichever of the pair stands further from the plaza gives way, so the settlement spreads
    outward exactly as it does when two footprints overlap. Returns whether anything moved."""
    moved = False
    for building in buildings:
        step = building.doorstep(c.Villages.DOORSTEP_CLEAR)
        if step is None:
            continue
        nx, ny = building.outward()
        for other in buildings:
            if other is building or not step.colliderect(other.bounds):
                continue
            bounds = other.bounds
            if nx:
                push = (step.right - bounds.left) if nx > 0 else (bounds.right - step.left)
            else:
                push = (step.bottom - bounds.top) if ny > 0 else (bounds.bottom - step.top)
            far = max((building, other), key=lambda b: math.hypot(b.x - center[0], b.y - center[1]))
            # The one that gives way is either shoved out of the apron or walked backwards
            # away from it, taking its own door with it.
            sign = 1 if far is other else -1
            if nx:
                far.x += round(push * nx * sign)
            else:
                far.y += round(push * ny * sign)
            far.reset_geometry()
            moved = True
    return moved


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
        moved = _clear_doorsteps(buildings, center) or moved
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
    for kind, (ox, oy) in _assign_slots(kinds, slots):
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
    # The lanes are not laid here: they run out to where the roads from the neighbouring
    # settlements stop, and a village rolled per playthrough is not on the map the roads
    # are drawn from until it is registered. Whoever puts it in the world plans them.
    village = Village(x, y, chunk, size, radius, extent_x, extent_y)
    for building in buildings:
        # Which settlement's tier lights this one's windows after dark. A building out in
        # the wilderness keeps -1 and is never lit: nobody lives in a ruin.
        building.village_tier = village.tier
    return village, buildings


def generate_village(x, y, chunk: tuple[int, int]) -> tuple[Village, list[Building]]:
    """Lay out the village that chunk (cx, cy) offers. Called once, the first time the
    player walks into range; after that the result lives in the save like the starting town."""
    rng = random.Random(f"village-layout:{chunk[0]},{chunk[1]}")
    sizes, weights = zip(*c.Villages.SIZE_WEIGHTS)
    size = rng.choices(sizes, weights=weights)[0]
    # The tier is worked out before anything is laid out, because it is worth houses: it is
    # the same answer `Village` gives itself, asked one step early.
    return _build(x, y, chunk, size, _composition_for(size, Village._tier_for(x, y, size)), rng)


def generate_starting_world() -> tuple[Village, list[Building]]:
    """The village the player starts next to, plus the ruined landmark standing alone out
    in the settled ring. Rolled fresh per new game rather than seeded, so two playthroughs
    don't open on the same town.

    The spot is chosen off the water rather than wherever the angle fell: the rivers are a
    pure function of their lane, so they can be asked about before the town exists, and a
    settlement that has to be built round a river bend is one the river was never asked
    about. Once it stands it is registered (`register_world_sites`), which is what makes
    everything else laid out from the sites bow around it."""
    # Imported here rather than at the top: the terrain is laid out from the village sites
    # this module owns, so it is the terrain that imports this and not the other way round.
    from game.entities.terrain import water_near

    clear_registered_sites()
    center = c.World.WORLD_SIZE // 2
    distance = c.Villages.START_DISTANCE_FROM_CENTER
    reach = _worst_case_footprint("start")[0] + c.Scenery.RIVER_VILLAGE_MARGIN
    for attempt in range(24):
        angle = random.uniform(0, 2 * math.pi)
        x = round(center + math.cos(angle) * distance)
        y = round(center + math.sin(angle) * distance)
        if attempt < 20 and water_near(x, y, reach):
            continue
        break
    chunk = (int(x // c.World.CHUNK_SIZE), int(y // c.World.CHUNK_SIZE))
    village, buildings = _build(x, y, chunk, "town", c.Villages.START_COMPOSITION, random.Random())

    landmark = _place_landmark(village, buildings)
    if landmark is not None:
        buildings.append(landmark)
    register_world_sites([village], buildings)
    return village, buildings


def _place_landmark(village: Village, buildings: list[Building]) -> Building | None:
    """The ancient ruin: out on the far side of the settled ring, well clear of the village
    and a long way from the spawn point, since its guardian is a boss and shouldn't be
    waiting on the doorstep (Boss.MIN_DIST_FROM_START, the floor under every boss rather
    than the ordinary building clearance).

    Clear of every *other* settlement too, planned ones included, and by a boss's clearance
    rather than a building's: the ruin is the one place in the world a boss stands from the
    first frame of the save, so it is placed where a boss is allowed to be. A ruin that
    fails that is a ruin with nothing guarding it."""
    center = c.World.WORLD_SIZE // 2
    margin = c.Buildings.EDGE_MARGIN
    size = c.World.CHUNK_SIZE
    reach = math.ceil(c.Boss.MIN_DIST_FROM_VILLAGE / size) + 2
    # More tries than a building's usual handful: the ruin has to clear every settlement in
    # the region by a boss's distance rather than a wall's, and the settled ring is not
    # large. A world with no ruin in it is a world with no guardian and no lore stone.
    for _ in range(400):
        x = random.randint(margin, c.World.WORLD_SIZE - margin)
        y = random.randint(margin, c.World.WORLD_SIZE - margin)
        if math.hypot(x - center, y - center) < c.Boss.MIN_DIST_FROM_START:
            continue
        if village.distance_to_point((x, y)) < village.grounds_radius + c.Boss.MIN_DIST_FROM_VILLAGE:
            continue
        chunk = (int(x // size), int(y // size))
        if any(
            math.hypot(x - sx, y - sy) - radius < c.Boss.MIN_DIST_FROM_VILLAGE
            for sx, sy, _, _, radius in settlements_near_chunk(*chunk, reach)
        ):
            continue
        candidate = Building(x, y, "landmark")
        gap = c.Buildings.MIN_GAP
        if any(candidate.bounds.inflate(gap * 2, gap * 2).colliderect(other.bounds) for other in buildings):
            continue
        return candidate
    return None
