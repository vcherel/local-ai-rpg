"""Rain and fog: the second thing that happens to the whole world at once.

Night is already a state of the world rather than a filter over it, and it is read the same
way everywhere (`World.night_damage_mult`, the detection multiplier, `witness_radius`).
Weather is that idea on a shorter clock and with no schedule at all: a spell comes on, holds
and bleeds out again, and what it costs while it does is sight, for the player's pursuers
and for the people who would otherwise catch them at a chest.

Two rules it is written to. It never touches damage or spawning, because a sky that decides
how hard a wolf hits is a difficulty setting the player cannot read; and it is session-only,
like the wildlife and the decals, because what the sky was doing is not a fact a save has
any business restoring.
"""

from __future__ import annotations

import math
import random

import pygame

import core.constants as c
from core.screen_fx import Overlay

# Every state the sky can be in, and how long a spell of each lasts. "clear" is the one with
# no duration: it holds until the next roll changes it.
_SPELLS = {
    "rain": c.Weather.RAIN_DURATION_MS,
    "fog": c.Weather.FOG_DURATION_MS,
}


class WeatherSystem:
    """What the sky is doing, as one kind and one number.

    `intensity` is the whole of it, ramped at both ends exactly as a blood night is: every
    effect reads that number rather than the kind's own constants, so weather thickens and
    thins instead of switching on.
    """

    def __init__(self):
        self.kind = "clear"
        self.timer = 0.0
        self.duration = 0.0
        self.next_check = random.uniform(*c.Weather.CHECK_INTERVAL_MS)
        # The drops, as (x fraction, phase, length, speed): a fixed set falling on their own
        # loop rather than a particle system. Rain interacts with nothing, and a thousand
        # live particles a frame for something that cannot be walked into is a frame spent
        # on nothing. Rolled once, so a squall does not reshuffle itself every second.
        self._drops = tuple(
            (
                random.random(),
                random.random(),
                random.uniform(*c.Weather.RAIN_LENGTH),
                random.uniform(*c.Weather.RAIN_SPEED),
            )
            for _ in range(c.Weather.RAIN_DROPS)
        )
        self._fog = Overlay(24)
        # The banks of fog that drift over the wash, as (y fraction, width fraction, how
        # long it takes to cross, phase, bob phase). Rolled once for the same reason the
        # drops are: a bank that reshuffled itself every frame is static, and static is what
        # made the old fog read as a frame round the screen rather than as air.
        self._banks = tuple(
            (
                random.uniform(-0.05, 1.05),
                random.uniform(*c.Weather.FOG_BANK_WIDTH),
                random.uniform(*c.Weather.FOG_BANK_CROSS_S),
                random.random(),
                random.uniform(0, 2 * math.pi),
            )
            for _ in range(c.Weather.FOG_BANKS)
        )
        # One soft blob per bank, painted the first time fog is drawn and kept: a bank is
        # the same shape wherever it has drifted to, so painting or scaling one per frame is
        # a gradient a frame for nothing.
        self._bank_art: tuple | None = None

    @property
    def intensity(self) -> float:
        """How much of the current spell is in force, 0 to 1, ramped at both ends and held
        at 1 through the middle. The one number everything about the weather reads."""
        if self.kind == "clear" or self.duration <= 0:
            return 0.0
        fade = c.Weather.FADE_MS
        elapsed = self.duration - self.timer
        return max(0.0, min(1.0, elapsed / fade, self.timer / fade))

    @property
    def label(self) -> str:
        """What to call it in a word, or "" while the sky is clear. What the minimap's clock
        strip says beside the phase, so the player can read the sky without looking up."""
        if self.intensity <= 0:
            return ""
        return "rain" if self.kind == "rain" else "fog"

    def update(self, dt):
        """Run the current spell down and roll the next one when its check comes round."""
        if self.timer > 0:
            self.timer = max(0.0, self.timer - dt)
            if self.timer == 0:
                self.kind = "clear"
                self.duration = 0.0

        self.next_check -= dt
        if self.next_check > 0:
            return
        self.next_check = random.uniform(*c.Weather.CHECK_INTERVAL_MS)
        # A check that lands mid spell is left alone: weather that could be cut off halfway
        # by its own clock would never be worth waiting out.
        if self.kind != "clear":
            return
        roll = random.random()
        if roll < c.Weather.RAIN_CHANCE:
            self._begin("rain")
        elif roll < c.Weather.RAIN_CHANCE + c.Weather.FOG_CHANCE:
            self._begin("fog")

    def _begin(self, kind: str):
        self.duration = random.uniform(*_SPELLS[kind])
        self.timer = self.duration
        self.kind = kind

    def sight_mult(self) -> float:
        """What can be seen through this, as a multiplier on a distance that already exists:
        how far a monster notices from and how far a villager catches a thief at.

        One function for both, so the wedge drawn on the ground and the ring a wolf reacts
        inside are always shortened by the same sky. Scaled by `intensity`, so the world
        closes in over the length of the spell rather than at the frame it starts."""
        if self.intensity <= 0:
            return 1.0
        full = c.Weather.RAIN_SIGHT_MULT if self.kind == "rain" else c.Weather.FOG_SIGHT_MULT
        return 1.0 - (1.0 - full) * self.intensity

    def draw(self, screen: pygame.Surface):
        """Paint the sky's own layer over the world, under the HUD.

        Rain is drawn straight, since every streak is a different line every frame and there
        is nothing to keep; fog is one flat wash and goes through `Overlay` like the night
        tint, painted once per step of the ramp rather than once a frame."""
        amount = self.intensity
        if amount <= 0:
            return
        if self.kind == "rain":
            self._draw_rain(screen, amount)
        else:
            self._draw_fog(screen, amount)

    def _draw_rain(self, screen: pygame.Surface, amount: float):
        """Streaks falling down the screen on their own loop, slanted, and only as many of
        them as the spell has come on: a shower thickens into a downpour rather than
        arriving whole. Screen space rather than world space on purpose, since rain in front
        of the camera is what rain looks like and nothing in the world is ever hit by it."""
        now = pygame.time.get_ticks() / 1000.0
        height = c.Screen.HEIGHT
        width = c.Screen.WIDTH
        color = (*c.Weather.RAIN_COLOR, int(c.Weather.RAIN_ALPHA * amount))
        layer = pygame.Surface((width, height), pygame.SRCALPHA)
        falling = round(len(self._drops) * amount)
        for x_frac, phase, length, speed in self._drops[:falling]:
            # The fall is the clock rather than a stored position: a drop is at whatever
            # height its own speed and offset put it at right now, so nothing has to be
            # stepped and a paused game has rain that carries on falling.
            y = ((phase + now * speed / height) % 1.0) * (height + length) - length
            x = x_frac * (width + length) - length * c.Weather.RAIN_SLANT
            pygame.draw.line(
                layer,
                color,
                (x, y),
                (x + length * c.Weather.RAIN_SLANT, y + length),
                1,
            )
        screen.blit(layer, (0, 0))

    def _draw_fog(self, screen: pygame.Surface, amount: float):
        """A pale wash that closes in from every side at once, with banks of it drifting
        across.

        What fog does to a view is take the distance away, and distance is a ring rather
        than a border: the wash is painted as rings from the rim inwards, so it thickens
        smoothly out of what the player is standing in. It used to be three nested
        rectangles, which reads as a frame laid over the screen and not as weather at all.

        The rings are kept (`Overlay`), since they only move when the ramp steps. The banks
        are drawn live, because the whole point of them is that they are moving: one soft
        blob painted once and blitted a few times at whatever it has drifted to.
        """
        alpha = c.Weather.FOG_MAX_ALPHA * amount
        overlay = self._fog.surface(alpha / 255, self._paint_fog, self.kind)
        if overlay is not None:
            screen.blit(overlay, (0, 0))
        self._draw_banks(screen, amount)

    @staticmethod
    def _paint_fog(surface: pygame.Surface, level: float):
        """The wash itself: rings from the rim in, thickest at the edge of the view and
        thinnest in the middle. Drawn largest first, since `pygame.draw` writes its pixels
        rather than blending them, so each ring lightens the middle of the one before it."""
        full = c.Weather.FOG_MAX_ALPHA * level
        centre = full * c.Weather.FOG_CENTRE_FRAC
        surface.fill((*c.Weather.FOG_COLOR, round(full)))
        # Wide enough to cover the corners, so the first ring is the whole screen and no
        # square edge of it is ever left standing.
        span = pygame.Rect(0, 0, round(c.Screen.WIDTH * 1.5), round(c.Screen.HEIGHT * 1.5))
        span.center = (c.Screen.WIDTH // 2, c.Screen.HEIGHT // 2)
        rings = c.Weather.FOG_RINGS
        for i in range(rings + 1):
            t = i / rings  # 0 at the rim, 1 in the middle
            shade = round(full + (centre - full) * (t**c.Weather.FOG_FALLOFF))
            ring = span.inflate(-round(span.width * t), -round(span.height * t))
            pygame.draw.ellipse(surface, (*c.Weather.FOG_COLOR, max(0, shade)), ring)

    def _bank_surfaces(self) -> tuple:
        """One soft blob per bank, at that bank's own width. Painted the first time fog is
        drawn and kept: a bank is the same shape wherever it has drifted to, so scaling one
        per frame would be a gradient a frame for nothing."""
        if self._bank_art is None:
            size = round(c.Screen.WIDTH * c.Weather.FOG_BANK_WIDTH[1])
            art = pygame.Surface((size, round(size * 0.55)), pygame.SRCALPHA)
            rect = art.get_rect()
            # Widest and faintest first, thickening inwards: the rim of a bank has to fade
            # to nothing or it is a drawn ellipse drifting across the screen.
            rings = 26
            for i in range(rings):
                t = i / rings
                shade = round(255 * t**1.7)
                pygame.draw.ellipse(art, (*c.Weather.FOG_COLOR, shade), rect.inflate(-rect.width * t, -rect.height * t))
            self._bank_art = tuple(
                pygame.transform.smoothscale(
                    art, (round(c.Screen.WIDTH * width_frac), round(c.Screen.WIDTH * width_frac * 0.55))
                )
                for _, width_frac, _, _, _ in self._banks
            )
        return self._bank_art

    def _draw_banks(self, screen: pygame.Surface, amount: float):
        """The banks drifting across the view, each on its own clock like a raindrop: where
        one is is worked out from the time rather than stepped, so nothing has to be updated
        and a paused game still has air that moves."""
        now = pygame.time.get_ticks() / 1000.0
        alpha = round(c.Weather.FOG_BANK_ALPHA * amount)
        if alpha <= 0:
            return
        for bank, (y_frac, _, cross_s, phase, bob) in zip(self._bank_surfaces(), self._banks, strict=True):
            width, height = bank.get_size()
            travel = (phase + now / cross_s) % 1.0
            x = travel * (c.Screen.WIDTH + width) - width
            y = y_frac * c.Screen.HEIGHT + math.sin(bob + now * 0.08) * c.Screen.HEIGHT * 0.05
            bank.set_alpha(alpha)
            screen.blit(bank, (round(x), round(y - height / 2)))
