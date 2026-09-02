"""The lanes worn inside one settlement.

A lane is the few corners it turns and the width it has at each. `StreetGrid` is the
ground a lane may be worn into, flood filled once out of the plaza so every lane the place
needs is answered from the same walk back: two doors on the same side of town share a lane
instead of each wearing its own beside it. Built per settlement and thrown away with the
plan; nothing here is kept or saved.
"""

from __future__ import annotations

import math
from collections import deque
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
        """Whether a lane laid straight between two points would run over anything."""
        length = math.dist(start, end)
        for i in range(int(length / (self.step / 2)) + 1):
            t = min(1.0, i * (self.step / 2) / max(1.0, length))
            at = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
            if not self._free(self._cell(*at)):
                return False
        return True
