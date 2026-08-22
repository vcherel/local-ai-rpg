import pygame

import core.constants as c
from core.audio import play_sound
from core.music import get_music
from core.settings import get_settings
from ui import widgets
from ui.menus.base_menu import BaseMenu

BUTTON_WIDTH = 200
BUTTON_HEIGHT = 44
BUTTON_SPACING = 12


class PauseMenu(BaseMenu):
    def __init__(self, screen):
        super().__init__(screen, width=360, height=360)
        self.save_button_rect = None
        self.music_button_rect = None
        self.sound_button_rect = None
        self.quit_button_rect = None

    def _button_rects(self) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
        x = (self.width - BUTTON_WIDTH) // 2
        save = pygame.Rect(x, self.content_top + 8, BUTTON_WIDTH, BUTTON_HEIGHT)
        music = pygame.Rect(x, save.bottom + BUTTON_SPACING, BUTTON_WIDTH, BUTTON_HEIGHT)
        sound = pygame.Rect(x, music.bottom + BUTTON_SPACING, BUTTON_WIDTH, BUTTON_HEIGHT)
        quit_rect = pygame.Rect(x, sound.bottom + BUTTON_SPACING, BUTTON_WIDTH, BUTTON_HEIGHT)
        return save, music, sound, quit_rect

    @staticmethod
    def _toggle_music():
        """Flip the preference and the player together: the setting outlives the session, so
        it is written now rather than at quit, when a crash would lose it."""
        get_music().set_enabled(get_settings().toggle("music"))

    @staticmethod
    def _toggle_sound():
        """The other half of the same idea: every effect the game plays, off in one place.
        `SoundManager.play` reads the preference itself, so nothing here has to reach into
        the mixer."""
        get_settings().toggle("sound")
        play_sound("pickup")

    def handle_event(self, event, on_save=None, on_quit=None) -> bool:
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_p, pygame.K_ESCAPE):
                self.close()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            menu_x, menu_y = self.get_centered_position()
            rel = (event.pos[0] - menu_x, event.pos[1] - menu_y)
            if self.save_button_rect and self.save_button_rect.collidepoint(rel):
                if on_save:
                    on_save()
                self.close()
            elif self.music_button_rect and self.music_button_rect.collidepoint(rel):
                # The two buttons here that do not end the pause: hearing what they did is
                # the point, and closing the menu on one would hide the label that changed.
                self._toggle_music()
            elif self.sound_button_rect and self.sound_button_rect.collidepoint(rel):
                self._toggle_sound()
            elif self.quit_button_rect and self.quit_button_rect.collidepoint(rel):
                self.close()
                if on_quit:
                    on_quit()
            else:
                # Click anywhere else resumes.
                self.close()

        return True

    def draw(self):
        if not self.active:
            return

        self.draw_overlay()
        surface = self.create_menu_surface("Paused")

        rects = self._button_rects()
        self.save_button_rect, self.music_button_rect, self.sound_button_rect, self.quit_button_rect = rects
        menu_x, menu_y = self.get_centered_position()
        mouse_x, mouse_y = pygame.mouse.get_pos()

        save_hovered = self.save_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(surface, self.save_button_rect, "Save game", c.Fonts.button, hovered=save_hovered)

        music_on = bool(get_settings().get("music"))
        music_hovered = self.music_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(
            surface,
            self.music_button_rect,
            f"Music: {'On' if music_on else 'Off'}",
            c.Fonts.button,
            hovered=music_hovered,
            text_color=c.Colors.WHITE if music_on else c.Colors.MUTED,
        )

        sound_on = bool(get_settings().get("sound"))
        sound_hovered = self.sound_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(
            surface,
            self.sound_button_rect,
            f"Sound: {'On' if sound_on else 'Off'}",
            c.Fonts.button,
            hovered=sound_hovered,
            text_color=c.Colors.WHITE if sound_on else c.Colors.MUTED,
        )

        quit_hovered = self.quit_button_rect.collidepoint(mouse_x - menu_x, mouse_y - menu_y)
        widgets.draw_button(surface, self.quit_button_rect, "Quit to menu", c.Fonts.button, hovered=quit_hovered)

        self.draw_hint(surface, "P, Esc or click to resume")
        self.blit_panel(surface)
