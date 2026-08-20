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

## Two melee weapons are worn and one of them swings

`Player.active_melee` indexes `MELEE_SLOTS`, X swaps it, and *nothing* reads a melee slot by
name: combat, the affix helpers, `weapon_bonus` and the drawn `gear()` all go through
`active_melee_weapon()`, so carrying a spear beside a sword is a stance chosen before the fight
rather than a trip through the inventory during it. Equipping a melee weapon fills the free slot
before displacing the one in hand, and emptying the slot in hand falls back to the other one,
because a player standing next to their own spare should never be barehanded.

## The weapon bar sits on top of the equip slots

`Player.weapon_bar` is a short list of weapon ids the number keys reach for; pressing one calls
`select_weapon`, which either makes an already-equipped weapon the one in hand or equips it into
the slot its archetype belongs to. So switching a bow leaves the swords equipped, and nothing in
`combat.py` knows the bar exists.

## What a key reaches for is a choice the player made, and it is saved

The weapon bar (`weapon_bar`, number keys) and the potion quickbar (`potion_bar`,
`Potions.QUICK_KEYS`) are both lists of item ids, both filled automatically only into a *free*
slot (on pickup, through `Player._auto_slot`) and both reassigned by hand by right-clicking the
item in the inventory. Picking up a nicer-sounding elixir can therefore never push the healing
potion off the bar. Arrows are the one thing equipped outright on pickup, and only when nothing
is loaded: firing is the point of carrying them, and `ready_ammo` falls back to the cheapest
stack anyway.
