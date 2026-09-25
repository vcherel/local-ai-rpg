from __future__ import annotations

from typing import TYPE_CHECKING

import core.constants as c
from core.audio import play_sound
from core.particles import get_particles
from game.entities.items import rarity_color
from game.loot import open_lootbox

if TYPE_CHECKING:
    from game.entities.items import Item


class GamePickups:
    """Everything that reaches the player's hands off the ground or out of a box: the
    magnet, purses, lootboxes, stacking into the inventory, and the F prompt for an upgrade.

    Mixed into `Game`, whose player, world, interior and notifications these read.
    """

    def _award_loot(self, rarity: str, label: str):
        coins, loot_item = open_lootbox(self.player.x, self.player.y, rarity)
        self.player.find_coins(coins)

        message = f"{label}: +{coins} coins"
        if loot_item is not None:
            # A stackable merges into an existing stack; only a genuinely new entry joins the master list.
            if self.player.add_item(loot_item) is loot_item:
                self.world.items.append(loot_item)
            message += f" and a {loot_item.rarity} {loot_item.name}!"

        self.loot_notification.show(message, rarity_color(rarity))
        play_sound("lootbox_open")
        if loot_item is not None:
            self._offer_upgrade(loot_item)

    def _open_lootbox(self, lootbox: Item):
        self.world.items.remove(lootbox)
        self._award_loot(lootbox.rarity, "Lootbox")

    def _offer_upgrade(self, item: Item) -> bool:
        """Flag a just-acquired item as an upgrade and prompt to equip it with F. Returns
        whether it said anything, so a caller can fall back to its own message."""
        if not self.player.is_upgrade(item):
            return False
        self.pending_upgrade_id = item.id
        self.loot_notification.show(f"New {item.name} (+{item.bonus}), press F to equip", rarity_color(item.rarity))
        return True

    def _announce_pickup(self, item: Item):
        """Say something for every item that reaches the inventory. An upgrade gets the F
        prompt; anything else at least names itself, since a pickup that isn't an upgrade
        (a second bow while a stronger staff is equipped, a pelt, a potion) would otherwise
        be silent apart from the sound."""
        if self._offer_upgrade(item):
            return
        label = f"Picked up {item.name}"
        if item.quantity > 1:
            label += f" x{item.quantity}"
        self.loot_notification.show(label, rarity_color(item.rarity))

    def _equip_pending_upgrade(self):
        if self.pending_upgrade_id is None:
            return
        item = next((i for i in self.player.inventory if i.id == self.pending_upgrade_id), None)
        self.pending_upgrade_id = None
        if item is None:
            return
        self.player.equip(item)
        self.loot_notification.show(f"Equipped {item.name}", rarity_color(item.rarity))

    def _sweep_loot(self, dt):
        """The whole of picking things up. Anything lying within the magnet's reach flies at
        the player and is collected on contact, so loot is taken by walking over it and the
        interact key is left for doors, beds, chests and people.

        Loot standing on another building's floor is left alone, the same rule the renderer
        draws by: nothing is dragged out through a wall."""
        for item in list(self.world.items):
            if item.picked_up:
                continue
            if self.world.building_at(item.x, item.y) is not self.interior:
                # Behind a wall: no pull at all, and whatever it had built up is let go, so
                # walking back into the room starts it moving from a standstill.
                item.magnet_speed = 0.0
                continue
            if self._magnet(item, dt):
                self._pickup_world_item(item)

        if self.interior is not None:
            for item in list(self.interior.dropped_items):
                if self._magnet(item, dt):
                    self._pickup_dropped_item(item)

    def _magnet(self, item: Item, dt) -> bool:
        """Pull one piece of loot a frame's worth toward the player, and say whether it got
        there. Out of the magnet's reach it simply lets go of whatever pull it had."""
        if item.distance_to_point((self.player.x, self.player.y)) > c.Player.MAGNET_RADIUS:
            item.magnet_speed = 0.0
            return False
        return item.magnet_toward(self.player.x, self.player.y, dt)

    @staticmethod
    def _pickup_burst(item: Item):
        """The puff of colour every pickup leaves behind, whatever became of the item."""
        get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)

    def _pickup_world_item(self, item: Item):
        item.picked_up = True
        if item.item_type == "coins":
            # A purse is money on the ground, not an object: it is credited and gone,
            # never carried, so it leaves the master item list rather than sitting in the
            # save as something picked up.
            self.world.items.remove(item)
            self._take_purse(item)
            return
        if item.item_type == "lootbox":
            self._open_lootbox(item)
            self._pickup_burst(item)
            return

        # If it merges into a stack (ammo, potions), drop the now-orphaned world item.
        if self.player.add_item(item) is not item and item in self.world.items:
            self.world.items.remove(item)
        self._collect_item(item)

    def _collect_item(self, item: Item):
        """Feedback shared by every item pickup. The caller has already settled the item
        into the inventory and the world's master item list."""
        play_sound("pickup")
        self._announce_pickup(item)
        self._pickup_burst(item)

    def _take_purse(self, purse: Item):
        """Credit a purse walked over, wherever it was lying. The caller has already taken it
        off whatever list held it."""
        self.player.find_coins(purse.quantity)
        self.loot_notification.show(f"+{purse.quantity} coins", c.Colors.ACCENT)
        play_sound("pickup")
        self._pickup_burst(purse)

    def _pickup_dropped_item(self, item: Item):
        self.interior.dropped_items.remove(item)
        item.picked_up = True
        if item.item_type == "coins":
            self._take_purse(item)
            return
        # If ammo merges into a stack, register the item purely so a saved inventory
        # id can still find it after reload; it never renders or drops again.
        if self.player.add_item(item) is item:
            self.world.items.append(item)
        self._collect_item(item)
