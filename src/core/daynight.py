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
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill((*color, alpha))
        surface.blit(overlay, (0, 0))
