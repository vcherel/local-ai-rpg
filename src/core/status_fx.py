"""Status bubbles: the timed effects on a body, drawn as small icons over its head.

One table row per effect (colour plus glyph) and one draw call, shared by the player,
the villagers and the monsters, so an effect looks the same whoever is wearing it. The
HUD buff chips stay the detailed readout with the seconds left on each; these say what
is on somebody at a glance, from across a fight, and carry no timer.

Adding an effect means adding a row to `EFFECTS`, not a branch: whatever an entity's
`status_effects()` returns and this table knows about gets a bubble.
"""

from __future__ import annotations

import math

import pygame

import core.constants as c

# effect key -> (bubble colour, glyph). The glyph is one character from the normal font,
# since a status bubble is read by its colour first and only confirmed by its mark.
EFFECTS = {
    "burn": ((238, 122, 44), "^"),
    "chill": ((122, 206, 238), "*"),
    "root": ((150, 118, 74), "X"),
    "weakened": ((214, 62, 72), "v"),
    "regen": ((92, 208, 118), "+"),
    "strength": ((232, 132, 46), "!"),
    "swiftness": ((88, 198, 234), ">"),
    "stoneskin": ((172, 172, 188), "O"),
    "bloodlust": ((196, 46, 66), "#"),
}

RADIUS = 9
GAP = 4


def draw_bubbles(screen: pygame.Surface, cx: float, cy: float, effects) -> None:
    """A row of bubbles centred on (cx, cy), which is above the head the effects are on.

    They bob together on a shared clock rather than each on its own, so a body carrying
    three effects reads as one marker instead of three unrelated blinking dots.
    """
    known = [effect for effect in effects if effect in EFFECTS]
    if not known:
        return

    bob = math.sin(pygame.time.get_ticks() / 260) * 2
    step = RADIUS * 2 + GAP
    x = cx - (len(known) * step - GAP) / 2 + RADIUS
    y = cy + bob

    for effect in known:
        color, glyph = EFFECTS[effect]
        center = (round(x), round(y))
        pygame.draw.circle(screen, (18, 16, 14), (center[0], center[1] + 1), RADIUS)
        pygame.draw.circle(screen, color, center, RADIUS)
        pygame.draw.circle(screen, (250, 248, 244), center, RADIUS, 1)
        mark = c.Fonts.small.render(glyph, True, (24, 20, 18))
        screen.blit(mark, mark.get_rect(center=center))
        x += step
