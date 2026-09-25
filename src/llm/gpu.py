"""Taking turns on one card.

The 4 GB card holds one copy of the model. A second load while another process has it
fails, and a load that fits beside it only by spilling layers to the CPU measures a model
nobody plays. So a script that loads the model on purpose (`uv run doctor`, the evals in
`scripts/eval/`) waits here first: for the lock every such script takes, and then for the
card to hold no compute process at all, which is what the game running, or anything else
on the machine, looks like from outside.

The game itself does not wait. A player is never held on the loading screen by a
measurement, and `llm/fit.py` already sizes its load to whatever room is left.
"""

import contextlib
import fcntl
import os
import shutil
import subprocess
import time

LOCK_PATH = "./saves/gpu.lock"
POLL_S = 5


def _compute_pids() -> list[str]:
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [pid.strip() for pid in out.splitlines() if pid.strip()]


@contextlib.contextmanager
def claimed(what: str):
    """Hold the card for `what` until the block ends, waiting for it first."""
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with open(LOCK_PATH, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            print(f"Waiting for the GPU, held by {lock.read().strip() or 'another process'}.", flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
        said = False
        while pids := _compute_pids():
            if not said:
                print(f"Waiting for the GPU, in use by pid {', '.join(pids)}.", flush=True)
                said = True
            time.sleep(POLL_S)
        lock.seek(0)
        lock.truncate()
        lock.write(f"pid {os.getpid()}: {what}\n")
        lock.flush()
        try:
            yield
        finally:
            lock.seek(0)
            lock.truncate()
