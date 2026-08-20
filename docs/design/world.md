# World

## The world has no edge

`World.WORLD_SIZE` is only the settled area: it fixes the starting village, the spawn
point, boss roaming ranges and the distance-from-center that scales monster difficulty.
Past it the map keeps going, and points of interest, villages and floor details all
stream in per chunk, so walking out never runs into a wall of nothing.

Because a POI is regenerated from its chunk seed on every visit, it must stay
deterministic from `(cx, cy)` alone: anything the player changes goes in
`World.poi_state`, keyed by the POI id, and nothing else about a POI is saved.

Villages are the deliberate exception. `village_site(cx, cy)` is a pure function of the
coordinates like everything else streamed, but the settlement itself is generated **once**
and then persisted, buildings in `buildings` and people in `npcs`. Regenerating it per
visit would mean rebuilding NPC names, affinity, quests and LLM shop stock from a seed,
which is impossible. So: the map is endless and deterministic, what stands on it is
generated on demand and kept. New villages must go through `World._ensure_village` so
their buildings reach the chunk index (`_index_buildings`) and `set_active_buildings`.

## The wilderness is terrain, not entities

Everything in `scenery.py` (trees, boulders, grass, ponds, roads, ground patches) is
generated from its chunk's coordinates, held only while that chunk is loaded and never
saved, exactly like the floor details: nothing the player does can change a single piece
of it, so there is no state to persist and no id to key.

A chunk rolls **one biome** and lays out that biome's clumps, which is what makes a wood
a wood; scattering every kind evenly over every chunk gives texture, not places.

The only part that touches gameplay is collision: trunks and boulders answer
`World.blocked` through their own fine grid (`Scenery.INDEX_CELL`, finer than the chunk
grid the buildings use, because a wood holds far more trunks than a village holds
houses), which is enough for the player, monsters, critters, arrows and spawning at once,
since they already go through `blocked`. Monsters get round a trunk by the lookahead in
`Monster._steer`; `World._detour_corner` stays about buildings only, a tree being too
small to be worth a detour.

The tracks over that terrain are terrain too, and they route by *placement* rather than
by pathfinding: a road and a footpath are laid as a bent line between two pure-function
places, stopped at the gate side of a settlement's grounds and bowed round any third one
in the way, and nothing solid is then generated within `ROAD_CLEARANCE` of a blob. That
order is the whole trick: the wood grows around the road, so no route ever has to pick
its way through anything, and a chunk still needs to know nothing about its neighbours.

## Water is a speed penalty, not a wall

Water is the one piece of terrain that is neither a wall nor scenery. Nothing is stopped
by a river, a pond or a lake (`blocked` never sees them), everything is slowed in one
through `World.terrain_speed`, and a bridge over it takes the point back to ordinary
ground (`World.water_at`, reading the same fine grid the trunks use).

Only the player ever gets better at it: `Stats.swim_multiplier` climbs from
`Scenery.SWIM_SPEED` toward `SWIM_SPEED_MAX` as the swimming stat trains, and never
reaches walking pace, so a river stays a real answer to being chased and a bridge stays
the fast way over for the whole game. That is why navigation needed no changes: nothing
has to route around water, it crosses slowly. Rivers are generated like roads (a pure
function of the lane index) and bend around settlements rather than being cut off at
them; landmarks and cover keep out of the water instead.

## The underground is a far corner of this world

Not a second world and not a scene. A tunnel's rooms are ordinary world-space rectangles
at `Tunnels.ORIGIN` plus its chunk's slot (a cave offset again by `CAVE_OFFSET`, so a
village well and a wilderness cave mouth in the same chunk are never dug in the same
place), so the player, the monsters, the projectiles, the loot and the save all work down
there unchanged, exactly as a building's interior is just its own footprint.

What makes it read as somewhere else is subtraction, and it hangs off the single
`World.underground`: `blocked` answers with the tunnel's rock instead of the map, and
`update` stops syncing chunks, stops revealing map cells, stops running events, stops
despawning and stops standing anything up around the player. So nothing streams into a
tunnel, nothing wanders in after you, and what is down there was put there when you
climbed down.

Its garrison is a count like a bandit camp's (tagged `camp_id`, never saved, never
counted toward the roaming cap, stood back up on the next descent), its hoard is placed
once ever, and dying down there surfaces you like any other death while the tunnel keeps
whatever is left of its garrison. A second way in is a second `Tunnel.kind`, not a second
system: `World.tunnel_at(chunk, kind)` builds and caches every tunnel there is and
`_go_underground` is the one way to be in one, so a cave mouth is a POI with an E on it
and nothing else had to learn that caves exist.

## The spawn point is protected ground, three ways at once

Any one of them alone still gets the player killed on arrival.

1. Nothing hostile is *spawned* within `World.SAFE_RADIUS` of the world centre
   (`_spawn_is_sheltered`, which also covers every settlement plus a margin), so the
   starting town has no ring of monsters waiting one screen out.
2. The player is *placed* by `World.safe_spot_near`, which looks for hostiles as well as
   walls, with `clear_hostiles_around` first sending whatever chased them there back out.
3. They arrive with `Player.invuln_until` open for `Death.SPAWN_GRACE_S`, spent early the
   moment they attack.

How crowded the world is at all follows from where the player is standing
(`World.roaming_cap`), not from a world-wide constant: the ground around the starting
town is deliberately thin and the deep wilds are full. Monsters may still *wander* into
any of this; what is forbidden is being stood up there.

The pace is slow on purpose too. `World.ROAMING_CAP_NEAR`,
`SAFE_RADIUS`/`INITIAL_SPAWN_MIN_DISTANCE` and the
`SPAWN_MIN_DISTANCE`..`SPAWN_MAX_DISTANCE` band are the four numbers deciding how
molested a new player is on their own doorstep, and they are tuned together: a wider safe
ring with the same cap only pushes the same crowd one screen further out.
`Player.SPEED`/`RUN_SPEED` and `Entities.MONSTER_SPEED_SCALE` are the other half, moved
together so the margin between running and being chased is unchanged while a fight is
slow enough to be read as it happens.

## Difficulty is distance from the world centre

Three levers pulled together rather than one:

- *Which* kinds spawn: `MonsterKind.min_distance` unlocks a kind and
  `Entities.DEPTH_HALF_LIFE` fades it out again, so the mix gets harder rather than merely
  wider as the player walks out.
- *How many*: `World.roaming_cap`, eased over a long ramp out to
  `ROAMING_CAP_FAR_DISTANCE`.
- *What has a name*: `Boss.LANDMARK_MIN_DISTANCE` puts the first world's guardian out on
  the far side of the settled ring and `Boss.ROAM_MIN_DISTANCE` (which quest bosses are
  also placed from, in a band outward) keeps every other boss well past it.

Night pulls the first lever and only the first: `DayNight.NIGHT_DANGER_BONUS` rolls a
spawn as if the ground were deeper, capped at `NIGHT_DANGER_DISTANCE_FRAC` of how far out
it already is, so the dark deepens the wilds instead of importing them onto the starting
town's doorstep. A camp leader (`CAMP_LEADER_DANGER_BONUS`) and a tunnel garrison
(`Tunnels.GUARD_DANGER_BONUS`) use that same bonus, so anything that stretches the
`min_distance` ladder has to stretch those with it.

Nothing scales a monster's own stat block: a Troll is the same Troll wherever it is met,
which is what keeps `MONSTER_KINDS` the one source of what a creature is worth.

## Night is a state of the world

`World.night_damage_mult` and the detection multiplier are read per frame and passed into
`Monster.move`, so a monster that spawned at noon still hits like a night monster after
dark; only the danger bonus a new spawn rolls with is baked in at spawn time.
