from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

import core.constants as c
from ui import widgets

if TYPE_CHECKING:
    from game.quest import Quest
    from game.record import Record
    from llm.quest_system import QuestSystem


def _progress_line(quest: Quest) -> str:
    if quest.quest_type == "kill_mob":
        return f"Kill {quest.target_monster_kind}: {quest.kills_done}/{quest.kill_count}"
    if quest.quest_type == "loot_mob":
        return f"Loot {quest.item_name} from a {quest.target_monster_kind}"
    if quest.quest_type == "recover_stolen":
        return f"Recover {quest.item_name} from {quest.thief_npc_name}"
    if quest.quest_type == "slay_boss":
        return f"Slay {quest.boss_name}" if quest.boss_name else "Slay the boss"
    if quest.quest_type == "clear_camp":
        return "Camp cleared" if quest.kills_done >= quest.kill_count else "Wipe out the bandit camp"
    if quest.quest_type == "steal":
        return f"Steal {quest.item_name} from the house"
    if quest.quest_type == "deliver":
        if quest.kills_done >= quest.kill_count:
            return f"{quest.item_name} delivered"
        return f"Take {quest.item_name} to {quest.recipient_npc_name}"
    return f"Fetch: {quest.item_name}"


class QuestTracker:
    """Permanent top right HUD widget: one quest tracked in full, others as swap chips.

    Replaces the old top left "new quest" slide-in banner: a freshly granted quest is
    made the tracked one and its card briefly flashes gold instead of a separate popup.
    """

    WIDTH = 300
    CARD_HEIGHT = 118
    CHIP_HEIGHT = 30
    CHIP_GAP = 6
    HIGHLIGHT_MS = 1800

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.tracked: Quest | None = None
        self.collapsed = False
        self.highlight_until = 0
        self.collapse_button_rect = pygame.Rect(0, 0, 0, 0)
        self.chip_rects: list[tuple[pygame.Rect, Quest]] = []

    def notify_new_quest(self, quest: Quest):
        self.tracked = quest
        self.collapsed = False
        self.highlight_until = pygame.time.get_ticks() + self.HIGHLIGHT_MS

    def _resolve_tracked(self, active_quests: list) -> Quest | None:
        if self.tracked is None or not any(q is self.tracked for q in active_quests):
            self.tracked = active_quests[0] if active_quests else None
        return self.tracked

    def handle_event(self, event: pygame.event.Event, quest_system: QuestSystem) -> bool:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        if not quest_system.active_quests:
            return False

        if self.collapse_button_rect.collidepoint(event.pos):
            self.collapsed = not self.collapsed
            return True

        if not self.collapsed:
            for rect, quest in self.chip_rects:
                if rect.collidepoint(event.pos):
                    self.tracked = quest
                    return True

        return False

    def draw(self, quest_system: QuestSystem, top: int, record: Record | None = None):
        """`top` is where the minimap's own strips ended (Minimap.content_bottom), not a
        fixed offset: the clock and the village name under the map change height, and the
        card used to be laid straight over them.

        Never blank: with no quest in hand the card is replaced by one slim line pointing
        the player at a notice board, and the quest-tally milestone always hangs below,
        so there is a visible goal whether or not an errand is running."""
        right = c.Screen.WIDTH - 10
        active_quests = quest_system.active_quests

        if not active_quests:
            self.chip_rects = []
            bottom = self._draw_idle_pill(right, top)
            self._draw_milestone_chip(right, bottom + self.CHIP_GAP, record)
            return

        if self.collapsed:
            bottom = self._draw_collapsed_pill(right, top, len(active_quests))
            self.chip_rects = []
            self._draw_milestone_chip(right, bottom + self.CHIP_GAP, record)
            return

        tracked = self._resolve_tracked(active_quests)
        others = [q for q in active_quests if q is not tracked]

        card_rect = pygame.Rect(right - self.WIDTH, top, self.WIDTH, self.CARD_HEIGHT)
        self._draw_tracked_card(card_rect, tracked)

        self.collapse_button_rect = pygame.Rect(card_rect.right - 24, card_rect.y + 6, 18, 18)
        self._draw_chevron(self.collapse_button_rect, expanded=True)

        self.chip_rects = []
        mouse_pos = pygame.mouse.get_pos()
        chip_y = card_rect.bottom + 8
        for quest in others:
            label_text = quest.npc_name or quest.item_name
            label = c.Fonts.small.render(label_text, True, c.Colors.WHITE)
            chip_width = min(self.WIDTH, label.get_width() + 24)
            chip_rect = pygame.Rect(right - chip_width, chip_y, chip_width, self.CHIP_HEIGHT)
            widgets.draw_slot(self.screen, chip_rect, hovered=chip_rect.collidepoint(mouse_pos))
            self.screen.blit(label, (chip_rect.x + 12, chip_rect.centery - label.get_height() // 2))
            self.chip_rects.append((chip_rect, quest))
            chip_y += self.CHIP_HEIGHT + self.CHIP_GAP

        self._draw_milestone_chip(right, chip_y, record)

    def _draw_collapsed_pill(self, right: int, top: int, count: int) -> int:
        text = c.Fonts.button.render(f"Quests ({count})", True, c.Colors.WHITE)
        width = text.get_width() + 44
        rect = pygame.Rect(right - width, top, width, 30)
        widgets.draw_panel(self.screen, rect)
        self.screen.blit(text, (rect.x + 12, rect.centery - text.get_height() // 2))
        self.collapse_button_rect = rect
        self._draw_chevron(pygame.Rect(rect.right - 26, rect.y + 7, 18, 18), expanded=False)
        return rect.bottom

    def _draw_idle_pill(self, right: int, top: int) -> int:
        """One slim line when no errand is running: the tracker is never blank, and the
        arrow the HUD draws is meanwhile pointing at the nearest notice board."""
        self.collapse_button_rect = pygame.Rect(0, 0, 0, 0)
        text = c.Fonts.small.render("No task. Find a notice board.", True, c.Colors.MUTED)
        rect = pygame.Rect(right - (text.get_width() + 24), top, text.get_width() + 24, 26)
        widgets.draw_panel(self.screen, rect)
        self.screen.blit(text, (rect.x + 12, rect.centery - text.get_height() // 2))
        return rect.bottom

    def _draw_milestone_chip(self, right: int, y: int, record: Record | None):
        """The quest tally as a goal: how many handed in, and the next one that pays a
        cache. Drawn under whatever the tracker showed above, small and muted."""
        if record is None:
            return
        progress = record.next_quest_reward()
        if progress is None:
            return
        done, target, rarity = progress
        text = c.Fonts.small.render(f"Quests {done}/{target} to a {rarity} cache", True, c.Colors.MUTED)
        rect = pygame.Rect(right - (text.get_width() + 24), y, text.get_width() + 24, 24)
        widgets.draw_panel(self.screen, rect)
        self.screen.blit(text, (rect.x + 12, rect.centery - text.get_height() // 2))

    def _draw_chevron(self, rect: pygame.Rect, expanded: bool):
        cx, cy = rect.center
        if expanded:
            points = [(cx - 5, cy - 2), (cx, cy + 3), (cx + 5, cy - 2)]
        else:
            points = [(cx - 5, cy + 2), (cx, cy - 3), (cx + 5, cy + 2)]
        pygame.draw.lines(self.screen, c.Colors.MUTED, False, points, 2)

    def _draw_tracked_card(self, rect: pygame.Rect, quest: Quest):
        highlighted = pygame.time.get_ticks() < self.highlight_until
        border = c.Colors.ACCENT if highlighted else c.Colors.BORDER
        widgets.draw_panel(self.screen, rect, border=border, border_w=3 if highlighted else 2)

        pad = 12
        text_x = rect.x + pad
        y = rect.y + pad

        title = c.Fonts.heading.render(quest.npc_name, True, c.Colors.YELLOW)
        self.screen.blit(title, (text_x, y))
        y += title.get_height() + 6

        max_width = rect.width - 2 * pad - 24  # leave room for the collapse chevron
        for line in widgets.wrap_text(quest.description, c.Fonts.small, max_width)[:2]:
            line_surface = c.Fonts.small.render(line, True, c.Colors.WHITE)
            self.screen.blit(line_surface, (text_x, y))
            y += line_surface.get_height() + 2

        progress = c.Fonts.small.render(_progress_line(quest), True, c.Colors.ACCENT)
        self.screen.blit(progress, (text_x, rect.bottom - pad - progress.get_height()))
