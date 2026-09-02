from __future__ import annotations

import math
import random

import pygame

import core.constants as c
from core.camera import Camera
from core.daynight import DayNightCycle
from game.entities.critter import Critter
from game.entities.npcs import NPC
from game.entities.terrain import generate_chunk_scenery
from game.entities.village_generation import generate_village
from game.entities.village_sites import clear_registered_sites, register_settlement


class _Nobody:
    """The player, from the point of view of a street with no player in it.

    `NPC.update` and `Critter.update` are written around somebody being there to notice, so
    the title screen hands them someone standing impossibly far away: everyone wanders, the
    dogs stroll, and nothing turns to face a camera that is not a person.
    """

    x = y = -1e9
    size = 0

    def get_pos(self, _distance=None):
        return (self.x, self.y)


class MenuScene:
    """The village the title screen stands over: a real settlement, laid out by the same
    generator the world uses, with its own people walking around it under a moving sky.

    Nothing here is the game: it is thrown away the moment a game starts, holds no save and
    no player. What it is for is that the first thing seen should be the world rather than a
    dark rectangle with two buttons on it. A fresh settlement is rolled per launch, so the
    title screen is a different place every time the game is opened.
    """

    # Kept a good deal quicker than the world's, so the light visibly moves while the player
    # is deciding rather than sitting on one flat hour.
    TIME_SCALE = 8.0
    # The camera drifts round the plaza rather than sitting still: a static shot of a village
    # reads as a screenshot, and the pan is what says the place is running.
    PAN_RADIUS = 320
    PAN_PERIOD_MS = 46_000

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.camera = Camera()
        # Always opens in daylight and runs on from there: the title screen has to be read,
        # and a launch that happened to start at midnight would be a black rectangle again.
        self.daynight = DayNightCycle(random.uniform(0, c.DayNight.DAY_END * c.DayNight.CYCLE_LENGTH_MS * 0.6))

        # Somewhere far from the world the save file knows about, so nothing here can be
        # mistaken for a place the player has been.
        chunk = (random.randint(-9000, 9000), random.randint(-9000, 9000))
        size = c.World.CHUNK_SIZE
        self.center = ((chunk[0] + 0.5) * size, (chunk[1] + 0.5) * size)
        self.village, self.buildings = generate_village(self.center[0], self.center[1], chunk)
        # The title screen's village stands in the middle of its chunk rather than wherever
        # that chunk's region would have put one, so the roads and the river laid out from
        # the sites know nothing about it: without this one is drawn straight through the
        # houses. Registering it is also what `World` does with the starting town, and
        # `World` clears the registry when a game begins, so nothing here leaks into it.
        clear_registered_sites()
        register_settlement(chunk, self.village.x, self.village.y, self.village.grounds_radius)
        # Its lanes after that, not before: they run out to where the roads stop, and until
        # the settlement is registered there are no roads coming to it.
        self.village.plan_streets(self.buildings)

        self.scenery = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.scenery += generate_chunk_scenery(chunk[0] + dx, chunk[1] + dy, self.buildings, [self.village], [])
        self.ground = [item for item in self.scenery if item.ground]
        self.props = [item for item in self.scenery if not item.ground]

        self.npcs = self._populate()
        self.critters = self._dogs()
        self.nobody = _Nobody()
        self._elapsed_ms = 0.0

    def _populate(self) -> list:
        """The same people `World._populate_npcs` puts in a village: a merchant at each shop
        and a villager or two at every home."""
        npcs = []
        for shop in (b for b in self.buildings if b.kind == "shop"):
            merchant = NPC(*shop.door_front())
            merchant.is_merchant = True
            merchant.color = c.Colors.MERCHANT
            npcs.append(merchant)
        for home in (b for b in self.buildings if b.kind in ("house", "tavern")):
            door_x, door_y = home.door_front()
            for _ in range(random.randint(*c.Villages.VILLAGERS_PER_HOME)):
                villager = NPC(door_x + random.randint(-80, 80), door_y + random.randint(0, 80))
                villager.home = (door_x, door_y)
                npcs.append(villager)
        return npcs

    def _dogs(self) -> list:
        """The village's dogs, in the street rather than on the roofs: a spot inside a
        footprint is rolled again, the same rule `World._ensure_village_dogs` follows."""
        dogs = []
        kind = c.CRITTER_KINDS_BY_NAME["dog"]
        for _ in range(random.randint(*c.Wildlife.VILLAGE_DOGS)):
            for _attempt in range(10):
                angle = random.uniform(0, 2 * math.pi)
                distance = random.uniform(self.village.radius * 0.2, self.village.radius * 0.5)
                x = self.village.x + math.cos(angle) * distance
                y = self.village.y + math.sin(angle) * distance
                if self._blocked(x, y, kind.size / 2) or any(b.covers(x, y, kind.size / 2) for b in self.buildings):
                    continue
                dogs.append(Critter(x, y, kind, home=(x, y)))
                break
        return dogs

    def _blocked(self, x, y, radius) -> bool:
        if self.village.blocks(x, y, radius):
            return True
        if any(building.blocks(x, y, radius) for building in self.buildings):
            return True
        return any(item.blocks(x, y, radius) for item in self.props)

    def update(self, dt):
        self._elapsed_ms += dt
        self.daynight.update(dt * self.TIME_SCALE)
        angle = 2 * math.pi * (self._elapsed_ms % self.PAN_PERIOD_MS) / self.PAN_PERIOD_MS
        self.camera.set_pos(
            (
                self.village.x + math.cos(angle) * self.PAN_RADIUS,
                self.village.y + math.sin(angle) * self.PAN_RADIUS * 0.6,
            )
        )
        for npc in self.npcs:
            npc.update(self.nobody, dt, self._blocked, face_player=False)
        for critter in self.critters:
            critter.update(self.nobody, dt, self._blocked)

    def draw(self):
        """The same order `GameRenderer.draw_world` uses: ground, plaza, buildings, then
        everything standing on top of them."""
        self.screen.fill(c.Colors.GREEN)
        for kind in c.Scenery.GROUND_KINDS:
            for item in self.ground:
                if item.kind == kind:
                    item.draw(self.screen, self.camera)
        self.village.draw(self.screen, self.camera)
        for building in self.buildings:
            building.draw(self.screen, self.camera)
        for item in self.props:
            item.draw(self.screen, self.camera)
        for critter in self.critters:
            critter.draw(self.screen, self.camera)
        for npc in self.npcs:
            npc.draw(self.screen, self.camera, health_bar=False)
        self.daynight.draw(self.screen, 0.0)
