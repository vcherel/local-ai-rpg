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
    """

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.visible = True
        size = c.Minimap.SIZE
        self.rect = pygame.Rect(c.Screen.WIDTH - size - c.Minimap.MARGIN, c.Minimap.MARGIN, size, size)

    def toggle(self):
        self.visible = not self.visible

    def draw(self, world: World, player: Player):
        if not self.visible:
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
        self._draw_player(player, inner)

        self.screen.set_clip(previous_clip)
        self._draw_compass(inner)
        self._draw_here_label(world, player)

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

    def _draw_here_label(self, world: World, player: Player):
        """The name of the village the player is standing in, under the map. The only place
        a name is spelled out, so the map itself stays a picture."""
        village = world.village_at(player.x, player.y)
        if village is None or not village.name or not village.discovered:
            return
        label = c.Fonts.small.render(village.name, True, c.Colors.WHITE)
        strip = pygame.Rect(self.rect.left, self.rect.bottom + 4, self.rect.width, label.get_height() + 8)
        widgets.draw_panel(self.screen, strip)
        self.screen.blit(label, label.get_rect(center=strip.center))
