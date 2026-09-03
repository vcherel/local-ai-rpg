# Verification scripts

What a change to this repo is checked with. None of them opens a window, none of them loads
the model, and none of them needs the game to be played: `harness.py` stands a real `Game`
up on SDL's dummy drivers with the LLM stubbed and a virtual clock, and every script here
steps that.

    uv run python scripts/verify/refs.py            # every module parses, every self.x() resolves
    uv run python scripts/verify/smoke.py           # 900 frames, then look at the state
    uv run python scripts/verify/render_diff.py     # this tree against HEAD, pixel by pixel
    uv run python scripts/verify/frame_profile.py   # where a frame goes
    uv run python scripts/verify/spawn_rates.py     # what the world would roll, as a table
    uv run python scripts/verify/render.py --out D  # the shots on their own, to look at

`refs.py` and `smoke.py` are the two to run after any multi-file change: between them they
catch a file truncated by a bad write, a call left behind by a deleted method, and a world
that stops making sense a few hundred frames in. `render_diff.py` is what an optimisation
meant to cost nothing visually is proved with. All of them exit non-zero on failure with
the reason on stderr.

## What is reproducible

A run is a function of its seed, all of it. The harness runs the generation threads inline,
stubs the music player (its worker waits on a queue forever and cannot be), freezes the
chunk build budget so streaming counts frames instead of milliseconds, keeps the frame clock
off the wall, and pins `PYTHONHASHSEED` before the interpreter starts.

The world itself is what makes that hold. A building is named off its settlement's chunk and
the slot it was dealt, so its wing, its roof and the shove it gives its neighbour when the
footprints are pushed apart are the same in every process; before that they were rolled off
a fresh uuid, and the same seed laid the same houses down in slightly different places each
run. The starting town is drawn off the global stream rather than a fresh unseeded one, so
it is still different every playthrough and the same under a seeded harness.

Two runs of the same tree therefore give byte-identical shots, the settlements and the
people walking about in them included, and `render_diff.py` compares all six.
