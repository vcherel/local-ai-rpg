"""Text drawn straight onto the world, readable without a panel behind it.

A name floating over somebody's head used to sit on a rounded rectangle, which read as
a tombstone standing in the grass rather than as a label belonging to the body under it.
An outline does the same job (light text stays legible over pale ground) without putting
a piece of HUD into the world.
"""

from __future__ import annotations

import pygame

# The eight directions the outline is stamped in. Four would leave the diagonals thin
# enough for a bright background to eat the glyph edge.
_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))


def draw_outlined_text(
    screen: pygame.Surface,
    text: str,
    font: pygame.font.Font,
    color,
    outline=(16, 14, 12),
    center=None,
    topleft=None,
    width: int = 1,
) -> pygame.Rect:
    """Blit `text` with a dark rim round it. Give exactly one of `center` or `topleft`."""
    body = font.render(text, True, color)
    rim = font.render(text, True, outline)
    rect = body.get_rect(center=center) if center is not None else body.get_rect(topleft=topleft)
    for ox, oy in _OFFSETS:
        screen.blit(rim, (rect.x + ox * width, rect.y + oy * width))
    screen.blit(body, rect)
    return rect
