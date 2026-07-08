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
    from game.entities.player import Player

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


def generate_buildings() -> List["Building"]:
    """Scatter buildings across the map, keeping them apart and away from the spawn point."""
    counts = [
        ("landmark", 1),
        ("inn", c.Buildings.NB_INNS),
        ("shop", c.Buildings.NB_SHOPS),
        ("house", c.Buildings.NB_HOUSES),
    ]
    center = c.World.WORLD_SIZE // 2
    buildings: List[Building] = []
    for kind, count in counts:
        for _ in range(count):
            for _attempt in range(60):
                margin = c.Buildings.EDGE_MARGIN
                x = random.randint(margin, c.World.WORLD_SIZE - margin)
                y = random.randint(margin, c.World.WORLD_SIZE - margin)
                if math.hypot(x - center, y - center) < c.Buildings.SPAWN_CLEARANCE:
                    continue
                candidate = Building(x, y, kind)
                gap = c.Buildings.MIN_GAP
                if any(candidate.rect.inflate(gap * 2, gap * 2).colliderect(other.rect) for other in buildings):
                    continue
                buildings.append(candidate)
                break
    return buildings


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

    def blocks(self, x, y, radius, door_open=False) -> bool:
        r = self.rect
        nearest_x = min(max(x, r.left), r.right)
        nearest_y = min(max(y, r.top), r.bottom)
        if math.hypot(x - nearest_x, y - nearest_y) >= radius:
            return False
        if door_open and self.has_door and self.door_zone().collidepoint(x, y):
            return False
        return True

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
        }

    @classmethod
    def from_dict(cls, data: dict) -> Building:
        building = cls(data["x"], data["y"], data["kind"], data["w"], data["h"])
        building.id = data["id"]
        building.name = data["name"]
        building.looted = data["looted"]
        return building

    # ------------------------------------------------------------------ interior

    def interior_floor(self) -> pygame.Rect:
        wall = c.Buildings.ROOM_WALL
        return pygame.Rect(wall, wall, c.Buildings.ROOM_W - wall * 2, c.Buildings.ROOM_H - wall * 2)

    def interior_exit_zone(self) -> pygame.Rect:
        # The trigger must start above the floor-bottom collision line, otherwise the player
        # is stopped by the wall before ever reaching it. It reaches up into the room and
        # down through the doorway so walking to the door leaves the building.
        floor = self.interior_floor()
        return pygame.Rect(
            round(c.Buildings.ROOM_W / 2 - c.Buildings.DOOR_WIDTH / 2),
            floor.bottom - 35,
            c.Buildings.DOOR_WIDTH,
            c.Buildings.ROOM_WALL + 70,
        )

    def interior_entry_pos(self) -> tuple:
        # Well above the exit zone so entering does not instantly trigger an exit.
        return (c.Buildings.ROOM_W / 2, self.interior_floor().bottom - 100)

    def interior_blocked(self, x, y, radius, door_open=True) -> bool:
        if self.interior_exit_zone().collidepoint(x, y):
            return False
        floor = self.interior_floor()
        if x - radius < floor.left or x + radius > floor.right or y - radius < floor.top or y + radius > floor.bottom:
            return True
        for rect, _kind in self.interior_layout()["solids"]:
            nearest_x = min(max(x, rect.left), rect.right)
            nearest_y = min(max(y, rect.top), rect.bottom)
            if math.hypot(x - nearest_x, y - nearest_y) < radius:
                return True
        return False

    def interior_layout(self) -> dict:
        """Furniture for this building's single room, deterministic from the building id."""
        if self._layout is not None:
            return self._layout

        rng = random.Random(self.id)
        floor = self.interior_floor()
        solids: list = []
        beds: List[pygame.Rect] = []
        chest = None

        # Keep a corridor from the door to the middle of the room clear of furniture.
        door_path = pygame.Rect(
            round(c.Buildings.ROOM_W / 2) - 90, round(c.Buildings.ROOM_H / 2), 180, round(c.Buildings.ROOM_H / 2)
        )

        def fits(rect: pygame.Rect) -> bool:
            if not floor.contains(rect) or rect.colliderect(door_path):
                return False
            return all(not rect.colliderect(other.inflate(70, 70)) for other, _ in solids)

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
            bed_x = floor.left + 30 if bed_left else floor.right - 140
            solids.append((pygame.Rect(bed_x, floor.top + 20, 110, 170), "bed"))
            solids.append((pygame.Rect(round(c.Buildings.ROOM_W / 2) - 90, floor.top + 8, 180, 34), "shelf"))
            chest_x = floor.right - 90 if bed_left else floor.left + 34
            chest = pygame.Rect(chest_x, floor.bottom - 100, 56, 44)
            solids.append((chest, "chest"))
            table = try_place(130, 95)
            if table:
                solids.append((table, "table"))
                for chair_x in (table.left - 46, table.right + 12):
                    chair = pygame.Rect(chair_x, table.centery - 17, 34, 34)
                    if floor.contains(chair) and not chair.colliderect(door_path):
                        solids.append((chair, "chair"))

        elif self.kind == "shop":
            counter = pygame.Rect(round(c.Buildings.ROOM_W / 2) - 160, floor.top + 150, 320, 48)
            solids.append((counter, "counter"))
            solids.append((pygame.Rect(floor.left + 40, floor.top + 8, 190, 34), "shelf"))
            solids.append((pygame.Rect(floor.right - 230, floor.top + 8, 190, 34), "shelf"))
            for _ in range(3):
                crate = try_place(58, 58)
                if crate:
                    solids.append((crate, "crate"))

        elif self.kind == "inn":
            nb_beds = rng.randint(3, 4)
            bed_w, bed_h = 95, 150
            span = floor.width - 80 - bed_w
            for i in range(nb_beds):
                bed = pygame.Rect(floor.left + 40 + round(span * i / (nb_beds - 1)), floor.top + 20, bed_w, bed_h)
                solids.append((bed, "bed"))
                beds.append(bed)
            solids.append((pygame.Rect(floor.right - 280, floor.bottom - 120, 240, 48), "counter"))
            for _ in range(2):
                table = try_place(110, 85)
                if table:
                    solids.append((table, "table"))

        rug = pygame.Rect(0, 0, 190, 120)
        rug.center = (round(c.Buildings.ROOM_W / 2), round(c.Buildings.ROOM_H / 2) - 40)

        self._layout = {"solids": solids, "beds": beds, "chest": chest, "rug": rug}
        return self._layout

    def interactable_at(self, x, y) -> Optional[tuple]:
        """Return ("chest", rect) or ("bed", rect) within reach of (x, y), else None."""
        layout = self.interior_layout()
        chest = layout["chest"]
        reach = c.Buildings.INTERACT_DISTANCE
        if chest and not self.looted and math.hypot(x - chest.centerx, y - chest.centery) <= reach:
            return ("chest", chest)
        for bed in layout["beds"]:
            if math.hypot(x - bed.centerx, y - bed.centery) <= reach:
                return ("bed", bed)
        return None

    # ------------------------------------------------------------------ drawing

    def draw(self, screen: pygame.Surface, camera: Camera):
        if self.kind == "landmark":
            self._draw_ruin(screen, camera)
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

        if self.kind == "shop":
            self._draw_awning(screen, srect)
        elif self.kind == "inn":
            self._draw_inn_sign(screen, srect)

    def _draw_awning(self, screen, srect: pygame.Rect):
        band = pygame.Rect(round(srect.centerx - 110), srect.bottom - 6, 220, 16)
        stripe_colors = ((196, 60, 50), (232, 226, 210))
        for i, x in enumerate(range(band.left, band.right, 22)):
            pygame.draw.rect(
                screen, stripe_colors[i % 2], pygame.Rect(x, band.top, min(22, band.right - x), band.height)
            )
        pygame.draw.rect(screen, (60, 45, 35), band, 2)

    def _draw_inn_sign(self, screen, srect: pygame.Rect):
        sign = pygame.Rect(round(srect.centerx + c.Buildings.DOOR_WIDTH / 2) + 12, srect.bottom - 28, 50, 24)
        pygame.draw.rect(screen, (225, 190, 70), sign)
        pygame.draw.rect(screen, (60, 45, 35), sign, 2)
        text = c.Fonts.small.render("INN", True, (60, 45, 35))
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

    def draw_interior(self, screen: pygame.Surface, camera: Camera, player: Player):
        screen.fill((24, 20, 17))
        ox, oy = camera.world_to_screen(0, 0)

        def to_screen(rect: pygame.Rect) -> pygame.Rect:
            return rect.move(ox, oy)

        room = pygame.Rect(0, 0, c.Buildings.ROOM_W, c.Buildings.ROOM_H)
        floor = self.interior_floor()
        pygame.draw.rect(screen, c.Buildings.WALL_COLOR, to_screen(room))
        floor_screen = to_screen(floor)
        pygame.draw.rect(screen, c.Buildings.FLOOR_COLOR, floor_screen)
        plank = tuple(round(v * 0.88) for v in c.Buildings.FLOOR_COLOR)
        for x in range(floor.left + 70, floor.right, 70):
            pygame.draw.line(screen, plank, (ox + x, floor_screen.top), (ox + x, floor_screen.bottom - 1), 2)

        # Exit doorway through the bottom wall: a floor-coloured gap in the dark wall.
        door = pygame.Rect(
            round(c.Buildings.ROOM_W / 2 - c.Buildings.DOOR_WIDTH / 2),
            floor.bottom,
            c.Buildings.DOOR_WIDTH,
            c.Buildings.ROOM_WALL,
        )
        door_screen = to_screen(door)
        pygame.draw.rect(screen, c.Buildings.FLOOR_COLOR, door_screen)
        pygame.draw.rect(screen, (45, 32, 26), door_screen, 3)
        draw_label(screen, "Exit", (door_screen.centerx, door_screen.bottom + 16))

        layout = self.interior_layout()
        rug_screen = to_screen(layout["rug"])
        pygame.draw.ellipse(screen, (170, 90, 80), rug_screen)
        pygame.draw.ellipse(screen, (120, 60, 55), rug_screen, 3)

        for rect, kind in layout["solids"]:
            self._draw_furniture(screen, to_screen(rect), kind, rect)

        chest = layout["chest"]
        if chest and not self.looted:
            reach = math.hypot(player.x - chest.centerx, player.y - chest.centery) <= c.Buildings.INTERACT_DISTANCE
            if reach:
                chest_screen = to_screen(chest)
                draw_label(screen, "E: open chest", (chest_screen.centerx, chest_screen.top - 18))
        for bed in layout["beds"]:
            if math.hypot(player.x - bed.centerx, player.y - bed.centery) <= c.Buildings.INTERACT_DISTANCE:
                bed_screen = to_screen(bed)
                text = f"E: sleep ({c.Buildings.INN_SLEEP_COST} coins)"
                draw_label(screen, text, (bed_screen.centerx, bed_screen.top - 18))

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
