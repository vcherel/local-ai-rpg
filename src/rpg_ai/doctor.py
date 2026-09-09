"""`uv run doctor`: what this machine can run, and the exact command for whatever it cannot.

The failures worth a script are the quiet ones. A CPU-only build of llama-cpp-python loads
and answers and is merely too slow to talk to; a model that half fits VRAM is unusable while
looking fine on paper. Both of those are a line here rather than an evening.
"""

import contextlib
import importlib.util
import os
import shutil
import subprocess
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import core.constants as c

BUILD_COMMAND = (
    'CMAKE_ARGS="-DGGML_CUDA=1 -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc '
    '-DCMAKE_CUDA_ARCHITECTURES=75" uv pip install llama-cpp-python --force-reinstall --no-cache-dir'
)

OK = "  ok  "
WARN = " warn "
BAD = " bad  "


def line(mark: str, what: str, detail: str = "", fix: str = ""):
    print(f"[{mark}] {what}" + (f": {detail}" if detail else ""))
    if fix:
        print(f"        {fix}")


def check_python():
    # Nothing to fail here: the package declares 3.12 and the entry point would not exist on
    # an older one. It is printed because the first question about any of the rest is which
    # interpreter answered them.
    line(OK, "Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


def check_pygame():
    if importlib.util.find_spec("pygame") is None:
        line(BAD, "pygame", "not installed", "Run `uv sync`.")
    else:
        import pygame

        line(OK, "pygame", pygame.version.ver)


def check_gpu():
    """What the driver says is here. No GPU is not a failure: it is the slow mode."""
    if shutil.which("nvidia-smi") is None:
        line(WARN, "GPU", "no nvidia-smi", "Without an NVIDIA GPU the model runs on the CPU, far slower.")
        return
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as error:
        line(WARN, "GPU", f"nvidia-smi failed ({error})")
        return

    for card in filter(None, out.splitlines()):
        name, _, memory = card.partition(",")
        vram = int("".join(ch for ch in memory if ch.isdigit()) or 0)
        if vram >= 3500:
            line(OK, "GPU", f"{name.strip()}, {vram} MiB")
        else:
            line(WARN, "GPU", f"{name.strip()}, {vram} MiB", "Under 4GB: the model will not fully fit in VRAM.")


def check_binding():
    """The one that matters. A build with no GPU offload is the silent failure."""
    if importlib.util.find_spec("llama_cpp") is None:
        line(
            WARN,
            "llama-cpp-python",
            "not installed",
            f"The game plays offline without it. To build it:\n        {BUILD_COMMAND}",
        )
        return
    try:
        # Importing the binding starts the CUDA backend, which writes its own banner to
        # stderr from C. That is the report's own output stream, so it is held shut for the
        # length of the import: what the backend found is said here, in one line.
        with open(os.devnull, "w") as quiet, contextlib.redirect_stderr(quiet):
            stderr_fd = os.dup(2)
            os.dup2(quiet.fileno(), 2)
            try:
                import llama_cpp
            finally:
                os.dup2(stderr_fd, 2)
                os.close(stderr_fd)
    except Exception as error:
        line(BAD, "llama-cpp-python", f"installed but will not load ({error})", f"Rebuild it:\n        {BUILD_COMMAND}")
        return

    if llama_cpp.llama_supports_gpu_offload():
        line(OK, "llama-cpp-python", f"{llama_cpp.__version__}, GPU offload available")
    else:
        line(
            BAD,
            "llama-cpp-python",
            f"{llama_cpp.__version__}, CPU only",
            f"This build answers, but too slowly to talk to. Rebuild it:\n        {BUILD_COMMAND}",
        )


def check_model():
    path = c.Hyperparameters.MODEL_PATH
    if not os.path.isfile(path):
        line(WARN, "Model", f"{path} not found", "The game plays offline. Run `uv run fetch-model` for AI dialogue.")
        return
    size = os.path.getsize(path)
    if size < 1 << 30:
        line(
            BAD,
            "Model",
            f"{path}, only {size / (1 << 20):.0f}MB",
            "Looks truncated. Delete it and run `uv run fetch-model`.",
        )
    else:
        line(OK, "Model", f"{path}, {size / (1 << 30):.1f}GB")


def main() -> int:
    print("rpg-ai doctor\n")
    check_python()
    check_pygame()
    check_gpu()
    check_binding()
    check_model()
    print("\nThe game runs either way: `uv run game`. Without a model, villagers speak from a written bank.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
