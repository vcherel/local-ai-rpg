import colorsys
import random

import constants as c

def random_color():
    h = random.random()
    s = 0.3 + 0.2 * random.random()
    l = 0.4 + 0.2 * random.random()
    r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
    return (r, g, b)

def random_coordinates():
    return tuple(random.randint(0, c.Game.WORLD_SIZE) for _ in range(2))
