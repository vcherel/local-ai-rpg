"""What every eval shares: the card, the model, the ref it is compared against, the table.

An eval is a module with a `measure(runs) -> dict` that asks the real model through the
game's own code and returns its numbers, and a call to `main(name, measure)`. This file
does the rest:

- The card is claimed first (`llm.gpu.claimed`), so two sessions measuring at once take
  turns instead of failing the second load.
- With `--ref`, the ref is checked out into a throwaway worktree and measured first, then
  this tree, each in its own process under the one claim, and the two land side by side.
  The eval's cases are always this tree's, so what differs is the game code alone.
- A commit's numbers are kept in `logs/eval/<name>.cache.json`, under the commit, the eval
  file's own hash and the run count. Measuring against a ref already measured with the
  same cases reuses them, so a before and after costs one measurement, not two.
- Every case is appended to `logs/eval/<name>.jsonl` with what was asked and what came
  back, so a surprising number can be read case by case after the run.

    uv run python scripts/eval/<name>.py [--runs 3] [--ref HEAD]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULT = "RESULT "
_rows = None


def record(row: dict):
    """One case, as asked and as answered, into this eval's log."""
    _rows.write(json.dumps(row, ensure_ascii=False) + "\n")
    _rows.flush()


def _measure_here(name: str, measure, src: Path, runs: int, label: str):
    global _rows
    sys.path.insert(0, str(src))
    from core import llm_log

    # The eval keeps its own log; the game's call log is for play sessions.
    llm_log._append = lambda _entry: None
    from llm.llm_request_queue import get_llm_queue

    if get_llm_queue() is None:
        sys.exit("The model did not load: `uv run doctor` says why.")
    os.makedirs(REPO / "logs" / "eval", exist_ok=True)
    with open(REPO / "logs" / "eval" / f"{name}.jsonl", "a") as _rows:
        record({"run": label, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": runs})
        numbers = measure(runs)
    print(RESULT + json.dumps(numbers), flush=True)


def _measure_in_child(script: Path, src: Path, runs: int, label: str) -> dict:
    process = subprocess.Popen(
        [sys.executable, "-u", str(script), "--runs", str(runs), "--src", str(src), "--label", label],
        cwd=REPO,
        stdout=subprocess.PIPE,
        text=True,
    )
    numbers = None
    for line in process.stdout:
        if line.startswith(RESULT):
            numbers = json.loads(line[len(RESULT) :])
        else:
            print(f"[{label}] {line}", end="", flush=True)
    if process.wait() != 0 or numbers is None:
        sys.exit(f"The run on {label} failed.")
    return numbers


def _cache_key(script: Path, ref: str, runs: int) -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()
    cases = hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    return f"{commit}:{cases}:{runs}"


def _cached(name: str) -> tuple[Path, dict]:
    path = REPO / "logs" / "eval" / f"{name}.cache.json"
    try:
        return path, json.loads(path.read_text())
    except (OSError, ValueError):
        return path, {}


def _table(columns: dict[str, dict]):
    labels = list(columns)
    keys = list(next(iter(columns.values())))
    width = max(len(key) for key in keys)
    widths = [max(len(label), 10) for label in labels]
    print()
    print(" " * width + "  " + "  ".join(label.rjust(w) for label, w in zip(labels, widths, strict=True)))
    for key in keys:
        cells = (str(columns[label].get(key, "")).rjust(w) for label, w in zip(labels, widths, strict=True))
        print(key.ljust(width) + "  " + "  ".join(cells))


def main(name: str, measure):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3, help="how many times every case is asked")
    parser.add_argument("--ref", help="a git ref to measure first and compare against")
    parser.add_argument("--src", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--label", default="this tree", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.src is not None:
        _measure_here(name, measure, args.src, args.runs, args.label)
        return 0

    sys.path.insert(0, str(REPO / "src"))
    from llm import gpu

    script = Path(sys.argv[0]).resolve()
    columns = {}
    worktree = None
    cache_path, cache = _cached(name)
    key = _cache_key(script, args.ref, args.runs) if args.ref else None
    if key in cache:
        print(f"{args.ref}: reusing the numbers measured on {key.split(':')[0][:10]}")
        columns[args.ref] = cache[key]
    with gpu.claimed(f"scripts/eval/{name}.py"):
        try:
            if args.ref and key not in cache:
                worktree = Path(tempfile.mkdtemp(prefix="rpg-ai-eval-"))
                shutil.rmtree(worktree)
                subprocess.run(
                    ["git", "worktree", "add", "--detach", str(worktree), args.ref],
                    cwd=REPO,
                    check=True,
                    capture_output=True,
                )
                columns[args.ref] = cache[key] = _measure_in_child(script, worktree / "src", args.runs, args.ref)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache, indent=1))
            columns["this tree"] = _measure_in_child(script, REPO / "src", args.runs, "this tree")
        finally:
            if worktree is not None:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=REPO,
                    check=False,
                    capture_output=True,
                )
    _table(columns)
    print(f"\nEvery case is in logs/eval/{name}.jsonl")
    return 0
