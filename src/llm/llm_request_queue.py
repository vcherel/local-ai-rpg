from queue import Queue
import threading
from llama_cpp import Llama
import time

import core.constants as c

class LLMRequestQueue:
    """Manages sequential LLM requests to prevent concurrent access"""
    
    def __init__(self, llm):
        self.llm = llm
        self.request_queue = Queue()
        self.callback_queue = Queue()  # For main-thread callbacks
        self.worker_thread = None
        self.running = False
        self.lock = threading.Lock()
        
        # Task tracking
        self.active_requests = 0  # Number of requests being processed
        self.queued_requests = 0  # Number of requests waiting in queue
    
    def start(self):
        """Start the worker thread"""
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.worker_thread.start()
    
    def get_active_task_count(self):
        """Get total number of active + queued requests"""
        with self.lock:
            return self.active_requests + self.queued_requests
    
    def get_queue_status(self):
        """Get detailed queue status"""
        with self.lock:
            return {
                'active': self.active_requests,
                'queued': self.queued_requests,
                'total': self.active_requests + self.queued_requests
            }
    
    def _process_queue(self):
        """Worker thread that processes LLM requests sequentially"""
        while self.running:
            try:
                # Get next request with timeout to allow checking self.running
                request = self.request_queue.get(timeout=0.1)
                
                # Update counters
                with self.lock:
                    self.queued_requests -= 1
                    self.active_requests += 1
                
                # Execute the request
                try:
                    result = request['func']()
                    request['result_queue'].put(('success', result))
                except Exception as e:
                    request['result_queue'].put(('error', str(e)))
                finally:
                    # Always decrement active counter
                    with self.lock:
                        self.active_requests -= 1
                    self.request_queue.task_done()
                    
            except:
                # Queue is empty, continue loop
                continue
    
    def generate_response(self, prompt: str, system_prompt: str) -> str:
        """
        Queue a blocking LLM request.
        Returns the response when complete.
        """
        result_queue = Queue()
        
        def request_func():
            return generate_response_internal(prompt, system_prompt)
        
        # Increment queued counter
        with self.lock:
            self.queued_requests += 1
        
        self.request_queue.put({
            'func': request_func,
            'result_queue': result_queue
        })
        
        # Wait for result
        status, result = result_queue.get()
        if status == 'error':
            raise Exception(f"LLM error: {result}")
        return result
    
    def generate_response_stream(self, prompt: str, system_prompt: str):
        """
        Queue a streaming LLM request.
        Yields accumulated text as it's generated.
        """
        result_queue = Queue()
        stream_queue = Queue()
        
        def request_func():
            # Generate streaming response
            for partial in generate_response_stream_internal(prompt, system_prompt):
                stream_queue.put(('chunk', partial))
            stream_queue.put(('done', None))
            return None
        
        # Increment queued counter
        with self.lock:
            self.queued_requests += 1
        
        # Queue the request
        self.request_queue.put({
            'func': request_func,
            'result_queue': result_queue
        })
        
        # Yield empty string immediately so UI doesn't block
        yield ""
        
        # Yield chunks as they arrive
        while True:
            status, data = stream_queue.get()
            if status == 'done':
                break
            yield data

# Global instance
llm_queue = None
llm = None
_init_lock = threading.Lock()

def get_llm_queue():
    """Get or initialize the global LLM queue"""
    global llm_queue, llm
    if llm_queue is None:
        with _init_lock:
            # Double-check pattern
            if llm_queue is None:
                llm = Llama(
                    model_path="./models/LFM2-2.6B-Q4_0.gguf",
                    n_gpu_layers=c.Hyperparameters.GPU_LAYERS,
                    verbose=False,
                    n_ctx=c.Hyperparameters.CONTEXT_SIZE,
                    flash_attn=True,
                    use_mlock=True,
                    n_threads=8,
                    seed=int(time.time() * 1000) % (2**31)
                )
                llm_queue = LLMRequestQueue(llm)
                llm_queue.start()
    return llm_queue

def get_llm_task_count():
    """Get number of active LLM tasks"""
    return get_llm_queue().get_active_task_count()

def generate_response_queued(prompt, system_prompt, log):
    print(f"~~~ LLM query : {log}")
    return get_llm_queue().generate_response(prompt, system_prompt)

def generate_response_stream_queued(prompt, system_prompt, log):
    print(f"~~~ LLM stream query : {log}")
    yield from get_llm_queue().generate_response_stream(prompt, system_prompt)

def generate_response_internal(prompt, system_prompt):
    formatted_prompt = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    
    llm.reset()
    response = llm(
        prompt=formatted_prompt,
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stop=["<|im_end|>", "<|im_start|>"]
    )
    
    generated_text = response.get("choices", [{}])[0].get("text", "").strip()
    generated_text = generated_text.translate(str.maketrans('', '', '"«»'))
    generated_text = generated_text.strip('\n')
    
    if '\n' in generated_text:
        generated_text = generated_text.split('\n', 1)[0].strip()
    
    return generated_text

CHAR_FILTER = str.maketrans('', '', '"«»')
def generate_response_stream_internal(prompt, system_prompt):
    formatted_prompt = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    
    llm.reset()
    stream = llm(
        prompt=formatted_prompt,
        max_tokens=c.Hyperparameters.MAX_TOKENS,
        temperature=c.Hyperparameters.TEMPERATURE,
        repeat_penalty=c.Hyperparameters.REPETITION_PENALTY,
        stream=True,
        stop=["<|im_end|>", "<|im_start|>"]
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
