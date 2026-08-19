from __future__ import annotations

import random
import threading
import time
from typing import TYPE_CHECKING

import core.constants as c
from llm.llm_request_queue import generate_response_queued

if TYPE_CHECKING:
    from core.save import SaveSystem


class DeathTauntGenerator:
    """The line the death screen mocks the player with, written ahead of time.

    Same shape as `NPCNameGenerator`, and for the same reason: the death screen is blocking
    and holds for a couple of seconds, so waiting on the model there would turn every death
    into a stall. A small buffer is filled on a background thread and topped back up after
    each death; an empty buffer falls back to `Death.FALLBACK_TAUNTS` rather than making the
    player wait. The taunts never name a killer, because they are written before anyone knows
    who it will be: the death screen puts that on its own line.
    """

    def __init__(self, save_system):
        self.cond = threading.Condition()
        self.save_system: SaveSystem = save_system
        self.is_generating = False
        self.ready_taunts: list[str] = list(save_system.load("death_taunts", []))
        # Set by close(): a taunt still in flight belongs to a session that is over and must
        # not write into the next game's save.
        self.closed = False

        self.start_generation()

    def close(self):
        self.closed = True

    def start_generation(self):
        """Keep the buffer topped up, one background call at a time."""
        with self.cond:
            if self.closed or self.is_generating or len(self.ready_taunts) >= c.Death.TAUNT_BUFFER:
                return
            self.is_generating = True

        threading.Thread(target=self._generate_background, daemon=True).start()

    def _generate_background(self):
        context = None
        while context is None:
            if self.closed:
                return
            context = self.save_system.load("context", None)
            if context is None:
                time.sleep(0.1)  # avoid busy waiting

        with self.cond:
            already = list(self.ready_taunts)
        avoid = f" Do not write any of these: {' | '.join(already)}." if already else ""
        system_prompt = (
            f"You write the death screen of an RPG set in this world: {context}. "
            "Reply with ONE short mocking line addressed to the adventurer who has just died, "
            "at most twelve words, cruel and dry rather than cheerful. Never name who or what "
            "killed them, and never use quotation marks. Single line, no explanation."
            f"{avoid}"
        )

        taunt = generate_response_queued("Write one death screen taunt.", system_prompt, "Death taunt").strip()
        taunt = taunt.strip('"').strip()
        if taunt:
            with self.cond:
                self.ready_taunts.append(taunt)
        with self.cond:
            self.is_generating = False
        self.persist()
        # One call per thread, so a buffer that wants three lines queues them one behind the
        # other instead of firing three LLM calls at once in front of the player's dialogue.
        self.start_generation()

    def take(self) -> str:
        """Pop a taunt for a death that just happened, and start writing its replacement.
        Never waits: a canned line is better than a death screen that hangs."""
        with self.cond:
            taunt = self.ready_taunts.pop(0) if self.ready_taunts else random.choice(c.Death.FALLBACK_TAUNTS)
        self.persist()
        self.start_generation()
        return taunt

    def persist(self):
        if self.closed:
            return
        with self.cond:
            self.save_system.update("death_taunts", list(self.ready_taunts))
        self.save_system.save_all()
