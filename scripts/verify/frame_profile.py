"""Where a frame goes, headlessly.

Two readings, because they answer different questions: the split between simulating the
world and drawing it says which half to look at, and the cProfile table says what in that
half to look at. Run it before and after an optimisation; the percentiles are the number
that matters, since a stutter is the 99th and not the mean.

    uv run python scripts/verify/frame_profile.py [--frames 600] [--at wilderness]
"""

import argparse
import cProfile
import pstats
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness

PLACES = {
    "town": (0, 0),
    "wilderness": (4000, 2500),
    "deep": (14000, 9000),
}


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--warmup", type=int, default=120)
    parser.add_argument("--at", choices=sorted(PLACES), default="town")
    parser.add_argument("--seed", type=int, default=harness.SEED)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    game, clock = harness.boot(seed=args.seed)
    dx, dy = PLACES[args.at]
    harness.walk(game, dx, dy)
    # Chunks stream in over several frames; measuring those measures loading, not a frame.
    harness.step(game, clock, args.warmup)

    updates, draws = [], []
    for _ in range(args.frames):
        game.active_menu = False
        t0 = time.perf_counter()
        game._update_frame()
        t1 = time.perf_counter()
        game._draw_frame()
        t2 = time.perf_counter()
        updates.append((t1 - t0) * 1000)
        draws.append((t2 - t1) * 1000)
        clock.tick()

    totals = [u + d for u, d in zip(updates, draws, strict=True)]
    print(f"{args.at}, {args.frames} frames (ms)")
    for name, series in (("update", updates), ("draw", draws), ("frame", totals)):
        print(
            f"  {name:7} mean {sum(series) / len(series):6.2f}  p50 {percentile(series, 0.50):6.2f}"
            f"  p95 {percentile(series, 0.95):6.2f}  p99 {percentile(series, 0.99):6.2f}"
            f"  max {max(series):6.2f}"
        )
    budget = sum(1 for t in totals if t > 16.6)
    print(f"  {budget} frame(s) over 16.6 ms ({budget / len(totals):.1%})")

    profiler = cProfile.Profile()
    profiler.enable()
    harness.step(game, clock, args.frames // 4)
    profiler.disable()
    print(f"\ntop {args.top} by cumulative time")
    pstats.Stats(profiler, stream=sys.stdout).sort_stats("cumulative").print_stats(args.top)

    game.world.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
