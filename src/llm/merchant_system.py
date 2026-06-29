from core.utils import parse_shop_inventory
from llm.llm_request_queue import generate_response_queued


def generate_shop_inventory(context: str) -> list:
    system_prompt = "You generate item lists for RPG shops. Reply with a JSON array only, no other text."
    prompt = (
        f"World: {context}\n"
        "Generate 5 items for a merchant's shop. Reply with only this JSON array:\n"
        '[{"name": "Iron Sword", "item_type": "weapon", "bonus": 3, "price": 25}]\n'
        'Rules: item_type must be "weapon", "armor", or "misc". bonus: 1 to 10. price: 5 to 80. '
        "Replace the example with 5 real items fitting the world."
    )
    response = generate_response_queued(prompt, system_prompt, "Shop generation", max_tokens=500, raw=True)
    return parse_shop_inventory(response)
