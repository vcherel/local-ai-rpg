"""How a settlement looks: its plaza, its lanes, its wall and everything hung on it.

Split off `village.py` the way `building_art.py` is split off `buildings.py`: that file
owns what a settlement *is* (where it stands, what it blocks, which gates are barred, where
its lanes run and what its board offers), this one owns nothing but paint. A search for how
a gate is worked never lands in three hundred lines of coursed stone, and vice versa.

Mixed into `Village` rather than written as free functions, because every one of these
draws from the geometry the settlement has already worked out for itself (`defences`,
`gate_leaves`, `streets`, `board_pos`): handing all of that to a function would be passing
the village in under another name.
"""

from __future__ import annotations

import math
import random
from itertools import pairwise
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.damage_fx import draw_cracks

if TYPE_CHECKING:
    from core.camera import Camera


class VillageArt:
    """Every drawing method `Village` has. See the module docstring for why it is a mixin."""

    @staticmethod
    def _lane_look(width: float, edge: bool) -> tuple[tuple, float]:
        """What a lane looks like where it is this wide, as the colour and how far out it
        reaches. A spur is trodden earth, a street is wider, lighter and verged like the road
        it carries on from, and the one worn out of a gate is both at either end of it: the
        whole look follows the one number that already tapers, so the two tracks never meet
        as a step.

        Full road at the width a road actually is (`ROAD_WIDTH[0]`) rather than at the widest
        one there can be: measured against the widest, a lane meeting a road of ordinary
        width was still half street-coloured on a half-width verge, and the round cap it
        ends in drew that difference on the road as a circle."""
        narrow, widest = c.Villages.STREET_SPUR_WIDTH, c.Scenery.ROAD_WIDTH[0]
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

        The stretches a lane out of a gate laps over the road are earth alone: the road has
        already laid its own verge there, and a second one on top of it is a dark ring drawn
        round the joint, since the lane paints a circle at every joint and its verge reaches
        further than the road's earth does.

        Only what is on screen is drawn, the same rule everything else in the world is drawn
        by, and the camera offset is asked for once: a town's lanes are the one loop here
        long enough for the call itself to cost something."""
        view = screen.get_rect().inflate(c.Scenery.ROAD_WIDTH[1] * 4, c.Scenery.ROAD_WIDTH[1] * 4)
        ox, oy = camera.world_to_screen(0, 0)
        lap = c.Villages.STREET_LAP_STRETCHES
        stretches = []
        for at, lane in enumerate(self.streets):
            for k, ((ax, ay, aw), (bx, by, bw)) in enumerate(pairwise(lane)):
                start = (round(ax + ox), round(ay + oy))
                end = (round(bx + ox), round(by + oy))
                if view.clipline(start, end):
                    stretches.append((start, end, (aw + bw) / 2, not (at in self._lapped and k < lap)))
        for edge in (True, False):
            for start, end, width, verged in stretches:
                if edge and not verged:
                    continue
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
