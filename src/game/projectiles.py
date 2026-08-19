from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from game.entities.entities import Entity
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

    def _projectile_after_hit(self, proj: Projectile, target):
        """Record the target and either pierce onward (arrow-pierce) or stop the projectile.

        A boomerang that has gone through everything it can carry turns for home instead of
        stopping: it is thrown rather than fired, and it always comes back."""
        proj.hit_ids.add(id(target))
        if proj.pierce > 0:
            proj.pierce -= 1
        elif not proj.turn_back():
            self.projectiles.remove(proj)
