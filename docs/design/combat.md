# Combat

## A weapon family answers a question; it is not a rung on a ladder

Rarity and affixes already carry the numbers, so `WEAPON_ARCHETYPES` progresses sideways:
the spear pays a blind spot and buys a lane through a line of chasers plus a shove that
puts whatever closed back out at the end of its shaft, the pole barely hurts and moves
people (into a river, onto a bear trap, off a ring that has closed round the player), the
boomerang costs no ammo and only one is ever in the air, and a staff's element
(fire/frost/storm, read out of the weapon's own name by `weapon_archetype`) points an
existing mechanic at whatever the bolt hits rather than adding one. A new family belongs in
that table naming what it is for; a weapon that is only a bigger number is a rarity roll,
not a family.

## A cleaving weapon is worth aiming

`WorldCombat._cleave_falloff` scales what each target takes by how far it is off the facing
and off the reach, down to `Combat.CLEAVE_MIN` at the edges, and the swing then carries on
into the hostile groups beneath the one it engaged (a monster and the angry villager beside
it both take it) while never touching the peaceful ones, so hunting an animal in a crowded
street still cannot start a brawl. The drawn arc is unchanged: it says what the swing
covers, and the damage numbers say what each part of that cover was worth.

`_swing_at_bodies` walks one table of target groups in priority order (bosses, monsters,
whatever is already fighting back, peaceful wildlife, peaceful villagers), stopping at the
first with anything in reach; each row carries a `hostile` flag, and that flag alone is what
a cleave carries on into, so reordering the table can never quietly widen a sweep onto
bystanders.

Whatever the hit test accepts is exactly what `core.swing_arcs` draws, so a cleaving weapon
visibly sweeps what it is about to hit, a thrust visibly covers its lane, and neither catches
anything behind the player.

## A shove is an impulse, not a teleport

`WorldCombat._knockback` hands its target a velocity (`entities.apply_impulse`) sized so the
body coasts exactly the weapon's `knockback` as it decays, and `World.advance_impulses`
spends it over the following frames with the same collision every step takes, so a shove into
a wall stops at the wall and the body is visibly off its feet (`staggered`, its own step
skipped while it still turns, swings and bleeds) for as long as it is travelling. That is what
makes the pole a weapon: its whole job is moving people, and moving people has to be something
that happens on screen rather than a body appearing at the far end of a room.

## Magic is not free, and what pays for it is its own stat

A staff spends no ammo and closes no distance, which used to make it the strictly better
weapon; now every bolt costs `WeaponArchetype.mana_cost` out of `Player.mana`, a pool that
refills on its own so magic is paced rather than rationed, and a staff that cannot pay simply
does not fire. The `magic` stat is what a caster is built out of and it overlaps nothing: it
is trained by casting alone, and it buys the bolt's damage (where a swing reads strength and
never this), the size of the pool and how fast it comes back. So a swordsman who picks up a
staff is holding a beginner's weapon, which is the point. A new magic weapon belongs in
`WEAPON_ARCHETYPES` with a `mana_cost`, not beside the pool.

## Nothing the player did not do pays the player

Friendly fire (a monster's arrow catching another monster, an animal or a villager) resolves
through the same `_resolve_*_hit` methods with `by_player=False`, and that flag is the single
switch for every reward and consequence attached to a kill: xp, hitstop, lootbox, quest
counters, pack aggro, the village turning. The kill itself always happens; only the credit is
withheld.

Three things deliberately survive an uncredited kill, because they are world state rather than
reward: a bandit camp's garrison count (`on_guard_killed`), the body's dropped item, and the
purse beside it, both of which are lying on the ground for anyone to take.

## Nothing in the world breaks in a single hit

Furniture, crates, barrels, pots, bushes, windows, doors and wilderness caches all take the
swing's damage off a hit-point pool and only give on the blow that empties it. Where that pool
lives follows what the thing already saves: a `Breakable` persists its own `hp`, a building's
furniture/windows keep theirs session-only (the save records what broke, not how far along the
rest are).

Every stick of furniture in a room comes apart, not only the crates
(`Buildings.FURNITURE_HP` per kind), because a room where one box out of six reacts to a
sword reads as scenery with a bug in it. The bed is in that list too, and a broken one drops
out of `interior_layout()["beds"]`, so the room loses the night's rest with it: that is the
player's to spend if they want to, and an exception carved out for it would have been the
one piece of a room that ignores a sword. The chest is the only thing left out, being a
container rather than furniture. Wrecking somebody's room is a
crime like emptying their chest (`World.report_crime`), which is why the witness cones are on
the ground the whole time the player is standing indoors rather than only over a chest, and a
POI's `cache_hp` is session-only because a POI is rebuilt from its chunk seed anyway.

The pool is never invisible: every one of them draws its own wear through `core/damage_fx.py`,
so a prop that is nearly gone looks nearly gone, and a blow that did not finish something still
visibly landed on it.

## The keg and the creeper

The one exception to "everything breakable is loot or scenery" is the powder keg, and it is
there to answer a different question: how do you kill a crowd without a better weapon?
`WorldCombat.explode` hurts everything near it, the player included, chains into other kegs,
and pays nothing at all, so a keg is a piece of ground worth fighting over rather than another
barrel. It is also the only prop a projectile interacts with: shooting one from across a
clearing is the plan the mechanic exists for.

The creeper is the same blast with nobody holding it: it walks up, plants itself and burns a
visible fuse, so the answer is to kill it, shove it or leave the ring it has drawn. Nothing it
kills pays the player, the bear trap's rule, because the reward for a creeper is killing it
before the fuse runs out.

## A bear trap is the only thing that stops movement with no wall in the way

`Entity.root(ms)` (and `Critter`'s own copy of it) is a timestamp every mover checks in its own
step routine, so a rooted thing still turns, still swings, still shoots and still bleeds; it
simply does not get anywhere. Nobody owns a trap and nobody aimed it: `WorldCombat.snap_traps`
tests the player, monsters, wildlife and villagers against the same `catches`, the first one to
stand on it springs it, and it resolves `by_player=False` because the player did not set it.
That is also the whole of what makes it a tactic rather than a hazard: the seconds it buys are
usable by whoever is not in it.

The bite is deliberately heavy (`Traps.DAMAGE`) and it bleeds like any other wound, so a careless
walk out of town costs a real part of the health bar and not only the wait. The wait itself is the
player's to take back: every movement key pressed works the leg loose, and the keys to press are
drawn under the struggle bar (`GameRenderer._draw_struggle_keys`), because a bar draining on its
own says "wait" and the whole point of the trap is that it does not have to.

## Projectiles

An arrow is not choosy about whose it is: a monster's shot that misses the player hits whatever
is standing behind them. `Projectile.update` advances in hops no longer than the projectile is
wide, since a whole frame at once let an arrow cross a 16px wall whenever the framerate dipped.
Everything about a shot lives in `projectiles.py` rather than `combat.py` for one reason: an
arrow has a lifetime of its own, where a swing resolves and is over.
