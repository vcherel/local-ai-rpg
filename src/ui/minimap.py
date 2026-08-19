from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets

if TYPE_CHECKING:
    from game.entities.player import Player
    from game.world import World


class Minimap:
    """The small map in the top right corner.

    It draws memory, not perception: the ground the player has already walked (World.explored),
    the buildings and landmarks standing on it, and the player's own arrow. No monsters, no
    NPCs, no loot, no quest marker, and a fixed zoom of about one and a half screens, so it
    can orient the player without ever doing their exploring for them. Everything not yet
    walked stays black.

    The one exception is a rumour's mark (World.rumor_marks): somewhere the player has been
    told about but never seen, which is the whole point of hearing a rumour. Under the panel
    sit the name of the village being stood in and the day/night clock, and the clock is
    drawn even when the map is toggled off.
    """

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.visible = True
        size = c.Minimap.SIZE
        self.rect = pygame.Rect(c.Screen.WIDTH - size - c.Minimap.MARGIN, c.Minimap.MARGIN, size, size)
        # Where the strips under the map actually ended last frame. It moves with the map
        # being toggled off and with the village strip coming and going, so whatever stacks
        # under this corner (the quest tracker) reads it instead of assuming a fixed offset.
        self.content_bottom = self.rect.bottom + c.Minimap.CLOCK_HEIGHT + 8

    def toggle(self):
        self.visible = not self.visible

    def draw(self, world: World, player: Player):
        # The clock is drawn whether or not the map is up: hiding the map hides where you
        # have been, not what time it is.
        if not self.visible:
            self._draw_strips(world, player, self.rect.top)
            return

        widgets.draw_panel(self.screen, self.rect)
        inner = self.rect.inflate(-c.Minimap.PADDING * 2, -c.Minimap.PADDING * 2)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(inner)
        pygame.draw.rect(self.screen, c.Minimap.UNSEEN_COLOR, inner)

        scale = inner.width / c.Minimap.RANGE

        def to_map(wx, wy) -> tuple:
            return (inner.centerx + (wx - player.x) * scale, inner.centery + (wy - player.y) * scale)

        self._draw_explored(world, player, inner, scale, to_map)
        self._draw_villages(world, player, scale, to_map)
        self._draw_buildings(world, player, scale, to_map)
        self._draw_pois(world, to_map)
        self._draw_rumors(world, inner, scale, to_map)
        self._draw_player(player, inner)

        self.screen.set_clip(previous_clip)
        self._draw_compass(inner)
        self._draw_strips(world, player, self.rect.bottom)

    def _draw_explored(self, world: World, player: Player, inner: pygame.Rect, scale: float, to_map):
        """The remembered ground, one flat square per explored cell. Cells are big enough
        that the edge of what the player knows reads as a ragged frontier."""
        cell = c.Fog.CELL
        half = c.Minimap.RANGE / 2
        size = math.ceil(cell * scale) + 1
        for gx in range(int((player.x - half) // cell), int((player.x + half) // cell) + 1):
            for gy in range(int((player.y - half) // cell), int((player.y + half) // cell) + 1):
                if (gx, gy) not in world.explored:
                    continue
                left, top = to_map(gx * cell, gy * cell)
                pygame.draw.rect(self.screen, c.Minimap.GROUND_COLOR, pygame.Rect(round(left), round(top), size, size))

    def _draw_villages(self, world: World, player: Player, scale: float, to_map):
        for village in world.villages:
            if not world.is_explored(village.x, village.y):
                continue
            if village.distance_to_point((player.x, player.y)) > c.Minimap.RANGE:
                continue
            cx, cy = to_map(village.x, village.y)
            radius = max(3, round(c.Villages.PLAZA_RADIUS * scale))
            pygame.draw.circle(self.screen, c.Minimap.PLAZA_COLOR, (round(cx), round(cy)), radius)

    def _draw_buildings(self, world: World, player: Player, scale: float, to_map):
        for building in world.buildings_in_range(player.x, player.y, c.Minimap.RANGE / 2):
            if not world.is_explored(building.x, building.y):
                continue
            left, top = to_map(building.rect.left, building.rect.top)
            rect = pygame.Rect(
                round(left), round(top), max(2, round(building.w * scale)), max(2, round(building.h * scale))
            )
            color = c.Buildings.ROOF_COLORS.get(building.kind, c.Buildings.STONE_COLOR)
            pygame.draw.rect(self.screen, color, rect)

    def _draw_pois(self, world: World, to_map):
        """Only the landmarks of loaded chunks, and only where the player has walked: a POI
        the map has never seen is exactly the thing worth going out to find."""
        for poi in world.pois:
            if not world.is_explored(poi.x, poi.y):
                continue
            x, y = to_map(poi.x, poi.y)
            color = c.Minimap.POI_COLORS.get(poi.kind, c.Colors.WHITE)
            if poi.kind == "camp":
                pygame.draw.polygon(self.screen, color, [(x, y - 4), (x - 4, y + 3), (x + 4, y + 3)])
            else:
                pygame.draw.circle(self.screen, color, (round(x), round(y)), 3)

    def _draw_player(self, player: Player, inner: pygame.Rect):
        """A small arrow at the middle of the map, pointing where the player faces. Sprites
        face up, so the facing angle is the orientation less a quarter turn."""
        angle = player.orientation - math.pi / 2
        cx, cy = inner.center
        tip = (cx + math.cos(angle) * 7, cy + math.sin(angle) * 7)
        left = (cx + math.cos(angle + 2.5) * 6, cy + math.sin(angle + 2.5) * 6)
        right = (cx + math.cos(angle - 2.5) * 6, cy + math.sin(angle - 2.5) * 6)
        pygame.draw.polygon(self.screen, c.Minimap.PLAYER_COLOR, [tip, left, right])
        pygame.draw.polygon(self.screen, (30, 30, 34), [tip, left, right], 1)

    def _draw_compass(self, inner: pygame.Rect):
        label = c.Fonts.small.render("N", True, c.Colors.MUTED)
        self.screen.blit(label, label.get_rect(midtop=(inner.centerx, inner.top + 2)))

    def _draw_rumors(self, world: World, inner: pygame.Rect, scale: float, to_map):
        """The one thing on this map the player has not walked to: where a rumour said to go.
        A lead further out than the map's range is pinned to the edge in its direction, so
        it still says which way to set off, and it is rubbed out on arrival by World."""
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 300.0)
        for mark in world.rumor_marks:
            x, y = to_map(mark["x"], mark["y"])
            x = min(max(x, inner.left + 6), inner.right - 6)
            y = min(max(y, inner.top + 6), inner.bottom - 6)
            radius = round(4 + 2 * pulse)
            pygame.draw.circle(self.screen, c.Minimap.RUMOR_COLOR, (round(x), round(y)), radius)
            pygame.draw.circle(self.screen, (40, 32, 12), (round(x), round(y)), radius, 1)

    def _draw_strips(self, world: World, player: Player, top: int):
        """The panels stacked under the map: the village standing on it, then the clock."""
        y = top + 4
        village = world.village_at(player.x, player.y)
        if village is not None and village.name and village.discovered:
            suffix, color = self._village_mood(world, village)
            text = self._fit_name(village.name, suffix, self.rect.width - c.Minimap.PADDING * 2)
            label = c.Fonts.small.render(text, True, color)
            strip = pygame.Rect(self.rect.left, y, self.rect.width, label.get_height() + 8)
            widgets.draw_panel(self.screen, strip)
            self.screen.blit(label, label.get_rect(center=strip.center))
            y = strip.bottom + 4
        self._draw_clock(world, y)
        self.content_bottom = y + c.Minimap.CLOCK_HEIGHT

    @staticmethod
    def _village_mood(world: World, village) -> tuple:
        """What this settlement's strip adds after its name: nothing, or how much longer it
        wants the player dead. Anger runs out now, so the player needs somewhere to read how
        long is left; the strip that already names the place they are standing in is it. A
        grudge (somebody was killed here) has no countdown to show, and never will."""
        angry = [npc for npc in world.npcs if npc.hostile and village.contains_point(npc.x, npc.y)]
        if not angry:
            return "", c.Colors.WHITE
        if any(npc.grudge for npc in angry):
            return ": never forgiven", c.Colors.RED
        remaining = max(npc.anger_remaining for npc in angry)
        return f": furious {int(remaining) // 60}:{int(remaining) % 60:02d}", c.Colors.RED

    @staticmethod
    def _fit_name(name: str, suffix: str, width: int) -> str:
        """Name plus mood, cut to the width of the strip. A long name with a countdown after
        it used to run out of the panel and across the map, so the name is what gives: the
        countdown is the part the player is reading."""
        if c.Fonts.small.size(name + suffix)[0] <= width:
            return name + suffix
        while name and c.Fonts.small.size(name + "..." + suffix)[0] > width:
            name = name[:-1]
        return name + "..." + suffix

    def _draw_clock(self, world: World, top: int):
        """The time of day, as a dial swept once per cycle plus the name of the phase. The
        marker is warm while it is light and cold once it is dark, so a glance says whether
        night is coming without reading the word."""
        daynight = world.daynight
        strip = pygame.Rect(self.rect.left, top, self.rect.width, c.Minimap.CLOCK_HEIGHT)
        widgets.draw_panel(self.screen, strip)

        radius = c.Minimap.CLOCK_HEIGHT // 2 - 7
        center = (strip.left + 8 + radius, strip.centery)
        night = daynight.is_night
        color = c.Minimap.CLOCK_NIGHT_COLOR if night else c.Minimap.CLOCK_DAY_COLOR
        pygame.draw.circle(self.screen, (60, 58, 66), center, radius, 1)

        # Midnight at the bottom of the dial, noon at the top, so the hand rises through
        # the morning and falls through the evening the way the sun does.
        angle = daynight.progress * 2 * math.pi - math.pi / 2
        hand = (center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius)
        pygame.draw.line(self.screen, color, center, hand, 2)
        pygame.draw.circle(self.screen, color, (round(hand[0]), round(hand[1])), 5)

        label = c.Fonts.small.render(daynight.phase, True, c.Colors.WHITE)
        self.screen.blit(label, label.get_rect(midleft=(center[0] + radius + 10, strip.centery)))
