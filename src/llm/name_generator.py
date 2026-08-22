from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from core.save import SaveSystem


class NPCNameGenerator:
    def __init__(self, save_system):
        # A Condition (re-entrant) guards the buffer and lets get_name wait for a name
        # instead of busy-looping when none is ready yet.
        self.cond = threading.Condition()
        self.save_system: SaveSystem = save_system
        self.is_generating = False
        # Both restored from the save so a continued game keeps every name it already
        # made: used_names avoids duplicates, name_buffer skips regenerating ready names.
        self.used_names: list[str] = list(save_system.load("used_names", []))
        self.ready_names: list[str] = list(save_system.load("name_buffer", []))
        # Set by close() when the player leaves the game: the save file is shared with
        # whatever game starts next, so a name still being generated must not write to it.
        self.closed = False

        self.start_generation()

    def close(self):
        self.closed = True

    def start_generation(self):
        """Ensure one name is being prepared ahead of the next NPC that needs one."""
        with self.cond:
            if self.closed or self.is_generating or self.ready_names:
                return
            self.is_generating = True

        threading.Thread(target=self._generate_name_background, daemon=True).start()

    def _generate_name_background(self):
        context = self.save_system.await_context(lambda: self.closed)
        if context is None:
            return

        with self.cond:
            used_names = list(self.used_names)

        already_generated = (
            f" Names already generated, do not reuse any of them: {', '.join(used_names)}." if used_names else ""
        )
        system_prompt = (
            f"You are an NPC generator for an RPG. Context: {context}. "
            "Reply with ONE realistic name for an NPC (first name, optionally with a last "
            "name), for example 'Elena', 'Bran Thatcher', or 'Mira the herbalist'. You may "
            "optionally add a short profession or epithet after the name, but never reply "
            "with a profession alone. Single line, no explanation."
            f"{already_generated}"
        )
        prompt = "Generate a name for an RPG NPC."

        name = generate_response_queued(prompt, system_prompt, "Name generation").strip()

        with self.cond:
            self.ready_names.append(name)
            self.used_names.append(name)
            self.is_generating = False
            self.cond.notify_all()
        self.persist()

    def get_name(self) -> str:
        """Return a prepared name, kicking off generation and waiting if none is buffered."""
        with self.cond:
            while not self.ready_names:
                self.start_generation()  # no-op if already generating; re-entrant lock
                self.cond.wait(timeout=0.5)
            name = self.ready_names.pop(0)
        self.persist()

        return name.replace(".", "").strip()

    def persist(self):
        """Write the buffered and used names to the save so a restart reuses them."""
        if self.closed:
            return
        with self.cond:
            self.save_system.update("name_buffer", list(self.ready_names))
            self.save_system.update("used_names", list(self.used_names))
        self.save_system.save_all()
