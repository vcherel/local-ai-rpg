from __future__ import annotations

import math
import random
import threading
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.daynight import DayNightCycle
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from core.screen_fx import get_hitstop
from game.entities.boss import Boss
from game.entities.breakables import Breakable, generate_breakables
from game.entities.buildings import Building, generate_buildings, set_active_buildings
from game.entities.critter import Critter, pick_critter_kind
from game.entities.items import AMMO_BUNDLE, Item, rarity_color
from game.entities.monsters import Monster, pick_monster_kind
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest, generate_pois
from game.entities.projectile import Projectile
from game.events import EventSystem
from game.loot import break_crate, open_poi_cache
from llm.llm_request_queue import generate_response_queued, generate_response_stream_queued

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator
    from llm.quest_system import QuestSystem
    from ui.menus.context_menu import ContextMenu


class World:
    def __init__(self, save_system: SaveSystem, context_window: ContextMenu, notify, show_rumor):
        # Regenerated on the fly as the player explores; see _sync_chunks.
        self.floor_details = []
        self._loaded_chunks = set()
        self._current_chunk = None

        self.items: List[Item] = []
        self.npcs: List[NPC] = []
        self.monsters: List[Monster] = []
        # Named, multi-phase bosses. Kept apart from monsters: they never despawn, don't
        # count toward the monster cap, and get their own update, health bar and rewards.
        self.bosses: List[Boss] = []
        self.buildings: List[Building] = []
        self.breakables: List[Breakable] = []
        self.pois: List[PointOfInterest] = []
        # Wandering wildlife, purely atmospheric; transient like particles, never saved.
        self.critters: List[Critter] = []
        # Arrows in flight; transient like particles, never saved.
        self.projectiles: List[Projectile] = []
        self.respawn_timer = 0.0
        self.critter_respawn_timer = 0.0
        self.boss_roam_timer = 0.0

        self.save_system = save_system
        self.context_window = context_window
        self.notify = notify
        self.context = self.save_system.load("context", None)
        self.events = EventSystem(self, notify, show_rumor)
        self.daynight = DayNightCycle(self.save_system.load("daynight_elapsed_ms", 0.0))

        # Generation guards: a merchant with no shop yet, or an unnamed landmark, would
        # otherwise be picked up again by every path that checks, queueing a duplicate
        # call while the first one is still in flight.
        self._shops_generating = False
        self._landmark_naming = False

        saved_npcs = self.save_system.load("npcs", None)
        if saved_npcs is not None:
            self._restore(saved_npcs)
            # Fills in quests saved before boss names were tracked, and quests whose boss
            # was still unnamed when the game was last closed.
            self.sync_quest_boss_names()
            if self.context:
                self.start_shop_generation()
        else:
            self.buildings = generate_buildings()
            set_active_buildings(self.buildings)
            self.breakables = generate_breakables(self.buildings)
            self.pois = generate_pois(self.buildings)
            self._populate_npcs()
            self.monsters = [
                self._new_monster(*self._random_coords_away_from_spawn()) for _ in range(c.World.NB_MONSTERS)
            ]
            self._spawn_camp_guards()
            self._spawn_landmark_boss()
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
        # Nothing clear in 20 tries: settle for the last roll rather than looping forever.
        # A monster standing in a wall beats hanging world generation.
        return x, y

    def _spawn_camp_guards(self):
        """A camp point of interest doesn't stand undefended: one regular monster spawns
        just next to it, at world creation only, so there's a small fight before the loot."""
        for poi in self.pois:
            if poi.kind != "camp":
                continue
            angle = random.uniform(0, 2 * math.pi)
            x = poi.x + math.cos(angle) * 70
            y = poi.y + math.sin(angle) * 70
            self.monsters.append(self._new_monster(x, y))

    def _new_monster(self, x, y) -> Monster:
        """Tougher kinds unlock farther from the world center, so wandering out gets more dangerous."""
        center = c.World.WORLD_SIZE // 2
        distance_from_center = math.hypot(x - center, y - center)
        return Monster(x, y, pick_monster_kind(distance_from_center))

    def _restore(self, saved_npcs: list):
        """Rebuild items, NPCs, monsters and buildings from a saved game, relinking quest items by id."""
        self.buildings = [Building.from_dict(d) for d in self.save_system.load("buildings", [])]
        self.breakables = [Breakable.from_dict(d) for d in self.save_system.load("breakables", [])]
        self.pois = [PointOfInterest.from_dict(d) for d in self.save_system.load("pois", [])]
        self.items = [Item.from_dict(d) for d in self.save_system.load("items", [])]
        items_by_id = {item.id: item for item in self.items}
        self.npcs = [NPC.from_dict(d, items_by_id) for d in saved_npcs]
        self.monsters = [Monster.from_dict(d) for d in self.save_system.load("monsters", [])]
        self.bosses = [Boss.from_dict(d) for d in self.save_system.load("bosses", [])]

    def persist_world(self):
        """Flush generated world state to disk. Called by the background generation threads
        so finished work (context, shops, boss and landmark names) survives a restart
        instead of being regenerated on the next continue."""
        try:
            state = self.serialize()
        except RuntimeError:
            # A list mutated on the main thread mid-serialisation; skip this write, the
            # periodic autosave and the next completion will catch it.
            return
        for key, value in state.items():
            self.save_system.update(key, value)
        self.save_system.update("context", self.context)
        self.save_system.save_all()

    def serialize(self) -> dict:
        # A wandering merchant is a transient event; drop it rather than saving it as permanent.
        npcs = [npc for npc in self.npcs if npc is not self.events.wandering_merchant]
        return {
            "items": [item.to_dict() for item in self.items],
            "npcs": [npc.to_dict() for npc in npcs],
            "monsters": [monster.to_dict() for monster in self.monsters],
            "bosses": [boss.to_dict() for boss in self.bosses],
            "buildings": [building.to_dict() for building in self.buildings],
            "breakables": [breakable.to_dict() for breakable in self.breakables],
            "pois": [poi.to_dict() for poi in self.pois],
            "daynight_elapsed_ms": self.daynight.elapsed_ms,
        }

    def blocked(self, x, y, radius) -> bool:
        return any(building.blocks(x, y, radius) for building in self.buildings)

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

        self.persist_world()

        self.start_shop_generation()
        for boss in self.bosses:
            threading.Thread(target=self._generate_boss_identity, args=(boss, None), daemon=True).start()
        self._start_landmark_naming()

    def _start_landmark_naming(self):
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None or landmark.name or self._landmark_naming:
            return
        self._landmark_naming = True
        threading.Thread(target=self._generate_landmark_name, args=(landmark,), daemon=True).start()

    def _generate_landmark_name(self, landmark: Building):
        system_prompt = "You name landmarks for an RPG world. Reply with the name only, no quotes, no punctuation."
        prompt = f"{self.context}\nGive a short name, 2 to 4 words, for the ancient ruined landmark of this world."
        try:
            name = generate_response_queued(prompt, system_prompt, "Landmark naming") or ""
            name = name.strip().strip('"').strip(".")
            if name:
                landmark.name = " ".join(name.split()[:5])
                self.persist_world()
        finally:
            self._landmark_naming = False

    # ------------------------------------------------------------------ bosses

    def spawn_boss(self, x, y, template: c.BossKind = None, quest_tag: str = None, announce: str = None) -> Boss:
        """Create a boss, register it, and kick off LLM naming. `announce`, if given, is a
        message template shown once the name is ready (use '{name}' for the boss's name)."""
        boss = Boss(x, y, template or random.choice(c.BOSS_KINDS), quest_tag=quest_tag)
        self.bosses.append(boss)
        if self.context:
            threading.Thread(target=self._generate_boss_identity, args=(boss, announce), daemon=True).start()
        return boss

    def _spawn_landmark_boss(self):
        """A guardian waits at the ruined landmark from the very first world. It's named
        later, once the world context has finished generating."""
        landmark = next((b for b in self.buildings if b.kind == "landmark"), None)
        if landmark is None:
            return
        self.spawn_boss(landmark.x, landmark.y + landmark.h / 2 + 90)

    def spawn_boss_for_quest(self) -> Boss:
        """Spawn a boss out in the dangerous outer ring as a quest hunt target."""
        center = c.World.WORLD_SIZE // 2
        for _ in range(20):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_MIN_DISTANCE, c.World.WORLD_SIZE // 2)
            x = center + math.cos(angle) * dist
            y = center + math.sin(angle) * dist
            if (
                0 <= x <= c.World.WORLD_SIZE
                and 0 <= y <= c.World.WORLD_SIZE
                and not self.blocked(x, y, c.MONSTER_MAX_SIZE)
            ):
                break
        tag = f"quest_boss_{random.randint(1000, 9999)}"
        return self.spawn_boss(x, y, quest_tag=tag)

    def _generate_boss_identity(self, boss: Boss, announce: str = None):
        system_prompt = (
            "You name bosses for a dark fantasy RPG. Reply with only the name, optionally as "
            "'Name, the Epithet'. No quotes, no other text."
        )
        prompt = f"World: {self.context}\nName {boss.template.flavor}. 2 to 5 words."
        text = generate_response_queued(prompt, system_prompt, "Boss naming") or ""
        boss.set_identity(text)
        self.sync_quest_boss_names()
        self.persist_world()
        if announce and self.notify:
            self.notify(announce.format(name=boss.name), c.Colors.BOSS_BAR)

    def sync_quest_boss_names(self):
        """Copy each boss's display name onto the slay_boss quest hunting it.

        The quest links to its boss by `target_monster_kind` holding the internal spawn
        tag ("quest_boss_1234"), which is never fit to show; naming happens later on a
        background thread, so the quest picks the real name up from here.
        """
        by_tag = {boss.quest_tag: boss for boss in self.bosses if boss.quest_tag}
        for npc in self.npcs:
            quest = npc.quest
            if quest is None or quest.quest_type != "slay_boss":
                continue
            boss = by_tag.get(quest.target_monster_kind)
            if boss is not None:
                quest.boss_name = boss.display_name

    def _maybe_spawn_roaming_boss(self, player: Player):
        if len(self.bosses) >= c.Boss.MAX_ACTIVE:
            return
        center = c.World.WORLD_SIZE // 2
        if math.hypot(player.x - center, player.y - center) < c.Boss.ROAM_MIN_DISTANCE:
            return
        if random.random() > c.Boss.ROAM_CHANCE:
            return
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Boss.ROAM_SPAWN_MIN_DIST, c.Boss.ROAM_SPAWN_MAX_DIST)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE):
                self.spawn_boss(x, y, announce="A roaming terror, {name}, prowls the wilds")
                return

    def start_shop_generation(self):
        """Stock every merchant still waiting for one, in a single background call."""
        merchants = [npc for npc in self.npcs if npc.is_merchant and not npc.shop_ready]
        if not merchants or not self.context or self._shops_generating:
            return
        self._shops_generating = True
        threading.Thread(target=self._generate_merchant_shops, args=(merchants,), daemon=True).start()

    def _generate_merchant_shops(self, merchants: list):
        from llm.merchant_system import generate_shop_inventories

        try:
            stocks = generate_shop_inventories(self.context, len(merchants))
            for merchant, stock in zip(merchants, stocks):
                merchant.set_shop(stock + self._shop_staples())
        finally:
            self._shops_generating = False
        self.persist_world()
        # A merchant that showed up mid-batch (the wandering merchant event) was skipped
        # by the guard, so give it its own pass now that this one is done.
        self.start_shop_generation()

    @staticmethod
    def _shop_staples() -> list:
        """Stocked in every shop regardless of what the LLM comes up with, so ranged combat
        doesn't depend entirely on loot RNG for its ammo, nor healing on finding a flask."""
        return [
            {"name": "Arrows", "item_type": "ammo", "rarity": "common", "price": 30, "quantity": AMMO_BUNDLE}
            for _ in range(2)
        ] + [{"name": "Healing Potion", "item_type": "potion", "rarity": "common", "price": 18} for _ in range(2)]

    def talk_npc(self, player: Player):
        if self.context is None:
            return

        pos = player.get_pos(c.Player.INTERACTION_DISTANCE)
        for npc in self.npcs:
            if npc.distance_to_point(pos) < c.Player.INTERACTION_DISTANCE + c.Entities.NPC_SIZE // 2:
                if npc.is_merchant and not npc.shop_ready:
                    return None
                return npc

    def handle_attack(self, player: Player, quest_system: QuestSystem, ranged: bool = False):
        """The weapon's archetype (constants.weapon_archetype) drives reach, damage, cadence,
        crit, knockback and cleave, so different weapon families feel different to swing.
        Building interiors are just world space now, so this has no indoor/outdoor split:
        monsters, NPCs, crates and windows are all found the same way whether the player is
        standing in a house or out in the open.

        `ranged` selects the ranged weapon slot (right click) instead of the melee one (left
        click), so a bow/staff and a melee weapon can be carried and used independently."""
        blocked = self.blocked

        if ranged:
            weapon = player.equipped_item("ranged_weapon")
            if weapon is None:
                return
            self._fire_ranged(player, self.projectiles, c.weapon_archetype(weapon.name))
            return

        weapon = player.equipped_item("melee_weapon")
        arch = c.weapon_archetype(weapon.name if weapon else None)

        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:  # still on cooldown from the previous swing
            return
        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult

        player.start_attack_anim("right")
        play_sound("attack")

        reach = c.Player.ATTACK_REACH * arch.reach_mult
        pos = player.get_pos(reach)
        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus() + player.stats.attack_bonus()
        ) * player.damage_multiplier()
        hit_radius = reach * (arch.cleave_radius_mult if arch.cleave else 1.0)

        if self.bosses:
            boss_targets = self._targets_in_reach(self.bosses, pos, hit_radius, lambda b: b.kind.size, arch.cleave)
            if boss_targets:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
                for boss in boss_targets:
                    self._strike_monster(boss, self.bosses, base_damage, arch, player, quest_system, blocked)
                return

        monster_targets = self._targets_in_reach(self.monsters, pos, hit_radius, lambda m: m.kind.size, arch.cleave)
        if monster_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for monster in monster_targets:
                self._strike_monster(monster, self.monsters, base_damage, arch, player, quest_system, blocked)
            return

        npc_targets = self._targets_in_reach(self.npcs, pos, hit_radius, lambda n: c.Entities.NPC_SIZE, arch.cleave)
        if npc_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for npc in npc_targets:
                self._strike_npc(npc, base_damage, arch, player, quest_system, blocked)
            return

        # A swing that reaches a shop/tavern crate smashes it instead.
        for building in self.buildings:
            crate = building.break_crate_at(pos, hit_radius)
            if crate is not None:
                self._break_crate(player, building, crate)
                return

        # A swing that reaches an unlooted wilderness ruins pile or camp cache smashes it.
        poi_hit = next(
            (
                p
                for p in self.pois
                if p.has_loot and not p.looted and p.distance_to_point(pos) < hit_radius + c.PointsOfInterest.HIT_RADIUS
            ),
            None,
        )
        if poi_hit is not None:
            self._break_poi(player, poi_hit)
            return

        # Nothing living in range: a swing that reaches a barrel/pot/bush smashes it instead.
        breakable = next(
            (b for b in self.breakables if b.distance_to_point(pos) < hit_radius + c.Breakables.HIT_RADIUS), None
        )
        if breakable is not None:
            self._break_breakable(player, breakable)
            return

        window_hit = self._find_window_in_reach(pos, hit_radius)
        if window_hit is not None:
            building, idx, window = window_hit
            self._break_window(building, idx, window)

    @staticmethod
    def _targets_in_reach(entities, pos, hit_radius, size_of, cleave: bool) -> list:
        """Entities within a swing's reach: every one in range if the weapon cleaves,
        otherwise just the nearest."""
        targets = [e for e in entities if e.distance_to_point(pos) < hit_radius + size_of(e) // 2]
        if not targets or cleave:
            return targets
        return [min(targets, key=lambda e: e.distance_to_point(pos))]

    def _find_window_in_reach(self, pos, hit_radius):
        """Nearest unbroken window (on any non-landmark building) a swing reaches, as
        (building, index, rect), or None."""
        px, py = pos
        best = None
        for building in self.buildings:
            for idx, window in enumerate(building.window_rects()):
                if idx in building.broken_windows:
                    continue
                dist = math.hypot(px - window.centerx, py - window.centery)
                if dist < hit_radius + c.Buildings.WINDOW_HIT_RADIUS and (best is None or dist < best[0]):
                    best = (dist, building, idx, window)
        return None if best is None else (best[1], best[2], best[3])

    def _break_window(self, building: Building, idx: int, window):
        """Shatter a window: no loot, just a satisfying crash."""
        building.broken_windows.add(idx)
        get_shake().add(c.Combat.WINDOW_SHAKE)
        play_sound("glass_break")
        get_particles().spawn_burst(
            window.centerx,
            window.centery,
            (210, 230, 240),
            count=16,
            speed=6,
            life=500,
            size=3,
            gravity=0.5,
            shape="shard",
        )

    def _fire_ranged(self, player: Player, proj_list: List[Projectile], arch: c.WeaponArchetype):
        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:
            return
        if arch.uses_ammo:
            ammo = next((item for item in player.inventory if item.item_type == "ammo"), None)
            if ammo is None:
                return
            ammo.quantity -= 1
            if ammo.quantity <= 0:
                player.inventory.remove(ammo)

        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult
        player.start_attack_anim("left")
        play_sound("shoot")

        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus(ranged=True) + player.stats.attack_bonus()
        ) * player.damage_multiplier()
        # A shot can crit too (weapon + affix chance), boosting damage and the hit's shake.
        # Rampage forces every Nth shot to crit and amplifies it further.
        rampage = player.rampage_trigger(ranged=True)
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus(ranged=True), rampage=rampage)
        crit_shake = c.Combat.CRIT_SHAKE_BONUS if crit else 0.0
        rampage_shake = c.Combat.CRIT_SHAKE_BONUS if rampage else 0.0
        shake = arch.shake + crit_shake + rampage_shake
        if arch.name == "staff":
            proj = Projectile(
                player.x,
                player.y,
                player.orientation,
                damage,
                style="bolt",
                color=(150, 90, 230),
                knockback=arch.knockback,
                shake=shake,
            )
        else:
            proj = Projectile(
                player.x,
                player.y,
                player.orientation,
                damage,
                knockback=arch.knockback,
                shake=shake,
            )
        proj.pierce = player.pierce_count()
        proj_list.append(proj)

    def _roll_hit(
        self, base_damage: float, arch: c.WeaponArchetype, crit_bonus: float = 0.0, rampage: bool = False
    ) -> tuple[int, bool]:
        """Apply the weapon's damage multiplier and roll for a crit (weapon + affix chance).
        Rampage forces the crit and amplifies it further on top."""
        damage = base_damage * arch.damage_mult
        crit = rampage or random.random() < arch.crit_chance + crit_bonus
        if crit:
            damage *= c.Combat.CRIT_MULT
        if rampage:
            damage *= c.Affixes.RAMPAGE_BONUS_MULT
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

    def _strike_monster(self, monster, monster_list, base_damage, arch, player, quest_system, blocked):
        rampage = player.rampage_trigger(ranged=False)
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus(), rampage=rampage)
        crit_shake = c.Combat.CRIT_SHAKE_BONUS if crit else 0.0
        rampage_shake = c.Combat.CRIT_SHAKE_BONUS if rampage else 0.0
        shake = arch.shake + crit_shake + rampage_shake
        kb_dir = self._dir_from(player.x, player.y, monster.x, monster.y)
        died = self._resolve_monster_hit(
            monster,
            monster_list,
            damage,
            player,
            quest_system,
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=kb_dir,
            blocked=blocked,
        )
        self._apply_on_hit_effects(monster, monster_list, damage, player, quest_system, died)
        self._apply_chainstrike(monster, monster_list, damage, player, quest_system, blocked, ranged=False)

    def _strike_npc(self, npc, base_damage, arch, player, quest_system, blocked):
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus())
        # Lifesteal works on any struck target, NPCs included.
        frac = player.lifesteal_frac()
        if frac > 0:
            player.heal(damage * frac)
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

    @staticmethod
    def _break_effects(x, y, color, count):
        """Shared shake, crash sound and shard burst for a smashed crate/cache/barrel."""
        get_shake().add(c.Combat.CRATE_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(x, y, color, count=count, speed=6, life=550, size=5, gravity=0.4, shape="shard")

    def _break_loot(self, player: Player, x, y, coins, loot_item, label: str, place_item):
        """Credit coins, pop any dropped item out near (x, y) via `place_item`, and toast the result."""
        player.gain_coins(coins)
        message = f"{label}: +{coins} coins"
        color = c.Colors.WHITE
        if loot_item is not None:
            loot_item.x = x + random.uniform(-20, 20)
            loot_item.y = y + random.uniform(-20, 20)
            loot_item.start_pop_anim(x, y)
            place_item(loot_item)
            message += f", and a {loot_item.rarity} {loot_item.name} dropped"
            color = rarity_color(loot_item.rarity)
        if self.notify:
            self.notify(message, color)

    def _break_crate(self, player: Player, building: Building, crate):
        """Smash a shop or tavern crate: juice, a few coins, and a small chance of a dropped item.

        The crate has already been removed from the interior's collision set by
        break_crate_at; here we handle the feedback and the loot. Coins are credited
        straight away; an item (if any) pops out onto the floor for the player to walk
        over and collect, rather than jumping straight into the inventory.
        """
        self._break_effects(crate.centerx, crate.centery, (150, 110, 70), 20)
        coins, loot_item = break_crate()
        self._break_loot(
            player, crate.centerx, crate.centery, coins, loot_item, "Crate smashed", building.dropped_items.append
        )

    def _break_poi(self, player: Player, poi: PointOfInterest):
        """Smash a wilderness ruins pile or camp cache: same feedback as an outdoor barrel,
        better odds and rarity since it took more effort to find. Left in place afterwards
        (not removed like a breakable) so the ruin/camp still reads as a landmark, just
        picked over."""
        poi.looted = True
        self._break_effects(poi.x, poi.y, (150, 140, 120), 20)
        coins, loot_item = open_poi_cache()
        label = "Camp cache" if poi.kind == "camp" else "Ruins searched"
        self._break_loot(player, poi.x, poi.y, coins, loot_item, label, self.items.append)

    def _break_breakable(self, player: Player, breakable: Breakable):
        """Smash an outdoor prop. A barrel plays out like a shop crate: juice, coins,
        and a small chance of a dropped item landing straight in the open world. A
        pot or bush is pure decoration: a satisfying puff and nothing else, so the
        world has more to smash without inflating the loot economy. Either way the
        prop is gone for good, no debris left behind."""
        self.breakables.remove(breakable)

        if not breakable.loot:
            get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
            if breakable.kind == "pot":
                play_sound("crate_break")
                get_particles().spawn_burst(
                    breakable.x,
                    breakable.y,
                    (170, 100, 60),
                    count=10,
                    speed=5,
                    life=400,
                    size=3,
                    gravity=0.4,
                    shape="shard",
                )
            else:  # bush
                play_sound("bush_rustle")
                get_particles().spawn_burst(
                    breakable.x, breakable.y, (80, 150, 65), count=14, speed=4, life=450, size=4, gravity=0.3
                )
            return

        self._break_effects(breakable.x, breakable.y, (150, 110, 70), 18)
        coins, loot_item = break_crate()
        self._break_loot(player, breakable.x, breakable.y, coins, loot_item, "Barrel smashed", self.items.append)

    def _resolve_monster_hit(
        self,
        monster: Monster,
        monster_list: List[Monster],
        damage: int,
        player: Player,
        quest_system: QuestSystem,
        crit: bool = False,
        shake: float = 0.0,
        knockback: float = 0.0,
        kb_dir=None,
        blocked=None,
    ) -> bool:
        """Applies damage to a monster and its kill rewards. Returns True if it died."""
        get_shake().add(shake)
        self._pop_damage(monster.x, monster.y - monster.kind.size / 2, damage, crit)
        if monster.receive_damage(damage):
            self._kill_monster(monster, monster_list, player, quest_system)
            return True
        self._hit_feedback(monster.x, monster.y, crit, kb_dir)
        if not getattr(monster, "knockback_immune", False):
            self._knockback(monster, monster.kind.size / 2, kb_dir, knockback, blocked)
        return False

    def _kill_monster(self, monster, monster_list, player: Player, quest_system: QuestSystem):
        """Death rewards and cleanup for a slain monster, shared by hits and burn ticks."""
        player.stats.train("vitality", c.Stats.XP_PER_KILL)
        play_sound("monster_death")
        # Bloodlust: any kill with a weapon carrying it refreshes the damage buff.
        bloodlust = player.bloodlust_mult()
        if bloodlust > 1.0:
            player.apply_buff("bloodlust", bloodlust, c.Affixes.BLOODLUST_DURATION_S)
        if isinstance(monster, Boss):
            self._on_boss_killed(monster, quest_system)
            monster_list.remove(monster)
            return
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        get_decals().spawn(monster.x, monster.y, radius=c.Decals.KILL_RADIUS)
        get_particles().spawn_burst(
            monster.x, monster.y, monster.kind.color, count=14, speed=5, life=500, size=5, gravity=0.3
        )
        quest_item = quest_system.on_monster_killed(monster.kind.name, monster.x, monster.y)
        if quest_item is not None:
            self.items.append(quest_item)
        drop_chance = c.LootBox.DROP_CHANCE
        if self.events.blood_night_active:
            drop_chance *= c.Events.BLOOD_NIGHT_DROP_MULT
        if random.random() < drop_chance:
            self.items.append(Item(monster.x, monster.y, "Lootbox", "lootbox"))
        monster_list.remove(monster)

    def _apply_on_hit_effects(self, monster, monster_list, damage, player, quest_system, died, ranged: bool = False):
        """Weapon lifesteal/burn/execute after a hit lands. `died` is the hit's own result."""
        frac = player.lifesteal_frac(ranged)
        if frac > 0 and damage > 0:
            player.heal(damage * frac)
            get_particles().spawn_burst(player.x, player.y, c.Colors.GREEN, count=5, speed=3, life=300, size=3)
        if died:
            return
        burn = player.burn_damage(ranged)
        if burn > 0:
            monster.apply_burn(burn)
        # Execute finishes off a badly wounded non-boss outright.
        thr = player.execute_threshold(ranged)
        if thr > 0 and not isinstance(monster, Boss) and 0 < monster.hp <= monster.max_hp * thr:
            get_particles().spawn_burst(monster.x, monster.y, (255, 60, 60), count=10, speed=5, life=400, size=4)
            if monster.receive_damage(monster.hp):
                self._kill_monster(monster, monster_list, player, quest_system)

    def _apply_chainstrike(self, primary, target_list, damage, player, quest_system, blocked, ranged: bool = False):
        """Chain Strike: a landed hit also strikes the nearest other target in the same
        list within range, for a fraction of the primary hit's damage."""
        frac = player.chainstrike_frac(ranged)
        if frac <= 0:
            return
        chain_target = min(
            (
                m
                for m in target_list
                if m is not primary and m.distance_to_point((primary.x, primary.y)) < c.Affixes.CHAINSTRIKE_RADIUS
            ),
            key=lambda m: m.distance_to_point((primary.x, primary.y)),
            default=None,
        )
        if chain_target is None:
            return
        chain_damage = max(1, int(damage * frac))
        get_particles().spawn_burst(chain_target.x, chain_target.y, (140, 200, 255), count=8, speed=4, life=300, size=3)
        kb_dir = self._dir_from(primary.x, primary.y, chain_target.x, chain_target.y)
        died = self._resolve_monster_hit(
            chain_target,
            target_list,
            chain_damage,
            player,
            quest_system,
            shake=0.0,
            knockback=0.0,
            kb_dir=kb_dir,
            blocked=blocked,
        )
        self._apply_on_hit_effects(chain_target, target_list, chain_damage, player, quest_system, died, ranged=ranged)

    def _on_boss_killed(self, boss: Boss, quest_system: QuestSystem):
        """A boss dies with extra spectacle and a guaranteed legendary lootbox."""
        get_hitstop().trigger(c.Combat.HITSTOP_BOSS_MS)
        get_decals().spawn(boss.x, boss.y, radius=c.Decals.BOSS_KILL_RADIUS)
        get_particles().spawn_burst(boss.x, boss.y, boss.template.aura, count=40, speed=10, life=800, size=7)
        get_shake().add(c.Boss.SLAM_SHAKE)
        quest_system.on_boss_killed(boss)
        reward = Item(boss.x, boss.y, "Lootbox", "lootbox")
        reward.rarity = c.Boss.REWARD_RARITY
        self.items.append(reward)
        if self.notify:
            self.notify(f"{boss.name} has been slain!", c.Colors.BOSS_BAR_ENRAGED)

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
        self._pop_damage(npc.x, npc.y - c.Entities.NPC_SIZE / 2, damage, crit)
        if npc.receive_damage(damage):
            stolen_item = quest_system.on_npc_killed(npc)
            if stolen_item is not None:
                self.items.append(stolen_item)
            # Drop any quest this NPC was offering so it can't become uncompletable
            quest_system.remove_quest(npc)
            play_sound("monster_death")
            get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
            get_decals().spawn(npc.x, npc.y, radius=c.Decals.KILL_RADIUS)
            get_particles().spawn_burst(npc.x, npc.y, npc.color, count=14, speed=5, life=500, size=5, gravity=0.3)
            self.npcs.remove(npc)
            return True
        self._hit_feedback(npc.x, npc.y, crit, kb_dir)
        self._knockback(npc, c.Entities.NPC_SIZE / 2, kb_dir, knockback, blocked)
        return False

    @staticmethod
    def _hit_feedback(x, y, crit: bool, direction=None):
        """Sound + particle burst for a non-fatal hit; crits read brighter and louder.
        `direction` (attacker -> target unit vector), if given, sprays the particles as a
        cone away from the hit instead of a plain omnidirectional poof."""
        play_sound("crit" if crit else "hit")
        if crit:
            get_hitstop().trigger(c.Combat.HITSTOP_CRIT_MS)
        get_decals().spawn(x, y, radius=c.Decals.HIT_RADIUS)
        color = (255, 240, 160) if crit else (255, 180, 180)
        count = 12 if crit else 6
        speed = 4 if crit else 3
        life = 350 if crit else 300
        size = 4 if crit else 3
        if direction:
            angle = math.atan2(direction[1], direction[0])
            get_particles().spawn_directional_burst(
                x, y, angle, spread_deg=80.0, color=color, count=count, speed=speed, life=life, size=size, gravity=0.35
            )
        else:
            get_particles().spawn_burst(x, y, color, count=count, speed=speed, life=life, size=size)

    @staticmethod
    def _pop_damage(x, y, damage: int, crit: bool):
        """Floating damage number over a hit; crits pop bigger and gold."""
        text = f"{damage}!" if crit else str(damage)
        color = (255, 210, 90) if crit else c.Colors.WHITE
        get_floating_text().spawn(x, y, text, color, big=crit)

    def update_projectiles(self, player: Player, quest_system: QuestSystem, dt):
        for proj in list(self.projectiles):
            proj.update(dt, self.blocked)
            if proj.dead:
                self.projectiles.remove(proj)
                continue

            # A boss's bolts fly past monsters and NPCs and only threaten the player.
            if proj.hostile:
                if proj.distance_to_point((player.x, player.y)) < c.Projectile.SIZE + c.Player.SIZE / 2:
                    player.receive_damage(proj.damage)
                    get_shake().add(proj.shake)
                    self.projectiles.remove(proj)
                continue

            if self._projectile_hits_monster(proj, self.monsters, player, quest_system):
                continue
            if self._projectile_hits_monster(proj, self.bosses, player, quest_system):
                continue
            self._projectile_hits_npc(proj, player, quest_system)

    def _projectile_hits_monster(self, proj: Projectile, targets, player: Player, quest_system: QuestSystem) -> bool:
        """Resolve a projectile against one list of monsters or bosses (both take hits the
        same way). Returns True if it struck something, pierced onward or not."""
        target = next(
            (
                t
                for t in targets
                if id(t) not in proj.hit_ids
                and proj.distance_to_point((t.x, t.y)) < c.Projectile.SIZE + t.kind.size // 2
            ),
            None,
        )
        if target is None:
            return False

        player.stats.train("strength", c.Stats.XP_PER_HIT)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        died = self._resolve_monster_hit(
            target,
            targets,
            proj.damage,
            player,
            quest_system,
            shake=proj.shake,
            knockback=proj.knockback,
            kb_dir=kb_dir,
            blocked=self.blocked,
        )
        self._apply_on_hit_effects(target, targets, proj.damage, player, quest_system, died, ranged=True)
        self._apply_chainstrike(target, targets, proj.damage, player, quest_system, self.blocked, ranged=True)
        self._projectile_after_hit(proj, self.projectiles, target)
        return True

    def _projectile_hits_npc(self, proj: Projectile, player: Player, quest_system: QuestSystem):
        npc = next(
            (
                n
                for n in self.npcs
                if id(n) not in proj.hit_ids
                and proj.distance_to_point((n.x, n.y)) < c.Projectile.SIZE + c.Entities.NPC_SIZE // 2
            ),
            None,
        )
        if npc is None:
            return

        player.stats.train("strength", c.Stats.XP_PER_HIT)
        self._resolve_npc_hit(
            npc,
            proj.damage,
            quest_system,
            shake=proj.shake,
            knockback=proj.knockback,
            kb_dir=self._dir_from(0, 0, proj.vx, proj.vy),
            blocked=self.blocked,
        )
        frac = player.lifesteal_frac(ranged=True)
        if frac > 0:
            player.heal(proj.damage * frac)
        self._projectile_after_hit(proj, self.projectiles, npc)

    def _tick_burns(self, monster_list: List[Monster], player: Player, quest_system: QuestSystem):
        now = pygame.time.get_ticks()
        for monster in list(monster_list):
            if monster.burn_ticks_remaining <= 0 or now < monster.burn_next_ms:
                continue
            monster.burn_ticks_remaining -= 1
            monster.burn_next_ms = now + c.Affixes.BURN_INTERVAL_MS
            get_particles().spawn_burst(monster.x, monster.y, (255, 140, 40), count=4, speed=2, life=300, size=3)
            get_floating_text().spawn(
                monster.x, monster.y - monster.kind.size / 2, str(monster.burn_damage), (255, 150, 60)
            )
            if monster.receive_damage(monster.burn_damage):
                self._kill_monster(monster, monster_list, player, quest_system)

    @staticmethod
    def _projectile_after_hit(proj: Projectile, proj_list: List[Projectile], target):
        """Record the target and either pierce onward (arrow-pierce) or stop the projectile."""
        proj.hit_ids.add(id(target))
        if proj.pierce > 0:
            proj.pierce -= 1
        else:
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

    def _spawn_critter_away_from(self, player: Player):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Wildlife.SPAWN_MIN_DISTANCE, c.Wildlife.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            if not self.blocked(x, y, max(c.Wildlife.SIZES.values()) / 2):
                self.critters.append(Critter(x, y, pick_critter_kind()))
                return

    def _check_shrine_discovery(self, player: Player):
        pos = player.get_pos()
        for poi in self.pois:
            if poi.kind != "shrine" or poi.discovered:
                continue
            if poi.distance_to_point(pos) < c.PointsOfInterest.DISCOVER_DISTANCE:
                poi.discovered = True
                if self.notify:
                    self.notify(random.choice(c.PointsOfInterest.SHRINE_MESSAGES), c.Colors.WHITE)

    def update(self, player: Player, dt, quest_system: QuestSystem, npc_name_generator: NPCNameGenerator):
        # Particles/floating text/screen fx update once per frame in Game.run() instead of
        # here, so they keep animating even while a menu pauses the rest of this update.
        self._sync_chunks(player)
        self.daynight.update(dt)
        self.events.update(dt, player, quest_system, npc_name_generator)
        self._check_shrine_discovery(player)

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt).
        update_radius = c.World.DETECTION_RANGE + c.Player.SIZE
        for monster in self.monsters:
            if abs(monster.x - player.x) <= update_radius and abs(monster.y - player.y) <= update_radius:
                monster.move(player, dt, self.blocked)

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        self.monsters = [m for m in self.monsters if m.distance_to_point(player.get_pos()) <= c.World.DESPAWN_DISTANCE]

        # Burn (weapon affix) ticks over time and can finish a wounded target off.
        self._tick_burns(self.monsters, player, quest_system)
        self._tick_burns(self.bosses, player, quest_system)

        # Bosses never despawn; they chase, cast and enrage on their own schedule.
        for boss in list(self.bosses):
            boss.update_boss(self, player, dt, quest_system)

        self.boss_roam_timer += dt
        if self.boss_roam_timer >= c.Boss.ROAM_CHECK_INTERVAL_MS:
            self.boss_roam_timer = 0.0
            self._maybe_spawn_roaming_boss(player)

        self.update_projectiles(player, quest_system, dt)

        for npc in self.npcs:
            npc.update(player, dt, self.blocked)

        for critter in self.critters:
            critter.update(player, dt, self.blocked)
        player_pos = player.get_pos()
        self.critters = [
            critter for critter in self.critters if critter.distance_to_point(player_pos) <= c.Wildlife.DESPAWN_DISTANCE
        ]
        if len(self.critters) < c.Wildlife.COUNT:
            self.critter_respawn_timer += dt
            if self.critter_respawn_timer >= c.Wildlife.RESPAWN_INTERVAL_MS:
                self.critter_respawn_timer = 0.0
                self._spawn_critter_away_from(player)

        if len(self.monsters) < c.World.NB_MONSTERS:
            self.respawn_timer += dt
            respawn_interval = c.World.RESPAWN_INTERVAL_MS
            if self.events.blood_night_active:
                respawn_interval /= c.Events.BLOOD_NIGHT_RESPAWN_MULT
            elif self.daynight.is_night:
                respawn_interval /= c.DayNight.NIGHT_RESPAWN_MULT
            if self.respawn_timer >= respawn_interval:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
