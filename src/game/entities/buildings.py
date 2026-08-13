from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING, List, Optional

import pygame

import core.constants as c
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


class Building:
    def __init__(self, x, y, kind: str, w=None, h=None):
        w_range, h_range = c.Buildings.SIZES[kind]
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.x = x
        self.y = y
        self.w = w if w is not None else random.randint(*w_range)
        self.h = h if h is not None else random.randint(*h_range)
        self.name = None  # Only the landmark gets an LLM-generated name
        self.looted = False
        self.broken_crates: set = set()  # indices into interior_layout()["crates"] already smashed
        self.broken_windows: set = set()  # indices into window_rects() already shattered
        # Loot dropped on the floor by smashed crates, waiting to be picked up. Not
        # persisted: it lives only for the current play session, same as indoor monsters.
        self.dropped_items: List["Item"] = []
        self._layout = None
        self._ruin = None

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x - self.w / 2), round(self.y - self.h / 2), self.w, self.h)

    @property
    def has_door(self) -> bool:
        return self.kind != "landmark"

    def door_zone(self) -> Optional[pygame.Rect]:
        """Trigger area straddling the front wall; walking into it enters the building."""
        if not self.has_door:
            return None
        depth = c.Buildings.DOOR_DEPTH
        return pygame.Rect(
            round(self.x - c.Buildings.DOOR_WIDTH / 2), self.rect.bottom - depth, c.Buildings.DOOR_WIDTH, depth * 2
        )

    def door_front(self) -> tuple:
        return (self.x, self.rect.bottom + 60)

    def window_rects(self) -> List[pygame.Rect]:
        """Two windows flanking the door on the front facade, in world coordinates.
        The landmark has no facade at all, so it gets none."""
        if not self.has_door:
            return []
        w, h = c.Buildings.WINDOW_W, c.Buildings.WINDOW_H
        y = round(self.rect.bottom - c.Buildings.WINDOW_Y_FROM_BOTTOM)
        offset = c.Buildings.DOOR_WIDTH / 2 + c.Buildings.WINDOW_X_FROM_DOOR
        left = pygame.Rect(round(self.x - offset - w), y, w, h)
        right = pygame.Rect(round(self.x + offset), y, w, h)
        return [left, right]

    def _wall_segments(self) -> List[pygame.Rect]:
        """The building's solid shell as a few thin rects, with a permanent door-sized
        gap cut from the front wall. The landmark ruin has no door, so its whole
        footprint stays one solid block."""
        r = self.rect
        if not self.has_door:
            return [r]
        wall = c.Buildings.WALL_THICKNESS
        door_left = round(self.x - c.Buildings.DOOR_WIDTH / 2)
        door_right = round(self.x + c.Buildings.DOOR_WIDTH / 2)
        return [
            pygame.Rect(r.left, r.top, r.width, wall),  # back wall
            pygame.Rect(r.left, r.top, wall, r.height),  # left wall
            pygame.Rect(r.right - wall, r.top, wall, r.height),  # right wall
            pygame.Rect(r.left, r.bottom - wall, door_left - r.left, wall),  # front, left of door
            pygame.Rect(door_right, r.bottom - wall, r.right - door_right, wall),  # front, right of door
        ]

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
            "name": self.name,
            "looted": self.looted,
            "broken_crates": sorted(self.broken_crates),
            "broken_windows": sorted(self.broken_windows),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Building:
        building = cls(data["x"], data["y"], data["kind"], data["w"], data["h"])
        building.id = data["id"]
        building.name = data["name"]
        building.looted = data["looted"]
        building.broken_crates = set(data.get("broken_crates", []))
        building.broken_windows = set(data.get("broken_windows", []))
        return building

    # ------------------------------------------------------------------ interior

    def interior_rect(self) -> pygame.Rect:
        """The walkable floor, in world coordinates: the footprint inset by the wall shell."""
        wall = c.Buildings.WALL_THICKNESS
        return self.rect.inflate(-wall * 2, -wall * 2)

    def contains_point(self, x, y) -> bool:
        """True once (x, y) has stepped past the wall onto this building's floor."""
        return self.has_door and self.interior_rect().collidepoint(x, y)

    def interior_layout(self) -> dict:
        """Furniture for this building's single room, deterministic from the building id."""
        if self._layout is not None:
            return self._layout

        rng = random.Random(self.id)
        floor = self.interior_rect()
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
            solids.append((pygame.Rect(bed_x, floor.top + 15, 70, 100), "bed"))
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

        # Smashed crates no longer block movement, but stay in `crates` so their debris
        # still draws and their index keeps matching the saved broken set.
        broken = [crates[i] for i in self.broken_crates if i < len(crates)]
        solids = [(rect, kind) for rect, kind in solids if not (kind == "crate" and rect in broken)]

        self._layout = {"solids": solids, "beds": beds, "crates": crates, "chest": chest, "rug": rug}
        return self._layout

    def break_crate_at(self, pos, hit_radius) -> Optional[pygame.Rect]:
        """Smash the nearest intact crate (shop or tavern) a swing reaches. Returns its rect, or None if none near."""
        layout = self.interior_layout()
        px, py = pos
        best = None
        for idx, crate in enumerate(layout["crates"]):
            if idx in self.broken_crates:
                continue
            dist = math.hypot(px - crate.centerx, py - crate.centery)
            if dist < hit_radius + crate.width / 2 and (best is None or dist < best[1]):
                best = (idx, dist, crate)
        if best is None:
            return None
        idx, _dist, crate = best
        self.broken_crates.add(idx)
        # Drop it from the cached collision set so the player can walk through the wreckage now.
        self._layout["solids"] = [
            (rect, kind) for rect, kind in self._layout["solids"] if not (kind == "crate" and rect == crate)
        ]
        return crate

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

        r = self.rect
        sx, sy = camera.world_to_screen(r.left, r.top)
        srect = pygame.Rect(sx, sy, r.width, r.height)
        pygame.draw.rect(screen, c.Buildings.WALL_COLOR, srect)

        roof = srect.inflate(-16, -16)
        roof_color = c.Buildings.ROOF_COLORS[self.kind]
        pygame.draw.rect(screen, roof_color, roof)
        lighter = tuple(min(255, round(v * 1.18)) for v in roof_color)
        pygame.draw.rect(screen, lighter, pygame.Rect(roof.left, roof.top, roof.width, roof.height // 2))
        darker = tuple(round(v * 0.7) for v in roof_color)
        pygame.draw.line(screen, darker, (roof.left, roof.centery), (roof.right - 1, roof.centery), 3)

        door = pygame.Rect(
            round(srect.centerx - c.Buildings.DOOR_WIDTH / 2), srect.bottom - 12, c.Buildings.DOOR_WIDTH, 12
        )
        pygame.draw.rect(screen, (45, 32, 26), door)
        pygame.draw.rect(screen, (205, 185, 140), pygame.Rect(srect.centerx - 22, srect.bottom, 44, 10))

        for idx, window in enumerate(self.window_rects()):
            self._draw_window(screen, camera, window, idx in self.broken_windows)

        if self.kind == "shop":
            self._draw_awning(screen, srect)
        elif self.kind == "tavern":
            self._draw_tavern_sign(screen, srect)

    def _draw_awning(self, screen, srect: pygame.Rect):
        band = pygame.Rect(round(srect.centerx - 110), srect.bottom - 6, 220, 16)
        stripe_colors = ((196, 60, 50), (232, 226, 210))
        for i, x in enumerate(range(band.left, band.right, 22)):
            pygame.draw.rect(
                screen, stripe_colors[i % 2], pygame.Rect(x, band.top, min(22, band.right - x), band.height)
            )
        pygame.draw.rect(screen, (60, 45, 35), band, 2)

    def _draw_tavern_sign(self, screen, srect: pygame.Rect):
        text = c.Fonts.small.render("TAVERN", True, (60, 45, 35))
        sign = pygame.Rect(0, 0, text.get_width() + 16, 24)
        sign.midleft = (round(srect.centerx + c.Buildings.DOOR_WIDTH / 2) + 12, srect.bottom - 16)
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

        # Doorway through the front wall: a floor-coloured gap, matching the collision gap.
        wall = c.Buildings.WALL_THICKNESS
        door = pygame.Rect(round(self.x - c.Buildings.DOOR_WIDTH / 2), floor.bottom, c.Buildings.DOOR_WIDTH, wall)
        pygame.draw.rect(screen, c.Buildings.FLOOR_COLOR, to_screen(door))

        for idx, window in enumerate(self.window_rects()):
            self._draw_window(screen, camera, window, idx in self.broken_windows)

        layout = self.interior_layout()
        rug_screen = to_screen(layout["rug"])
        pygame.draw.ellipse(screen, (170, 90, 80), rug_screen)
        pygame.draw.ellipse(screen, (120, 60, 55), rug_screen, 3)

        for rect, kind in layout["solids"]:
            self._draw_furniture(screen, to_screen(rect), kind, rect)

        for idx in self.broken_crates:
            if idx < len(layout["crates"]):
                world_rect = layout["crates"][idx]
                self._draw_broken_crate(screen, to_screen(world_rect), world_rect)

        # Interaction prompts (pick up, open, sleep) are not drawn here: the game draws a
        # single prompt for the one thing the key would act on, so a room full of beds
        # can't stack labels over each other.
        for item in self.dropped_items:
            item.draw(screen, camera)

    @staticmethod
    def _draw_window(screen, camera: Camera, window: pygame.Rect, broken: bool):
        wx, wy = camera.world_to_screen(window.left, window.top)
        wrect = pygame.Rect(round(wx), round(wy), window.width, window.height)
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

    def _draw_broken_crate(self, screen, rect: pygame.Rect, world_rect: pygame.Rect):
        """A smashed crate: a scatter of splintered planks left on the floor."""
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
            pygame.draw.rect(screen, (95, 65, 45), rect)
            mattress = rect.inflate(-12, -12)
            pygame.draw.rect(screen, (228, 222, 205), mattress)
            pygame.draw.rect(
                screen, c.Colors.WHITE, pygame.Rect(mattress.left + 8, mattress.top + 8, mattress.width - 16, 30)
            )
            blanket = pygame.Rect(mattress.left, mattress.top + 55, mattress.width, mattress.height - 55)
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
            pygame.draw.rect(screen, (150, 110, 70), pygame.Rect(rect.left, rect.top, rect.width, 14))
        elif kind == "shelf":
            pygame.draw.rect(screen, (55, 40, 28), rect)
            # Seed from the world-space rect so the items keep their colours as the camera moves.
            rng = random.Random(world_rect.left * 31 + world_rect.top)
            palette = ((190, 70, 60), (90, 140, 190), (110, 170, 90), (210, 170, 80))
            for i in range(rect.width // 34):
                item = pygame.Rect(rect.left + 8 + i * 34, rect.top + 8, 20, rect.height - 16)
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
