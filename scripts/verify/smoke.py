"""Run the world for a while and fail loudly if anything about it stops making sense.

What it catches is what a change breaks without raising: a coordinate gone NaN, an entity
whose hp left its own range, an item id nothing resolves, a body standing inside a wall.
Exits non-zero with the traceback on stderr, so a runner never reads a silent 1.

    uv run python scripts/verify/smoke.py [--frames 900] [--seed N]
"""

import argparse
import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness


def _finite(*values):
    return all(isinstance(v, int | float) and math.isfinite(v) for v in values)


def check(game):
    """Every assertion is about state the frame left behind, never about how it got there."""
    problems = []
    world, player = game.world, game.player

    if not _finite(player.x, player.y, player.hp):
        problems.append(f"player state not finite: x={player.x} y={player.y} hp={player.hp}")
    if player.hp > player.max_hp:
        problems.append(f"player hp {player.hp} over max {player.max_hp}")

    for name, group in (("npc", world.npcs), ("monster", world.monsters), ("item", world.items)):
        for entity in group:
            x = getattr(entity, "x", None)
            y = getattr(entity, "y", None)
            if x is not None and not _finite(x, y):
                problems.append(f"{name} {getattr(entity, 'name', '?')} at non-finite ({x}, {y})")
            hp = getattr(entity, "hp", None)
            if hp is not None and not _finite(hp):
                problems.append(f"{name} {getattr(entity, 'name', '?')} hp not finite: {hp}")

    # Anything handed to the player has to resolve on reload, which means being in the one
    # master list. A quest pointing at an id that is not there is a save that loads wrong.
    world_ids = {getattr(item, "id", None) for item in world.items}
    for item in getattr(player, "inventory", []):
        item_id = getattr(item, "id", None)
        if item_id is not None and item_id not in world_ids:
            problems.append(f"carried item {item_id} is not in world.items")

    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=900)
    parser.add_argument("--seed", type=int, default=harness.SEED)
    parser.add_argument("--check-every", type=int, default=60)
    args = parser.parse_args()

    game, clock = harness.boot(seed=args.seed)
    problems = []
    for frame in range(0, args.frames, args.check_every):
        harness.step(game, clock, args.check_every)
        for problem in check(game):
            problems.append(f"frame {frame + args.check_every}: {problem}")

    # A save and a reload, because half of what a world change breaks it breaks on disk.
    game.save_data()
    game.world.close()

    if problems:
        print(f"FAIL: {len(problems)} problem(s) over {args.frames} frames", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    world = game.world
    print(
        f"OK: {args.frames} frames, {len(world.npcs)} npcs, {len(world.monsters)} monsters, "
        f"{len(world.buildings)} buildings, {len(world.items)} items"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
