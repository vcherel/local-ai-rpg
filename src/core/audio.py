"""Lightweight procedural sound effects.

Tones are synthesised in memory at startup (no audio asset files, no extra
dependencies) and played through pygame's mixer. If the mixer is unavailable
(e.g. no audio device), everything degrades to a silent no-op.
"""

from __future__ import annotations

import array
import math
import random

import pygame

from core.settings import get_settings

SAMPLE_RATE = 44100

# Each effect is a list of (frequency_hz, duration_s) segments plus a volume and
# waveform. Segments play back to back, each with a short linear decay.
_SOUND_SPECS = {
    "attack": ([(600, 0.04), (300, 0.06)], 0.25, "square"),
    "shoot": ([(900, 0.03), (450, 0.05)], 0.25, "sine"),
    "hit": ([(160, 0.08), (110, 0.06)], 0.35, "square"),
    "crit": ([(520, 0.04), (300, 0.05), (180, 0.08)], 0.40, "square"),
    "monster_death": ([(400, 0.06), (250, 0.07), (150, 0.10)], 0.30, "square"),
    "player_hurt": ([(220, 0.10), (160, 0.10)], 0.40, "square"),
    "pickup": ([(660, 0.06), (990, 0.08)], 0.30, "sine"),
    "quest_new": ([(523, 0.09), (659, 0.09), (784, 0.13)], 0.30, "sine"),
    "quest_complete": ([(523, 0.08), (659, 0.08), (784, 0.08), (1047, 0.18)], 0.35, "sine"),
    "level_up": ([(440, 0.06), (587, 0.06), (740, 0.06), (880, 0.16)], 0.35, "sine"),
    "lootbox_open": ([(440, 0.07), (660, 0.07), (880, 0.12)], 0.32, "sine"),
    "potion_drink": ([(300, 0.05), (420, 0.05), (620, 0.06), (880, 0.10)], 0.28, "sine"),
    "crate_break": ([(200, 0.05), (130, 0.05), (80, 0.08)], 0.35, "square"),
    "glass_break": ([(1500, 0.02), (1100, 0.02), (1800, 0.02), (700, 0.05)], 0.28, "sine"),
    "bush_rustle": ([(300, 0.03), (250, 0.03), (200, 0.04)], 0.18, "square"),
    "door": ([(180, 0.06), (140, 0.05), (95, 0.09)], 0.24, "square"),
    "discover": ([(523, 0.08), (784, 0.10), (1047, 0.18)], 0.28, "sine"),
    "rest": ([(392, 0.12), (330, 0.14), (262, 0.22)], 0.25, "sine"),
    "fuse": ([(700, 0.06), (880, 0.06), (1100, 0.08), (1400, 0.10)], 0.22, "square"),
    # Steel jaws: a bright snap over a low thunk, so a trap shutting is heard before the
    # health bar is read.
    "trap_snap": ([(1700, 0.02), (900, 0.03), (240, 0.06), (120, 0.12)], 0.40, "square"),
    # A villager shouting the player off before their street turns on them.
    "shout": ([(330, 0.05), (392, 0.05), (294, 0.09)], 0.30, "square"),
    # Something arriving where nothing was: a boss's summons clawing out of the ground.
    "summon": ([(120, 0.08), (180, 0.07), (260, 0.07), (150, 0.12)], 0.30, "square"),
    # The wet burst of a body opening up. Noise rather than a tone: a kill is the one sound
    # in the game that must not be musical.
    "gore": ([(220, 0.05), (130, 0.08), (70, 0.14)], 0.45, "noise"),
    # A gate beaten off its hinges: splintering over the thud of the leaf going down.
    "gate_break": ([(400, 0.05), (260, 0.07), (150, 0.10), (70, 0.18)], 0.45, "noise"),
    # And the same gate shutting itself: a long creak onto a heavy thump.
    "gate_close": ([(150, 0.16), (120, 0.14), (90, 0.10), (60, 0.14)], 0.34, "square"),
    # Sitting down at a fire: not a chime, just the wood settling under a pot.
    "fire_crackle": ([(320, 0.04), (180, 0.06), (240, 0.05)], 0.20, "noise"),
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
            elif wave == "noise":
                # Band-limited only by the tone it is mixed with: the frequency sets a dull
                # body under the hiss, so a splatter still has a pitch to it.
                shape = math.sin(2 * math.pi * freq * t) * 0.35 + random.uniform(-1.0, 1.0) * 0.65
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
        """Silent while the sound preference is off: muting is a preference, not a state of
        the mixer, so it is read here rather than by every call site."""
        if not self.enabled or not get_settings().get("sound"):
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
