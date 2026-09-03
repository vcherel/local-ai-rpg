"""Standing a session up with no window, no model and no wall clock.

Every script in this folder boots through here, so what they measure is the same world.
Three things are replaced and nothing else is:

- The video and audio drivers are SDL's dummies, so a frame is drawn into memory.
- `llm.llm_request_queue` is stubbed before any game module imports from it, so nothing
  pulls the 7B model into VRAM. Callers do `from llm.llm_request_queue import ...`, which
  binds at their import time, hence the order in `boot`.
- The clock is virtual: a frame is always `FRAME_MS` and no frame sleeps, so a run is
  deterministic and as fast as the machine can draw it.
"""

import os
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRAME_MS = 16
SEED = 20260903
CONTEXT = "The valley kept its wars quietly. What was buried under it did not stay buried."


class FixedClock:
    """A pygame clock that never waits. `pygame.time.get_ticks` is driven off the same
    counter, so animation timers, cooldowns and the autosave interval all advance with the
    frames rather than with how long the machine took to draw them."""

    def __init__(self, frame_ms=FRAME_MS):
        self.frame_ms = frame_ms
        self.ticks = 0

    def tick(self, _fps=0):
        self.ticks += self.frame_ms
        return self.frame_ms

    def get_time(self):
        return self.frame_ms

    def get_fps(self):
        return 1000.0 / self.frame_ms


class SyncThread:
    """A thread that has already finished by the time `start` returns.

    The generation threads (landmark names, NPC names, shop stock, death taunts) race the
    main thread for the global `random` stream, and losing that race differently on two
    runs is what made the same code draw different frames. With the model stubbed their
    work is instant anyway, so running it inline costs nothing and buys a world that is a
    function of its seed. Installed only while a script is booting a deterministic run.
    """

    def __init__(self, _group=None, target=None, name=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.name = name or "sync"
        self.daemon = daemon

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)

    def join(self, _timeout=None):
        return None

    def is_alive(self):
        return False


class _StubStream:
    def __init__(self, text):
        self.text = text

    def __iter__(self):
        yield self.text


def _stub_llm(answer):
    """Replace the queue's entry points with canned answers. The parsers on the other side
    are the real ones, so an answer still has to be a sentence to survive them."""
    from llm import llm_request_queue as q

    q.get_llm_queue = lambda: None
    q.get_llm_tasks = lambda: []
    q.llm_busy = lambda: False
    q.generate_response_queued = lambda *_a, **_kw: answer
    q.generate_response_stream_queued = lambda *_a, **_kw: iter(_StubStream(answer))


class _Nothing:
    """Answers any call with None. What the music player is replaced by."""

    def __getattr__(self, _name):
        return lambda *_a, **_kw: None


def _freeze_chunk_budget():
    """`WorldStreaming` stops starting chunk builds once a frame has spent
    `CHUNK_BUILD_BUDGET_MS` of real time, so how much world exists after N frames depends on
    how fast the machine drew them, and every `random` draw after that is off by a chunk.
    Frozen to zero here, which leaves the count cap (`CHUNK_LOADS_PER_FRAME`) as the only
    limit and makes streaming a function of frames instead of seconds.
    """
    import time
    import types

    from game import streaming

    frozen = types.SimpleNamespace(**{name: getattr(time, name) for name in dir(time) if not name.startswith("_")})
    frozen.perf_counter = lambda: 0.0
    streaming.time = frozen


def _stub_music():
    """`MusicPlayer` renders its pads on a worker that then waits on a queue forever, which
    is the one background thread that cannot be run inline. Nothing here listens anyway."""
    from core import music

    music.get_music = _Nothing


def boot(seed=SEED, frame_ms=FRAME_MS, new_game=True, deterministic=True):
    """A `Game` ready to be stepped. Returns (game, clock).

    `deterministic` makes the run a function of `seed` alone, at the cost of the background
    generation threads becoming inline calls. Leave it on for anything being compared
    against another run, turn it off to profile threading as the game actually has it.
    """
    # Set before the interpreter starts or not at all, hence the re-exec: without it the
    # order of any set of strings is a fact about the process, and the spawn point comes out
    # of a search that walks one.
    if deterministic and os.environ.get("PYTHONHASHSEED") != "0":
        os.execve(sys.executable, [sys.executable, *sys.argv], {**os.environ, "PYTHONHASHSEED": "0"})

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    src = Path(os.environ.get("RPG_AI_SRC", REPO / "src"))
    sys.path.insert(0, str(src))

    import pygame

    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))

    import core.constants as c

    c.Fonts = c.Fonts.load()

    _stub_llm(CONTEXT)
    _stub_music()

    import threading

    if deterministic:
        threading.Thread = SyncThread

    from core import settings as settings_module
    from core.save import SaveSystem
    from game.game import Game

    clock = FixedClock(frame_ms)
    pygame.time.get_ticks = lambda: clock.ticks

    # Written into the live preferences object rather than through `set`, which would put
    # a silent install on disk for whoever runs this next.
    settings_module.get_settings().data.update({"music": False, "sound": False})

    random.seed(seed)

    save_system = SaveSystem(filename=str(REPO / "saves" / "verify_save.json"))
    if new_game:
        save_system.data.clear()
    # Seeded so the world reads its lore as already written: an empty context starts a
    # generation thread, and the intro panel holds the first frames on black.
    save_system.update("context", CONTEXT)

    if deterministic:
        _freeze_chunk_budget()

    game = Game(screen, clock, save_system)
    game.context_window.active = False
    return game, clock


def step(game, clock, frames):
    """Run the world exactly as `Game.run` does, minus input, display flip and autosave."""
    for _ in range(frames):
        game.active_menu = False
        game._update_frame()
        game._draw_frame()
        clock.tick()
        if game.player.hp <= 0:
            game._respawn()


def walk(game, dx, dy):
    """Put the player somewhere without simulating the walk there. Chunks stream in on the
    next update, which is what a script sampling several places wants."""
    game.player.x += dx
    game.player.y += dy
    game.world.prepare(game.player)
