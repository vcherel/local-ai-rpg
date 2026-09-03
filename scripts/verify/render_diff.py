"""Draw the same frames on this working tree and on a git ref, and say what moved.

The point is proving a change is invisible: an optimisation that is meant to cost nothing
visually should come back "identical" on every shot. Anything else prints how many pixels
differ and leaves a diff image behind to look at.

    uv run python scripts/verify/render_diff.py [--ref HEAD] [--out /tmp/diff]

The ref is checked out into a throwaway worktree and only its `src` is used: the harness
and the shot list are always this tree's, so the comparison is of game code and nothing
else. That also means the ref does not need to contain this folder at all.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness
import render

RENDER = Path(__file__).resolve().parent / "render.py"


def render_into(out: Path, src: Path, seed: int):
    env = dict(os.environ, RPG_AI_SRC=str(src))
    result = subprocess.run(
        [sys.executable, str(RENDER), "--out", str(out), "--seed", str(seed)],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"render failed for {src}:\n{result.stdout}\n{result.stderr}")


def compare(before: Path, after: Path, out: Path):
    import numpy as np
    import pygame

    # Only the shots that come out the same twice on the same code. The rest are rendered
    # to be looked at: see the note in `render.py` about settlement layout and about where
    # a villager has got to after N frames.
    comparable = {name for name, *_rest, stable in render.SHOTS if stable}

    verdicts = []
    for shot in sorted(after.glob("*.png")):
        if shot.stem not in comparable:
            verdicts.append((shot.stem, None, "not compared, not reproducible"))
            continue
        old = before / shot.name
        if not old.exists():
            verdicts.append((shot.stem, None, "only in this tree"))
            continue
        a = pygame.surfarray.array3d(pygame.image.load(str(old))).astype(np.int16)
        b = pygame.surfarray.array3d(pygame.image.load(str(shot))).astype(np.int16)
        if a.shape != b.shape:
            verdicts.append((shot.stem, None, f"size changed {a.shape} -> {b.shape}"))
            continue
        delta = np.abs(a - b).sum(axis=2)
        changed = int((delta > 0).sum())
        if changed:
            # White where it moved, so the shape of the change is what you see first.
            mask = (delta > 0).astype(np.uint8) * 255
            surface = pygame.surfarray.make_surface(np.stack([mask] * 3, axis=2))
            pygame.image.save(surface, str(out / f"{shot.stem}_diff.png"))
            verdicts.append((shot.stem, changed, f"max channel delta {int(delta.max())}"))
        else:
            verdicts.append((shot.stem, 0, "identical"))
    return verdicts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "rpg-ai-render-diff")
    parser.add_argument("--seed", type=int, default=harness.SEED)
    args = parser.parse_args()

    before, after = args.out / "before", args.out / "after"
    for d in (before, after):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)

    worktree = Path(tempfile.mkdtemp(prefix="rpg-ai-ref-"))
    shutil.rmtree(worktree)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), args.ref],
        cwd=harness.REPO,
        check=True,
        capture_output=True,
    )
    try:
        print(f"rendering {args.ref}...")
        render_into(before, worktree / "src", args.seed)
        print("rendering working tree...")
        render_into(after, harness.REPO / "src", args.seed)
        verdicts = compare(before, after, args.out)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=harness.REPO,
            check=False,
            capture_output=True,
        )

    total = 0
    for name, changed, note in verdicts:
        print(f"{name:16} {note}" if not changed else f"{name:16} {changed} pixels changed, {note}")
        total += changed or 0
    print(f"\ndiffs in {args.out}")
    return 0 if total == 0 else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
