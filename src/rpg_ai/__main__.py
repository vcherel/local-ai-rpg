import sys

import pygame

import core.constants as c
from core.audio import get_audio
from core.save import SaveSystem
from game.game import Game
from llm.llm_request_queue import get_llm_queue
from ui.menus.main_menu import run_main_menu


def main():
    # Request a mono 16-bit mixer to match the procedurally generated sound buffers.
    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT))
    clock = pygame.time.Clock()
    c.Fonts = c.Fonts.load()

    get_audio()
    get_llm_queue()

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
