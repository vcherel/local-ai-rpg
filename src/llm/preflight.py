"""Finding out whether this install can generate, without dying in the attempt.

A CUDA failure is not an exception. llama.cpp writes a line and calls `abort()`, which
takes the process it happens in, so a game that finds out by asking for its first line of
dialogue does not fall back to the written bank: it disappears, mid-village.

`blocking_warning` is what the game reads, and it costs nothing. The build states which
cards it carries kernels for (`ARCHS = 750`) and the driver states which card is here: a
build made for another GPU leaves its PTX to be translated by the driver, and a driver
older than the toolkit that wrote it refuses, aborting on the first kernel. That is the
whole failure, caught in milliseconds and answered with the command that fixes it. The
verdict `doctor` last wrote is read here too, since a check already paid for is free.

`verify` is the thorough one and belongs to `doctor` alone: a whole model load and one
token, in a subprocess, where an abort kills something that can be survived. The game
never runs it. A launch is not the place to spend a model load proving a model loads.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import core.constants as c
from llm import fit

# `native` rather than a number: a build carrying one card's cubins and no other loads,
# allocates, reports offload available and then aborts on the first kernel launch, which is
# a healthy-looking install that cannot answer. nvcc reads the card that is in the machine,
# so the command is copied rather than edited. Only a CUDA older than 11.5 needs the number,
# which is why `build_hint` prints the card's own underneath.
BUILD_COMMAND = (
    'CMAKE_ARGS="-DGGML_CUDA=1 -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc '
    '-DCMAKE_CUDA_ARCHITECTURES={arch}" uv pip install llama-cpp-python --force-reinstall --no-cache-dir'
)

PATH = "./saves/llm_probe.json"
PROBE_TIMEOUT_S = 300

# One load and one token, on the settings the game itself is about to use. `verbose=True`
# is load-bearing: with it off, llama-cpp-python installs a log callback that swallows
# ggml's own output, and `CUDA error: <what>` is one of the lines it swallows. The reason
# would be gone and only the backtrace would arrive, which is a report saying nothing.
PROBE = """
import sys
from llama_cpp import Llama

llm = Llama(
    model_path=sys.argv[1],
    n_gpu_layers=int(sys.argv[2]),
    n_ctx=int(sys.argv[3]),
    flash_attn=True,
    verbose=True,
)
llm("Hi", max_tokens=1)
"""


def build_hint() -> str:
    hint = BUILD_COMMAND.format(arch="native")
    cap = fit.compute_cap()
    if cap:
        here = cap.replace(".", "")
        hint += f"\n        (`native` is this card's {here}. A CUDA older than 11.5 wants that number instead.)"
    return hint


def system_info() -> str:
    """llama.cpp's own one-line summary of the build, or empty when it will not load.

    Cheap: it reports what was compiled in and never launches a kernel. The CUDA backend
    writes its banner to stderr from C on import, which is held shut for the length of it.
    """
    if importlib.util.find_spec("llama_cpp") is None:
        return ""
    try:
        with open(os.devnull, "w") as quiet, contextlib.redirect_stderr(quiet):
            stderr_fd = os.dup(2)
            os.dup2(quiet.fileno(), 2)
            try:
                import llama_cpp

                return llama_cpp.llama_print_system_info().decode("utf-8", "replace")
            finally:
                os.dup2(stderr_fd, 2)
                os.close(stderr_fd)
    except Exception:
        return ""


def build_archs(info: str = "") -> list[int]:
    """The compute capabilities this build carries kernels for, as `86` rather than `860`.

    The line is `CUDA : ARCHS = 750 | USE_GRAPHS = 1 | ...`, and the field is a list when
    the build was made for several cards. An older llama.cpp does not print it at all,
    which is an empty list and no claim either way.
    """
    field = ""
    for part in info.split("|"):
        _, sep, value = part.partition("ARCHS =")
        if sep:
            field = value
            break
    archs = []
    for token in field.replace(";", " ").replace(",", " ").split():
        if token.isdigit():
            archs.append(int(token) // 10 if len(token) > 2 else int(token))
    return sorted(set(archs))


def arch_warning() -> str:
    """Why this build will not run on this card, in one sentence, or empty when it will."""
    cap = fit.compute_cap()
    archs = build_archs(system_info())
    if not cap or not archs:
        return ""
    here = int(cap.replace(".", ""))
    if here in archs:
        return ""
    carried = ", ".join(f"{a // 10}.{a % 10}" for a in archs)
    return f"this build carries kernels for {carried} and the card is {cap}"


def blocking_warning() -> str:
    """Why this install must not be trusted with the model, or empty when it may be.

    Only what can be answered without loading anything: what the build says about itself,
    and what `doctor` found out last time it was run here.
    """
    warning = arch_warning()
    if warning:
        return warning
    kept = remembered(fingerprint())
    if kept is not None and not kept.get("ok"):
        return str(kept.get("reason", ""))
    return ""


def cuda_error(stderr: str) -> str:
    """The one line of a page of backtrace that says what the card refused."""
    for line in stderr.splitlines():
        if line.startswith("CUDA error:"):
            return line.partition(":")[2].strip()
    return ""


def advice(reported: str) -> str:
    """What to do about a CUDA error, by what it said."""
    # The three ways a build for another card says so: the driver having no cubin, the
    # driver refusing to translate the PTX that was shipped instead, and this module
    # having seen it coming (`arch_warning`) before either of them was reached.
    wrong_build = any(
        said in reported for said in ("no kernel image", "unsupported toolchain", "PTX", "carries kernels for")
    )
    if wrong_build:
        return f"This build was not compiled for this GPU. Rebuild it here:\n        {build_hint()}"
    if "out of memory" in reported:
        return (
            "The card has less free VRAM than the model and its context need. Close what\n"
            "        else is using the GPU, or lower `Hyperparameters.CONTEXT_SIZE`."
        )
    if reported:
        return "The card refused the work. `nvidia-smi` will say whether the driver is healthy."
    return ""


def probe(loading: fit.Plan) -> tuple[bool, str]:
    """Load the model and ask for one token, in a process this one can afford to lose."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", PROBE, c.Hyperparameters.MODEL_PATH, str(loading.n_gpu_layers), str(loading.n_ctx)],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"no answer within {PROBE_TIMEOUT_S}s"
    except (subprocess.SubprocessError, OSError):
        return True, ""  # the probe itself would not run: not the model's fault, let it try
    if done.returncode == 0:
        return True, ""
    reported = cuda_error(done.stderr)
    if reported:
        return False, f"CUDA error: {reported}"
    last = next((ln for ln in reversed(done.stderr.splitlines()) if ln.strip()), "no output")
    return False, last


def out_of_memory(reason: str) -> bool:
    """Whether the card refused for room, which is the one failure worth trying again smaller.

    Two shapes of it: the abort, when a kernel asks for memory that is not there, and the
    tidier one where the context will not allocate at all and llama-cpp-python raises,
    leaving its own exception as the last line of the probe.
    """
    said = reason.lower()
    return "out of memory" in said or "failed to create llama_context" in said or "failed to allocate" in said


def fingerprint() -> str:
    """Everything that could change the answer, so a rebuild is asked again and nothing else is.

    The plan is deliberately not part of it. What a probe finds out is whether this build
    can run kernels on this card at all, and that does not change because a browser took
    300 MiB and the context came down a notch; keeping it in the key would spend a whole
    model load every time the free VRAM moved. Fitting inside the card is `fit.py`'s job.
    """
    path = c.Hyperparameters.MODEL_PATH
    try:
        stat = os.stat(path)
        model = f"{path}:{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        model = path
    build = system_info()
    try:
        import llama_cpp

        # The build's own mtime as well as what it says about itself: a rebuild for this
        # card is the fix for the failure this check exists to catch, and it has to be
        # asked again afterwards rather than answered from the last machine's verdict.
        lib = os.path.join(os.path.dirname(llama_cpp.__file__), "lib")
        build += f":{llama_cpp.__version__}:{int(os.path.getmtime(lib))}"
    except Exception:
        pass
    return f"{model}|{build}"


def _remember(verdict: dict) -> None:
    """Written the way a save is: a whole file swapped in, never a half-written one read."""
    try:
        os.makedirs(os.path.dirname(PATH) or ".", exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=os.path.dirname(PATH) or ".", suffix=".tmp")
        with os.fdopen(handle, "w") as f:
            json.dump(verdict, f)
        os.replace(temporary, PATH)
    except OSError:
        pass


def remembered(mark: str) -> dict | None:
    try:
        with open(PATH) as f:
            verdict = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return verdict if isinstance(verdict, dict) and verdict.get("fingerprint") == mark else None


@dataclass(frozen=True)
class Verdict:
    """Whether this machine generates, and on what settings it was willing to."""

    ok: bool
    reason: str
    loading: fit.Plan


def _kept_verdict(kept: dict) -> Verdict:
    return Verdict(
        bool(kept.get("ok")),
        str(kept.get("reason", "")),
        fit.Plan(
            int(kept.get("n_ctx", c.Hyperparameters.CONTEXT_SIZE)),
            int(kept.get("n_gpu_layers", c.Hyperparameters.GPU_LAYERS)),
            str(kept.get("note", "")),
        ),
    )


def verify(again: bool = False) -> Verdict:
    """What this machine can generate on, asked once and then remembered.

    `again` forces the whole walk: `doctor` is the one thing that always pays for a fresh
    answer, so re-running it is how a machine that has been fixed says so.
    """
    mark = fingerprint()
    if not again:
        kept = remembered(mark)
        if kept is not None:
            return _kept_verdict(kept)

    rungs = fit.ladder()
    reason = ""
    for step, rung in enumerate(rungs):
        ok, reason = probe(rung)
        if ok:
            # The first rung is what was asked for, so it has nothing to explain.
            loading = fit.Plan(rung.n_ctx, rung.n_gpu_layers, rung.note if step else "")
            _remember(
                {
                    "fingerprint": mark,
                    "ok": True,
                    "reason": "",
                    "n_ctx": loading.n_ctx,
                    "n_gpu_layers": loading.n_gpu_layers,
                    "note": loading.note,
                }
            )
            return Verdict(True, "", loading)
        if not out_of_memory(reason):
            break

    _remember({"fingerprint": mark, "ok": False, "reason": reason})
    return Verdict(False, reason, rungs[0])
