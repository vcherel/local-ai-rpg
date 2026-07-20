import random

import core.constants as c


class ScreenShake:
    """Global camera-shake state. Combat code calls `add`; the camera reads the current
    per-frame offset in `world_to_screen`. One offset per frame keeps the whole scene
    shaking together instead of each entity jittering independently."""

    def __init__(self):
        self.amp = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0

    def add(self, amount: float):
        self.amp = min(max(self.amp, amount), c.Combat.MAX_SHAKE)

    def update(self, dt):
        if self.amp <= 0.3:
            self.amp = self.offset_x = self.offset_y = 0.0
            return
        self.offset_x = random.uniform(-self.amp, self.amp)
        self.offset_y = random.uniform(-self.amp, self.amp)
        self.amp *= c.Combat.SHAKE_DECAY ** (dt * c.TARGET_FPS / 1000.0)


_shake = None


def get_shake() -> ScreenShake:
    global _shake
    if _shake is None:
        _shake = ScreenShake()
    return _shake


class Camera:
    """Handles world-to-screen translation, including the current screen-shake offset."""

    def __init__(self):
        self.x = 0  # Player's world x
        self.y = 0  # Player's world y

    def get_pos(self):
        return (self.x, self.y)

    def set_pos(self, pos):
        """Update camera position"""
        self.x = pos[0]
        self.y = pos[1]

    def world_to_screen(self, x, y):
        """Convert world coordinates to screen coordinates"""
        shake = get_shake()
        screen_x = x - self.x + c.Screen.ORIGIN_X + shake.offset_x
        screen_y = y - self.y + c.Screen.ORIGIN_Y + shake.offset_y
        return screen_x, screen_y
