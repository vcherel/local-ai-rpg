from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.damage_fx import get_damage_fx
from core.decals import get_decals, style_for_weapon
from core.floating_text import get_floating_text
from core.impact_fx import get_impacts
from core.particles import get_particles
from core.screen_fx import get_hitstop, get_trap_fx
from core.swing_arcs import get_swings
from game.blow import PLAIN_BLOW, Blow
from game.entities.boss import Boss
from game.entities.breakables import Breakable
from game.entities.buildings import Building
from game.entities.critter import Critter
from game.entities.entities import apply_impulse
from game.entities.items import Item, rarity_color, roll_rarity
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest
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

    # The weapon family whose wound is being drawn right now, one of `core.decals`'
    # splat styles. Set for the length of one blow by whatever started it (a swing, a
    # shot) and read by the gore, so a spear leaves a spear's mess without every damage
    # path having to carry an archetype down to the decal. Anything nobody set it for (a
    # burn tick, a monster's bite, a fall) bleeds generically.
    blow_style = "generic"

    def handle_attack(self, player: Player, quest_system: QuestSystem, hand: int = 0):
        """The weapon's archetype (constants.weapon_archetype) drives reach, damage, cadence,
        crit, knockback and cleave, so different weapon families feel different to swing.
        Building interiors are just world space now, so this has no indoor/outdoor split:
        monsters, NPCs, crates and windows are all found the same way whether the player is
        standing in a house or out in the open.

        `hand` is which of the player's two hands acted: 0 is the left mouse button, 1 the
        right. What that click does is decided by whatever is in that hand rather than by
        the button, so a bow in hand one fires and a sword in hand two swings. An empty hand
        is bare hands, which still swings.
        """
        weapon = player.hand_weapon(hand)
        arch = c.weapon_archetype(weapon.name if weapon else None)
        self.blow_style = style_for_weapon(arch)

        if arch.ranged:
            player.end_spawn_grace()
            self._fire_ranged(player, arch, hand)
            return

        now = pygame.time.get_ticks()
        if not player.hand_ready(hand, now):  # this hand is still on its own cooldown
            return
        player.spend_hand(hand, now, arch.cooldown_ms, arch.swing_mult)
        # Swinging spends whatever is left of the spawn grace: it is there to get the player
        # out of what killed them, not to let them open a fight untouchable.
        player.end_spawn_grace()

        # Hand one is the right arm on the sprite and hand two the left, so the arm that
        # comes round is the one actually holding the weapon.
        player.start_attack_anim("right" if hand == 0 else "left", c.Player.SWING_MS)
        play_sound("attack")

        reach = c.Player.ATTACK_REACH * arch.reach_mult
        pos = player.get_pos(reach)
        origin = player.get_pos()
        base_damage = (
            c.Player.ATTACK_DAMAGE + player.weapon_bonus(hand) + player.stats.attack_bonus()
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
            # And the player goes with it: a short shove down their own facing, spent through
            # the same collision a step is, so a thrust into a wall stays where the wall is.
            # A lunge is what the blind spot is paid for, and standing perfectly still while
            # driving a spear out is the one part of it that never read.
            apply_impulse(player, (math.sin(player.orientation), -math.cos(player.orientation)), c.Combat.THRUST_LUNGE)
        else:
            get_swings().spawn(origin[0], origin[1], player.orientation, reach, arch.arc_deg, arch.cleave)

        if self._swing_at_bodies(player, quest_system, arch, origin, pos, hit_radius, base_damage, hand):
            return
        self._swing_at_scenery(player, quest_system, arch, pos, hit_radius, base_damage)

    def _swing_at_bodies(self, player, quest_system, arch, origin, pos, hit_radius, base_damage, hand=0) -> bool:
        """Land the swing on whatever living thing it covers. Returns whether it hit anything,
        which is what decides between a fight and a swing into the furniture."""
        blocked = self.blocked
        # A thrust's share per target: the first body on the shaft takes it all and every
        # one behind it a little less, filled in as each group is found.
        lane_share: dict = {}

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

        def strike_monster(monster, roster):
            self._strike_monster(monster, roster, falloff(monster), arch, player, quest_system, blocked, hand)

        def strike_critter(critter, _roster):
            self._strike_critter(critter, falloff(critter), arch, player)

        def strike_npc(npc, _roster):
            self._strike_npc(npc, falloff(npc), arch, player, quest_system, blocked, hand)

        # Target priority: bosses and monsters, then whatever is already fighting back (an
        # animal biting, a villager swinging), then the peaceful. A rabbit standing behind
        # a wolf must never soak the blow meant for the wolf, and hunting one in a crowded
        # street must not land on a bystander and start a brawl. The swing goes to the
        # first group with anything in reach.
        #
        # A cleaving weapon then carries on through the groups still marked hostile: a sweep
        # that catches a goblin and the villager swinging beside it hits both, since a wide
        # blade does not stop at a species. It never reaches the peaceful groups, so hunting
        # a rabbit in a crowded street still cannot start a brawl. That flag is the whole of
        # what a cleave carries into, so reordering the table can never quietly widen it.
        #
        # `roster` is the list a death takes the body off, which is not always the list it
        # was found in: the hostile rows are filtered copies, and removing a corpse from one
        # of those would leave it standing in the world.
        groups = (
            (self.bosses, self.bosses, lambda e: e.kind.size, strike_monster, True),
            (self.monsters, self.monsters, lambda e: e.kind.size, strike_monster, True),
            ([cr for cr in self.critters if cr.hostile], None, lambda e: e.hit_radius * 2, strike_critter, True),
            ([npc for npc in self.npcs if npc.hostile], None, lambda _e: c.Entities.NPC_SIZE, strike_npc, True),
            (self.critters, None, lambda e: e.hit_radius * 2, strike_critter, False),
            (self.npcs, None, lambda _e: c.Entities.NPC_SIZE, strike_npc, False),
        )
        carries_on = arch.cleave or arch.pierce_melee
        engaged = False
        for group, roster, size_of, strike, hostile in groups:
            if engaged and not (carries_on and hostile):
                break
            targets = self._targets_in_reach(
                group,
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
            if not targets:
                continue
            if arch.pierce_melee:
                lane_share.update(self._thrust_shares(origin, targets))
            if not engaged:
                player.stats.train("strength", c.Stats.XP_PER_HIT)
            engaged = True
            for target in targets:
                strike(target, roster)
        return engaged

    def _swing_at_scenery(self, player, quest_system, arch, pos, hit_radius, base_damage):
        """Nothing living in range: the swing goes into the scenery. Props take the weapon's
        damage rather than breaking on contact, so a heavy hammer clears a barrel in one blow
        and a dagger has to work at it."""
        prop_damage = max(1, round(base_damage * arch.damage_mult))
        blow = player.orientation

        for building in self.buildings_in_range(*pos, c.World.CHUNK_SIZE):
            # Only the floor the swing actually lands on: furniture is reached by standing
            # in the room with it, never through the wall. A bed against the front wall used
            # to take the blow aimed at the window beside it, swung from the street.
            if not any(floor.collidepoint(*pos) for floor in building.interior_rects()):
                continue
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

        gate_hit = self._gate_in_reach(pos, hit_radius)
        if gate_hit is not None:
            self._hit_gate(*gate_hit, prop_damage, blow)
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

        prop_poi = next(
            (
                p
                for p in self.pois
                if p.wreckable and p.distance_to_point(pos) < hit_radius + c.PointsOfInterest.HIT_RADIUS
            ),
            None,
        )
        if prop_poi is not None:
            self._wreck_poi(prop_poi, prop_damage, blow)
            return

        breakable = next(
            (b for b in self.breakables if b.distance_to_point(pos) < hit_radius + c.Breakables.HIT_RADIUS), None
        )
        if breakable is not None:
            self._hit_breakable(player, breakable, prop_damage, quest_system, blow)
            return

        wild = self._wilderness_in_reach(pos, hit_radius)
        if wild is not None:
            if wild.choppable:
                self._chop_tree(player, wild, arch, prop_damage, blow)
            else:
                self._smash_boulder(player, wild, arch, prop_damage, blow)
            return

        window_hit = self._find_window_in_reach(pos, hit_radius)
        if window_hit is not None:
            building, idx, window = window_hit
            self._hit_window(player, building, idx, window, prop_damage, blow)

    def _wilderness_in_reach(self, pos, hit_radius: float):
        """The tree or the boulder a swing at `pos` lands on, or None. The two things in the
        wilderness that answer a weapon, found the same way and each by its own reach."""
        for item in self.scenery_near(*pos):
            if item.choppable:
                reach = c.Trees.HIT_RADIUS
            elif item.smashable:
                reach = c.Boulders.HIT_RADIUS
            else:
                continue
            if math.hypot(item.x - pos[0], item.y - pos[1]) < hit_radius + reach:
                return item
        return None

    def _chop_tree(self, player: Player, tree, arch, prop_damage: int, blow: float):
        """One swing into a trunk. An axe is what a tree is felled with and does the work
        several times over; anything else is somebody hitting a tree with the wrong thing,
        which is slow but not impossible.

        A felled tree leaves a stump and a couple of logs on the ground, and the world
        remembers it was cut (`World.felled`) so it is still down when the chunk streams
        back in."""
        mult = c.Trees.AXE_MULT if arch.name == "axe" else c.Trees.OTHER_MULT
        tree.hp -= max(1, round(prop_damage * mult))
        self._prop_chip(tree.x, tree.y, c.Trees.STUMP_COLOR, "crate_break", tree.key, blow)
        if tree.hp > 0:
            return

        # Through the world rather than on the tree itself: what a piece of wilderness
        # blocks is what files it, so a trunk becoming a stump has to be filed again or the
        # player goes on walking round a tree lying on the ground.
        self.rework_scenery(tree, tree.fell)
        if tree.key:
            self.felled.add(tree.key)
        play_sound("gate_break")
        get_shake().add(c.Trees.FALL_SHAKE)
        get_particles().spawn_burst(tree.x, tree.y, (110, 150, 70), count=26, speed=6, life=700, size=5, gravity=0.3)
        player.stats.train("strength", c.Trees.XP_PER_FELL)
        for _ in range(random.randint(*c.Trees.LOG_DROPS)):
            log = Item(tree.x + random.uniform(-16, 16), tree.y + random.uniform(-16, 16), "Log", "misc")
            log.rarity = "common"
            log.start_pop_anim(tree.x, tree.y)
            self.items.append(log)

    def _smash_boulder(self, player: Player, boulder, arch, prop_damage: int, blow: float):
        """One swing into a rock. A hammer is what breaks stone and does the work several
        times over; an edge chips at it, which is slow but not impossible.

        A broken boulder leaves rubble and a few stones on the ground, and the world
        remembers it was broken (`World.smashed`) so it is still open when the chunk streams
        back in, exactly as a felled tree is."""
        mult = c.Boulders.HAMMER_MULT if arch.name == "hammer" else c.Boulders.OTHER_MULT
        boulder.hp -= max(1, round(prop_damage * mult))
        self._prop_chip(boulder.x, boulder.y, c.Boulders.RUBBLE_COLOR, "hit", boulder.key, blow)
        if boulder.hp > 0:
            return

        self.rework_scenery(boulder, boulder.smash)
        if boulder.key:
            self.smashed.add(boulder.key)
        play_sound("crate_break")
        get_shake().add(c.Boulders.SHAKE)
        get_particles().spawn_burst(
            boulder.x,
            boulder.y,
            c.Boulders.RUBBLE_COLOR,
            count=24,
            speed=7,
            life=600,
            size=5,
            gravity=0.5,
            shape="shard",
        )
        player.stats.train("strength", c.Boulders.XP_PER_SMASH)
        for _ in range(random.randint(*c.Boulders.STONE_DROPS)):
            stone = Item(boulder.x + random.uniform(-16, 16), boulder.y + random.uniform(-16, 16), "Stone", "misc")
            stone.rarity = "common"
            stone.start_pop_anim(boulder.x, boulder.y)
            self.items.append(stone)

    def _wreck_poi(self, poi: PointOfInterest, prop_damage: int, blow: float):
        """One swing into a landmark that is a prop rather than a place: a signpost. It
        comes down like a barrel, pays nothing, and stays down (`PointOfInterest.wrecked`),
        which costs the player whatever was written on it."""
        poi.prop_hp -= prop_damage
        if poi.prop_hp > 0:
            self._prop_chip(poi.x, poi.y, (150, 120, 80), "crate_break", f"poi:{poi.id}", blow)
            return
        poi.wrecked = True
        get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(
            poi.x, poi.y, (150, 120, 80), count=18, speed=6, life=520, size=4, gravity=0.5, shape="shard"
        )
        if self.notify:
            self.notify("The signpost comes down", c.Colors.MUTED)

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
        (building, index, rect), or None.

        Measured to the pane rather than to the middle of it. A window is three times as
        wide as it is deep and sits a wall's depth back from the face the player is stood
        against, so a reach taken from its centre covered a circle narrower than the pane
        itself: standing plainly in front of one and swinging at it missed unless the player
        happened to be lined up with the middle. What the reach is for is how far short of
        the glass a blow may land, which is what a distance to the rectangle answers."""
        px, py = pos
        best = None
        for building in self.buildings_in_range(px, py, c.World.CHUNK_SIZE):
            for idx, window in enumerate(building.window_rects()):
                if idx in building.broken_windows:
                    continue
                near_x = min(max(px, window.left), window.right)
                near_y = min(max(py, window.top), window.bottom)
                dist = math.hypot(px - near_x, py - near_y)
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

    def _hit_window(self, player: Player, building: Building, idx: int, window, damage: int, angle: float = 0.0):
        """Crack a window, and shatter it once it has taken enough."""
        remaining = building.window_hp.get(idx, c.Buildings.WINDOW_HP) - damage
        if remaining > 0:
            building.window_hp[idx] = remaining
            self._prop_chip(
                window.centerx, window.centery, (210, 230, 240), "glass_break", f"{building.id}:window:{idx}", angle
            )
            return
        building.window_hp.pop(idx, None)
        self._break_window(player, building, idx, window)

    def _blocking_door(self, chaser, player: Player) -> Building | None:
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

    def _gate_in_reach(self, pos, reach: float):
        """The barred gate a blow at `pos` lands on, as (village, index), or None.

        Barred and not merely shut: a gate closed for the night has no beam across it and
        opens to a press from either side, so hacking one down would be work nobody has any
        reason to do. Only the wall a settlement puts between itself and you answers a
        weapon."""
        for village in self._village_solids_by_chunk.get(self._chunk_of(*pos), ()):
            if not village.barred:
                continue
            index = village.gate_at(pos[0], pos[1], reach)
            if index is not None:
                return village, index
        return None

    def _hit_gate(self, village, index: int, damage: int, angle: float = 0.0):
        """Land a blow on a barred gate, and put it through once it has taken enough. The
        one part of a wall that ever gives: a settlement that has shut you out (or in) can
        be answered with a weapon rather than only with a walk round to the next side."""
        gate = village.defences()["gates"][index]
        rect = gate["rect"]
        if not village.damage_gate(index, damage):
            self._prop_chip(
                rect.centerx, rect.centery, c.Villages.GATE_LEAF, "crate_break", village.gate_key(index), angle
            )
            return
        # A gate going over is not a crate breaking: it gets its own sound, its own kick and
        # its own animation (`Village.gate_fall_progress`), so beating one down never reads
        # as the same event as somebody opening it.
        get_shake().add(c.Combat.CRATE_SHAKE * 2.0)
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        play_sound("gate_break")
        get_particles().spawn_burst(
            rect.centerx,
            rect.centery,
            c.Villages.GATE_LEAF,
            count=44,
            speed=9,
            life=800,
            size=6,
            gravity=0.5,
            shape="shard",
        )
        # The dust off a beam that size going down, hanging after the splinters have landed.
        get_particles().spawn_burst(
            rect.centerx, rect.centery, (120, 105, 88), count=20, speed=3, life=1100, size=9, gravity=0.03
        )
        if self.notify:
            self.notify("The gate gives way", c.Colors.WHITE)

    def bash_gates(self, player: Player, damage_mult: float = 1.0):
        """Let a monster shut out by a barred gate beat on it, exactly as it would a door.

        A gate is barred because the settlement has turned on the player, which is also when
        a pack is most likely to be standing at it: the wall is not breakable, the way round
        is a long one, and the leaf across the gap is the one thing in the way that answers a
        swing."""
        now = pygame.time.get_ticks()
        for monster in self.monsters:
            if (
                abs(monster.x - player.x) > c.World.DETECTION_RANGE
                or abs(monster.y - player.y) > c.World.DETECTION_RANGE
            ):
                continue
            if now < monster.next_bash_ms:
                continue
            hit = self._gate_in_reach((monster.x, monster.y), c.Buildings.DOOR_BASH_REACH)
            if hit is None:
                continue
            village, index = hit
            # Only if it is actually what stands between them: inside looking out, or the
            # other way about, either side of the line the gateway is cut in.
            if not village.gate_between(index, monster.x, monster.y, player.x, player.y):
                continue
            monster.next_bash_ms = now + c.Buildings.DOOR_BASH_COOLDOWN_MS
            monster.start_attack_anim()
            rect = village.defences()["gates"][index]["rect"]
            angle = math.atan2(rect.centery - monster.y, rect.centerx - monster.x)
            self._hit_gate(village, index, round(monster.kind.damage * damage_mult), angle)

    def prick_spikes(self, player: Player, quest_system: QuestSystem):
        """Whatever has just walked into the stakes outside a town's wall.

        The same idea as a bear trap and resolved the same way: nobody aimed it, so it costs
        the player nothing and pays them nothing (`by_player=False`). What it is for is the
        approach: an attacker crossing a tier 1 wall's outworks arrives hurt and slowed,
        which is what makes walking up to a far settlement feel different from walking up to
        a near one. The villagers know where their own stakes are and are never caught."""
        now = pygame.time.get_ticks()
        villages = [
            village
            for village in self._village_solids_by_chunk.get(self._chunk_of(player.x, player.y), ())
            if village.defended and village.tier >= c.Villages.SPIKE_TIER
        ]
        if not villages:
            return
        victims = [(player, c.Player.SIZE / 2)]
        victims += [(m, m.kind.size / 2) for m in self.monsters]
        victims += [(cr, cr.hit_radius) for cr in self.critters]
        for victim, radius in victims:
            if now < self._spike_ready.get(id(victim), 0):
                continue
            if not any(village.spike_hit(victim.x, victim.y, radius) for village in villages):
                continue
            self._spike_ready[id(victim)] = now + c.Villages.SPIKE_COOLDOWN_MS
            self._spike_victim(victim, player, quest_system)

    def _spike_victim(self, victim, player: Player, quest_system: QuestSystem):
        """A stake going in: a bite of health, wherever it lands."""
        play_sound("hit")
        get_particles().spawn_burst(victim.x, victim.y, c.Decals.BLOOD_COLOR, count=8, speed=4, life=380, size=3)
        if victim is player:
            player.receive_damage(c.Villages.SPIKE_DAMAGE, source=None)
            get_shake().add(c.Combat.PLAYER_HURT_SHAKE)
            return
        self._hurt_bystander(victim, c.Villages.SPIKE_DAMAGE, player, quest_system)

    def _hurt_bystander(self, victim, damage: int, player: Player, quest_system: QuestSystem):
        """Damage nobody aimed: a stake in an outwork, a bear trap's jaws.

        The player is not handled here, because what an unaimed blow costs *them* is a
        screen effect chosen by whatever laid it. Everything else only has to land on the
        right resolver, and all of them are told `by_player=False`: the player did not set
        this off, so it neither pays them nor is held against them.
        """
        if isinstance(victim, Critter):
            if victim.dead:
                return
            self._pop_damage(victim.x, victim.y - victim.size / 2, damage, False)
            if victim.receive_damage(damage):
                self._kill_critter(victim, player, by_player=False)
            else:
                victim.startle()
            return
        if isinstance(victim, NPC):
            self._resolve_npc_hit(victim, damage, player, quest_system, Blow(blocked=self.blocked, by_player=False))
            return
        self._resolve_monster_hit(victim, self.monsters, damage, player, quest_system, Blow(by_player=False))

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
            building = self._blocking_door(monster, player)
            if building is None or now < monster.next_bash_ms:
                continue
            monster.next_bash_ms = now + c.Buildings.DOOR_BASH_COOLDOWN_MS
            # A door is bashed on its own cadence rather than on the monster's swing clock,
            # so this is the animation only: no wind-up to read and no blow to land.
            monster.start_attack_anim()
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

    def _break_window(self, player: Player, building: Building, idx: int, window):
        """Shatter a window. No loot, and two things that are not the crash: the hole is a
        way into the house (`Building.window_gaps`, which is what makes a locked door worth
        answering), and putting somebody's window through in front of them is vandalism like
        wrecking their room, answered on the same ladder by whoever saw it."""
        building.broken_windows.add(idx)
        self.report_crime(window.centerx, window.centery, player)
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
        return max(1, round(damage)), crit

    @staticmethod
    def _dir_from(x0, y0, x1, y1):
        """Unit vector from (x0,y0) toward (x1,y1), or None if they coincide."""
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist == 0:
            return None
        return (dx / dist, dy / dist)

    @staticmethod
    def _knockback(target, _radius, kb_dir, distance, _blocked):
        """Shove a target along kb_dir: hand it the impulse the blow is worth and let it
        travel.

        The shove used to be walked out here and then it was over, all of it inside the
        frame the blow landed on, which is a teleport however many collision tests it is
        cut into: the pole, whose whole job is moving people, put them somewhere else with
        nothing crossing the ground in between. Now the blow only sets a velocity
        (`entities.apply_impulse`); `World.advance_impulses` spends it over the next few
        frames, walls and all, and the body is off its feet (`staggered`) while it does.

        `_radius` and `_blocked` are the caller's business no longer, kept in the signature
        because every strike site has them to hand and the sweep needs neither.
        """
        if not kb_dir or distance <= 0:
            return
        apply_impulse(target, kb_dir, distance)
        # A shove worth real ground kicks up where it started, so the impulse is seen
        # leaving the weapon rather than only read off where the body ends up.
        if distance >= c.Combat.KNOCKBACK_DUST_MIN:
            get_particles().spawn_directional_burst(
                target.x,
                target.y,
                math.atan2(-kb_dir[1], -kb_dir[0]),
                spread_deg=70.0,
                color=c.Combat.KNOCKBACK_DUST_COLOR,
                count=8,
                speed=4,
                life=340,
                size=4,
                gravity=0.25,
            )

    def _player_blow(self, target, base_damage, arch, player, blocked, hand=0, rampage=False) -> tuple[int, Blow]:
        """One blow of the player's own: the damage rolled, and how it landed.

        The three strike sites below share all of this and differ only in what they do
        around it, which is the point of pulling it out: a monster is open to on-hit effects
        and to chainstrike, a villager to lifesteal, an animal to neither.
        """
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus(hand), rampage=rampage)
        shake = arch.shake
        shake += c.Combat.CRIT_SHAKE_BONUS if crit else 0.0
        shake += c.Combat.CRIT_SHAKE_BONUS if rampage else 0.0
        blow = Blow(
            crit=crit,
            shake=shake,
            knockback=arch.knockback,
            kb_dir=self._dir_from(player.x, player.y, target.x, target.y),
            blocked=blocked,
        )
        return damage, blow

    def _strike_monster(self, monster, monster_list, base_damage, arch, player, quest_system, blocked, hand=0):
        rampage = player.rampage_trigger(hand)
        damage, blow = self._player_blow(monster, base_damage, arch, player, blocked, hand, rampage=rampage)
        died = self._resolve_monster_hit(monster, monster_list, damage, player, quest_system, blow)
        self._apply_on_hit_effects(monster, monster_list, damage, player, quest_system, died, hand)
        self._apply_chainstrike(monster, monster_list, damage, player, quest_system, blocked, hand)

    def _strike_npc(self, npc, base_damage, arch, player, quest_system, blocked, hand=0):
        damage, blow = self._player_blow(npc, base_damage, arch, player, blocked, hand)
        # Lifesteal works on any struck target, NPCs included.
        frac = player.lifesteal_frac(hand)
        if frac > 0:
            player.heal(damage * frac)
        self._resolve_npc_hit(npc, damage, player, quest_system, blow)

    def _strike_critter(self, critter: Critter, base_damage, arch, player: Player):
        """Wildlife takes hits like anything else. What a survivor does about it is its own
        temperament's business: a rabbit bolts, a boar turns round, a pack all turns round
        at once (`World.aggro_pack`). No quest system involvement, no loot table, nothing to
        burn or chain into, so this is the one strike that resolves the blow itself."""
        if critter.dead:
            return
        damage, blow = self._player_blow(critter, base_damage, arch, player, self.blocked)
        get_shake().add(blow.shake)
        self._pop_damage(critter.x, critter.y - critter.size / 2, damage, blow.crit)
        if critter.receive_damage(damage):
            self._kill_critter(critter, player, blow.kb_dir)
            return
        self._hit_feedback(critter.x, critter.y, blow.crit, blow.kb_dir)
        self._knockback(critter, critter.size / 2, blow.kb_dir, blow.knockback, self.blocked)
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
        self.report_crime(rect.centerx, rect.centery, player)
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
        self.drop_breakable(breakable)

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
        play_sound("trap_snap")
        get_shake().add(c.Combat.CRATE_SHAKE)
        get_particles().spawn_burst(trap.x, trap.y, c.Traps.JAW_COLOR, count=14, speed=5, life=450, size=4)
        # Teeth through a leg bleed like anything else does, and from where the leg is: a
        # trap that took a third of the health bar with nothing on the grass to show for it
        # was the one wound in the world that left no mark. Pierced, and thrown outward,
        # since nobody swung this.
        get_decals().splash(trap.x, trap.y, "pierce", direction=None, fatal=False)
        get_particles().spawn_burst(trap.x, trap.y, (178, 26, 26), count=22, speed=6, life=620, size=5, gravity=0.35)
        damage = c.Traps.DAMAGE
        victim.root(c.Traps.HOLD_MS)

        if victim is player:
            # The jaws shut over the whole screen, because what a trap actually costs the
            # player is the seconds afterwards, and a body that has simply stopped answering
            # the keys reads as a bug rather than as being caught.
            get_trap_fx().trigger()
            get_shake().add(c.Traps.SNAP_FX_SHAKE)
            get_hitstop().trigger(c.Traps.SNAP_FX_HITSTOP_MS)
            player.receive_damage(damage, source=trap)
            if self.notify:
                self.notify("A bear trap snaps shut on your leg. Struggle!", c.Colors.RED)
            return
        self._hurt_bystander(victim, damage, player, quest_system)

    def _resolve_monster_hit(
        self,
        monster: Monster,
        monster_list: list[Monster],
        damage: int,
        player: Player,
        quest_system: QuestSystem,
        blow: Blow = PLAIN_BLOW,
    ) -> bool:
        """Applies damage to a monster and its kill rewards. Returns True if it died."""
        if monster.dead:
            return True
        get_shake().add(blow.shake)
        self._pop_damage(monster.x, monster.y - monster.kind.size / 2, damage, blow.crit)
        if monster.receive_damage(damage):
            self._kill_monster(
                monster, monster_list, player, quest_system, direction=blow.kb_dir, by_player=blow.by_player
            )
            return True
        self._hit_feedback(monster.x, monster.y, blow.crit, blow.kb_dir)
        if not monster.knockback_immune:
            self._knockback(monster, monster.kind.size / 2, blow.kb_dir, blow.knockback, blow.blocked)
        return False

    def _spill_blood(self, x, y, body_color, direction=None, boss: bool = False):
        """The gore of a kill: a pool where it dropped, a fan of droplets thrown along the
        killing blow, and a spray still in the air over both.

        `direction` is the blow's (dx, dy) unit vector, so the mess points away from the
        player instead of ringing the corpse. A kill with no direction (a burn tick, an
        execute) bursts outward instead. What the mess is shaped like comes from the weapon
        that made it (`blow_style`), so a spear kill and a hammer kill leave different
        ground behind them."""
        style = self.blow_style
        get_decals().splash(x, y, style, direction, fatal=True, boss=boss)
        play_sound("gore")

        blood = (178, 26, 26)
        count = 78 if boss else 52
        speed = 17 if boss else 14
        size = 8 if boss else 7
        if direction:
            get_particles().spawn_directional_burst(
                x,
                y,
                math.atan2(direction[1], direction[0]),
                spread_deg=c.Decals.SPRAY_SPREAD_DEG,
                color=blood,
                count=count,
                speed=speed,
                life=780,
                size=size,
                gravity=0.32,
            )
        else:
            get_particles().spawn_burst(x, y, blood, count=count, speed=speed, life=780, size=size, gravity=0.32)
        # Chunks of the thing itself, so a slime still bleeds green over the red.
        get_particles().spawn_burst(x, y, body_color, count=30 if boss else 22, speed=8, life=600, size=7, gravity=0.42)
        # A slow, dark mist hanging where the body was, under the fast stuff: it lingers
        # after the droplets have landed, so the moment does not end on the same frame.
        get_particles().spawn_burst(
            x, y, (96, 12, 12), count=24 if boss else 16, speed=2, life=1200, size=10 if boss else 8, gravity=0.02
        )
        get_shake().add(c.Combat.KILL_SHAKE_BONUS * (2.0 if boss else 1.0))

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
            # A cave's warden belongs to its vault the way a garrison belongs to its camp,
            # so its death is that tunnel's business and is recorded there.
            if monster.camp_id:
                self.on_guard_killed(monster, quest_system)
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
        # And a raider's is the village's: what the settlement thanks the player for is the
        # raid being over, so the kills are counted and paid once (`WorldSocial.update_raid`).
        if by_player and monster.raid_key:
            self.credit_raid_kill(monster)
        monster_list.remove(monster)

    def _apply_on_hit_effects(self, monster, monster_list, damage, player, quest_system, died, hand: int = 0):
        """Weapon lifesteal/burn/execute after a hit lands, from the weapon in `hand`.
        `died` is the hit's own result."""
        frac = player.lifesteal_frac(hand)
        if frac > 0 and damage > 0:
            player.heal(damage * frac)
            get_particles().spawn_burst(player.x, player.y, c.Colors.GREEN, count=5, speed=3, life=300, size=3)
        if died:
            return
        burn = player.burn_damage(hand)
        if burn > 0:
            monster.apply_burn(burn)
        # Execute finishes off a badly wounded non-boss outright.
        thr = player.execute_threshold(hand)
        if thr > 0 and not isinstance(monster, Boss) and 0 < monster.hp <= monster.max_hp * thr:
            get_particles().spawn_burst(monster.x, monster.y, (255, 60, 60), count=10, speed=5, life=400, size=4)
            if monster.receive_damage(monster.hp):
                self._kill_monster(monster, monster_list, player, quest_system)

    def _apply_chainstrike(self, primary, target_list, damage, player, quest_system, blocked, hand: int = 0):
        """Chain Strike: a landed hit sends a pulse out from whatever was struck, and
        everything else within `Affixes.CHAINSTRIKE_RADIUS` takes a share of the blow.

        An area effect rather than one jump to the nearest body: the legendary is the
        reason to wade into a crowd rather than a slightly better single target. It draws
        the ring it damaged over (`core.impact_fx`) and a bolt to each thing it caught, so
        several damage numbers popping at once have something visible behind them."""
        frac = player.chainstrike_frac(hand)
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
                target, target_list, chain_damage, player, quest_system, Blow(kb_dir=kb_dir, blocked=blocked)
            )
            self._apply_on_hit_effects(target, target_list, chain_damage, player, quest_system, died, hand)

    def _apply_element(self, proj, target, target_list, player, quest_system, died: bool):
        """What an elemental staff's bolt does where it landed (`c.Staffs`).

        Each element is an existing mechanic pointed at by the weapon rather than by an
        affix roll: fire lights the burn ticker, frost slows whatever it touched, storm
        jumps to the nearest other body. Nothing happens on a shot that was not the
        player's, and nothing happens to something the hit already killed."""
        if not proj.element or died:
            return
        # Only a monster carries a burn ticker: an NPC and an animal are hit by the bolt
        # and lit by nothing, which is deliberate rather than an oversight.
        if proj.element == "fire" and isinstance(target, Monster):
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
            Blow(kb_dir=self._dir_from(primary.x, primary.y, nearest.x, nearest.y), blocked=self.blocked),
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
        blow: Blow = PLAIN_BLOW,
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
        if npc.dead:
            return True
        # Whatever bit them is what they turn round and swing at (`WorldSocial.militia_orders`).
        # Only ever something the player did not do: the player's own blows are answered by
        # the village as a whole, on the ladder below, and not by one farmer taking a swing.
        if not blow.by_player and blow.source is not None:
            npc.threaten(blow.source)
        # A settlement warns before it turns (`WorldSocial.strike_village`): the first blow
        # the player lands there is answered with a shout and nothing else, so snapping at
        # somebody in the street is a thing the player is told they are about to do rather
        # than something they discover a moment too late. A killing skips the ladder below.
        # Cutting down somebody who has thrown their weapon down is the one offence with no
        # ladder under it: they are kneeling with their hands empty in front of the whole
        # street, and there is nothing left to warn anybody about.
        if blow.by_player and (npc.surrendered or self.strike_village(npc, player)):
            if npc.surrendered and self.notify:
                self.notify("You struck someone who had yielded", c.Colors.RED)
            for provoked in self.provoke_village(npc):
                # Nobody hands in a task to someone they are trying to kill; drop it rather
                # than leave an uncompletable quest in the log.
                quest_system.remove_quest(provoked)
        get_shake().add(blow.shake)
        self._pop_damage(npc.x, npc.y - c.Entities.NPC_SIZE / 2, damage, blow.crit)
        if npc.receive_damage(damage):
            if blow.by_player:
                for provoked in self.hold_grudge(npc):
                    quest_system.remove_quest(provoked)
            stolen_item = quest_system.on_npc_killed(npc)
            if stolen_item is not None:
                self.items.append(stolen_item)
            # Drop any quest this NPC was offering so it can't become uncompletable
            quest_system.remove_quest(npc)
            play_sound("monster_death")
            if blow.by_player:
                get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
            self._spill_blood(npc.x, npc.y, npc.color, blow.kb_dir)
            self._drop_villager_loot(npc, player, blow.by_player)
            self.npcs.remove(npc)
            return True
        self._hit_feedback(npc.x, npc.y, blow.crit, blow.kb_dir)
        self._knockback(npc, c.Entities.NPC_SIZE / 2, blow.kb_dir, blow.knockback, blow.blocked)
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

    def _hit_feedback(self, x, y, crit: bool, direction=None):
        """Sound + particle burst for a non-fatal hit; crits read brighter and louder.
        `direction` (attacker -> target unit vector), if given, sprays the particles as a
        cone away from the hit instead of a plain omnidirectional poof."""
        play_sound("crit" if crit else "hit")
        if crit:
            get_hitstop().trigger(c.Combat.HITSTOP_CRIT_MS)
        # Even a hit that does not kill throws blood: a short fan along the blow, so a long
        # fight paints the ground it was fought over instead of leaving one dot per hit.
        get_decals().splash(x, y, self.blow_style, direction, fatal=False)
        color = (255, 240, 160) if crit else (255, 180, 180)
        count = 18 if crit else 10
        speed = 5 if crit else 4
        life = 420 if crit else 340
        size = 5 if crit else 4
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

    def _tick_burns(self, monster_list: list[Monster], player: Player, quest_system: QuestSystem):
        now = pygame.time.get_ticks()
        for monster in list(monster_list):
            if monster.dead or monster.burn_ticks_remaining <= 0 or now < monster.burn_next_ms:
                continue
            monster.burn_ticks_remaining -= 1
            monster.burn_next_ms = now + c.Affixes.BURN_INTERVAL_MS
            get_particles().spawn_burst(monster.x, monster.y, (255, 140, 40), count=4, speed=2, life=300, size=3)
            get_floating_text().spawn(
                monster.x, monster.y - monster.kind.size / 2, str(monster.burn_damage), (255, 150, 60)
            )
            if monster.receive_damage(monster.burn_damage):
                self._kill_monster(monster, monster_list, player, quest_system)
