from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING, List

from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from core.save import SaveSystem


class NPCNameGenerator:
    def __init__(self, save_system):
        self.name_queue = queue.Queue(maxsize=1)  # Only keep 1 name ready
        self.lock = threading.Lock()
        self.save_system: SaveSystem = save_system
        self.is_generating = False
        self.used_names: List[str] = []

        self.start_generation()

    def start_generation(self):
        with self.lock:
            if self.is_generating or not self.name_queue.empty():
                return

            loaded_name: str = self.save_system.load("name", None)
            if loaded_name:
                loaded_name = loaded_name.strip()
                self.name_queue.put(loaded_name)
                self.used_names.append(loaded_name)
                self.save_system.update("name", None)
                return

            self.is_generating = True

        threading.Thread(target=self._generate_name_background, daemon=True).start()

    def _generate_name_background(self):
        context = None
        while context is None:
            context = self.save_system.load("context", None)
            if context is None:
                time.sleep(0.1)  # avoid busy waiting

        with self.lock:
            used_names = list(self.used_names)

        already_generated = (
            f" Names already generated, do not reuse any of them: {', '.join(used_names)}." if used_names else ""
        )
        system_prompt = (
            f"You are an NPC generator for an RPG. Context: {context}. "
            "Reply only with ONE first name and/or ONE profession, "
            "on a single line, with no repetition and no explanation."
            f"{already_generated}"
        )
        prompt = "Generate a first name and/or a profession for an RPG NPC."

        name = generate_response_queued(prompt, system_prompt, "Name generation").strip()
        self.name_queue.put(name)

        with self.lock:
            self.used_names.append(name)
            self.is_generating = False

    def get_name(self) -> str:
        """Get a generated name (waits if necessary)"""
        name: str = self.name_queue.get()
        name = name.replace(".", "").strip()

        return name
