"""Decisions: the model asked to pick one of a few labelled answers, and never to write one.

The question ends on a lettered list, and the answer is read off the probabilities the
model gives each letter as the first thing it would say: one pass over the prompt, nothing
generated, nothing to parse. Those probabilities are odds, not a verdict, and the choice is
a draw from them (`Decisions.TEMPERATURE` flattens them first), so a villager who is
probably going to report the player now and then does not. What each choice is worth in
the game is the caller's to say: the model picks a label, code turns it into a number.

With no model the caller's own odds are drawn from instead (`offline`), so every decision
has an answer the game can live with in a clone that never downloaded the weights.

`decide` blocks and is for a worker. `later` runs a function calling it on a thread and
hands back a `Pending` the main thread polls once a frame; nothing it does touches the world.
"""

from __future__ import annotations

import math
import random
import threading
from dataclasses import dataclass

import core.constants as c
from core import llm_log
from llm.llm_request_queue import decide_queued

LETTERS = "ABCDEFGH"

# Draws of its own, so a decision made or not made never shifts a seeded roll of the world's.
_rng = random.Random()


@dataclass
class Decision:
    choice: str
    probs: dict[str, float]

    def chance(self, label: str) -> float:
        return self.probs.get(label, 0.0)


def _normalised(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0:
        return {label: 1.0 / len(weights) for label in weights}
    return {label: max(0.0, w) / total for label, w in weights.items()}


def _softmax(labels: list[str], logits: list[float]) -> dict[str, float]:
    scaled = [value / c.Decisions.TEMPERATURE for value in logits]
    top = max(scaled)
    exps = [math.exp(value - top) for value in scaled]
    total = sum(exps)
    return {label: e / total for label, e in zip(labels, exps, strict=True)}


def odds(base: dict[str, float], *shifts: dict[str, float] | None) -> dict[str, float]:
    """`base` with every one of `shifts` multiplied in, label by label: how a caller's own
    odds lean on the state of the world (a temperament, a liking) when there is no model."""
    out = dict(base)
    for shift in shifts:
        for label, mult in (shift or {}).items():
            if label in out:
                out[label] *= mult
    return out


def _pick(labels: list[str], probs: dict[str, float], draw: bool) -> str:
    if not draw:
        return max(labels, key=probs.__getitem__)
    return pick(probs)


def pick(weights: dict[str, float]) -> str:
    """One label drawn from `weights`, off the decisions' own stream."""
    labels = list(weights)
    return _rng.choices(labels, weights=[weights[label] for label in labels])[0]


def question_block(question: str, options: dict[str, str]) -> str:
    lines = "\n".join(f"{LETTERS[i]}) {text}" for i, text in enumerate(options.values()))
    return f"{question}\n{lines}\nAnswer with the letter only."


def decide(
    prompt: str,
    question: str,
    options: dict[str, str],
    system_prompt: str,
    category: str,
    offline: dict[str, float] | None = None,
    draw: bool = True,
    prior: dict[str, float] | None = None,
) -> Decision:
    """One of `options` (label: how it is put to the model), drawn from the model's odds.

    `prompt` is the situation and `question` what is asked about it; they are kept apart so
    a caller can put the part it shares with a call just made (a conversation) first, where
    the cache already holds it. `offline` is the odds with no model, uniform if not given,
    and is also what a model that fails mid-call falls back to. `draw=False` takes the most
    likely answer instead of drawing one, for a question of fact rather than of character.
    `prior` is multiplied into the model's odds, label by label: what the game wants as a
    base rate whatever the model leans towards (a witness mostly tells)."""
    labels = list(options)
    full = f"{prompt}\n\n{question_block(question, options)}" if prompt else question_block(question, options)
    category = f"Decide: {category}"
    answer = None
    try:
        answer = decide_queued(full, system_prompt, category, len(labels))
    except Exception as error:
        llm_log.log_parse_failure(category, "", f"decision failed: {error}")
    if answer is None:
        probs = _normalised(offline or dict.fromkeys(labels, 1.0))
        return Decision(_pick(labels, probs, draw), probs)
    probs = _normalised(odds(_softmax(labels, answer["logits"]), prior))
    choice = _pick(labels, probs, draw)
    llm_log.log_decision(
        category,
        system_prompt,
        full,
        probs,
        choice,
        answer["duration"],
        answer["model_path"],
        answer["prompt_tokens"],
        answer["evaluated"],
    )
    return Decision(choice, probs)


class Pending:
    """Work that asks for decisions, run on a thread. `poll` is None until it is done, then
    whatever it returned. It is handed only what it reads and changes nothing itself: the
    main thread polls it and does the changing."""

    def __init__(self, work):
        self._result = None
        self._done = False
        threading.Thread(target=self._run, args=(work,), daemon=True).start()

    def _run(self, work):
        try:
            self._result = work()
        finally:
            self._done = True

    @property
    def done(self) -> bool:
        return self._done

    def poll(self):
        return self._result


def later(work) -> Pending:
    """`work()` (a function calling `decide`) on a thread of its own, for the main thread to poll."""
    return Pending(work)
