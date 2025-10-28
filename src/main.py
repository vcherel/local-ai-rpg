import pygame

import core.constants as c
from core.save import SaveSystem
from game import Game
from llm.llm_request_queue import get_llm_queue
from ui.main_menu import run_main_menu


# Initialize Pygame
pygame.init()
screen = pygame.display.set_mode((c.Screen.WIDTH, c.Screen.HEIGHT))
clock = pygame.time.Clock()

# Initialize LLM queue
get_llm_queue()

# Initialize memory
save_system = SaveSystem()

# Show main menu
if run_main_menu(screen, clock, save_system):
    # Start the game
    game = Game(screen, clock, save_system)
    game.run()
