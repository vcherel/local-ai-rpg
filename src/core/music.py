"""Background music, synthesised in memory like the sound effects.

No asset files and no new dependency: the score is a set of slow chord pads, and which one
is playing is the game's own business. A pad per context (day, night, a village street, a
fight, a boss, a blood night) and several progressions inside each of them, picked at
random, so the music answers what is happening rather than being one track playing over
the top of everything.

Rendering a pad in pure Python is slow enough to be felt, so it happens on a daemon thread
and each one simply starts once it is ready: asking for a context that has not been
rendered yet leaves whatever is playing where it is until it has been. Two reserved
channels are held so a change of context is a crossfade rather than a cut, and the same
context comes back to a different progression after a while, since a pad that never
changes stops being heard at all.

Whether it plays at all is a preference (`core.settings`), read once here and toggled from
the pause menu.
"""

from __future__ import annotations

import array
import math
import queue
import random
import threading

import pygame

from core.audio import SAMPLE_RATE
from core.settings import get_settings

# One cycle of a sine, looked up rather than recomputed: a pad is a few million samples
# and math.sin per partial per sample is what made the first version take half a minute.
_TABLE_SIZE = 2048
_SINE = [math.sin(2 * math.pi * i / _TABLE_SIZE) for i in range(_TABLE_SIZE)]

# One row per context, and several progressions in each: semitone offsets from the root,
# one tuple per chord. Every progression resolves back to where it started, since the loop
# point has to pass unnoticed. `root` sets how low it sits, `brightness` how much of the
# upper partials survives, `breath` how fast it swells, `chord_s` how long a chord is held:
# a fight is the same instrument as a field, hurried and darkened.
CONTEXTS = {
    "day": {
        "root": 110.0,
        "brightness": 1.0,
        "breath": 0.15,
        "chord_s": 4.0,
        "volume": 1.0,
        "sets": (
            ((0, 3, 7), (-4, 0, 3), (3, 7, 10), (-2, 2, 7)),
            ((0, 4, 7), (5, 9, 12), (-3, 2, 5), (0, 4, 9)),
            ((0, 5, 9), (-2, 3, 7), (2, 5, 10), (0, 3, 7)),
        ),
    },
    "night": {
        "root": 82.5,
        "brightness": 0.45,
        "breath": 0.09,
        "chord_s": 4.6,
        "volume": 0.9,
        "sets": (
            ((0, 3, 7), (5, 8, 12), (-4, 0, 3), (-5, -1, 2)),
            ((0, 3, 10), (-2, 1, 8), (-5, 0, 3), (0, 3, 7)),
            ((0, 2, 7), (-7, -3, 0), (-4, 1, 5), (0, 3, 8)),
        ),
    },
    # Inside a settlement: higher, warmer and moving a little quicker, because a street is
    # the one place in the world with people in it.
    "village": {
        "root": 146.8,
        "brightness": 1.25,
        "breath": 0.22,
        "chord_s": 3.2,
        "volume": 0.85,
        "sets": (
            ((0, 4, 7), (2, 5, 9), (-3, 0, 4), (0, 4, 7)),
            ((0, 4, 9), (5, 9, 14), (0, 5, 7), (0, 4, 7)),
        ),
    },
    # A fight: low, close, and pulsing hard enough to be felt under the sound effects.
    "combat": {
        "root": 98.0,
        "brightness": 0.8,
        "breath": 2.4,
        "chord_s": 1.6,
        "volume": 1.15,
        "sets": (
            ((0, 1, 7), (0, 3, 6), (-1, 2, 5), (0, 1, 7)),
            ((0, 6, 7), (-2, 4, 5), (0, 3, 6), (0, 6, 7)),
            ((0, 2, 6), (1, 4, 7), (-2, 1, 6), (0, 2, 6)),
        ),
    },
    # Something with a name standing in front of you: lower still, slower, and heavier.
    "boss": {
        "root": 73.4,
        "brightness": 1.5,
        "breath": 1.1,
        "chord_s": 2.4,
        "volume": 1.3,
        "sets": (
            ((0, 1, 6), (-5, 0, 6), (0, 3, 6), (0, 1, 6)),
            ((0, 6, 11), (-4, 1, 6), (-7, 0, 5), (0, 6, 11)),
        ),
    },
    # The night the whole world is seen through red: the night pad, sharpened and sped up.
    "blood": {
        "root": 87.3,
        "brightness": 1.6,
        "breath": 0.7,
        "chord_s": 2.8,
        "volume": 1.1,
        "sets": (
            ((0, 3, 6), (-1, 2, 5), (0, 4, 6), (0, 3, 6)),
            ((0, 1, 8), (-3, 0, 6), (-6, 1, 4), (0, 1, 8)),
        ),
    },
}

# How loud the music sits under everything else. It is background, and the game is read
# through its sound effects.
MASTER_VOLUME = 0.32
# Seconds a crossfade between two pads takes, in the volume the update applies.
FADE_PER_SECOND = 0.6
# How long one progression is left alone before the same context swaps itself to another of
# its own. Long enough not to be fidgeting, short enough that a night in one place is not
# four bars on repeat.
VARIANT_MS = 62_000.0

_MUSIC_CHANNELS = 2


def _render_pad(chords, root_hz: float, brightness: float, breath_hz: float, chord_seconds: float) -> array.array:
    """One looping pad: each chord swelling in and out, its partials thinned by `brightness`.

    The whole progression is written in a single pass over the samples, with every partial
    advanced by its own phase step, which keeps the cost to a handful of float operations
    per sample rather than one pass per note.
    """
    chord_samples = int(SAMPLE_RATE * chord_seconds)
    total = chord_samples * len(chords)
    out = array.array("h", bytes(2 * total))

    partials = ((1.0, 1.0), (2.0, 0.30 * brightness), (3.0, 0.12 * brightness))
    breath_step = breath_hz * _TABLE_SIZE / SAMPLE_RATE

    for chord_index, chord in enumerate(chords):
        voices = []
        for semitone in chord:
            freq = root_hz * (2.0 ** (semitone / 12.0))
            for ratio, weight in partials:
                # A random start phase per partial stops every voice from beginning on the
                # same peak, which is what a chord sounding like one buzzing sawtooth is.
                voices.append([random.uniform(0, _TABLE_SIZE), freq * ratio * _TABLE_SIZE / SAMPLE_RATE, weight])
        norm = 1.0 / sum(weight for _, _, weight in voices)

        breath = random.uniform(0, _TABLE_SIZE)
        base = chord_index * chord_samples
        for i in range(chord_samples):
            t = i / chord_samples
            # Swell in over the first third, hold, and fall away: the seam between two
            # chords lands where both are near silent, so nothing clicks.
            envelope = math.sin(math.pi * t) ** 0.6
            value = 0.0
            for voice in voices:
                phase = voice[0]
                value += _SINE[int(phase) & (_TABLE_SIZE - 1)] * voice[2]
                voice[0] = phase + voice[1]
            breath = breath + breath_step
            tremolo = 0.88 + 0.12 * _SINE[int(breath) & (_TABLE_SIZE - 1)]
            sample = int(value * norm * envelope * tremolo * 0.85 * 32767)
            out[base + i] = max(-32768, min(32767, sample))

    return out


class MusicPlayer:
    """Which pad is playing, and the crossfade from the last one to it.

    Silent and harmless when there is no audio device, when the mixer has no channels to
    reserve, or while the pad that has been asked for is still being rendered.
    """

    def __init__(self):
        self.enabled = bool(get_settings().get("music"))
        # (context, variant) -> Sound, filled in by the worker thread as it gets to them.
        self._pads: dict[tuple[str, int], pygame.mixer.Sound] = {}
        self._wanted: set[tuple[str, int]] = set()
        self._requests: queue.Queue = queue.Queue()
        self._channels = None
        # Which of the two channels is carrying the music, what it is playing, and the
        # level each is fading towards.
        self._slot = 0
        self._playing: tuple[str, int] | None = None
        self._levels = [0.0, 0.0]
        self._context = "day"
        self._variant_age = 0.0

        if pygame.mixer.get_init() is None:
            return
        try:
            pygame.mixer.set_reserved(_MUSIC_CHANNELS)
            self._channels = tuple(pygame.mixer.Channel(i) for i in range(_MUSIC_CHANNELS))
        except Exception as e:
            print(f"Music init failed, music disabled: {e}")
            return
        threading.Thread(target=self._worker, daemon=True).start()
        # The two the game opens on, so something is ready by the time the player is walking.
        for context in ("day", "night"):
            self._request(context, 0)

    # ------------------------------------------------------------------ rendering

    def _worker(self):
        while True:
            key = self._requests.get()
            context, variant = key
            row = CONTEXTS[context]
            chords = row["sets"][variant % len(row["sets"])]
            try:
                pad = _render_pad(chords, row["root"], row["brightness"], row["breath"], row["chord_s"])
                self._pads[key] = pygame.mixer.Sound(buffer=pad.tobytes())
            except Exception as e:
                print(f"Music render failed for {context}: {e}")

    def _request(self, context: str, variant: int):
        key = (context, variant)
        if key in self._pads or key in self._wanted:
            return
        self._wanted.add(key)
        self._requests.put(key)

    @property
    def ready(self) -> bool:
        """Whether anything at all can be played yet, which is what the menus ask."""
        return bool(self._pads)

    # ------------------------------------------------------------------ playing

    def _play(self, key):
        """Bring `key` in on the free channel and start the other one fading out."""
        self._slot = 1 - self._slot
        channel = self._channels[self._slot]
        channel.set_volume(0.0)
        channel.play(self._pads[key], loops=-1)
        self._levels[self._slot] = 0.0
        self._playing = key
        self._variant_age = 0.0

    def _stop(self):
        if self._channels is None:
            return
        for channel in self._channels:
            channel.stop()
        self._playing = None
        self._levels = [0.0, 0.0]

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        if not enabled:
            self._stop()

    def update(self, dt: float, darkness: float, context: str = "day"):
        """`context` is what the world is doing right now, one of `CONTEXTS`.

        Resolved by the caller (`Game._music_context`), because what counts as a fight is
        the game's business and not the mixer's. `darkness` only survives as the thing that
        decides between day and night when the caller has nothing louder to say.
        """
        if self._channels is None or not self.enabled:
            return
        if context not in CONTEXTS:
            context = "night" if darkness > 0.5 else "day"

        self._variant_age += dt
        if context != self._context:
            self._context = context
            self._variant_age = VARIANT_MS  # a new context picks its progression at once

        # A context stays on one progression for a while and then moves to another of its
        # own, so standing still for an hour is not four bars on repeat.
        if self._playing is None or self._playing[0] != context or self._variant_age >= VARIANT_MS:
            choices = [v for v in range(len(CONTEXTS[context]["sets"])) if (context, v) != self._playing]
            variant = random.choice(choices) if choices else 0
            key = (context, variant)
            if key in self._pads:
                self._play(key)
            else:
                self._request(context, variant)
                # Nothing to swap to yet: leave what is playing where it is and try again
                # next frame rather than dropping into silence while it renders.
                self._variant_age = min(self._variant_age, VARIANT_MS)

        step = min(1.0, FADE_PER_SECOND * dt / 1000.0)
        volume = MASTER_VOLUME * CONTEXTS[self._context]["volume"]
        for slot in range(_MUSIC_CHANNELS):
            target = 1.0 if (self._playing is not None and slot == self._slot) else 0.0
            self._levels[slot] += (target - self._levels[slot]) * step
            self._channels[slot].set_volume(volume * self._levels[slot])


_player = None


def get_music() -> MusicPlayer:
    global _player
    if _player is None:
        _player = MusicPlayer()
    return _player
