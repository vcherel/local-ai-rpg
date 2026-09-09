"""`uv run doctor`: what this machine can run, and the exact command for whatever it cannot.

The failures worth a script are the quiet ones. A CPU-only build of llama-cpp-python loads
and answers and is merely too slow to talk to; a model that half fits VRAM is unusable while
looking fine on paper; a build compiled for another card passes every check that does not
run a kernel and then aborts on the first token. Each of those is a line here rather than an
evening: the card is measured against the model before anything is loaded, the build is
asked which GPUs it carries kernels for, and last of all a token is asked for in a
subprocess, since that answer is the only conclusive one.

The verdict of that last check is what the game reads too (`llm/preflight.py`), so running
this report is also how a machine that has been fixed says so.
"""

import importlib.util
import os
import shutil
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import core.constants as c
from llm import fit, preflight

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
    out = fit.smi("name,memory.total")
    if out is None:
        line(WARN, "GPU", "nvidia-smi failed")
        return

    caps = (fit.smi("compute_cap") or "").splitlines()
    for index, card in enumerate(filter(None, out.splitlines())):
        name, _, memory = card.partition(",")
        vram = int("".join(ch for ch in memory if ch.isdigit()) or 0)
        cap = caps[index].strip() if index < len(caps) else ""
        line(OK, "GPU", f"{name.strip()}, {vram} MiB" + (f", compute {cap}" if cap else ""))


def check_build() -> bool:
    """The one that matters. A build with no GPU offload is the silent failure.

    True means the next checks are worth their minutes: the binding is here, it reaches a
    card, and it carries kernels for the card it reached. That last one is cheap, since the
    build says so itself, and it is the difference between a five minute diagnosis and a
    sentence: a build made for another GPU leaves the driver to translate its PTX, and a
    driver older than the toolkit that wrote it refuses, aborting on the first kernel.
    """
    if importlib.util.find_spec("llama_cpp") is None:
        line(
            WARN,
            "llama-cpp-python",
            "not installed",
            f"The game plays offline without it. To build it:\n        {preflight.build_hint()}",
        )
        return False
    info = preflight.system_info()
    try:
        import llama_cpp
    except Exception as error:
        line(
            BAD,
            "llama-cpp-python",
            f"installed but will not load ({error})",
            f"Rebuild it:\n        {preflight.build_hint()}",
        )
        return False

    if not llama_cpp.llama_supports_gpu_offload():
        line(
            BAD,
            "llama-cpp-python",
            f"{llama_cpp.__version__}, CPU only",
            f"This build answers, but too slowly to talk to. Rebuild it:\n        {preflight.build_hint()}",
        )
        return False
    line(OK, "llama-cpp-python", f"{llama_cpp.__version__}, GPU offload available")

    warning = preflight.arch_warning()
    if warning:
        line(
            BAD,
            "Build target",
            warning,
            f"It will abort on the first token. Rebuild it here:\n        {preflight.build_hint()}",
        )
        return False
    archs = preflight.build_archs(info)
    if archs:
        line(OK, "Build target", "compiled for this card (" + ", ".join(f"{a // 10}.{a % 10}" for a in archs) + ")")
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
            f"{path}, only {size / (1 << 30):.1f}GB",
            "Looks truncated. Delete it and run `uv run fetch-model`.",
        )
        return False
    line(OK, "Model", f"{path}, {size / (1 << 30):.1f}GB")
    return True


def check_room() -> None:
    """What the card has, against what the full context wants. A reading, not a verdict.

    The estimate is worth printing and is not worth obeying: what a machine actually runs
    is settled by the check below, which asks the card rather than the arithmetic.
    """
    free = fit.free_vram_mb()
    if free is None:
        return
    want = c.Hyperparameters.CONTEXT_SIZE
    shape = fit.model_shape(c.Hyperparameters.MODEL_PATH)
    weights = os.path.getsize(c.Hyperparameters.MODEL_PATH) / fit.MB
    line(OK, "Room", f"{free} MiB free, {weights:.0f} of weights and {shape.kv_mb(want):.0f} of KV cache for {want}")


def check_generation() -> None:
    """The only check that runs a kernel, and the conclusive one.

    Everything above can pass on a build that dies the first time the game asks for a line
    of dialogue: the weights load, the VRAM is taken, offload is reported available, and the
    failure waits for the first token. So one is asked for here, in a subprocess, because a
    CUDA error is an abort() from C that would take this report down with it. A card that
    refuses for room is asked again smaller, which is the one failure that ends in a
    working game rather than in a rebuild. The answer is written where the game reads it,
    and asked again every time this runs.
    """
    print("        (loading the model, this takes a moment)")
    verdict = preflight.verify(again=True)
    if verdict.ok and not verdict.loading.trimmed:
        line(OK, "Generation", f"the model answered, {verdict.loading.n_ctx} of context")
        return
    if verdict.ok:
        line(WARN, "Generation", f"the model answered, {verdict.loading.note}", "Memory, not the build: it plays on.")
        return
    line(BAD, "Generation", verdict.reason, preflight.advice(verdict.reason) or "The game plays offline meanwhile.")


def main() -> int:
    print("rpg-ai doctor\n")
    check_python()
    check_pygame()
    check_gpu()
    build = check_build()
    model = check_model()
    if model:
        check_room()
        if build:
            check_generation()
    print("\nThe game runs either way: `uv run game`. Without a model, villagers speak from a written bank.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
