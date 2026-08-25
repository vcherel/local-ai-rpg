from core.utils import parse_shop_inventories
from game.loot import roll_shop_stock
from llm.llm_request_queue import generate_response_queued

# What each shop trades in, so a batch of shops comes back varied instead of three
# lists of the same moonlit blade. Cycled if a world ever has more shops than roles.
SHOP_ROLES = (
    "blacksmith (weapons and armor)",
    "alchemist (potions, charms and bombs)",
    "general trader (odds and ends)",
)

ITEMS_PER_SHOP = 4
# One line per item is roughly 15 tokens; leave room for the model to be a bit verbose.
TOKENS_PER_ITEM = 22


def _roles(shop_count: int) -> list:
    return [SHOP_ROLES[i % len(SHOP_ROLES)] for i in range(shop_count)]


def generate_shop_inventories(context: str, shop_count: int) -> list:
    """Stock every merchant in the world with a single LLM call.

    One call instead of one per merchant: shop generation used to be the most expensive
    thing the queue did, and the per-merchant prompts were identical, so the shops came
    out identical too. Any shop the model fails to fill falls back to a procedural roll
    rather than a second request.
    """
    if shop_count <= 0:
        return []

    roles = _roles(shop_count)
    shop_list = "\n".join(f"{i + 1}. {role}" for i, role in enumerate(roles))
    system_prompt = "You stock RPG shops. Reply with the item lines only, no other text."
    prompt = (
        f"World: {context}\n"
        f"Stock these {shop_count} shops:\n{shop_list}\n"
        f"Write {ITEMS_PER_SHOP} items per shop, one item per line, exactly this format:\n"
        "shop|name|type|rarity|price\n"
        "Example:\n"
        "1|Iron Sword|weapon|uncommon|25\n"
        "Rules: shop is the shop number. "
        'type is "weapon", "armor", "shield", "accessory", "potion", "bomb" or "misc". '
        'rarity is "common", "uncommon", "rare", "epic" or "legendary" (mostly common or uncommon). '
        "price is 5 to 80. "
        "Each shop's items fit its trade, suit the world, and differ from the other shops'. "
        "No headers, no numbering, no commentary."
    )
    response = generate_response_queued(
        prompt,
        system_prompt,
        "Shop generation",
        max_tokens=shop_count * ITEMS_PER_SHOP * TOKENS_PER_ITEM,
        raw=True,
    )

    stocks = parse_shop_inventories(response, shop_count)
    return [stock or roll_shop_stock(ITEMS_PER_SHOP) for stock in stocks]
