from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING, List, Optional

import pygame

import core.constants as c
from core.damage_fx import draw_cracks, get_damage_fx
from core.utils import random_coordinates

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.items import Item

# The world's buildings, registered so systems without a World reference
# (e.g. quest item placement) can avoid dropping things inside a footprint.
_active_buildings: List["Building"] = []


def set_active_buildings(buildings: List["Building"]):
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


def draw_label(screen: pygame.Surface, text: str, center: tuple):
    label = c.Fonts.small.render(text, True, c.Colors.WHITE)
    label_rect = label.get_rect(center=center)
    bg_rect = label_rect.inflate(12, 6)
    bg_surface = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(bg_surface, c.Colors.TRANSPARENT, bg_surface.get_rect(), border_radius=6)
    screen.blit(bg_surface, bg_rect)
    screen.blit(label, label_rect)


# Which wall the front door sits in, as the outward direction of that wall. A building is
# still an axis-aligned rect: what turns is the facade, so a street can face the plaza from
# both sides instead of every house in the world opening south.
FACING_NORMALS = {"S": (0, 1), "N": (0, -1), "E": (1, 0), "W": (-1, 0)}


class Building:
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
        # Loot dropped on the floor by smashed crates, waiting to be picked up. Not
        # persisted: it lives only for the current play session, same as indoor monsters.
        self.dropped_items: List["Item"] = []
        self._layout = None
        self._ruin = None
        # How this one is built (roof material and form, wall tint, extras). Rolled from
        # the building's own id on first draw, so a street is a row of different houses
        # and each of them keeps its look for good.
        self._style = None

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x - self.w / 2), round(self.y - self.h / 2), self.w, self.h)

    @property
    def has_door(self) -> bool:
        return self.kind != "landmark"

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

    def door_zone(self) -> Optional[pygame.Rect]:
        """Trigger area straddling the front wall; walking into it enters the building."""
        if not self.has_door:
            return None
        depth = c.Buildings.DOOR_DEPTH
        door = self.door_rect()
        nx, _ny = self.outward()
        zone = pygame.Rect(0, 0, depth * 2 if nx else door.width, door.height if nx else depth * 2)
        zone.center = door.center
        return zone

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
    def door_key(self) -> str:
        """Identity of this door for `core.damage_fx`, which is keyed by string."""
        return f"{self.id}:door"

    def toggle_door(self) -> bool:
        """Open a shut door or shut an open one. Returns the new open state; a door that has
        been beaten down is past opening or closing and stays as it is."""
        if not self.has_door or self.door_broken:
            return True
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

    def window_rects(self) -> List[pygame.Rect]:
        """Two windows flanking the door on the front facade, in world coordinates.
        The landmark has no facade at all, so it gets none."""
        if not self.has_door:
            return []
        long_side, depth = c.Buildings.WINDOW_W, c.Buildings.WINDOW_H
        inset = c.Buildings.WINDOW_Y_FROM_BOTTOM - depth
        offset = c.Buildings.DOOR_WIDTH / 2 + c.Buildings.WINDOW_X_FROM_DOOR + long_side / 2
        return [self._facade_slot(long_side, depth, side * offset, inset) for side in (-1, 1)]

    def _wall_segments(self) -> List[pygame.Rect]:
        """The building's solid shell as a few thin rects, with a permanent door-sized
        gap cut from the front wall. The landmark ruin has no door, so its whole
        footprint stays one solid block."""
        r = self.rect
        if not self.has_door:
            return [r]
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
        # A shut door is part of the shell; open it or break it and the gap is back.
        if self.door_closed:
            segments.append(self.door_rect())
        return segments

    def blocks(self, x, y, radius) -> bool:
        """True if a point (with this radius) overlaps the wall shell (the door gap is
        always walkable) or a piece of furniture inside the room."""
        for seg in self._wall_segments():
            nearest_x = min(max(x, seg.left), seg.right)
            nearest_y = min(max(y, seg.top), seg.bottom)
            if math.hypot(x - nearest_x, y - nearest_y) < radius:
                return True
        if self.has_door and self.interior_rect().collidepoint(x, y):
            for rect, _kind in self.interior_layout()["solids"]:
                nearest_x = min(max(x, rect.left), rect.right)
                nearest_y = min(max(y, rect.top), rect.bottom)
                if math.hypot(x - nearest_x, y - nearest_y) < radius:
                    return True
        return False

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
        building.door_open = data.get("door_open", False)
        building.door_broken = data.get("door_broken", False)
        return building

    # ------------------------------------------------------------------ interior

    def interior_rect(self) -> pygame.Rect:
        """The walkable floor, in world coordinates: the footprint inset by the wall shell."""
        wall = c.Buildings.WALL_THICKNESS
        return self.rect.inflate(-wall * 2, -wall * 2)

    def contains_point(self, x, y) -> bool:
        """True once (x, y) has stepped past the wall onto this building's floor."""
        return self.has_door and self.interior_rect().collidepoint(x, y)

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
        floor = pygame.Rect(room.left, room.top, room.width, room.height)
        if self.facing in ("E", "W"):
            floor.size = (room.height, room.width)
        solids: list = []
        beds: List[pygame.Rect] = []
        crates: List[pygame.Rect] = []
        chest = None

        # Keep a corridor from the door to the middle of the room clear of furniture.
        corridor_w = c.Buildings.DOOR_WIDTH + 40
        door_path = pygame.Rect(
            round(floor.centerx - corridor_w / 2), floor.centery, corridor_w, floor.bottom - floor.centery
        )

        def fits(rect: pygame.Rect) -> bool:
            if not floor.contains(rect) or rect.colliderect(door_path):
                return False
            return all(not rect.colliderect(other.inflate(40, 40)) for other, _ in solids)

        def try_place(w, h) -> Optional[pygame.Rect]:
            for _ in range(50):
                rect = pygame.Rect(
                    rng.randint(floor.left + 10, floor.right - 10 - w),
                    rng.randint(floor.top + 10, floor.bottom - 10 - h),
                    w,
                    h,
                )
                if fits(rect):
                    return rect
            return None

        if self.kind == "house":
            bed_left = rng.random() < 0.5
            bed_x = floor.left + 20 if bed_left else floor.right - 90
            # The household's own bed, which the player can sleep in for nothing at all,
            # provided nobody outside sees them do it (Game._sleep_in_bed).
            house_bed = pygame.Rect(bed_x, floor.top + 15, 70, 100)
            solids.append((house_bed, "bed"))
            beds.append(house_bed)
            solids.append((pygame.Rect(round(floor.centerx - 50), floor.top + 6, 100, 22), "shelf"))
            chest_x = floor.right - 55 if bed_left else floor.left + 20
            chest = pygame.Rect(chest_x, floor.bottom - 70, 40, 32)
            solids.append((chest, "chest"))
            table = try_place(80, 60)
            if table:
                solids.append((table, "table"))
                for chair_x in (table.left - 30, table.right + 8):
                    chair = pygame.Rect(chair_x, table.centery - 13, 26, 26)
                    if floor.contains(chair) and not chair.colliderect(door_path):
                        solids.append((chair, "chair"))

        elif self.kind == "shop":
            counter = pygame.Rect(round(floor.centerx - 85), floor.top + 90, 170, 32)
            solids.append((counter, "counter"))
            solids.append((pygame.Rect(floor.left + 25, floor.top + 6, 100, 22), "shelf"))
            solids.append((pygame.Rect(floor.right - 125, floor.top + 6, 100, 22), "shelf"))
            for _ in range(3):
                crate = try_place(40, 40)
                if crate:
                    # Always placed (so positions stay deterministic across saves); broken
                    # ones are dropped from the collision set below but keep their index.
                    solids.append((crate, "crate"))
                    crates.append(crate)

        elif self.kind == "tavern":
            nb_beds = rng.randint(3, 4)
            bed_w, bed_h = 60, 95
            span = floor.width - 80 - bed_w
            for i in range(nb_beds):
                bed = pygame.Rect(floor.left + 40 + round(span * i / (nb_beds - 1)), floor.top + 15, bed_w, bed_h)
                solids.append((bed, "bed"))
                beds.append(bed)
            solids.append((pygame.Rect(floor.right - 190, floor.bottom - 80, 170, 32), "counter"))
            for _ in range(2):
                table = try_place(80, 60)
                if table:
                    solids.append((table, "table"))
            for _ in range(2):
                crate = try_place(40, 40)
                if crate:
                    # Same deal as the shop: always placed for deterministic indices, dropped
                    # from the collision set once broken (see the broken-crate filter below).
                    solids.append((crate, "crate"))
                    crates.append(crate)

        rug = pygame.Rect(0, 0, 130, 80)
        rug.center = (round(floor.centerx), round(floor.centery - 25))

        # Everything in the room that can be taken apart, in placement order: that order is
        # what `broken_props` indexes, so it has to be built before anything is dropped for
        # having been smashed already.
        props = [(rect, kind) for rect, kind in solids if kind in c.Buildings.FURNITURE_HP]
        broken = {id(props[i][0]) for i in self.broken_props if i < len(props)}
        # Wreckage no longer blocks movement, but stays in `props` so its debris still draws
        # and its index keeps matching the saved broken set.
        solids = [(rect, kind) for rect, kind in solids if id(rect) not in broken]

        def place(rect: pygame.Rect) -> pygame.Rect:
            return self._place(rect, floor, room)

        self._layout = {
            "solids": [(place(rect), kind) for rect, kind in solids],
            "beds": [place(bed) for bed in beds],
            "crates": [place(crate) for crate in crates],
            "props": [(place(rect), kind) for rect, kind in props],
            "chest": place(chest) if chest is not None else None,
            "rug": place(rug),
        }
        return self._layout

    def prop_key(self, index: int) -> str:
        """Identity of one piece of furniture for `core.damage_fx`. A table is an index into
        this building's layout rather than an object of its own, so the registry that
        remembers recent blows needs a string to hang them on."""
        return f"{self.id}:prop:{index}"

    def damage_prop_at(self, pos, hit_radius, damage: int) -> Optional[tuple]:
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
        # Drop it from the cached collision set so the player can walk through the wreckage now.
        self._layout["solids"] = [(other, other_kind) for other, other_kind in self._layout["solids"] if other != rect]
        return idx, rect, kind, True

    # ------------------------------------------------------------------ drawing

    def draw(self, screen: pygame.Surface, camera: Camera, player_inside: bool = False):
        """`player_inside` swaps this one building from its normal solid-roof look to a
        cutaway (no roof, floor and furniture visible) so the player can be seen standing
        in it while the rest of the map keeps drawing around it, same camera, no cut."""
        if self.kind == "landmark":
            self._draw_ruin(screen, camera)
            return

        if player_inside:
            self._draw_interior(screen, camera)
            return

        style = self.style()
        r = self.rect
        sx, sy = camera.world_to_screen(r.left, r.top)
        srect = pygame.Rect(sx, sy, r.width, r.height)
        pygame.draw.rect(screen, style["wall"], srect)

        roof = srect.inflate(-16, -16)
        self._draw_roof(screen, roof, style)

        # The doorstep, wherever the door is.
        pygame.draw.rect(screen, (205, 185, 140), self._facade_screen(camera, 44, 10, 0, -10))
        self._draw_door(screen, camera)

        windows = self.window_rects()
        for idx, window in enumerate(windows):
            self._draw_window(
                screen,
                camera,
                window,
                idx in self.broken_windows,
                f"{self.id}:window:{idx}",
                self.window_hp.get(idx, c.Buildings.WINDOW_HP) / c.Buildings.WINDOW_HP,
            )
        self._draw_extras(screen, camera, srect, roof, windows, style)

        if self.kind == "shop":
            self._draw_awning(screen, camera)
        elif self.kind == "tavern":
            self._draw_tavern_sign(screen, camera)

    def style(self) -> dict:
        """How this building is built. Rolled once from its id, which is stable across a
        save, so a house keeps its roof and its shutters for the life of the world."""
        if self._style is not None:
            return self._style

        rng = random.Random(f"style:{self.id}")

        def pick(weights):
            names, values = zip(*weights)
            return rng.choices(names, weights=values)[0]

        material = pick(c.Buildings.ROOF_MATERIALS)
        base = c.Buildings.ROOF_MATERIAL_COLORS[material]
        # The kind's own colour is blended into the material's, so a shop still reads
        # blue-ish and a tavern purple-ish whatever they happen to be roofed with.
        kind_color = c.Buildings.ROOF_COLORS[self.kind]
        blend = c.Buildings.ROOF_KIND_BLEND
        roof = tuple(round(base[i] * (1 - blend) + kind_color[i] * blend) for i in range(3))
        tint = rng.uniform(*c.Buildings.WALL_TINT_RANGE)
        wall = tuple(min(255, round(v * tint)) for v in c.Buildings.WALL_COLOR)

        extras = rng.sample([name for name, _ in c.Buildings.EXTRAS], k=len(c.Buildings.EXTRAS))
        extras = [name for name in extras if rng.random() < 0.55][: c.Buildings.EXTRA_MAX]

        self._style = {
            "material": material,
            "form": pick(c.Buildings.ROOF_FORMS),
            "roof": roof,
            "wall": wall,
            "extras": extras,
            # Which way the ridge of a gable roof runs, and which side the extras sit on.
            "ridge_horizontal": rng.random() < 0.5,
            "side": rng.choice((-1, 1)),
        }
        return self._style

    def _facade_screen(self, camera: Camera, width, depth, offset, inset=0) -> pygame.Rect:
        """`_facade_slot` in screen coordinates, for everything hung on the front of the
        building. A negative `inset` puts it outside the wall (a doorstep, an awning)."""
        r = self._facade_slot(round(width), round(depth), offset, round(inset))
        sx, sy = camera.world_to_screen(r.left, r.top)
        return pygame.Rect(round(sx), round(sy), r.width, r.height)

    def _draw_roof(self, screen, roof: pygame.Rect, style: dict):
        """The covering over the walls: a ridged gable, a hipped pyramid or a flat slab,
        then the texture of whatever it is made of."""
        color = style["roof"]
        lighter = tuple(min(255, round(v * 1.18)) for v in color)
        darker = tuple(round(v * 0.7) for v in color)
        pygame.draw.rect(screen, color, roof)

        if style["form"] == "gable":
            if style["ridge_horizontal"]:
                pygame.draw.rect(screen, lighter, pygame.Rect(roof.left, roof.top, roof.width, roof.height // 2))
                pygame.draw.line(screen, darker, (roof.left, roof.centery), (roof.right - 1, roof.centery), 4)
            else:
                pygame.draw.rect(screen, lighter, pygame.Rect(roof.left, roof.top, roof.width // 2, roof.height))
                pygame.draw.line(screen, darker, (roof.centerx, roof.top), (roof.centerx, roof.bottom - 1), 4)
        elif style["form"] == "hip":
            inner = roof.inflate(-round(roof.width * 0.42), -round(roof.height * 0.42))
            corners = (roof.topleft, roof.topright, roof.bottomright, roof.bottomleft)
            inners = (inner.topleft, inner.topright, inner.bottomright, inner.bottomleft)
            shades = (lighter, color, darker, color)
            for i in range(4):
                slope = (corners[i], corners[(i + 1) % 4], inners[(i + 1) % 4], inners[i])
                pygame.draw.polygon(screen, shades[i], slope)
            pygame.draw.rect(screen, lighter, inner, 2)
        else:
            pygame.draw.rect(screen, lighter, pygame.Rect(roof.left, roof.top, roof.width, 10))

        self._draw_roof_texture(screen, roof, style)
        pygame.draw.rect(screen, darker, roof, 2)

    @staticmethod
    def _draw_roof_texture(screen, roof: pygame.Rect, style: dict):
        color = style["roof"]
        line = tuple(round(v * 0.82) for v in color)
        if style["material"] == "thatch":
            for y in range(roof.top + 6, roof.bottom - 2, 9):
                pygame.draw.line(screen, line, (roof.left + 3, y), (roof.right - 4, y), 2)
        elif style["material"] == "shingle":
            for row, y in enumerate(range(roof.top + 8, roof.bottom - 2, 12)):
                offset = 9 if row % 2 else 0
                for x in range(roof.left + 4 + offset, roof.right - 6, 18):
                    pygame.draw.arc(screen, line, pygame.Rect(x, y - 6, 16, 12), 3.34, 6.08, 2)
        elif style["material"] == "slate":
            for x in range(roof.left + 14, roof.right - 4, 16):
                pygame.draw.line(screen, line, (x, roof.top + 3), (x, roof.bottom - 4), 1)
            for y in range(roof.top + 14, roof.bottom - 4, 16):
                pygame.draw.line(screen, line, (roof.left + 3, y), (roof.right - 4, y), 1)
        else:
            for y in range(roof.top + 12, roof.bottom - 4, 14):
                pygame.draw.line(screen, line, (roof.left + 3, y), (roof.right - 4, y), 2)

    def _draw_extras(self, screen, camera: Camera, srect: pygame.Rect, roof: pygame.Rect, windows, style: dict):
        """The one or two things that make this house somebody's: a smoking chimney, a
        porch over the door, shutters, a flower box, a stack of firewood."""
        side = style["side"]
        for extra in style["extras"]:
            if extra == "chimney":
                stack = pygame.Rect(0, 0, 22, 22)
                stack.center = (roof.centerx + side * (roof.width // 3), roof.top + roof.height // 3)
                pygame.draw.rect(screen, (108, 92, 84), stack, border_radius=3)
                pygame.draw.rect(screen, (66, 56, 50), stack, 2, border_radius=3)
                # A slow curl of smoke, so a lived-in house reads as lived in from a distance.
                drift = math.sin(pygame.time.get_ticks() / 700.0)
                for i in range(3):
                    puff = (round(stack.centerx + drift * (4 + i * 4)), stack.top - 8 - i * 11)
                    pygame.draw.circle(screen, (206, 202, 198), puff, 5 + i * 2)
            elif extra == "porch":
                porch = self._facade_screen(camera, c.Buildings.DOOR_WIDTH + 46, 20, 0, -18)
                pygame.draw.rect(screen, (126, 100, 68), porch)
                pygame.draw.rect(screen, (78, 60, 40), porch, 2)
                posts = (
                    ((porch.left + 5, porch.centery), (porch.right - 5, porch.centery))
                    if porch.width > porch.height
                    else ((porch.centerx, porch.top + 5), (porch.centerx, porch.bottom - 5))
                )
                for post in posts:
                    pygame.draw.circle(screen, (94, 74, 50), post, 5)
            elif extra == "shutters":
                for window in windows:
                    wx, wy = camera.world_to_screen(window.left, window.top)
                    frame = pygame.Rect(round(wx), round(wy), window.width, window.height)
                    # Flanking the opening along the wall, whichever way the wall runs.
                    for shift in (-8, frame.width if frame.width > frame.height else frame.height):
                        shutter = (
                            pygame.Rect(frame.left + shift, frame.top, 8, frame.height)
                            if frame.width > frame.height
                            else pygame.Rect(frame.left, frame.top + shift, frame.width, 8)
                        )
                        pygame.draw.rect(screen, (92, 108, 86), shutter)
                        pygame.draw.rect(screen, (54, 66, 52), shutter, 1)
            elif extra == "flowerbox" and windows:
                window = windows[0] if side < 0 else windows[-1]
                nx, ny = self.outward()
                wx, wy = camera.world_to_screen(window.centerx, window.centery)
                long_side = max(window.width, window.height)
                box = pygame.Rect(0, 0, long_side + 4, 9) if nx == 0 else pygame.Rect(0, 0, 9, long_side + 4)
                box.center = (
                    round(wx + nx * (min(window.width, window.height) / 2 + 4)),
                    round(wy + ny * (min(window.width, window.height) / 2 + 4)),
                )
                pygame.draw.rect(screen, (112, 84, 54), box)
                for i in range(3):
                    petal = (box.left + 7 + i * 11, box.centery) if nx == 0 else (box.centerx, box.top + 7 + i * 11)
                    pygame.draw.circle(screen, (216, 96, 120), petal, 4)
            elif extra == "woodpile":
                pile = pygame.Rect(0, 0, 16, 46)
                pile.midtop = (srect.centerx + side * (srect.width // 2 - 12), srect.bottom + 4)
                pygame.draw.rect(screen, (104, 78, 50), pile, border_radius=3)
                for y in range(pile.top + 6, pile.bottom - 2, 10):
                    pygame.draw.circle(screen, (146, 116, 76), (pile.centerx, y), 5)
                    pygame.draw.circle(screen, (74, 54, 34), (pile.centerx, y), 5, 1)

    def _draw_awning(self, screen, camera: Camera):
        """The shop's striped canopy, hung over whichever wall the door is in. The stripes
        run along the facade, so a shop facing east reads the same as one facing south."""
        band = self._facade_screen(camera, 220, 16, 0, -10)
        stripe_colors = ((196, 60, 50), (232, 226, 210))
        along_x = band.width > band.height
        span = band.width if along_x else band.height
        for i, offset in enumerate(range(0, span, 22)):
            size = min(22, span - offset)
            stripe = (
                pygame.Rect(band.left + offset, band.top, size, band.height)
                if along_x
                else pygame.Rect(band.left, band.top + offset, band.width, size)
            )
            pygame.draw.rect(screen, stripe_colors[i % 2], stripe)
        pygame.draw.rect(screen, (60, 45, 35), band, 2)

    def _draw_tavern_sign(self, screen, camera: Camera):
        """Hung beside the door. The board stays the right way up whichever wall it is on:
        a sign nobody can read is a decoration."""
        text = c.Fonts.small.render("TAVERN", True, (60, 45, 35))
        width = text.get_width() + 16
        anchor = self._facade_screen(camera, width, 24, c.Buildings.DOOR_WIDTH / 2 + 12 + width / 2, 4)
        sign = pygame.Rect(0, 0, width, 24)
        sign.center = anchor.center
        pygame.draw.rect(screen, (225, 190, 70), sign)
        pygame.draw.rect(screen, (60, 45, 35), sign, 2)
        screen.blit(text, text.get_rect(center=sign.center))

    def _ruin_shape(self) -> dict:
        if self._ruin is not None:
            return self._ruin

        rng = random.Random(self.id)
        hw, hh = self.w / 2, self.h / 2

        outline = []
        step = 55
        x = -hw
        while x < hw:
            outline.append((x, -hh))
            x += step
        y = -hh
        while y < hh:
            outline.append((hw, y))
            y += step
        x = hw
        while x > -hw:
            outline.append((x, hh))
            x -= step
        y = hh
        while y > -hh:
            outline.append((-hw, y))
            y -= step
        points = [(px + rng.uniform(-14, 10), py + rng.uniform(-14, 10)) for px, py in outline]

        # Pull a short run of points inward: the collapsed section of the ruin.
        start = rng.randrange(len(points))
        for k in range(3):
            idx = (start + k) % len(points)
            points[idx] = (points[idx][0] * 0.65, points[idx][1] * 0.65)

        cracks = []
        for _ in range(3):
            cx = rng.uniform(-hw * 0.6, hw * 0.6)
            cy = rng.uniform(-hh * 0.6, hh * 0.6)
            cracks.append(
                [
                    (cx, cy),
                    (cx + rng.uniform(-40, 40), cy + rng.uniform(20, 60)),
                    (cx + rng.uniform(-60, 60), cy + rng.uniform(40, 100)),
                ]
            )

        rubble = []
        for _ in range(7):
            if rng.random() < 0.5:
                rx = rng.uniform(-hw, hw)
                ry = (hh + rng.uniform(12, 45)) * rng.choice((-1, 1))
            else:
                rx = (hw + rng.uniform(12, 45)) * rng.choice((-1, 1))
                ry = rng.uniform(-hh, hh)
            rubble.append((rx, ry, rng.randint(5, 12)))

        self._ruin = {"outline": points, "cracks": cracks, "rubble": rubble}
        return self._ruin

    def _draw_ruin(self, screen, camera: Camera):
        shape = self._ruin_shape()
        cx, cy = camera.world_to_screen(self.x, self.y)
        points = [(cx + px, cy + py) for px, py in shape["outline"]]
        pygame.draw.polygon(screen, c.Buildings.STONE_COLOR, points)
        pygame.draw.polygon(screen, (80, 80, 76), points, 4)
        for crack in shape["cracks"]:
            pygame.draw.lines(screen, (90, 90, 86), False, [(cx + px, cy + py) for px, py in crack], 3)
        for px, py, radius in shape["rubble"]:
            pygame.draw.circle(screen, (110, 110, 105), (cx + px, cy + py), radius)
            pygame.draw.circle(screen, (80, 80, 76), (cx + px, cy + py), radius, 2)
        if self.name:
            draw_label(screen, self.name, (cx, cy + self.h / 2 + 30))

    def _draw_interior(self, screen: pygame.Surface, camera: Camera):
        """Cutaway view of this one building: wall shell, floor and furniture drawn at its
        real world position, roof omitted so the player (drawn by the caller afterwards) and
        anything else on the floor stay visible. Everything outside the footprint is drawn
        by the normal outdoor pass around this, same frame, same camera."""

        def to_screen(rect: pygame.Rect) -> pygame.Rect:
            tl = camera.world_to_screen(rect.left, rect.top)
            return pygame.Rect(tl[0], tl[1], rect.width, rect.height)

        floor = self.interior_rect()
        pygame.draw.rect(screen, c.Buildings.WALL_COLOR, to_screen(self.rect))
        floor_screen = to_screen(floor)
        pygame.draw.rect(screen, c.Buildings.FLOOR_COLOR, floor_screen)
        plank = tuple(round(v * 0.88) for v in c.Buildings.FLOOR_COLOR)
        for x in range(floor.left + 50, floor.right, 50):
            wx, _ = camera.world_to_screen(x, floor.top)
            pygame.draw.line(screen, plank, (wx, floor_screen.top), (wx, floor_screen.bottom - 1), 2)

        # Doorway through the front wall: a floor-coloured gap, matching the collision gap,
        # with whatever is left of the door drawn in it.
        pygame.draw.rect(screen, c.Buildings.FLOOR_COLOR, to_screen(self.door_rect()))
        self._draw_door(screen, camera)

        for idx, window in enumerate(self.window_rects()):
            self._draw_window(
                screen,
                camera,
                window,
                idx in self.broken_windows,
                f"{self.id}:window:{idx}",
                self.window_hp.get(idx, c.Buildings.WINDOW_HP) / c.Buildings.WINDOW_HP,
            )

        layout = self.interior_layout()
        rug_screen = to_screen(layout["rug"])
        pygame.draw.ellipse(screen, (170, 90, 80), rug_screen)
        pygame.draw.ellipse(screen, (120, 60, 55), rug_screen, 3)

        for rect, kind in layout["solids"]:
            self._draw_furniture(screen, to_screen(rect), kind, rect)

        # Furniture carries its damage on it: the cracks say how many more blows it takes,
        # and a struck piece flinches on the frame it was hit.
        fx = get_damage_fx()
        for idx, (prop, kind) in enumerate(layout["props"]):
            if idx in self.broken_props:
                self._draw_debris(screen, to_screen(prop), prop)
            elif idx in self.prop_hp:
                rect = to_screen(prop).move(fx.offset(self.prop_key(idx)))
                draw_cracks(screen, rect, self.prop_hp[idx] / c.Buildings.FURNITURE_HP[kind], f"{self.id}-{idx}")

        # Interaction prompts (pick up, open, sleep) are not drawn here: the game draws a
        # single prompt for the one thing the key would act on, so a room full of beds
        # can't stack labels over each other.
        for item in self.dropped_items:
            item.draw(screen, camera)

    def _draw_door(self, screen: pygame.Surface, camera: Camera):
        """The front door as it currently stands: shut (a planked leaf, cracking further
        with every blow it takes), open (swung out of the frame, the dark doorway showing)
        or beaten down (a hole with a few splinters left in the jamb).

        Drawn from the same rect the collision shell uses, so what is painted across the
        doorway is exactly what is standing in it."""
        if not self.has_door:
            return
        door = self.door_rect()
        sx, sy = camera.world_to_screen(door.left, door.top)
        rect = pygame.Rect(round(sx), round(sy), door.width, door.height)
        frame = (52, 36, 24)
        dark = (32, 24, 20)

        if self.door_broken:
            pygame.draw.rect(screen, dark, rect)
            # Seeded from world space so the wreckage holds still as the camera pans.
            rng = random.Random(door.left * 31 + door.top)
            for _ in range(5):
                w = rng.randint(5, 13)
                shard = pygame.Rect(rng.randint(rect.left, rect.right - w), rect.top, w, rng.randint(4, rect.height))
                pygame.draw.rect(screen, c.Buildings.DOOR_COLOR, shard)
                pygame.draw.rect(screen, frame, shard, 1)
            return

        if self.door_open:
            pygame.draw.rect(screen, dark, rect)
            # The leaf standing open against the facade, so an open house reads as open
            # from across the street.
            leaf = pygame.Rect(rect.right - 7, rect.bottom - 2, 8, round(door.width * 0.6))
            pygame.draw.rect(screen, c.Buildings.DOOR_COLOR, leaf)
            pygame.draw.rect(screen, frame, leaf, 1)
            return

        leaf = rect.move(get_damage_fx().offset(self.door_key))
        pygame.draw.rect(screen, c.Buildings.DOOR_COLOR, leaf)
        pygame.draw.rect(screen, frame, leaf, 2)
        for i in (1, 2):
            plank_x = leaf.left + round(leaf.width * i / 3)
            pygame.draw.line(screen, frame, (plank_x, leaf.top + 2), (plank_x, leaf.bottom - 3), 1)
        pygame.draw.circle(screen, (208, 176, 96), (leaf.right - 10, leaf.centery), 3)
        draw_cracks(screen, leaf, self.door_hp / c.Buildings.DOOR_HP, self.door_key)

    @staticmethod
    def _draw_window(
        screen, camera: Camera, window: pygame.Rect, broken: bool, damage_key: str = "", hp_frac: float = 1.0
    ):
        wx, wy = camera.world_to_screen(window.left, window.top)
        wrect = pygame.Rect(round(wx), round(wy), window.width, window.height)
        if damage_key:
            wrect = wrect.move(get_damage_fx().offset(damage_key))
        if broken:
            pygame.draw.rect(screen, (32, 28, 26), wrect)
            pygame.draw.rect(screen, (70, 50, 35), wrect, 2)
            pygame.draw.line(screen, (55, 52, 56), wrect.topleft, wrect.center, 1)
            pygame.draw.line(screen, (55, 52, 56), (wrect.right, wrect.top), wrect.center, 1)
            return
        pygame.draw.rect(screen, (70, 50, 35), wrect)
        pane = wrect.inflate(-4, -4)
        pygame.draw.rect(screen, (150, 195, 210), pane)
        pygame.draw.line(screen, (70, 50, 35), (pane.centerx, pane.top), (pane.centerx, pane.bottom), 2)
        pygame.draw.line(screen, (70, 50, 35), (pane.left, pane.centery), (pane.right, pane.centery), 2)
        # A cracked pane before it shatters: the same wear every other breakable shows.
        draw_cracks(screen, pane, hp_frac, damage_key)

    def _draw_debris(self, screen, rect: pygame.Rect, world_rect: pygame.Rect):
        """What is left of a piece of furniture: a scatter of splintered planks on the floor.
        One look for all of them, because a broken chair and a broken crate are both a pile
        of wood and the room is read at a glance."""
        # Seed from the world rect so the debris keeps its shape as the camera pans.
        rng = random.Random(world_rect.left * 31 + world_rect.top)
        for _ in range(6):
            px = rng.randint(rect.left, rect.right - 16)
            py = rng.randint(rect.centery - 6, rect.bottom - 6)
            plank = pygame.Rect(px, py, rng.randint(12, 22), rng.randint(4, 7))
            pygame.draw.rect(screen, (110, 78, 48), plank)
            pygame.draw.rect(screen, (60, 42, 30), plank, 1)

    def _draw_furniture(self, screen, rect: pygame.Rect, kind: str, world_rect: pygame.Rect):
        if kind == "bed":
            # A bed in a room whose door is in a side wall lies along the other axis, so the
            # pillow and the blanket follow the long side rather than always the top.
            pygame.draw.rect(screen, (95, 65, 45), rect)
            mattress = rect.inflate(-12, -12)
            pygame.draw.rect(screen, (228, 222, 205), mattress)
            if mattress.height >= mattress.width:
                pillow = pygame.Rect(mattress.left + 8, mattress.top + 8, mattress.width - 16, 30)
                blanket = pygame.Rect(mattress.left, mattress.top + 55, mattress.width, mattress.height - 55)
            else:
                pillow = pygame.Rect(mattress.left + 8, mattress.top + 8, 30, mattress.height - 16)
                blanket = pygame.Rect(mattress.left + 55, mattress.top, mattress.width - 55, mattress.height)
            pygame.draw.rect(screen, c.Colors.WHITE, pillow)
            pygame.draw.rect(screen, (150, 70, 60), blanket)
        elif kind == "table":
            pygame.draw.rect(screen, (60, 42, 30), rect)
            pygame.draw.rect(screen, (120, 85, 55), rect.inflate(-8, -8))
        elif kind in ("chair", "crate"):
            pygame.draw.rect(screen, (60, 42, 30), rect)
            pygame.draw.rect(screen, (130, 95, 60), rect.inflate(-6, -6))
            if kind == "crate":
                pygame.draw.line(screen, (60, 42, 30), rect.topleft, rect.bottomright, 2)
                pygame.draw.line(screen, (60, 42, 30), rect.topright, rect.bottomleft, 2)
        elif kind == "counter":
            pygame.draw.rect(screen, (70, 50, 35), rect)
            top = (
                pygame.Rect(rect.left, rect.top, rect.width, 14)
                if rect.width >= rect.height
                else pygame.Rect(rect.left, rect.top, 14, rect.height)
            )
            pygame.draw.rect(screen, (150, 110, 70), top)
        elif kind == "shelf":
            pygame.draw.rect(screen, (55, 40, 28), rect)
            # Seed from the world-space rect so the items keep their colours as the camera moves.
            rng = random.Random(world_rect.left * 31 + world_rect.top)
            palette = ((190, 70, 60), (90, 140, 190), (110, 170, 90), (210, 170, 80))
            along_x = rect.width >= rect.height
            span = rect.width if along_x else rect.height
            for i in range(span // 34):
                item = (
                    pygame.Rect(rect.left + 8 + i * 34, rect.top + 8, 20, rect.height - 16)
                    if along_x
                    else pygame.Rect(rect.left + 8, rect.top + 8 + i * 34, rect.width - 16, 20)
                )
                pygame.draw.rect(screen, palette[rng.randrange(len(palette))], item)
        elif kind == "chest":
            pygame.draw.rect(screen, (60, 42, 30), rect)
            inner = rect.inflate(-6, -6)
            pygame.draw.rect(screen, (110, 75, 45), inner)
            if self.looted:
                pygame.draw.rect(screen, (35, 25, 20), inner.inflate(-10, -10))
            else:
                lid_y = rect.top + round(rect.height * 0.4)
                pygame.draw.line(screen, (60, 42, 30), (rect.left, lid_y), (rect.right - 1, lid_y), 2)
                pygame.draw.circle(screen, (225, 190, 70), (rect.centerx, lid_y), 5)
