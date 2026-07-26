"""Global screen-space juice: a brief freeze-frame on a heavy hit, and a red flash
when the player takes damage. Both are read once per frame in Game.run(), the same
pattern as ScreenShake in core/camera.py."""

import pygame

import core.constants as c


class Hitstop:
    """A short freeze sells a heavy hit without any new animation work: gameplay
    updates slow almost to a stop for a few frames while rendering keeps going."""

    def __init__(self):
        self.remaining_ms = 0.0

    def trigger(self, duration_ms: float):
        self.remaining_ms = max(self.remaining_ms, duration_ms)

    def apply(self, dt):
        """Consume real dt, returning a slowed dt for gameplay updates while a freeze is active."""
        if self.remaining_ms <= 0:
            return dt
        self.remaining_ms -= dt
        return dt * c.Combat.HITSTOP_SLOW_FACTOR


class HurtVignette:
    """A red flash at the screen edges, pulsing in and decaying, when the player is hit."""

    def __init__(self):
        self.amp = 0.0

    def trigger(self, amount: float):
        self.amp = min(max(self.amp, amount), 1.0)

    def update(self, dt):
        if self.amp <= 0.01:
            self.amp = 0.0
            return
        self.amp *= c.Combat.VIGNETTE_DECAY ** (dt * c.TARGET_FPS / 1000.0)

    def draw(self, surface):
        if self.amp <= 0.0:
            return
        w, h = c.Screen.WIDTH, c.Screen.HEIGHT
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((160, 20, 20, int(35 * self.amp)))
        border = max(30, int(90 * self.amp))
        pygame.draw.rect(overlay, (160, 20, 20, int(150 * self.amp)), (0, 0, w, h), border)
        surface.blit(overlay, (0, 0))


_hitstop = None
_vignette = None


def get_hitstop() -> Hitstop:
    global _hitstop
    if _hitstop is None:
        _hitstop = Hitstop()
    return _hitstop


def get_vignette() -> HurtVignette:
    global _vignette
    if _vignette is None:
        _vignette = HurtVignette()
    return _vignette
