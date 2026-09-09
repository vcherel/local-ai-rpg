"""`uv run fetch-model`: put the weights the game talks through in `models/`.

Separate from the game on purpose. The game plays without a model (`llm/offline.py`), so
nothing should ever pull three gigabytes down because somebody double-clicked play; this is
the one place that download is asked for, and it says what it is doing while it happens.

Resumable: a part file is kept beside the target and continued with a Range request, since
the whole point of a progress bar is that the connection it is measuring can drop.
"""

import os
import shutil
import sys
import time
import urllib.error
import urllib.request

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import core.constants as c

CHUNK = 1 << 20
USER_AGENT = "rpg-ai fetch-model"


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _progress(done: int, total: int, started: float):
    width = 34
    rate = done / max(time.monotonic() - started, 0.001)
    if total:
        filled = int(width * done / total)
        bar = "#" * filled + "." * (width - filled)
        line = f"\r[{bar}] {done * 100 // total:3d}%  {_human(done)} / {_human(total)}  {_human(rate)}/s"
    else:
        line = f"\r{_human(done)}  {_human(rate)}/s"
    sys.stdout.write(line)
    sys.stdout.flush()


def download(url: str, target: str) -> bool:
    part = target + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if have:
        request.add_header("Range", f"bytes={have}-")
        print(f"Resuming at {_human(have)}.")

    try:
        response = urllib.request.urlopen(request)
    except urllib.error.URLError as error:
        print(f"Could not reach the download: {error}")
        return False

    # A server that ignored the Range header sends the whole file back, so the part file is
    # started again rather than appended to and silently corrupted.
    resumed = response.status == 206
    if have and not resumed:
        have = 0
    total = int(response.headers.get("Content-Length", 0)) + (have if resumed else 0)

    started = time.monotonic()
    with open(part, "ab" if resumed else "wb") as handle, response:
        done = have
        while chunk := response.read(CHUNK):
            handle.write(chunk)
            done += len(chunk)
            _progress(done, total, started)
    print()

    if total and os.path.getsize(part) != total:
        print("The download stopped short. Run it again to resume.")
        return False

    shutil.move(part, target)
    return True


def main() -> int:
    target = c.Hyperparameters.MODEL_PATH
    if os.path.isfile(target):
        print(f"{target} is already here ({_human(os.path.getsize(target))}). Nothing to do.")
        return 0

    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    print(f"Downloading {os.path.basename(target)} (about 2.9GB) into {os.path.dirname(target)}/")
    if not download(c.Hyperparameters.MODEL_URL, target):
        return 1

    print(f"Done. {target}")
    print("Run 'uv run doctor' to check the game can actually run it on this machine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
