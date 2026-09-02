"""What is on a merchant's shelf.

Mixed into `World`. A town's stock is asked of the model once, in one batched call, when
the player walks up to the settlement; everything after that (the restock clock, the
staples every shop carries) is rolled locally, because one call per shop was the queue's
biggest cost and a shelf that refills every ten minutes would put it straight back.
"""

from __future__ import annotations

import threading

import core.constants as c
from game.entities.items import AMMO_BUNDLE
from game.loot import roll_shop_stock
from llm.merchant_system import generate_shop_inventories


class WorldShops:
    """Stocking every merchant, in a batch when it is asked of the model and locally after."""

    def _restock_merchants(self):
        """Put a delivery on the shelf of any merchant whose clock has run out.

        Rolled locally rather than asked of the model: the batched generation exists because
        one call per shop was the queue's biggest cost, and a shop that refills every ten
        minutes would put that cost straight back. What is already out is left alone, so a
        restock tops the stock back up instead of replacing what the player was saving up
        for."""
        for npc in self.npcs:
            if not npc.is_merchant or not npc.shop_ready or npc.restock_in() > 0:
                continue
            missing = c.Villages.SHOP_STOCK_TARGET - len(npc.shop_items)
            npc.add_stock(roll_shop_stock(missing, luck=npc.stock_luck) if missing > 0 else [])

    def start_shop_generation(self, merchants: list | None = None):
        """Stock the given merchants, in a single background call.

        `merchants` is the shortlist the caller wants filled: the shops of a settlement the
        player is walking up to (`_prepare_settlements_near`) or the one merchant an event
        has just put on the road. Passing nothing stocks every merchant still waiting, which
        is a whole world's worth of calls and is only what a caller standing in front of all
        of them would want."""
        if merchants is None:
            merchants = [npc for npc in self.npcs if npc.is_merchant and not npc.shop_ready]
        merchants = [npc for npc in merchants if npc.is_merchant and not npc.shop_ready]
        if not merchants or not self.context or self._shops_generating:
            return
        self._shops_generating = True
        threading.Thread(target=self._generate_merchant_shops, args=(merchants,), daemon=True).start()

    def _generate_merchant_shops(self, merchants: list):
        try:
            stocks = generate_shop_inventories(self.context, len(merchants))
            for merchant, stock in zip(merchants, stocks, strict=False):
                merchant.set_shop(stock + self._shop_staples())
        finally:
            self._shops_generating = False
        self.persist_world()

    @staticmethod
    def _shop_staples() -> list:
        """Stocked in every shop regardless of what the LLM comes up with, so ranged combat
        doesn't depend entirely on loot RNG for its ammo, nor healing on finding a flask."""
        return [
            {"name": "Arrows", "item_type": "ammo", "rarity": "common", "price": 30, "quantity": AMMO_BUNDLE}
            for _ in range(2)
        ] + [{"name": "Healing Potion", "item_type": "potion", "rarity": "common", "price": 18} for _ in range(2)]
