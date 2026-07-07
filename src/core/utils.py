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


def parse_shop_inventory(response: str) -> list:
    try:
        response = response.strip()
        # Strip markdown code fences
        response = re.sub(r"```(?:json)?\s*|\s*```", "", response).strip()
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return []
        json_str = match.group(0)
        # Fix common small-model JSON deviations
        json_str = re.sub(r":\s*True\b", ": true", json_str)
        json_str = re.sub(r":\s*False\b", ": false", json_str)
        items = json.loads(json_str)
        result = []
        for item in items:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            item_type = str(item.get("item_type", "misc"))
            rarity = str(item.get("rarity", "")).strip().lower()
            if rarity not in (tier.name for tier in c.Rarity.TIERS):
                rarity = ""
            result.append(
                {
                    "name": str(item["name"]),
                    "item_type": item_type,
                    "rarity": rarity,
                    "price": max(1, int(item.get("price", 10))),
                }
            )
        return result
    except Exception as e:
        print(f"Failed to parse shop inventory: {e}, response: {response}")
        return []


def parse_response_quest_analysis(response):
    try:
        response = response.strip()
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            return {"has_quest": False, "quest_description": "", "item_name": ""}
        json_str = match.group(0)

        json_str = re.sub(r"([{,]\s*)(\w+)(?=\s*:)", r'\1"\2"', json_str)

        json_str = re.sub(r":\s*True", ": true", json_str)
        json_str = re.sub(r":\s*False", ": false", json_str)

        json_str = re.sub(r':\s*([^"{},\s][^,}]*)', lambda m: f': "{m.group(1).strip()}"', json_str)

        json_str = re.sub(r":\s*([,}])", r': ""\1', json_str)

        result = json.loads(json_str)

        fields = ["has_quest", "quest_description", "item_name", "reward_item"]
        result_dict = {}

        for field in fields:
            if field == "has_quest":
                result_dict[field] = bool(result.get(field, False))
            else:
                result_dict[field] = result.get(field, "")

        if result_dict["has_quest"] and not (result_dict["quest_description"] or result_dict["item_name"]):
            return {"has_quest": False, "quest_description": "", "item_name": "", "reward_item": ""}

        return result_dict

    except Exception as e:
        print(f"Failed to parse quest analysis: {e}, response: {response}\n")

    return {"has_quest": False, "quest_description": "", "item_name": "", "reward_item": ""}
