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

A chaser holds the way round it picked. Both ways round a rect cost the same to within a
pixel from anywhere near the middle of one, so the cheaper of the two flipped from frame to
frame and the body rocked on the spot: `_detour_corner` remembers the corner on the chaser
itself (`Entity.route_corner`) and gives it up only when the other way is properly shorter
(`World.ROUTE_SWITCH_MARGIN`) or when nothing is in the way any more. It is `door_commit`
for the open ground, and for the same reason.

Whether a corner can be walked to is asked of the solid itself, while the corner returned
stands off it by the body's radius. Asking the grown shell both questions meant a goal
leaning against a wall was inside every candidate route's obstacle, every way round came
back barred, and the chaser walked flat into the wall the player was standing at. The one
goal allowed to lie inside a shell is the doorway of the building that shell belongs to,
which `chase_waypoint` names (`through`): walking round that building would be walking away
from its door. The same holds inside a room, where the shells are the furniture: the thing
being walked *to* is never walked round, or a villager sent to the foot of their own bed is
routed round the bed.

Two more things about a corner, both of them bodies that stopped where nothing was wrong.
A corner is a step and never a destination, so whoever is walking to one has to be told the
difference: `_hunt` always knew it, `NPC._run_to` did not, and a villager running for a door
or walking home to bed arrived at the corner of a house and stood on it. And a one-corner
route whose corner is already underfoot answers with the goal rather than with that corner,
since the route was only costed because the way on from it is clear; answering with the
corner is telling a body to walk to where it already stands.

A body halfway through a doorway is standing in the wall rather than on the floor, so
`building_at` disowns it and the route was costed as if it were out in the open: every way
round the shell it is standing *inside* comes back barred, and it was sent flat at whatever
it was chasing, into the jamb beside the gap it was walking through. A doorway belongs to
its building (`World.doorway_building_at`, the leaf's own rect and not the doorstep), so a
body in one goes through `_door_goal` like anything else and walks square out of the gap.

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
Every mover runs through it each frame, the player included: a leaf shutting on somebody is
exactly how a body ends up inside a solid, and the player used to get one only on a chunk
change, which is a step they cannot take while wedged.

Nothing is ever sealed inside a leaf in the first place. `Game._use_door` already stepped the
player out of a door they shut around themselves; `World.shut_door` (a villager taking shelter)
and `World.clear_gateways` (a settlement barring itself) do the same for whoever else is standing
in the opening, through `Building.clear_of_door` and `Village.gate_side_point`. Neither is a ring
search: an opening is the one gap in that wall, so the way out of it is a single step in or out.

## A body that means to move and does not is prised out

`World.unstick` answers a body standing *inside* something solid: from in there every step is
refused, so it never gets out on its own. `WorldNavigation.unwedge` answers the other half,
which nothing could see. The inside corner of an L, the neck between two houses, the pocket
behind a doorstep: the body is on perfectly legal ground there and every test it makes passes,
it simply has a wall on both axes and a slide (`step_along`) that carries it into neither. A
villager wedged in the corner of a building stayed there for the rest of the session looking
like a bug, because from the inside it is not one.

Only time tells the two apart, so time is what is measured: meaning to move and covering less
than `Entities.WEDGE_STEP` a frame for `Entities.WEDGE_MS` is being wedged, and the way out is
a spot with real clearance round it (`Entities.WEDGE_CLEARANCE`), which is exactly what a
corner does not have. Whatever it was strolling to is dropped with it: that target was the
reason it walked in there.

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

## A monster that has seen nobody is living, not waiting

Every monster carries the same `Wander` a villager and an animal do, anchored on where it was
stood up, and walks it whenever it is unaware and free to move. Before that, a monster did
nothing at all until the player crossed its detection ring, so the world was full of bodies
standing perfectly still facing nowhere: every cave mouth read as an ambush laid in advance
rather than as somewhere things lived. Anything with a post to hold takes `Monster.post_at`
(a camp's fire, a room in a tunnel) and roams on a short leash instead, so a garrison is
still a garrison. The frame it needs for that is why `_update_monsters` never skips anything
on screen, whatever its detection range.

## A disguised monster is drawn as what it is pretending to be

The husk (`MonsterKind.disguise`) is built out of the same three pieces a villager is, a body
and two arms, because anything more inventive would be spotted across a field and the whole
kind is the moment it is not. Until it reveals it does not move, does not swing, does not
notice, has no health bar, and its eyes carry only `Husk.DISGUISE_EYE`. The tells are in the
silhouette and nowhere else: too grey, too still, arms hanging too low and unevenly, a seam
down the front.

Two rules keep it honest. It only ever unmasks for the player (`World._monster_target` hands
a disguised one the player whatever is nearer), because what it is wearing is worn for the
player's benefit and spending its one moment on a passing farmer wastes it. And the reveal is
a lunge, not the start of a chase: `Husk.LUNGE_MS` at `LUNGE_SPEED_MULT`, after which it is
an ordinary monster that happened to start the fight standing still. A husk that has opened
stays open across a save; the ambush is spent.

## A boss arrives, and everything within earshot answers it

Three rules, all of them about a boss being an event rather than a large monster.

*It arrives.* Every boss spends `Boss.RISE_MS` climbing out of the ground before it is a
fight at all: rooted, drawn as a hole widening under it with cracks running out, and the
roar, the white flash, the shake and the banner all landing on the frame it finishes. The
thing that matters most in the world is the thing that may least afford to appear from
nowhere. One loaded out of a save is already standing there and does not climb out again.
The climb waits for somebody to watch it (`Boss._witnessed`): every boss is updated wherever
it stands, so one that rose on its own would spend the loudest moment in the game on an
empty screen, whether it was a quest target stood up thousands of paces out or a boss on the
surface while the player was down a tunnel. It waits, and it arrives when they walk up.

*A settlement answers it.* `WorldSocial.militia_orders` counts bosses among the intruders,
at their own wider `Villages.BOSS_DEFEND_RADIUS` / `BOSS_PANIC_RADIUS`, and a slam catches
the villagers standing in it. None of it is the player's doing, so every one of those blows
goes through `by_player=False`: the village is never provoked by it and nothing it costs
them is charged to the player.

*A phase is a different fight, not a bigger number.* Enrage is one such step and
`BossKind.shrinks` is the other: a shrinking boss walks down `Boss.SHRINK_BANDS` as its
health falls, rebuilding its own `MonsterKind` each time, so it opens as a slow wall to be
kept away from and ends small, quick, charging and finally shovable. Both are written as a
replacement kind rather than as branches, because everything about reach, mass, collision
and drawing already reads the kind. Difficulty-by-distance still never touches a stat block;
this is a boss's own arc through one fight.

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
