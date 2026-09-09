from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.decals import get_decals, style_for_weapon
from core.floating_text import get_floating_text
from core.impact_fx import get_impacts
from core.particles import get_particles
from core.screen_fx import get_hitstop, get_trap_fx
from core.swing_arcs import get_swings
from game.blow import PLAIN_BLOW, Blow
from game.entities.boss import Boss
from game.entities.critter import Critter
from game.entities.entities import apply_impulse
from game.entities.items import Item, rarity_color, roll_rarity
from game.entities.monsters import Monster
from game.entities.npcs import NPC
from game.loot import loot_villager

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
        pos = player.reach_point(reach)
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
        for victim, radius in self._bodies_with_radius(player, npcs=False):
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

    def _bodies_with_radius(self, player: Player, npcs: bool = True) -> list[tuple]:
        """Everything standing on the ground that something underfoot can catch, each with
        the radius it is caught at: the player, the monsters, the animals and (unless the
        caller says otherwise) the villagers.

        What a bear trap and a town's stakes both need, and the one place the four different
        ways of asking a body how wide it is are written down. The villagers are left out
        for the stakes because they know where their own are.
        """
        bodies = [(player, c.Player.SIZE / 2)]
        bodies += [(monster, monster.kind.size / 2) for monster in self.monsters]
        bodies += [(critter, critter.hit_radius) for critter in self.critters]
        if npcs:
            bodies += [(npc, c.Entities.NPC_SIZE / 2) for npc in self.npcs]
        return bodies

    def snap_traps(self, player: Player, quest_system: QuestSystem):
        """Whatever has just put a foot in a set bear trap, and what it costs them.

        A trap is not aimed at anyone: the first thing to stand on it springs it, whether
        that is the player, a wolf, a villager or the monster chasing all three. Nothing it
        catches pays the player anything (`by_player=False`), since the player did not set
        it; what they get out of one is the seconds it holds something still.
        """
        live = [trap for trap in self.traps if not trap.sprung]
        if not live:
            return
        # The player first and then everything else, which is the order the jaws are checked
        # in and not a priority: one trap shuts on one body, whoever reached it.
        underfoot = self._bodies_with_radius(player)
        for trap in live:
            caught = next((body for body, radius in underfoot if trap.catches(body.x, body.y, radius)), None)
            if caught is not None:
                self._spring_trap(trap, caught, player, quest_system)

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

    @staticmethod
    def _others_within(primary, target_list, radius: float) -> list:
        """Everything in `target_list` but `primary` standing within `radius` of it.

        What a hit jumps to when it carries on past what it landed on, whether that is Chain
        Strike taking all of them or a storm staff taking the nearest. The two differ in
        what they do with the list, not in how they find it.
        """
        return [
            target
            for target in target_list
            if target is not primary and target.distance_to_point((primary.x, primary.y)) < radius
        ]

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
        caught = self._others_within(primary, target_list, c.Affixes.CHAINSTRIKE_RADIUS)
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
            self._others_within(primary, target_list, c.Staffs.CHAIN_RADIUS),
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
