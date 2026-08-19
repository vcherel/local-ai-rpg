from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.damage_fx import get_damage_fx
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.impact_fx import get_impacts
from core.particles import get_particles
from core.screen_fx import get_hitstop
from core.swing_arcs import get_swings
from game.entities.boss import Boss
from game.entities.breakables import Breakable
from game.entities.buildings import Building
from game.entities.critter import Critter
from game.entities.entities import Entity
from game.entities.items import Item, rarity_color, roll_rarity
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest
from game.entities.projectile import ARROW_COLOR, BOLT_COLOR, Projectile
from game.loot import break_crate, loot_villager, open_poi_cache

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
            player.end_spawn_grace()
            self._fire_ranged(player, c.weapon_archetype(weapon.name))
            return

        weapon = player.active_melee_weapon()
        arch = c.weapon_archetype(weapon.name if weapon else None)

        now = pygame.time.get_ticks()
        if now < player.attack_ready_ms:  # still on cooldown from the previous swing
            return
        player.attack_ready_ms = now + arch.cooldown_ms
        player.attack_swing_mult = arch.swing_mult
        # Swinging spends whatever is left of the spawn grace: it is there to get the player
        # out of what killed them, not to let them open a fight untouchable.
        player.end_spawn_grace()

        player.start_attack_anim("right")
        play_sound("attack")

        reach = c.Player.ATTACK_REACH * arch.reach_mult
        pos = player.get_pos(reach)
        origin = player.get_pos()
        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus() + player.stats.attack_bonus()
        ) * player.damage_multiplier()
        hit_radius = reach * (arch.cleave_radius_mult if arch.cleave else 1.0)

        # What the attack covers, drawn and enforced from the same numbers, so what is on
        # screen is what the hit test accepts rather than three damage numbers popping at
        # once and being inferred from. A thrust is a lane down the facing, a sweep a wedge.
        if arch.pierce_melee:
            # The lane runs out to where the hit test actually stops: the swing point is
            # `reach` ahead of the player and the test covers `hit_radius` around it.
            get_swings().spawn_thrust(
                origin[0], origin[1], player.orientation, reach + hit_radius, arch.min_hit_distance
            )
        else:
            get_swings().spawn(origin[0], origin[1], player.orientation, reach, arch.arc_deg, arch.cleave)

        # A thrust's share per target: the first body on the shaft takes it all and every
        # one behind it a little less, filled in as each group is found.
        lane_share: dict = {}

        def in_reach(entities, size_of):
            return self._targets_in_reach(
                entities,
                pos,
                hit_radius,
                size_of,
                arch.cleave,
                origin,
                arch.min_hit_distance,
                player.orientation,
                arch.arc_deg,
                arch.pierce_melee,
            )

        def falloff(target):
            """What this particular target takes of the swing. Full damage for anything the
            weapon is actually pointed at; a cleave bleeds out toward the edge of its arc and
            the end of its reach, so sweeping six things at once is worth doing and worth
            less per head than picking one of them. A thrust instead loses a fixed share per
            body it has already gone through."""
            if arch.pierce_melee:
                return base_damage * lane_share.get(id(target), 1.0)
            if not arch.cleave:
                return base_damage
            return base_damage * self._cleave_falloff(origin, player.orientation, arch, hit_radius, target)

        def strike_boss(boss):
            self._strike_monster(boss, self.bosses, falloff(boss), arch, player, quest_system, blocked)

        def strike_monster(monster):
            self._strike_monster(monster, self.monsters, falloff(monster), arch, player, quest_system, blocked)

        def strike_critter(critter):
            self._strike_critter(critter, falloff(critter), arch, player)

        def strike_npc(npc):
            self._strike_npc(npc, falloff(npc), arch, player, quest_system, blocked)

        # Target priority: bosses and monsters, then whatever is already fighting back (an
        # animal biting, a villager swinging), then the peaceful. A rabbit standing behind
        # a wolf must never soak the blow meant for the wolf, and hunting one in a crowded
        # street must not land on a bystander and start a brawl. The swing goes to the
        # first group with anything in reach.
        #
        # A cleaving weapon then carries on through the hostile groups under that one: a
        # sweep that catches a goblin and the villager swinging beside it hits both, since a
        # wide blade does not stop at a species. It never reaches the peaceful groups, so
        # hunting a rabbit in a crowded street still cannot start a brawl.
        hostile_groups = 4
        engaged = False
        for index, (group, size_of, strike) in enumerate(
            (
                (self.bosses, lambda e: e.kind.size, strike_boss),
                (self.monsters, lambda e: e.kind.size, strike_monster),
                ([cr for cr in self.critters if cr.hostile], lambda e: e.hit_radius * 2, strike_critter),
                ([npc for npc in self.npcs if npc.hostile], lambda e: c.Entities.NPC_SIZE, strike_npc),
                (self.critters, lambda e: e.hit_radius * 2, strike_critter),
                (self.npcs, lambda e: c.Entities.NPC_SIZE, strike_npc),
            )
        ):
            if engaged and not ((arch.cleave or arch.pierce_melee) and index < hostile_groups):
                break
            targets = in_reach(group, size_of)
            if not targets:
                continue
            if arch.pierce_melee:
                lane_share.update(self._thrust_shares(origin, targets))
            if not engaged:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
            engaged = True
            for target in targets:
                strike(target)
        if engaged:
            return

        # Nothing living in range: the swing goes into the scenery. Props take the weapon's
        # damage rather than breaking on contact, so a heavy hammer clears a barrel in one
        # blow and a dagger has to work at it.
        prop_damage = max(1, int(round(base_damage * arch.damage_mult)))
        blow = player.orientation

        for building in self.buildings_in_range(*pos, c.World.CHUNK_SIZE):
            hit = building.damage_prop_at(pos, hit_radius, prop_damage)
            if hit is not None:
                index, rect, kind, destroyed = hit
                if destroyed:
                    self._break_prop(player, building, rect, kind)
                else:
                    self._prop_chip(
                        rect.centerx, rect.centery, (150, 110, 70), "crate_break", building.prop_key(index), blow
                    )
                return

        poi_hit = next(
            (
                p
                for p in self.pois
                if p.has_loot and not p.looted and p.distance_to_point(pos) < hit_radius + c.PointsOfInterest.HIT_RADIUS
            ),
            None,
        )
        if poi_hit is not None:
            self._hit_poi(player, poi_hit, prop_damage, blow)
            return

        breakable = next(
            (b for b in self.breakables if b.distance_to_point(pos) < hit_radius + c.Breakables.HIT_RADIUS), None
        )
        if breakable is not None:
            self._hit_breakable(player, breakable, prop_damage, quest_system, blow)
            return

        window_hit = self._find_window_in_reach(pos, hit_radius)
        if window_hit is not None:
            building, idx, window = window_hit
            self._hit_window(building, idx, window, prop_damage, blow)

    @staticmethod
    def _targets_in_reach(
        entities,
        pos,
        hit_radius,
        size_of,
        cleave: bool,
        origin=None,
        min_distance: float = 0.0,
        facing: float | None = None,
        arc_deg: float = 360.0,
        pierce: bool = False,
    ) -> list:
        """Entities within a swing's reach: every one in range if the weapon cleaves,
        otherwise just the nearest.

        `min_distance` is the weapon's blind spot measured from `origin` (the player's own
        position): a spear covers a ring, not a disc, so anything pressed up against the
        player is past the point of the shaft and takes nothing.

        `facing`/`arc_deg` are the wedge the swing covers, the same one drawn on screen by
        `core.swing_arcs`. Without it a cleaving weapon caught things standing behind the
        player, which the drawn arc would then be lying about.

        `pierce` swaps that wedge for a lane: a thrust skewers everything standing along
        the shaft, out to `hit_radius` and past the blind spot, which is what the spear's
        dead zone buys and why lining a pack up is worth doing."""
        if pierce and origin is not None and facing is not None:
            # The lane is as long as the disc test is deep: out to the swing point and the
            # hit radius around it, so a thrust reaches exactly as far as any other swing.
            reach = math.hypot(pos[0] - origin[0], pos[1] - origin[1]) + hit_radius
            return WorldCombat._targets_in_lane(entities, origin, facing, reach, min_distance, size_of)
        targets = [e for e in entities if e.distance_to_point(pos) < hit_radius + size_of(e) // 2]
        if min_distance and origin is not None:
            targets = [e for e in targets if e.distance_to_point(origin) >= min_distance]
        if facing is not None and origin is not None and arc_deg < 360.0:
            targets = [e for e in targets if WorldCombat._within_arc(origin, facing, arc_deg, e.x, e.y)]
        if not targets or cleave:
            return targets
        return [min(targets, key=lambda e: e.distance_to_point(pos))]

    @staticmethod
    def _targets_in_lane(entities, origin, facing: float, reach: float, min_distance: float, size_of) -> list:
        """Everything standing on the line a thrust runs down, nearest first.

        Measured as two distances rather than an angle: how far along the facing a target
        is (which has to fall between the blind spot and the reach) and how far off to the
        side of it (which has to be inside `Combat.THRUST_LANE_WIDTH` plus its own bulk).
        An angle would make the lane a wedge again, widening with distance, and the point
        of a spear is that it is exactly as wide at the tip as at the hand."""
        sin_a, cos_a = math.sin(facing), math.cos(facing)
        hits = []
        for entity in entities:
            dx, dy = entity.x - origin[0], entity.y - origin[1]
            along = dx * sin_a - dy * cos_a
            across = abs(dx * cos_a + dy * sin_a)
            half = size_of(entity) / 2
            if min_distance <= along <= reach + half and across <= c.Combat.THRUST_LANE_WIDTH + half:
                hits.append((along, entity))
        return [entity for _, entity in sorted(hits, key=lambda pair: pair[0])]

    @staticmethod
    def _thrust_shares(origin, targets) -> dict:
        """What each skewered target takes of the thrust: full for the first body on the
        shaft, `Combat.THRUST_FALLOFF` of the one before it for everything behind."""
        ordered = sorted(targets, key=lambda e: e.distance_to_point(origin))
        return {id(entity): c.Combat.THRUST_FALLOFF**index for index, entity in enumerate(ordered)}

    @staticmethod
    def _cleave_falloff(origin, facing: float, arch, hit_radius: float, target) -> float:
        """How much of a cleaving swing lands on one target: 1.0 for whatever is dead ahead
        at arm's length, down to `Combat.CLEAVE_MIN` for whatever is caught at the edge of
        the arc or at the far end of the reach.

        A cleave used to hit six things for full damage each, which made a wide weapon
        strictly better than a focused one in every crowd. Now the crowd is worth sweeping
        and the single target is worth facing."""
        dx, dy = target.x - origin[0], target.y - origin[1]
        distance = math.hypot(dx, dy)
        # Angles here are measured from straight up, clockwise, like every facing.
        delta = math.atan2(dx, -dy) - facing
        delta = abs((delta + math.pi) % (2 * math.pi) - math.pi)
        half_arc = max(math.radians(arch.arc_deg) / 2, 1e-6)
        angle_off = min(1.0, delta / half_arc)
        range_off = min(1.0, distance / max(hit_radius, 1e-6))
        loss = angle_off * c.Combat.CLEAVE_ANGLE_SHARE + range_off * (1 - c.Combat.CLEAVE_ANGLE_SHARE)
        return 1.0 - loss * (1.0 - c.Combat.CLEAVE_MIN)

    @staticmethod
    def _within_arc(origin, facing: float, arc_deg: float, x, y) -> bool:
        """Is (x, y) inside the wedge of `arc_deg` centred on `facing` from `origin`?

        Anything all but on top of the swinger counts as inside: its bearing is noise at
        that range, and a weapon that misses what is hugging the player reads as broken."""
        dx, dy = x - origin[0], y - origin[1]
        if math.hypot(dx, dy) < 20:
            return True
        # Angles here are measured from straight up, clockwise, like every facing.
        delta = math.atan2(dx, -dy) - facing
        delta = (delta + math.pi) % (2 * math.pi) - math.pi
        return abs(delta) <= math.radians(arc_deg) / 2

    def _find_window_in_reach(self, pos, hit_radius):
        """Nearest unbroken window (on any non-landmark building) a swing reaches, as
        (building, index, rect), or None."""
        px, py = pos
        best = None
        for building in self.buildings_in_range(px, py, c.World.CHUNK_SIZE):
            for idx, window in enumerate(building.window_rects()):
                if idx in building.broken_windows:
                    continue
                dist = math.hypot(px - window.centerx, py - window.centery)
                if dist < hit_radius + c.Buildings.WINDOW_HIT_RADIUS and (best is None or dist < best[0]):
                    best = (dist, building, idx, window)
        return None if best is None else (best[1], best[2], best[3])

    @staticmethod
    def _prop_chip(x, y, color, sound: str = "hit", key: str | None = None, angle: float = 0.0):
        """A blow that damaged a prop without finishing it: a small puff, a knock, and the
        prop itself flinching and cracking, so hitting something breakable always reads as
        progress even when it holds.

        `key` is what identifies the prop to `core.damage_fx`, which is what the drawing
        side reads back: props are not all objects (a crate is an index into a building's
        layout), so the registry is keyed by string rather than by identity."""
        get_shake().add(c.Combat.DECOR_BREAK_SHAKE * 0.5)
        play_sound(sound)
        get_particles().spawn_burst(x, y, color, count=5, speed=4, life=280, size=3, gravity=0.4, shape="shard")
        if key is not None:
            get_damage_fx().hit(key, angle)

    def _hit_window(self, building: Building, idx: int, window, damage: int, angle: float = 0.0):
        """Crack a window, and shatter it once it has taken enough."""
        remaining = building.window_hp.get(idx, c.Buildings.WINDOW_HP) - damage
        if remaining > 0:
            building.window_hp[idx] = remaining
            self._prop_chip(
                window.centerx, window.centery, (210, 230, 240), "glass_break", f"{building.id}:window:{idx}", angle
            )
            return
        building.window_hp.pop(idx, None)
        self._break_window(building, idx, window)

    def blocking_door(self, chaser, player: Player) -> Building | None:
        """The shut door standing between a chaser and the player, once the chaser is at it.

        A door is the one obstacle in the world that cannot be walked round, which is exactly
        why it is the one a monster is allowed to break. Either the player is inside and the
        chaser out, or the other way about: anything else means the door is not what is
        keeping them apart."""
        building = self.building_at(player.x, player.y) or self.building_at(chaser.x, chaser.y)
        if building is None or not building.door_closed:
            return None
        if building.contains_point(chaser.x, chaser.y) == building.contains_point(player.x, player.y):
            return None
        door = building.door_rect()
        if math.hypot(chaser.x - door.centerx, chaser.y - door.centery) > c.Buildings.DOOR_BASH_REACH:
            return None
        return building

    def bash_doors(self, player: Player, damage_mult: float = 1.0):
        """Let every monster held up at a shut door beat on it.

        Kept here rather than on `Monster` for the same reason a monster's arrow is: the door
        belongs to the world, and what happens to it is a blow landing on a hit-point pool
        like any other. It takes the monster's own damage, so a troll is through a door in a
        few swings and a slime is a long while about it, and the hole it leaves is permanent."""
        now = pygame.time.get_ticks()
        for monster in self.monsters:
            # Cheap box test first: only something already on the player can be held up by
            # a door between them, and this runs over every monster alive every frame.
            if (
                abs(monster.x - player.x) > c.World.DETECTION_RANGE
                or abs(monster.y - player.y) > c.World.DETECTION_RANGE
            ):
                continue
            building = self.blocking_door(monster, player)
            if building is None or now < monster.next_bash_ms:
                continue
            monster.next_bash_ms = now + c.Buildings.DOOR_BASH_COOLDOWN_MS
            # Monster.start_attack_anim resolves a melee hit from a distance; the door wants
            # the swing only, so it goes to the plain Entity one.
            Entity.start_attack_anim(monster)
            door = building.door_rect()
            angle = math.atan2(door.centery - monster.y, door.centerx - monster.x)
            self._hit_door(building, round(monster.kind.damage * damage_mult), angle)

    def _hit_door(self, building: Building, damage: int, angle: float = 0.0):
        """Land a blow on a shut door, and put it through once it has taken enough."""
        door = building.door_rect()
        if not building.damage_door(damage):
            self._prop_chip(door.centerx, door.centery, c.Buildings.DOOR_COLOR, "crate_break", building.door_key, angle)
            return
        get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(
            door.centerx,
            door.centery,
            c.Buildings.DOOR_COLOR,
            count=18,
            speed=6,
            life=520,
            size=4,
            gravity=0.5,
            shape="shard",
        )

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
        # A boomerang is thrown, not fired: there is only ever one of them in the air, and
        # waiting for it to come home is what it costs instead of ammo.
        if arch.projectile_style == "boomerang" and any(
            proj.style == "boomerang" and proj.owner_id == id(player) for proj in self.projectiles
        ):
            return
        if arch.uses_ammo:
            # `Player.ready_ammo` is the quiver in the ammo slot, or the cheapest carried
            # once that one is empty, and it is what the HUD counts too, so the number on
            # screen is always the stack the next shot spends.
            ammo = player.ready_ammo()
            if ammo is None:
                return
            ammo.quantity -= 1
            if ammo.quantity <= 0:
                player.unequip_if_equipped(ammo)
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
        style = arch.projectile_style
        color = c.STAFF_BOLT_COLORS[arch.element] if style == "bolt" else ARROW_COLOR
        if style == "boomerang":
            color = c.Boomerang.COLOR
        proj = Projectile(
            player.x,
            player.y,
            player.orientation,
            damage,
            style=style,
            color=color,
            knockback=arch.knockback,
            shake=arch.shake + crit_shake + rampage_shake,
            owner_id=id(player),
            max_range=c.Boomerang.OUT_RANGE if style == "boomerang" else None,
        )
        # What the shot does beyond damage, carried by the projectile rather than looked up
        # again when it lands: the weapon that threw it may well have been swapped by then.
        proj.element = arch.element
        proj.pierce = player.pierce_count()
        if style == "boomerang":
            proj.owner = player
            proj.pierce += c.Boomerang.PIERCE
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

    KNOCKBACK_STEP = 8.0

    @staticmethod
    def _knockback(target, radius, kb_dir, distance, blocked):
        """Shove a target along kb_dir, sliding along walls one axis at a time.

        Walked out in short hops rather than in one jump, for the reason a projectile is:
        testing only where the shove ends puts whatever was hit on the far side of a thin
        wall, and a pole shoves things far enough for that to be most of a room."""
        if not kb_dir or distance <= 0:
            return
        steps = max(1, math.ceil(distance / WorldCombat.KNOCKBACK_STEP))
        step_x, step_y = kb_dir[0] * distance / steps, kb_dir[1] * distance / steps
        for _ in range(steps):
            moved = False
            if blocked is None or not blocked(target.x + step_x, target.y, radius):
                target.x += step_x
                moved = True
            if blocked is None or not blocked(target.x, target.y + step_y, radius):
                target.y += step_y
                moved = True
            if not moved:
                return

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
            player,
            quest_system,
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=kb_dir,
            blocked=blocked,
        )

    def _strike_critter(self, critter: Critter, base_damage, arch, player: Player):
        """Wildlife takes hits like anything else. What a survivor does about it is its own
        temperament's business: a rabbit bolts, a boar turns round, a pack all turns round
        at once (`World.aggro_pack`). No quest system involvement, no loot table, nothing to
        burn or chain into."""
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
        self.aggro_pack(critter)

    def _kill_critter(self, critter: Critter, player: Player, direction=None, by_player: bool = True):
        """A hunted animal leaves a pelt worth selling, and nothing else: critters are
        session-only, so the drop is the only trace of it that reaches the save.

        The pelt is left even when something else did the killing (it is lying there, and
        the player is welcome to it); the hunting xp is not."""
        play_sound("monster_death")
        if by_player:
            get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
            player.stats.train("vitality", c.Stats.XP_PER_KILL * 0.5)
        self._spill_blood(critter.x, critter.y, critter.kind.color, direction)
        if critter.kind.drop_name and random.random() < critter.kind.drop_chance:
            drop = Item(critter.x, critter.y, critter.kind.drop_name, "misc", rarity="common")
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

    def _break_prop(self, player: Player, building: Building, rect, kind: str):
        """Take a piece of furniture apart: splinters, and for the two kinds that hold wares
        a few coins and a small chance of a dropped item.

        The piece has already been removed from the interior's collision set by
        `damage_prop_at`; here we handle the feedback and the loot. Coins are credited
        straight away; an item (if any) pops out onto the floor for the player to walk over
        and collect, rather than jumping straight into the inventory. A table pays nothing,
        which is the point: most of a room is somebody's furniture, not a container.
        """
        self._break_effects(rect.centerx, rect.centery, (150, 110, 70), 20)
        # Wrecking somebody's room is a crime like emptying their chest: whoever sees it
        # comes for the player alone, and the rest of the street never hears about it.
        self.report_crime(rect.centerx, rect.centery)
        if kind not in c.Buildings.FURNITURE_LOOT:
            return
        coins, loot_item = break_crate()
        label = "Crate smashed" if kind == "crate" else "Shelf cleared"
        self._break_loot(player, rect.centerx, rect.centery, coins, loot_item, label, building.dropped_items.append)

    def _hit_poi(self, player: Player, poi: PointOfInterest, damage: int, angle: float = 0.0):
        """Work at a ruins pile or a camp cache. It takes several blows to force one open,
        which is why the guard check comes first: nobody chips away at a strongbox with
        three bandits still standing over it."""
        if poi.kind == "camp" and not self.camp_is_clear(poi):
            if self.notify:
                self.notify("The camp is still guarded", c.Colors.MUTED)
            return
        poi.cache_hp -= damage
        if poi.cache_hp > 0:
            self._prop_chip(poi.x, poi.y, (150, 140, 120), "crate_break", f"poi:{poi.id}", angle)
            return
        self._break_poi(player, poi)

    def _break_poi(self, player: Player, poi: PointOfInterest):
        """Smash a wilderness ruins pile or bandit camp cache: same feedback as an outdoor
        barrel, better odds and rarity since it took more effort to find. Left in place
        afterwards (not removed like a breakable) so the ruin/camp still reads as a landmark,
        just picked over.

        A bandit camp's cache stays shut while its owners are still on their feet, which
        `_hit_poi` checks before any blow lands on it: the loot is the reward for clearing
        the camp, not for running past it."""
        poi.looted = True
        self._break_effects(poi.x, poi.y, (150, 140, 120), 20)
        coins, loot_item = open_poi_cache(player.loot_luck())
        label = {"camp": "Camp cache", "farmstead": "Farmstead searched"}.get(poi.kind, "Ruins searched")
        self._break_loot(player, poi.x, poi.y, coins, loot_item, label, self.items.append)

    def _hit_breakable(
        self, player: Player, breakable: Breakable, damage: int, quest_system: QuestSystem, angle: float = 0.0
    ):
        """Take a swing at an outdoor prop. A bush goes down in one, a barrel takes a
        beating; either way the reward only comes when it finally gives."""
        breakable.hp -= damage
        if breakable.hp > 0:
            color = (80, 150, 65) if breakable.kind == "bush" else (150, 110, 70)
            self._prop_chip(
                breakable.x,
                breakable.y,
                color,
                "bush_rustle" if breakable.kind == "bush" else "hit",
                breakable.damage_key,
                angle,
            )
            return
        self._break_breakable(player, breakable, quest_system)

    def _break_breakable(self, player: Player, breakable: Breakable, quest_system: QuestSystem):
        """Smash an outdoor prop. A barrel plays out like a shop crate: juice, coins,
        and a small chance of a dropped item landing straight in the open world. A powder
        keg pays nothing and goes off instead. Anything planted is pure decoration: a
        satisfying puff and nothing else, so the world has more to smash without inflating
        the loot economy. Either way the prop is gone for good, no debris left behind."""
        self.breakables.remove(breakable)

        if breakable.kind == "powder":
            self.explode(breakable.x, breakable.y, player, quest_system)
            return

        if not breakable.loot:
            get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
            play_sound("bush_rustle")
            get_particles().spawn_burst(
                breakable.x, breakable.y, (80, 150, 65), count=14, speed=4, life=450, size=4, gravity=0.3
            )
            return

        self._break_effects(breakable.x, breakable.y, (150, 110, 70), 18)
        coins, loot_item = break_crate()
        self._break_loot(player, breakable.x, breakable.y, coins, loot_item, "Barrel smashed", self.items.append)

    def explode(
        self,
        x,
        y,
        player: Player,
        quest_system: QuestSystem,
        depth: int = 0,
        *,
        radius: float = c.Explosion.RADIUS,
        damage: int = c.Explosion.DAMAGE,
        edge_frac: float = c.Explosion.EDGE_DAMAGE_FRAC,
        knockback: float = c.Explosion.KNOCKBACK,
        shake: float = c.Explosion.SHAKE,
        player_mult: float = c.Explosion.PLAYER_DAMAGE_MULT,
        by_player: bool = True,
        message: str = "The powder keg goes off!",
    ):
        """A powder keg going off: the one thing in the world that kills a crowd without a
        swing.

        Everything alive inside `radius` takes damage falling off toward the rim, the player
        included, and any keg caught in it goes off in turn. That is the whole design: a keg
        is not loot, it is a piece of ground the player can decide to fight over, and shooting
        one from across a clearing is a plan rather than a lucky swing. Kills count as the
        player's, since setting it off is what killed them.

        The keyword arguments are the same blast pointed at something else: a creeper's fuse
        burning out (`detonate_creeper`) is this call with its own numbers and `by_player`
        off, since the player did not light it. Nothing here knows which it is.

        `depth` caps a chain so a shipment of kegs cannot recurse without end.
        """
        get_shake().add(shake)
        play_sound("crate_break")
        get_particles().spawn_burst(x, y, (255, 170, 60), count=40, speed=11, life=650, size=7, gravity=0.2)
        get_particles().spawn_burst(x, y, (90, 80, 75), count=22, speed=6, life=900, size=8, gravity=0.05)
        get_impacts().pulse(x, y, radius, (255, 170, 60))
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        if self.notify and depth == 0 and message:
            self.notify(message, (255, 170, 60))

        def blast_damage(distance: float) -> int:
            frac = max(0.0, 1.0 - distance / radius)
            scale = edge_frac + (1.0 - edge_frac) * frac
            return max(1, round(damage * scale))

        def caught(entities, radius_of):
            return [
                (e, math.hypot(e.x - x, e.y - y))
                for e in list(entities)
                if math.hypot(e.x - x, e.y - y) < radius + radius_of(e)
            ]

        for group in (self.bosses, self.monsters):
            for monster, distance in caught(group, lambda m: m.kind.size / 2):
                self._resolve_monster_hit(
                    monster,
                    group,
                    blast_damage(distance),
                    player,
                    quest_system,
                    knockback=knockback,
                    kb_dir=self._dir_from(x, y, monster.x, monster.y),
                    blocked=self.blocked,
                    by_player=by_player,
                )

        for critter, distance in caught(self.critters, lambda cr: cr.hit_radius):
            hurt = blast_damage(distance)
            kb_dir = self._dir_from(x, y, critter.x, critter.y)
            self._pop_damage(critter.x, critter.y - critter.size / 2, hurt, False)
            if critter.receive_damage(hurt):
                self._kill_critter(critter, player, kb_dir, by_player=by_player)
            else:
                self._knockback(critter, critter.size / 2, kb_dir, knockback, self.blocked)
                critter.startle()
                if by_player:
                    self.aggro_pack(critter)

        for npc, distance in caught(self.npcs, lambda n: c.Entities.NPC_SIZE / 2):
            self._resolve_npc_hit(
                npc,
                blast_damage(distance),
                player,
                quest_system,
                knockback=knockback,
                kb_dir=self._dir_from(x, y, npc.x, npc.y),
                blocked=self.blocked,
                by_player=by_player,
            )

        player_distance = math.hypot(player.x - x, player.y - y)
        if player_distance < radius:
            player.receive_damage(
                round(blast_damage(player_distance) * player_mult), source=self._blast_source(by_player)
            )

        if depth >= 3:
            return
        for keg in [
            b
            for b in list(self.breakables)
            if b.kind == "powder" and math.hypot(b.x - x, b.y - y) < c.Explosion.CHAIN_RADIUS
        ]:
            if keg in self.breakables:
                self.breakables.remove(keg)
                # A keg is still a keg whatever lit it, but the credit follows the hand that
                # started the chain: nothing a creeper set off pays the player.
                self.explode(keg.x, keg.y, player, quest_system, depth + 1, by_player=by_player)

    @staticmethod
    def _blast_source(by_player: bool) -> str:
        """What the death screen names when a blast is what killed the player. The keg is the
        player's own doing; the creeper is somebody else's."""
        return "a powder keg" if by_player else "a creeper"

    def detonate_creeper(self, monster: Monster, player: Player, quest_system: QuestSystem):
        """A creeper's fuse burning out: it comes off the map and the blast goes off where it
        stood.

        It is taken out of the list first, so it is not caught in its own explosion and its
        death is never credited to anyone. Nothing the blast kills pays the player either
        (`by_player=False`, the bear trap's rule): the reward for a creeper is killing it
        before the fuse runs out, not standing next to one when it does.
        """
        if monster in self.monsters:
            self.monsters.remove(monster)
        self._spill_blood(monster.x, monster.y, monster.kind.color)
        self.explode(
            monster.x,
            monster.y,
            player,
            quest_system,
            radius=c.Creeper.RADIUS,
            damage=c.Creeper.DAMAGE,
            edge_frac=c.Creeper.EDGE_DAMAGE_FRAC,
            knockback=c.Creeper.KNOCKBACK,
            shake=c.Creeper.SHAKE,
            player_mult=1.0,
            by_player=False,
            message="The creeper bursts!",
        )

    def snap_traps(self, player: Player, quest_system: QuestSystem):
        """Whatever has just put a foot in a set bear trap, and what it costs them.

        A trap is not aimed at anyone: the first thing to stand on it springs it, whether
        that is the player, a wolf, a villager or the monster chasing all three. Nothing it
        catches pays the player anything (`by_player=False`), since the player did not set
        it; what they get out of one is the seconds it holds something still.
        """
        for trap in self.traps:
            if trap.sprung:
                continue
            if trap.catches(player.x, player.y, c.Player.SIZE / 2):
                self._spring_trap(trap, player, player, quest_system)
                continue
            monster = next((m for m in self.monsters if trap.catches(m.x, m.y, m.kind.size / 2)), None)
            if monster is not None:
                self._spring_trap(trap, monster, player, quest_system)
                continue
            critter = next((cr for cr in self.critters if trap.catches(cr.x, cr.y, cr.hit_radius)), None)
            if critter is not None:
                self._spring_trap(trap, critter, player, quest_system)
                continue
            npc = next((n for n in self.npcs if trap.catches(n.x, n.y, c.Entities.NPC_SIZE / 2)), None)
            if npc is not None:
                self._spring_trap(trap, npc, player, quest_system)

    def _spring_trap(self, trap, victim, player: Player, quest_system: QuestSystem):
        """Shut the jaws on whoever stood in them: a bite of health off, and held where they
        are for as long as it takes to work a foot free. Bosses are deliberately not checked
        by the caller, for the same reason nothing knocks them back."""
        trap.sprung = True
        play_sound("hit")
        get_shake().add(c.Combat.CRATE_SHAKE)
        get_particles().spawn_burst(trap.x, trap.y, c.Traps.JAW_COLOR, count=14, speed=5, life=450, size=4)
        damage = c.Traps.DAMAGE
        victim.root(c.Traps.HOLD_MS)

        if victim is player:
            player.receive_damage(damage, source=trap)
            if self.notify:
                self.notify("A bear trap snaps shut on your leg", c.Colors.RED)
            return
        if isinstance(victim, Critter):
            self._pop_damage(victim.x, victim.y - victim.size / 2, damage, False)
            if victim.receive_damage(damage):
                self._kill_critter(victim, player, by_player=False)
            else:
                victim.startle()
            return
        if isinstance(victim, NPC):
            self._resolve_npc_hit(victim, damage, player, quest_system, blocked=self.blocked, by_player=False)
            return
        self._resolve_monster_hit(victim, self.monsters, damage, player, quest_system, by_player=False)

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
        by_player: bool = True,
    ) -> bool:
        """Applies damage to a monster and its kill rewards. Returns True if it died."""
        get_shake().add(shake)
        self._pop_damage(monster.x, monster.y - monster.kind.size / 2, damage, crit)
        if monster.receive_damage(damage):
            self._kill_monster(monster, monster_list, player, quest_system, direction=kb_dir, by_player=by_player)
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

    def _kill_monster(
        self, monster, monster_list, player: Player, quest_system: QuestSystem, direction=None, by_player: bool = True
    ):
        """Death rewards and cleanup for a slain monster, shared by hits and burn ticks.

        `by_player` False is a monster killed by another monster's stray arrow: it dies and
        bleeds like any other, but the xp, the lootbox and the quest counter all stay with
        the player's own kills, so standing behind an archer is not a way to farm. The one
        thing that still counts is a camp guard falling, since a garrison is world state:
        whoever shot it, it is not standing up again."""
        if by_player:
            player.stats.train("vitality", c.Stats.XP_PER_KILL)
            # Bloodlust: any kill with a weapon carrying it refreshes the damage buff.
            bloodlust = player.bloodlust_mult()
            if bloodlust > 1.0:
                player.apply_buff("bloodlust", bloodlust, c.Affixes.BLOODLUST_DURATION_S)
        play_sound("monster_death")
        if isinstance(monster, Boss):
            self._on_boss_killed(monster, quest_system, direction)
            monster_list.remove(monster)
            return
        if by_player:
            get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        self._spill_blood(monster.x, monster.y, monster.kind.color, direction)
        if by_player:
            quest_item = quest_system.on_monster_killed(monster.kind.name, monster.x, monster.y)
            if quest_item is not None:
                self.items.append(quest_item)
            drop_chance = c.LootBox.DROP_CHANCE
            drop_chance *= 1.0 + (c.Events.BLOOD_NIGHT_DROP_MULT - 1.0) * self.events.blood_intensity
            if random.random() < drop_chance:
                rarity = roll_rarity(luck=player.loot_luck())
                self.items.append(Item(monster.x, monster.y, "Lootbox", "lootbox", rarity=rarity))
        # A camp guard's death is the camp's business: it is what opens the cache, and the
        # only thing that lowers the garrison it stands back up from on the next chunk load.
        if monster.camp_id:
            self.on_guard_killed(monster, quest_system)
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
        """Chain Strike: a landed hit sends a pulse out from whatever was struck, and
        everything else within `Affixes.CHAINSTRIKE_RADIUS` takes a share of the blow.

        An area effect rather than one jump to the nearest body: the legendary is the
        reason to wade into a crowd rather than a slightly better single target. It draws
        the ring it damaged over (`core.impact_fx`) and a bolt to each thing it caught, so
        several damage numbers popping at once have something visible behind them."""
        frac = player.chainstrike_frac(ranged)
        if frac <= 0:
            return
        caught = [
            target
            for target in target_list
            if target is not primary and target.distance_to_point((primary.x, primary.y)) < c.Affixes.CHAINSTRIKE_RADIUS
        ]
        get_impacts().pulse(
            primary.x,
            primary.y,
            c.Affixes.CHAINSTRIKE_RADIUS,
            c.ImpactFx.CHAINSTRIKE_COLOR,
            [(target.x, target.y) for target in caught],
        )
        chain_damage = max(1, int(damage * frac))
        for target in caught:
            get_particles().spawn_burst(target.x, target.y, (140, 200, 255), count=8, speed=4, life=300, size=3)
            kb_dir = self._dir_from(primary.x, primary.y, target.x, target.y)
            died = self._resolve_monster_hit(
                target,
                target_list,
                chain_damage,
                player,
                quest_system,
                shake=0.0,
                knockback=0.0,
                kb_dir=kb_dir,
                blocked=blocked,
            )
            self._apply_on_hit_effects(target, target_list, chain_damage, player, quest_system, died, ranged=ranged)

    def _apply_element(self, proj, target, target_list, player, quest_system, died: bool):
        """What an elemental staff's bolt does where it landed (`c.Staffs`).

        Each element is an existing mechanic pointed at by the weapon rather than by an
        affix roll: fire lights the burn ticker, frost slows whatever it touched, storm
        jumps to the nearest other body. Nothing happens on a shot that was not the
        player's, and nothing happens to something the hit already killed."""
        if not proj.element or died:
            return
        if proj.element == "fire" and hasattr(target, "apply_burn"):
            target.apply_burn(c.Staffs.BURN_DAMAGE)
            get_particles().spawn_burst(target.x, target.y, (255, 150, 60), count=8, speed=4, life=320, size=3)
            return
        if proj.element == "frost":
            target.chill(c.Staffs.CHILL_MS, c.Staffs.CHILL_MULT)
            get_particles().spawn_burst(target.x, target.y, (150, 220, 255), count=8, speed=3, life=380, size=3)
            return
        if proj.element == "storm" and target_list is not None:
            self._chain_bolt(target, target_list, proj.damage, player, quest_system)

    def _chain_bolt(self, primary, target_list, damage, player, quest_system):
        """A storm staff's bolt jumping to the nearest other body: the Chain Strike idea at
        a weapon's strength, one target and no pulse."""
        nearest = min(
            (
                target
                for target in target_list
                if target is not primary and target.distance_to_point((primary.x, primary.y)) < c.Staffs.CHAIN_RADIUS
            ),
            key=lambda target: target.distance_to_point((primary.x, primary.y)),
            default=None,
        )
        if nearest is None:
            return
        get_impacts().pulse(primary.x, primary.y, 0.0, c.STAFF_BOLT_COLORS["storm"], [(nearest.x, nearest.y)])
        self._resolve_monster_hit(
            nearest,
            target_list,
            max(1, int(damage * c.Staffs.CHAIN_FRAC)),
            player,
            quest_system,
            shake=0.0,
            knockback=0.0,
            kb_dir=self._dir_from(primary.x, primary.y, nearest.x, nearest.y),
            blocked=self.blocked,
        )

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
        player: Player,
        quest_system: QuestSystem,
        crit: bool = False,
        shake: float = 0.0,
        knockback: float = 0.0,
        kb_dir=None,
        blocked=None,
        by_player: bool = True,
    ) -> bool:
        """Applies damage to an NPC and handles death. Returns True if it died.

        Striking anyone is what turns their village on the player, so it happens here:
        every path that lands a blow on an NPC (swing, arrow, cleave, blast) goes through
        this. `by_player` False is the one exception, and it covers everything the player
        did not do: a monster's arrow catching a villager, or a monster cutting one down in
        the street. The village has nothing to blame the player for, so it is not provoked
        and the purse is not theirs to take.

        A blow turns the settlement for a while; a death turns it for good (`hold_grudge`),
        which is the one thing no clock ever runs out on."""
        if by_player:
            for provoked in self.provoke_village(npc):
                # Nobody hands in a task to someone they are trying to kill; drop it rather
                # than leave an uncompletable quest in the log.
                quest_system.remove_quest(provoked)
        get_shake().add(shake)
        self._pop_damage(npc.x, npc.y - c.Entities.NPC_SIZE / 2, damage, crit)
        if npc.receive_damage(damage):
            if by_player:
                for provoked in self.hold_grudge(npc):
                    quest_system.remove_quest(provoked)
            stolen_item = quest_system.on_npc_killed(npc)
            if stolen_item is not None:
                self.items.append(stolen_item)
            # Drop any quest this NPC was offering so it can't become uncompletable
            quest_system.remove_quest(npc)
            play_sound("monster_death")
            if by_player:
                get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
            self._spill_blood(npc.x, npc.y, npc.color, kb_dir)
            self._drop_villager_loot(npc, player, by_player)
            self.npcs.remove(npc)
            return True
        self._hit_feedback(npc.x, npc.y, crit, kb_dir)
        self._knockback(npc, c.Entities.NPC_SIZE / 2, kb_dir, knockback, blocked)
        return False

    def _drop_villager_loot(self, npc: NPC, player: Player, by_player: bool):
        """What a killed villager leaves behind: the purse they were carrying, and
        sometimes a piece of what they owned.

        Killing a townsperson used to cost the player their village and pay nothing, which
        made it a pure mistake rather than a choice. A merchant carries more than a
        labourer, since a merchant's whole day is coins. Neither the purse nor the
        possession is credited to anyone: both drop on the ground where the body fell, for
        whoever walks over them, which is why an uncredited kill still leaves them there.
        """
        coins, loot_item = loot_villager(bool(npc.shop_items), player.loot_luck() if by_player else 0.0)
        dropped = []
        if coins > 0:
            purse = Item(npc.x, npc.y, "Purse", "coins", rarity="common", quantity=coins)
            purse.start_pop_anim(npc.x, npc.y - c.Entities.NPC_SIZE)
            self.items.append(purse)
            dropped.append(purse)
        if loot_item is not None:
            loot_item.x, loot_item.y = npc.x, npc.y
            loot_item.start_pop_anim(npc.x, npc.y - c.Entities.NPC_SIZE)
            self.items.append(loot_item)
            dropped.append(loot_item)
        if not by_player or not dropped or self.notify is None:
            return
        if loot_item is not None:
            self.notify(
                f"{npc.name or 'The body'} drops a purse and a {loot_item.rarity} {loot_item.name}",
                rarity_color(loot_item.rarity),
            )
        else:
            self.notify(f"{npc.name or 'The body'} drops a purse", c.Colors.WHITE)

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

    def fire_monster_shots(self, player: Player, damage_mult: float = 1.0):
        """Let every ranged monster in range loose an arrow at the player.

        Kept here rather than on `Monster` because the shot is the world's, not the
        monster's: it goes in the same `projectiles` list the player's arrows do, and
        it is stopped by the same walls. A shot is aimed where the player stands now,
        so sidestepping it is a real answer.

        Nothing shoots through a wall: the arrow was always stopped by one, but the archer
        used to keep loosing into it at a player it had no way of seeing, so breaking line
        of sight is now a real answer too. Nothing shoots point blank either: an archer with
        the player on top of it is cornered (Monster.cornered) and has to use its knife."""
        now = pygame.time.get_ticks()
        for monster in self.monsters:
            if not monster.kind.ranged or now < monster.next_shot_ms:
                continue
            dx, dy = player.x - monster.x, player.y - monster.y
            distance = math.hypot(dx, dy)
            if distance > monster.kind.attack_range or monster.cornered(distance):
                continue
            if not self.line_of_sight(monster.x, monster.y, player.x, player.y):
                continue
            monster.next_shot_ms = now + monster.kind.shot_cooldown_ms
            # Monster.start_attack_anim takes a distance and resolves a melee hit from it;
            # a shot wants the animation only, so it goes to the plain Entity one.
            Entity.start_attack_anim(monster)
            play_sound("shoot")
            style, color = ("bolt", BOLT_COLOR) if monster.kind.name == "Hexer" else ("arrow", ARROW_COLOR)
            self.projectiles.append(
                Projectile(
                    monster.x,
                    monster.y,
                    # Projectile angles are measured from straight up, clockwise.
                    math.atan2(dx, -dy),
                    round(monster.kind.damage * damage_mult),
                    style=style,
                    color=color,
                    shake=c.Combat.PLAYER_HURT_SHAKE,
                    hostile=True,
                    owner_id=id(monster),
                    source_name=monster.kind.name,
                    max_range=c.Projectile.MONSTER_RANGE,
                )
            )

    def update_projectiles(self, player: Player, quest_system: QuestSystem, dt):
        for proj in list(self.projectiles):
            proj.update(dt, self.blocked)
            if proj.dead:
                self.projectiles.remove(proj)
                continue

            # A hostile shot is aimed at the player, but it is an arrow, not a guided one:
            # anything standing in the way takes it instead. What that hits is nobody's
            # doing, so it is uncredited (`by_player=False`): no xp, no loot, no quest
            # progress, and a villager felled by a goblin's stray arrow does not turn the
            # village on the player who was only walking past.
            if proj.hostile:
                if proj.distance_to_point((player.x, player.y)) < c.Projectile.SIZE + c.Player.SIZE / 2:
                    # Passed as the source so a raised shield can catch it: an arrow is
                    # blocked by where it came from, like any other blow.
                    player.receive_damage(proj.damage, source=proj)
                    get_shake().add(proj.shake)
                    self.projectiles.remove(proj)
                    continue

            by_player = not proj.hostile
            if self._projectile_hits_monster(proj, self.monsters, player, quest_system, by_player):
                continue
            if self._projectile_hits_monster(proj, self.bosses, player, quest_system, by_player):
                continue
            if self._projectile_hits_critter(proj, player, by_player):
                continue
            if self._projectile_hits_npc(proj, player, quest_system, by_player):
                continue
            self._projectile_hits_keg(proj, player, quest_system)

    @staticmethod
    def _projectile_target(proj: Projectile, entities, radius_of):
        """The first thing in `entities` this projectile is touching and has not already
        struck, or None. `radius_of` is how wide that kind of target is: a monster goes by
        its sprite size, an animal by its own hit radius."""
        return next(
            (
                entity
                for entity in entities
                if id(entity) not in proj.hit_ids
                and proj.distance_to_point((entity.x, entity.y)) < c.Projectile.SIZE + radius_of(entity)
            ),
            None,
        )

    def _projectile_hits_monster(
        self, proj: Projectile, targets, player: Player, quest_system: QuestSystem, by_player: bool = True
    ) -> bool:
        """Resolve a projectile against one list of monsters or bosses (both take hits the
        same way). Returns True if it struck something, pierced onward or not.

        `by_player` is False for a monster's own arrow catching another monster: it still
        dies, but none of the player's affixes fire on a shot they did not loose and none
        of the reward is theirs."""
        target = self._projectile_target(proj, targets, lambda t: t.kind.size // 2)
        if target is None:
            return False

        if by_player:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        died = self._resolve_monster_hit(
            target,
            targets,
            proj.damage,
            player,
            quest_system,
            shake=proj.shake if by_player else 0.0,
            knockback=proj.knockback,
            kb_dir=kb_dir,
            blocked=self.blocked,
            by_player=by_player,
        )
        if by_player:
            self._apply_on_hit_effects(target, targets, proj.damage, player, quest_system, died, ranged=True)
            self._apply_element(proj, target, targets, player, quest_system, died)
            self._apply_chainstrike(target, targets, proj.damage, player, quest_system, self.blocked, ranged=True)
        self._projectile_after_hit(proj, target)
        return True

    def _projectile_hits_critter(self, proj: Projectile, player: Player, by_player: bool = True) -> bool:
        """Resolve a projectile against wildlife: an arrow is how most animals get hunted,
        since they run long before a swing lands. Returns True if it struck one.

        A shot that was not the player's still wounds the animal, but the pack it belongs
        to has no reason to blame the player for it, so `aggro_pack` is skipped."""
        critter = self._projectile_target(proj, self.critters, lambda cr: cr.hit_radius)
        if critter is None:
            return False

        if by_player:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
            get_shake().add(proj.shake)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        self._pop_damage(critter.x, critter.y - critter.size / 2, proj.damage, False)
        if critter.receive_damage(proj.damage):
            self._kill_critter(critter, player, kb_dir, by_player=by_player)
        else:
            if by_player:
                self._apply_element(proj, critter, None, player, None, died=False)
            self._hit_feedback(critter.x, critter.y, False, kb_dir)
            self._knockback(critter, critter.size / 2, kb_dir, proj.knockback, self.blocked)
            critter.startle()
            if by_player:
                self.aggro_pack(critter)
        self._projectile_after_hit(proj, critter)
        return True

    def _projectile_hits_npc(
        self, proj: Projectile, player: Player, quest_system: QuestSystem, by_player: bool = True
    ) -> bool:
        npc = self._projectile_target(proj, self.npcs, lambda n: c.Entities.NPC_SIZE // 2)
        if npc is None:
            return False

        if by_player:
            player.stats.train("strength", c.Stats.XP_PER_HIT)
        self._resolve_npc_hit(
            npc,
            proj.damage,
            player,
            quest_system,
            shake=proj.shake if by_player else 0.0,
            knockback=proj.knockback,
            kb_dir=self._dir_from(0, 0, proj.vx, proj.vy),
            blocked=self.blocked,
            by_player=by_player,
        )
        frac = player.lifesteal_frac(ranged=True) if by_player else 0.0
        if frac > 0:
            player.heal(proj.damage * frac)
        if by_player and npc.hp > 0:
            self._apply_element(proj, npc, None, player, quest_system, died=False)
        self._projectile_after_hit(proj, npc)
        return True

    def _projectile_hits_keg(self, proj: Projectile, player: Player, quest_system: QuestSystem) -> bool:
        """A shot that reaches a powder keg sets it off. Kegs are the only prop an arrow
        interacts with, deliberately: shooting one from across a clearing is a way to kill
        a crowd, where shooting a flower bed would just be loot at no risk."""
        keg = next(
            (
                b
                for b in self.breakables
                if b.kind == "powder" and b.distance_to_point((proj.x, proj.y)) < c.Breakables.POWDER_HIT_RADIUS
            ),
            None,
        )
        if keg is None:
            return False
        self.projectiles.remove(proj)
        self._break_breakable(player, keg, quest_system)
        return True

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
        """Record the target and either pierce onward (arrow-pierce) or stop the projectile.

        A boomerang that has gone through everything it can carry turns for home instead of
        stopping: it is thrown rather than fired, and it always comes back."""
        proj.hit_ids.add(id(target))
        if proj.pierce > 0:
            proj.pierce -= 1
        elif not proj.turn_back():
            self.projectiles.remove(proj)
