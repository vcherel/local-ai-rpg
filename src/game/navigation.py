"""How a body gets from where it is to where it wants to be, and what it may pass through.

The fifth part of `World` (see `world.py` for the other four). `world.py` owns the state
and the indexes that say what is solid; this owns everything that reads them to move
something: the line between two points, the way round a wood or a palisade, the corner a
chaser commits to, the ring a crowd spreads into, and the doors and gates a body is
allowed to open rather than break.

Gathered here because it is one subject with one rule behind it: if something cannot reach
the player, the answer is navigation. Only a door and a gate may be broken, and only after
its own people have been given the chance to let themselves through it.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

import pygame

import core.constants as c
from game.entities.buildings import Building
from game.entities.monsters import Monster

if TYPE_CHECKING:
    from game.entities.player import Player


# A bare coordinate to route towards. `chase_waypoint` only ever reads an x and a y off
# whoever is being chased, and a villager running for a door is chasing a spot on the floor.
class Point(NamedTuple):
    x: float
    y: float


def merge_rects(rects: list[pygame.Rect]) -> list[pygame.Rect]:
    """Fold overlapping rectangles into the shapes they actually make. A clump of trunks is
    one obstacle to walk round; treated as a dozen, a chaser routes round the first, finds
    the second in its way, and picks its way into the middle of the wood."""
    merged: list[pygame.Rect] = []
    for rect in rects:
        current = rect
        joined = True
        while joined:
            joined = False
            for other in list(merged):
                if current.colliderect(other):
                    merged.remove(other)
                    current = current.union(other)
                    joined = True
        merged.append(current)
    return merged


class WorldNavigation:
    def walls_near(self, x, y) -> list:
        """The palisade of any walled town near this point, as rectangles a detour can be
        costed round: each wall stretch grown to swallow the corner tower it ends at.

        A tower is a third solid where two stretches meet, and left out of this it was
        invisible to navigation: the way round a stretch ended at a corner standing inside
        the tower, so a chaser walked at a point it could never reach and ground there. The
        towers are folded into the stretches one at a time rather than merged wholesale,
        since unioning both sides of a corner would swallow the town and its gates with it."""
        rects = []
        for village in self._village_solids_by_chunk.get(self._chunk_of(x, y), ()):
            defences = village.defences()
            reach = village.tower_radius
            towers = [
                pygame.Rect(round(tx - reach), round(ty - reach), reach * 2, reach * 2) for tx, ty in defences["towers"]
            ]
            for wall in defences["walls"]:
                for tower in towers:
                    if wall.colliderect(tower):
                        wall = wall.union(tower)
                rects.append(wall)
            rects.extend(tower for tower in towers if not any(tower.colliderect(wall) for wall in defences["walls"]))
        return rects

    def line_of_sight(self, x0, y0, x1, y1, over_walls: bool = False) -> bool:
        """Is there a clear line between two points, or is something solid in the way?

        Walks the segment in steps half a wall thick, asking the same `blocked` everything
        else does, so a house wall, a well or a tree trunk all break sight the way they
        break movement. Used by ranged monsters before they shoot: their arrow was already
        stopped by the wall, but they used to keep firing into it at a player they could
        not possibly see.

        `over_walls` is what an archer standing in a tower has that a goblin in a field does
        not: a settlement's own palisade is beneath them, so it neither hides the target nor
        stops the arrow (`blocked_over_walls`). Everything else still does both."""
        test = self.blocked_over_walls if over_walls else self.blocked
        dx, dy = x1 - x0, y1 - y0
        distance = math.hypot(dx, dy)
        if distance == 0:
            return True
        step = c.Buildings.WALL_THICKNESS / 2
        for i in range(1, int(distance / step) + 1):
            t = i * step / distance
            if test(x0 + dx * t, y0 + dy * t, 1):
                return False
        return True

    def unwedge(self, body, radius: float, dt, wants_move: bool) -> bool:
        """Prise a body out of ground it is standing on legally and cannot get off.

        `World.unstick` answers the body that is *inside* something solid. This answers the
        other half, which nothing could see: a corner of an L, the neck between two houses,
        the pocket behind a doorstep. The body is on open ground there, so every test it
        makes passes; it simply has a wall on both axes and a slide that carries it into
        neither. A villager wedged in the corner of a building stayed there for the rest of
        the session looking like a bug, because from the inside it is not one.

        Only time tells them apart, so that is what is measured: meaning to move
        (`wants_move`) and covering less than `Entities.WEDGE_STEP` a frame for
        `Entities.WEDGE_MS` is being wedged. The way out is a spot with real clearance
        around it (`Entities.WEDGE_CLEARANCE` of the body's own radius), which is what a
        corner never has, and whatever it was strolling towards is dropped: the target was
        the reason it walked in there.
        """
        spot = (body.x, body.y)
        last = getattr(body, "wedge_spot", None)
        body.wedge_spot = spot
        moved = math.hypot(spot[0] - last[0], spot[1] - last[1]) if last is not None else math.inf
        if not wants_move or moved > c.Entities.WEDGE_STEP or body.rooted or body.staggered:
            body.wedge_ms = 0.0
            return False
        body.wedge_ms = getattr(body, "wedge_ms", 0.0) + dt
        if body.wedge_ms < c.Entities.WEDGE_MS:
            return False
        body.wedge_ms = 0.0
        body.x, body.y = self.free_spot_near(
            body.x, body.y, radius * c.Entities.WEDGE_CLEARANCE, rings=c.World.UNSTICK_RINGS
        )
        body.wedge_spot = (body.x, body.y)
        body.wander.interrupt()
        return True

    def chase_waypoint(self, chaser, player: Player, radius: float):
        """Where a chaser should head next, or None to walk straight at the player.

        Buildings are the only obstacles and each has a single door, so a chase across a wall
        never needs a real pathfinder: aim for the door of whichever building separates the
        two, and walk round any other building standing in the way rather than into it.

        Takes any entity with an x/y and its own radius, since an angry villager has to find
        its way round a house exactly like a wolf does.
        """
        monster = chaser
        monster_building = self.building_at(monster.x, monster.y)
        player_building = self.building_at(player.x, player.y)
        start = (monster.x, monster.y)

        if monster_building is player_building:
            # Through the doorway (or given up on it): whatever door this one had committed
            # itself to is behind it now.
            chaser.door_commit = None
            if monster_building is not None:
                # Same room: the only things between them are the bed and the table, so the
                # detour that walks round a house walks round those too. Without it a monster
                # steered into the furniture and stuck there while the player stood in a
                # corner two steps away.
                solids = [rect for rect, _kind in monster_building.interior_layout()["solids"]]
                corner = self._detour_corner(start, (player.x, player.y), radius, solids, chaser=chaser)
                # A room is small enough that the way round a table can be a point inside the
                # wall behind it. Sending a monster at one is worse than sending it nowhere:
                # steering gets round furniture on its own, it just needs the room to do it.
                if corner is not None and self.blocked(corner[0], corner[1], radius):
                    return None
                return corner
            # Both outdoors: straight at the player, round anything standing in the way.
            goal = (player.x, player.y)
        elif monster_building is not None:
            # Indoors with the player elsewhere: out through the door first, and no detour
            # around the building the monster is standing in.
            return self._door_goal(monster_building, monster, radius, leaving=True)
        else:
            goal = self._door_goal(player_building, monster, radius, leaving=False)

        # The one building whose shell the goal is allowed to be inside is the one whose
        # doorway the goal *is*: walking round that one would be walking away from the door.
        through = player_building.bounds if player_building is not None else None
        return self._detour_corner(start, goal, radius, through=through, chaser=chaser) or goal

    def open_door_for(self, chaser):
        """A villager chasing the player into a house lets themselves in: the door is theirs
        and they live behind it. Monsters get no such courtesy and beat it down instead
        (WorldCombat.bash_doors), which is the whole difference between the two."""
        for building in self.buildings_near(chaser.x, chaser.y):
            if not building.door_closed:
                continue
            door = building.door_rect()
            if math.hypot(chaser.x - door.centerx, chaser.y - door.centery) <= c.Buildings.DOOR_BASH_REACH:
                building.door_open = True

    def pass_gate_for(self, chaser, radius: float, target) -> bool:
        """A villager reaching their own barred gate lets themselves through it.

        The bar is theirs: they lift it, step across the gateway and it swings shut behind
        them (`Village.let_through`), which is the difference between a wall that keeps the
        player out and one that keeps its own people in. Nothing else in the world may do
        this: a monster beats the leaf down instead (`WorldCombat.bash_gates`) and the player
        hacks their way through it.

        One step across, never a walk through: the leaf is solid to everything `blocked`
        answers, this one included, so the way past it is the same short hop out of a
        doorway that `Building.clear_of_door` is.
        """
        for village in self._village_solids_by_chunk.get(self._chunk_of(chaser.x, chaser.y), ()):
            if not village.barred:
                continue
            for index, gate in enumerate(village.defences()["gates"]):
                if not village.gate_closed(index):
                    continue
                leaf = gate["rect"]
                nearest_x = min(max(chaser.x, leaf.left), leaf.right)
                nearest_y = min(max(chaser.y, leaf.top), leaf.bottom)
                if math.hypot(chaser.x - nearest_x, chaser.y - nearest_y) > c.Buildings.DOOR_BASH_REACH:
                    continue
                # Only if this gate is actually what stands between them, the same test a
                # monster's swing at one gets.
                if not village.gate_between(index, chaser.x, chaser.y, target.x, target.y):
                    continue
                x, y = village.gate_side_point(index, chaser.x, chaser.y, radius, across=True)
                if self.blocked(x, y, radius):
                    continue
                village.let_through(index)
                chaser.x, chaser.y = x, y
                return True
        return False

    def shut_door(self, building: Building, player: Player):
        """Shut a door, stepping whoever stands in the frame out of it first.

        A leaf closing on a body seals it inside a solid, where every step it could take is
        refused: this is the one way in the world a door is ever shut on somebody who did
        not shut it themselves, and it is how a villager taking shelter used to trap the
        player in their own doorway."""
        building.door_open = False
        for body, radius in self.bodies(player):
            if building.door_overlaps(body.x, body.y, radius):
                body.x, body.y = building.clear_of_door(body.x, body.y, radius)

    def clear_gateways(self, village, player: Player):
        """Step anything standing in a barred gateway out of it, to the side it is already
        nearer. The gates bar themselves the moment a settlement turns (`_bar_gates`), with
        no regard for who happened to be walking through one; the same rule holds as for a
        door, that nothing is ever sealed inside a leaf."""
        bodies = None
        for index, gate in enumerate(village.defences()["gates"]):
            if not village.gate_closed(index) or village.gate_ajar(index):
                continue
            leaf = gate["rect"]
            if bodies is None:
                bodies = self.bodies(player)
            for body, radius in bodies:
                if not leaf.inflate(radius * 2, radius * 2).collidepoint(body.x, body.y):
                    continue
                x, y = village.gate_side_point(index, body.x, body.y, radius, across=False)
                if not self.blocked(x, y, radius):
                    body.x, body.y = x, y

    @staticmethod
    def _door_goal(building: Building, monster: Monster, radius: float, leaving: bool):
        """The point to walk to next to get through `building`'s door, in or out. A monster
        lines up with the doorway from the outside first, then steps across the threshold,
        so it goes through the gap instead of shouldering the wall next to it.

        Written along the door's own outward normal rather than in terms of "the bottom of
        the building", since a house can be turned to face any of the four ways."""
        nx, ny = building.outward()
        door = building.door_rect()
        door_front = building.door_front()
        inside = (door.centerx - nx * 36, door.centery - ny * 36)
        fits = radius < c.Buildings.DOOR_WIDTH / 2 - 4
        # How far off the doorway's centre line this one stands, measured across the facade.
        across = abs((monster.x - door.centerx) * -ny + (monster.y - door.centery) * nx)
        aligned = across < c.Buildings.DOOR_WIDTH / 2 - radius
        if monster.door_commit == building.id and not building.door_closed:
            # Already committed to going through: the alignment tests below flip as the body
            # crosses the threshold, and re-deciding every frame is what had a chaser
            # shivering in the doorway instead of walking through it. The commit is dropped
            # by `chase_waypoint` the moment both are on the same side of the wall.
            return door_front if leaving else inside
        if building.door_closed:
            # A shut door is a wall with nothing to walk round: come right up against it from
            # whichever side this is on and beat on it (WorldCombat.bash_doors). Close enough
            # to be in reach of the leaf, which the usual standing-off point is not.
            if leaving:
                return inside
            return (door.centerx + nx * (radius + 6), door.centery + ny * (radius + 6))
        if leaving:
            if not aligned:
                return inside
            monster.door_commit = building.id
            return door_front
        # Too broad for the doorway (the stone colossus): it waits on the doorstep rather
        # than shoving itself into a wall it can never pass. Still round the far side of the
        # building, and the door is on the front: only step in from the front half.
        in_front = (monster.x - building.x) * nx + (monster.y - building.y) * ny > 0
        if not fits or not aligned or not in_front:
            return door_front
        # Lined up on the doorstep and about to step through: hold that line to the end.
        monster.door_commit = building.id
        return inside

    def assign_surround_slots(self, chasers, target):
        """Deal the chasers coming for one target their places around it, and hand out the
        few permissions to swing.

        Two things turn a pack from a queue into an ambush. The bearings are dealt evenly
        round the ring in the order the chasers already stand in, rather than each rolling
        its own at spawn, so whoever joins the chase late takes the empty side instead of
        the crowded one; and only `Entities.MAX_ACTIVE_ATTACKERS` of them may swing at any
        moment, the nearest first, so the rest close the circle and wait their turn where
        the player can see them coming.

        A chaser keeps the bearing it holds while the dealt one is close to it, which is
        what stops the whole ring rotating a little every frame."""
        if not chasers:
            return
        ordered = sorted(chasers, key=lambda ch: math.atan2(ch.y - target.y, ch.x - target.x))
        # The ring is anchored on where the first of them already stands, so dealing the
        # slots never asks anybody to walk round to the far side for the sake of symmetry.
        base = math.atan2(ordered[0].y - target.y, ordered[0].x - target.x)
        step = 2 * math.pi / len(ordered)
        limit = math.radians(c.Entities.SLOT_REASSIGN_DEG)
        for index, chaser in enumerate(ordered):
            slot = base + step * index
            drift = abs((chaser.slot_angle - slot + math.pi) % (2 * math.pi) - math.pi)
            if drift > limit:
                chaser.slot_angle = slot

        target_pos = (target.x, target.y)
        closest = sorted(chasers, key=lambda ch: ch.distance_to_point(target_pos))
        for rank, chaser in enumerate(closest):
            # A swing already under way is never cut off half finished: the token is spent
            # the moment the arm goes back, not when the blow lands.
            chaser.attack_token = rank < c.Entities.MAX_ACTIVE_ATTACKERS or chaser.attack_in_progress

    def _scenery_obstacles(self, start, goal, radius: float) -> list:
        """The solid wilderness standing between two points, as rectangles a detour can be
        costed round. Trunks and boulders touching each other are merged into one clump: a
        copse is one thing to walk round, and routing round each trunk in turn is what has
        a monster picking its way into the middle of the wood.

        Only looked for over a short stretch (`World.SCENERY_DETOUR_RANGE`). Beyond that a
        wood is not an obstacle, it is the ground, and `Monster._steer` deals with it a
        trunk at a time."""
        span = math.dist(start, goal)
        if not span or span > c.World.SCENERY_DETOUR_RANGE:
            return []
        rects = []
        seen = set()
        step = c.Scenery.INDEX_CELL / 2
        for i in range(int(span / step) + 1):
            t = min(1.0, i * step / span)
            x = start[0] + (goal[0] - start[0]) * t
            y = start[1] + (goal[1] - start[1]) * t
            for piece in self.scenery_near(x, y):
                if not piece.blocking_radius or id(piece) in seen:
                    continue
                seen.add(id(piece))
                reach = piece.blocking_radius + radius
                rects.append(pygame.Rect(piece.x - reach, piece.y - reach, reach * 2, reach * 2))
        return merge_rects(rects)

    def _detour_corner(self, start, goal, radius: float, rects=None, through=None, chaser=None):
        """The corner to head for when something solid sits between `start` and `goal`, or
        None when the way is clear.

        The way past a rectangle runs through at most two of its corners, so both ways round
        are costed in full and the first corner of the shorter one is returned. Costing the
        whole detour, rather than just picking the nearest corner, is what stops a monster
        oscillating between the near corner behind it and the far corner it should round.

        `rects` is what stands in the way: the buildings around `start` by default, or a
        room's furniture when the chase is happening inside one.

        `through` is the one obstacle the goal is allowed to be standing inside, and `chaser`
        the body being routed, which is remembered so it holds the way round it picked.
        """
        if rects is None:
            rects = [building.bounds for building in self.buildings_in_range(*start, c.World.CHUNK_SIZE)]
            # A town wall is the one obstacle in the world too long to steer round a step at
            # a time: each stretch runs from a corner tower to a gatepost, so rounding its
            # end is exactly walking to the nearest gate.
            rects += self.walls_near(*start)
            rects += self._scenery_obstacles(start, goal, radius)
        for obstacle in rects:
            margin = radius + 8
            rect = obstacle.inflate(margin * 2, margin * 2)
            # The one goal allowed to lie inside a shell is the doorway of the building that
            # shell belongs to: walking round that building would be walking away from its
            # door. Everything else is routed round even with the goal pressed against it,
            # which is what stops a chaser walking flat into the wall the player stands at.
            if through is not None and obstacle == through and rect.collidepoint(goal):
                continue
            # Tested against a hair-smaller rect so a leg running along an edge, corner to
            # corner, doesn't count as cutting through the building.
            inner = rect.inflate(-2, -2)
            if not inner.clipline(start, goal):
                continue
            # Whether a corner can be walked to is asked of the solid itself rather than of
            # the shell grown round it. The shell is where a body may stand, and a goal
            # standing against a wall is inside it: costed against the shell, every way
            # round came back barred and the chaser walked into the wall the player was
            # leaning on. Against the wall itself, the way round it is found.

            solid = obstacle.inflate(4, 4)
            corners = [rect.topleft, rect.topright, rect.bottomright, rect.bottomleft]
            committed = chaser.route_corner if chaser is not None else None
            best = held = None
            for i, first in enumerate(corners):
                if solid.clipline(start, first):
                    continue
                for last in (first, corners[(i + 1) % 4], corners[(i - 1) % 4]):
                    if last is not first and solid.clipline(first, last):
                        continue
                    if solid.clipline(last, goal):
                        continue
                    cost = math.dist(start, first) + math.dist(first, last) + math.dist(last, goal)
                    # Aim at the next corner along once this one is effectively reached.
                    target = first if math.dist(start, first) > radius + 6 else last
                    route = (cost, target, first)
                    if best is None or cost < best[0]:
                        best = route
                    if committed is not None and math.dist(first, committed) < 1 and (held is None or cost < held[0]):
                        held = route
            if best is not None:
                # The way round already picked is kept unless the other one is properly
                # shorter, not merely shorter this frame: from the middle of a wall the two
                # cost the same to within a pixel, and re-deciding had the chaser rocking
                # between them. Committing to a corner is `door_commit` for the open ground.
                if held is not None and best[0] >= held[0] * c.World.ROUTE_SWITCH_MARGIN:
                    best = held
                if chaser is not None:
                    chaser.route_corner = best[2]
                return best[1]
        # Nothing in the way: whatever corner was being walked to is behind them now.
        if chaser is not None:
            chaser.route_corner = None
        return None
