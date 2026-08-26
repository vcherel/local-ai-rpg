"""Status effects: what a timed effect looks like on a body, as particles around it.

One table row per effect and one emit call, shared by the player, the villagers and the
monsters, so an effect looks the same whoever is wearing it. The HUD buff chips stay the
detailed readout with the seconds left on each; this is what says something is on somebody
from across a fight, and it carries no timer.

Particles rather than icons over the head: a row of lettered bubbles is HUD standing in the
world, and three of them stacked over a body read as a notification. A creature that is
burning should look like it is burning. Each effect is a drift and a colour (embers going
up, frost settling, sickness sinking off the shoulders), so it is recognised the way the
gore and the weapon trails are, and never read.

Cheap on purpose: this runs for everything on screen carrying an effect, every frame, so
each effect drops one or two particles every `EMIT_INTERVAL_MS` and nothing else. Adding an
effect means adding a row to `EFFECTS`, not a branch: whatever an entity's `status_effects()`
returns and this table knows about gets its look.
"""

from __future__ import annotations

import random

import pygame

from core.particles import Particle, get_particles

# How often one affected body throws its next few motes. Everything on screen with an effect
# on it pays this, so it is a handful of particles a second and not a plume.
EMIT_INTERVAL_MS = 150

# effect key -> what drifts off a body wearing it.
#   color   the one thing it is recognised by
#   rise    how hard it is thrown up the screen (negative) or down it (positive)
#   spread  how wide across the body it is thrown
#   size, life, shape  as the particle system takes them
#   count   motes per emission, so a fire crackles and a poison seeps
EFFECTS = {
    # Embers coming off something alight, thrown up and dying quickly.
    "burn": {"color": (238, 122, 44), "rise": -2.2, "spread": 0.9, "size": 3, "life": 420, "count": 2},
    # Frost settling out of the air around something too cold to move properly.
    "chill": {"color": (170, 224, 246), "rise": 0.5, "spread": 1.3, "size": 2, "life": 620, "count": 1},
    # Earth and root fibre at the feet, low and going nowhere.
    "root": {"color": (150, 118, 74), "rise": 0.2, "spread": 1.6, "size": 3, "life": 500, "count": 1, "foot": True},
    # Sickness running off the shoulders.
    "weakened": {"color": (168, 62, 76), "rise": 1.0, "spread": 1.1, "size": 2, "life": 560, "count": 1},
    # Life going back in, rising gently.
    "regen": {"color": (92, 208, 118), "rise": -1.4, "spread": 1.0, "size": 2, "life": 620, "count": 1},
    # Sparks off the hands of somebody hitting harder than they should.
    "strength": {
        "color": (232, 132, 46),
        "rise": -1.0,
        "spread": 1.2,
        "size": 3,
        "life": 380,
        "count": 1,
        "shape": "shard",
    },
    # Streaks left behind somebody moving too fast for them.
    "swiftness": {"color": (88, 198, 234), "rise": -0.6, "spread": 1.8, "size": 2, "life": 340, "count": 1},
    # Chips of stone orbiting a skin that is not skin.
    "stoneskin": {
        "color": (172, 172, 188),
        "rise": -0.3,
        "spread": 1.5,
        "size": 3,
        "life": 520,
        "count": 1,
        "shape": "shard",
    },
    # Blood in the air around somebody who is enjoying this.
    "bloodlust": {"color": (196, 46, 66), "rise": -0.8, "spread": 1.2, "size": 3, "life": 420, "count": 1},
}


def emit_status(x: float, y: float, size: float, effects, next_ms: int) -> int:
    """Throw one round of motes for everything on this body, and say when the next round is
    due. `next_ms` is that deadline back from last time, kept on the body itself so each of
    them keeps its own clock instead of the whole street pulsing together.

    (x, y) is the body in world space and `size` how big it is: the effects come off its
    middle, except the ones that belong at its feet.
    """
    now = pygame.time.get_ticks()
    if now < next_ms:
        return next_ms
    known = [effect for effect in effects if effect in EFFECTS]
    if not known:
        # Jittered even with nothing to draw, so a fresh effect starts on its own beat.
        return now + EMIT_INTERVAL_MS
    particles = get_particles()
    for effect in known:
        spec = EFFECTS[effect]
        half = size / 2
        origin_y = y + half * 0.7 if spec.get("foot") else y - half * 0.2
        for _ in range(spec["count"]):
            particles.particles.append(
                _mote(
                    x + random.uniform(-half, half) * spec["spread"],
                    origin_y + random.uniform(-half * 0.4, half * 0.4),
                    spec,
                )
            )
    return now + EMIT_INTERVAL_MS + random.randint(-30, 30)


def _mote(x: float, y: float, spec: dict):
    """One particle of an effect: its drift is the whole of what tells the effects apart, so
    it is built here rather than going through a burst, which would spray it every way at
    once and lose the difference."""
    return Particle(
        x,
        y,
        random.uniform(-0.4, 0.4),
        spec["rise"] + random.uniform(-0.3, 0.3),
        spec["life"],
        spec["color"],
        random.uniform(spec["size"] * 0.6, spec["size"]),
        shape=spec.get("shape", "circle"),
        rot=random.uniform(0, 6.28) if spec.get("shape") == "shard" else 0.0,
        rot_speed=random.uniform(-4, 4) if spec.get("shape") == "shard" else 0.0,
    )
