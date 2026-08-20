# Settlements

## A building is one rect or two

`Building.footprint()` is what it is built of, `bounds` is the box that fits it (the
chunk index, chase detours and the tree and bear-trap clearances all ask for that), and
`rect` stays the main block the facade hangs on, so the door, the windows, the awning and
the doorstep never learn about wings.

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
strolling. Only `Villages.WALLED_SIZES` (and the starting town) get any of it: a hamlet
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

A monster that walks onto a settlement's grounds is retargeted by `World._monster_target`
onto the nearest villager instead of filing past them toward the player (a camp guard is
exempt: it holds ground rather than raids). `World.militia_orders` then works out once a
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

Theft is the one exception to the all-or-nothing rule and it has exactly one entry point:
`Game._check_witness` asks `World.theft_witness` who could see the player empty a chest or
climb into a bed, and `World.catch_thief` turns that one villager, alone, while the rest of
the settlement goes on with its day.

Being seen is a field of view with walls in it, not a radius: `NPC.sees` tests
`Crime.VIEW_CONE_DEG` off the villager's own facing and `World.can_see` then walks the line
for anything solid (`sight_reach`), with exactly one thing see-through, the building the
player is standing in, since the villager being robbed is on the other side of a doorway
rather than behind a wall and a strict test would make every theft free.
`GameRenderer._draw_witness_cones` draws exactly that wedge on the ground while a chest or
a bed is in reach, and the prompt names whoever is currently watching, so waiting for a back
to be turned is the mechanic. Its price is that a villager stops turning to greet the player
while the player is inside a building (`face_player`), since a cone that always points at you
is not a cone.

Escalation is the player's own doing: swinging back at whoever caught them lands in
`_resolve_npc_hit` like any other blow and turns the whole village. No other path may turn a
single NPC hostile. The second exception is not the player's doing at all: a monster's stray
arrow can kill a villager, and `_resolve_npc_hit(by_player=False)` skips the provocation,
because the village has nothing to blame the player for.

## An angry village fights the way it defends itself

The split `NPC.is_militia` makes about a monster in the street decides what the mob does
about the player too (`World._mob_orders`): the militia close and swing, everybody else
keeps `Villages.MOB_STANDOFF` back and throws stones, which is a real threat in numbers and
cannot be answered with a sword. A mob also breaks: anyone cut to `Villages.ROUT_HP_FRAC`
(`NPC.routed`) leaves the fight for the nearest door, so a village thins out as it loses
instead of feeding farmers into a blade one at a time. Nothing here is a new kind of
villager, only a new thing to point the existing split at.

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
