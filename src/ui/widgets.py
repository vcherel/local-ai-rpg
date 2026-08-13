"""Shared drawing primitives for menus and HUD.

Every panel, button and slot in the game draws through these helpers so a visual
tweak lands everywhere at once instead of being reinvented per menu. The look is
flat and square: solid fills, plain borders, a gold accent on hover/focus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import pygame

import core.constants as c

if TYPE_CHECKING:
    from game.entities.items import Item

# The equip slots as the UI shows them: (Player equip slot, caption, ghost glyph drawn when
# empty). Shared by the HUD strip and the inventory paper-doll so the two can't disagree.
# Melee and ranged are separate slots, so a sword and a bow are carried and equipped at once.
EQUIP_SLOTS = (
    ("melee_weapon", "Melee", "sword"),
    ("ranged_weapon", "Ranged", "sword"),
    ("offhand", "Shield", "shield"),
    ("armor", "Armor", "shield"),
    ("accessory", "Accessory", "gem"),
)


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill: Optional[tuple] = None,
    border: Optional[tuple] = None,
    border_w: int = 2,
):
    """Fill `rect` with a flat panel color and a square border."""
    fill = fill or c.Colors.MENU_BACKGROUND
    border = border or c.Colors.BORDER

    pygame.draw.rect(surface, fill, rect)
    if border_w:
        pygame.draw.rect(surface, border, rect, border_w)


def draw_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    text: str,
    font: pygame.font.Font,
    hovered: bool = False,
    pressed: bool = False,
    text_color: Optional[tuple] = None,
    accent: Optional[tuple] = None,
):
    """A flat, square button with a gold border on hover, sinks slightly when pressed."""
    accent = accent or c.Colors.ACCENT
    text_color = text_color or c.Colors.WHITE
    draw_rect = rect.move(0, 2) if pressed else rect

    fill = c.Colors.BUTTON_HOVERED if hovered else c.Colors.BUTTON
    border = accent if hovered else c.Colors.BORDER
    pygame.draw.rect(surface, fill, draw_rect)
    pygame.draw.rect(surface, border, draw_rect, 2)

    label = font.render(text, True, text_color)
    surface.blit(label, label.get_rect(center=draw_rect.center))


def draw_slot(
    surface: pygame.Surface,
    rect: pygame.Rect,
    hovered: bool = False,
    border_color: Optional[tuple] = None,
    glow_color: Optional[tuple] = None,
    border_w: int = 2,
):
    """An inset slot for grid cells and list rows, with an optional rarity tint/glow."""
    bg = c.Colors.SLOT_BG_HOVER if hovered else c.Colors.SLOT_BG
    pygame.draw.rect(surface, bg, rect)
    if glow_color:
        glow = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(glow, (*glow_color, 46), glow.get_rect())
        surface.blit(glow, rect.topleft)
    bc = border_color or (c.Colors.ACCENT if hovered else c.Colors.SLOT_BORDER)
    pygame.draw.rect(surface, bc, rect, border_w)


def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Greedy word-wrap: break `text` into lines that each fit within `max_width` px of `font`."""
    lines = []
    current_line = []
    for word in text.split():
        candidate = " ".join(current_line + [word])
        if font.size(candidate)[0] <= max_width:
            current_line.append(word)
            continue
        if current_line:
            lines.append(" ".join(current_line))
            current_line = []
        # A single word too long for a line (an unspaced run from the LLM) would otherwise
        # be laid down as one line running off the panel, so break it on characters.
        while font.size(word)[0] > max_width:
            cut = len(word) - 1
            while cut > 1 and font.size(word[:cut])[0] > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines


def draw_item_scaled(surface: pygame.Surface, item: "Item", cx: int, cy: int, size: int):
    """Draw an item icon scaled to `size` px, centered at (cx, cy).

    Item.draw renders at a fixed small size, too tiny for big inventory slots, so we
    render once to a scratch surface and scale it up smoothly.
    """
    base = c.Entities.ITEM_SIZE
    pad = 44
    tmp_size = base + pad
    tmp = pygame.Surface((tmp_size, tmp_size), pygame.SRCALPHA)
    item.draw(tmp, x=tmp_size // 2, y=tmp_size // 2)
    scale = size / base
    scaled = pygame.transform.smoothscale(tmp, (int(tmp_size * scale), int(tmp_size * scale)))
    surface.blit(scaled, scaled.get_rect(center=(cx, cy)))
