"""Global screen-space juice: a brief freeze-frame on a heavy hit, a red flash when the
player takes damage, the white wash of a blast, the jaws of a bear trap shutting over the
whole screen, and the banner an event announces itself with. All of them are read once per
frame in Game.run(), the same pattern as ScreenShake in core/camera.py.

Every one of them paints a whole screen from a single number, so every one of them goes
through `_Overlay`, which keeps what it painted until that number moves a step. Painted
fresh each frame instead, the blood night's veil alone cost 10 ms a frame for the length of
the night, which is most of a frame's budget spent redrawing the same six rectangles."""

import math

import pygame

import core.constants as c
from core.text_fx import draw_outlined_text

# How tall the strip behind an event's title is.
_BAND_H = 190


class Overlay:
    """A full-screen effect painted once and kept until what shapes it moves a step.

    All of these are one number between 0 and 1 (how hurt, how bright, how shut, how deep
    into the night, how dark the sky) deciding a screenful of pixels. Taken in steps, a value
    that holds still is painted once and one that drifts is painted a few dozen times rather
    than sixty times a second. How many steps is how fine the effect actually is: enough that
    one step to the next is nothing anybody can see, and no more.

    Shared with the sky in `core/daynight.py`, which is the same thing drawn over the same
    screen a line earlier in the draw order.
    """

    def __init__(self, steps: int):
        self.steps = steps
        self._surface = None
        self._key = None

    def surface(self, amount: float, paint, key=None) -> pygame.Surface | None:
        """The overlay for this amount, repainted only if its step (or `key`) has moved.
        None when there is nothing to draw, which is what an effect at rest is."""
        step = round(min(1.0, max(0.0, amount)) * self.steps)
        if step <= 0:
            return None
        if (step, key) != self._key:
            if self._surface is None:
                self._surface = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SRCALPHA)
            self._surface.fill((0, 0, 0, 0))
            paint(self._surface, step / self.steps)
            self._key = (step, key)
        return self._surface


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
        # Its border widens with the flash, so, like the trap's jaws, it is kept exact and
        # only the surface is reused: the whole thing is over in half a second.
        self._overlay = Overlay(255)

    def trigger(self, amount: float):
        self.amp = min(max(self.amp, amount), 1.0)

    def update(self, dt):
        if self.amp <= 0.01:
            self.amp = 0.0
            return
        self.amp *= c.Combat.VIGNETTE_DECAY ** (dt * c.TARGET_FPS / 1000.0)

    def _paint(self, overlay, amp):
        w, h = c.Screen.WIDTH, c.Screen.HEIGHT
        overlay.fill((160, 20, 20, int(35 * amp)))
        border = max(30, int(90 * amp))
        pygame.draw.rect(overlay, (160, 20, 20, int(150 * amp)), (0, 0, w, h), border)

    def draw(self, surface):
        overlay = self._overlay.surface(self.amp, self._paint)
        if overlay is not None:
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
        # A flat wash, so a step is a step of alpha and nothing else.
        self._overlay = Overlay(64)

    def trigger(self, amount: float, color=(255, 255, 255)):
        if amount >= self.amp:
            self.color = color
        self.amp = min(max(self.amp, amount), 1.0)

    def update(self, dt):
        if self.amp <= 0.01:
            self.amp = 0.0
            return
        self.amp *= c.Combat.FLASH_DECAY ** (dt * c.TARGET_FPS / 1000.0)

    def _paint(self, overlay, amp):
        overlay.fill((*self.color, int(200 * amp)))

    def draw(self, surface):
        # Keyed on the colour as well as the level: two blasts of different colours a moment
        # apart are two washes, not one repainted at the wrong step.
        overlay = self._overlay.surface(self.amp, self._paint, key=self.color)
        if overlay is not None:
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
        # The jaws sweep half the screen in half a second, which is the one thing here whose
        # shape moves fast enough to show a step: it is kept exact, and only the surface it
        # is painted on is reused.
        self._overlay = Overlay(255)

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

    def _paint(self, overlay, closure):
        w, h = c.Screen.WIDTH, c.Screen.HEIGHT
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

    def draw(self, surface):
        if self.age is None:
            return
        overlay = self._overlay.surface(self._closure(), self._paint)
        if overlay is not None:
            surface.blit(overlay, (0, 0))


class EventBanner:
    """The title a world event announces itself with: it fades up over the middle of the
    screen, holds, and fades out again.

    A toast in the corner is how the world tells the player something; a banner is how it
    tells them the rules just changed. Only events that change them get one.
    """

    def __init__(self):
        self.title = ""
        self.subtitle = ""
        self.color = c.Colors.WHITE
        self.remaining_ms = 0.0
        self._band = None
        self._words = None
        self._words_key = None

    def trigger(self, title: str, subtitle: str = "", color=c.Colors.WHITE):
        self.title = title
        self.subtitle = subtitle
        self.color = color
        self.remaining_ms = c.Events.BANNER_DURATION_MS

    def update(self, dt):
        self.remaining_ms = max(0.0, self.remaining_ms - dt)

    def band(self) -> pygame.Surface:
        """The strip the words sit on. A band behind them rather than a full wash: the world
        stays visible, since a blood night is something to look at, not something to read
        through. The same strip every time, so it is painted once and faded with `set_alpha`
        rather than being built a row at a time on every frame it is up."""
        if self._band is None:
            self._band = pygame.Surface((c.Screen.WIDTH, _BAND_H), pygame.SRCALPHA)
            for i in range(_BAND_H):
                edge = 1.0 - abs(i - _BAND_H / 2) / (_BAND_H / 2)
                self._band.fill((0, 0, 0, int(150 * edge)), (0, i, c.Screen.WIDTH, 1))
        return self._band

    def words(self, rise: int) -> pygame.Surface:
        """The title and its subtitle, kept until one of them or the drift changes. The rise
        settles within the first second, so this is a handful of paintings for a banner that
        is up for four."""
        key = (self.title, self.subtitle, self.color, rise)
        if key != self._words_key:
            words = pygame.Surface((c.Screen.WIDTH, _BAND_H), pygame.SRCALPHA)
            middle = _BAND_H // 2 + rise
            mid_x = c.Screen.WIDTH // 2
            draw_outlined_text(words, self.title, c.Fonts.big_title, self.color, center=(mid_x, middle), width=2)
            if self.subtitle:
                draw_outlined_text(words, self.subtitle, c.Fonts.text, c.Colors.WHITE, center=(mid_x, middle + 52))
            self._words, self._words_key = words, key
        return self._words

    def draw(self, surface):
        if self.remaining_ms <= 0 or not self.title:
            return
        total = c.Events.BANNER_DURATION_MS
        fade = c.Events.BANNER_FADE_MS
        elapsed = total - self.remaining_ms
        alpha = int(255 * max(0.0, min(1.0, elapsed / fade, self.remaining_ms / fade)))

        # The title drifts up a little as it lands, which is what keeps it from reading as
        # a static label someone pasted over the game.
        rise = round((1.0 - min(1.0, elapsed / (fade * 2))) * 14)
        top = c.Screen.HEIGHT // 3 - _BAND_H // 2
        for layer in (self.band(), self.words(rise)):
            layer.set_alpha(alpha)
            surface.blit(layer, (0, top))


def _paint_blood_veil(overlay, amount: float):
    w, h = c.Screen.WIDTH, c.Screen.HEIGHT
    border = round(70 + 90 * amount)
    # Drawn as nested rectangles so the red thickens toward the edge instead of stopping
    # at a hard line the way one filled border would.
    for step in range(6):
        t = (step + 1) / 6
        pygame.draw.rect(
            overlay,
            (150, 12, 12, int(38 * amount * t)),
            (0, 0, w, h),
            round(border * (1 - step / 8)),
            border_radius=round(40 * t),
        )


def draw_blood_veil(surface, intensity: float):
    """The red the whole blood night is seen through: a heavy edge vignette breathing in
    and out, over the sky tint the same intensity already drives.

    The tint alone changed the colour of the world without ever saying why; this is the
    part the player reads as "it is still going on". The breath is slow and the veil is up
    for the whole night, so it is the one effect here that most wants keeping: repainted
    every frame it was 10 ms of every 16."""
    if intensity <= 0.0:
        return
    pulse = 0.75 + 0.25 * math.sin(pygame.time.get_ticks() / 900)
    overlay = _veil.surface(intensity * pulse, _paint_blood_veil)
    if overlay is not None:
        surface.blit(overlay, (0, 0))


_veil = Overlay(24)

_hitstop = None
_vignette = None
_flash = None
_trap_fx = None
_banner = None


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


def get_banner() -> EventBanner:
    global _banner
    if _banner is None:
        _banner = EventBanner()
    return _banner
