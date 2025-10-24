import random
import colorsys

def random_color():
    h = random.random()
    s = 0.6 + 0.4 * random.random()  # moderate to high saturation
    l = 0.5 + 0.2 * random.random()  # mid to bright
    r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
    return (r, g, b)