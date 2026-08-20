"""Global screen-space juice: a brief freeze-frame on a heavy hit, a red flash when the
player takes damage, the white wash of a blast, and the jaws of a bear trap shutting over
the whole screen. All of them are read once per frame in Game.run(), the same pattern as
ScreenShake in core/camera.py."""

import math

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


class ScreenFlash:
    """A full-screen wash of colour, blown out at once and fading fast.

    What a blast needs that a vignette cannot give: the vignette is an edge effect and reads
    as *being hurt*, where a keg going off two rooms away is something that happened to the
    world. Colour comes from whatever triggered it, so a new effect that deserves a wash
    picks its own rather than adding a flag here."""

    def __init__(self):
        self.amp = 0.0
        self.color = (255, 255, 255)

    def trigger(self, amount: float, color=(255, 255, 255)):
        if amount >= self.amp:
            self.color = color
        self.amp = min(max(self.amp, amount), 1.0)

    def update(self, dt):
        if self.amp <= 0.01:
            self.amp = 0.0
            return
        self.amp *= c.Combat.FLASH_DECAY ** (dt * c.TARGET_FPS / 1000.0)

    def draw(self, surface):
        if self.amp <= 0.0:
            return
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
        overlay.fill((*self.color, int(200 * self.amp)))
        surface.blit(overlay, (0, 0))


class TrapSnap:
    """The bear trap shutting, drawn over the whole screen rather than at the trap.

    A trap costs a bite of health and a few seconds of standing still, which on its own is a
    number and a stuck body: the player reads it as the game having frozen on them. So the
    jaws are drawn where they can't be missed, two rows of teeth swinging in from the top and
    bottom edges, biting shut and then easing open as the hold runs out. It is triggered only
    for the player (`WorldCombat._spring_trap`): a wolf standing in one somewhere off screen
    is not what this is for."""

    def __init__(self):
        self.age = None

    def trigger(self):
        self.age = 0.0

    def update(self, dt):
        if self.age is None:
            return
        self.age += dt
        if self.age >= c.Traps.SNAP_FX_MS:
            self.age = None

    def _closure(self) -> float:
        """How shut the jaws are, 0 open to 1 bitten together. Slams in over the first part
        of the animation and lets go slowly, which is the shape of the thing it draws."""
        progress = self.age / c.Traps.SNAP_FX_MS
        bite = c.Traps.SNAP_FX_BITE_FRAC
        if progress <= bite:
            return math.sin((progress / bite) * math.pi / 2)
        return 1.0 - (progress - bite) / (1.0 - bite)

    def draw(self, surface):
        if self.age is None:
            return
        closure = max(0.0, self._closure())
        w, h = c.Screen.WIDTH, c.Screen.HEIGHT
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        # The bite darkens the screen edges as it comes in, so the jaws read as closing over
        # the player rather than as two shapes sliding past them.
        overlay.fill((20, 10, 10, int(110 * closure)))

        reach = h * c.Traps.SNAP_FX_REACH * closure
        teeth = c.Traps.SNAP_FX_TEETH
        tooth_w = w / teeth
        jaw = c.Traps.JAW_COLOR
        shadow = tuple(max(0, channel - 55) for channel in jaw)
        shine = tuple(min(255, channel + 60) for channel in jaw)
        for top in (True, False):
            base = 0 if top else h
            tip = reach if top else h - reach
            # The band the teeth stand in, kept shallow so most of the bite is teeth.
            gum = base + (tip - base) * 0.4
            pygame.draw.polygon(overlay, (*jaw, 240), [(0, base), (w, base), (w, gum), (0, gum)])
            pygame.draw.line(overlay, (*shine, 200), (0, gum), (w, gum), 3)
            for i in range(teeth):
                left = i * tooth_w
                # Every other tooth a little shorter, so the row reads as iron rather than
                # as a sawtooth pattern.
                point = gum + (tip - gum) * (1.0 if i % 2 == 0 else 0.78)
                spike = [(left, gum), (left + tooth_w, gum), (left + tooth_w / 2, point)]
                pygame.draw.polygon(overlay, (*jaw, 240), spike)
                pygame.draw.polygon(overlay, (*shadow, 240), spike, 3)
        surface.blit(overlay, (0, 0))


_hitstop = None
_vignette = None
_flash = None
_trap_fx = None


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


def get_flash() -> ScreenFlash:
    global _flash
    if _flash is None:
        _flash = ScreenFlash()
    return _flash


def get_trap_fx() -> TrapSnap:
    global _trap_fx
    if _trap_fx is None:
        _trap_fx = TrapSnap()
    return _trap_fx
