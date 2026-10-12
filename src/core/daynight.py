from __future__ import annotations

import pygame

import core.constants as c
from core.screen_fx import Overlay


class DayNightCycle:
    """Tracks time of day for one World and exposes the ambient tint the renderer
    overlays on the outdoor world. Owned by World so its elapsed time can be
    persisted and restored per save, the same way World.events owns blood night."""

    def __init__(self, elapsed_ms: float = 0.0):
        self.elapsed_ms = elapsed_ms % c.DayNight.CYCLE_LENGTH_MS
        self._tint = Overlay(255)

    def update(self, dt):
        self.elapsed_ms = (self.elapsed_ms + dt) % c.DayNight.CYCLE_LENGTH_MS

    @property
    def progress(self) -> float:
        """0.0 at the start of day, ramping back to 0.0 at the end of the following dawn."""
        return self.elapsed_ms / c.DayNight.CYCLE_LENGTH_MS

    @property
    def darkness(self) -> float:
        """0.0 in full daylight, 1.0 at the depth of night, ramped smoothly through dusk/dawn."""
        d = c.DayNight
        p = self.progress
        if p < d.DAY_END:
            return 0.0
        if p < d.DUSK_END:
            return (p - d.DAY_END) / (d.DUSK_END - d.DAY_END)
        if p < d.NIGHT_END:
            return 1.0
        return 1.0 - (p - d.NIGHT_END) / (1.0 - d.NIGHT_END)

    def time_until(self, target_progress: float) -> float:
        """Milliseconds from now until the cycle next reaches that point, going forward.
        What sleeping through to dawn has to skip."""
        return ((target_progress - self.progress) % 1.0) * c.DayNight.CYCLE_LENGTH_MS

    @property
    def is_night(self) -> bool:
        return self.darkness > 0.5

    @property
    def curfew(self) -> bool:
        """Whether a village has called it a night: its people head home and its gates lean
        shut (`World._work_gates`). True from partway through dusk to partway through dawn,
        earlier than `is_night` so the street empties over the sunset rather than at a
        stroke."""
        return self.darkness >= c.DayNight.CURFEW_DARKNESS

    @property
    def phase(self) -> str:
        """What the clock in the HUD calls the current stretch of the cycle."""
        d = c.DayNight
        p = self.progress
        if p < d.DAY_END:
            return "Day"
        if p < d.DUSK_END:
            return "Dusk"
        if p < d.NIGHT_END:
            return "Night"
        return "Dawn"

    def draw(self, surface: pygame.Surface, blood_intensity: float = 0.0):
        """Overlay the ambient tint. `blood_intensity` (0..1) blends the ordinary sky toward
        the blood night's red, so the event comes on and bleeds out rather than snapping."""
        darkness = self.darkness
        color = c.DayNight.NIGHT_COLOR
        alpha = c.DayNight.NIGHT_MAX_ALPHA * darkness
        if blood_intensity > 0:
            blood = c.DayNight.BLOOD_NIGHT_COLOR
            color = tuple(round(v + (b - v) * blood_intensity) for v, b in zip(color, blood, strict=True))
            alpha += (c.DayNight.BLOOD_NIGHT_ALPHA - alpha) * blood_intensity
        alpha = int(alpha)
        if alpha <= 0:
            return
        # Kept rather than filled afresh every frame: the sky is one flat colour that holds
        # still for minutes at a time, and a whole screen of it was 2 ms of every night frame.
        # A step per level of alpha, so nothing about the dusk is any coarser than it was.
        overlay = self._tint.surface(alpha / 255, lambda tint, amount: self._paint(tint, amount, color), color)
        if overlay is not None:
            surface.blit(overlay, (0, 0))

    @staticmethod
    def _paint(tint: pygame.Surface, amount: float, color: tuple):
        """The sky, and the dark it gathers at the edges of the view: night closes in on
        the player rather than lying over the screen as one flat sheet."""
        tint.fill((*color, round(amount * 255)))
        depth = min(1.0, amount * 255 / c.DayNight.NIGHT_MAX_ALPHA)
        edges = _vignette(color).copy()
        edges.fill((255, 255, 255, round(depth * 255)), special_flags=pygame.BLEND_RGBA_MULT)
        tint.blit(edges, (0, 0))


_VIGNETTE: dict = {}


def _vignette(color: tuple) -> pygame.Surface:
    """Rings of `color`, clear in the middle of the screen and densest in its corners."""
    if color not in _VIGNETTE:
        w, h = c.Screen.WIDTH, c.Screen.HEIGHT
        art = pygame.Surface((w, h), pygame.SRCALPHA)
        art.fill((*color, c.DayNight.NIGHT_EDGE_ALPHA))
        rings = 24
        for i in range(rings):
            t = i / rings  # 0 at the corners, 1 at the clear middle
            scale = 1.5 - t * (1.5 - c.DayNight.NIGHT_EDGE_CLEAR)
            rect = pygame.Rect(0, 0, round(w * scale), round(h * scale))
            rect.center = (w // 2, h // 2)
            pygame.draw.ellipse(art, (*color, round(c.DayNight.NIGHT_EDGE_ALPHA * (1 - t) ** 2)), rect)
        _VIGNETTE[color] = art
    return _VIGNETTE[color]
