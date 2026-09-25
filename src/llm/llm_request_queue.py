import importlib.util
import itertools
import os
import queue
import re
import threading
import time
from queue import PriorityQueue, Queue

import numpy as np

import core.constants as c
from core import llm_log
from llm import fit, offline, preflight

CHAR_FILTER = str.maketrans("", "", '"«»')

# Qwen occasionally drifts into CJK or other glyphs the UI font can't render, which
# shows up as tofu squares. Keep printable ASCII, the Latin-1/Extended-A/B accented
# letters DejaVu Sans covers, and the common smart-quote/dash/ellipsis punctuation
# LLMs favour; drop everything else so it never reaches the screen.
UNSUPPORTED_GLYPH_RE = re.compile("[^\t\n\r\x20-\x7e -ɏ‐-―‘-‟…]")

SYSTEM_OPEN = "<|im_start|>system\n"
ENGLISH_ONLY_REMINDER = "Respond only in English, using standard Latin letters and punctuation."

# The player is waiting on the screen for these, so they go to the front of the queue.
# Everything else (naming, shop stock, world context, quest analysis) happens in the
# background and can wait: what it must not do is hold up the next line of dialogue.
# The decisions read off a conversation still open, and a witness standing there making up
# their mind, are waited on the same way.
INTERACTIVE_CATEGORIES = frozenset(
    {
        "First message",
        "Continuing conversation",
        "Decide: conversation",
        "Decide: haggle",
        "Decide: parley",
        "Decide: witness",
    }
)
# Every decision's category starts with this. A decision is one pass over a prompt and no
# generation, a fraction of a second, so it never makes an NPC too busy to talk.
DECISION_PREFIX = "Decide"
# The head of the system prompt of whoever the player is standing in front of, read into the
# cache before E is pressed. Invisible: never "busy", never on the HUD, never logged.
WARM_CATEGORY = "Warm"
# How many tokens a warm reads before looking whether a line is waiting behind it, which is
# the most it can hold a first line up by (about 11.5 ms a token on the GTX 1650).
WARM_CHUNK = 16
PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 1


def _priority_of(category: str) -> int:
    return PRIORITY_INTERACTIVE if category in INTERACTIVE_CATEGORIES else PRIORITY_BACKGROUND


def _strip_unsupported_glyphs(text: str) -> str:
    return UNSUPPORTED_GLYPH_RE.sub("", text)


def _format_prompt(prompt: str, system_prompt: str) -> str:
    system_prompt = f"{system_prompt} {ENGLISH_ONLY_REMINDER}"
    return f"{SYSTEM_OPEN}{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"


class LLMRequestQueue:
    def __init__(self):
        # Priority queue, not FIFO: one model serves the whole game, so a background job
        # queued the moment a conversation closes (quest analysis) would otherwise make the
        # next NPC's first line wait for it. Ties break on arrival order.
        self.request_queue = PriorityQueue()
        self._sequence = itertools.count()
        self.worker_thread = None
        self.running = False
        self.lock = threading.Lock()

        # task_id -> {category, priority, state ("queued"/"running"), start (monotonic)}.
        self.tasks = {}
        self._next_task_id = 0
        # Set whenever something the player waits on is queued, so a warm stops for it.
        self.interactive_waiting = threading.Event()

    def start(self):
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.worker_thread.start()

    def get_active_tasks(self):
        """Snapshot of in-flight tasks: category, state, and elapsed seconds, in the order
        they will be served (the running one first, then by priority)."""
        now = time.monotonic()
        with self.lock:
            tasks = [t for t in self.tasks.values() if t["category"] != WARM_CATEGORY]
        tasks.sort(key=lambda t: (t["state"] != "running", t["priority"]))
        return [{"category": t["category"], "state": t["state"], "elapsed": now - t["start"]} for t in tasks]

    def _register_task(self, category):
        with self.lock:
            task_id = self._next_task_id
            self._next_task_id += 1
            self.tasks[task_id] = {
                "category": category,
                "priority": _priority_of(category),
                "state": "queued",
                "start": time.monotonic(),
            }
        return task_id

    def _submit(self, request: dict, category: str):
        if _priority_of(category) == PRIORITY_INTERACTIVE:
            self.interactive_waiting.set()
        self.request_queue.put((_priority_of(category), next(self._sequence), request))

    def idle(self) -> bool:
        with self.lock:
            return not self.tasks

    def warm(self, system_prompt_head: str):
        """Read the head of a system prompt into the cache, answering nothing."""
        result_queue = Queue()

        def request_func():
            return warm_internal(system_prompt_head, self.interactive_waiting)

        task_id = self._register_task(WARM_CATEGORY)
        self._submit({"func": request_func, "result_queue": result_queue, "task_id": task_id}, WARM_CATEGORY)

    def _process_queue(self):
        while self.running:
            try:
                # Get next request with timeout to allow checking self.running
                _, _, request = self.request_queue.get(timeout=0.1)

                task_id = request["task_id"]
                with self.lock:
                    if self.tasks.get(task_id, {}).get("priority") == PRIORITY_INTERACTIVE:
                        self.interactive_waiting.clear()
                    task = self.tasks.get(task_id)
                    if task is not None:
                        task["state"] = "running"
                        task["start"] = time.monotonic()

                try:
                    result = request["func"]()
                    request["result_queue"].put(("success", result))
                except Exception as e:
                    request["result_queue"].put(("error", str(e)))
                finally:
                    with self.lock:
                        self.tasks.pop(task_id, None)
                    self.request_queue.task_done()

            except queue.Empty:
                continue

    def generate_response(
        self, prompt: str, system_prompt: str, category: str, max_tokens: int | None = None, raw: bool = False
    ) -> str:
        result_queue = Queue()

        def request_func():
            return generate_response_internal(prompt, system_prompt, category, max_tokens=max_tokens, raw=raw)

        task_id = self._register_task(category)
        self._submit({"func": request_func, "result_queue": result_queue, "task_id": task_id}, category)

        status, result = result_queue.get()
        if status == "error":
            raise Exception(f"LLM error: {result}")
        return result

    def decide(self, prompt: str, system_prompt: str, category: str, n_options: int) -> dict:
        result_queue = Queue()

        def request_func():
            return decide_internal(prompt, system_prompt, n_options)

        task_id = self._register_task(category)
        self._submit({"func": request_func, "result_queue": result_queue, "task_id": task_id}, category)

        status, result = result_queue.get()
        if status == "error":
            raise Exception(f"LLM error: {result}")
        return result

    def generate_response_stream(
        self,
        prompt: str,
        system_prompt: str,
        category: str,
        max_tokens: int | None = None,
        stop: list | None = None,
        poll=False,
    ):
        result_queue = Queue()
        stream_queue = Queue()

        def request_func():
            for partial in generate_response_stream_internal(
                prompt, system_prompt, category, max_tokens=max_tokens, stop=stop
            ):
                stream_queue.put(("chunk", partial))
            stream_queue.put(("done", None))

        task_id = self._register_task(category)
        self._submit({"func": request_func, "result_queue": result_queue, "task_id": task_id}, category)

        # Yield empty string immediately so UI doesn't block
        yield ""

        while True:
            if poll:
                # Drained rather than waited on: this generator is stepped once per frame
                # from the main thread, and the worker may be busy with an earlier request
                # (a closing conversation's quest analysis, world context, shop stock).
                # Blocking here froze the whole game until that finished. None means
                # "nothing new yet", the caller simply draws another frame.
                try:
                    status, data = stream_queue.get_nowait()
                except queue.Empty:
                    yield None
                    continue
            else:
                status, data = stream_queue.get()
            if status == "done":
                break
            yield data


llm_queue = None
llm = None
_init_lock = threading.Lock()


_available = None


def model_available() -> bool:
    """Whether this install can run a model at all: the binding built and the weights on
    disk. False is a supported way to play (`llm/offline.py`), not an error, so nothing
    here raises and nothing prints; `doctor` is what explains what is missing.

    Answered once and kept: this is read on the frame path (`get_llm_tasks`), and neither
    the package nor the weights arrive part way through a session."""
    global _available
    if _available is None:
        _available = importlib.util.find_spec("llama_cpp") is not None and os.path.isfile(c.Hyperparameters.MODEL_PATH)
    return _available


def _load_model(Llama):
    """The model, on the largest settings this card takes, or None if it takes none.

    The settings are worked out rather than tried out (`llm/fit.py`): a launch may not
    spend a model load proving that a model loads. The rungs below the first are walked
    only by a machine whose load actually refused for room, which is a few seconds of
    allocation that was going to fail either way, and never happens on a card with space.
    """
    rungs = fit.ladder()
    for step, loading in enumerate(rungs):
        try:
            model = Llama(
                model_path=c.Hyperparameters.MODEL_PATH,
                n_gpu_layers=loading.n_gpu_layers,
                verbose=False,
                n_ctx=loading.n_ctx,
                flash_attn=True,
                use_mlock=True,
                n_threads=8,
                seed=int(time.time() * 1000) % (2**31),
            )
        except Exception as error:
            if step + 1 < len(rungs) and preflight.out_of_memory(str(error)):
                continue
            print(f"The model would not load: {error}")
            print("Playing offline. Run `uv run doctor` for what this machine is missing.")
            return None
        if step:
            print(f"Sizing the model to this card: {loading.note}.")
        return model
    return None


def get_llm_queue():
    """The queue, or None when the weights would not load.

    A refused load is a session that plays from the written bank, not a session that ends:
    `model_available()` is answered False from here on, so every call falls through to
    `offline.py` exactly as a clone with no weights does.

    The card aborting mid-generation cannot be caught: it is a C abort() and takes this
    process with it whatever Python does. What can be known about it beforehand costs
    nothing to ask (`preflight.blocking_warning`), so it is asked here, and a build that
    was compiled for somebody else's GPU never gets to load at all.
    """
    global llm_queue, llm, _available
    if llm_queue is None:
        with _init_lock:
            # Double-check pattern
            if llm_queue is None:  # double-checked after acquiring the lock
                # Imported here rather than at the top of the module: llama-cpp-python is an
                # optional dependency, and a clone without it still plays.
                from llama_cpp import Llama

                warning = preflight.blocking_warning()
                if warning:
                    print(f"This machine will not generate: {warning}")
                    said = preflight.advice(warning)
                    print(said if said else "Run `uv run doctor` for what this machine is missing.")
                    print("Playing offline: villagers speak from the written bank.")
                    _available = False
                    return None

                llm = _load_model(Llama)
                if llm is None:
                    _available = False
                    return None
                llm_queue = LLMRequestQueue()
                llm_queue.start()
    return llm_queue


def get_llm_tasks():
    if not model_available():
        return []
    active = get_llm_queue()
    return active.get_active_tasks() if active else []


def llm_busy() -> bool:
    """True while the worker has anything running or queued. One model serves the whole
    game and a running call cannot be preempted, so a conversation opened on top of one
    would sit there with an empty box until it finished; the interaction prompt says the
    NPC is busy instead. Never forces the model to load: no queue means nothing in flight."""
    if not llm_queue:
        return False
    return any(not task["category"].startswith(DECISION_PREFIX) for task in llm_queue.get_active_tasks())


_warmed = None


def warm_queued(key, system_prompt_head: str):
    """Read what a conversation about to open will start with, while nothing else wants the
    model. Called every frame the talk prompt shows; does nothing past the first for the same
    `key`, nothing while the queue holds anything, and never loads a model to do it."""
    global _warmed
    if llm_queue is None or key == _warmed or not llm_queue.idle():
        return
    _warmed = key
    llm_queue.warm(system_prompt_head)


def generate_response_queued(prompt, system_prompt, log, max_tokens=None, raw=False):
    active = get_llm_queue() if model_available() else None
    if active is None:
        return offline.answer(log, prompt, system_prompt)
    return active.generate_response(prompt, system_prompt, log, max_tokens=max_tokens, raw=raw)


def generate_response_stream_queued(prompt, system_prompt, log, max_tokens=None, stop=None, poll=False):
    active = get_llm_queue() if model_available() else None
    if active is None:
        yield from offline.stream(log, prompt, system_prompt)
        return
    yield from active.generate_response_stream(prompt, system_prompt, log, max_tokens=max_tokens, stop=stop, poll=poll)


def decide_queued(prompt, system_prompt, category, n_options) -> dict | None:
    """The model's leaning over `n_options` lettered answers, or None with no model to ask
    (the caller falls back to its own odds, `llm/decide.py`)."""
    active = get_llm_queue() if model_available() else None
    if active is None:
        return None
    return active.decide(prompt, system_prompt, category, n_options)


def _sampling(prompt, system_prompt, max_tokens, stop=()) -> dict:
    """The one set of arguments both generate paths hand the model."""
    return {
        "prompt": _format_prompt(prompt, system_prompt),
        "max_tokens": max_tokens,
        "temperature": c.Hyperparameters.TEMPERATURE,
        "repeat_penalty": c.Hyperparameters.REPETITION_PENALTY,
        "stop": ["<|im_end|>", "<|im_start|>", *stop],
    }


def _log(category, system_prompt, prompt, response, start, max_tokens, streaming, usage):
    llm_log.log_call(
        category=category,
        system_prompt=system_prompt,
        prompt=prompt,
        response=response,
        duration=time.monotonic() - start,
        model_path=llm.model_path,
        max_tokens=max_tokens,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        streaming=streaming,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )


def generate_response_internal(prompt, system_prompt, category, max_tokens=None, raw=False):
    max_tokens = max_tokens or c.Hyperparameters.MAX_TOKENS
    start = time.monotonic()

    # No llm.reset(): keeping the KV cache lets llama_cpp skip re-evaluating the
    # shared prefix (system prompt + prior turns) on each call.
    response = llm(**_sampling(prompt, system_prompt, max_tokens))

    generated_text = _strip_unsupported_glyphs(response["choices"][0]["text"].strip())

    if not raw:
        generated_text = generated_text.translate(CHAR_FILTER).strip("\n")
        if "\n" in generated_text:
            generated_text = generated_text.split("\n", 1)[0].strip()

    _log(category, system_prompt, prompt, generated_text, start, max_tokens, False, response.get("usage", {}))
    return generated_text


def generate_response_stream_internal(prompt, system_prompt, category, max_tokens=None, stop=None):
    # See generate_response_internal: skip reset() to reuse the cached prefix.
    max_tokens = max_tokens or c.Hyperparameters.MAX_TOKENS
    start = time.monotonic()
    stream = llm(**_sampling(prompt, system_prompt, max_tokens, stop or ()), stream=True)

    accumulated_text = ""
    usage = {}
    for output in stream:
        new_token = output["choices"][0]["text"]
        usage = output.get("usage", usage)

        # Skip the blank line the model sometimes opens with, so the first real token
        # isn't preceded by whitespace that the newline cut below would trip on.
        if not accumulated_text.strip() and not new_token.strip():
            continue

        accumulated_text += new_token
        # Everything past the first line break is the model carrying on past its reply,
        # often writing the player's next turn. Cut it here rather than trusting the
        # tokenizer to hand us a token that is exactly "\n".
        if "\n" in accumulated_text:
            accumulated_text = accumulated_text.split("\n", 1)[0]
            yield _strip_unsupported_glyphs(accumulated_text).translate(CHAR_FILTER)
            break

        yield _strip_unsupported_glyphs(accumulated_text).translate(CHAR_FILTER)

    response = _strip_unsupported_glyphs(accumulated_text).translate(CHAR_FILTER)
    _log(category, system_prompt, prompt, response, start, max_tokens, True, usage)


def _reuse_cache(tokens) -> None:
    """Keep what the cache shares with `tokens`, short of the last one, and drop the rest."""
    shared = 0
    for cached, wanted in zip(llm._input_ids, tokens, strict=False):
        if cached != wanted:
            break
        shared += 1
    keep = min(shared, len(tokens) - 1)
    if keep > 0 and llm._ctx.kv_cache_seq_rm(-1, keep, -1):
        llm.n_tokens = keep
    else:
        llm.reset()


def warm_internal(system_prompt_head, interrupted: threading.Event):
    """The head evaluated into the cache in small chunks, stopping at the first chunk boundary
    after an interactive call is queued. What was read stays: the call that follows matches
    against it like any other prefix. The head's own last token may tokenise differently
    inside the whole prompt, which costs that one token again."""
    text = SYSTEM_OPEN + system_prompt_head.rstrip()
    tokens = llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)
    if len(tokens) >= llm.n_ctx():
        return
    _reuse_cache(tokens)
    while llm.n_tokens < len(tokens) and not interrupted.is_set():
        llm.eval(tokens[llm.n_tokens : llm.n_tokens + WARM_CHUNK])


def _option_tokens(n_options: int) -> list[int]:
    """The token each answer letter is written as, first thing in the assistant's turn."""
    return [llm.tokenize(letter.encode("utf-8"), add_bos=False, special=False)[0] for letter in "ABCDEFGH"[:n_options]]


def decide_internal(prompt, system_prompt, n_options):
    """One pass over the prompt and the logits of the answer letters, with nothing sampled.

    Tokenised exactly as a completion is, and started from whatever the cache already holds
    of it, so a decision asked right after a reply over the same conversation pays only for
    the question. What it leaves in the cache is a valid prefix too: the next generation
    matches against it the same way."""
    start = time.monotonic()
    tokens = llm.tokenize(_format_prompt(prompt, system_prompt).encode("utf-8"), add_bos=False, special=True)
    if len(tokens) >= llm.n_ctx():
        raise ValueError(f"decision prompt of {len(tokens)} tokens does not fit the context")
    # At least the last token is always evaluated: its logits are the answer.
    _reuse_cache(tokens)
    keep = llm.n_tokens
    llm.eval(tokens[llm.n_tokens :])
    logits = np.ctypeslib.as_array(llm._ctx.get_logits_ith(-1), shape=(llm.n_vocab(),))
    return {
        "logits": [float(logits[token]) for token in _option_tokens(n_options)],
        "prompt_tokens": len(tokens),
        "evaluated": len(tokens) - keep,
        "duration": time.monotonic() - start,
        "model_path": llm.model_path,
    }
