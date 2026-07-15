"""Shared drawing primitives for menus and HUD.

Every panel, button and slot in the game draws through these helpers so a visual
tweak lands everywhere at once instead of being reinvented per menu. The look is a
polished dark theme: rounded corners, a soft drop shadow, a subtle vertical
gradient fill and a gold accent on focus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import pygame

import core.constants as c

if TYPE_CHECKING:
    from game.entities.items import Item


def _vertical_gradient(width: int, height: int, top: tuple, bottom: tuple) -> pygame.Surface:
    grad = pygame.Surface((width, height), pygame.SRCALPHA)
    if height <= 1:
        grad.fill((*top, 255))
        return grad
    for y in range(height):
        t = y / (height - 1)
        col = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
            255,
        )
        pygame.draw.line(grad, col, (0, y), (width, y))
    return grad


def draw_shadow(surface: pygame.Surface, rect: pygame.Rect, radius: int = 14, offset: int = 8, blur: int = 9):
    """Cast a soft drop shadow for `rect`, offset downward, faked with expanding rings."""
    if rect.width <= 0 or rect.height <= 0:
        return
    shadow = pygame.Surface((rect.width + blur * 2, rect.height + blur * 2), pygame.SRCALPHA)
    for i in range(blur, 0, -1):
        alpha = int(c.Colors.SHADOW_ALPHA * (blur - i + 1) / blur / blur)
        ring = pygame.Rect(blur - i, blur - i, rect.width + i * 2, rect.height + i * 2)
        pygame.draw.rect(shadow, (0, 0, 0, alpha), ring, border_radius=radius + i)
    surface.blit(shadow, (rect.x - blur, rect.y - blur + offset))


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    radius: int = 14,
    top: Optional[tuple] = None,
    bottom: Optional[tuple] = None,
    border: Optional[tuple] = None,
    border_w: int = 2,
):
    """Fill `rect` with a rounded vertical-gradient panel and a border."""
    top = top or c.Colors.PANEL_TOP
    bottom = bottom or c.Colors.PANEL_BOTTOM
    border = border or c.Colors.PANEL_BORDER

    grad = _vertical_gradient(rect.width, rect.height, top, bottom)
    mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(grad, rect.topleft)
    if border_w:
        pygame.draw.rect(surface, border, rect, border_w, border_radius=radius)


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
    """A tactile button: drop shadow, gradient fill, gold border on hover, sinks when pressed."""
    accent = accent or c.Colors.ACCENT
    text_color = text_color or c.Colors.WHITE
    draw_rect = rect.move(0, 2) if pressed else rect

    draw_shadow(surface, draw_rect, radius=10, offset=4, blur=6)

    top, bottom = c.Colors.BUTTON_TOP, c.Colors.BUTTON_BOTTOM
    if hovered:
        top = tuple(min(255, v + 16) for v in top)
        bottom = tuple(min(255, v + 16) for v in bottom)
    draw_panel(
        surface,
        draw_rect,
        radius=10,
        top=top,
        bottom=bottom,
        border=accent if hovered else c.Colors.PANEL_BORDER,
        border_w=2,
    )

    label = font.render(text, True, text_color)
    surface.blit(label, label.get_rect(center=draw_rect.center))


def draw_slot(
    surface: pygame.Surface,
    rect: pygame.Rect,
    hovered: bool = False,
    border_color: Optional[tuple] = None,
    glow_color: Optional[tuple] = None,
    radius: int = 8,
    border_w: int = 2,
):
    """An inset slot for grid cells and list rows, with an optional rarity tint/glow."""
    bg = c.Colors.SLOT_BG_HOVER if hovered else c.Colors.SLOT_BG
    pygame.draw.rect(surface, bg, rect, border_radius=radius)
    if glow_color:
        glow = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(glow, (*glow_color, 46), glow.get_rect(), border_radius=radius)
        surface.blit(glow, rect.topleft)
    bc = border_color or (c.Colors.ACCENT if hovered else c.Colors.SLOT_BORDER)
    pygame.draw.rect(surface, bc, rect, border_w, border_radius=radius)


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
