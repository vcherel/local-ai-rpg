# Bug fixes from the fuzz and read-through

## Batch 1: quest bookkeeping
- [x] A quest can be handed in twice (`complete_quest` not idempotent, second conversation queues a second completion)
- [x] `quest_target` reads `COUNTED_QUEST_TYPES` so a dead boss points the arrow home
- [x] A delivery whose recipient dies is dropped from the giver like any other unfinishable quest
- [x] Quest items are never sold: not by Sell valuables, not by a click on the row

## Batch 2: world state
- [x] `pacify_village`, `amends_at`, `blood_price` count a settlement's own people, not whoever stands on its grounds
- [x] A spent stack (potion, bomb, quiver) leaves `world.items` when it leaves the bag
- [x] `pass_time` moves the merchants' restock clocks with the other wall-clock deadlines
- [x] A villager is never stood up in a shut door leaf on the first frame

## Batch 3: threads
- [ ] Background LLM work hands its world mutations back to the main thread (quest analysis, quest completion, events with a presage, crisis)
- [ ] `NPCNameGenerator` keeps a few names ready, quotes only the recent ones in the prompt, and never hands out a duplicate
