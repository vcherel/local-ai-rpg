from __future__ import annotations

import math
import random
import threading
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.particles import get_particles
from game.entities.buildings import Building, generate_buildings, set_active_buildings
from game.entities.items import Item, roll_rarity
from game.entities.monsters import Monster, pick_monster_kind
from game.entities.npcs import NPC
from game.entities.projectile import Projectile
from game.events import EventSystem
from game.loot import open_lootbox
from llm.llm_request_queue import generate_response_queued, generate_response_stream_queued

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World:
    def __init__(self, save_system: SaveSystem, context_window: ContextMenu, notify):
        # Regenerated on the fly as the player explores; see _sync_chunks.
        self.floor_details = []
        self._loaded_chunks = set()
        self._current_chunk = None

        self.items: List[Item] = []
        self.npcs: List[NPC] = []
        self.monsters: List[Monster] = []
        self.buildings: List[Building] = []
        # Arrows in flight; transient like particles, never saved.
        self.projectiles: List[Projectile] = []
        self.respawn_timer = 0.0

        self.save_system = save_system
        self.context_window = context_window
        self.context = self.save_system.load("context", None)
        self.events = EventSystem(self, notify)

        saved_npcs = self.save_system.load("npcs", None)
        if saved_npcs is not None:
            self._restore(saved_npcs)
            if self.context:
                for npc in self.npcs:
                    if npc.is_merchant and not npc.shop_ready:
                        threading.Thread(target=self.generate_merchant_shop, args=(npc,), daemon=True).start()
        else:
            self.buildings = generate_buildings()
            set_active_buildings(self.buildings)
            self._populate_npcs()
            self.monsters = [
                self._new_monster(*self._random_coords_away_from_spawn()) for _ in range(c.World.NB_MONSTERS)
            ]
        set_active_buildings(self.buildings)

        if self.context is None:
            self.context_window.start_streaming()
            threading.Thread(target=self._generate_context, daemon=True).start()
        else:
            self.context_window.show(self.context)
            self._start_landmark_naming()

    def _populate_npcs(self):
        """Every NPC lives at a building: one merchant per shop, villagers spread over houses and taverns."""
        homes = [b for b in self.buildings if b.kind in ("house", "tavern")]
        for shop in (b for b in self.buildings if b.kind == "shop"):
            npc = NPC(*shop.door_front())
            npc.is_merchant = True
            npc.color = c.Colors.MERCHANT
            self.npcs.append(npc)
        while len(self.npcs) < c.World.NB_NPCS:
            home = random.choice(homes)
            door_x, door_y = home.door_front()
            npc = NPC(door_x + random.randint(-80, 80), door_y + random.randint(0, 80))
            npc.home = (door_x, door_y)
            self.npcs.append(npc)

    def _random_coords_away_from_spawn(self) -> tuple[int, int]:
        center = c.World.WORLD_SIZE // 2
        min_dist = c.World.INITIAL_SPAWN_MIN_DISTANCE
        for _ in range(20):
            x, y = random.randint(0, c.World.WORLD_SIZE), random.randint(0, c.World.WORLD_SIZE)
            if math.hypot(x - center, y - center) >= min_dist and not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                return x, y
        return x, y

    def _new_monster(self, x, y) -> Monster:
        """Tougher kinds unlock farther from the world center, so wandering out gets more dangerous."""
        center = c.World.WORLD_SIZE // 2
        distance_from_center = math.hypot(x - center, y - center)
        return Monster(x, y, pick_monster_kind(distance_from_center))

    def _restore(self, saved_npcs: list):
        """Rebuild items, NPCs, monsters and buildings from a saved game, relinking quest items by id."""
        self.buildings = [Building.from_dict(d) for d in self.save_system.load("buildings", [])]
        self.items = [Item.from_dict(d) for d in self.save_system.load("items", [])]
        items_by_id = {item.id: item for item in self.items}
        self.npcs = [NPC.from_dict(d, items_by_id) for d in saved_npcs]
        self.monsters = [Monster.from_dict(d) for d in self.save_system.load("monsters", [])]

    def serialize(self) -> dict:
        # A wandering merchant is a transient event; drop it rather than saving it as permanent.
        npcs = [npc for npc in self.npcs if npc is not self.events.wandering_merchant]
        return {
            "items": [item.to_dict() for item in self.items],
            "npcs": [npc.to_dict() for npc in npcs],
            "monsters": [monster.to_dict() for monster in self.monsters],
            "buildings": [building.to_dict() for building in self.buildings],
        }

    def blocked(self, x, y, radius, door_open=False) -> bool:
        return any(building.blocks(x, y, radius, door_open) for building in self.buildings)

    def _chunk_of(self, x, y) -> tuple[int, int]:
        size = c.World.CHUNK_SIZE
        return int(x // size), int(y // size)

    def _load_chunk(self, chunk: tuple[int, int]):
        """Deterministically generate a chunk's floor details, so revisiting it looks the same."""
        cx, cy = chunk
        size = c.World.CHUNK_SIZE
        rng = random.Random(f"{cx},{cy}")
        for _ in range(c.World.DETAILS_PER_CHUNK):
            x = cx * size + rng.uniform(0, size)
            y = cy * size + rng.uniform(0, size)
            self.floor_details.append((x, y, rng.choice(["stone", "flower"])))
        self._loaded_chunks.add(chunk)

    def _unload_chunk(self, chunk: tuple[int, int]):
        self.floor_details = [d for d in self.floor_details if self._chunk_of(d[0], d[1]) != chunk]
        self._loaded_chunks.discard(chunk)

    def _sync_chunks(self, player: Player):
        chunk = self._chunk_of(player.x, player.y)
        if chunk == self._current_chunk:
            return
        self._current_chunk = chunk
        cx, cy = chunk
        load_r = c.World.CHUNK_LOAD_RADIUS
        keep_r = c.World.CHUNK_KEEP_RADIUS
        for dx in range(-load_r, load_r + 1):
            for dy in range(-load_r, load_r + 1):
                candidate = (cx + dx, cy + dy)
                if candidate not in self._loaded_chunks:
                    self._load_chunk(candidate)
        for loaded in list(self._loaded_chunks):
            if max(abs(loaded[0] - cx), abs(loaded[1] - cy)) > keep_r:
                self._unload_chunk(loaded)

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
                threading.Thread(target=self.generate_merchant_shop, args=(npc,), daemon=True).start()
        self._start_landmark_naming()

    def _start_landmark_naming(self):
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None or landmark.name:
            return
        threading.Thread(target=self._generate_landmark_name, args=(landmark,), daemon=True).start()

    def _generate_landmark_name(self, landmark: Building):
        system_prompt = "You name landmarks for an RPG world. Reply with the name only, no quotes, no punctuation."
        prompt = f"{self.context}\nGive a short name, 2 to 4 words, for the ancient ruined landmark of this world."
        name = generate_response_queued(prompt, system_prompt, "Landmark naming") or ""
        name = name.strip().strip('"').strip(".")
        if name:
            landmark.name = " ".join(name.split()[:5])

    def generate_merchant_shop(self, merchant: NPC):
        from llm.merchant_system import generate_shop_inventory

        shop_data = generate_shop_inventory(self.context)
        if not shop_data:
            shop_data = generate_shop_inventory(self.context)
        # Guaranteed regardless of what the LLM comes up with, so ranged combat
        # doesn't depend entirely on loot RNG for its ammo.
        shop_data += [{"name": "Arrows", "item_type": "ammo", "rarity": "common", "price": 2} for _ in range(2)]
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

    def handle_attack(
        self,
        player: Player,
        quest_system: QuestSystem,
        monsters: List[Monster] = None,
        projectiles: List[Projectile] = None,
        blocked=None,
    ):
        """`monsters` overrides the target list for an indoor fight; loot then goes straight to
        the player instead of dropping a world item, since interior coordinates aren't outdoor ones.
        The weapon's archetype (constants.weapon_archetype) drives reach, damage, cadence, crit,
        knockback and cleave, so different weapon families feel different to swing."""
        indoor = monsters is not None
        monster_list = monsters if indoor else self.monsters
        proj_list = projectiles if indoor else self.projectiles
        if blocked is None:
            blocked = self.blocked

        weapon = player.equipped_item("weapon")
        arch = c.weapon_archetype(weapon.name if weapon else None)

        if arch.ranged:
            self._fire_ranged(player, proj_list, arch)
            return

        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:  # still on cooldown from the previous swing
            return
        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult

        player.start_attack_anim()
        play_sound("attack")

        reach = c.Player.ATTACK_REACH * arch.reach_mult
        pos = player.get_pos(reach)
        base_damage = c.Player.ATTACK_DAMAGE + player.weapon_bonus() + player.stats.attack_bonus()
        hit_radius = reach * (arch.cleave_radius_mult if arch.cleave else 1.0)

        monster_targets = [m for m in monster_list if m.distance_to_point(pos) < hit_radius + m.kind.size // 2]
        if monster_targets:
            if not arch.cleave:
                monster_targets = [min(monster_targets, key=lambda m: m.distance_to_point(pos))]
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for monster in monster_targets:
                self._strike_monster(monster, monster_list, base_damage, arch, player, quest_system, indoor, blocked)
            return

        if indoor:
            return

        npc_targets = [n for n in self.npcs if n.distance_to_point(pos) < hit_radius + c.Entities.NPC_SIZE // 2]
        if npc_targets:
            if not arch.cleave:
                npc_targets = [min(npc_targets, key=lambda n: n.distance_to_point(pos))]
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for npc in npc_targets:
                self._strike_npc(npc, base_damage, arch, player, quest_system, blocked)

    def _fire_ranged(self, player: Player, proj_list: List[Projectile], arch: c.WeaponArchetype):
        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:
            return
        if arch.uses_ammo:
            ammo = next((item for item in player.inventory if item.item_type == "ammo"), None)
            if ammo is None:
                return
            player.inventory.remove(ammo)

        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult
        player.start_attack_anim()
        play_sound("shoot")

        base_damage = c.Player.ATTACK_DAMAGE + player.weapon_bonus() + player.stats.attack_bonus()
        damage = max(1, int(round(base_damage * arch.damage_mult)))
        if arch.name == "staff":
            proj = Projectile(
                player.x,
                player.y,
                player.orientation,
                damage,
                style="bolt",
                color=(150, 90, 230),
                knockback=arch.knockback,
                shake=arch.shake,
            )
        else:
            proj = Projectile(
                player.x,
                player.y,
                player.orientation,
                damage,
                knockback=arch.knockback,
                shake=arch.shake,
            )
        proj_list.append(proj)

    def _roll_hit(self, base_damage: float, arch: c.WeaponArchetype) -> tuple[int, bool]:
        """Apply the weapon's damage multiplier and roll for a crit."""
        damage = base_damage * arch.damage_mult
        crit = random.random() < arch.crit_chance
        if crit:
            damage *= c.Combat.CRIT_MULT
        return max(1, int(round(damage))), crit

    @staticmethod
    def _dir_from(x0, y0, x1, y1):
        """Unit vector from (x0,y0) toward (x1,y1), or None if they coincide."""
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist == 0:
            return None
        return (dx / dist, dy / dist)

    @staticmethod
    def _knockback(target, radius, kb_dir, distance, blocked):
        """Shove a target along kb_dir, sliding along walls one axis at a time."""
        if not kb_dir or distance <= 0:
            return
        step_x, step_y = kb_dir[0] * distance, kb_dir[1] * distance
        if blocked is not None and blocked(target.x + step_x, target.y, radius):
            step_x = 0
        target.x += step_x
        if blocked is not None and blocked(target.x, target.y + step_y, radius):
            step_y = 0
        target.y += step_y

    def _strike_monster(self, monster, monster_list, base_damage, arch, player, quest_system, indoor, blocked):
        damage, crit = self._roll_hit(base_damage, arch)
        shake = arch.shake + (c.Combat.CRIT_SHAKE_BONUS if crit else 0.0)
        kb_dir = self._dir_from(player.x, player.y, monster.x, monster.y)
        self._resolve_monster_hit(
            monster,
            monster_list,
            damage,
            player,
            quest_system,
            indoor,
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=kb_dir,
            blocked=blocked,
        )

    def _strike_npc(self, npc, base_damage, arch, player, quest_system, blocked):
        damage, crit = self._roll_hit(base_damage, arch)
        shake = arch.shake + (c.Combat.CRIT_SHAKE_BONUS if crit else 0.0)
        kb_dir = self._dir_from(player.x, player.y, npc.x, npc.y)
        self._resolve_npc_hit(
            npc,
            damage,
            quest_system,
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=kb_dir,
            blocked=blocked,
        )

    def _resolve_monster_hit(
        self,
        monster: Monster,
        monster_list: List[Monster],
        damage: int,
        player: Player,
        quest_system: QuestSystem,
        indoor: bool,
        crit: bool = False,
        shake: float = 0.0,
        knockback: float = 0.0,
        kb_dir=None,
        blocked=None,
    ) -> bool:
        """Applies damage to a monster and its kill rewards. Returns True if it died."""
        get_shake().add(shake)
        if monster.receive_damage(damage):
            player.stats.train("vitality", c.Stats.XP_PER_KILL)
            play_sound("monster_death")
            get_particles().spawn_burst(monster.x, monster.y, monster.kind.color, count=14, speed=5, life=500, size=5)
            quest_item = quest_system.on_monster_killed(monster.kind.name, monster.x, monster.y)
            if quest_item is not None:
                if indoor:
                    player.inventory.append(quest_item)
                else:
                    self.items.append(quest_item)
            drop_chance = c.LootBox.DROP_CHANCE
            if self.events.blood_night_active:
                drop_chance *= c.Events.BLOOD_NIGHT_DROP_MULT
            if random.random() < drop_chance:
                if indoor:
                    coins, loot_item = open_lootbox(monster.x, monster.y, roll_rarity())
                    player.add_coins(coins)
                    if loot_item is not None:
                        player.inventory.append(loot_item)
                else:
                    self.items.append(Item(monster.x, monster.y, "Lootbox", "lootbox"))
            monster_list.remove(monster)
            return True
        self._hit_feedback(monster.x, monster.y, crit)
        self._knockback(monster, monster.kind.size / 2, kb_dir, knockback, blocked)
        return False

    def _resolve_npc_hit(
        self,
        npc: NPC,
        damage: int,
        quest_system: QuestSystem,
        crit: bool = False,
        shake: float = 0.0,
        knockback: float = 0.0,
        kb_dir=None,
        blocked=None,
    ) -> bool:
        """Applies damage to an NPC and handles death. Returns True if it died."""
        get_shake().add(shake)
        if npc.receive_damage(damage):
            stolen_item = quest_system.on_npc_killed(npc)
            if stolen_item is not None:
                self.items.append(stolen_item)
            # Drop any quest this NPC was offering so it can't become uncompletable
            quest_system.remove_quest(npc)
            play_sound("monster_death")
            get_particles().spawn_burst(npc.x, npc.y, npc.color, count=14, speed=5, life=500, size=5)
            self.npcs.remove(npc)
            return True
        self._hit_feedback(npc.x, npc.y, crit)
        self._knockback(npc, c.Entities.NPC_SIZE / 2, kb_dir, knockback, blocked)
        return False

    @staticmethod
    def _hit_feedback(x, y, crit: bool):
        """Sound + particle burst for a non-fatal hit; crits read brighter and louder."""
        play_sound("crit" if crit else "hit")
        color = (255, 240, 160) if crit else (255, 180, 180)
        get_particles().spawn_burst(
            x,
            y,
            color,
            count=12 if crit else 6,
            speed=4 if crit else 3,
            life=350 if crit else 300,
            size=4 if crit else 3,
        )

    def update_projectiles(
        self,
        proj_list: List[Projectile],
        monster_list: List[Monster],
        player: Player,
        quest_system: QuestSystem,
        dt,
        blocked=None,
        indoor: bool = False,
    ):
        for proj in list(proj_list):
            proj.update(dt, blocked)
            if proj.dead:
                proj_list.remove(proj)
                continue

            hit_monster = next(
                (m for m in monster_list if proj.distance_to_point((m.x, m.y)) < c.Projectile.SIZE + m.kind.size // 2),
                None,
            )
            if hit_monster is not None:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
                kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
                self._resolve_monster_hit(
                    hit_monster,
                    monster_list,
                    proj.damage,
                    player,
                    quest_system,
                    indoor,
                    shake=proj.shake,
                    knockback=proj.knockback,
                    kb_dir=kb_dir,
                    blocked=blocked,
                )
                proj_list.remove(proj)
                continue

            if not indoor:
                hit_npc = next(
                    (
                        n
                        for n in self.npcs
                        if proj.distance_to_point((n.x, n.y)) < c.Projectile.SIZE + c.Entities.NPC_SIZE // 2
                    ),
                    None,
                )
                if hit_npc is not None:
                    player.stats.train("strength", c.Stats.XP_PER_HIT)
                    kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
                    self._resolve_npc_hit(
                        hit_npc,
                        proj.damage,
                        quest_system,
                        shake=proj.shake,
                        knockback=proj.knockback,
                        kb_dir=kb_dir,
                        blocked=blocked,
                    )
                    proj_list.remove(proj)

    def pickup_item(self, player: Player):
        for item in self.items:
            if not item.picked_up and item.distance_to_point(player.get_pos()) < c.Player.INTERACTION_DISTANCE:
                return item

    def _spawn_monster_away_from(self, player: Player):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.World.SPAWN_MIN_DISTANCE, c.World.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                self.monsters.append(self._new_monster(x, y))
                return

    def update(self, player: Player, dt, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        get_particles().update(dt)
        self._sync_chunks(player)
        self.events.update(dt, player, quest_system, npc_name_generator)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt).
        update_radius = c.World.DETECTION_RANGE + c.Player.SIZE
        for monster in self.monsters:
            if abs(monster.x - player.x) <= update_radius and abs(monster.y - player.y) <= update_radius:
                monster.move(player, dt, self.blocked)

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        self.monsters = [m for m in self.monsters if m.distance_to_point(player.get_pos()) <= c.World.DESPAWN_DISTANCE]

        self.update_projectiles(self.projectiles, self.monsters, player, quest_system, dt, self.blocked)

        for npc in self.npcs:
            npc.update(player, dt, self.blocked)

        if len(self.monsters) < c.World.NB_MONSTERS:
            self.respawn_timer += dt
            respawn_interval = c.World.RESPAWN_INTERVAL_MS
            if self.events.blood_night_active:
                respawn_interval /= c.Events.BLOOD_NIGHT_RESPAWN_MULT
            if self.respawn_timer >= respawn_interval:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
