from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List, Optional, Tuple

import pygame

import core.constants as c

if TYPE_CHECKING:
    from core.camera import Camera


def has_tunnel(chunk: Tuple[int, int]) -> bool:
    """Whether the well of the village in this chunk goes anywhere. A pure function of the
    coordinates, like everything else about where a place is: the same well always leads to
    the same nothing, or to the same tunnel."""
    return random.Random(f"tunnel:{int(chunk[0])},{int(chunk[1])}").random() < c.Tunnels.CHANCE


class Tunnel:
    """The dug-out under a village well: a few rooms joined by corridors, in the dark.

    It is not a separate place in any technical sense. A tunnel is carved out of ordinary
    world space, a very long way from any ground that streams in (`c.Tunnels.ORIGIN`), which
    is what lets the player, the monsters, the projectiles, the loot and the save work down
    there exactly as they do above without one of them knowing where they are. What makes it
    read as underground is what `World` does while the player is in one: no chunks are
    generated, nothing wanders in, the sky is not drawn, and the only light is the player's.

    Collision is the floor rather than the walls: everywhere outside the rooms and corridors
    is solid rock, so `blocks` asks whether a body of that size fits inside one of them. Its
    layout comes from the village's chunk alone; the two things a player changes about it,
    how much of the garrison is left and whether the hoard has been put out, are what the
    world saves.
    """

    def __init__(self, chunk: Tuple[int, int]):
        self.chunk = (int(chunk[0]), int(chunk[1]))
        self.guards_alive: Optional[int] = None
        self.hoard_placed = False

        rng = random.Random(f"tunnel-layout:{self.chunk[0]},{self.chunk[1]}")
        origin_x = c.Tunnels.ORIGIN + self.chunk[0] * c.Tunnels.SPACING
        origin_y = c.Tunnels.ORIGIN + self.chunk[1] * c.Tunnels.SPACING

        self.rooms: List[pygame.Rect] = []
        self.corridors: List[pygame.Rect] = []
        x, y = origin_x, origin_y
        for index in range(rng.randint(*c.Tunnels.ROOMS)):
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

    @property
    def id(self) -> str:
        return f"tunnel:{self.chunk[0]}:{self.chunk[1]}"

    @staticmethod
    def _dig(start, end) -> List[pygame.Rect]:
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
        """Solid rock everywhere the floor is not. Something of `radius` is in the clear only
        where it fits inside one of the floor rectangles with room to spare."""
        for rect in self._floor:
            if rect.left + radius <= x <= rect.right - radius and rect.top + radius <= y <= rect.bottom - radius:
                return False
        return True

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
        return {"guards_alive": self.guards_alive, "hoard_placed": self.hoard_placed}

    def apply_state(self, state: dict):
        self.guards_alive = state.get("guards_alive")
        self.hoard_placed = state.get("hoard_placed", False)

    def floor_spots(self, count: int, rng: random.Random) -> List[Tuple[float, float]]:
        """`count` points scattered over the rooms, for whatever has to be stood up down
        here. The rooms only: nothing is put in a corridor, which is what the player walks."""
        spots = []
        for _ in range(count):
            room = rng.choice(self.rooms)
            spots.append(
                (
                    rng.uniform(room.left + 70, room.right - 70),
                    rng.uniform(room.top + 70, room.bottom - 70),
                )
            )
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
        """The bottom of the well: daylight on the floor and the ladder standing in it, the
        one thing down here the player has to be able to find again."""
        x, y = camera.world_to_screen(*self.entrance)
        pygame.draw.circle(screen, (108, 104, 88), (x, y), 54)
        pygame.draw.circle(screen, (146, 142, 118), (x, y), 38)
        for rung in range(-2, 3):
            pygame.draw.line(screen, c.Tunnels.LADDER_COLOR, (x - 16, y + rung * 12), (x + 16, y + rung * 12), 3)
        for side in (-16, 16):
            pygame.draw.line(screen, c.Tunnels.LADDER_COLOR, (x + side, y - 26), (x + side, y + 26), 3)

    @staticmethod
    def draw_dark(screen: pygame.Surface, camera: Camera, player):
        """Everything past the player's own light. Drawn over the entities, so a monster is
        heard before it is seen and the dark is the tunnel's real difficulty."""
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, c.Tunnels.DARKNESS))
        x, y = camera.world_to_screen(player.x, player.y)
        steps = 24
        for step in range(steps, 0, -1):
            radius = round(c.Tunnels.LIGHT_RADIUS * step / steps)
            alpha = round(c.Tunnels.DARKNESS * (step / steps) ** 2)
            pygame.draw.circle(overlay, (0, 0, 0, alpha), (x, y), radius)
        screen.blit(overlay, (0, 0))
