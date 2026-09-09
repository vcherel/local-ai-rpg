"""Fitting the model to the card that is actually in the machine.

`CONTEXT_SIZE` and `GPU_LAYERS` are what to ask for, and what is asked for first on every
machine: nothing here is allowed to talk a card out of settings it would have run. The
arithmetic below is only ever the answer to "that was refused, what next", which is why
`ladder` starts at what was asked and `plan` is a rung rather than a verdict. Guessing is
what the estimate is bad at: the file on disk is bigger than what goes on the card, some
tensors stay behind, and a card written off on paper is a card that would have talked.

The estimate itself: what the driver says is free, minus the weights, minus what the run
needs for itself, is what the KV cache may have. The context comes down a step at a time,
and only when even the shortest will not fit do layers come off the card, since a layer on
the CPU costs far more speed than a shorter conversation does. What one token of KV cache
weighs is read out of the GGUF header rather than assumed: `MODEL_PATH` is a constant that
can be pointed at another file.
"""

from __future__ import annotations

import os
import struct
import subprocess
from dataclasses import dataclass

import core.constants as c

MB = 1 << 20


def smi(fields: str) -> str | None:
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


def _first_number(text: str | None) -> int | None:
    if not text:
        return None
    digits = "".join(ch for ch in text.splitlines()[0] if ch.isdigit())
    return int(digits) if digits else None


def free_vram_mb() -> int | None:
    """What the first card has free right now, or None when there is no card to ask.

    Free rather than total on purpose: the desktop, the browser and anything else on the
    GPU have already taken their share, and it is the remainder the model has to fit in.
    """
    return _first_number(smi("memory.free"))


# GGUF metadata is a flat list of typed key/value pairs. Only a handful of scalars are
# wanted here, and they all come before the tokenizer's arrays, which is where the file
# stops being cheap to walk: 150k strings read one length at a time.
_MAGIC = b"GGUF"
_SCALAR_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_STRING, _ARRAY = 8, 9
_WANTED = ("block_count", "attention.head_count_kv", "attention.head_count", "attention.key_length", "embedding_length")


def _read(f, fmt: str):
    size = struct.calcsize(fmt)
    raw = f.read(size)
    if len(raw) < size:
        raise EOFError
    return struct.unpack(fmt, raw)[0]


def _read_string(f) -> str:
    return f.read(_read(f, "<Q")).decode("utf-8", "replace")


def _skip_value(f, kind: int) -> None:
    if kind == _STRING:
        f.seek(_read(f, "<Q"), os.SEEK_CUR)
    elif kind == _ARRAY:
        element = _read(f, "<I")
        count = _read(f, "<Q")
        if element in _SCALAR_SIZES:
            f.seek(_SCALAR_SIZES[element] * count, os.SEEK_CUR)
        elif element == _STRING:
            for _ in range(count):
                f.seek(_read(f, "<Q"), os.SEEK_CUR)
        else:
            raise EOFError  # an array of arrays: not worth walking, give up on the header
    elif kind in _SCALAR_SIZES:
        f.seek(_SCALAR_SIZES[kind], os.SEEK_CUR)
    else:
        raise EOFError


def _header(path: str) -> dict[str, int]:
    """The architecture scalars of a GGUF file, keyed without their architecture prefix.

    Anything unexpected returns what was read so far: this is a size estimate, and a model
    whose header cannot be walked falls back to the coarse figure rather than to an error.
    """
    found: dict[str, int] = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != _MAGIC:
                return found
            _read(f, "<I")  # version
            _read(f, "<Q")  # tensor count
            for _ in range(_read(f, "<Q")):
                key = _read_string(f)
                kind = _read(f, "<I")
                name = key.partition(".")[2]
                if key.startswith("tokenizer.") or len(found) == len(_WANTED):
                    break
                if name in _WANTED and kind in (4, 5, 10, 11):
                    found[name] = _read(f, "<I" if kind in (4, 5) else "<Q")
                else:
                    _skip_value(f, kind)
    except (OSError, EOFError, struct.error):
        pass
    return found


@dataclass(frozen=True)
class Shape:
    """What the model costs per layer and per token of context, both in bytes."""

    blocks: int
    kv_per_token: int

    @property
    def kv_per_layer_token(self) -> int:
        return self.kv_per_token // max(1, self.blocks)

    def kv_mb(self, n_ctx: int) -> float:
        return self.kv_per_token * n_ctx / MB


# A 7B with grouped-query attention is 56 KiB of KV per token. Used only when the header
# would not parse, where being wrong high costs a shorter context and nothing else.
FALLBACK_KV_PER_TOKEN = 64 << 10
FALLBACK_BLOCKS = 32


def model_shape(path: str) -> Shape:
    kv = _header(path)
    blocks = kv.get("block_count", FALLBACK_BLOCKS)
    heads_kv = kv.get("attention.head_count_kv")
    head_dim = kv.get("attention.key_length")
    if head_dim is None and kv.get("attention.head_count") and kv.get("embedding_length"):
        head_dim = kv["embedding_length"] // kv["attention.head_count"]
    if not (heads_kv and head_dim):
        return Shape(blocks, FALLBACK_KV_PER_TOKEN)
    # Key and value, one f16 each, per head per layer.
    return Shape(blocks, 2 * blocks * heads_kv * head_dim * 2)


@dataclass(frozen=True)
class Plan:
    """The settings to load with, and what the card made of the ones that were asked for."""

    n_ctx: int
    n_gpu_layers: int
    note: str = ""

    @property
    def trimmed(self) -> bool:
        return bool(self.note)


def plan(path: str = "") -> Plan:
    """What this card can actually hold, as the two numbers `Llama` is given.

    No card is not a reduced plan: without CUDA the model runs off system RAM, where
    running out is an exception and a swap rather than an abort, and there is nothing here
    worth guessing about.
    """
    path = path or c.Hyperparameters.MODEL_PATH
    want_ctx = c.Hyperparameters.CONTEXT_SIZE
    want_layers = c.Hyperparameters.GPU_LAYERS
    free = free_vram_mb()
    if free is None or not os.path.isfile(path):
        return Plan(want_ctx, want_layers)

    shape = model_shape(path)
    weights_mb = os.path.getsize(path) / MB
    reserve = c.Hyperparameters.VRAM_RESERVE_MB
    budget = free - weights_mb - reserve

    # A step down rather than a halving: the cut is the smallest one that fits, since the
    # context is the whole memory a conversation has and there is no reason to give up
    # twice what the card actually wants back.
    n_ctx = want_ctx
    while n_ctx > c.Hyperparameters.MIN_CONTEXT_SIZE and shape.kv_mb(n_ctx) > budget:
        n_ctx -= c.Hyperparameters.CONTEXT_STEP
    n_ctx = max(n_ctx, c.Hyperparameters.MIN_CONTEXT_SIZE)
    card = f"{free} MiB free, {weights_mb:.0f} MiB of weights"
    if shape.kv_mb(n_ctx) <= budget:
        if n_ctx == want_ctx:
            return Plan(n_ctx, want_layers)
        return Plan(n_ctx, want_layers, f"{card}: {want_ctx} of context would not fit, using {n_ctx}")

    # Even the shortest context does not fit, so the weights themselves are what is too
    # big. Layers come off until the rest fits, each one taking its share of the KV cache
    # with it: what stays behind runs on the CPU, which is slow but is not an abort.
    per_layer = weights_mb / max(1, shape.blocks) + shape.kv_per_layer_token * n_ctx / MB
    layers = max(0, int((free - reserve) / per_layer)) if per_layer > 0 else 0
    layers = min(layers, shape.blocks)
    return Plan(
        n_ctx, layers, f"{card}: only {layers} of {shape.blocks} layers fit on the card, the rest run on the CPU"
    )


def compute_cap() -> str:
    """The first card's compute capability as nvidia-smi writes it (`8.6`), or empty.

    Asked for on its own because an old driver answers the name and the memory and refuses
    this field, and losing the number is worth less than losing the line it goes on.
    """
    out = smi("compute_cap")
    return out.splitlines()[0].strip() if out else ""


def ladder() -> list[Plan]:
    """What to try, in order, starting with everything that was asked for.

    Only a card that has actually refused the rung above ever reaches the next one, so the
    machines that fit keep their full context and the ones that do not are walked down
    rather than written off. The rungs after the estimate halve what is left, because past
    the point where the arithmetic was wrong there is nothing better to go on than trying
    something clearly smaller.
    """
    asked = Plan(c.Hyperparameters.CONTEXT_SIZE, c.Hyperparameters.GPU_LAYERS)
    rungs = [asked]
    estimated = plan()
    if (estimated.n_ctx, estimated.n_gpu_layers) != (asked.n_ctx, asked.n_gpu_layers):
        rungs.append(estimated)

    floor = c.Hyperparameters.MIN_CONTEXT_SIZE
    n_ctx = min(estimated.n_ctx, asked.n_ctx)
    while n_ctx > floor:
        n_ctx = max(floor, n_ctx // 2)
        rungs.append(Plan(n_ctx, estimated.n_gpu_layers, f"{n_ctx} of context is what this card took"))

    # Last of all, the weights themselves are what does not fit: layers come off until
    # something loads, each rung slower than the one before but still a model that answers.
    shape = model_shape(c.Hyperparameters.MODEL_PATH)
    for share in (0.75, 0.5, 0.25):
        layers = max(1, int(shape.blocks * share))
        rungs.append(Plan(floor, layers, f"only {layers} of {shape.blocks} layers fit on this card"))
    return rungs
