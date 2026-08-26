# Presentation

## Exactly one interaction prompt is on screen at a time

`Game.current_interaction` picks the nearest interactable in reach (NPC, campfire, door,
interior chest/bed, well, ladder), `Game._interact` runs that same one, and
`GameRenderer._draw_interaction_prompt` draws it. Never draw a prompt from the entity or
building that owns the thing: that is what used to stack a label over every bed in the tavern,
and what let a prompt point at something other than what the key did.

## The map is memory, not radar

`World.explored` is the only thing that lights the minimap up, it is filled in by walking
(`_reveal_around`) and persisted, and the minimap draws no live entity of any kind at a fixed
small zoom. Anything that would let the player scout from the HUD instead of walking (monster
dots, a full-screen map, zoom) is a deliberate omission, not a missing feature.

Underground the same memory is kept on a finer grid (`Fog.TUNNEL_CELL`, `World.fog_cell`)
and only as far as the lantern reaches, and only over floor: rock is not somewhere the
player has been. So a cave draws itself room by room as it is walked, the map is scaled to
hold the whole dug-out (`Minimap.TUNNEL_RANGE`), and the one mark on it is the way back
out. It is the surface's system down to the cells being cells of the same world grid, which
is what gets it saved and reloaded with everything else.

Under the map, the distance strip reads from the world centre on the surface (difficulty is
distance from it) and from the way in underground, where the same sum would report a
million paces of nothing. It takes the longest phrasing that fits its panel: past four
digits the sentence ran off the end of the strip, and the number is the half worth reading.

The single exception is a rumour's mark (`World.mark_rumor` / `rumor_marks`): somewhere the
player was *told* about, held session-only and rubbed out on arrival, which is what turns a
rumour into somewhere to go. It marks a place, never a creature, and nothing else may put a pin
on the map.

## The first thing seen is the world, and the lore is read before it

The title screen is a live settlement (`MenuScene`) built by the same generator the game uses,
with real villagers walking it under a moving sky; opening a session then holds the screen black,
writes the world's context onto it with nothing else drawn anywhere, and fades the world up once
the player dismisses it (`ContextMenu.intro` / `draw_fade`). That is deliberate: the lore used to
open as a panel over a street already full of moving people, where it read as one more widget and
went unread. The spawn grace is opened on the first frame the player can actually see the world
for the same reason it is granted after the death screen, since the opening holds for as long as
the model takes and as long as the player reads.

## The effect systems

Particles, floating damage numbers and blood decals are each one global session-only system
(`get_particles` / `get_floating_text` / `get_decals`), updated once per frame in `Game.run()`
rather than inside `World.update`, so they keep animating even while a menu pauses the rest of the
update. They are drawn from `GameRenderer.draw_world`, same call whether the player is indoors or
out.

`Hitstop` (`core/screen_fx.py`) only slows the `dt` fed to gameplay updates (player/monster
movement, `World.update`, projectiles); camera shake, particles, floating text and decals keep
advancing on the real `dt` so the freeze reads as a snap rather than the whole frame stalling.

Anything that hurts a crowd at once draws itself through `core/impact_fx.py` (a wave of particles
thrown out to exactly the radius the damage covered, plus a bolt to everything it caught). Chain
Strike used to pop three damage numbers across the screen with nothing connecting them, which
reads as a bug. The wave is particles rather than a drawn ring on purpose: a perfect circle reads
as a HUD element laid over the fight, while a scatter of debris reads as something having gone off
there.

## Blood is the record of a fight, and it says what made it

A wound is drawn from the weapon that opened it. `core/decals.py` holds one recipe per family
(`_SPLAT_STYLES`: light, slash, pierce, heavy, shot), and `WorldCombat.blow_style` is the family
whose blow is being resolved right now, set for the length of one swing or shot by whatever
started it. A dagger leaves specks, a sword throws a wide arc of it sideways, a spear puts a
narrow jet out the far side, a hammer bursts. A kill is the same recipe several times over, with
the long arterial throws over the top, because the difference between a hit and a kill has to be
legible from across the clearing. Nothing about a splat is a circle: the outline is torn off its
own radius (`Decals.RAGGED`), which is the whole difference between blood and a sticker.

Blood is also something to stand in. Every splat marks its cell wet for a few seconds, and
`DecalSystem.track_walkers` gives anything crossing that ground bloody soles, printed out again
stride by stride until they run dry. It is the one thing on the ground that says which way
something walked away from a body.

## The music answers the world, not the clock

`core/music.py` holds a pad per context (day, night, village, combat, boss, blood night) and
several progressions inside each, rendered on a worker thread and crossfaded on two reserved
channels. What is playing is decided by `Game._music_context`, as a priority and never a blend:
what is most immediately about to kill the player wins, and where they are standing is the
tiebreak. A context also swaps itself to another of its own progressions after a while, because a
pad that never changes stops being heard.

The swing arc and the hit test read the same two numbers (`WeaponArchetype.arc_deg` at the
weapon's reach), so the arc can never promise reach the swing does not have.

## The game saves itself, and the player can see it happen

`Game.save_data` is the one path to disk: a 5 minute timer (`World.AUTOSAVE_INTERVAL_S`) plus the
moments worth not replaying (a tunnel entered or left, a night slept through, a quest handed in, a
death, quitting), each of them pushing the timer back. Every one of them stamps
`Game.last_save_ms`, which `GameRenderer._draw_save_marker` shows as a brief disc in the corner. A
new save trigger belongs on that list rather than in a new write path.

## The key map is written down exactly twice

`Game._handle_key` is the whole in-world key map as one table, and `HelpMenu.CONTROLS` is the only
written record of it. A rebinding that misses the second leaves the game lying to the player.
