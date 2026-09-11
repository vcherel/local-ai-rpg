"""What the game answers with when there is no model loaded.

The weights are optional (`Hyperparameters.MODEL_PATH`, `fetch-model`): somebody who has
just cloned the repo can play before downloading three gigabytes, and everything but the
improvisation still works. Every LLM call in the game carries a category string, so this is
one local answer per category rather than a branch at each of the nine call sites, and the
categories whose failure the game already survives (a quest analysis that found no quest, a
shop the model did not stock, a death taunt) answer with nothing at all and fall through to
the fallbacks that were written for a model that answered badly.

The banks below are the one place offline writing lives. A name is composed rather than
picked so a long session does not run out, and every answer is seeded on the prompt it
replies to, so the same villager asked the same thing says the same thing.
"""

import random
import re

GREETINGS = (
    "Well met. You have the look of someone who walked a long way to get here.",
    "You are not from the valley. I would know the face.",
    "Mind the road east, it has been bad lately.",
    "If you are looking for work, read the board on the plaza.",
    "Quiet day. They are the ones I like.",
    "Careful past the treeline. Things come out of it after dark.",
    "You can sleep at the tavern if you have the coin for it.",
    "Say your piece, I have bread in the oven.",
)

GREETER_REPLIES = (
    "Come back when it is done and there is coin waiting.",
    "They are not far. Past the treeline, mostly.",
    "Mind yourself out there. We need you back in one piece.",
    "That is all I ask. The rest of us have work to do.",
)

MERCHANT_GREETINGS = (
    "Everything on the shelf is honest. Everything under it is negotiable.",
    "Have a look. I do not chase people who are only looking.",
    "Coin first, questions after. That is how I have kept the door open.",
    "You look like someone who breaks things. Good, I sell replacements.",
)

REPLIES = (
    "That is one way to see it.",
    "Aye. Half the village would say the same and the other half would deny it.",
    "I have heard stranger, and from soberer people.",
    "You would have to ask someone who leaves the valley.",
    "Times being what they are, I keep that to myself.",
    "There is truth in that, or near enough for a Tuesday.",
    "Talk to the board on the plaza, it is more use than I am.",
    "Hm. I will think on it.",
)

MERCHANT_REPLIES = (
    "Prices are prices. I did not set the world up this way.",
    "Buy something and I will remember you kindly.",
    "I trade, I do not gossip. Much.",
    "That will not get you a discount, but it was well said.",
)

# One sentence describing a world, written the way the model is asked to write it
# ("The game takes place...") so it goes through `parse_world_context` unchanged.
WORLDS = (
    "The game takes place in a green valley of scattered villages where every road was "
    "built by an empire nobody remembers, and the milestones still count down to a "
    "capital that is not there.",
    "The game takes place in a wilderness of old farms and older ruins, where the wells "
    "run deeper than they should and the villages have agreed not to discuss it.",
    "The game takes place across a country of walled hamlets that ring their bells at "
    "dusk, because the things that come out at night learned to knock.",
    "The game takes place in a land whose forests are growing back over a war, and the "
    "bones under the roots are still worth money to the right buyer.",
)

LORE_LINES = (
    "Somewhere past the ridge, something old turns over in its sleep.",
    "The roads have been quieter than the season deserves.",
    "Smoke on the horizon, and nobody willing to say whose.",
    "Travellers have started going the long way round, and paying for it.",
)

NAME_FIRST = (
    "Aldric",
    "Bran",
    "Cael",
    "Dara",
    "Edda",
    "Fenn",
    "Gerta",
    "Hale",
    "Ivo",
    "Jorun",
    "Kesta",
    "Lem",
    "Mira",
    "Nils",
    "Orla",
    "Perrin",
    "Quill",
    "Rook",
    "Sable",
    "Tam",
    "Ulla",
    "Vesna",
    "Wyn",
    "Yarrow",
)

NAME_LAST = (
    "Thatcher",
    "Ashdown",
    "Warden",
    "Coombe",
    "Fletcher",
    "Harrow",
    "Marsh",
    "Oakley",
    "Pike",
    "Redfern",
    "Stonewell",
    "Tanner",
    "Vale",
    "Wick",
)

NAME_EPITHET = (
    "the herbalist",
    "the miller",
    "the smith's daughter",
    "the ferryman",
    "the fletcher",
    "the cooper",
    "the goat-keeper",
    "the roofer",
)

PLACE_FIRST = (
    "Ash",
    "Bram",
    "Cold",
    "Dun",
    "Elder",
    "Far",
    "Grey",
    "Hollow",
    "Kirk",
    "Long",
    "Mire",
    "North",
    "Oak",
    "Raven",
    "Stone",
    "Thorn",
    "West",
    "Yew",
)

PLACE_LAST = (
    "ford",
    "hollow",
    "reach",
    "barrow",
    "cross",
    "gate",
    "moor",
    "stead",
    "watch",
    "mere",
    "wick",
    "fell",
)

LANDMARKS = (
    "The Drowned Chapel",
    "The Hanging Stones",
    "Old Kettering Hall",
    "The Sunken Barracks",
    "The Weeping Arch",
    "The Broken Abbey",
    "The Ninth Milestone",
)

BOSS_FIRST = (
    "Vorrus",
    "Ghaunt",
    "Malrek",
    "Sildra",
    "Korrath",
    "Ebbon",
    "Thal",
    "Nyx",
)

BOSS_EPITHET = (
    "the Unburied",
    "the Last Warden",
    "Who Waits",
    "of the Long Winter",
    "the Rootbound",
    "the Quiet Ruin",
    "the Toll-Taker",
)


def _rng(*parts: str) -> random.Random:
    """A generator seeded on what was asked, so the same question gets the same answer."""
    return random.Random(hash("\n".join(parts)) & 0xFFFFFFFF)


def _npc_is_merchant(system_prompt: str) -> bool:
    return "a merchant in an RPG" in system_prompt


# The greeter's errand, quoted in their prompt after `dialogue_manager.GREETER_TASK`.
GREETER_TASK_RE = re.compile(r'the errand is: "([^"]+)"')


def _dialogue(prompt: str, system_prompt: str, first: bool) -> str:
    rng = _rng(prompt, system_prompt)
    # The greeter says the errand they walked over with, not a line off the bank: their
    # quest is granted whatever they said, so what they said had better be it.
    errand = GREETER_TASK_RE.search(system_prompt)
    if errand is not None:
        return errand.group(1) if first else rng.choice(GREETER_REPLIES)
    if _npc_is_merchant(system_prompt):
        bank = MERCHANT_GREETINGS if first else MERCHANT_REPLIES
    else:
        bank = GREETINGS if first else REPLIES
    return rng.choice(bank)


def _npc_name(prompt: str, system_prompt: str) -> str:
    """A composed name, avoiding the ones the prompt says have already been used."""
    rng = _rng(prompt, system_prompt)
    for _ in range(24):
        first = rng.choice(NAME_FIRST)
        roll = rng.random()
        if roll < 0.45:
            name = f"{first} {rng.choice(NAME_LAST)}"
        elif roll < 0.7:
            name = f"{first} {rng.choice(NAME_EPITHET)}"
        else:
            name = first
        if name.lower() not in system_prompt.lower():
            return name
        rng = random.Random(rng.random())
    return f"{rng.choice(NAME_FIRST)} of the valley"


def _village_name(prompt: str, system_prompt: str) -> str:
    rng = _rng(prompt, system_prompt)
    if rng.random() < 0.5:
        return f"{rng.choice(PLACE_FIRST)}{rng.choice(PLACE_LAST)}"
    return f"{rng.choice(PLACE_FIRST)} {rng.choice(PLACE_LAST).capitalize()}"


def _boss_name(prompt: str, system_prompt: str) -> str:
    rng = _rng(prompt, system_prompt)
    return f"{rng.choice(BOSS_FIRST)}, {rng.choice(BOSS_EPITHET)}"


def _pick(bank):
    return lambda prompt, system_prompt: _rng(prompt, system_prompt).choice(bank)


# Category to local answer. Anything not listed answers with an empty string, which every
# caller already treats as the model having failed: no quest found, no boss title yet, a
# shop stocked by `roll_shop_stock`, a death screen using the canned lines in `Death`.
ANSWERS = {
    "First message": lambda prompt, system_prompt: _dialogue(prompt, system_prompt, first=True),
    "Continuing conversation": lambda prompt, system_prompt: _dialogue(prompt, system_prompt, first=False),
    "Name generation": _npc_name,
    "Village naming": _village_name,
    "Landmark naming": _pick(LANDMARKS),
    "Boss naming": _boss_name,
    "Context generation": _pick(WORLDS),
    "Event flavor text": _pick(LORE_LINES),
}


def answer(category: str, prompt: str, system_prompt: str) -> str:
    return ANSWERS.get(category, lambda *_: "")(prompt, system_prompt)


def stream(category: str, prompt: str, system_prompt: str):
    """The same answer, handed over the way the model's is: an empty first chunk, then one
    growing prefix per call, so a line still types itself into the dialogue box a word at a
    time instead of landing whole on one frame."""
    text = answer(category, prompt, system_prompt)
    yield ""
    words = text.split()
    for i in range(1, len(words) + 1):
        yield " ".join(words[:i])
