from __future__ import annotations

import pygame

import core.constants as c


class DayNightCycle:
    """Tracks time of day for one World and exposes the ambient tint the renderer
    overlays on the outdoor world. Owned by World so its elapsed time can be
    persisted and restored per save, the same way World.events owns blood night."""

    def __init__(self, elapsed_ms: float = 0.0):
        self.elapsed_ms = elapsed_ms % c.DayNight.CYCLE_LENGTH_MS

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

    @property
    def is_night(self) -> bool:
        return self.darkness > 0.5

    def draw(self, surface: pygame.Surface, blood_night_active: bool):
        if blood_night_active:
            color = c.DayNight.BLOOD_NIGHT_COLOR
            alpha = c.DayNight.BLOOD_NIGHT_ALPHA
        else:
            darkness = self.darkness
            if darkness <= 0.0:
                return
            color = c.DayNight.NIGHT_COLOR
            alpha = int(c.DayNight.NIGHT_MAX_ALPHA * darkness)
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill((*color, alpha))
        surface.blit(overlay, (0, 0))
