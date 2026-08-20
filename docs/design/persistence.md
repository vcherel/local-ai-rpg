# Persistence

## Item persistence works by id

`SaveSystem` stores `inventory` / `equipped` as item id lists and `items` as the one master list
of full item dicts (see the key list in `src/core/save.py`). Anything handed to the player has to
end up in `world.items` or its id will not resolve on reload and the item silently vanishes. For
items granted instantly (chest, lootbox) rather than picked up off the ground, they are appended
already flagged `picked_up = True`, purely so the id resolves later; they never render or get
picked up again.

## What is saved and what is not

Saved because a seed cannot rebuild it: villages (their buildings and people, with names,
affinity, quests and stock), touched POI state (`pois`, keyed by `"cx:cy"`), which bear traps have
shut, what is left of each tunnel, explored minimap cells, rest cooldowns, breakables' hp, the
player and their items.

Never saved because a seed or a count can rebuild it: scenery, floor details, roads and rivers,
POIs themselves, camp and tunnel garrisons (a count is), critters, projectiles, particles, decals
and floating text.

`Building.dropped_items` (loot popped from a smashed crate, waiting to be picked up) is
session-only and not written to the save. A `Building` object lives for the whole process, so
dropped crate loot survives leaving and re-entering the room, but not a save/reload.

## Background threads must not write over the next session's save

`World.persist_world` flushes generated state (context, shops, boss/landmark/village names) when a
background thread finishes it, throttled to `World.PERSIST_MIN_INTERVAL_S` since each call
serialises the whole world, and skipped once `close()` has ended the session. `__main__` builds a
fresh `SaveSystem` per session for the same reason, and `EventSystem.notify`, `NPCNameGenerator`
and `DeathTauntGenerator` all check whether the session is still alive before writing or talking to
a widget.
