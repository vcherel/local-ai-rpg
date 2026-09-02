import colorsys
import json
import random
import re

import core.constants as c
from core import llm_log


def frames(dt: float) -> float:
    """How many frames' worth of movement `dt` milliseconds is.

    Everything that moves is tuned per frame at `TARGET_FPS` and then scaled by this, so the
    world covers the same ground whatever the framerate is doing. One definition, because it
    was written out by hand in every step routine in the game.
    """
    return dt * c.TARGET_FPS / 1000.0


def random_color():
    h = random.random()
    s = 0.3 + 0.2 * random.random()
    lightness = 0.4 + 0.2 * random.random()
    r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, lightness, s)]
    return (r, g, b)


def random_coordinates():
    return tuple(random.randint(0, c.World.WORLD_SIZE) for _ in range(2))


class ConversationHistory:
    def __init__(self):
        self.messages = []

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def update_last_assistant_message(self, content: str):
        if self.messages and self.messages[-1]["role"] == "assistant":
            self.messages[-1]["content"] = content
        else:
            self.add_assistant_message(content)

    def get_last_message(self):
        return self.messages[-1] if self.messages else None

    def clear(self):
        self.messages.clear()

    def format_for_prompt(self):
        conversation_text = ""
        for msg in self.messages:
            if msg["role"] == "user":
                conversation_text += f"Player: {msg['content']}\n"
            else:
                conversation_text += f"NPC: {msg['content']}\n"
        return conversation_text


# The shortest thing that can still be a world: fewer words than this and the model has
# handed back a title, a label or a single noun rather than the sentence it was asked for.
_CONTEXT_MIN_WORDS = 8
_CONTEXT_MIN_CHARS = 40


def parse_world_context(response: str | None) -> str | None:
    """Read the world's lore out of a response, or return None if there is no lore in it.

    The lore is the one generation the player reads whole, on black, before anything else
    happens, and a quantized model will now and then answer the prompt with a title: one
    word, a newline, and the stream is cut there. That word used to be persisted as the
    world and written across the middle of the screen on every launch since. Guarded here
    rather than in the prompt, and the answer to a failure is nothing at all: no lore is
    read as no lore yet, and the call is made again on the next session.
    """
    text = (response or "").strip().strip('"').strip()
    # A leading label the model sometimes prefixes its own answer with.
    text = re.sub(r"^(world|context|setting|lore)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    if len(text) < _CONTEXT_MIN_CHARS or len(text.split()) < _CONTEXT_MIN_WORDS:
        return None
    return text


def parse_shop_inventories(response: str, shop_count: int) -> list:
    """Read the compact stock list of every shop out of one response.

    Each line is `shop|name|type|rarity|price`, one item per line, the leading number
    saying which shop it belongs to. A line that doesn't fit is skipped rather than
    failing the whole batch, so one malformed row costs one item, not a second call.
    Returns one list of item entries per shop, in shop order (some may be empty).
    """
    stocks = [[] for _ in range(shop_count)]
    # Strip markdown code fences and any stray bullet/numbering the model adds.
    response = re.sub(r"```(?:\w+)?\s*|\s*```", "", response or "").strip()

    for line in response.splitlines():
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if len(fields) != 5:
            continue
        shop_field, name, item_type, rarity, price_field = fields
        shop_match = re.search(r"\d+", shop_field)
        if not shop_match or not name:
            continue
        index = int(shop_match.group(0)) - 1
        if not 0 <= index < shop_count:
            continue

        item_type = item_type.lower()
        # An invented type ("consumable", "drink") is dropped so the shop falls back
        # to reading the type out of the item's name instead.
        if item_type not in ("weapon", "armor", "shield", "accessory", "ammo", "potion", "misc"):
            item_type = ""
        rarity = rarity.lower()
        if rarity not in (tier.name for tier in c.Rarity.TIERS):
            rarity = ""
        price_match = re.search(r"\d+", price_field)

        stocks[index].append(
            {
                "name": name.strip('"').strip("*"),
                "item_type": item_type,
                "rarity": rarity,
                "price": max(1, int(price_match.group(0))) if price_match else 10,
            }
        )

    return stocks


def _repaired_json(response) -> dict | None:
    """The JSON object out of one reply, with the repairs a quantized model needs.

    None for a reply with nothing usable in it, which is the only failure this can have:
    the model can fail this in any number of ways, and a bad quest analysis has to end as
    "no quest" rather than as a crash mid-conversation. Narrow on purpose, so a mistake in
    what is built out of the result below still raises instead of quietly reading as a
    villager who never offers a quest.
    """
    try:
        match = re.search(r"\{.*\}", response.strip(), re.DOTALL)
        if not match:
            return None
        json_str = match.group(0)
        json_str = re.sub(r"([{,]\s*)(\w+)(?=\s*:)", r'\1"\2"', json_str)
        json_str = re.sub(r":\s*True", ": true", json_str)
        json_str = re.sub(r":\s*False", ": false", json_str)
        json_str = re.sub(r':\s*([^"{},\s][^,}]*)', lambda m: f': "{m.group(1).strip()}"', json_str)
        json_str = re.sub(r":\s*([,}])", r': ""\1', json_str)
        result = json.loads(json_str)
        return result if isinstance(result, dict) else None
    except Exception as e:
        llm_log.log_parse_failure("Conversation analyze", response, f"{type(e).__name__}: {e}")
        return None


def parse_response_quest_analysis(response):
    result = _repaired_json(response)
    if result is None:
        return _empty_quest_analysis()

    fields = [
        "quest_description",
        "item_name",
        "reward_item",
        "quest_type",
        "monster_hint",
        "kill_count",
    ]
    result_dict = {field: result.get(field, "") for field in fields}
    # A quest is only handed over if the NPC offered one *and* the player took it. A
    # quantized model drops the field it was asked for often enough that treating a missing
    # `player_accepted` as a refusal would throw away most of the quests actually offered,
    # so the flag only ever takes a quest away.
    result_dict["has_quest"] = _as_bool(result.get("has_quest"), default=False) and _as_bool(
        result.get("player_accepted"), default=True
    )

    if result_dict["has_quest"] and not (
        result_dict["quest_description"] or result_dict["item_name"] or result_dict["monster_hint"]
    ):
        return _empty_quest_analysis()

    return result_dict


def _as_bool(value, default: bool) -> bool:
    """Read a flag the model may have written as a JSON boolean or as text.

    Plain `bool()` is not enough: the repairs above quote every unquoted value, so a literal
    `false` reaches here as the string "false", which is truthy. That is what used to hand
    the player a quest they had just turned down."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("false", "no", "0", "none", ""):
        return False
    if text in ("true", "yes", "1"):
        return True
    return default


def _empty_quest_analysis() -> dict:
    return {
        "has_quest": False,
        "quest_description": "",
        "item_name": "",
        "reward_item": "",
        "quest_type": "",
        "monster_hint": "",
        "kill_count": "",
    }
