# Settlements

## A building is one rect or two

`Building.footprint()` is what it is built of, `bounds` is the box that fits it (the
chunk index, chase detours and the tree and bear-trap clearances all ask for that), and
`rect` stays the main block the facade hangs on, so the door, the windows, the awning and
the doorstep never learn about wings.

The wing is snapped flush against its block rather than left where the rotation put it
(`_snap_wing`): the canonical room is turned by rounding a centre, and a wing whose depth
does not share the block's parity lands a pixel off, which is a hairline of grass between the
two halves and a seam in the wall shell nothing ever closes. `_wing_opening` is measured off
the wing where it actually stands for the same reason: two roundings of one rect are two
rects, and the one the walls are cut with has to be the one the floor is drawn from.

Where a building *is* and what it *stops* are two questions. `blocks` is the second one and
answers False for the open floor of a room, which is right for anything walking about in one
and wrong for anything being placed: asking it is what put a barrel in the back room of an L
and a dog on a roof. `Building.covers` is the first one, and everything that scatters
something on the ground goes through it (`World.on_building` is the same question asked of a
whole world).

The two halves are joined by exactly one rect, `_wing_opening`: subtracted from the wall
shell it is the way through, taken as a floor it is what makes `interior_rects` one
connected space, which is the same trick a tunnel's corridors use. Furniture then has to
respect it: `_RoomSpace.keep_clear` holds every way through a room (the corridor in from
the door, the neck of an L), `add` nudges a fixed piece out of one and `try_place` rolls
over every floor, because a table dropped in the neck walls half a building off and a
wing nobody can walk into is worse than no wing at all.

An interior is the building's own footprint in world space, not a separate coordinate
space or screen: `Building.interior_rect()` is the footprint inset by
`Buildings.WALL_THICKNESS`, and `Building.blocks()` collides against a thin wall shell
(with a permanent door-sized gap) plus furniture, instead of treating the whole footprint
as one solid block. `Game.interior` is recomputed every frame from the player's position
(`world.building_at`) rather than tracked as an enter/exit mode switch; there is no
teleport, no separate indoor monster/projectile lists, and `World.update` /
`World.handle_attack` always run against the one `world.monsters` / `items` /
`projectiles`. `GameRenderer.draw_world` draws every building normally except the one the
player is standing in, which `Building.draw(..., player_inside=True)` renders as a
roofless cutaway so the rest of the map keeps drawing around it in the same pass.

The interior is laid out once in a canonical room whose door is in the bottom wall and
then turned onto the real one by `_place`, so every arrangement can go on saying "against
the back wall" and mean it.

## A settlement is a square with lanes off it, and every door opens onto one

Slots are handed out from the plaza outward and the buildings are built biggest first, which
put every special a town had on the same corner of the square: both taverns side by side and
the shops next to them. `_assign_slots` deals the specials first instead, each one taking the
nearest free slot that is at least `SPECIAL_MIN_GAP` from another of its own kind, and the
houses fill what is left. A settlement has one of each thing per quarter of it rather than a
row of them on one side.

Keeping the boxes apart is not the same as leaving the doors usable, so `_clear_doorsteps`
runs with the separation passes: a building whose front opens onto a neighbour's wall pushes
whichever of the two stands further from the plaza off its doorstep, the same outward shove
overlapping footprints get. `Building.doorstep` is that piece of ground, and it is also what
nothing may be planted or scattered on (`generate_breakables`, `generate_chunk_scenery`).

The lanes are then worn between the houses by `Village.plan_streets`: one from the edge of
the plaza out to every front door, plus the rim of the square they all leave from. They are
held on the village and drawn with it rather than generated into a chunk's scenery, because
a street belongs to the settlement and reaches into whichever chunks it likes, and nothing
solid grows on village grounds for it to have to be kept clear of. Nothing about them is
saved: they are worked out from where the buildings ended up, and the buildings are in the
save.

## Nothing walks the whole building list per frame

Buildings and village wells are bucketed by chunk (`World._index_buildings`), and
collision (`blocked`, `building_at`), swing/window tests, chase detours and the renderer
all go through `buildings_near` / `buildings_in_range`. The list only grows as the player
finds villages, so a full scan would make the game slower the more of the world had been
seen.

## A door is the one obstacle a monster may break

Because it is the one that cannot be walked round. Every door starts shut and is part of
the wall shell while it is (`Building._wall_segments`), the player opens and shuts it with
E, and a chaser that ends up on the wrong side either lets itself in (a villager,
`World.open_door_for`: it is their street) or beats it down (`WorldCombat.bash_doors`,
several swings, audible, permanent once through). Nothing else about the world may become
breakable to let a monster take a shortcut: if a monster cannot reach the player, the
answer is navigation, not demolition.

## A town is walled and the wall is one thing

`Village.defences()` is a ring set outside the last house, with a gate in the middle of
each side, a gatehouse either side of every gateway and a tower at each corner, solid
through the same `Village.blocks` the well already went through and bucketed by chunk with
it (`World._village_solids_by_chunk`). Its stretches are handed to `World._detour_corner`
(`walls_near`) so a chaser routes round one to a gate instead of grinding on it: every
stretch runs from a corner tower to a gatepost, so rounding its end *is* walking to the
nearest way in. A gate on every side is deliberate, so walling a town in never turns an
approach into a dead end.

Who stands on it is not a new kind of person: `World._post_guards` puts an ordinary
villager at each gate, tower and wall stretch with `is_guard` set, which only means they
always take up arms (`NPC.is_militia`), carry a real weapon and hold their post instead of
strolling. An archer stands *on* the tower, at its own coordinates, and is the one body in
the world exempt from the free-spot search, from `unstick` and from the crowd that pushes
in around the player: a tower is solid, so every one of those walked them off it, and an
archer who has been walked off their tower is a guard stranded outside their own wall
shooting at a player standing safely inside it. They never move at all, and never needed
to: `_loose_arrows` shoots `over_walls`, which is what a roof is for. Only `Villages.WALLED_SIZES` (and the starting town) get any of it: a hamlet
has nothing to defend with.

A gate is the only part of a wall that gives, for the same reason a door is the only part
of a house that does. The stretches, the towers and the gatehouses are never breakable:
there is a gate on every side and `_detour_corner` routes round the wall already, so
nothing is ever unable to reach anything. What a gate answers is a question the wall
created: `World._bar_gates` shuts a settlement's gates while it is angry at the player,
which is when the player is inside a town that wants them dead, and
`WorldCombat._hit_gate` / `bash_gates` let them hack their way out (or a pack beat its way
in) on the same hit-point pool a front door uses. `gate_broken` is persisted, `gate_hp` is
not, exactly as a door does it.

Shutting a town takes a real escalation, not one cross word. One villager turning (a caught
thief, most often) is a fight, and its gates stay open through it: a settlement bars itself
only once it holds a grudge (somebody was killed here) or `Villages.BAR_GATES_MOB` of its
people are after the player at once. Being shut in should mean the town has decided
something, not that one farmer has.

And a shut town is not a box. The bar can be heaved up from the inside: `Game._lift_gate` is
the one interaction in the game that is held rather than pressed, `Villages.GATE_LIFT_S` of
standing still with both hands on the beam, with a blow landing costing
`Villages.GATE_LIFT_HIT_LOSS` of it and letting go of the key costing the lot. It ends with
`Village.lift_bar` swinging the leaves and the player stepped across the gateway exactly the
way the settlement's own people cross it (`gate_side_point`). Breaking the gate is still
there and still faster; the difference is that hacking through is now a choice about time
rather than the only door out.

A barred gate is a wall to the player and to every monster, and it is not one to the
settlement's own people: `World.pass_gate_for` lets a villager who reaches their own gate work
the bar and step across it, `Village.let_through` swings it open while they do and shuts it
behind them. It is the same asymmetry as `open_door_for` against `bash_doors`, one street
further out: the mob pours out after you, and the gate is still shut when you turn round.
Whether a gate is what stands between two bodies is `Village.gate_between`, the side of the
gateway's own line each of them is on. `contains_point` cannot answer that and reading it as
though it could is what left a pack standing quietly at a barred gate: the grounds are a circle
drawn round the whole settlement and reach well past the wall on every axis, so two bodies
either side of the north gate are both standing in them.

The leaves swing rather than blink (`Village.advance_gates`), open meaning folded back against
the inside of their own wall, since a gate stands open nearly always. It is drawing alone:
`gate_closed` flips on the frame a settlement turns and the leaves catch up with it.

## How well defended a settlement is is one number

`Village.tier` is rolled once from the distance to the world centre and the size, then
persisted with the village like its wall, and *everything* that makes a deep wilds town
different from a border hamlet reads it: the wall's material and thickness, its towers'
size, how many guards stand on it, whether any of them carry a bow, whether there are
stakes and a ditch outside it, which weapon ladder its militia and guards draw from, and
how much health its people have. Adding a new difference between settlements means adding
a row indexed by tier, not a new flag. It is the same idea as `MonsterKind.min_distance`,
pointed at a place rather than at a creature: walking further out should be visible before
anything is fought.

## A village is made strong in numbers, in health and behind its wall

Never in what its people are carrying. A farmer owns no weapon: `Entities.VILLAGER_WEAPONS`
is a shelf of tools, all of it resolving to the `tool` archetype (short, slow, feeble), and
the fallback for an unrecognised name is deliberately still the sword, which is why a tool
needs a keyword rather than just a name. What buys the strength back is
`World._set_toughness` (health per tier and per role, the one place a villager's health is
set), `Villages.VILLAGERS_PER_HOME_BY_SIZE` and the wall itself. A villager who hits harder
is the one change that is not allowed: it turns every street into a fight the player cannot
walk away from.

A villager fights with whatever they own, and what they own is a name. `NPC.weapon_name` is
rolled off the same home seed the militia flag is, out of three pools (a tool for a farmer,
a weapon for the militia, a soldier's weapon for a guard), and `weapon` resolves it through
the ordinary `weapon_archetype`: reach, damage and cadence all come off the table the
player's own weapons use, and the thing is drawn in their hand through the same
`gear.draw_weapon`. Adding a villager weapon is a name in a tuple, not a branch in
`NPC._hunt`.

## A village defends itself, and who defends is decided per person

A monster is retargeted by `World._monster_target` onto the nearest villager it can reach
and see instead of filing past them toward the player (a camp guard is exempt: it holds
ground rather than raids). Reach and sight, not a settlement's grounds: keying it to the
grounds left the woman standing twenty paces outside her own gate ignored by the wolf beside
her, which reads as the world not seeing her at all. `World.militia_orders` then works out once a
frame what everyone does about it: whoever `NPC.is_militia` says takes up arms goes to meet
it, everyone else runs for the nearest door and shuts it behind them. Villagers killed in
that fight are dead for good, resolved as `by_player=False` so the village blames nobody and
the player is paid nothing.

`Monster.move` and `NPC.update` both hand their swing's damage back rather than applying
it, because only the world knows whether a blow goes through the player's shield or off a
villager's health, and that is what let one chase routine serve both.

## Violence against a villager is a whole-settlement event, and a timed one

Any blow landing on an NPC goes through `WorldCombat._resolve_npc_hit`, which calls
`World.provoke_village`: every NPC inside that village's radius turns hostile at once,
their affinity floors and their quests are dropped. That anger runs on a clock
(`Villages.ANGER_S`, extended by each new offence up to `ANGER_CAP_S`, counted down on the
minimap's village strip) and expires back to `Affinity.FORGIVEN`, so a brawl is something a
village lives down. A death is not: killing a villager calls `World.hold_grudge` instead,
which sets `NPC.grudge` on the whole settlement and no clock ever clears it. Quests dropped
by a provocation stay dropped, and `EventSystem._generate_crisis` refuses to hand a new one
out in an angry village, which was the last path that still did.

Nothing turns a village on the first offence, and no settlement counts one kind of offence
against another. `World.strike_village` keeps a ledger per settlement *per kind*
(`Villages.OFFENCES`: violence, theft, trespass, damage): the first of each is a warning and
the second of the same kind inside `Villages.STRIKE_WINDOW_S` is what provokes the place.
One global counter meant the player spent their last warning on something they had no way of
connecting to what they were about to do, and heard "I saw that, put it back" about a bed.
Each kind carries its own shouts for exactly that reason: the wording is the only thing that
says which ledger was just spent. The countdown is drawn on its own strip under the minimap
(`Minimap._draw_strips`, read through `World.warnings_at`), because a warning whose end the
player cannot see is a trap rather than a warning.

Theft is the one exception to the all-or-nothing rule and it has exactly one entry point:
`Game._check_witness` asks `World.theft_witness` who could see the player empty a chest, and
`World.catch_thief` turns that one villager, alone, while the rest of the settlement goes on
with its day. A bed is asked about differently (`World.squatter_witness`): sleeping is not an
instant somebody either had eyes on or missed, it is a night, so what answers for it is who
of that settlement is near the bed by morning rather than who was facing it.

Being seen is a field of view with rooms in it, not a radius and not a raycast: `NPC.sees`
tests `Crime.VIEW_CONE_DEG` off the villager's own facing, and `World.can_see` then asks
which room each of the two is standing in (`World.theft_room` is the building the theft
happens in). Out in the open, anyone else out in the open sees you. Inside a room, whoever
is in it with you sees you and whoever is inside a different building sees nothing, having
their own walls and their own roof between. From outside, a room is open along the wall its
door and its windows are in: a villager in front of the facade sees straight in, one round
the back does not, which is why the far side of a house is worth walking to.

That is the whole test and it is a handful of comparisons per villager. It used to be a ray
per villager per frame, marched in half-wall steps against every solid nearby, which cost
more than everything else on screen put together: a tavern with ten villagers outside ran at
one and a half frames a second, of which 99% was casting the cones.
`GameRenderer._draw_witness_cones` draws the wedge whole while a chest or a bed is in reach,
unclipped, because nothing clips the rule either: a cone that reaches the player and stays
pale is a villager the walls have already answered. The prompt names whoever is currently
watching, so waiting for a back to be turned is still the mechanic. Its price is that a
villager stops turning to greet the player while the player is inside a building
(`face_player`), since a cone that always points at you is not a cone.

Escalation is the player's own doing: swinging back at whoever caught them lands in
`_resolve_npc_hit` like any other blow and turns the whole village. No other path may turn a
single NPC hostile. The second exception is not the player's doing at all: a monster's stray
arrow can kill a villager, and `_resolve_npc_hit(by_player=False)` skips the provocation,
because the village has nothing to blame the player for.

## An angry village fights the way it defends itself

The split `NPC.is_militia` makes about a monster in the street decides what the mob does
about the player too (`World._mob_orders`): the militia close and swing, everybody else
keeps `Villages.MOB_STANDOFF` back and throws stones, which is a real threat in numbers and
cannot be answered with a sword. A mob also breaks, and the same split says how: anyone cut to `Villages.ROUT_HP_FRAC`
(`NPC.routed`) leaves the fight, whoever took up arms for the place by falling back shouting
for help (`World.call_for_help`, once each, and every calm villager in earshot joins), and
everybody else by throwing down their weapon (`World.yield_to_player`). A villager who has
yielded kneels under a white flag with empty hands, is nobody's enemy for
`Villages.SURRENDER_S` (`NPC.surrendered` outranks even a grudge), and then gets up and runs
for a door like anyone else; nobody yields twice. Cutting one down is the single offence with
no ladder under it: it turns the settlement on the spot.

This exists because a villager quietly ceasing to attack at low health reads as a broken
villager rather than a beaten one. The rule is that a state the player can see the
consequences of has to have a cue they can see too: a white flag, a shout, or nothing.
Nothing here is a new kind of villager, only a new thing to point the existing split at.

## A merchant's shelf is a clock

`NPC.restock_at` is persisted wall time, `World._restock_merchants` tops the stock back up
to `Villages.SHOP_STOCK_TARGET` when it runs out, and the shop menu counts it down so
buying a merchant out is a decision with a known price in time. The delivery is rolled
locally through `loot.roll_shop_stock`: one LLM call per shop per restock is exactly the
cost the batched generation in `merchant_system.py` exists to avoid, and what is already on
the shelf is never replaced, only added to.

## A bandit camp's garrison is a number, not a set of monsters

`PointOfInterest.guards_alive` / `leader_alive` are persisted with the camp;
`_populate_camp` stands that many bandits up when the chunk loads, `_unload_chunk` takes
them away with it, `World.serialize` never saves them, and `on_guard_killed` is the only
thing that lowers the count. So a camp costs the same whether the player has found one or a
hundred, killing four of five guards survives walking away and reloading, and clearing a
camp is recorded rather than inferred from who happens to be loaded. Guards are tagged
`Monster.camp_id` (with `camp_leader` for the one worth remembering), which is what keeps
them out of the distance despawn, out of the roaming population cap and out of the save.
They come back at full health, which is the one thing the count deliberately forgets.
