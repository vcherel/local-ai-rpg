from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import core.constants as c
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
        self._context = ""

    def close(self):
        self.closed = True

    def start_generation(self):
        """Ensure names are being prepared ahead of the next NPCs that need one, up to
        `Hyperparameters.NAME_BUFFER` of them.

        Never called on construction: a session that opens on empty wilderness, or on a save
        whose buffer is already full, should not spend a call on a name for nobody. What
        asks for one is the player walking up to a settlement (`_prepare_settlements_near`)
        and the end of each conversation, both of which are far enough ahead of the next NPC
        that the name is waiting when it is wanted. A few rather than one, because
        `get_name` waits on the model when the buffer is dry, and two unnamed villagers
        spoken to in a row emptied it."""
        with self.cond:
            if self.closed or self.is_generating or len(self.ready_names) >= c.Hyperparameters.NAME_BUFFER:
                return
            self.is_generating = True

        threading.Thread(target=self._generate_name_background, daemon=True).start()

    def _distinct(self, name: str) -> str:
        """A name nobody in this world wears yet. The prompt asks for one, but a small model
        does not always listen, and everything that links a quest to a person (the thief,
        the recipient) does so by name: a second Bran Thatcher is a delivery handed to the
        wrong man. Asked again a couple of times, then told apart by hand."""
        with self.cond:
            used = {used.lower() for used in self.used_names}
        for _ in range(c.Hyperparameters.NAME_RETRIES):
            if name.lower() not in used:
                return name
            name = self._ask_for_name()
        if name.lower() not in used:
            return name
        suffix = 2
        while f"{name} {suffix}".lower() in used:
            suffix += 1
        return f"{name} {suffix}"

    def _ask_for_name(self) -> str:
        with self.cond:
            recent = self.used_names[-c.Hyperparameters.NAME_PROMPT_RECENT :]
        already_generated = (
            f" Names already generated, do not reuse any of them: {', '.join(recent)}." if recent else ""
        )
        system_prompt = (
            f"You are an NPC generator for an RPG. Context: {self._context}. "
            "Reply with ONE realistic name for an NPC (first name, optionally with a last "
            "name), for example 'Elena', 'Bran Thatcher', or 'Mira the herbalist'. You may "
            "optionally add a short profession or epithet after the name, but never reply "
            "with a profession alone. Single line, no explanation."
            f"{already_generated}"
        )
        prompt = "Generate a name for an RPG NPC."
        return generate_response_queued(prompt, system_prompt, "Name generation").strip()

    def _generate_name_background(self):
        context = self.save_system.await_context(lambda: self.closed)
        if context is None:
            with self.cond:
                self.is_generating = False
            return
        self._context = context

        name = self._distinct(self._ask_for_name())

        with self.cond:
            self.ready_names.append(name)
            self.used_names.append(name)
            self.is_generating = False
            self.cond.notify_all()
        self.persist()
        # Keep going until the buffer is full: one call per name, but the next is asked for
        # as soon as this one is on the shelf.
        self.start_generation()

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
