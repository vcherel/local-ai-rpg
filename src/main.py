import sys

import pygame

import core.constants as c
from core.save import SaveSystem
from game.game import Game
from llm.llm_request_queue import get_llm_queue
from ui.menus.main_menu import run_main_menu

pygame.init()
screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT))
clock = pygame.time.Clock()
c.Fonts = c.Fonts.load()

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
