from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets

if TYPE_CHECKING:
    from game.entities.player import Player
    from game.world import World


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    """`a` blended toward `b`, `t` clamped to 0..1. The one thing the sky strip is painted
    through: its colours are all one colour on the way to another."""
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Minimap:
    """The small map in the top right corner.

    It draws memory, not perception: the ground the player has already walked (World.explored),
    the buildings and landmarks standing on it, and the player's own arrow. No monsters, no
    NPCs, no loot, no quest marker, and a fixed zoom of about one and a half screens, so it
    can orient the player without ever doing their exploring for them. Everything not yet
    walked stays black.

    The one exception is a rumour's mark (World.rumor_marks): somewhere the player has been
    told about but never seen, which is the whole point of hearing a rumour. Where the
    player last died (World.death_drop) is drawn on the same terms and for the same reason:
    their coins and their gear are lying there and respawn is half a world away. Under the panel
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

        tunnel = world.underground
        span = c.Minimap.TUNNEL_RANGE if tunnel is not None else c.Minimap.RANGE
        scale = inner.width / span

        def to_map(wx, wy) -> tuple:
            return (inner.centerx + (wx - player.x) * scale, inner.centery + (wy - player.y) * scale)

        self._draw_explored(world, player, span, scale, to_map)
        # Underground there is nothing else on the map: no village, no building, no landmark
        # and no rumour is within a million paces of a tunnel. The one mark worth drawing is
        # the way back out, and only once the player has walked past it.
        if tunnel is not None:
            self._draw_exit(world, tunnel, to_map)
        else:
            self._draw_villages(world, player, scale, to_map)
            self._draw_buildings(world, player, scale, to_map)
            self._draw_pois(world, to_map)
            self._draw_rumors(world, inner, to_map)
        # Drawn in both branches, unlike everything else here: a death underground leaves
        # its drop in the tunnel, and the way back to it is the one pin that map wants.
        self._draw_death_drop(world, inner, to_map)
        self._draw_player(player, inner)

        self.screen.set_clip(previous_clip)
        self._draw_compass(inner)
        self._draw_strips(world, player, self.rect.bottom)

    def _draw_explored(self, world: World, player: Player, span: float, scale: float, to_map):
        """The remembered ground, one flat square per explored cell. Cells are big enough
        that the edge of what the player knows reads as a ragged frontier.

        Underground the same squares are smaller and stone-coloured (`World.fog_cell`), so a
        cave draws itself room by room as it is lit rather than arriving whole."""
        cell = world.fog_cell
        color = c.Minimap.TUNNEL_GROUND_COLOR if world.underground is not None else c.Minimap.GROUND_COLOR
        half = span / 2
        size = math.ceil(cell * scale) + 1
        for gx in range(int((player.x - half) // cell), int((player.x + half) // cell) + 1):
            for gy in range(int((player.y - half) // cell), int((player.y + half) // cell) + 1):
                if (gx, gy) not in world.explored:
                    continue
                left, top = to_map(gx * cell, gy * cell)
                pygame.draw.rect(self.screen, color, pygame.Rect(round(left), round(top), size, size))

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
            left, top = to_map(building.bounds.left, building.bounds.top)
            rect = pygame.Rect(
                round(left),
                round(top),
                max(2, round(building.bounds.width * scale)),
                max(2, round(building.bounds.height * scale)),
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

    def _draw_exit(self, world: World, tunnel, to_map):
        """The shaft or the cave mouth, the one thing underground the player has to be able
        to find again. Drawn like a landmark, and like a landmark only once it has been
        walked to: it is where they came in, so it always has been."""
        if not world.is_explored(*tunnel.entrance):
            return
        x, y = to_map(*tunnel.entrance)
        pygame.draw.circle(self.screen, c.Minimap.EXIT_COLOR, (round(x), round(y)), 4)
        pygame.draw.circle(self.screen, (40, 36, 30), (round(x), round(y)), 4, 1)

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

    def _draw_rumors(self, world: World, inner: pygame.Rect, to_map):
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

    def _draw_death_drop(self, world: World, inner: pygame.Rect, to_map):
        """Where the player died and what they left there. Drawn as a cross rather than a
        dot so it never reads as another rumour, clamped to the panel edge the same way, and
        rubbed out by World once they are standing over it again."""
        if world.death_drop is None:
            return
        x, y = to_map(world.death_drop["x"], world.death_drop["y"])
        x = round(min(max(x, inner.left + 6), inner.right - 6))
        y = round(min(max(y, inner.top + 6), inner.bottom - 6))
        arm = 5
        for dx, dy in ((arm, arm), (arm, -arm)):
            pygame.draw.line(self.screen, c.Minimap.DEATH_COLOR, (x - dx, y - dy), (x + dx, y + dy), 3)

    def _draw_strips(self, world: World, player: Player, top: int):
        """The panels stacked under the map: the village standing on it, how that village
        feels about the player, every warning it has not let go of yet, how far out the
        player has walked, then the clock.

        Each one is laid under the last and `content_bottom` records where the stack actually
        ended, since whatever hangs below this corner (the quest tracker) has no other way of
        knowing how many strips were drawn this frame."""
        y = top + 4
        village = world.village_at(player.x, player.y)
        if village is not None and village.name and village.discovered:
            y = self._draw_text_strip(self._fit(village.name), c.Colors.WHITE, y)
            mood = self._village_mood(world, village)
            if mood is not None:
                y = self._draw_text_strip(mood, c.Colors.RED, y)
            # What the place is still counting against the player, and for how much longer.
            # A warning the player cannot see the end of is a trap: they have no way of
            # knowing whether the next swing is the one that turns the town, or whether the
            # theft it is still holding has been let go of yet.
            for label, seconds in world.warnings_at(player.x, player.y):
                # Short enough to fit the panel with the countdown still on it: the number
                # is the half of this that the player is actually reading.
                y = self._draw_text_strip(self._fit(f"{label} {int(seconds) + 1}s"), c.Colors.ORANGE, y)
            # What it would take to be let back in, while there is anything to pay for. Its
            # own strip and not a prompt, because the key that pays it (K) is answered from
            # anywhere on the village's ground: a settlement chasing the player across its
            # own plaza is exactly when they need to be able to read the price.
            y = self._draw_amends_strip(world, player, y)
        # What the country round here has heard, wherever the player is standing. Not inside
        # the village branch above: word of mouth is the one thing about the player that is
        # true out on the road as well (`WorldPlaces.notoriety_at`).
        heard = world.notoriety_label(player.x, player.y)
        if heard:
            y = self._draw_text_strip(heard, c.Colors.ORANGE, y)
        # How far out the player has walked. Difficulty in this world is distance from the
        # centre and nothing else, so this strip is the one number that says how dangerous
        # the ground under the player's feet is, and it belongs with the map that says where
        # that ground is.
        y = self._draw_text_strip(self._distance_label(world, player), c.Colors.MUTED, y)
        self._draw_clock(world, y)
        self.content_bottom = y + c.Minimap.CLOCK_HEIGHT

    def _draw_amends_strip(self, world: World, player: Player, y: int) -> int:
        """The blood price this settlement wants, and whether the player can pay it right
        now: gold when the coins are in the purse, muted when they are not, so the strip
        says both what it costs and whether pressing the key would do anything."""
        found = world.amends_at(player.x, player.y)
        if found is None:
            return y
        _village, price = found
        color = c.Colors.ACCENT if player.coins >= price else c.Colors.MUTED
        return self._draw_text_strip(self._fit(f"Blood price {price}  (K)"), color, y)

    @staticmethod
    def _distance_label(world: World, player: Player) -> str:
        """How far out the player has walked, and from what.

        On the surface that is the world centre, since difficulty here is distance from it.
        Underground it cannot be: a tunnel is carved a million paces from anywhere, so the
        same sum would report a number that says nothing about the ground being stood on.
        Down there the reading is from the way in instead, which is the only distance that
        means anything in a cave: how far back the daylight is.

        The wording is the longest of the phrasings that fits the panel. At four digits the
        full sentence runs off the end of its strip, and a distance is worth reading exactly
        where a preposition is not."""
        if world.underground is not None:
            ex, ey = world.underground.entrance
            paces = round(math.hypot(player.x - ex, player.y - ey) / c.Minimap.PACE)
            return Minimap._widest(f"{paces:,} paces from the way in", f"{paces:,} paces in")
        center = c.World.WORLD_SIZE // 2
        paces = round(math.hypot(player.x - center, player.y - center) / c.Minimap.PACE)
        return Minimap._widest(f"{paces:,} paces from home", f"{paces:,} paces out")

    @staticmethod
    def _widest(*options: str) -> str:
        """The first phrasing that fits a strip, thousands spaced rather than commaed. The
        last one is taken whether it fits or not, so there is always an answer."""
        for option in options:
            text = option.replace(",", " ")
            if c.Fonts.small.size(text)[0] <= c.Minimap.SIZE - c.Minimap.PADDING * 2:
                return text
        return options[-1].replace(",", " ")

    def _draw_text_strip(self, text: str, color: tuple, top: int) -> int:
        """One line of its own under the map, returning where the next strip starts."""
        label = c.Fonts.small.render(text, True, color)
        strip = pygame.Rect(self.rect.left, top, self.rect.width, label.get_height() + 8)
        widgets.draw_panel(self.screen, strip)
        self.screen.blit(label, label.get_rect(center=strip.center))
        return strip.bottom + 4

    @staticmethod
    def _village_mood(world: World, village) -> str | None:
        """How much longer this settlement wants the player dead, or None while it does not.

        Its own strip rather than a suffix on the name: the panel is 180 pixels wide, and a
        countdown appended to a name ate the name it was appended to. A grudge (somebody was
        killed here) has no countdown to show, and never will."""
        angry = [npc for npc in world.npcs if npc.hostile and village.contains_point(npc.x, npc.y)]
        if not angry:
            return None
        if any(npc.grudge for npc in angry):
            return "Never forgiven"
        remaining = max(npc.anger_remaining for npc in angry)
        return f"Furious for {int(remaining) // 60}:{int(remaining) % 60:02d}"

    @staticmethod
    def _fit(text: str) -> str:
        """Cut to the width of a strip, so a long name ends in an ellipsis inside the panel
        instead of running out of it and across the map."""
        width = c.Minimap.SIZE - c.Minimap.PADDING * 2
        if c.Fonts.small.size(text)[0] <= width:
            return text
        while text and c.Fonts.small.size(text + "...")[0] > width:
            text = text[:-1]
        return text + "..."

    @staticmethod
    def _sky_position(daynight) -> tuple[float, bool]:
        """How far across its own sky the body in it has got, and whether that body is the
        moon. Two spans, not one: the sun is up from dawn to the end of dusk and the moon
        holds the stretch between, so each crosses the whole strip over its own length
        instead of the day being squeezed into half a bar it does not last."""
        d = c.DayNight
        p = daynight.progress
        if d.DUSK_END <= p < d.NIGHT_END:
            return (p - d.DUSK_END) / (d.NIGHT_END - d.DUSK_END), True
        # The sun's span runs over the wrap: dawn (from NIGHT_END) through to the end of dusk.
        return ((p - d.NIGHT_END) % 1.0) / (1.0 - d.NIGHT_END + d.DUSK_END), False

    def _draw_clock(self, world: World, top: int):
        """The time of day as the sky itself: a strip of it with the sun or the moon crossing
        left to right, rising and setting over a horizon, the sky behind them going from blue
        through the warm band of dusk to a starred night. The phase is named beside it, but
        the point is that a glance at the colour and at how low the body is already says how
        much daylight is left."""
        daynight = world.daynight
        strip = pygame.Rect(self.rect.left, top, self.rect.width, c.Minimap.CLOCK_HEIGHT)
        widgets.draw_panel(self.screen, strip)

        darkness = daynight.darkness
        # The phase, and what the sky is doing over it when that is anything: rain and fog
        # are read off the screen first, and this is where the player checks what they are
        # looking at (`core.weather.WeatherSystem.label`).
        weather = world.weather.label
        phase = f"{daynight.phase}, {weather}" if weather else daynight.phase
        label = c.Fonts.small.render(phase, True, c.Colors.WHITE)
        band = pygame.Rect(strip.left + 6, strip.top + 6, strip.width - label.get_width() - 20, strip.height - 12)
        horizon = band.bottom - 7

        # The sky in three bands rather than a gradient: dark at the top, lighter at the
        # horizon, and the whole thing pulled toward the sunset colour through dusk and dawn,
        # which is the half of the cycle the two ends of the strip are actually spent in.
        warmth = 4 * darkness * (1 - darkness)
        sky = _mix(c.Minimap.CLOCK_SKY_DAY, c.Minimap.CLOCK_SKY_NIGHT, darkness)
        for i in range(3):
            low = _mix(sky, c.Minimap.CLOCK_SKY_LOW, warmth * (i + 1) / 3 * 0.8)
            row = pygame.Rect(band.left, band.top + (horizon - band.top) * i // 3, band.width, 0)
            row.height = band.top + (horizon - band.top) * (i + 1) // 3 - row.top
            pygame.draw.rect(self.screen, _mix(sky, low, 0.5 + i * 0.25), row)

        # Fixed stars, faded in with the darkness by being mixed into the sky they stand in:
        # a colour rather than an alpha, so nothing is allocated per frame for six dots.
        star = _mix(sky, (236, 238, 255), darkness)
        for fx, fy in ((0.12, 0.3), (0.28, 0.62), (0.46, 0.2), (0.63, 0.52), (0.78, 0.28), (0.9, 0.66)):
            x = band.left + band.width * fx
            y = band.top + (horizon - band.top) * fy
            pygame.draw.circle(self.screen, star, (x, y), 1)

        pygame.draw.rect(self.screen, c.Minimap.CLOCK_GROUND, (band.left, horizon, band.width, band.bottom - horizon))
        pygame.draw.line(self.screen, (16, 14, 12), (band.left, horizon), (band.right - 1, horizon), 1)

        travelled, is_moon = self._sky_position(daynight)
        color = c.Minimap.CLOCK_NIGHT_COLOR if is_moon else c.Minimap.CLOCK_DAY_COLOR
        left, span = band.left + 8, band.width - 16
        arc = horizon - band.top - 5
        x = left + span * travelled
        y = horizon - math.sin(math.pi * travelled) * arc

        # The track already crossed, so the strip says how much of this sky is behind the
        # player as well as where in it the body currently is.
        steps = max(2, int(span * travelled / 6))
        for i in range(steps):
            t = travelled * i / steps
            pygame.draw.circle(
                self.screen,
                _mix(sky, color, 0.35),
                (left + span * t, horizon - math.sin(math.pi * t) * arc),
                1,
            )

        radius = 6 if not is_moon else 5
        if is_moon:
            # The bite taken out of it is the sky drawn back over the disc, so the crescent
            # always sits on whatever colour the sky happens to be.
            pygame.draw.circle(self.screen, color, (x, y), radius)
            pygame.draw.circle(self.screen, sky, (x + radius * 0.55, y - radius * 0.35), radius * 0.92)
        else:
            for i in range(8):
                angle = i * math.pi / 4 + travelled * math.pi
                pygame.draw.line(
                    self.screen,
                    color,
                    (x + math.cos(angle) * (radius + 2), y + math.sin(angle) * (radius + 2)),
                    (x + math.cos(angle) * (radius + 5), y + math.sin(angle) * (radius + 5)),
                    1,
                )
            pygame.draw.circle(self.screen, color, (x, y), radius)
            pygame.draw.circle(self.screen, (255, 244, 200), (x - radius * 0.3, y - radius * 0.3), radius * 0.4)

        self.screen.blit(label, label.get_rect(midleft=(band.right + 8, strip.centery)))
