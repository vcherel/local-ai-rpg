from __future__ import annotations

import math
import random
import threading
from typing import TYPE_CHECKING, List

import core.constants as c
from core.audio import play_sound
from core.particles import get_particles
from core.utils import random_coordinates
from game.entities.items import Item
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from llm.llm_request_queue import generate_response_stream_queued

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World:
    def __init__(self, save_system: SaveSystem, context_window: ContextMenu):
        self.floor_details = [
            (*random_coordinates(), random.choice(["stone", "flower"])) for _ in range(c.World.NB_DETAILS)
        ]

        self.items: List[Item] = []
        self.npcs: List[NPC] = []
        self.monsters: List[Monster] = []
        self.respawn_timer = 0.0

        self.save_system = save_system
        self.context_window = context_window
        self.context = self.save_system.load("context", None)

        saved_npcs = self.save_system.load("npcs", None)
        if saved_npcs is not None:
            self._restore(saved_npcs)
            if self.context:
                for npc in self.npcs:
                    if npc.is_merchant and not npc.shop_ready:
                        threading.Thread(target=self._generate_merchant_shop, args=(npc,), daemon=True).start()
        else:
            self.npcs = [NPC(*random_coordinates()) for _ in range(c.World.NB_NPCS)]
            self.monsters = [Monster(*self._random_coords_away_from_spawn()) for _ in range(c.World.NB_MONSTERS)]
            for npc in self.npcs:
                if random.random() < c.World.MERCHANT_PROBABILITY:
                    npc.is_merchant = True
                    npc.color = c.Colors.MERCHANT

        if self.context is None:
            self.context_window.start_streaming()
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            self.context_window.show(self.context)

    def _random_coords_away_from_spawn(self) -> tuple[int, int]:
        center = c.World.WORLD_SIZE // 2
        min_dist = c.World.INITIAL_SPAWN_MIN_DISTANCE
        for _ in range(20):
            x, y = random.randint(0, c.World.WORLD_SIZE), random.randint(0, c.World.WORLD_SIZE)
            if math.hypot(x - center, y - center) >= min_dist:
                return x, y
        return x, y

    def _restore(self, saved_npcs: list):
        """Rebuild items, NPCs and monsters from a saved game, relinking quest items by id."""
        self.items = [Item.from_dict(d) for d in self.save_system.load("items", [])]
        items_by_id = {item.id: item for item in self.items}
        self.npcs = [NPC.from_dict(d, items_by_id) for d in saved_npcs]
        self.monsters = [Monster.from_dict(d) for d in self.save_system.load("monsters", [])]

    def serialize(self) -> dict:
        return {
            "items": [item.to_dict() for item in self.items],
            "npcs": [npc.to_dict() for npc in self.npcs],
            "monsters": [monster.to_dict() for monster in self.monsters],
        }

    def _generate_context(self):
        system_prompt = (
            "You create worlds for an RPG. "
            "Each world must contain one original detail that can serve as a starting point for quests."
        )
        prompt = (
            "In a single very short sentence, describe an RPG world starting with 'The game takes place...' "
            "The sentence must contain one original detail that can serve as a starting point for adventures."
        )
        for chunk in generate_response_stream_queued(prompt, system_prompt, "Context generation"):
            if chunk:
                self.context_window.push_chunk(chunk)
                self.context = chunk
        self.context_window.finish_streaming()

        self.save_system.update("context", self.context)

        for npc in self.npcs:
            if npc.is_merchant:
                threading.Thread(target=self._generate_merchant_shop, args=(npc,), daemon=True).start()

    def _generate_merchant_shop(self, merchant: NPC):
        from llm.merchant_system import generate_shop_inventory

        shop_data = generate_shop_inventory(self.context)
        if not shop_data:
            shop_data = generate_shop_inventory(self.context)
        merchant.set_shop(shop_data)

    def talk_npc(self, player: Player):
        if self.context is None:
            return

        pos = player.get_pos(c.Player.INTERACTION_DISTANCE)
        for npc in self.npcs:
            if npc.distance_to_point(pos) < c.Player.INTERACTION_DISTANCE + c.Entities.NPC_SIZE // 2:
                if npc.is_merchant and not npc.shop_ready:
                    return None
                return npc

    def handle_attack(self, player: Player, quest_system: QuestSystem):
        player.start_attack_anim()
        play_sound("attack")
        pos = player.get_pos(c.Player.ATTACK_REACH)

        attack_damage = c.Player.ATTACK_DAMAGE + player.best_weapon_bonus() + player.stats.attack_bonus()
        for monster in self.monsters:
            if monster.distance_to_point(pos) < c.Player.ATTACK_REACH + c.Monster.SIZE // 2:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
                if monster.receive_damage(attack_damage):
                    player.stats.train("vitality", c.Stats.XP_PER_KILL)
                    play_sound("monster_death")
                    get_particles().spawn_burst(monster.x, monster.y, c.Colors.RED, count=14, speed=5, life=500, size=5)
                    self.monsters.remove(monster)
                    return
                play_sound("hit")
                get_particles().spawn_burst(monster.x, monster.y, (255, 180, 180), count=6, speed=3, life=300, size=3)

        for npc in self.npcs:
            if npc.distance_to_point(pos) < c.Player.ATTACK_REACH + c.Entities.NPC_SIZE // 2:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
                if npc.receive_damage(attack_damage):
                    # Drop any quest this NPC was offering so it can't become uncompletable
                    quest_system.remove_quest(npc)
                    play_sound("monster_death")
                    get_particles().spawn_burst(npc.x, npc.y, npc.color, count=14, speed=5, life=500, size=5)
                    self.npcs.remove(npc)
                    return
                play_sound("hit")
                get_particles().spawn_burst(npc.x, npc.y, (255, 180, 180), count=6, speed=3, life=300, size=3)

    def pickup_item(self, player: Player):
        for item in self.items:
            if not item.picked_up and item.distance_to_point(player.get_pos()) < c.Player.INTERACTION_DISTANCE:
                return item

    def _spawn_monster_away_from(self, player: Player):
        for _ in range(10):
            x, y = random_coordinates()
            if math.hypot(x - player.x, y - player.y) >= c.World.SPAWN_MIN_DISTANCE:
                self.monsters.append(Monster(x, y))
                return

    def update(self, player: Player, dt):
        get_particles().update(dt)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt).
        update_radius = c.World.DETECTION_RANGE + c.Player.SIZE
        for monster in self.monsters:
            if abs(monster.x - player.x) <= update_radius and abs(monster.y - player.y) <= update_radius:
                monster.move(player, dt)

        if len(self.monsters) < c.World.NB_MONSTERS:
            self.respawn_timer += dt
            if self.respawn_timer >= c.World.RESPAWN_INTERVAL_MS:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
