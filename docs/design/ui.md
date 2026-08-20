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

Anything that hurts a crowd at once draws itself through `core/impact_fx.py` (a ring at exactly
the radius the damage covered, plus a bolt to everything it caught). Chain Strike used to pop
three damage numbers across the screen with nothing connecting them, which reads as a bug.

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
