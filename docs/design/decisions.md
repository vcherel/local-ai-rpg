# Decisions

A decision is the model asked to pick one of a few labelled answers, and never to write one
(`llm/decide.py`). The question ends on a lettered list, and one pass over the prompt gives
the probability of each letter as the first thing the model would say. Nothing is generated
and nothing is parsed, so a decision cannot come back malformed, and it costs what the
prompt costs to read: on the GTX 1650 that is about 0.4 s for a question asked right after a
reply over the same conversation (the cache already holds everything but the question) and
about 1.5 s cold.

The probabilities are odds, not a verdict. `Decisions.TEMPERATURE` flattens them and the
answer is drawn, so a villager who will probably tell now and then does not. A question of
fact (is this conversation over, did the player accept the quest) passes `draw=False` and
takes the likeliest answer instead. What an answer is worth is always the caller's: the
model picks `insulted`, `Affinity.MOOD_SHIFT` says that is eight points. The model never
writes a number the game uses.

Every decision has an answer with no model. The caller passes `offline` odds, read off the
state of the world (a temperament, a liking, a word in the player's line through
`offline.says`), and the same odds are what a model that fails mid-call falls back to.
`prior` is the other half: game odds multiplied into the model's, for when the game wants a
base rate the model does not share (a witness mostly tells). `trust` is for a model too sure
of itself for any prior to move: below 1, that share of the answer is the model's and the
rest is the `offline` odds. Draws come off the module's own random stream, so a decision
made or not made never shifts a seeded roll of the world's.

## Who asks what

- **The conversation** (`DialogueManager`). After each reply: how the player's line landed
  (`MOODS`, into affinity, capped per conversation by `Affinity.TALK_GAIN_CAP` so flattery
  is not a farm) and whether the conversation is over, which replaced the `[END]` marker the
  model was asked to write and wrote however it liked. Before a merchant's reply: whether
  the line is a haggle and what they say to it (`Haggle.DISCOUNT`, one answer a session,
  taken off every buy price). Before any reply where a warning stands: whether the line is a
  sincere apology, which clears the settlement's warnings. The answers asked before a reply
  are written into the NPC's prompt, so what they say is what they decided.
- **The parley** (`Parley`). An angry villager can be pleaded with while the anger is the
  kind that runs out (never a grudge). Each line is judged good, poor or bad before the
  villager answers; `PLEAS_NEEDED` good ones stand the whole settlement down
  (`WorldSocial.stand_down`), one bad one or running out of lines ends it, and so does
  closing the box, since the world stands still while it is open.
- **The witness** (`WorldWitnesses.catch_thief`). Being seen is still the cones alone. What the
  witness does is theirs: raise the alarm (the ladder, as before), look away, or demand a
  bribe (`Crime.HUSH_*`, paid with E, told anyway if it does not come). They stand with a
  "?" over them for at most `Crime.WITNESS_THINK_MS`; a model too busy to answer in time is
  answered for them off the offline odds.
- **Quest analysis** (`QuestSystem.analyze_conversation_for_quest`). Was a task offered,
  was it taken, which of the eight kinds: three decisions. Only the details are written, and
  only when there is a quest, so the common conversation with no quest in it costs one pass.
- **Temperament** (`WorldStreaming._settle_temperaments`). One decision per settlement,
  once it has a name, over `Temperament.KINDS`; its whole leaning is kept as the place's mix
  and each villager is drawn from it off their own home. It is flavour and odds only: a line
  in their prompt, the rout threshold (`Temperament.ROUT_SHIFT`), and the offline odds of
  the other decisions.
- **Boss leaning** (`WorldBosses._decide_leaning`). Off the name the model just gave it,
  which of its archetype's abilities it favours, rolled `Boss.LEANING_WEIGHT` times as
  often. Never a new ability and never a stat.

## Asking well

Found on the Q2_K 7B, and worth keeping in mind for any new question:

- Asked in the voice of an angry character, the model is angry: as the villager at weapon
  point it found no plea convincing however sincere, and as the witness it almost never
  raised the alarm. Asked as an onlooker ("You judge conversations in an RPG game",
  "You narrate an RPG") the same model reads the same lines well. Tone questions about the
  NPC's own feelings (`MOODS`) are fine in their own voice; judgements about the player are
  asked from outside.
- Two options that share words blur together: "keep quiet" beside "keep quiet for coins"
  was read as one answer. Make every option say something the others do not.
- A detail in the prompt primes the answer it suggests: mentioning the player's coins made
  every witness a blackmailer, and "likes the player" made a brave one ask for a bribe.
  What the game should weigh (a liking) goes in `prior` rather than in the words.
- A decision is not always better than a written field. "Besides any money, did the NPC
  promise an object?" read most offers of coins and a thing as money only, and read them
  that way every time, where the quest's written `reward_item` lost a promised item in 4 of
  30 runs. Rewording the field did not move that, and naming what it must not hold ("not
  the item the player must fetch") made the model leave it empty. What the model writes
  there is cleaned in code instead (`QuestSystem._reward_name`): the money cut out of a
  mixed reward, and an object written where a name was asked for flattened to its values.
  What did move it was asking the field again on its own, only when it came back empty
  (`QuestSystem._promised_object`): no promised item lost in 60 runs against 10 lost. Asked
  as "what object did the NPC promise", it named the letter a delivery hands over in 6 of
  30 coin only runs; "as a reward" brought that to 1.
- Ask before the reply when the reply has to agree with the answer (a haggle, an apology,
  a plea), after it when the answer is about the exchange (the mood, the end).

## Later

Ideas that fit the same call and were not built:

- **Which world event.** `EventSystem` rolls events uniformly; a decision over the ones that
  can fire, off the lore, the hour and what the player just did, would pick the one that
  fits.
- **What a merchant wants.** Whether this merchant would want this item, off their shop and
  the lore, as a nudge on the sell price.
- **The monster in a quest.** `monster_hint` is still written and matched by name; a
  decision over `MONSTER_KINDS` would need more than eight letters, so either two rounds
  (family, then kind) or a shortlist by distance first.
- **Rumours and lies.** Whether a villager tells the player the truth about a rumour, off
  their temperament and liking, with a false rumour mark on the minimap.
- **Reward size.** Whether the quest giver is generous, stingy or fair, within the coin band
  the payout is already clamped into, instead of reading the number out of their line.
- **Bribing a guard.** The door guard on a tavern after curfew or a gate guard during a
  grudge, with the same hush machinery pointed the other way.
- **A second, smaller model.** Qwen2.5 0.5B on the CPU would let decisions run beside a
  generation instead of queueing behind it. Only worth it if the wait turns out to be felt.
