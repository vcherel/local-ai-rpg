"""Draw a fixed set of frames to PNG, so a rendering change is something you can look at.

Every shot is bit-identical between two runs of the same tree, bodies and settlements
included, so all of them are worth diffing. What buys that is elsewhere: a building is
named off its village's chunk and its slot rather than off a fresh uuid, so the wing it
grows, the roof it wears and the shove its footprint gives its neighbour are the same in
every process (`game/entities/village_generation.py`).

The spots are still absolute rather than relative to the spawn, which is what keeps a shot
framed on the same ground when the spawn point itself moves for an unrelated reason.

    uv run python scripts/verify/render.py --out /tmp/shots
"""

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness

# name, absolute (x, y), frames to settle, bodies left in frame, stable enough to diff.
SHOTS = (
    ("wilderness", (6500, 5000), 120, False, True),
    ("wilderness_night", (6500, 5000), 120, False, True),
    ("deep", (16500, 11500), 120, False, True),
    ("village", (14574, 13467), 180, False, True),
    ("village_night", (14574, 13467), 180, False, True),
    ("town_people", (2500, 2500), 120, True, True),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=harness.SEED)
    parser.add_argument("--only", help="render just the shot with this name")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    import pygame

    game, clock = harness.boot(seed=args.seed)

    # After the boot: `src` goes on the path there.
    import core.constants as c

    for name, (x, y), settle, people, _stable in SHOTS:
        if args.only and name != args.only:
            continue
        game.player.x, game.player.y = x, y
        # Night is a phase of the day/night clock, not a flag: wind it round rather than
        # setting one, so everything that reads darkness reads the number it would in play.
        game.world.daynight.elapsed_ms = c.DayNight.CYCLE_LENGTH_MS * (0.75 if name.endswith("_night") else 0.0)
        game.world.prepare(game.player)
        harness.step(game, clock, settle)
        if not people:
            game.world.npcs.clear()
            game.world.monsters.clear()
            game._draw_frame()
        pygame.image.save(game.screen, str(args.out / f"{name}.png"))
        print(f"wrote {args.out / f'{name}.png'}")

    game.world.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
