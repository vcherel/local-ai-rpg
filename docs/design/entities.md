# Creatures

## A crowd surrounds, it does not queue

Anything chasing the same target goes through `World.assign_surround_slots`, which deals the
chasers evenly spaced bearings round it and hands out only `Entities.MAX_ACTIVE_ATTACKERS`
permissions to swing, nearest first; the rest hold their place on the ring and walk it slowly
round (`Monster.circle_side`). That is the one lever for how overwhelming a pack feels, and it
is deliberately two numbers rather than a per-kind behaviour: raising the token count makes
every fight in the game bloodier, and nothing else has to know. The same call serves an angry
village, which is why `NPC` carries a `slot_angle` and an `attack_token` at all: a dozen
villagers each landing a blow on the same frame was a woodchipper rather than a fight.

## Chasing is navigation, never demolition

`World.chase_waypoint` is shared by monsters, bosses and angry villagers: buildings are the
only obstacles and each has one door, so a chase across a wall aims for `_door_goal` (line up
with the doorway, then step across the threshold, or come right up against it when the door is
shut and there is nothing to do but beat on it), all of it written along the door's own outward
normal so a house may face any of the four ways. `_detour_corner` walks round anything in the
way by costing both ways round the rect, its obstacles being the buildings plus
`_scenery_obstacles` (the solid trunks and boulders on the straight line over a short stretch,
merged by `_merge_rects` so a copse is one thing to walk round rather than a dozen, since
routing round each trunk in turn is how a monster picks its way into the middle of a wood).

`Monster._steer` probes a lookahead distance rather than one step so a monster turns away from
a wall early instead of grinding into it, never probing past the goal itself (a wall behind the
player is not in the way), sampling along each probe's length rather than at the tip alone (a
clear point beyond a thin wall is not a clear path to it), holding the side it deflected to for
`World.STEER_COMMIT_MS` so it walks round an obstacle instead of shivering at the seam, and
falling back to a wall-follow so a boxed-in monster runs along what is in the way rather than
into it.

`World.unstick(body, radius)` is the one answer to a body having ended up *inside* something
solid (every mover tests `blocked` at the point it wants to step to, so one already in a wall
has every step refused and stays there for good). Its search is deliberately short
(`World.UNSTICK_RINGS`) so a body steps out of what it is in rather than being moved through it.

## A monster's look is its kind's `shape`, not its colour

Every hostile thing used to be the same circle with two smaller circles for arms, which meant a
slime, a skeleton and an ogre differed only in radius and hue. Now `MonsterKind.shape` picks a
silhouette out of `monster_art._SHAPES` and `weapon` puts something recognisable in its hand,
drawn by the same `gear.draw_weapon` the player's gear goes through.

Adding a monster means adding a row to `MONSTER_KINDS` naming an existing shape, or one function
in `monster_art.py` and one entry in `_SHAPES` when it needs a new one: nothing about a
creature's look belongs in `monsters.py`, and no kind may be told apart by colour alone.

What sits above the silhouette is deliberately shared by all of them (the ground shadow saying
it stands on the ground, the idle breath saying it is alive, the eyes saying it has seen you),
because those three are what get read first and they must not vary per kind.

## Nothing on legs slides across the ground

`Gait` (`game/entities/entities.py`) is one walk cycle advanced by the distance actually covered
rather than by the clock, held by every `Entity` and by `Critter`, and read once per frame by
whatever draws the thing. So a rooted monster, a villager pinned against a wall, an animal
wading a river and a corpse all stop animating for free, nothing has to be told how fast it is
going, and the arms, the legs, the body bob and a monster's rocking all come off the same
number. New artwork that moves reads that number; it does not keep an animation clock of its own.

## An animal's behaviour is its species' `temperament`, nothing else

`CritterKind.temperament` ("passive"/"retaliate"/"predator"/"guard") is the single switch behind
whether a `Critter` runs, fights back, hunts on sight or takes its village's side, and
`Critter._should_hunt` is the one place that reads it. Adding an animal means adding a row to
`CRITTER_KINDS`, not a subclass and not a new branch in `World.update`.

Dogs are that table's one deliberately placed kind (weight 0): a village or camp stands them up
and owns them, which is why they carry `village_key` / `camp_id` while wildlife carries neither.

Fleeing is a commitment, not a jitter: a fleeing animal picks a heading and bends it only
`FLEE_TURN_RATE_DEG` a frame, sprints for its `stamina_ms` and then trots at `TIRED_MULT`, so
catching one is a question of its wind rather than of out-turning it.
