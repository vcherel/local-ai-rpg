# Standing

What a settlement thinks of the player and what it does about it: who saw what, the
warning ladder every offence climbs, a village turning, the blood price that buys it back,
what the country around has heard, the raid a blood night sends, and the notices pinned to
a board. The code is `game/social.py` (`WorldSocial`); the settlement it all happens in is
`settlements.md`.

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

A rout always ends in something. With no door within reach (a fight out in the fields, or a
village whose houses are the other side of a chunk border) `_refuge_for` used to give back
nothing at all and the villager fell straight through to the ordinary orders, turning round
and fighting on at full aggression at a fifth of their health. It answers with open ground
away from whatever beat them instead (`Villages.ROUT_RUN`), and `_npc_flees` takes a bare
point as happily as a building: running is a rout too.

This exists because a villager quietly ceasing to attack at low health reads as a broken
villager rather than a beaten one. The rule is that a state the player can see the
consequences of has to have a cue they can see too: a white flag, a shout, or nothing.
Nothing here is a new kind of villager, only a new thing to point the existing split at.

## A settlement can be bought back

Anger runs out on its own and a grudge never does, which left a killing as a place struck
off the map for the rest of the save: everyone in it comes for the player on sight, no
shop, no quest, no bed, and the one thing that ever cleared it was dying to that same town
(`pacify_village`). That is a fine paid by accident rather than a decision.

The blood price is the second exit and the only one the player chooses. While a settlement
is hostile, `WorldSocial.amends_at` quotes what it wants (`blood_price`: a base, a step per
tier, multiplied for a grudge, rounded to something a person would say out loud), the strip
under the minimap shows the figure and whether the purse can cover it, and K pays it
straight into the `pacify_village` a death would have run, plus `settle_deeds` for the
notoriety earned on that ground.

It is a key rather than an interaction prompt on purpose. Paying happens while the town is
chasing the player across its own plaza, and a prompt is something you have to stand still
in front of: the one thing the player cannot do there is stand still. What keeps it honest
instead is that the price is on screen the whole time, so pressing K is never a guess, and
that the coins are real money out of a purse that buys potions and gear.

## What the next village along has heard

A grudge belongs to the settlement holding it. That is right for the settlement and wrong
for the world: the player could empty a street, walk a day, and be greeted as a stranger by
a town whose road runs to the one they emptied.

A deed (`WorldSocial.record_deed`) belongs to the ground it was done on instead: a point, a
weight and the moment. `notoriety_at` sums whatever has not faded, falling off with the
distance from where it happened (`Notoriety.TRAVEL_DISTANCE`) and with the time since
(`FADE_S`), clamped so the effects have a top. A killing is most of a reputation on its own;
a brawl and a theft are worth a fraction of one.

Nothing about it turns anybody hostile, which is the whole design. What it costs is:

- a rung off the warning ladder (`strike_village`), so a place that has heard about the
  player spends its warning before they arrive
- a surcharge at every shelf within earshot, taken off the affinity swing rather than
  beside it (`ShopMenu._swing`), so a trader who likes the player and has heard about them
  charges what a stranger pays
- a line under the minimap, because a reputation nobody can read is a difficulty setting

It fades on its own and paying a settlement's blood price rubs out what was done on its
ground, which is the only thing that ever takes it back on purpose.

## A blood night raids a settlement

A blood night used to be a filter and a respawn multiplier: the sky went red, the wilds
filled up, and the answer was to spend it indoors. Everything a village is built out of (the
wall, the militia split, the gates, the tower archers, `militia_orders`) only ever answered
whatever wandered in by itself.

`WorldSocial.raid_village` points a wave at one: `Raid.SIZE_BY_TIER` monsters stood up
around the settlement's grounds, rolled with the danger bonus a camp leader takes, each
posted on the village (`Monster.post_at`) so it roams toward the place while it has seen
nobody rather than waiting to be walked into. Nothing about the fight is new; every order the
settlement gives itself is the order it always gave.

What is new is a reason to stand in somebody else's street. A raid the player took a real
part in (`Raid.THANKS_MIN_KILLS`) ends in the whole settlement thinking better of them
(`update_raid`), which is the exact mirror of `provoke_village` turning all of them at once,
and the only way in the game to move a village's opinion without a quest. A raid they
watched pays nothing.

Three things keep it from being a farm. Only a settlement the player is near enough to
reach is ever raided, since a village sacked out of sight is a notification rather than an
event; a settlement already hostile is never raided, because a town that wants the player
dead is not a town they can save; and a raider is out of the roaming population cap
(`Monster.raid_key`) and never saved, so a raid is a night rather than a permanent siege.

## A notice board is quests without the model

Every quest in the game comes out of a conversation the model wrote and then read back
(`QuestSystem.analyze_conversation_for_quest`). That makes the supply of them wait on one
busy 7B model and on the player deciding to talk to somebody, and it means a session where
the model is loaded down has nothing to do.

The board on each plaza rim (`Village.board_pos`) is the same quest types rolled locally.
`WorldSocial.board_offers` writes the same `{has_quest, quest_type, item_name, ...}` reading
the model would have produced and hands it to the same `create_quest_from_analysis`, so a
notice and a promise made in a tavern are the same object by the time anything else sees
them: the tracker, the map arrow, the coin band, the hand in and the reward are all the ones
that already exist.

The one thing a board may not do is give a quest itself. `board_poster` finds somebody who
actually lives there, is still speaking to the player and is not already waiting on a task,
and the quest goes on them, which is what makes handing it in the ordinary conversation.
With nobody free to have written it, the notice stays on the board rather than becoming a
task with no one to answer for it. The notices are the village's and session-only, like its
lanes: three at a time, rerolled once the board is worth walking back to
(`Board.REFRESH_S`), and taking one is what empties a peg.
