import queue
import threading
import time
from queue import Queue

from llama_cpp import Llama

import core.constants as c

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

        self.active_requests = 0
        self.queued_requests = 0

    def start(self):
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.worker_thread.start()

    def get_active_task_count(self):
        with self.lock:
            return self.active_requests + self.queued_requests

    def _process_queue(self):
        while self.running:
            try:
                # Get next request with timeout to allow checking self.running
                request = self.request_queue.get(timeout=0.1)

                with self.lock:
                    self.queued_requests -= 1
                    self.active_requests += 1

                try:
                    result = request["func"]()
                    request["result_queue"].put(("success", result))
                except Exception as e:
                    request["result_queue"].put(("error", str(e)))
                finally:
                    with self.lock:
                        self.active_requests -= 1
                    self.request_queue.task_done()

            except queue.Empty:
                continue

    def generate_response(self, prompt: str, system_prompt: str) -> str:
        result_queue = Queue()

        def request_func():
            return generate_response_internal(prompt, system_prompt)

        with self.lock:
            self.queued_requests += 1

        self.request_queue.put({"func": request_func, "result_queue": result_queue})

        status, result = result_queue.get()
        if status == "error":
            raise Exception(f"LLM error: {result}")
        return result

    def generate_response_stream(self, prompt: str, system_prompt: str):
        result_queue = Queue()
        stream_queue = Queue()

        def request_func():
            for partial in generate_response_stream_internal(prompt, system_prompt):
                stream_queue.put(("chunk", partial))
            stream_queue.put(("done", None))
            return None

        with self.lock:
            self.queued_requests += 1

        self.request_queue.put({"func": request_func, "result_queue": result_queue})

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
                    model_path="./models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
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


def generate_response_queued(prompt, system_prompt, log):
    print(f"~~~ LLM query : {log}")
    return get_llm_queue().generate_response(prompt, system_prompt)


def generate_response_stream_queued(prompt, system_prompt, log):
    print(f"~~~ LLM stream query : {log}")
    yield from get_llm_queue().generate_response_stream(prompt, system_prompt)


def generate_response_internal(prompt, system_prompt):
    llm.reset()
    response = llm(
        prompt=_format_prompt(prompt, system_prompt),
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stop=["<|im_end|>", "<|im_start|>"],
    )

    generated_text = response.get("choices", [{}])[0].get("text", "").strip()
    generated_text = generated_text.translate(CHAR_FILTER).strip("\n")

    if "\n" in generated_text:
        generated_text = generated_text.split("\n", 1)[0].strip()

    return generated_text


def generate_response_stream_internal(prompt, system_prompt):
    llm.reset()
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
    for output in stream:
        new_token = output.get("choices", [{}])[0].get("text", "")

        if new_token:
            started = True
        if started and new_token == "\n":
            break

        accumulated_text += new_token
        yield accumulated_text.translate(CHAR_FILTER)
