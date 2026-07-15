"""Log every LLM generation call as JSON lines for later analysis of model quality and speed.

Each line under ``logs/llm_calls.jsonl`` is one self-contained record: the category of
call, the prompts, the response, and timing/token counts. Meant to be parsed by a script
or an AI agent later to assess response quality and generation efficiency.
"""

import json
import os
import threading
from datetime import datetime

LOG_PATH = "./logs/llm_calls.jsonl"
_lock = threading.Lock()


def log_call(
    category: str,
    system_prompt: str,
    prompt: str,
    response: str,
    duration: float,
    model_path: str,
    max_tokens: int,
    temperature: float,
    repeat_penalty: float,
    streaming: bool,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
):
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "category": category,
        "model": model_path,
        "streaming": streaming,
        "system_prompt": system_prompt,
        "prompt": prompt,
        "response": response,
        "duration_seconds": round(duration, 3),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "repeat_penalty": repeat_penalty,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens_per_second": round(completion_tokens / duration, 2) if completion_tokens and duration > 0 else None,
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with _lock, open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
