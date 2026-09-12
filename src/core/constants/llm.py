"""The model: where the weights are, how they are sized to the card, and how they sample."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Hyperparameters:
    # The one place the weights are named. The game plays without them (llm/offline.py);
    # `fetch-model` puts them here and `doctor` reports on what it finds.
    MODEL_PATH: str = "models/Qwen2.5-7B-Instruct-Q2_K.gguf"
    MODEL_URL: str = (
        "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q2_K.gguf"
    )
    GPU_LAYERS: int = -1
    CONTEXT_SIZE: int = 8192
    # What a card too small for the two above is cut back to, and how much of it is left
    # alone for the compute buffers and the fragmentation between them (`llm/fit.py`).
    # A short conversation still reads as a conversation; an abort mid-village does not.
    # The reserve is on top of an overestimate and not beside one: the whole file is
    # counted as going onto the card when some of it never does (170MB of a Q2_K 7B stays
    # in host memory), so a number near what the compute buffers actually measure leaves
    # the slack that overestimate already provides, rather than doubling it and talking a
    # card that fits out of a context it would have run.
    MIN_CONTEXT_SIZE: int = 2048
    CONTEXT_STEP: int = 1024
    VRAM_RESERVE_MB: int = 256
    MAX_TOKENS: int = 200
    # NPC replies are asked to be one short sentence; capping them keeps a rambling
    # answer from outgrowing the dialogue box and from stalling the queue for everyone.
    DIALOGUE_MAX_TOKENS: int = 120
    TEMPERATURE: float = 0.8
    REPETITION_PENALTY: float = 1.2
