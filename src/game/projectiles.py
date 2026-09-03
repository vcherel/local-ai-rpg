from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.floating_text import get_floating_text
from core.particles import get_particles
from game.blow import Blow
from game.entities.items import rarity_tier
from game.entities.projectile import ARROW_COLOR, BOLT_COLOR, Projectile

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


class WorldProjectiles:
    """Everything that travels: the player's shot, a monster's, and what each one does when
    it arrives.

    Mixed into `World` beside `WorldCombat`, which owns the swing and the damage helpers
    these methods call (`_resolve_monster_hit`, `_resolve_npc_hit`, `_kill_critter`, the
    affix and element effects). Split out for the same reason `combat.py` was split off
    `world.py`: an arrow in flight is one coherent job with its own lifetime, where a swing
    resolves and is over.

    An arrow is not choosy about whose it is, so every method here carries a `by_player`
    flag: False means the shot still lands and still kills, but no xp, no lootbox, no quest
    counter, no provoked village and no pack aggro come of it.
    """

    def _fire_ranged(self, player: Player, arch: c.WeaponArchetype, hand: int = 0):
        now = pygame.time.get_ticks()
        if not player.hand_ready(hand, now):
            return
        # A boomerang is thrown, not fired: waiting for it to come home is what it costs
        # instead of ammo. One per hand, not one per player: two of them is two weapons,
        # and each hand waits for its own to come back.
        if arch.projectile_style == "boomerang" and any(
            proj.style == "boomerang" and proj.owner_id == id(player) and proj.hand == hand for proj in self.projectiles
        ):
            return
        # Magic is paid for out of the pool, ammo out of the quiver, and a staff that cannot
        # pay simply does not fire: the shot is not queued, nothing is spent and the swing
        # animation never starts, so an empty pool reads as a weapon that has run dry.
        if arch.mana_cost and not player.spend_mana(arch.mana_cost):
            get_floating_text().spawn(player.x, player.y - c.Player.SIZE, "No mana", c.Magic.EMPTY_COLOR)
            player.spend_hand(hand, now, arch.cooldown_ms)
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

        player.spend_hand(hand, now, arch.cooldown_ms, arch.swing_mult)
        # Hand one is the right arm on the sprite, hand two the left: the arm that comes up
        # is the one the weapon is actually in.
        player.start_attack_anim("right" if hand == 0 else "left", c.Player.SWING_MS)
        play_sound("shoot")

        # A bolt is worth what the caster is worth: magic where a bow reads strength, so
        # training one never quietly pays for the other.
        stat_bonus = player.stats.magic_bonus() if arch.mana_cost else player.stats.attack_bonus()
        base_damage = (c.Player.ATTACK_DAMAGE + player.weapon_bonus(hand) + stat_bonus) * (player.damage_multiplier())
        # A shot can crit too (weapon + affix chance), boosting damage and the hit's shake.
        # Rampage forces every Nth shot to crit and amplifies it further.
        rampage = player.rampage_trigger(hand)
        damage, crit = self._roll_hit(base_damage, arch, player.crit_bonus(hand), rampage=rampage)
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
        proj.skill = "magic" if arch.mana_cost else "strength"
        proj.pierce = player.pierce_count()
        # Which hand loosed it, so what it does when it lands is the weapon that threw it
        # rather than whatever the player has switched to by then.
        proj.hand = hand
        weapon = player.hand_weapon(hand)
        if style == "boomerang":
            proj.owner = player
            # A boomerang leaves the hand: while it is in the air the player is holding
            # nothing, and `Player.gear` reads this same id to draw them that way.
            proj.weapon_id = weapon.id if weapon else None
            # How many bodies it carries through before it turns for home is its rarity,
            # and a plain one carries through nothing: it comes back off the first hit.
            if weapon is not None:
                tier = c.Rarity.TIERS.index(rarity_tier(weapon.rarity))
                proj.pierce += c.Boomerang.PIERCE_BY_TIER[tier]
            proj.out_pierce = proj.pierce
        self.projectiles.append(proj)
        # Magic is trained by casting, the way running trains speed: the mana it costs is
        # what stops that being free.
        if arch.mana_cost:
            player.stats.train("magic", c.Stats.XP_PER_CAST)

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
            # A shot is paced by `shot_cooldown_ms` rather than by the swing clock, so this
            # is the animation only: the arrow is what lands, not the arm.
            monster.start_attack_anim()
            play_sound("shoot")
            style, color = ("bolt", BOLT_COLOR) if monster.kind.name == "Hexer" else ("arrow", ARROW_COLOR)
            shot = Projectile(
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
            # Who loosed it, so a villager it catches knows what to turn round and swing at
            # (`NPC.threaten`) instead of taking an arrow from nowhere.
            shot.owner = monster
            self.projectiles.append(shot)

    def update_projectiles(self, player: Player, quest_system: QuestSystem, dt):
        for proj in list(self.projectiles):
            proj.update(dt, self.blocked_over_walls if proj.over_walls else self.blocked)
            if proj.dead:
                self.projectiles.remove(proj)
                continue

            # A hostile shot is aimed at the player, but it is an arrow, not a guided one:
            # anything standing in the way takes it instead. What that hits is nobody's
            # doing, so it is uncredited (`by_player=False`): no xp, no loot, no quest
            # progress, and a villager felled by a goblin's stray arrow does not turn the
            # village on the player who was only walking past.
            if proj.hostile and proj.distance_to_point((player.x, player.y)) < c.Projectile.SIZE + c.Player.SIZE / 2:
                # A raised shield turns away what arrives on the side it is worn: the
                # shot glances off the face of it and nothing lands. Everything else
                # goes through `receive_damage` with the shot as its source, so the
                # shield still eats its share of a blow it only half covers.
                if player.shield_side_hit(proj):
                    self._deflect(proj, player)
                    continue
                player.receive_damage(proj.damage, source=proj)
                get_shake().add(proj.shake)
                self.projectiles.remove(proj)
                continue

            by_player = proj.by_player and not proj.hostile
            # Whatever this arrow opens up bleeds the way something struck from a distance
            # does, not the way the last sword swing did.
            self.blow_style = "shot"
            if self._projectile_hits_monster(proj, self.monsters, player, quest_system, by_player):
                continue
            if self._projectile_hits_monster(proj, self.bosses, player, quest_system, by_player):
                continue
            if self._projectile_hits_critter(proj, player, by_player):
                continue
            # A villager's own shot passes through villagers: an angry street is a crowd,
            # and an arrow that stopped in the first neighbour standing in the way had a
            # town shooting itself to pieces the moment it turned on the player.
            if not proj.from_npc and self._projectile_hits_npc(proj, player, quest_system, by_player):
                continue
            self._projectile_hits_keg(proj, player, quest_system)

        # What the player is currently holding nothing of: a thrown boomerang is in the air,
        # not in the hand that threw it, and `Player.gear` draws that hand empty until it
        # comes home. Read off what is actually flying, so a catch, a wall or a death all
        # put the weapon back without any of them having to remember to.
        player.thrown_ids = {proj.weapon_id for proj in self.projectiles if proj.owner is player and proj.weapon_id}

    def _deflect(self, proj: Projectile, player: Player):
        """A shot met by the face of a raised shield: it glances off and is gone, in a spray
        of sparks thrown back the way it came.

        It costs guard rather than health, so an archer can still wear a shield down: turning
        arrows away is something the player does for the volley they saw coming, not a wall
        they can stand behind all afternoon."""
        self.projectiles.remove(proj)
        player.spend_guard(c.Shield.DEFLECT_GUARD_COST)
        play_sound("hit")
        get_particles().spawn_directional_burst(
            proj.x,
            proj.y,
            math.atan2(-proj.vy, -proj.vx),
            spread_deg=80.0,
            color=c.Shield.DEFLECT_COLOR,
            count=12,
            speed=6,
            life=300,
            size=3,
        )
        get_floating_text().spawn(player.x, player.y - c.Player.SIZE / 2, "Deflected", c.Shield.DEFLECT_COLOR)

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
            player.stats.train(proj.skill, c.Stats.XP_PER_HIT)
        kb_dir = self._dir_from(0, 0, proj.vx, proj.vy)
        died = self._resolve_monster_hit(
            target,
            targets,
            proj.damage,
            player,
            quest_system,
            Blow(
                shake=proj.shake if by_player else 0.0,
                knockback=proj.knockback,
                kb_dir=kb_dir,
                blocked=self.blocked,
                by_player=by_player,
            ),
        )
        if by_player:
            self._apply_on_hit_effects(target, targets, proj.damage, player, quest_system, died, proj.hand)
            self._apply_element(proj, target, targets, player, quest_system, died)
            self._apply_chainstrike(target, targets, proj.damage, player, quest_system, self.blocked, proj.hand)
        self._projectile_after_hit(proj, target)
        return True

    def _projectile_hits_critter(self, proj: Projectile, player: Player, by_player: bool = True) -> bool:
        """Resolve a projectile against wildlife: an arrow is how most animals get hunted,
        since they run long before a swing lands. Returns True if it struck one.

        A shot that was not the player's still wounds the animal, but the pack it belongs
        to has no reason to blame the player for it, so `aggro_pack` is skipped."""
        critter = self._projectile_target(proj, self.critters, lambda cr: cr.hit_radius)
        if critter is None or critter.dead:
            return False
        # A village's own dogs are its own people for this: a shot out of the towers passes
        # through them exactly as it passes through the villagers standing in the street.
        if proj.from_npc and critter.village_key:
            return False

        if by_player:
            player.stats.train(proj.skill, c.Stats.XP_PER_HIT)
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
        npc = self._projectile_target(proj, self.npcs, lambda _n: c.Entities.NPC_SIZE // 2)
        if npc is None:
            return False

        if by_player:
            player.stats.train(proj.skill, c.Stats.XP_PER_HIT)
        self._resolve_npc_hit(
            npc,
            proj.damage,
            player,
            quest_system,
            Blow(
                shake=proj.shake if by_player else 0.0,
                knockback=proj.knockback,
                kb_dir=self._dir_from(0, 0, proj.vx, proj.vy),
                blocked=self.blocked,
                by_player=by_player,
                source=None if by_player else proj.owner,
            ),
        )
        frac = player.lifesteal_frac(proj.hand) if by_player else 0.0
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

    def _projectile_after_hit(self, proj: Projectile, target):
        """Record the target and either pierce onward (arrow-pierce) or stop the projectile.

        A boomerang that has gone through everything it can carry turns for home instead of
        stopping: it is thrown rather than fired, and it always comes back."""
        proj.hit_ids.add(id(target))
        if proj.pierce > 0:
            proj.pierce -= 1
        elif not proj.turn_back():
            self.projectiles.remove(proj)
