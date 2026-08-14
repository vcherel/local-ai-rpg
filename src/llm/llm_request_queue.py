import itertools
import queue
import re
import threading
import time
from queue import PriorityQueue, Queue

from llama_cpp import Llama

import core.constants as c
from core import llm_log

CHAR_FILTER = str.maketrans("", "", '"«»')

# Qwen occasionally drifts into CJK or other glyphs the UI font can't render, which
# shows up as tofu squares. Keep printable ASCII, the Latin-1/Extended-A/B accented
# letters DejaVu Sans covers, and the common smart-quote/dash/ellipsis punctuation
# LLMs favour; drop everything else so it never reaches the screen.
UNSUPPORTED_GLYPH_RE = re.compile("[^\t\n\r\x20-\x7e -ɏ‐-―‘-‟…]")

ENGLISH_ONLY_REMINDER = "Respond only in English, using standard Latin letters and punctuation."

# The player is waiting on the screen for these, so they go to the front of the queue.
# Everything else (naming, shop stock, world context, quest analysis) happens in the
# background and can wait: what it must not do is hold up the next line of dialogue.
INTERACTIVE_CATEGORIES = frozenset({"First message", "Continuing conversation"})
PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 1


def _priority_of(category: str) -> int:
    return PRIORITY_INTERACTIVE if category in INTERACTIVE_CATEGORIES else PRIORITY_BACKGROUND


def _strip_unsupported_glyphs(text: str) -> str:
    return UNSUPPORTED_GLYPH_RE.sub("", text)


def _format_prompt(prompt: str, system_prompt: str) -> str:
    system_prompt = f"{system_prompt} {ENGLISH_ONLY_REMINDER}"
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


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
            tasks = list(self.tasks.values())
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
        self.request_queue.put((_priority_of(category), next(self._sequence), request))

    def _process_queue(self):
        while self.running:
            try:
                # Get next request with timeout to allow checking self.running
                _, _, request = self.request_queue.get(timeout=0.1)

                task_id = request["task_id"]
                with self.lock:
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
        self, prompt: str, system_prompt: str, category: str, max_tokens: int = None, raw: bool = False
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

    def generate_response_stream(
        self, prompt: str, system_prompt: str, category: str, max_tokens: int = None, stop: list = None, poll=False
    ):
        result_queue = Queue()
        stream_queue = Queue()

        def request_func():
            for partial in generate_response_stream_internal(
                prompt, system_prompt, category, max_tokens=max_tokens, stop=stop
            ):
                stream_queue.put(("chunk", partial))
            stream_queue.put(("done", None))
            return None

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


def get_llm_queue():
    global llm_queue, llm
    if llm_queue is None:
        with _init_lock:
            # Double-check pattern
            if llm_queue is None:  # double-checked after acquiring the lock
                llm = Llama(
                    model_path="./models/Qwen2.5-7B-Instruct-Q2_K.gguf",
                    n_gpu_layers=c.Hyperparameters.GPU_LAYERS,
                    verbose=False,
                    n_ctx=c.Hyperparameters.CONTEXT_SIZE,
                    flash_attn=True,
                    use_mlock=True,
                    n_threads=8,
                    seed=int(time.time() * 1000) % (2**31),
                )
                llm_queue = LLMRequestQueue()
                llm_queue.start()
    return llm_queue


def get_llm_tasks():
    return get_llm_queue().get_active_tasks()


def llm_busy() -> bool:
    """True while the worker has anything running or queued. One model serves the whole
    game and a running call cannot be preempted, so a conversation opened on top of one
    would sit there with an empty box until it finished; the interaction prompt says the
    NPC is busy instead. Never forces the model to load: no queue means nothing in flight."""
    return bool(llm_queue and llm_queue.get_active_tasks())


def generate_response_queued(prompt, system_prompt, log, max_tokens=None, raw=False):
    return get_llm_queue().generate_response(prompt, system_prompt, log, max_tokens=max_tokens, raw=raw)


def generate_response_stream_queued(prompt, system_prompt, log, max_tokens=None, stop=None, poll=False):
    yield from get_llm_queue().generate_response_stream(
        prompt, system_prompt, log, max_tokens=max_tokens, stop=stop, poll=poll
    )


def generate_response_internal(prompt, system_prompt, category, max_tokens=None, raw=False):
    max_tokens = max_tokens or c.Hyperparameters.MAX_TOKENS
    start = time.monotonic()

    # No llm.reset(): keeping the KV cache lets llama_cpp skip re-evaluating the
    # shared prefix (system prompt + prior turns) on each call.
    response = llm(
        prompt=_format_prompt(prompt, system_prompt),
        max_tokens=max_tokens,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stop=["<|im_end|>", "<|im_start|>"],
    )
    duration = time.monotonic() - start

    generated_text = _strip_unsupported_glyphs(response.get("choices", [{}])[0].get("text", "").strip())

    if not raw:
        generated_text = generated_text.translate(CHAR_FILTER).strip("\n")
        if "\n" in generated_text:
            generated_text = generated_text.split("\n", 1)[0].strip()

    usage = response.get("usage", {})
    llm_log.log_call(
        category=category,
        system_prompt=system_prompt,
        prompt=prompt,
        response=generated_text,
        duration=duration,
        model_path=llm.model_path,
        max_tokens=max_tokens,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        streaming=False,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )

    return generated_text


def generate_response_stream_internal(prompt, system_prompt, category, max_tokens=None, stop=None):
    # See generate_response_internal: skip reset() to reuse the cached prefix.
    max_tokens = max_tokens or c.Hyperparameters.MAX_TOKENS
    start = time.monotonic()
    stream = llm(
        prompt=_format_prompt(prompt, system_prompt),
        max_tokens=max_tokens,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stream=True,
        stop=["<|im_end|>", "<|im_start|>"] + list(stop or []),
    )

    accumulated_text = ""
    usage = {}
    for output in stream:
        new_token = output.get("choices", [{}])[0].get("text", "")
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

    duration = time.monotonic() - start
    accumulated_text = _strip_unsupported_glyphs(accumulated_text)
    llm_log.log_call(
        category=category,
        system_prompt=system_prompt,
        prompt=prompt,
        response=accumulated_text.translate(CHAR_FILTER),
        duration=duration,
        model_path=llm.model_path,
        max_tokens=max_tokens,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        streaming=True,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )
