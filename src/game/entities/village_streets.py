"""The lanes worn inside one settlement.

A lane is the few corners it turns and the width it has at each. `StreetGrid` is the
ground a lane may be worn into, filled once out of the plaza so every lane the place needs
is answered from the same walk back: two doors on the same side of town share a lane
instead of each wearing its own beside it. Built per settlement and thrown away with the
plan; nothing here is kept or saved.

The sharing is the whole point and it is easy to compute and then throw away: a route
straightened on its own from the door all the way to the plaza snaps back to the straight
line it would have had anyway, and a town whose lanes were worked out together comes out as
a fan of spokes crossing each other at shallow angles. So `trace` does every lane at once
and straightens only between the junctions where the routes actually part company, which is
what leaves a trunk with branches off it rather than eleven spokes.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from itertools import pairwise
from typing import TYPE_CHECKING

import pygame

import core.constants as c

if TYPE_CHECKING:
    from game.entities.buildings import Building
    from game.entities.village import Village


def walk_lane(lane: tuple, step: float):
    """Every `step` along one lane, with the width it has there. The lane itself is the few
    corners it turns; this is what has to answer for the ground between them."""
    for (ax, ay, aw), (bx, by, bw) in pairwise(lane):
        length = math.hypot(bx - ax, by - ay)
        for i in range(max(1, int(length // step))):
            t = i * step / length if length else 0.0
            yield ax + (bx - ax) * t, ay + (by - ay) * t, aw + (bw - aw) * t
    yield lane[-1]


def taper_from_gate(route: list[tuple[float, float]], wide: float) -> tuple:
    """One lane out of a gate: the road's own width where the road stopped, narrowing to a
    lane's by the time it is `STREET_TAPER` inside.

    A road is twice a lane wide and carries a verge, so the two used to meet as a step with
    a round cap on the end of it. Only the tapering stretch is walked in steps; past it the
    lane is the corners it turns like any other."""
    narrow = float(c.Villages.STREET_WIDTH)
    taper = c.Villages.STREET_TAPER
    lane = []
    walked = 0.0
    for start, end in pairwise(route):
        length = math.dist(start, end)
        along = 0.0
        while True:
            t = along / length if length else 0.0
            here = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
            lane.append((*here, wide + (narrow - wide) * min(1.0, (walked + along) / taper)))
            if walked + along >= taper or along + c.Villages.STREET_STEP >= length:
                break
            along += c.Villages.STREET_STEP
        walked += length
    lane.append((*route[-1], narrow))
    return tuple(lane)


def _towards(start: tuple[float, float], end: tuple[float, float], reach: float) -> tuple[float, float]:
    """`reach` along the way from one point to another."""
    length = math.dist(start, end) or 1.0
    return start[0] + (end[0] - start[0]) * reach / length, start[1] + (end[1] - start[1]) * reach / length


class StreetGrid:
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
        self.rects = [rect.inflate(keep * 2, keep * 2) for b in buildings for rect in b.footprint()]
        self.rects += [rect.inflate(keep, keep) for rect in village.defences()["walls"]]
        self.blocked: set[tuple[int, int]] = set()
        for rect in self.rects:
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

    def _cells_in_plaza(self, village: Village, rx: float, ry: float):
        """Every cell of the grid standing on the plaza, which is the ellipse the plaza is
        drawn as and not the rectangle around it."""
        bounds = pygame.Rect(0, 0, round(rx * 2), round(ry * 2))
        bounds.center = (round(village.x), round(village.y))
        for cell in self._cells_in(bounds):
            x, y = self._point(cell)
            if ((x - village.x) / rx) ** 2 + ((y - village.y) / ry) ** 2 <= 1.0:
                yield cell

    def _free(self, cell: tuple[int, int]) -> bool:
        return 0 <= cell[0] < self.span and 0 <= cell[1] < self.span and cell not in self.blocked

    def _flood(self, village: Village) -> dict:
        """Every cell the plaza can be walked to from, and which cell to take to get there.

        Cost rather than steps: eight ways out of a cell with a diagonal costing what a
        diagonal is, plus `STREET_TURN_COST` for changing direction. A plain step count on
        an eight-way grid ties every staircase between two points with the straight run
        that costs the same, and picks between them by the order the queue happened to be
        in: what came back was a diagonal stretch and then an axis-aligned one, which the
        straightening could shorten but never unbend.

        The seeds are the plaza as it is drawn, an ellipse and not the rectangle around it:
        a route ending in a corner of that rectangle stopped on the grass a good stride
        short of the earth it was going to."""
        turn = c.Villages.STREET_TURN_COST
        rim = c.Villages.PLAZA_RADIUS
        parent: dict[tuple[int, int], tuple[int, int] | None] = {}
        came: dict[tuple[int, int], tuple[int, int]] = {}
        cost: dict[tuple[int, int], float] = {}
        queue: list[tuple[float, tuple[int, int]]] = []
        for cell in self._cells_in_plaza(village, rim, rim * c.Villages.PLAZA_SQUASH):
            if self._free(cell):
                parent[cell], came[cell], cost[cell] = None, (0, 0), 0.0
                heapq.heappush(queue, (0.0, cell))
        while queue:
            spent, cell = heapq.heappop(queue)
            if spent > cost[cell] + 1e-9:
                continue
            gx, gy = cell
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    step = (gx + dx, gy + dy)
                    if not (dx or dy) or not self._free(step):
                        continue
                    # A diagonal between two blocked cells is a lane drawn through the
                    # corner of the house it was going round.
                    if dx and dy and not (self._free((gx + dx, gy)) and self._free((gx, gy + dy))):
                        continue
                    through = spent + math.hypot(dx, dy) + (turn if came[cell] not in ((0, 0), (dx, dy)) else 0.0)
                    if through < cost.get(step, math.inf) - 1e-9:
                        cost[step], parent[step], came[step] = through, cell, (dx, dy)
                        heapq.heappush(queue, (through, step))
        return parent

    def trace(self, ends: list[tuple[float, float]]) -> dict[int, list[list[tuple[float, float]]]]:
        """Every lane the settlement needs at once, each as the stretches it is made of,
        keyed by which end it was asked for. Missing for an end the plaza cannot be walked
        to at all, which the caller reads as "no lane here" rather than as a straight one
        laid through whatever is in the way.

        Doing them together is what makes them a network. Every route walks back along the
        same tree, so two doors on the same side of town share cells the whole way in; the
        stretches are cut where that sharing starts and stops, and each is straightened on
        its own. Two lanes that share a trunk are then the same points along it rather than
        two lines a few paces apart, and the ones that come off it read as branches."""
        chains = {i: chain for i, end in enumerate(ends) if (chain := self._chain(end)) is not None}
        shared = Counter(cell for chain in chains.values() for cell in chain)
        return {i: self._stretches(ends[i], chain, shared) for i, chain in chains.items()}

    def _chain(self, end: tuple[float, float]) -> list[tuple[int, int]] | None:
        """The cells from one point back to the plaza, or None for somewhere the plaza
        cannot be walked to, or only by going three times round the houses."""
        start = self._nearest_free(end)
        if start is None:
            return None
        cells = [start]
        while self.parent[cells[-1]] is not None:
            cells.append(self.parent[cells[-1]])
        points = [self._point(cell) for cell in cells]
        walked = math.dist(end, points[0]) + sum(math.dist(a, b) for a, b in pairwise(points))
        # A lane that has to go three times round the houses is not a lane anybody wore:
        # something is walled in, and the straight one it used to have says more.
        return cells if walked <= math.dist(end, points[-1]) * c.Villages.STREET_DETOUR else None

    def _stretches(self, end, chain, shared) -> list[list[tuple[float, float]]]:
        """One route cut into the stretches it shares with its neighbours and the ones it
        walks alone, each straightened and worn round its corners. A cell used by more
        routes than the one before it is where another lane joined, and that is a junction
        rather than a corner to be straightened through."""
        points = [self._point(cell) for cell in chain]
        cuts = [0, *(i for i in range(1, len(chain)) if shared[chain[i]] != shared[chain[i - 1]]), len(chain) - 1]
        stretches = []
        for start, stop in pairwise(sorted(set(cuts))):
            run = self._straighten(points[start : stop + 1])
            if start == 0:
                run = [end, *run]
            stretches.append(self._bend(run))
        return stretches or [[end, points[-1]]]

    def _bend(self, route: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """A route with its corners worn round rather than mitred: each one cut back along
        both its stretches and rounded off between the two. Only where the short way round
        is clear, so a lane never cuts the corner of the house it was going round."""
        if len(route) < 3:
            return route
        bend, steps = c.Villages.STREET_BEND, c.Villages.STREET_BEND_STEPS
        worn = [route[0]]
        for before, corner, after in zip(route, route[1:], route[2:], strict=False):
            back = min(bend, math.dist(before, corner) / 2)
            on = min(bend, math.dist(corner, after) / 2)
            start, end = _towards(corner, before, back), _towards(corner, after, on)
            if min(back, on) < 1.0 or not self._clear(start, end):
                worn.append(corner)
                continue
            for i in range(steps + 1):
                t = i / steps
                worn.append(
                    (
                        (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * corner[0] + t * t * end[0],
                        (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * corner[1] + t * t * end[1],
                    )
                )
        worn.append(route[-1])
        return worn

    def _nearest_free(self, point: tuple[float, float]) -> tuple[int, int] | None:
        """The nearest cell to a doorstep (or a gateway) the plaza can be reached from. A
        door stands against its own wall, so the cell it is in is one the lane may not run
        through: the lane starts at the first one outside it.

        None for a doorstep the plaza cannot be walked to from at all, which `route` reads
        as "no lane here" rather than as a straight one laid through whatever is in the way.
        The search runs out to `STREET_SEARCH_RINGS`: past that the door is not merely
        against a wall, it is walled in, and a lane out to it would be a lane nobody wore.
        """
        gx, gy = self._cell(*point)
        for ring in range(c.Villages.STREET_SEARCH_RINGS):
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
        """Whether a lane laid straight between two points would run over anything.

        Asked of the ground rather than of the grid: the fill has to work in cells, but a
        cell is as wide as a lane and a straight run that only clips the corner of one is a
        run the straightening should be allowed to take. Tested against the grid it was
        refused, and what came back instead was the staircase the fill had found."""
        length = math.dist(start, end)
        for i in range(int(length / (self.step / 2)) + 1):
            t = min(1.0, i * (self.step / 2) / max(1.0, length))
            at = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
            if any(rect.collidepoint(at) for rect in self.rects):
                return False
        return True
