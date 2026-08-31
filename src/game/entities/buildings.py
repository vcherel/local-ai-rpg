from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.utils import random_coordinates
from game.entities.building_art import BuildingArt

if TYPE_CHECKING:
    from game.entities.items import Item

# The world's buildings, registered so systems without a World reference
# (e.g. quest item placement) can avoid dropping things inside a footprint.
_active_buildings: list[Building] = []


def set_active_buildings(buildings: list[Building]):
    global _active_buildings
    _active_buildings = buildings


def random_open_coordinates() -> tuple:
    """Random world coordinates guaranteed not to fall inside a building footprint."""
    x, y = random_coordinates()
    for _ in range(30):
        if not any(b.blocks(x, y, c.Entities.ITEM_SIZE) for b in _active_buildings):
            break
        x, y = random_coordinates()
    return x, y


# Which wall the front door sits in, as the outward direction of that wall. A building is
# still an axis-aligned rect: what turns is the facade, so a street can face the plaza from
# both sides instead of every house in the world opening south.
FACING_NORMALS = {"S": (0, 1), "N": (0, -1), "E": (1, 0), "W": (-1, 0)}


class _RoomSpace:
    """The room a `Building.interior_layout` is laid out in, and what has been put in it.

    Everything is in the canonical room whose door is in the bottom wall; `Building._place`
    turns it onto the wall the door is actually in afterwards. Furniture is added through
    `add` so it keeps its placement order, which is what `broken_props` indexes."""

    def __init__(self, rng: random.Random, floors: list[pygame.Rect], keep_clear: list[pygame.Rect]):
        self.rng = rng
        # The main room, which every arrangement below is written against ("against the back
        # wall", "by the door"), and every piece of floor there is, which is what a stray
        # crate may be dropped on: an L has a second one round the corner.
        self.floor = floors[0]
        self.floors = floors
        # Kept clear of furniture, so no way through the room is ever walled off: the
        # corridor in from the door, and the neck between the two halves of an L.
        self.keep_clear = keep_clear
        self.solids: list = []
        self.beds: list[pygame.Rect] = []
        self.crates: list[pygame.Rect] = []
        self.chest: pygame.Rect | None = None

    def add(self, rect: pygame.Rect, kind: str) -> pygame.Rect | None:
        """Put one piece of furniture down, stepped out of anything already there first.

        The arrangements below place their fixed pieces (a bed against the back wall, a
        shop's counter) by measurement rather than by search, so this is where they are kept
        off the corridor in from the door, out of the neck of an L, and off each other: a
        room is measured for one piece at a time, and in a narrow one the measurements
        overlap. Returns where the piece actually ended up, or None if there was nowhere for
        it to go."""
        placed = self._nudge_clear(rect)
        if placed is None:
            return None
        self.solids.append((placed, kind))
        return placed

    def _nudge_clear(self, rect: pygame.Rect) -> pygame.Rect | None:
        """The same piece, moved off whatever it is standing in, by the shortest step that
        still leaves it on the floor: a way through the room, or a piece already put down.

        Both are the same problem, so both are stepped out of the same way. One step can
        land the piece on the next thing along, which is why it is tried more than once."""
        blockers = self.keep_clear + [placed for placed, _kind in self.solids]
        for _ in range(4):
            band = next((zone for zone in blockers if rect.colliderect(zone)), None)
            if band is None:
                return rect
            moves = [
                (band.left - rect.right, 0),
                (band.right - rect.left, 0),
                (0, band.top - rect.bottom),
                (0, band.bottom - rect.top),
            ]
            candidates = [rect.move(dx, dy) for dx, dy in moves]
            candidates = [cand for cand in candidates if any(floor.contains(cand) for floor in self.floors)]
            if not candidates:
                return None
            rect = min(candidates, key=lambda cand: abs(cand.x - rect.x) + abs(cand.y - rect.y))
        return None

    @property
    def crowded_side(self) -> int:
        """Which side of the main room the neck of an L runs along: -1 left, 1 right, 0 for
        a plain box. An arrangement that has a choice of sides takes the other one, so the
        bed and the chest are put down where nothing has to be nudged out of the way."""
        for clear in self.keep_clear[1:]:
            return -1 if clear.centerx < self.floor.centerx else 1
        return 0

    def on_floor(self, rect: pygame.Rect) -> bool:
        """Whether a piece this size and place stands on the floor at all: inside one of the
        room's rects and out of every way through it."""
        if not any(floor.contains(rect) for floor in self.floors):
            return False
        return not any(rect.colliderect(clear) for clear in self.keep_clear)

    def fits(self, rect: pygame.Rect) -> bool:
        if not self.on_floor(rect):
            return False
        return all(not rect.colliderect(other.inflate(40, 40)) for other, _ in self.solids)

    def try_place(self, w: int, h: int) -> pygame.Rect | None:
        """A free spot for a piece this size, or None once fifty tries have failed. Rolled
        over every piece of floor by area, so the wing of an L is furnished too rather than
        standing empty behind the room the arrangement was written for."""
        floors = [floor for floor in self.floors if floor.width > w + 20 and floor.height > h + 20]
        if not floors:
            return None
        weights = [floor.width * floor.height for floor in floors]
        for _ in range(50):
            floor = self.rng.choices(floors, weights=weights)[0]
            rect = pygame.Rect(
                self.rng.randint(floor.left + 10, floor.right - 10 - w),
                self.rng.randint(floor.top + 10, floor.bottom - 10 - h),
                w,
                h,
            )
            if self.fits(rect):
                return rect
        return None

    def add_crates(self, count: int):
        """Crates are always placed so their indices stay the same across saves; the broken
        ones are dropped from the collision set later but keep their place in the list."""
        for _ in range(count):
            crate = self.try_place(40, 40)
            if crate:
                self.crates.append(self.add(crate, "crate") or crate)


def _subtract(seg: pygame.Rect, hole: pygame.Rect) -> list[pygame.Rect]:
    """What is left of one wall segment once a hole is cut through it, as up to two rects.

    Segments are thin and axis aligned, so the cut only ever splits the long axis: this is
    how the wall between the two halves of an L is taken out without rebuilding the shell
    as a polygon."""
    if not seg.colliderect(hole):
        return [seg]
    pieces = []
    if seg.width >= seg.height:
        if hole.left > seg.left:
            pieces.append(pygame.Rect(seg.left, seg.top, hole.left - seg.left, seg.height))
        if hole.right < seg.right:
            pieces.append(pygame.Rect(hole.right, seg.top, seg.right - hole.right, seg.height))
    else:
        if hole.top > seg.top:
            pieces.append(pygame.Rect(seg.left, seg.top, seg.width, hole.top - seg.top))
        if hole.bottom < seg.bottom:
            pieces.append(pygame.Rect(seg.left, hole.bottom, seg.width, seg.bottom - hole.bottom))
    return pieces


class Building(BuildingArt):
    def __init__(self, x, y, kind: str, w=None, h=None, facing: str = "S"):
        w_range, h_range = c.Buildings.SIZES[kind]
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.x = x
        self.y = y
        self.w = w if w is not None else random.randint(*w_range)
        self.h = h if h is not None else random.randint(*h_range)
        # Which way the front is. Set by the village layout so a door opens onto the plaza
        # (game/entities/village.py) and persisted, since it cannot be rederived from the id:
        # the same house would face a different way in a different slot.
        self.facing = facing
        self.name = None  # Only the landmark gets an LLM-generated name
        self.looted = False
        # Indices into interior_layout()["props"]: every piece of furniture already taken
        # apart, crates and tables alike.
        self.broken_props: set = set()
        self.broken_windows: set = set()  # indices into window_rects() already shattered
        # Which settlement's tier lights this one's windows after dark, or -1 for a building
        # standing out in the wilderness, which is never lit. Session-only and set by
        # whoever puts the building in the world (`village._build`, `World._light_windows`):
        # a house does not know its village, it knows how well kept the street is.
        self.village_tier: int = -1
        self._lamps: frozenset | None = None
        # Damage taken by a crate/window still standing, by index. Session-only, like the
        # loot on the floor: what a save has to remember is what finally broke, not how
        # far along the player got with the rest.
        self.prop_hp: dict = {}
        self.window_hp: dict = {}
        # The front door, shut until somebody opens it. `door_open` and `door_broken` are
        # persisted (a door left open stays open, a door beaten down is a hole for good);
        # the damage a door still standing has taken is session-only, like a crate's.
        self.door_open = False
        self.door_broken = False
        self.door_hp = c.Buildings.DOOR_HP
        # Whether this one is locked is rolled from the id on first ask and kept, like the
        # style and the wing; `door_unlocked` is the player having let themselves out from
        # the inside, which is persisted because a house broken into stays broken into.
        self._locked: bool | None = None
        self.door_unlocked = False
        # Loot dropped on the floor by smashed crates, waiting to be picked up. Not
        # persisted: it lives only for the current play session, same as indoor monsters.
        self.dropped_items: list[Item] = []
        self._layout = None
        self._ruin = None
        # The second rect an L-shaped building is built of, rolled from the id on first
        # ask like the style: None until asked, False once rolled and refused.
        self._wing: pygame.Rect | bool | None = None
        self._canon_wing: pygame.Rect | None = None
        # Everything derived from where this building stands and how it is built, worked out
        # once and kept: the footprint, the floors, and the wall shell with its doorway.
        # `blocks` is asked hundreds of times a frame by anything that walks, and rebuilding
        # a dozen rects per question is what made a street of villagers cost more than the
        # street. `reset_geometry` drops the lot; the shell also depends on whether the door
        # is shut, which is the one part of it that changes without the building moving.
        self._rect: pygame.Rect | None = None
        self._floors: list[pygame.Rect] | None = None
        self._segments: list[pygame.Rect] | None = None
        self._segments_door: tuple | None = None
        # How this one is built (roof material and form, wall tint, extras). Rolled from
        # the building's own id on first draw, so a street is a row of different houses
        # and each of them keeps its look for good.
        self._style = None
        # The house painted onto its own surface (`BuildingArt._shell`), and where in the
        # world its top left corner sits. Everything that holds still is in there and is
        # blitted from then on; the door, the windows and the smoke are drawn over it.
        self._shell_surface: pygame.Surface | None = None
        self._shell_origin: tuple[int, int] = (0, 0)

    @property
    def rect(self) -> pygame.Rect:
        if self._rect is None:
            self._rect = pygame.Rect(round(self.x - self.w / 2), round(self.y - self.h / 2), self.w, self.h)
        return self._rect

    @property
    def has_door(self) -> bool:
        return self.kind != "landmark"

    def wing(self) -> pygame.Rect | None:
        """The second rect that makes this building an L, or None for a plain box.

        Rolled from the building's own id like its roof, so it survives a save without a
        field of its own, and described in the canonical room (door at the bottom) before
        being turned onto the real facing: a wing always grows out of the *back* half of one
        side, which is what keeps the facade one straight wall. The door, the windows, the
        awning and the doorstep therefore know nothing about any of this."""
        if self._wing is not None:
            return self._wing or None
        rng = random.Random(f"wing:{self.id}")
        if self.kind not in c.Buildings.WING_KINDS or rng.random() > c.Buildings.WING_CHANCE:
            self._wing = False
            return None
        canon = self._canon_rect()
        depth = rng.randint(*c.Buildings.WING_DEPTH)
        length = round(canon.height * rng.uniform(*c.Buildings.WING_LENGTH_FRAC))
        side = rng.choice((-1, 1))
        cwing = pygame.Rect(0, 0, depth, length)
        if side > 0:
            cwing.topleft = (canon.right, canon.top)
        else:
            cwing.topright = (canon.left, canon.top)
        self._canon_wing = cwing
        self._wing = self._snap_wing(self._place(cwing, canon, self.rect))
        return self._wing

    def _snap_wing(self, wing: pygame.Rect) -> pygame.Rect:
        """The wing pushed back flush against the block it grows out of.

        `_place` turns the canonical room by rounding a centre, and a wing whose depth does
        not share the main block's parity lands a pixel off it: the two halves are then
        drawn with a hairline of grass between them and the wall shell has a seam in it
        that nothing ever closes. A wing shares a whole edge with its block or it is not
        one, so the edge is set rather than computed."""
        rect = self.rect
        if abs(wing.centerx - rect.centerx) > abs(wing.centery - rect.centery):
            wing.left = rect.right if wing.centerx > rect.centerx else rect.left - wing.width
            wing.top = (
                rect.top if abs(wing.top - rect.top) <= abs(wing.bottom - rect.bottom) else rect.bottom - wing.height
            )
        else:
            wing.top = rect.bottom if wing.centery > rect.centery else rect.top - wing.height
            wing.left = (
                rect.left if abs(wing.left - rect.left) <= abs(wing.right - rect.right) else rect.right - wing.width
            )
        return wing

    def _canon_opening(self) -> pygame.Rect | None:
        """`_wing_opening` in the canonical room, where the wing is always out to one side:
        what the furniture is laid out over before `_place` turns the room onto its facing."""
        if self.wing() is None:
            return None
        wall = c.Buildings.WALL_THICKNESS
        canon, cwing = self._canon_rect(), self._canon_wing
        opening = cwing.inflate(-wall * 2, -wall * 2)
        opening.width += wall * 3
        if cwing.left >= canon.right - 1:
            opening.left = cwing.left - wall * 2
        return opening

    def reset_geometry(self):
        """Forget everything derived from where this building stands: its wing and its
        interior. Called by the village layout, which moves a building after building it."""
        self._wing = None
        self._canon_wing = None
        self._layout = None
        self._rect = None
        self._floors = None
        self._segments = None
        self._shell_surface = None
        self._lamps = None

    def _canon_rect(self) -> pygame.Rect:
        """This building's own footprint seen with its door in the bottom wall: the frame
        every layout is written in before `_place` turns it onto the real facing."""
        canon = self.rect.copy()
        if self.facing in ("E", "W"):
            canon.size = (self.rect.height, self.rect.width)
        return canon

    def footprint(self) -> list[pygame.Rect]:
        """Every rect this building is built of: one for a plain box, two for an L. The
        walls, the floor and the collision shell are all built off this rather than off
        `rect`, which stays the main block the facade hangs on."""
        wing = self.wing()
        return [self.rect] if wing is None else [self.rect, wing]

    @property
    def bounds(self) -> pygame.Rect:
        """The box the whole building fits in, wing included. What anything outside this
        file wants when it asks where the building is: the chunk index, a chase detour, the
        clearances that keep trees and bear traps off it."""
        wing = self.wing()
        return self.rect if wing is None else self.rect.union(wing)

    def _wing_opening(self) -> pygame.Rect | None:
        """The gap between the two halves of an L: the wing's own floor, carried far enough
        into the main room to swallow the wall that would otherwise stand between them.

        One rect does both jobs. Subtracted from the wall shell it is the opening; taken as
        a floor it is what joins the two rooms into one, the same trick a tunnel's corridors
        use to stay walkable across a doorway.

        Measured off the wing where it actually stands rather than turned out of the
        canonical room a second time: two roundings of the same rect are two rects, and the
        one the walls are cut with has to be the one the floor is drawn from."""
        wing = self.wing()
        if wing is None:
            return None
        wall = c.Buildings.WALL_THICKNESS
        rect = self.rect
        # How far the opening reaches back into the main block: past its wall, so the two
        # rooms are one space rather than two with a shared doorway.
        over = wall * 2
        if wing.left >= rect.right:
            box = (rect.right - over, wing.top + wall, wing.right - wall, wing.bottom - wall)
        elif wing.right <= rect.left:
            box = (wing.left + wall, wing.top + wall, rect.left + over, wing.bottom - wall)
        elif wing.top >= rect.bottom:
            box = (wing.left + wall, rect.bottom - over, wing.right - wall, wing.bottom - wall)
        else:
            box = (wing.left + wall, wing.top + wall, wing.right - wall, rect.top + over)
        return pygame.Rect(box[0], box[1], box[2] - box[0], box[3] - box[1])

    def outward(self) -> tuple:
        """The unit vector pointing out of the front wall. Everything about the facade (the
        door, its trigger zone, the windows, the doorstep, an awning, the point a monster
        lines up on) is written as an offset along this rather than as "the bottom"."""
        return FACING_NORMALS[self.facing]

    def _facade_band(self, depth: int, inset: int = 0) -> pygame.Rect:
        """A band `depth` deep lying along the front wall, `inset` in from its outer face.
        The one place the four facings are turned into a rect."""
        nx, ny = self.outward()
        r = self.rect
        if nx:
            left = r.right - inset - depth if nx > 0 else r.left + inset
            return pygame.Rect(left, r.top, depth, r.height)
        top = r.bottom - inset - depth if ny > 0 else r.top + inset
        return pygame.Rect(r.left, top, r.width, depth)

    def _facade_slot(self, width: int, depth: int, offset: float, inset: int = 0) -> pygame.Rect:
        """A `width` by `depth` piece of the front wall, `offset` along it from the middle
        (positive is clockwise round the building), lying `inset` in from the outer face."""
        band = self._facade_band(depth, inset)
        nx, _ny = self.outward()
        slot = pygame.Rect(0, 0, depth if nx else width, width if nx else depth)
        if nx:
            slot.center = (band.centerx, round(self.y + offset))
        else:
            slot.center = (round(self.x + offset), band.centery)
        return slot

    def door_front(self) -> tuple:
        """The spot on the doorstep, outside the wall: where somebody waits to be let in."""
        nx, ny = self.outward()
        door = self.door_rect()
        return (door.centerx + nx * 60, door.centery + ny * 60)

    def door_rect(self) -> pygame.Rect:
        """The door leaf itself, filling the gap in the front wall."""
        return self._facade_slot(c.Buildings.DOOR_WIDTH, c.Buildings.WALL_THICKNESS, 0)

    @property
    def door_closed(self) -> bool:
        """True while the doorway is shut: a wall to anything trying to walk through it."""
        return self.has_door and not self.door_open and not self.door_broken

    @property
    def locked(self) -> bool:
        """True while the front door will not open for the player at all.

        Rolled from the building's own id, so the same house is locked every time and a
        street is worth learning rather than worth trying. A locked door is not a tougher
        door: it is a wall with a window beside it, and the window is the way in
        (`window_gaps`). Once the player is inside, they unbar it themselves and it is a
        door like any other from then on."""
        if not self.has_door or self.door_broken or self.door_unlocked:
            return False
        if self._locked is None:
            self._locked = (
                self.kind in c.Buildings.LOCK_KINDS
                and random.Random(f"lock:{self.id}").random() < c.Buildings.LOCK_CHANCE
            )
        return self._locked

    def unlock(self):
        """Unbar the door from the inside, for good. What somebody who climbed in through
        the window does on their way out, so a house broken into is never a room the player
        has to leave the way they came."""
        self.door_unlocked = True

    @property
    def door_key(self) -> str:
        """Identity of this door for `core.damage_fx`, which is keyed by string."""
        return f"{self.id}:door"

    def door_overlaps(self, x, y, radius: float) -> bool:
        """Whether a body of `radius` standing at (x, y) is in the doorway. The one question
        behind both halves of never shutting a door on somebody: the prompt only ever offers
        to *open* the door somebody is standing in, and shutting one steps them out of it."""
        if not self.has_door:
            return False
        return self.door_rect().inflate(radius * 2, radius * 2).collidepoint(x, y)

    def clear_of_door(self, x, y, radius: float) -> tuple:
        """(x, y) stepped out of the doorway along the front wall's own normal, to whichever
        side of it the body is already nearer.

        Searching outward in rings for somewhere free (`World.free_spot_near`) finds nothing
        when the doorway is the only gap in the wall and the room behind it is furnished,
        which is how a door used to shut with the player sealed inside its frame. The way
        out of a doorway is never a search: it is one step in or one step out."""
        nx, ny = self.outward()
        door = self.door_rect()
        depth = c.Buildings.WALL_THICKNESS / 2 + radius + 1
        side = 1.0 if (x - door.centerx) * nx + (y - door.centery) * ny >= 0 else -1.0
        if nx:
            return door.centerx + nx * side * depth, y
        return x, door.centery + ny * side * depth

    def toggle_door(self) -> bool:
        """Open a shut door or shut an open one. Returns the new open state; a door that has
        been beaten down is past opening or closing and stays as it is, and a locked one
        does not answer at all until somebody inside has unbarred it."""
        if not self.has_door or self.door_broken or self.locked:
            return self.door_open
        self.door_open = not self.door_open
        return self.door_open

    def damage_door(self, damage: int) -> bool:
        """Land a blow on the door. True on the blow that finally puts it through: from then
        on the doorway is a hole, exactly like the gap every building used to have."""
        if not self.door_closed:
            return False
        self.door_hp -= damage
        if self.door_hp > 0:
            return False
        self.door_hp = 0
        self.door_broken = True
        return True

    def _window_offsets(self) -> list[float]:
        """Where along the front wall the two windows sit, either side of the door. The one
        place that is decided, so the pane that is drawn and the hole a broken one leaves in
        the wall are always the same slot."""
        if not self.has_door:
            return []
        offset = c.Buildings.DOOR_WIDTH / 2 + c.Buildings.WINDOW_X_FROM_DOOR + c.Buildings.WINDOW_W / 2
        return [side * offset for side in (-1, 1)]

    def window_rects(self) -> list[pygame.Rect]:
        """Two windows flanking the door on the front facade, in world coordinates.
        The landmark has no facade at all, so it gets none."""
        depth = c.Buildings.WINDOW_H
        inset = c.Buildings.WINDOW_Y_FROM_BOTTOM - depth
        return [self._facade_slot(c.Buildings.WINDOW_W, depth, offset, inset) for offset in self._window_offsets()]

    def window_gaps(self) -> list[pygame.Rect]:
        """The holes the shattered windows leave in the wall: one slot through the full
        thickness of the facade per broken pane.

        The pane itself is drawn a little way inside the wall, the way everything on a
        facade is; what the wall actually loses is the whole depth of it, because a window
        somebody has put through is a way into the house and not a decoration."""
        wall = c.Buildings.WALL_THICKNESS
        return [
            self._facade_slot(c.Buildings.WINDOW_W, wall, offset)
            for index, offset in enumerate(self._window_offsets())
            if index in self.broken_windows
        ]

    def _wall_segments(self) -> list[pygame.Rect]:
        """The building's solid shell as a few thin rects, with a permanent door-sized
        gap cut from the front wall. The landmark ruin has no door, so its whole
        footprint stays one solid block.

        An L is the same shell twice over, minus the wall the two halves would otherwise
        have between them: `_wing_opening` is cut out of every segment, which turns two
        boxes standing against each other into one room with a corner in it.

        Kept once built, and rebuilt only when the door opens or comes down or a window is
        put through: a shut door is part of the shell and an open one is a gap in it, a
        broken window is a second gap, and nothing else about a standing building's walls
        ever changes."""
        state = (self.door_closed, len(self.broken_windows))
        if self._segments is not None and self._segments_door == state:
            return self._segments
        self._segments_door = state
        r = self.rect
        if not self.has_door:
            self._segments = [r]
            return self._segments
        wall = c.Buildings.WALL_THICKNESS
        door = self.door_rect()
        nx, _ny = self.outward()
        # Three whole walls plus the two stubs either side of the doorway, whichever wall
        # the doorway happens to be in.
        segments = [
            pygame.Rect(r.left, r.top, r.width, wall),
            pygame.Rect(r.left, r.bottom - wall, r.width, wall),
            pygame.Rect(r.left, r.top, wall, r.height),
            pygame.Rect(r.right - wall, r.top, wall, r.height),
        ]
        segments = [seg for seg in segments if not seg.colliderect(door)]
        if nx:
            segments.append(pygame.Rect(door.left, r.top, wall, door.top - r.top))
            segments.append(pygame.Rect(door.left, door.bottom, wall, r.bottom - door.bottom))
        else:
            segments.append(pygame.Rect(r.left, door.top, door.left - r.left, wall))
            segments.append(pygame.Rect(door.right, door.top, r.right - door.right, wall))

        wing = self.wing()
        if wing is not None:
            segments += [
                pygame.Rect(wing.left, wing.top, wing.width, wall),
                pygame.Rect(wing.left, wing.bottom - wall, wing.width, wall),
                pygame.Rect(wing.left, wing.top, wall, wing.height),
                pygame.Rect(wing.right - wall, wing.top, wall, wing.height),
            ]
            opening = self._wing_opening()
            segments = [piece for seg in segments for piece in _subtract(seg, opening)]

        # A shut door is part of the shell; open it or break it and the gap is back.
        if self.door_closed:
            segments.append(self.door_rect())
        # And every window somebody has put through is a hole in it, which is what makes
        # breaking one the way into a house whose door will not open.
        for gap in self.window_gaps():
            segments = [piece for seg in segments for piece in _subtract(seg, gap)]
        self._segments = segments
        return segments

    def blocks(self, x, y, radius) -> bool:
        """True if a point (with this radius) overlaps the wall shell (the door gap is
        always walkable) or a piece of furniture inside the room."""
        for seg in self._wall_segments():
            nearest_x = min(max(x, seg.left), seg.right)
            nearest_y = min(max(y, seg.top), seg.bottom)
            if math.hypot(x - nearest_x, y - nearest_y) < radius:
                return True
        if self.has_door and self.contains_point(x, y):
            for rect, _kind in self.interior_layout()["solids"]:
                nearest_x = min(max(x, rect.left), rect.right)
                nearest_y = min(max(y, rect.top), rect.bottom)
                if math.hypot(x - nearest_x, y - nearest_y) < radius:
                    return True
        return False

    def covers(self, x, y, radius: float = 0.0) -> bool:
        """Whether a body of `radius` standing here is on any part of this building, wing,
        walls and floor alike.

        Not the same question as `blocks`, which is about walking into something and
        answers False for the open floor of a room: this is the one anything being *placed*
        has to ask, and asking the other one is how a barrel came to stand in the back room
        of an L-shaped house."""
        return any(rect.inflate(radius * 2, radius * 2).collidepoint(x, y) for rect in self.footprint())

    def doorstep(self, depth: float, width: float | None = None) -> pygame.Rect | None:
        """The clear ground in front of the front door: the doorway plus a shoulder either
        side, `depth` out from the wall it is in.

        One rect, asked for by everything that has to leave a door usable: the village
        layout pushes a neighbour off one, and nothing is planted or scattered in one. A
        door you cannot walk up to is a room the player never sees the inside of."""
        if not self.has_door:
            return None
        return self._facade_slot(width or c.Villages.DOORSTEP_WIDTH, round(depth), 0, -round(depth))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "facing": self.facing,
            "name": self.name,
            "looted": self.looted,
            "broken_props": sorted(self.broken_props),
            "broken_windows": sorted(self.broken_windows),
            "door_unlocked": self.door_unlocked,
            "door_open": self.door_open,
            "door_broken": self.door_broken,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Building:
        building = cls(data["x"], data["y"], data["kind"], data["w"], data["h"], data.get("facing", "S"))
        building.id = data["id"]
        building.name = data["name"]
        building.looted = data["looted"]
        building.broken_props = set(data.get("broken_props", []))
        building.broken_windows = set(data.get("broken_windows", []))
        building.door_unlocked = data.get("door_unlocked", False)
        building.door_open = data.get("door_open", False)
        building.door_broken = data.get("door_broken", False)
        return building

    # ------------------------------------------------------------------ interior

    def interior_rect(self) -> pygame.Rect:
        """The main room's walkable floor, in world coordinates: the block the facade hangs
        on, inset by the wall shell. A wing is a second floor beside it (`interior_rects`)."""
        wall = c.Buildings.WALL_THICKNESS
        return self.rect.inflate(-wall * 2, -wall * 2)

    def interior_rects(self) -> list[pygame.Rect]:
        """Every piece of floor in the building. Two of them for an L, overlapping where
        the wing meets the main room so the union is one connected space to walk over."""
        if self._floors is None:
            opening = self._wing_opening()
            self._floors = [self.interior_rect()] if opening is None else [self.interior_rect(), opening]
        return self._floors

    def contains_point(self, x, y) -> bool:
        """True once (x, y) has stepped past the wall onto this building's floor."""
        return self.has_door and any(floor.collidepoint(x, y) for floor in self.interior_rects())

    def _place(self, rect: pygame.Rect, canon: pygame.Rect, floor: pygame.Rect) -> pygame.Rect:
        """Carry one piece of furniture out of the canonical room (door at the bottom) into
        the real one, turned to match the facing. A room laid out four times over, once per
        wall the door might be in, is four chances to get a bed placed across a doorway; laid
        out once and turned, it is the same room seen from a different side."""
        u = rect.centerx - canon.centerx
        v = rect.centery - canon.centery
        if self.facing == "S":
            cu, cv, w, h = u, v, rect.width, rect.height
        elif self.facing == "N":
            cu, cv, w, h = -u, -v, rect.width, rect.height
        elif self.facing == "E":
            cu, cv, w, h = v, -u, rect.height, rect.width
        else:
            cu, cv, w, h = -v, u, rect.height, rect.width
        out = pygame.Rect(0, 0, w, h)
        out.center = (round(floor.centerx + cu), round(floor.centery + cv))
        return out

    def interior_layout(self) -> dict:
        """Furniture for this building's single room, deterministic from the building id.

        Laid out in a canonical room whose door is in the bottom wall, then turned onto the
        wall this building's door is actually in (`_place`), so every arrangement below can
        go on saying "by the door" and "against the back wall" and mean it."""
        if self._layout is not None:
            return self._layout

        rng = random.Random(self.id)
        room = self.interior_rect()
        # The same room seen with the door at the bottom: a facade on the long side swaps
        # the two dimensions.
        floor = room.copy()
        if self.facing in ("E", "W"):
            floor.size = (room.height, room.width)

        # Keep a corridor from the door to the middle of the room clear of furniture.
        corridor_w = c.Buildings.DOOR_WIDTH + 40
        door_path = pygame.Rect(
            round(floor.centerx - corridor_w / 2), floor.centery, corridor_w, floor.bottom - floor.centery
        )
        opening = self._canon_opening()
        floors = [floor] if opening is None else [floor, opening]
        keep_clear = [door_path]
        if opening is not None:
            # The way through to the wing, kept clear exactly as the way in from the door
            # is: a table dropped in the neck of an L walls half the building off.
            keep_clear.append(opening.clip(floor).inflate(c.Buildings.WING_NECK_CLEAR, c.Buildings.WING_NECK_CLEAR))
        space = _RoomSpace(rng, floors, keep_clear)

        if self.kind == "house":
            self._lay_out_house(space)
        elif self.kind == "shop":
            self._lay_out_shop(space)
        elif self.kind == "tavern":
            self._lay_out_tavern(space)

        rug = pygame.Rect(0, 0, 130, 80)
        rug.center = (round(floor.centerx), round(floor.centery - 25))

        # Everything in the room that can be taken apart, in placement order: that order is
        # what `broken_props` indexes, so it has to be built before anything is dropped for
        # having been smashed already.
        props = [(rect, kind) for rect, kind in space.solids if kind in c.Buildings.FURNITURE_HP]
        broken = {id(props[i][0]) for i in self.broken_props if i < len(props)}
        # Wreckage no longer blocks movement, but stays in `props` so its debris still draws
        # and its index keeps matching the saved broken set.
        solids = [(rect, kind) for rect, kind in space.solids if id(rect) not in broken]

        def place(rect: pygame.Rect) -> pygame.Rect:
            return self._place(rect, floor, room)

        self._layout = {
            "solids": [(place(rect), kind) for rect, kind in solids],
            # A bed comes apart like any other stick of furniture, and a broken one is not a
            # bed any more: it drops out of the list the sleep prompt is offered from, so a
            # room of wreckage is a room with nowhere to sleep.
            "beds": [place(bed) for bed in space.beds if id(bed) not in broken],
            "crates": [place(crate) for crate in space.crates],
            "props": [(place(rect), kind) for rect, kind in props],
            "chest": place(space.chest) if space.chest is not None else None,
            "rug": place(rug),
        }
        return self._layout

    @staticmethod
    def _lay_out_house(space: _RoomSpace):
        floor = space.floor
        bed_left = space.crowded_side > 0 if space.crowded_side else space.rng.random() < 0.5
        bed_x = floor.left + 20 if bed_left else floor.right - 90
        # The household's own bed, which the player can sleep in for nothing at all,
        # provided nobody outside sees them do it (Game._sleep_in_bed).
        house_bed = space.add(pygame.Rect(bed_x, floor.top + 15, 70, 100), "bed")
        if house_bed:
            space.beds.append(house_bed)
        space.add(pygame.Rect(round(floor.centerx - 50), floor.top + 6, 100, 22), "shelf")
        chest_x = floor.right - 55 if bed_left else floor.left + 20
        space.chest = space.add(pygame.Rect(chest_x, floor.bottom - 70, 40, 32), "chest")
        table = space.try_place(80, 60)
        if table:
            table = space.add(table, "table") or table
            for chair_x in (table.left - 30, table.right + 8):
                chair = pygame.Rect(chair_x, table.centery - 13, 26, 26)
                if space.on_floor(chair):
                    space.add(chair, "chair")

    @staticmethod
    def _lay_out_shop(space: _RoomSpace):
        floor = space.floor
        space.add(pygame.Rect(round(floor.centerx - 85), floor.top + 90, 170, 32), "counter")
        space.add(pygame.Rect(floor.left + 25, floor.top + 6, 100, 22), "shelf")
        space.add(pygame.Rect(floor.right - 125, floor.top + 6, 100, 22), "shelf")

        space.add_crates(3)

    @staticmethod
    def _lay_out_tavern(space: _RoomSpace):
        floor = space.floor
        nb_beds = space.rng.randint(3, 4)
        bed_w, bed_h = 60, 95
        span = floor.width - 80 - bed_w
        for i in range(nb_beds):
            bed = space.add(
                pygame.Rect(floor.left + 40 + round(span * i / max(1, nb_beds - 1)), floor.top + 15, bed_w, bed_h),
                "bed",
            )
            if bed:
                space.beds.append(bed)
        space.add(pygame.Rect(floor.right - 190, floor.bottom - 80, 170, 32), "counter")
        for _ in range(2):
            table = space.try_place(80, 60)
            if table:
                space.add(table, "table")
        space.add_crates(2)

    def prop_key(self, index: int) -> str:
        """Identity of one piece of furniture for `core.damage_fx`. A table is an index into
        this building's layout rather than an object of its own, so the registry that
        remembers recent blows needs a string to hang them on."""
        return f"{self.id}:prop:{index}"

    def damage_prop_at(self, pos, hit_radius, damage: int) -> tuple | None:
        """Land a blow on the nearest intact piece of furniture a swing reaches.

        Returns (index, rect, kind, destroyed), or None if the swing reached nothing. Every
        stick of furniture in a room comes apart under enough blows, not only the crates: a
        table takes more than a chair and only the blow that finishes one reports
        `destroyed`, which is also when it stops blocking movement.
        """
        layout = self.interior_layout()
        px, py = pos
        best = None
        for idx, (rect, kind) in enumerate(layout["props"]):
            if idx in self.broken_props:
                continue
            dist = math.hypot(px - rect.centerx, py - rect.centery)
            if dist < hit_radius + max(rect.width, rect.height) / 2 and (best is None or dist < best[1]):
                best = (idx, dist, rect, kind)
        if best is None:
            return None
        idx, _dist, rect, kind = best

        remaining = self.prop_hp.get(idx, c.Buildings.FURNITURE_HP[kind]) - damage
        if remaining > 0:
            self.prop_hp[idx] = remaining
            return idx, rect, kind, False
        self.prop_hp.pop(idx, None)
        self.broken_props.add(idx)
        # Drop it from the cached collision set so the player can walk through the wreckage
        # now, and from the beds, since nobody sleeps in a pile of splinters.
        self._layout["solids"] = [(other, other_kind) for other, other_kind in self._layout["solids"] if other != rect]
        self._layout["beds"] = [bed for bed in self._layout["beds"] if bed != rect]
        return idx, rect, kind, True
