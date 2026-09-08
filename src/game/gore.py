from __future__ import annotations

import math

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.damage_fx import get_damage_fx
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from core.screen_fx import get_hitstop


class WorldGore:
    """What a blow looks like where it landed: the mess, the noise and the number.

    Mixed into `World` beside `WorldCombat`, which is what decides who was hit and for how
    much. Split out because the two answer different questions and only one of them is ever
    the reason to open the file: a change to how a wound reads is a change here, and a
    change to what a swing catches is a change there. Nothing in here reads the entity
    lists, which is the other half of why it is its own file.
    """

    # The weapon family whose wound is being drawn right now, one of `core.decals`'
    # splat styles. Set for the length of one blow by whatever started it (a swing, a
    # shot) and read by the gore, so a spear leaves a spear's mess without every damage
    # path having to carry an archetype down to the decal. Anything nobody set it for (a
    # burn tick, a monster's bite, a fall) bleeds generically.
    blow_style = "generic"

    @staticmethod
    def _prop_chip(x, y, color, sound: str = "hit", key: str | None = None, angle: float = 0.0):
        """A blow that damaged a prop without finishing it: a small puff, a knock, and the
        prop itself flinching and cracking, so hitting something breakable always reads as
        progress even when it holds.

        `key` is what identifies the prop to `core.damage_fx`, which is what the drawing
        side reads back: props are not all objects (a crate is an index into a building's
        layout), so the registry is keyed by string rather than by identity."""
        get_shake().add(c.Combat.DECOR_BREAK_SHAKE * 0.5)
        play_sound(sound)
        get_particles().spawn_burst(x, y, color, count=5, speed=4, life=280, size=3, gravity=0.4, shape="shard")
        if key is not None:
            get_damage_fx().hit(key, angle)

    @staticmethod
    def _break_effects(x, y, color, count):
        """Shared shake, crash sound and shard burst for a smashed crate/cache/barrel."""
        get_shake().add(c.Combat.CRATE_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(x, y, color, count=count, speed=6, life=550, size=5, gravity=0.4, shape="shard")

    def _spill_blood(self, x, y, body_color, direction=None, boss: bool = False):
        """The gore of a kill: a pool where it dropped, a fan of droplets thrown along the
        killing blow, and a spray still in the air over both.

        `direction` is the blow's (dx, dy) unit vector, so the mess points away from the
        player instead of ringing the corpse. A kill with no direction (a burn tick, an
        execute) bursts outward instead. What the mess is shaped like comes from the weapon
        that made it (`blow_style`), so a spear kill and a hammer kill leave different
        ground behind them."""
        style = self.blow_style
        get_decals().splash(x, y, style, direction, fatal=True, boss=boss)
        play_sound("gore")

        blood = (178, 26, 26)
        count = 78 if boss else 52
        speed = 17 if boss else 14
        size = 8 if boss else 7
        if direction:
            get_particles().spawn_directional_burst(
                x,
                y,
                math.atan2(direction[1], direction[0]),
                spread_deg=c.Decals.SPRAY_SPREAD_DEG,
                color=blood,
                count=count,
                speed=speed,
                life=780,
                size=size,
                gravity=0.32,
            )
        else:
            get_particles().spawn_burst(x, y, blood, count=count, speed=speed, life=780, size=size, gravity=0.32)
        # Chunks of the thing itself, so a slime still bleeds green over the red.
        get_particles().spawn_burst(x, y, body_color, count=30 if boss else 22, speed=8, life=600, size=7, gravity=0.42)
        # A slow, dark mist hanging where the body was, under the fast stuff: it lingers
        # after the droplets have landed, so the moment does not end on the same frame.
        get_particles().spawn_burst(
            x, y, (96, 12, 12), count=24 if boss else 16, speed=2, life=1200, size=10 if boss else 8, gravity=0.02
        )
        get_shake().add(c.Combat.KILL_SHAKE_BONUS * (2.0 if boss else 1.0))

    def _hit_feedback(self, x, y, crit: bool, direction=None):
        """Sound + particle burst for a non-fatal hit; crits read brighter and louder.
        `direction` (attacker -> target unit vector), if given, sprays the particles as a
        cone away from the hit instead of a plain omnidirectional poof."""
        play_sound("crit" if crit else "hit")
        if crit:
            get_hitstop().trigger(c.Combat.HITSTOP_CRIT_MS)
        # Even a hit that does not kill throws blood: a short fan along the blow, so a long
        # fight paints the ground it was fought over instead of leaving one dot per hit.
        get_decals().splash(x, y, self.blow_style, direction, fatal=False)
        color = (255, 240, 160) if crit else (255, 180, 180)
        count = 18 if crit else 10
        speed = 5 if crit else 4
        life = 420 if crit else 340
        size = 5 if crit else 4
        if direction:
            angle = math.atan2(direction[1], direction[0])
            get_particles().spawn_directional_burst(
                x, y, angle, spread_deg=80.0, color=color, count=count, speed=speed, life=life, size=size, gravity=0.35
            )
        else:
            get_particles().spawn_burst(x, y, color, count=count, speed=speed, life=life, size=size)

    @staticmethod
    def _pop_damage(x, y, damage: int, crit: bool):
        """Floating damage number over a hit; crits pop bigger and gold."""
        text = f"{damage}!" if crit else str(damage)
        color = (255, 210, 90) if crit else c.Colors.WHITE
        get_floating_text().spawn(x, y, text, color, big=crit)
