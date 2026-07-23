import sys
import threading

import pygame

import core.constants as c
from core.audio import get_audio
from core.save import SaveSystem
from game.game import Game
from llm.llm_request_queue import get_llm_queue
from ui.loading_indicator import LoadingIndicator
from ui.menus.main_menu import run_main_menu


def run_loading_screen(screen, clock):
    """Load the LLM model on a background thread while drawing a spinner.

    Constructing the Llama object pulls the 7B model into VRAM and blocks for
    several seconds; doing it on a worker thread lets the main thread keep the
    window responsive instead of showing a frozen void.
    """
    ready = threading.Event()

    def load():
        get_llm_queue()
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

        text = c.Fonts.title.render("Loading AI model...", True, c.Colors.WHITE)
        screen.blit(text, (cx - text.get_width() // 2, cy + 30))

        pygame.display.flip()
        clock.tick(60)


def main():
    # Request a mono 16-bit mixer to match the procedurally generated sound buffers.
    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT))
    clock = pygame.time.Clock()
    c.Fonts = c.Fonts.load()

    get_audio()
    run_loading_screen(screen, clock)

    save_system = SaveSystem()

    while True:
        if run_main_menu(screen, clock, save_system):
            game = Game(screen, clock, save_system)
            game.run()
        else:
            break

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
