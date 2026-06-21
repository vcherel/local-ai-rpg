"""Persist finished NPC conversations to readable files for later analysis.

Each conversation becomes one timestamped Markdown file under ``logs/dialogues/``,
holding the system prompt, the full transcript, and the quest outcome. The files
are meant to be re-read later to inspect what the model was told and how it replied.
"""

import os
import threading
from datetime import datetime

LOG_DIR = "./logs/dialogues"
_lock = threading.Lock()


def _safe_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum())
    return cleaned or "npc"


def write_conversation(npc, system_prompt: str, conversation) -> str | None:
    """Write a finished conversation to a new file. Returns its path, or None if empty."""
    messages = conversation.messages
    if not messages:
        return None

    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now()
    path = os.path.join(LOG_DIR, f"{now:%Y%m%d_%H%M%S}_{_safe_name(npc.name)}.md")

    lines = [
        f"# Conversation with {npc.name}",
        f"_{now:%Y-%m-%d %H:%M:%S}_",
        "",
        "## System prompt",
        "",
        system_prompt,
        "",
        "## Transcript",
        "",
    ]
    for msg in messages:
        speaker = "Player" if msg["role"] == "user" else npc.name
        lines.append(f"**{speaker}:** {msg['content']}")
        lines.append("")

    with _lock, open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def append_section(path: str | None, title: str, body: str):
    """Append a titled section to an existing conversation file (no-op if path is None)."""
    if not path:
        return
    with _lock, open(path, "a") as f:
        f.write(f"\n## {title}\n\n{body}\n")
