"""Player preferences that belong to the install rather than to a game.

Kept apart from `SaveSystem` on purpose: a save is one playthrough and is wiped by New
game, while whether the music plays is a fact about this machine and must outlive both.
Small, flat and read through one module-level object, since anything that wants a
preference wants the same one everything else is reading.
"""

from __future__ import annotations

import json
import os
import tempfile

import core.constants as c

PATH = "./saves/settings.json"

DEFAULTS = {
    "music": True,
    # Every sound effect the game makes, apart from the music, which has its own switch.
    "sound": True,
    # Which keyboard the four walking keys are read off: AZERTY puts Z Q S D under the
    # hand where QWERTY puts W A S D. Toggled in the pause menu, since a player on the
    # wrong one cannot walk to a menu that is anywhere else.
    "azerty": False,
    # Hold every nearby villager's vision cone up instead of only showing it over something
    # worth stealing (V in game).
    "cones": False,
    # Whether the player has already been told that key exists. Shown once, the first time
    # they stand in somebody's room, and never again on this machine.
    "cones_hinted": False,
}


class Settings:
    def __init__(self, filename: str = PATH):
        self.filename = filename
        self.data = dict(DEFAULTS)
        self._load()

    def _load(self):
        try:
            with open(self.filename) as f:
                stored = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        # Only keys the build still knows about, so an old file never revives a setting
        # that has been removed.
        self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value):
        self.data[key] = value
        self.save()

    def toggle(self, key: str) -> bool:
        self.set(key, not self.get(key))
        return self.get(key)

    def save(self):
        """Written the same way a save is: to a temporary file, then moved into place, so a
        crash mid-write cannot leave a settings file that will not parse."""
        directory = os.path.dirname(self.filename) or "."
        os.makedirs(directory, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as tmp:
                json.dump(self.data, tmp, indent=2)
                temp_name = tmp.name
            os.replace(temp_name, self.filename)
        except OSError as e:
            print(f"Could not write settings: {e}")


_settings = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def move_keys() -> tuple:
    """The four walking keys, north west south east, off the layout the player picked.

    One reader for everything that has to know which keys walk: the movement itself and
    what the help screen says are the same answer.
    """
    return c.Controls.AZERTY if get_settings().get("azerty") else c.Controls.QWERTY
