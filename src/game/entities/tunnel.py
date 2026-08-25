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


_LANTERN_MASK: pygame.Surface | None = None
# The dark itself, kept for the life of the process and refilled each frame. A fresh
# screen-sized alpha surface every frame is an allocation the size of the window for
# something whose contents never change but for where the light is cut out of it.
_DARK_OVERLAY: pygame.Surface | None = None


def _lantern_mask() -> pygame.Surface:
    """The player's light as one continuous gradient, built once and kept.

    Drawn small and then scaled up: circles on an alpha surface overwrite rather than blend,
    so any stack of them is a set of steps, and the scale up interpolates those steps into a
    ramp. Alpha runs from clear at the middle to full dark at the radius, squared so the
    light holds its ground close in and gives out quickly at the edge.
    """
    global _LANTERN_MASK
    if _LANTERN_MASK is not None:
        return _LANTERN_MASK

    steps = 48
    small = pygame.Surface((steps * 2, steps * 2), pygame.SRCALPHA)
    small.fill((0, 0, 0, c.Tunnels.DARKNESS))
    for step in range(steps, 0, -1):
        alpha = round(c.Tunnels.DARKNESS * (step / steps) ** 2)
        pygame.draw.circle(small, (0, 0, 0, alpha), (steps, steps), step)
    size = c.Tunnels.LIGHT_RADIUS * 2
    _LANTERN_MASK = pygame.transform.smoothscale(small, (size, size))
    return _LANTERN_MASK


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
        # The shaft comes down into the first room, and it is the only way back up.
        self.entrance = self.rooms[0].center
        # The furthest room from the way in, which is the one worth walking to. A well has
        # none: a cellar under a village is not an expedition.
        self.vault = self.rooms[-1] if kind != "well" and len(self.rooms) > 1 else None

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

    def contains_point(self, x: float, y: float) -> bool:
        return any(rect.collidepoint(x, y) for rect in self._floor)

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
        cut-out is clipped to the floor the player is actually standing on (a room, a
        corridor, both where the two overlap), so what is round a corner stays round it."""
        global _DARK_OVERLAY
        if _DARK_OVERLAY is None:
            _DARK_OVERLAY = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay = _DARK_OVERLAY
        overlay.fill((0, 0, 0, c.Tunnels.DARKNESS))
        x, y = camera.world_to_screen(player.x, player.y)
        light = _lantern_mask()
        area = light.get_rect(center=(x, y))
        # Taking the lower of the two alphas cuts the light out of the dark: inside the
        # radius the gradient wins, outside it the mask is already full dark and nothing
        # changes. Done once per piece of floor under the player, clipped to that piece.
        for rect in self._floor:
            if not rect.collidepoint(player.x, player.y):
                continue
            overlay.set_clip(self._to_screen(camera, rect))
            overlay.blit(light, area, special_flags=pygame.BLEND_RGBA_MIN)
        overlay.set_clip(None)
        screen.blit(overlay, (0, 0))
