from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.particles import get_particles
from core.screen_fx import get_hitstop
from game.entities.boss import Boss
from game.entities.breakables import Breakable
from game.entities.buildings import Building
from game.entities.critter import Critter
from game.entities.items import Item, rarity_color, rarity_tier
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest
from game.entities.projectile import ARROW_COLOR, BOLT_COLOR, Projectile
from game.loot import break_crate, open_poi_cache

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


class WorldCombat:
    """Everything that resolves a blow: swings, shots, the damage each one does, the loot and
    gore it leaves behind, and the projectiles still in the air.

    Mixed into `World`, which owns the entity lists these methods read and mutate
    (`monsters`, `bosses`, `npcs`, `critters`, `items`, `pois`, `breakables`, `projectiles`).
    Split out of `world.py` purely for size: this is one coherent job, and the rest of the
    class is world state and lookups.
    """

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
            self._fire_ranged(player, c.weapon_archetype(weapon.name))
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
        origin = player.get_pos()
        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus() + player.stats.attack_bonus()
        ) * player.damage_multiplier()
        hit_radius = reach * (arch.cleave_radius_mult if arch.cleave else 1.0)

        def in_reach(entities, size_of):
            return self._targets_in_reach(
                entities, pos, hit_radius, size_of, arch.cleave, origin, arch.min_hit_distance
            )

        if self.bosses:
            boss_targets = in_reach(self.bosses, lambda b: b.kind.size)
            if boss_targets:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
                for boss in boss_targets:
                    self._strike_monster(boss, self.bosses, base_damage, arch, player, quest_system, blocked)
                return

        monster_targets = in_reach(self.monsters, lambda m: m.kind.size)
        if monster_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for monster in monster_targets:
                self._strike_monster(monster, self.monsters, base_damage, arch, player, quest_system, blocked)
            return

        # Wildlife is struck before villagers, so hunting a rabbit in a crowd doesn't start
        # a brawl, and after monsters, so a fox never soaks a swing meant for a wolf.
        critter_targets = in_reach(self.critters, lambda cr: cr.hit_radius * 2)
        if critter_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for critter in critter_targets:
                self._strike_critter(critter, base_damage, arch, player)
            return

        npc_targets = in_reach(self.npcs, lambda n: c.Entities.NPC_SIZE)
        if npc_targets:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            for npc in npc_targets:
                self._strike_npc(npc, base_damage, arch, player, quest_system, blocked)
            return

        # A swing that reaches a shop/tavern crate smashes it instead.
        for building in self.buildings_around(*pos):
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
    def _targets_in_reach(
        entities, pos, hit_radius, size_of, cleave: bool, origin=None, min_distance: float = 0.0
    ) -> list:
        """Entities within a swing's reach: every one in range if the weapon cleaves,
        otherwise just the nearest.

        `min_distance` is the weapon's blind spot measured from `origin` (the player's own
        position): a spear covers a ring, not a disc, so anything pressed up against the
        player is past the point of the shaft and takes nothing."""
        targets = [e for e in entities if e.distance_to_point(pos) < hit_radius + size_of(e) // 2]
        if min_distance and origin is not None:
            targets = [e for e in targets if e.distance_to_point(origin) >= min_distance]
        if not targets or cleave:
            return targets
        return [min(targets, key=lambda e: e.distance_to_point(pos))]

    def _find_window_in_reach(self, pos, hit_radius):
        """Nearest unbroken window (on any non-landmark building) a swing reaches, as
        (building, index, rect), or None."""
        px, py = pos
        best = None
        for building in self.buildings_around(px, py):
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

    def _fire_ranged(self, player: Player, arch: c.WeaponArchetype):
        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:
            return
        if arch.uses_ammo:
            # Ammo stacks per rarity, so shoot the cheapest quiver first: rarity only
            # changes what a stack sells for, and nobody wants to fire legendary arrows
            # at slimes while common ones sit in the bag.
            ammo = min(
                (item for item in player.inventory if item.item_type == "ammo"),
                key=lambda item: rarity_tier(item.rarity).price_mult,
                default=None,
            )
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
        style, color = ("bolt", BOLT_COLOR) if arch.name == "staff" else ("arrow", ARROW_COLOR)
        proj = Projectile(
            player.x,
            player.y,
            player.orientation,
            damage,
            style=style,
            color=color,
            knockback=arch.knockback,
            shake=arch.shake + crit_shake + rampage_shake,
        )
        proj.pierce = player.pierce_count()
        self.projectiles.append(proj)

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

    def _strike_critter(self, critter: Critter, base_damage, arch, player: Player):
        """Wildlife takes hits like anything else, but never fights back: a survivor just
        bolts. No quest system involvement, no loot table, nothing to burn or chain into."""
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus())
        get_shake().add(arch.shake + (c.Combat.CRIT_SHAKE_BONUS if crit else 0.0))
        self._pop_damage(critter.x, critter.y - critter.size / 2, damage, crit)
        kb_dir = self._dir_from(player.x, player.y, critter.x, critter.y)
        if critter.receive_damage(damage):
            self._kill_critter(critter, player, kb_dir)
            return
        self._hit_feedback(critter.x, critter.y, crit, kb_dir)
        self._knockback(critter, critter.size / 2, kb_dir, arch.knockback, self.blocked)
        critter.startle()

    def _kill_critter(self, critter: Critter, player: Player, direction=None):
        """A hunted animal leaves a pelt worth selling, and nothing else: critters are
        session-only, so the drop is the only trace of it that reaches the save."""
        play_sound("monster_death")
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        self._spill_blood(critter.x, critter.y, c.Wildlife.COLORS[critter.kind], direction)
        player.stats.train("vitality", c.Stats.XP_PER_KILL * 0.5)
        if random.random() < c.Wildlife.DROP_CHANCE[critter.kind]:
            drop = Item(critter.x, critter.y, c.Wildlife.DROP_NAMES[critter.kind], "misc", rarity="common")
            drop.start_pop_anim(critter.x, critter.y - critter.size)
            self.items.append(drop)
        self.critters.remove(critter)

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
        """Smash a wilderness ruins pile or bandit camp cache: same feedback as an outdoor
        barrel, better odds and rarity since it took more effort to find. Left in place
        afterwards (not removed like a breakable) so the ruin/camp still reads as a landmark,
        just picked over.

        A bandit camp's cache stays shut while its owners are still on their feet: the loot
        is the reward for clearing the camp, not for running past it."""
        if poi.kind == "camp" and not self.camp_is_clear(poi):
            if self.notify:
                self.notify("The camp is still guarded", c.Colors.MUTED)
            return
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
            self._kill_monster(monster, monster_list, player, quest_system, direction=kb_dir)
            return True
        self._hit_feedback(monster.x, monster.y, crit, kb_dir)
        if not monster.knockback_immune:
            self._knockback(monster, monster.kind.size / 2, kb_dir, knockback, blocked)
        return False

    @staticmethod
    def _spill_blood(x, y, body_color, direction=None, boss: bool = False):
        """The gore of a kill: a pool where it dropped, a fan of droplets thrown along the
        killing blow, and a spray still in the air over both.

        `direction` is the blow's (dx, dy) unit vector, so the mess points away from the
        player instead of ringing the corpse. A kill with no direction (a burn tick, an
        execute) bursts outward instead."""
        decals = get_decals()
        decals.spawn(x, y, radius=c.Decals.BOSS_KILL_RADIUS if boss else c.Decals.KILL_RADIUS)
        decals.spawn_spray(
            x,
            y,
            direction,
            count=c.Decals.BOSS_SPRAY_COUNT if boss else c.Decals.KILL_SPRAY_COUNT,
            distance=c.Decals.BOSS_SPRAY_DISTANCE if boss else c.Decals.KILL_SPRAY_DISTANCE,
            radius=c.Decals.BOSS_SPRAY_RADIUS if boss else c.Decals.KILL_SPRAY_RADIUS,
        )

        blood = (178, 26, 26)
        count = 34 if boss else 22
        speed = 12 if boss else 9
        size = 6 if boss else 5
        if direction:
            get_particles().spawn_directional_burst(
                x,
                y,
                math.atan2(direction[1], direction[0]),
                spread_deg=c.Decals.SPRAY_SPREAD_DEG,
                color=blood,
                count=count,
                speed=speed,
                life=700,
                size=size,
                gravity=0.32,
            )
        else:
            get_particles().spawn_burst(x, y, blood, count=count, speed=speed, life=700, size=size, gravity=0.32)
        # Chunks of the thing itself, so a slime still bleeds green over the red.
        get_particles().spawn_burst(x, y, body_color, count=16 if boss else 12, speed=6, life=550, size=5, gravity=0.42)

    def _kill_monster(self, monster, monster_list, player: Player, quest_system: QuestSystem, direction=None):
        """Death rewards and cleanup for a slain monster, shared by hits and burn ticks."""
        player.stats.train("vitality", c.Stats.XP_PER_KILL)
        play_sound("monster_death")
        # Bloodlust: any kill with a weapon carrying it refreshes the damage buff.
        bloodlust = player.bloodlust_mult()
        if bloodlust > 1.0:
            player.apply_buff("bloodlust", bloodlust, c.Affixes.BLOODLUST_DURATION_S)
        if isinstance(monster, Boss):
            self._on_boss_killed(monster, quest_system, direction)
            monster_list.remove(monster)
            return
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        self._spill_blood(monster.x, monster.y, monster.kind.color, direction)
        quest_item = quest_system.on_monster_killed(monster.kind.name, monster.x, monster.y)
        if quest_item is not None:
            self.items.append(quest_item)
        drop_chance = c.LootBox.DROP_CHANCE
        if self.events.blood_night_active:
            drop_chance *= c.Events.BLOOD_NIGHT_DROP_MULT
        if random.random() < drop_chance:
            self.items.append(Item(monster.x, monster.y, "Lootbox", "lootbox"))
        # A camp guard's death is the camp's business: it is what opens the cache, and the
        # only thing that lowers the garrison it stands back up from on the next chunk load.
        if monster.camp_id:
            self.on_guard_killed(monster)
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

    def _on_boss_killed(self, boss: Boss, quest_system: QuestSystem, direction=None):
        """A boss dies with extra spectacle and a guaranteed legendary lootbox."""
        get_hitstop().trigger(c.Combat.HITSTOP_BOSS_MS)
        self._spill_blood(boss.x, boss.y, boss.template.color, direction, boss=True)
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
            self._spill_blood(npc.x, npc.y, npc.color, kb_dir)
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
            if self._projectile_hits_critter(proj, player):
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
        self._projectile_after_hit(proj, target)
        return True

    def _projectile_hits_critter(self, proj: Projectile, player: Player) -> bool:
        """Resolve a projectile against wildlife: an arrow is how most animals get hunted,
        since they run long before a swing lands. Returns True if it struck one."""
        critter = next(
            (
                cr
                for cr in self.critters
                if id(cr) not in proj.hit_ids
                and proj.distance_to_point((cr.x, cr.y)) < c.Projectile.SIZE + cr.hit_radius
            ),
            None,
        )
        if critter is None:
            return False

        player.stats.train("strength", c.Stats.XP_PER_HIT)
        get_shake().add(proj.shake)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        self._pop_damage(critter.x, critter.y - critter.size / 2, proj.damage, False)
        if critter.receive_damage(proj.damage):
            self._kill_critter(critter, player, kb_dir)
        else:
            self._hit_feedback(critter.x, critter.y, False, kb_dir)
            self._knockback(critter, critter.size / 2, kb_dir, proj.knockback, self.blocked)
            critter.startle()
        self._projectile_after_hit(proj, critter)
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
        self._projectile_after_hit(proj, npc)

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

    def _projectile_after_hit(self, proj: Projectile, target):
        """Record the target and either pierce onward (arrow-pierce) or stop the projectile."""
        proj.hit_ids.add(id(target))
        if proj.pierce > 0:
            proj.pierce -= 1
        else:
            self.projectiles.remove(proj)
