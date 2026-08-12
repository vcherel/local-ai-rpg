import colorsys
import json
import random
import re

import core.constants as c


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
        if item_type not in ("weapon", "armor", "accessory", "ammo", "potion", "misc"):
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


def parse_response_quest_analysis(response):
    try:
        response = response.strip()
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            return _empty_quest_analysis()
        json_str = match.group(0)

        json_str = re.sub(r"([{,]\s*)(\w+)(?=\s*:)", r'\1"\2"', json_str)

        json_str = re.sub(r":\s*True", ": true", json_str)
        json_str = re.sub(r":\s*False", ": false", json_str)

        json_str = re.sub(r':\s*([^"{},\s][^,}]*)', lambda m: f': "{m.group(1).strip()}"', json_str)

        json_str = re.sub(r":\s*([,}])", r': ""\1', json_str)

        result = json.loads(json_str)

        fields = [
            "has_quest",
            "quest_description",
            "item_name",
            "reward_item",
            "quest_type",
            "monster_hint",
            "kill_count",
        ]
        result_dict = {}

        for field in fields:
            if field == "has_quest":
                result_dict[field] = bool(result.get(field, False))
            else:
                result_dict[field] = result.get(field, "")

        if result_dict["has_quest"] and not (
            result_dict["quest_description"] or result_dict["item_name"] or result_dict["monster_hint"]
        ):
            return _empty_quest_analysis()

        return result_dict

    except Exception as e:
        print(f"Failed to parse quest analysis: {e}, response: {response}\n")

    return _empty_quest_analysis()


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
