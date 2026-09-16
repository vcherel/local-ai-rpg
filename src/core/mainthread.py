"""The one way a worker changes the world: by asking the main thread to.

A background thread is for waiting on the model. What it does with the answer (a quest
built into the world, a boss stood up, a payout) touches the lists and dicts the frame is
walking at that very moment, and a dict that grows under an iteration raises. So a worker
posts the change here and `Game._update_frame` runs it at the top of the next frame, on
the main thread, in the order it was posted. Nothing is lost when no frame is being run: a
change posted while a menu is open lands on the frame the menu closes, which is when the
world moves again anyway.
"""

import queue

_pending: queue.Queue = queue.Queue()


def post(fn, *args):
    """Run `fn(*args)` on the main thread, on its next frame."""
    _pending.put((fn, args))


def drain():
    """Run everything posted so far. Called once a frame by the main thread and nowhere else."""
    while True:
        try:
            fn, args = _pending.get_nowait()
        except queue.Empty:
            return
        fn(*args)
