"""`uv run doctor`: what this machine can run, and the exact command for whatever it cannot.

The failures worth a script are the quiet ones. A CPU-only build of llama-cpp-python loads
and answers and is merely too slow to talk to; a model that half fits VRAM is unusable while
looking fine on paper; a build compiled for another card passes every check that does not
run a kernel and then aborts on the first token. Each of those is a line here rather than an
evening, the last one because the report asks for a token itself.
"""

import contextlib
import importlib.util
import os
import shutil
import subprocess
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import core.constants as c

# `native` rather than a number: a build carrying one card's cubins and no other loads,
# allocates, reports offload available and then aborts on the first kernel launch, which is
# a healthy-looking install that cannot answer. nvcc reads the card that is in the machine,
# so the command is copied rather than edited. Only a CUDA older than 11.5 needs the number,
# which is why `check_gpu` reads it off the card and `build_hint` prints it underneath.
BUILD_COMMAND = (
    'CMAKE_ARGS="-DGGML_CUDA=1 -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc '
    '-DCMAKE_CUDA_ARCHITECTURES={arch}" uv pip install llama-cpp-python --force-reinstall --no-cache-dir'
)

# What nvidia-smi said this card's compute capability is, once anything has asked.
_compute_cap = ""


def build_hint() -> str:
    hint = BUILD_COMMAND.format(arch="native")
    if _compute_cap:
        hint += f"\n        (`native` is this card's {_compute_cap}. A CUDA older than 11.5 wants that number instead.)"
    return hint


# One load and one token, on the settings the game itself uses. A CUDA failure is an abort()
# from C: it cannot be caught, only survived by not being in the process it kills.
PROBE = """
import sys
from llama_cpp import Llama

llm = Llama(
    model_path=sys.argv[1],
    n_gpu_layers=int(sys.argv[2]),
    n_ctx=int(sys.argv[3]),
    flash_attn=True,
    verbose=False,
)
llm("Hi", max_tokens=1)
"""
PROBE_TIMEOUT_S = 300

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


def _smi(fields: str) -> str | None:
    """One nvidia-smi query, or None if it would not answer."""
    try:
        done = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def check_gpu():
    """What the driver says is here. No GPU is not a failure: it is the slow mode."""
    if shutil.which("nvidia-smi") is None:
        line(WARN, "GPU", "no nvidia-smi", "Without an NVIDIA GPU the model runs on the CPU, far slower.")
        return
    global _compute_cap
    out = _smi("name,memory.total")
    if out is None:
        line(WARN, "GPU", "nvidia-smi failed")
        return

    # Asked for on its own: an old driver answers the name and the memory and refuses this
    # field, and losing the number is worth less than losing the line it goes on.
    caps = (_smi("compute_cap") or "").splitlines()
    _compute_cap = caps[0].strip().replace(".", "") if caps else ""

    for index, card in enumerate(filter(None, out.splitlines())):
        name, _, memory = card.partition(",")
        vram = int("".join(ch for ch in memory if ch.isdigit()) or 0)
        cap = caps[index].strip() if index < len(caps) else ""
        detail = f"{name.strip()}, {vram} MiB" + (f", compute {cap}" if cap else "")
        if vram >= 3500:
            line(OK, "GPU", detail)
        else:
            line(WARN, "GPU", detail, "Under 4GB: the model will not fully fit in VRAM.")


def check_binding() -> bool:
    """The one that matters. A build with no GPU offload is the silent failure.

    True means the next check is worth its minutes: the binding is here and reaches a card."""
    if importlib.util.find_spec("llama_cpp") is None:
        line(
            WARN,
            "llama-cpp-python",
            "not installed",
            f"The game plays offline without it. To build it:\n        {build_hint()}",
        )
        return False
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
        line(BAD, "llama-cpp-python", f"installed but will not load ({error})", f"Rebuild it:\n        {build_hint()}")
        return False

    if not llama_cpp.llama_supports_gpu_offload():
        line(
            BAD,
            "llama-cpp-python",
            f"{llama_cpp.__version__}, CPU only",
            f"This build answers, but too slowly to talk to. Rebuild it:\n        {build_hint()}",
        )
        return False
    line(OK, "llama-cpp-python", f"{llama_cpp.__version__}, GPU offload available")
    return True


def check_model() -> bool:
    path = c.Hyperparameters.MODEL_PATH
    if not os.path.isfile(path):
        line(WARN, "Model", f"{path} not found", "The game plays offline. Run `uv run fetch-model` for AI dialogue.")
        return False
    size = os.path.getsize(path)
    if size < 1 << 30:
        line(
            BAD,
            "Model",
            f"{path}, only {size / (1 << 20):.0f}MB",
            "Looks truncated. Delete it and run `uv run fetch-model`.",
        )
        return False
    line(OK, "Model", f"{path}, {size / (1 << 30):.1f}GB")
    return True


def _cuda_failure(stderr: str) -> tuple[str, str]:
    """What the backend said, and what to do about it.

    llama.cpp prints `CUDA error: <what>` and then aborts, so the reason is one line in a
    page of backtrace. Two of them have an answer worth printing; the rest are quoted as
    they came.
    """
    reported = next((ln.partition(":")[2].strip() for ln in stderr.splitlines() if ln.startswith("CUDA error:")), "")
    if "no kernel image" in reported:
        return reported, f"This build was compiled for a different GPU. Rebuild it here:\n        {build_hint()}"
    if "out of memory" in reported:
        return reported, (
            "The card has less free VRAM than the model and its context need. Close what else\n"
            f"        is using the GPU, or lower Hyperparameters.CONTEXT_SIZE (now {c.Hyperparameters.CONTEXT_SIZE})."
        )
    if reported:
        return reported, "The card refused the work. `nvidia-smi` will say whether the driver is healthy."
    return "", ""


def check_generation() -> None:
    """The only check that runs a kernel, and the one this report used to be missing.

    Everything above can pass on a build that dies the first time the game asks for a line
    of dialogue: the weights load, the VRAM is taken, offload is reported available, and the
    failure waits for the first token. So one is asked for here, in a subprocess, because a
    CUDA error is an abort() from C that would take this report down with it.
    """
    print("        (loading the model, this takes a moment)")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            PROBE,
            c.Hyperparameters.MODEL_PATH,
            str(c.Hyperparameters.GPU_LAYERS),
            str(c.Hyperparameters.CONTEXT_SIZE),
        ],
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_S,
    )
    if probe.returncode == 0:
        line(OK, "Generation", "the model answered")
        return

    reported, fix = _cuda_failure(probe.stderr)
    if reported:
        line(BAD, "Generation", f"CUDA error: {reported}", fix)
        return
    last = next((ln for ln in reversed(probe.stderr.splitlines()) if ln.strip()), "no output")
    line(BAD, "Generation", f"the model would not answer ({last})", "The game plays offline meanwhile.")


def main() -> int:
    print("rpg-ai doctor\n")
    check_python()
    check_pygame()
    check_gpu()
    binding = check_binding()
    model = check_model()
    if binding and model:
        try:
            check_generation()
        except subprocess.TimeoutExpired:
            line(WARN, "Generation", f"no answer within {PROBE_TIMEOUT_S}s", "The card or the disk is very slow.")
    print("\nThe game runs either way: `uv run game`. Without a model, villagers speak from a written bank.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
