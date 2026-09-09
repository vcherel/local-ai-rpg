import sys
import threading

import pygame

import core.constants as c
from core.audio import get_audio
from core.music import get_music
from core.save import SaveSystem
from game.game import Game
from llm.llm_request_queue import get_llm_queue, model_available
from ui.loading_indicator import LoadingIndicator
from ui.menus.main_menu import run_main_menu


def run_loading_screen(screen, clock):
    """Draw a spinner until the session's slow start-up work is done.

    With a model, that is the Llama object pulling the 7B into VRAM, which blocks for
    several seconds; doing it on a worker thread lets the main thread keep the window
    responsive instead of showing a frozen void. Without one there is still the music to
    wait for: the pads are rendered on a thread and this is the one screen with nothing on
    it to stutter, so an install with no weights waits out the few hundred milliseconds
    here rather than under the live village behind the title.
    """
    ready = threading.Event()
    label = "Loading AI model..." if model_available() else "Preparing..."

    def load():
        # A model that will not load answers False from here on, and this is an offline
        # session after all: the pads are what it waits out instead, as it would have.
        if model_available():
            get_llm_queue()
        if not model_available():
            get_music().await_pads()
        ready.set()

    threading.Thread(target=load, daemon=True).start()

    cx = c.Screen.WIDTH // 2
    cy = c.Screen.HEIGHT // 2
    indicator = LoadingIndicator(screen, cx, cy - 20)

    while not ready.is_set():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        indicator.update()

        screen.fill(c.Colors.MENU_BACKGROUND)
        indicator.draw_spinner(18, c.Colors.ACCENT)

        text = c.Fonts.title.render(label, True, c.Colors.WHITE)
        screen.blit(text, (cx - text.get_width() // 2, cy + 30))

        pygame.display.flip()
        clock.tick(60)


def main():
    # Every pygame call on this thread lets go of the GIL and has to take it back again, and
    # a background thread doing arithmetic holds it for a whole switch interval at a time. At
    # the default 5 ms that is one sprite rotation costing 5 ms instead of 0.08, which is a
    # frame rate the model, the naming threads and the music can all halve between them. A
    # shorter slice costs those threads a little throughput and gives the frame back.
    sys.setswitchinterval(0.001)
    # Request a mono 16-bit mixer to match the procedurally generated sound buffers.
    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    # SCALED keeps the fixed layout resolution and translates mouse coordinates, so
    # fullscreen is a stretch of the same screen rather than a different one.
    screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT), pygame.SCALED | pygame.FULLSCREEN)
    clock = pygame.time.Clock()
    c.Fonts = c.Fonts.load()

    get_audio()
    # Started here rather than with the first game: the pads render on their own thread and
    # the title screen is exactly the dead time that costs nothing.
    get_music()
    run_loading_screen(screen, clock)

    while True:
        choice = run_main_menu(screen, clock)
        # One SaveSystem per session, never shared with the previous game: its background
        # threads may still be finishing, and they must not write into this game's state.
        save_system = SaveSystem()
        if choice == "new_game":
            save_system.clear()
        game = Game(screen, clock, save_system)
        game.run()
        if game.quit_app:
            break

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
