from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera


def has_tunnel(chunk: tuple[int, int]) -> bool:
    """Whether the well of the village in this chunk goes anywhere. A pure function of the
    coordinates, like everything else about where a place is: the same well always leads to
    the same nothing, or to the same tunnel."""
    return random.Random(f"tunnel:{int(chunk[0])},{int(chunk[1])}").random() < c.Tunnels.CHANCE


# The lantern gradient at full size, and the small stack it is scaled up from. The light
# is no longer one fixed circle: it flickers and slowly dims, so it is scaled per frame to
# whatever the tunnel says it is throwing right now, keyed on the radius in coarse steps so
# a steady light costs one dict lookup.
_LANTERN_SMALL: pygame.Surface | None = None
_LANTERN_BY_RADIUS: dict[int, pygame.Surface] = {}
# The dark itself, kept for the life of the process and refilled each frame. A fresh
# screen-sized alpha surface every frame is an allocation the size of the window for
# something whose contents never change but for where the light is cut out of it.
_DARK_OVERLAY: pygame.Surface | None = None


def _distance_to_rect(rect: pygame.Rect, x: float, y: float) -> float:
    """How far a point is from the nearest edge of a rectangle, zero inside it."""
    dx = max(rect.left - x, 0.0, x - rect.right)
    dy = max(rect.top - y, 0.0, y - rect.bottom)
    return math.hypot(dx, dy)


def _lantern_mask(radius: int | None = None) -> pygame.Surface:
    """The player's light as one continuous gradient at `radius` pixels, built once per
    coarse radius and kept.

    Drawn small and then scaled up: circles on an alpha surface overwrite rather than blend,
    so any stack of them is a set of steps, and the scale up interpolates those steps into a
    ramp. Alpha runs from clear at the middle to full dark at the radius, squared so the
    light holds its ground close in and gives out quickly at the edge. The radius is
    quantised to 16px, so the flicker only ever picks a mask that is already scaled.
    """
    global _LANTERN_SMALL
    if _LANTERN_SMALL is None:
        steps = 48
        small = pygame.Surface((steps * 2, steps * 2), pygame.SRCALPHA)
        small.fill((0, 0, 0, c.Tunnels.DARKNESS))
        for step in range(steps, 0, -1):
            alpha = round(c.Tunnels.DARKNESS * (step / steps) ** 2)
            pygame.draw.circle(small, (0, 0, 0, alpha), (steps, steps), step)
        _LANTERN_SMALL = small

    want = c.Tunnels.LIGHT_RADIUS if radius is None else max(16, round(radius / 16) * 16)
    cached = _LANTERN_BY_RADIUS.get(want)
    if cached is None:
        cached = pygame.transform.smoothscale(_LANTERN_SMALL, (want * 2, want * 2))
        _LANTERN_BY_RADIUS[want] = cached
    return cached


class Tunnel:
    """The dark under the world: a few rooms joined by corridors, reached either by climbing
    down a village well or by walking into a cave mouth out in the wilds.

    It is not a separate place in any technical sense. A tunnel is carved out of ordinary
    world space, a very long way from any ground that streams in (`c.Tunnels.ORIGIN`), which
    is what lets the player, the monsters, the projectiles, the loot and the save work down
    there exactly as they do above without one of them knowing where they are. What makes it
    read as underground is what `World` does while the player is in one: no chunks are
    generated, nothing wanders in, the sky is not drawn, and the only light is the player's.

    `kind` is only where the way in was: a well's tunnel is a short dug-out under a
    settlement, a cave is bigger and worse guarded, and the two are told apart in the id so
    a village and a landmark sharing a chunk can never share a tunnel.

    Collision is the floor rather than the walls: everywhere outside the rooms and corridors
    is solid rock, so `blocks` asks whether a body of that size fits inside one of them. Its
    layout comes from the village's chunk alone; the two things a player changes about it,
    how much of the garrison is left and whether the hoard has been put out, are what the
    world saves.
    """

    def __init__(self, chunk: tuple[int, int], kind: str = "well"):
        self.chunk = (int(chunk[0]), int(chunk[1]))
        self.kind = kind
        self.guards_alive: int | None = None
        self.hoard_placed = False
        # A cave's last room is its vault: a dead end with one guaranteed legendary box in
        # it and, far enough out, a warden standing over it. Both are one-time, so both are
        # remembered here rather than rolled again on the next climb down.
        self.vault_placed = False
        self.warden_alive: bool | None = None
        # What the model called the warden the first time anybody met it. Kept so the same
        # creature is not renamed on every descent, and so it is not named at all on the
        # second one.
        self.warden_name = ""

        # A well's layout is seeded exactly as it always was, so a game saved standing in
        # one loads back into the same rooms rather than into solid rock.
        seed = f"tunnel-layout:{self.chunk[0]},{self.chunk[1]}"
        rng = random.Random(seed if kind == "well" else f"tunnel-layout:{kind}:{self.chunk[0]},{self.chunk[1]}")
        # A cave is dug in its own corner of that far-off space, so a landmark and a well
        # that happen to share a chunk can never be laid out on top of each other.
        origin = c.Tunnels.ORIGIN + (0 if kind == "well" else c.Tunnels.CAVE_OFFSET)
        origin_x = origin + self.chunk[0] * c.Tunnels.SPACING
        origin_y = origin + self.chunk[1] * c.Tunnels.SPACING

        self.rooms: list[pygame.Rect] = []
        self.corridors: list[pygame.Rect] = []
        x, y = origin_x, origin_y
        for index in range(rng.randint(*c.Tunnels.ROOMS[kind])):
            width = rng.randint(*c.Tunnels.ROOM_SIZE)
            height = rng.randint(*c.Tunnels.ROOM_SIZE)
            room = pygame.Rect(0, 0, width, height)
            room.center = (round(x), round(y))
            self.rooms.append(room)
            if index:
                self.corridors.extend(self._dig(self.rooms[-2].center, room.center))
            angle = rng.uniform(0, 2 * math.pi)
            gap = rng.uniform(*c.Tunnels.ROOM_GAP)
            x, y = x + math.cos(angle) * gap, y + math.sin(angle) * gap

        self._floor = self.rooms + self.corridors
        # Which pieces of floor open onto which, worked out once. The player's light travels
        # along these and nowhere else, so it reaches round a doorway without ever crossing
        # rock (see `_lit_floor`).
        self._adjacent = [
            [j for j, other in enumerate(self._floor) if j != i and rect.colliderect(other)]
            for i, rect in enumerate(self._floor)
        ]
        # The shaft comes down into the first room, and it is the only way back up.
        self.entrance = self.rooms[0].center
        # The furthest room from the way in, which is the one worth walking to. A well has
        # none: a cellar under a village is not an expedition.
        self.vault = self.rooms[-1] if kind != "well" and len(self.rooms) > 1 else None

        # --- session-only mood, rebuilt every descent -------------------------------------
        # None of this is saved: how frightening the dark is on this trip is not something a
        # save should carry, only how much of the garrison is left is. `menace` is the one
        # number the rest read, `light_scale` what the lantern actually throws this frame
        # once the flicker and the slow dimming are in it, `blackout` the beat a down
        # draught has it out, `pressure` how hard the unseen warden leans on the vignette.
        self.menace = 0.0
        self.light_scale = 1.0
        self.blackout = 0.0
        self.pressure = 0.0
        self.time_in = 0.0
        self._blackout_gap = 0.0
        self._blackout_room = -1
        self._flicker = 0.0
        self.ambient_timer = 0.0
        self.breath_timer = 0.0
        self.bat_timer = 0.0

    @property
    def id(self) -> str:
        # A well's tunnel keeps the id it has always had, so a save made before there were
        # caves still finds the tunnel it left half cleared.
        if self.kind == "well":
            return f"tunnel:{self.chunk[0]}:{self.chunk[1]}"
        return f"tunnel:{self.kind}:{self.chunk[0]}:{self.chunk[1]}"

    @property
    def guard_count(self) -> tuple[int, int]:
        return c.Tunnels.GUARDS[self.kind]

    @staticmethod
    def _dig(start, end) -> list[pygame.Rect]:
        """The two legs of the passage between two room centres, horizontal then vertical.

        Starting and ending at the centres is what keeps the floor one connected piece: each
        leg runs well inside the rooms at both ends, so nothing can be standing in a gap
        between a corridor and the room it opens onto."""
        width = c.Tunnels.CORRIDOR_WIDTH
        (x0, y0), (x1, y1) = start, end
        across = pygame.Rect(min(x0, x1), y0 - width // 2, abs(x1 - x0), width)
        down = pygame.Rect(x1 - width // 2, min(y0, y1), width, abs(y1 - y0))
        return [across, down]

    def blocks(self, x: float, y: float, radius: float) -> bool:
        """Solid rock everywhere the floor is not. Something of `radius` is in the clear where
        its whole footprint lies on floor, the *union* of the rectangles rather than any one
        of them.

        Testing each rectangle on its own is what put invisible walls across every doorway:
        a body straddling the seam where a corridor opens onto a room fits inside neither,
        even though the floor under it is unbroken. The footprint is tested at its centre and
        its four corners, which is enough for axis-aligned rectangles that overlap by far
        more than a body is wide."""
        for px, py in (
            (x, y),
            (x - radius, y - radius),
            (x + radius, y - radius),
            (x - radius, y + radius),
            (x + radius, y + radius),
        ):
            if not any(rect.left <= px <= rect.right and rect.top <= py <= rect.bottom for rect in self._floor):
                return True
        return False

    def _lit_floor(self, x: float, y: float) -> list[pygame.Rect]:
        """The pieces of floor the player's light may fall on: the ones they are standing on,
        and everything joined to those that is close enough to be lit at all.

        Clipping to the single rectangle under the player is what made the dark flicker: a
        room and the corridor leaving it are two rectangles, so half of a doorway went black
        and the whole view snapped over as the player crossed the seam. Spreading along the
        overlaps instead means the light stops at rock (it never jumps to floor that is not
        joined to the floor being stood on) while the set of lit pieces only ever changes at
        the light's own radius, where the piece was contributing nothing anyway.
        """
        reach = c.Tunnels.LIGHT_RADIUS
        here = [i for i, rect in enumerate(self._floor) if rect.collidepoint(x, y)]
        if not here:
            # Off the floor entirely (thrown clear, or loaded standing in rock): light the
            # nearest piece rather than nothing at all.
            here = [min(range(len(self._floor)), key=lambda i: _distance_to_rect(self._floor[i], x, y))]
        seen = set(here)
        queue = list(here)
        while queue:
            for j in self._adjacent[queue.pop()]:
                if j in seen or _distance_to_rect(self._floor[j], x, y) > reach:
                    continue
                seen.add(j)
                queue.append(j)
        return [self._floor[i] for i in seen]

    def contains_point(self, x: float, y: float) -> bool:
        return any(rect.collidepoint(x, y) for rect in self._floor)

    def room_index_at(self, x: float, y: float) -> int:
        """Which room the point is in, or -1 in a corridor or in rock. Used to roll the
        down-draught per room the player walks into rather than per frame."""
        for i, room in enumerate(self.rooms):
            if room.collidepoint(x, y):
                return i
        return -1

    def update_atmosphere(self, dt: float, player, warden_dist: float | None):
        """Everything about how the dark feels right now, folded into the handful of numbers
        the renderer reads. Session-only and recomputed every frame the player is down here.

        `menace` climbs with depth from the shaft and with how close the warden is, well
        past the light so it is felt before it is seen. The lantern flickers harder and
        dims slower the higher it runs, and never quite recovers until the player is back
        near the way out. A down draught is rolled once per room walked into, seeded from
        the room so a cave that put the light out here last time does it again."""
        self.time_in += dt
        px, py = player.x, player.y
        d_shaft = math.hypot(px - self.entrance[0], py - self.entrance[1])

        depth = min(1.0, d_shaft / c.Tunnels.MENACE_DEPTH_PACES)
        warden01 = 0.0
        if warden_dist is not None:
            warden01 = max(0.0, 1.0 - warden_dist / c.Tunnels.MENACE_WARDEN_RANGE)
        self.menace = max(depth * 0.6, warden01)

        # The slow dim: worst deep in after a long time down, eased off near the shaft.
        held = min(1.0, self.time_in / (c.Tunnels.DIM_FULL_S * 1000.0))
        near_out = max(0.0, 1.0 - d_shaft / c.Tunnels.DIM_RECOVER_PACES)
        dim = 1.0 - (1.0 - c.Tunnels.DIM_FLOOR) * held * (1.0 - near_out)

        # The flicker: a cheap wander, two sines beating against each other, deep as menace.
        now = pygame.time.get_ticks()
        wander = 0.5 + 0.5 * math.sin(now * 0.011) * math.sin(now * 0.037 + 1.3)
        amount = c.Tunnels.FLICKER_MIN + (c.Tunnels.FLICKER_MAX - c.Tunnels.FLICKER_MIN) * self.menace
        self.light_scale = max(0.2, dim * (1.0 - amount * wander))

        self.blackout = max(0.0, self.blackout - dt)
        self._blackout_gap = max(0.0, self._blackout_gap - dt)
        room = self.room_index_at(px, py)
        started = False
        if room >= 0 and room != self._blackout_room:
            self._blackout_room = room
            if self._blackout_gap <= 0 and room != 0:
                roll = random.Random(f"blackout:{self.id}:{room}").random()
                if roll < c.Tunnels.BLACKOUT_CHANCE:
                    self.blackout = c.Tunnels.BLACKOUT_MS
                    self._blackout_gap = c.Tunnels.BLACKOUT_MIN_GAP_S * 1000.0
                    started = True

        lit = c.Tunnels.LIGHT_RADIUS * self.light_scale
        self.pressure = warden01 if (warden_dist is not None and warden_dist > lit * 1.1) else 0.0
        return started

    def at_exit(self, x: float, y: float) -> bool:
        return math.hypot(x - self.entrance[0], y - self.entrance[1]) <= c.Tunnels.EXIT_RADIUS

    def guard_killed(self):
        if self.guards_alive:
            self.guards_alive -= 1

    @property
    def cleared(self) -> bool:
        return self.guards_alive == 0

    def state(self) -> dict:
        return {
            "guards_alive": self.guards_alive,
            "hoard_placed": self.hoard_placed,
            "vault_placed": self.vault_placed,
            "warden_alive": self.warden_alive,
            "warden_name": self.warden_name,
        }

    def apply_state(self, state: dict):
        self.guards_alive = state.get("guards_alive")
        self.hoard_placed = state.get("hoard_placed", False)
        self.vault_placed = state.get("vault_placed", False)
        self.warden_alive = state.get("warden_alive")
        self.warden_name = state.get("warden_name", "")

    def floor_spots(self, count: int, rng: random.Random, clearance: float = 0.0) -> list[tuple[float, float]]:
        """`count` points scattered over the rooms, for whatever has to be stood up down
        here. The rooms only: nothing is put in a corridor, which is what the player walks.

        `clearance` keeps them off the shaft. Somebody standing at the foot of the ladder is
        an ambush the player was given no chance to read, and the first thing they see of
        the dark should be the dark."""
        spots = []
        for _ in range(count):
            for _ in range(12):
                room = rng.choice(self.rooms)
                spot = (
                    rng.uniform(room.left + 70, room.right - 70),
                    rng.uniform(room.top + 70, room.bottom - 70),
                )
                if math.hypot(spot[0] - self.entrance[0], spot[1] - self.entrance[1]) >= clearance:
                    break
            spots.append(spot)
        return spots

    # ------------------------------------------------------------------ drawing

    def draw(self, screen: pygame.Surface, camera: Camera):
        """The rock, then the floor cut out of it. Drawn as two passes over the same
        rectangles rather than as outlines: an outline would draw a wall across every
        doorway, since a doorway here is just where two rectangles overlap."""
        screen.fill(c.Tunnels.ROCK_COLOR)
        rim = tuple(round(v * 0.72) for v in c.Tunnels.FLOOR_COLOR)
        for rect in self._floor:
            screen.fill(rim, self._to_screen(camera, rect.inflate(16, 16)))
        for rect in self._floor:
            screen.fill(c.Tunnels.FLOOR_COLOR, self._to_screen(camera, rect))

        for room in self.rooms:
            self._draw_rubble(screen, camera, room)
        self._draw_shaft(screen, camera)

    @staticmethod
    def _to_screen(camera: Camera, rect: pygame.Rect) -> pygame.Rect:
        x, y = camera.world_to_screen(rect.x, rect.y)
        return pygame.Rect(x, y, rect.width, rect.height)

    @staticmethod
    def _draw_rubble(screen: pygame.Surface, camera: Camera, room: pygame.Rect):
        """Loose stone on the floor, seeded from the room's own position so it holds still
        while the camera moves. Without it a room is a flat brown rectangle."""
        rng = random.Random(f"rubble:{room.x},{room.y}")
        dark = tuple(round(v * 0.82) for v in c.Tunnels.FLOOR_COLOR)
        for _ in range(18):
            x = rng.uniform(room.left + 20, room.right - 20)
            y = rng.uniform(room.top + 20, room.bottom - 20)
            screen_x, screen_y = camera.world_to_screen(x, y)
            pygame.draw.circle(screen, dark, (screen_x, screen_y), rng.randint(3, 9))

    def _draw_shaft(self, screen: pygame.Surface, camera: Camera):
        """The way out: daylight on the floor, and the ladder standing in it under a well.
        The one thing down here the player has to be able to find again, so it is drawn
        whatever else the dark is hiding."""
        x, y = camera.world_to_screen(*self.entrance)
        pygame.draw.circle(screen, (108, 104, 88), (x, y), 54)
        pygame.draw.circle(screen, (146, 142, 118), (x, y), 38)
        if self.kind != "well":
            # A cave is walked out of rather than climbed: the daylight is the whole marker.
            pygame.draw.circle(screen, (188, 184, 156), (x, y), 22)
            return
        for rung in range(-2, 3):
            pygame.draw.line(screen, c.Tunnels.LADDER_COLOR, (x - 16, y + rung * 12), (x + 16, y + rung * 12), 3)
        for side in (-16, 16):
            pygame.draw.line(screen, c.Tunnels.LADDER_COLOR, (x + side, y - 26), (x + side, y + 26), 3)

    def draw_dark(self, screen: pygame.Surface, camera: Camera, player):
        """Everything past the player's own light. Drawn over the entities, so a monster is
        heard before it is seen and the dark is the tunnel's real difficulty.

        The light is one gradient rather than a stack of circles: circles drawn onto an alpha
        surface replace the pixels under them rather than blending, so each one left a hard
        edge and the lantern read as a set of rings.

        And it stops at the rock. The lantern used to be cut out of the dark as a plain
        circle, which meant it shone straight through a wall: standing in a corridor lit the
        rooms on the far side of it and gave the whole layout away from the doorway. The
        cut-out is clipped to the floor the light can actually reach (`_lit_floor`: what is
        being stood on and whatever opens onto it), so what is round a corner stays round
        it while a doorway is lit on both sides of the seam."""
        global _DARK_OVERLAY
        if _DARK_OVERLAY is None:
            _DARK_OVERLAY = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay = _DARK_OVERLAY
        overlay.fill((0, 0, 0, c.Tunnels.DARKNESS))
        x, y = camera.world_to_screen(player.x, player.y)
        # What the lantern is throwing this frame: the slow dim and the flicker are already
        # in `light_scale`, and a down draught collapses it to almost nothing for a beat.
        scale = self.light_scale * (0.12 if self.blackout > 0 else 1.0)
        radius = round(c.Tunnels.LIGHT_RADIUS * scale)
        light = _lantern_mask(radius)
        area = light.get_rect(center=(x, y))
        # Taking the lower of the two alphas cuts the light out of the dark: inside the
        # radius the gradient wins, outside it the mask is already full dark and nothing
        # changes. Done once per piece of floor under the player, clipped to that piece.
        for rect in self._lit_floor(player.x, player.y):
            overlay.set_clip(self._to_screen(camera, rect))
            overlay.blit(light, area, special_flags=pygame.BLEND_RGBA_MIN)
        overlay.set_clip(None)
        screen.blit(overlay, (0, 0))
        self._draw_omens(screen, camera, player, radius)

    def _draw_omens(self, screen: pygame.Surface, camera: Camera, player, lit_radius: int):
        """Shapes in the dark just past the light: a pair of eyes, a hunched outline. Almost
        all of them are nothing, they hold still in world space while the camera moves, and
        they are drawn over the darkness rather than cut out of it, so the light never falls
        on one to prove it is not there. Seeded per room, so the same corner of the same
        cave is watched on every descent."""
        room = self.room_index_at(player.x, player.y)
        if room < 0:
            return
        rect = self.rooms[room]
        rng = random.Random(f"omen:{self.id}:{room}")
        now = pygame.time.get_ticks()
        count = rng.randint(*c.Tunnels.OMEN_PER_ROOM)
        for i in range(count):
            ox = rng.uniform(rect.left + 30, rect.right - 30)
            oy = rng.uniform(rect.top + 30, rect.bottom - 30)
            dist = math.hypot(ox - player.x, oy - player.y)
            # Only in the band that is dark but near: on the light and it would be a real
            # thing, far off and it is not glimpsed at all.
            if dist < lit_radius * 0.9 or dist > lit_radius * 2.1:
                continue
            period = c.Tunnels.OMEN_FADE_MS * rng.uniform(1.6, 3.4)
            phase = (now + i * 900) % period / period
            glow = math.sin(phase * math.pi)
            if glow < 0.45:
                continue
            alpha = round(70 * (glow - 0.45) / 0.55)
            sx, sy = camera.world_to_screen(ox, oy)
            shape = pygame.Surface((28, 36), pygame.SRCALPHA)
            if rng.random() < 0.5:
                for cx in (10, 18):
                    pygame.draw.circle(shape, (170, 150, 120, min(255, alpha * 2)), (cx, 18), 2)
            else:
                pygame.draw.ellipse(shape, (8, 8, 10, alpha), (5, 2, 18, 24))
                pygame.draw.ellipse(shape, (8, 8, 10, alpha), (3, 18, 22, 16))
            screen.blit(shape, shape.get_rect(center=(sx, sy)))
