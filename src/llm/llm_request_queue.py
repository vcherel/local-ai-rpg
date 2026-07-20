import queue
import threading
import time
from queue import Queue

from llama_cpp import Llama

import core.constants as c
from core import llm_log

CHAR_FILTER = str.maketrans("", "", '"«»')


def _format_prompt(prompt: str, system_prompt: str) -> str:
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


class LLMRequestQueue:
    def __init__(self):
        self.request_queue = Queue()
        self.worker_thread = None
        self.running = False
        self.lock = threading.Lock()

        # task_id -> {category, state ("queued"/"running"), start (monotonic)}.
        # Insertion order is FIFO, so the running task (oldest) always sorts first.
        self.tasks = {}
        self._next_task_id = 0

    def start(self):
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.worker_thread.start()

    def get_active_task_count(self):
        with self.lock:
            return len(self.tasks)

    def get_active_tasks(self):
        """Snapshot of in-flight tasks: category, state, and elapsed seconds."""
        now = time.monotonic()
        with self.lock:
            return [
                {"category": t["category"], "state": t["state"], "elapsed": now - t["start"]}
                for t in self.tasks.values()
            ]

    def _register_task(self, category):
        with self.lock:
            task_id = self._next_task_id
            self._next_task_id += 1
            self.tasks[task_id] = {"category": category, "state": "queued", "start": time.monotonic()}
        return task_id

    def _process_queue(self):
        while self.running:
            try:
                # Get next request with timeout to allow checking self.running
                request = self.request_queue.get(timeout=0.1)

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
        self.request_queue.put({"func": request_func, "result_queue": result_queue, "task_id": task_id})

        status, result = result_queue.get()
        if status == "error":
            raise Exception(f"LLM error: {result}")
        return result

    def generate_response_stream(self, prompt: str, system_prompt: str, category: str):
        result_queue = Queue()
        stream_queue = Queue()

        def request_func():
            for partial in generate_response_stream_internal(prompt, system_prompt, category):
                stream_queue.put(("chunk", partial))
            stream_queue.put(("done", None))
            return None

        task_id = self._register_task(category)
        self.request_queue.put({"func": request_func, "result_queue": result_queue, "task_id": task_id})

        # Yield empty string immediately so UI doesn't block
        yield ""

        while True:
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


def get_llm_task_count():
    return get_llm_queue().get_active_task_count()


def get_llm_tasks():
    return get_llm_queue().get_active_tasks()


def generate_response_queued(prompt, system_prompt, log, max_tokens=None, raw=False):
    return get_llm_queue().generate_response(prompt, system_prompt, log, max_tokens=max_tokens, raw=raw)


def generate_response_stream_queued(prompt, system_prompt, log):
    yield from get_llm_queue().generate_response_stream(prompt, system_prompt, log)


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

    generated_text = response.get("choices", [{}])[0].get("text", "").strip()

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


def generate_response_stream_internal(prompt, system_prompt, category):
    # See generate_response_internal: skip reset() to reuse the cached prefix.
    start = time.monotonic()
    stream = llm(
        prompt=_format_prompt(prompt, system_prompt),
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stream=True,
        stop=["<|im_end|>", "<|im_start|>"],
    )

    accumulated_text = ""
    started = False
    usage = {}
    for output in stream:
        new_token = output.get("choices", [{}])[0].get("text", "")
        usage = output.get("usage", usage)

        if new_token:
            started = True
        if started and new_token == "\n":
            break

        accumulated_text += new_token
        yield accumulated_text.translate(CHAR_FILTER)

    duration = time.monotonic() - start
    llm_log.log_call(
        category=category,
        system_prompt=system_prompt,
        prompt=prompt,
        response=accumulated_text.translate(CHAR_FILTER),
        duration=duration,
        model_path=llm.model_path,
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        streaming=True,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )
