"""How a building looks: its roof, its facade, its open door and the room behind it.

Split off `buildings.py` the way `monster_art.py` is split off `monsters.py`: that file
owns what a building *is* (where it stands, what it blocks, what is in it and what has
been broken), this one owns nothing but paint. A search for a building's behaviour never
lands in three hundred lines of roof texture, and vice versa.

Mixed into `Building` rather than written as free functions, because every one of these
draws from the geometry the building has already worked out for itself (`footprint`,
`door_rect`, `window_rects`, `interior_layout`): handing all of that to a function would
be passing the building in under another name.
"""

from __future__ import annotations

import math
import random
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.damage_fx import draw_cracks, get_damage_fx
from core.text_fx import draw_outlined_text

if TYPE_CHECKING:
    from core.camera import Camera


# What counts as nothing on a building's shell surface. Magenta, because no part of a
# house is painted in it.
SHELL_KEY = (255, 0, 255)

# Every shell currently painted, oldest looked at first. A house keeps its surface for as
# long as it is being drawn, but the world keeps every village the player has ever walked
# into, so past a point the ones nobody has looked at for longest give theirs back. Held by
# weak reference: this is a budget, not a reason for a building to stay in memory.
_SHELLS: OrderedDict[str, weakref.ref] = OrderedDict()
_SHELL_BUDGET = 64


def _draw_label(screen: pygame.Surface, text: str, center: tuple):
    draw_outlined_text(screen, text, c.Fonts.small, c.Colors.WHITE, center=center)


class _ShellCamera:
    """Stands in for the camera while a building's shell is painted onto its own surface.

    Everything here draws through `camera.world_to_screen`, so painting the same code onto a
    surface instead of onto the screen is a matter of handing it a camera whose screen is
    that surface. No drawing method needs to know which of the two it is running for."""

    __slots__ = ("ox", "oy")

    def __init__(self, ox: int, oy: int):
        self.ox = ox
        self.oy = oy

    def world_to_screen(self, x, y):
        return x - self.ox, y - self.oy


class BuildingArt:
    """Every drawing method `Building` has. See the module docstring for why it is a mixin."""

    # How far past its own footprint the shell reaches: only the doorstep hangs off the
    # front wall, everything else outside the walls is drawn live over the top.
    SHELL_PAD = 24

    def draw(self, screen: pygame.Surface, camera: Camera, player_inside: bool = False, darkness: float = 0.0):
        """`player_inside` swaps this one building from its normal solid-roof look to a
        cutaway (no roof, floor and furniture visible) so the player can be seen standing
        in it while the rest of the map keeps drawing around it, same camera, no cut.

        `darkness` is the sky: after dark some of the windows of a village have a lamp
        behind them, and how many of them is the settlement's tier (`_lit_windows`)."""
        if self.kind == "landmark":
            self._draw_ruin(screen, camera)
            return

        if player_inside:
            self._draw_interior(screen, camera)
            return

        # The walls and the roof are painted once onto a surface of the building's own and
        # blitted from then on. They are the expensive half (a roof is a few hundred lines
        # of thatch or shingle) and the half that never changes, and re-laying every course
        # of it every frame was most of what a street of houses cost to look at. Everything
        # after this is drawn live, in the order it always was: what the door is doing, what
        # is left of the windows and the few things hung on the front of the house.
        style = self.style()
        r = self.rect
        origin, shell = self._shell()
        ox, oy = camera.world_to_screen(*origin)
        screen.blit(shell, (round(ox), round(oy)))

        sx, sy = camera.world_to_screen(r.left, r.top)
        srect = pygame.Rect(sx, sy, r.width, r.height)
        self._draw_door(screen, camera)

        windows = self.window_rects()
        lamps = self._lit_windows(darkness)
        for idx, window in enumerate(windows):
            self._draw_window(
                screen,
                camera,
                window,
                idx in self.broken_windows,
                f"{self.id}:window:{idx}",
                self.window_hp.get(idx, c.Buildings.WINDOW_HP) / c.Buildings.WINDOW_HP,
                lit=darkness if idx in lamps else 0.0,
            )
        self._draw_extras(screen, camera, srect, srect.inflate(-16, -16), windows, style)

        if self.kind == "shop":
            self._draw_awning(screen, camera)
        elif self.kind == "tavern":
            self._draw_tavern_sign(screen, camera)

    def _shell(self) -> tuple[tuple[int, int], pygame.Surface]:
        """The walls, the roof and the doorstep, painted onto a surface of their own, with
        the world position of its top left corner. Kept for the life of the building and
        dropped by `reset_geometry`, like the rest of the geometry it is painted from."""
        if self._shell_surface is not None:
            _SHELLS.move_to_end(self.id)
            return self._shell_origin, self._shell_surface

        pad = self.SHELL_PAD
        area = self.bounds.inflate(pad * 2, pad * 2)
        # Keyed rather than per-pixel transparent: nothing here is drawn half-see-through,
        # and a keyed blit of a house-sized surface is several times the speed of an alpha
        # one. The key is a colour no roof, wall or doorstep is ever painted in.
        surface = pygame.Surface(area.size)
        surface.fill(SHELL_KEY)
        self._paint_shell(surface, _ShellCamera(area.left, area.top))
        surface = surface.convert()
        surface.set_colorkey(SHELL_KEY, pygame.RLEACCEL)
        self._shell_origin = (area.left, area.top)
        self._shell_surface = surface
        _SHELLS[self.id] = weakref.ref(self)
        while len(_SHELLS) > _SHELL_BUDGET:
            _, ref = _SHELLS.popitem(last=False)
            oldest = ref()
            if oldest is not None:
                oldest._shell_surface = None
        return self._shell_origin, surface

    def _paint_shell(self, screen: pygame.Surface, camera):
        """What the shell holds. Written against a camera like every other draw here, so the
        same code paints the surface as would paint the screen."""
        style = self.style()
        r = self.rect
        sx, sy = camera.world_to_screen(r.left, r.top)
        srect = pygame.Rect(sx, sy, r.width, r.height)
        # The wing first, so the main block's roof reads as the higher of the two where
        # they meet: an L is a house with something built onto the back of it.
        wing = self.wing()
        if wing is not None:
            wx, wy = camera.world_to_screen(wing.left, wing.top)
            wrect = pygame.Rect(wx, wy, wing.width, wing.height)
            pygame.draw.rect(screen, style["wall"], wrect)
            self._draw_roof(screen, wrect.inflate(-12, -12), style)
        pygame.draw.rect(screen, style["wall"], srect)
        self._draw_roof(screen, srect.inflate(-16, -16), style)

        # The doorstep, wherever the door is.
        pygame.draw.rect(screen, (205, 185, 140), self._facade_screen(camera, 44, 10, 0, -10))

    def style(self) -> dict:
        """How this building is built. Rolled once from its id, which is stable across a
        save, so a house keeps its roof and its shutters for the life of the world."""
        if self._style is not None:
            return self._style

        rng = random.Random(f"style:{self.id}")

        def pick(weights):
            names, values = zip(*weights, strict=True)
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
                    for shift in (-8, max(frame.width, frame.height)):
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
        """Hung beside the door, off the front of the building rather than on it. The board
        stays the right way up whichever wall it is on: a sign nobody can read is a
        decoration.

        Outside the wall like the awning, because the wall is not the tavern's to hang
        things on: a board is as wide as the font makes it, the window is only forty from
        the jamb, and painted onto the facade it landed on the pane. Far enough along to
        clear a porch, which is the other thing hung out here."""
        text = c.Fonts.small.render("TAVERN", True, (60, 45, 35))
        width = text.get_width() + 16
        beside = (c.Buildings.DOOR_WIDTH + 46) / 2 + 8 + width / 2
        anchor = self._facade_screen(camera, width, 24, beside, -30)
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
            _draw_label(screen, self.name, (cx, cy + self.h / 2 + 30))

    def _draw_interior(self, screen: pygame.Surface, camera: Camera):
        """Cutaway view of this one building: wall shell, floor and furniture drawn at its
        real world position, roof omitted so the player (drawn by the caller afterwards) and
        anything else on the floor stay visible. Everything outside the footprint is drawn
        by the normal outdoor pass around this, same frame, same camera."""

        def to_screen(rect: pygame.Rect) -> pygame.Rect:
            tl = camera.world_to_screen(rect.left, rect.top)
            return pygame.Rect(tl[0], tl[1], rect.width, rect.height)

        for block in self.footprint():
            pygame.draw.rect(screen, c.Buildings.WALL_COLOR, to_screen(block))
        plank = tuple(round(v * 0.88) for v in c.Buildings.FLOOR_COLOR)
        for floor in self.interior_rects():
            floor_screen = to_screen(floor)
            pygame.draw.rect(screen, c.Buildings.FLOOR_COLOR, floor_screen)
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

    def _open_leaf(self, door: pygame.Rect) -> pygame.Rect:
        """The door leaf swung open: hinged at one side of the doorway and standing out
        against the front wall, in world coordinates. Outward is the wall's own normal, so
        a door never opens into the room whichever wall it is in."""
        nx, ny = self.outward()
        # Along the wall, towards the side the leaf is hinged on.
        ax, ay = ny, -nx
        thick = c.Buildings.DOOR_LEAF_THICKNESS
        span = door.height if nx else door.width
        reach = round(span * c.Buildings.DOOR_LEAF_SWING)
        if nx:
            left = door.right if nx > 0 else door.left - reach
            top = door.bottom - thick if ay > 0 else door.top
            return pygame.Rect(left, top, reach, thick)
        left = door.right - thick if ax > 0 else door.left
        top = door.bottom if ny > 0 else door.top - reach
        return pygame.Rect(left, top, thick, reach)

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
            # from across the street. Swung along the front wall's own normal like
            # everything else about the facade: written as "down and to the right" it
            # opened into the room on a house facing north, and was painted over the roof.
            leaf = self._open_leaf(door)
            lx, ly = camera.world_to_screen(leaf.left, leaf.top)
            leaf = pygame.Rect(round(lx), round(ly), leaf.width, leaf.height)
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
        if self.locked:
            self._draw_lock(screen, leaf)

    @staticmethod
    def _draw_lock(screen: pygame.Surface, leaf: pygame.Rect):
        """The beam, hasp and padlock across a barred leaf. A house the player cannot walk
        into says so on its own door rather than on the prompt they get for trying it, and
        says it after dark as well, which is what the pale iron is for: the shape alone is
        lost under the night tint on a door that is already the darkest thing on the facade.

        The beam is the half of it that reads from across the street, and it is drawn
        whatever barred this one: the hour, the settlement's temper or the house's own roll
        are one picture, because a door the player cannot open must never look like one they
        have not tried yet.

        Laid across the leaf's short axis, so it reads the same on all four facings."""
        iron, edge, shine = (176, 182, 192), (44, 40, 38), (232, 236, 242)
        along_x = leaf.width > leaf.height
        # The timber first: right across the leaf, since that is what a beam does, with the
        # iron over the middle of it.
        beam = pygame.Rect(0, 0, leaf.width, 11) if along_x else pygame.Rect(0, 0, 11, leaf.height)
        beam.center = leaf.center
        pygame.draw.rect(screen, (118, 84, 48), beam)
        pygame.draw.rect(screen, (58, 40, 24), beam, 1)
        # The two brackets it sits in, one at each end.
        for frac in (0.16, 0.84):
            if along_x:
                bracket = pygame.Rect(round(leaf.left + leaf.width * frac) - 3, beam.top - 2, 6, beam.height + 4)
            else:
                bracket = pygame.Rect(beam.left - 2, round(leaf.top + leaf.height * frac) - 3, beam.width + 4, 6)
            pygame.draw.rect(screen, iron, bracket)
            pygame.draw.rect(screen, edge, bracket, 1)
        # Over the middle of the leaf only: the planks and the handle are what a door looks
        # like, and a band across the whole of it hid the door to say something about it.
        band = (
            pygame.Rect(0, 0, round(leaf.width * 0.55), 8)
            if along_x
            else pygame.Rect(0, 0, 8, round(leaf.height * 0.55))
        )
        band.center = leaf.center
        pygame.draw.rect(screen, iron, band)
        pygame.draw.rect(screen, edge, band, 1)
        body = pygame.Rect(0, 0, 10, 10)
        body.center = band.center
        # The shackle stands out of the body across the leaf, so it is the half of the ring
        # facing off the door that is drawn: on a side wall that is the left half, not the top.
        if along_x:
            pygame.draw.arc(screen, shine, body.move(0, -5), 0, math.pi, 2)
        else:
            pygame.draw.arc(screen, shine, body.move(-5, 0), math.pi / 2, math.pi * 1.5, 2)
        pygame.draw.rect(screen, iron, body, border_radius=2)
        pygame.draw.rect(screen, edge, body, 1, border_radius=2)
        pygame.draw.circle(screen, edge, body.center, 2)

    def _lit_windows(self, darkness: float) -> frozenset:
        """Which of this building's windows have a lamp behind them, as indices.

        Nothing in the wilderness is ever lit, and how much of a settlement is awake is its
        tier (`Villages.LIT_WINDOW_FRAC_BY_TIER`): a border hamlet after dark is three
        windows and a deep wilds town is a constellation, which is the difference read from
        outside the wall at the hour the wall itself is hardest to see.

        The fraction is the share of the settlement's houses with somebody still up, not the
        share of one house's windows: read per window it lit every house in every settlement
        and rounded two tiers to the same answer, which is a village with no dark houses in
        it. A house that is up lights all of its own, so a street reads as houses rather than
        as panes. Rolled off the building's own id and kept, so the same houses stay lit all
        night."""
        if self.village_tier < 0 or darkness < c.DayNight.CURFEW_DARKNESS:
            return frozenset()
        if self._lamps is None:
            ladder = c.Villages.LIT_WINDOW_FRAC_BY_TIER
            frac = ladder[max(0, min(self.village_tier, len(ladder) - 1))]
            awake = random.Random(f"lamps:{self.id}").random() < frac
            self._lamps = frozenset(range(len(self.window_rects()))) if awake else frozenset()
        return self._lamps

    @staticmethod
    def _draw_window(
        screen,
        camera: Camera,
        window: pygame.Rect,
        broken: bool,
        damage_key: str = "",
        hp_frac: float = 1.0,
        lit: float = 0.0,
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
        if lit > 0:
            # A lamp behind the glass: a little spill on the wall around it, so the pane is
            # the brightest thing in it, and both are worth more the darker it has got.
            reach = round(max(pane.width, pane.height) * 1.6)
            glow = pygame.Surface((reach * 2, reach * 2), pygame.SRCALPHA)
            for step in (3, 2, 1):
                pygame.draw.circle(glow, (*c.Villages.WINDOW_LIGHT, round(14 * lit)), (reach, reach), reach * step / 3)
            screen.blit(glow, (pane.centerx - reach, pane.centery - reach))
            pygame.draw.rect(screen, c.Villages.WINDOW_LIGHT, pane)
        else:
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
