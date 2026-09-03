"""Sample what the world would roll, so a spawn change is a table rather than an opinion.

`pick_monster_kind` is a pure function of distance from the centre, which makes the whole
difficulty curve something you can print. Run it, change the weights, run it again, and
the two tables are the before and after.

    uv run python scripts/verify/spawn_rates.py [--samples 20000]
"""

import argparse
import os
import sys
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness

BANDS = (0, 1500, 3000, 6000, 10000, 16000, 24000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--min-share", type=float, default=0.5, help="hide kinds under this %")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(os.environ.get("RPG_AI_SRC", harness.REPO / "src"))))
    import core.constants as c
    from game.entities.monsters import pick_monster_kind

    names = [kind.name for kind in c.MONSTER_KINDS]
    width = max(len(n) for n in names) + 2

    header = "distance".ljust(width) + "".join(f"{band:>8}" for band in BANDS)
    print(header)
    print("-" * len(header))

    rolls = {band: Counter(pick_monster_kind(float(band)).name for _ in range(args.samples)) for band in BANDS}
    for name in names:
        shares = [100.0 * rolls[band][name] / args.samples for band in BANDS]
        if max(shares) < args.min_share:
            continue
        print(name.ljust(width) + "".join(f"{share:7.1f}%" for share in shares))

    print("\nkinds available")
    print("-" * len(header))
    for band in BANDS:
        available = [kind.name for kind in c.MONSTER_KINDS if band >= kind.min_distance]
        print(f"{band:>8}: {len(available)} kinds")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
