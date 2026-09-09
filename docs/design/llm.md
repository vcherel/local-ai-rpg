# LLM

The model runs on a background thread via `LLMRequestQueue`. Never call `llama_cpp` directly from
the main thread.

The model is optional. `llama-cpp-python` has to be compiled against the local CUDA toolkit and
the weights are three gigabytes, which between them are more than someone who only wants to see
the game will do, so neither is a dependency: `model_available()` answers once per session (the
binding importable, the file at `Hyperparameters.MODEL_PATH` on disk) and with no model every
public call in the queue is served by `llm/offline.py` instead. That module is one local answer
per category rather than a branch at each of the nine call sites, and the categories whose
failure the game already survives (a quest analysis that found nothing, a shop the model did not
stock, a death taunt) answer with an empty string and fall through to the fallbacks written for a
model that answered badly. What offline mode has to write itself is what the game cannot do
without: the greeting and the reply in the dialogue box, an NPC's name, a settlement's name, the
world's opening lore. `fetch-model` is the only thing that downloads the weights and `doctor`
is what explains a machine that has them but cannot use them, both deliberately outside the game
so nothing large or slow ever happens because somebody pressed play.

Calls are served in priority order: the categories in `INTERACTIVE_CATEGORIES` (the dialogue the
player is waiting on) go ahead of background work, so quest analysis queued as one conversation
closes does not hold up the next NPC's greeting. Ties break on arrival.

A running call cannot be preempted, so anything the main thread streams must pass `poll=True`,
which drains the chunk queue instead of waiting on it and yields `None` when there is nothing new.
Blocking there froze the game until the call finished. `llm_busy()` is what stops the player
opening a conversation on top of work already in flight.

Cost is controlled by batching rather than by retrying: `merchant_system.generate_shop_inventories`
stocks every merchant in a town in one call and falls back to `loot.roll_shop_stock` for any shop
the model failed to fill, and a merchant's later restocks are rolled locally. Names and death
taunts are generated ahead of need into a persisted buffer, so nothing the player is waiting on
ever blocks on generation.

A reply is not trusted: streams are cut at the first line break and capped
(`Hyperparameters.DIALOGUE_MAX_TOKENS`, `DIALOGUE_STOPS`), a capped reply is trimmed back to its
last finished sentence, the quest parser repairs the model's near-JSON and reads booleans as text
(plain `bool()` read `"false"` as true and handed over quests the player had refused), and a
response that will not parse ends as "no quest" and is recorded through `llm_log.log_parse_failure`
rather than printed and lost.
