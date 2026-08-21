"""Background music, synthesised in memory like the sound effects.

No asset files and no new dependency: the score is two slow chord pads, one for daylight
and one for the dark, each looping forever on its own reserved channel. The day/night
cycle crossfades between them, so the music answers the same clock the sky does instead
of being a track that plays over the top of everything.

Rendering a pad in pure Python is slow enough to be felt, so it happens on a daemon
thread and the music simply starts once it is ready. Whether it plays at all is a
preference (`core.settings`), read once here and toggled from the pause menu.
"""

from __future__ import annotations

import array
import math
import random
import threading

import pygame

from core.audio import SAMPLE_RATE
from core.settings import get_settings

# One cycle of a sine, looked up rather than recomputed: a pad is a few million samples
# and math.sin per partial per sample is what made the first version take half a minute.
_TABLE_SIZE = 2048
_SINE = [math.sin(2 * math.pi * i / _TABLE_SIZE) for i in range(_TABLE_SIZE)]

# Semitone offsets from the root, one tuple per chord. Both progressions resolve back to
# where they started, since the loop point has to pass unnoticed.
DAY_CHORDS = ((0, 3, 7), (-4, 0, 3), (3, 7, 10), (-2, 2, 7))
NIGHT_CHORDS = ((0, 3, 7), (5, 8, 12), (-4, 0, 3), (-5, -1, 2))

DAY_ROOT_HZ = 110.0
NIGHT_ROOT_HZ = 82.5

CHORD_SECONDS = 4.0
# How loud the music sits under everything else. It is background, and the game is read
# through its sound effects.
MASTER_VOLUME = 0.32
# Seconds a crossfade between the two pads takes, in the volume the update applies.
FADE_PER_SECOND = 0.4

_MUSIC_CHANNELS = 2


def _render_pad(chords, root_hz: float, brightness: float, breath_hz: float) -> array.array:
    """One looping pad: each chord swelling in and out, its partials thinned by `brightness`.

    The whole progression is written in a single pass over the samples, with every partial
    advanced by its own phase step, which keeps the cost to a handful of float operations
    per sample rather than one pass per note.
    """
    chord_samples = int(SAMPLE_RATE * CHORD_SECONDS)
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
    """The two pads and the crossfade between them.

    Silent and harmless when there is no audio device, when the mixer has no channels to
    reserve, or while the pads are still being rendered.
    """

    def __init__(self):
        self.enabled = bool(get_settings().get("music"))
        self.ready = False
        self.day_level = 1.0
        self.night_level = 0.0
        self._channels = None
        self._sounds = None

        if pygame.mixer.get_init() is None:
            return
        pygame.mixer.set_reserved(_MUSIC_CHANNELS)
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        try:
            day = _render_pad(DAY_CHORDS, DAY_ROOT_HZ, brightness=1.0, breath_hz=0.15)
            night = _render_pad(NIGHT_CHORDS, NIGHT_ROOT_HZ, brightness=0.45, breath_hz=0.09)
            sounds = (pygame.mixer.Sound(buffer=day.tobytes()), pygame.mixer.Sound(buffer=night.tobytes()))
            channels = tuple(pygame.mixer.Channel(i) for i in range(_MUSIC_CHANNELS))
        except Exception as e:
            print(f"Music init failed, music disabled: {e}")
            return
        self._sounds = sounds
        self._channels = channels
        self.ready = True
        if self.enabled:
            self._start()

    def _start(self):
        if not self.ready:
            return
        for channel, sound in zip(self._channels, self._sounds):
            channel.set_volume(0.0)
            channel.play(sound, loops=-1)
        self._apply_volumes()

    def _stop(self):
        if not self.ready:
            return
        for channel in self._channels:
            channel.stop()

    def _apply_volumes(self):
        if not self.ready or not self.enabled:
            return
        self._channels[0].set_volume(MASTER_VOLUME * self.day_level)
        self._channels[1].set_volume(MASTER_VOLUME * self.night_level)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        if enabled:
            self._start()
        else:
            self._stop()

    def update(self, dt: float, darkness: float):
        """`darkness` is the day/night cycle's own 0..1, so dusk moves the music with the sky.

        Eased rather than assigned, so a jump in the cycle (a night's sleep, a load) fades
        across instead of switching pad mid-bar.
        """
        if not self.ready or not self.enabled:
            return
        step = min(1.0, FADE_PER_SECOND * dt / 1000.0)
        target_night = max(0.0, min(1.0, darkness))
        self.night_level += (target_night - self.night_level) * step
        self.day_level += ((1.0 - target_night) - self.day_level) * step
        self._apply_volumes()


_player = None


def get_music() -> MusicPlayer:
    global _player
    if _player is None:
        _player = MusicPlayer()
    return _player
