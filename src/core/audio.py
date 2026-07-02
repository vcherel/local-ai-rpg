"""Lightweight procedural sound effects.

Tones are synthesised in memory at startup (no audio asset files, no extra
dependencies) and played through pygame's mixer. If the mixer is unavailable
(e.g. no audio device), everything degrades to a silent no-op.
"""

from __future__ import annotations

import array
import math

import pygame

SAMPLE_RATE = 44100

# Each effect is a list of (frequency_hz, duration_s) segments plus a volume and
# waveform. Segments play back to back, each with a short linear decay.
_SOUND_SPECS = {
    "attack": ([(600, 0.04), (300, 0.06)], 0.25, "square"),
    "hit": ([(160, 0.08), (110, 0.06)], 0.35, "square"),
    "monster_death": ([(400, 0.06), (250, 0.07), (150, 0.10)], 0.30, "square"),
    "player_hurt": ([(220, 0.10), (160, 0.10)], 0.40, "square"),
    "pickup": ([(660, 0.06), (990, 0.08)], 0.30, "sine"),
    "quest_new": ([(523, 0.09), (659, 0.09), (784, 0.13)], 0.30, "sine"),
    "quest_complete": ([(523, 0.08), (659, 0.08), (784, 0.08), (1047, 0.18)], 0.35, "sine"),
    "lootbox_open": ([(440, 0.07), (660, 0.07), (880, 0.12)], 0.32, "sine"),
}


def _synth(segments, volume, wave) -> array.array:
    samples = array.array("h")
    for freq, duration in segments:
        count = int(SAMPLE_RATE * duration)
        for i in range(count):
            t = i / SAMPLE_RATE
            envelope = 1.0 - i / count  # fade each segment out to avoid clicks
            if wave == "square":
                shape = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
            else:
                shape = math.sin(2 * math.pi * freq * t)
            value = int(shape * envelope * volume * 32767)
            samples.append(max(-32768, min(32767, value)))
    return samples


class SoundManager:
    def __init__(self):
        self.sounds = {}
        self.enabled = pygame.mixer.get_init() is not None
        if not self.enabled:
            return
        try:
            for name, (segments, volume, wave) in _SOUND_SPECS.items():
                samples = _synth(segments, volume, wave)
                self.sounds[name] = pygame.mixer.Sound(buffer=samples.tobytes())
        except Exception as e:
            print(f"Audio init failed, sound disabled: {e}")
            self.enabled = False

    def play(self, name: str):
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is not None:
            sound.play()


_manager = None


def get_audio() -> SoundManager:
    global _manager
    if _manager is None:
        _manager = SoundManager()
    return _manager


def play_sound(name: str):
    get_audio().play(name)
