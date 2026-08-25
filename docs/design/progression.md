# Healing, economy and loadout

## Healing is scarce on purpose, and each source has one job

- potions mid-fight
- a campfire for a partial patch-up, once per fire per cooldown
- a bed for a genuine full rest
- a slow passive trickle that only starts `Player.REGEN_DELAY_MS` after the last hit

Anything that hands back full health for free (the campfire used to) collapses the whole
difficulty curve, so new healing goes through one of those four rather than beside them.

No bed anywhere is bought: an inn room is taken exactly as a villager's bed is, at the price of
being seen and of that bed going cold for `REST_COOLDOWN_S`, so a street of houses is not a row
of free full heals. A bed also costs time, which is the other half of what it is for: sleeping
runs the world forward to dawn (`Game._sleep_until_dawn` over `World.pass_time`), so the night is
something the player can put behind them at the price of whatever they had drunk, and it is
refused outright while anything hostile is close, exactly as a campfire is.

## Quests are the best coins in the game

Everything else was trimmed around that. The band a quest pays is the game's decision, not the
model's: `c.QUEST_COIN_BANDS` per quest type clamps whatever figure the NPC named in their
parting line, the prompt is told that band so the sentence and the payout agree, and the hardest
types always hand over gear as well (`Quests.ALWAYS_ITEM_TYPES`).

What stretches that band is the journey. A quest puts whatever it sends the player after a
real walk away (`World.quest_target_spot`, floored at `Quests.MIN_TARGET_DISTANCE`, and the
same floor is what a `clear_camp` looks past the nearest camp for), the distance is written
into the quest when it is given, and `quest_system.coin_band` widens the band with it up to
`Quests.PAY_DISTANCE_BONUS`. Both the NPC's line and the payout read that one function, so
they still agree. An errand finishable without leaving the square is a line of dialogue, not
a quest.

Against that, salvage is pocket money: shops pay `Stats.SELL_BASE` of a low `items.base_value`
with a ceiling under 1.0, and lootbox/crate/cache coins are all small. New income belongs on the
quest and cache side of that line, not on the "sell everything you find" side.

## Loot is collected by walking, not by a key

`Game._sweep_loot` runs once a frame: anything on the ground within `Player.MAGNET_RADIUS`
accelerates at the player and is taken on contact, which is why `Interaction` has no "item" kind
and E belongs to doors, beds, chests and people alone. Two things it refuses to do: pull an item
still hopping out of whatever dropped it (`start_pop_anim`), so a purse is seen to fall off the
body before it flies at you, and pull anything standing on another building's floor, the same
rule `GameRenderer._hidden_indoors` draws by, because loot must not come out through a wall.

## Coins on the ground are an object, not a number

A killed villager's purse is an `Item` of type `"coins"` holding its amount in `quantity`,
dropped where the body fell and credited (through `gain_coins`, so the coin-find accessory still
applies) only when somebody walks into it; it never enters the inventory and leaves the master
item list the moment it is taken. That is what lets an uncredited kill still leave money lying
there, and it is the shape any new coin drop should take rather than another instant credit.

## An item's icon is derived, never stored as a decision

`items.icon_shape(item_type, name)` is the single source of the shape, `Item.__init__` sets it
from there and `Item.from_dict` recomputes it rather than restoring the saved value, so an old
save picks up new artwork instead of keeping a stale silhouette. Nothing about an item's identity
or behaviour lives in `shape`.

## Two hands, two weapons in each, and the button never changes

The player has two weapon hands. Hand one is always the left mouse button and hand two always
the right; keys 1 and 2 pick which of hand one's two weapons is up, keys 3 and 4 do the same for
hand two. `HAND_SLOTS` is the whole arrangement, four equip slots in key order, and `active_hand`
is which of each pair is in hand.

Nothing is typed by family. Any weapon goes in any position, and what a click *does* is read off
the archetype of whatever is in that hand at the time (`WorldCombat.handle_attack(hand)` sends a
ranged archetype to `_fire_ranged` and everything else to a swing), so a bow in hand one fires on
left click and a sword in hand two swings on right. Best melee in hand one and best ranged in
hand two is only what `auto_equip_best` arranges, and only because the lower key should hold the
better weapon; the player rearranges all four by right-clicking in the bag.

An empty position is a real choice rather than a gap: pressing its key puts that hand on bare
hands, which still swing. That is why `select_weapon` returning None is reported rather than
refused, and why `gear()` simply omits a hand instead of drawing a fallback weapon.

Nothing reads a weapon slot by name. Combat, the affix helpers, `weapon_bonus` and the drawn
`gear()` all go through `hand_weapon(hand)`, and every on-hit effect is keyed by hand, so a
weapon's lifesteal can never fire off a blow struck with the other one. A projectile carries the
hand that loosed it (`Projectile.hand`) for the same reason it already carried its element: the
weapon may well be swapped before the arrow lands.

## A bomb is a weapon that is spent

Both bombs live in a weapon position like anything else and are used by that hand's button. The
mine is laid where the player stands and waits for something that would fight them; the grenade
is thrown at the cursor and burns a fuse. Neither knows what an explosion is: both end in
`WorldCombat.explode`, the powder keg's own blast, so the damage, the gore, the shake and what a
village makes of it are decided in one place. Spending the last one empties the position, and
that hand falls back to bare hands rather than quietly equipping something else.

## The shield is worn on a side, and that side is where it works

`draw_shield` puts it on the offhand side of the body, and `Player._blocks_hit` /
`shield_side_hit` read the same two wedges the sprite shows: what arrives inside
`Shield.SIDE_ARC_DEG` of the shield side is met by the face of it, what arrives on the open side
keeps only `Shield.OFF_SIDE_MULT` of the block. A hostile shot that arrives on the shield side is
turned away entirely and costs guard instead of health, so an archer can still wear a shield down
without ever landing an arrow. Anything in flight is judged by the way it is travelling rather
than by where it has got to, or a shot that stepped just past the player would read as a blow
from behind.

## What a key reaches for is a choice the player made, and it is saved

The four weapon positions (number keys) and the potion quickbar (`potion_bar`,
`Potions.QUICK_KEYS`) are both filled automatically only into a *free* slot (on pickup, through
`Player._auto_slot`) and both reassigned by hand by right-clicking the item in the inventory.
Picking up a nicer-sounding elixir can therefore never push the healing potion off the bar, and a
bomb picked up takes a position only if one is free. Arrows are the one thing equipped outright on pickup, and only when nothing
is loaded: firing is the point of carrying them, and `ready_ammo` falls back to the cheapest
stack anyway.

## The playthrough keeps two numbers, and they pay out in opposite directions

`game/record.py` holds the deaths and the quests handed in. Neither is a stat: nothing trains
them, nothing reads them to decide anything in the world, and that is exactly why they are not in
`Stats`. Both pay out at milestones (`Milestones`), and a milestone is recorded once it has paid
so nothing is ever handed out twice.

Quests pay in loot, through the same lootbox every other windfall in the game opens, because the
tenth errand should be worth something the player can carry. Deaths pay in words: each milestone
unlocks the next tier of `Death.TAUNT_TIERS`, so the game finds more to say about a player the
worse they are at staying alive. Dying is not an achievement and never pays in gear.
