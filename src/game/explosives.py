"""Bombs, blasts and everything caught in one.

Mixed into `World` beside `WorldCombat`, on the same entity lists. Both kinds of bomb (the
mine laid on the ground, the grenade thrown at the cursor) and the creeper that walks up
and goes off end in the one `explode`, so nothing about a blast is ever written twice: one
radius, one falloff, one set of things caught, one scorch mark.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.decals import get_decals
from core.impact_fx import get_impacts
from core.particles import get_particles
from core.screen_fx import get_flash, get_hitstop
from game.blow import Blow
from game.entities.bomb import GRENADE, MINE, Bomb
from game.entities.items import bomb_kind

if TYPE_CHECKING:
    from game.entities.monsters import Monster
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


class WorldExplosives:
    """What a blast catches and what it does to each thing it caught."""

    def use_bomb(self, player: Player, item):
        """Spend one out of the bomb slot: a mine laid where the player stands, a grenade
        thrown at what the player is aiming at.

        Neither is a weapon that hits something. Both are a piece of ground the player has
        decided to fight over, exactly like a powder keg, and both end in the same `explode`
        the keg does. The one thing decided here is where it ends up."""
        now = pygame.time.get_ticks()
        # Thrown with the first hand, so it is that hand's clock a bomb spends: the other
        # one is free to keep firing, exactly as it is while this one swings.
        if not player.hand_ready(0, now):
            return
        if not player.spend_one(item):
            return
        player.spend_hand(0, now, c.Bombs.COOLDOWN_MS)
        player.end_spawn_grace()
        player.start_attack_anim("right", c.Player.SWING_MS)

        if bomb_kind(item.name) == MINE:
            self.bombs.append(Bomb(player.x, player.y, MINE))
        else:
            # Thrown where the player is looking rather than as far as the arm goes: the
            # cursor is the aim for every other weapon, and a grenade lands short of it
            # only when a wall is in the way.
            mouse_x, mouse_y = pygame.mouse.get_pos()
            reach = math.hypot(mouse_x - c.Screen.ORIGIN_X, mouse_y - c.Screen.ORIGIN_Y)
            self.bombs.append(Bomb(player.x, player.y, GRENADE, player.orientation, reach))
        play_sound("fuse")

    def update_bombs(self, player: Player, quest_system: QuestSystem, dt):
        """Burn every fuse down and set off whatever has run out or been stepped on.

        A mine answers to anything that would fight the player and never to the player
        themselves: laying one under your own feet and backing away is the whole point of
        it, and a blast that went off as you stepped off it would make it unusable."""
        for bomb in list(self.bombs):
            fired = bomb.update(dt, self.blocked)
            if bomb.dead:
                self.bombs.remove(bomb)
                continue
            if not fired and bomb.kind == MINE:
                hostile = [
                    body
                    for group in (self.monsters, self.bosses, self.npcs, self.critters)
                    for body in group
                    if getattr(body, "hostile", True)
                ]
                fired = bomb.triggered_by(hostile)
            if not fired:
                continue
            self.bombs.remove(bomb)
            self.explode(
                bomb.x,
                bomb.y,
                player,
                quest_system,
                radius=c.Bombs.RADIUS,
                damage=c.Bombs.DAMAGE,
                knockback=c.Bombs.KNOCKBACK,
                shake=c.Bombs.SHAKE,
                player_mult=c.Bombs.PLAYER_DAMAGE_MULT,
                message="",
            )

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
        self._blast_fx(x, y, radius, shake, message if depth == 0 else "")

        def blast_damage(distance: float) -> int:
            frac = max(0.0, 1.0 - distance / radius)
            scale = edge_frac + (1.0 - edge_frac) * frac
            return max(1, round(damage * scale))

        def blow_at(ex: float, ey: float) -> Blow:
            return Blow(
                knockback=knockback,
                kb_dir=self._dir_from(x, y, ex, ey),
                blocked=self.blocked,
                by_player=by_player,
            )

        self._blast_monsters(x, y, radius, blast_damage, blow_at, player, quest_system)
        self._blast_critters(x, y, radius, blast_damage, knockback, by_player, player)
        self._blast_npcs(x, y, radius, blast_damage, blow_at, player, quest_system)
        self._blast_player(x, y, radius, blast_damage, knockback, player_mult, by_player, player)
        self._chain_kegs(x, y, depth, player, quest_system, by_player)

    @staticmethod
    def _caught_in(x, y, radius: float, entities, radius_of) -> list:
        """Everything in `entities` standing inside the blast, with how far out it was.

        Taken as a list before anything is resolved: a blast kills, and killing walks the
        very list being iterated."""
        found = []
        for entity in list(entities):
            distance = math.hypot(entity.x - x, entity.y - y)
            if distance < radius + radius_of(entity):
                found.append((entity, distance))
        return found

    def _blast_monsters(self, x, y, radius, blast_damage, blow_at, player: Player, quest_system: QuestSystem):
        for group in (self.bosses, self.monsters):
            for monster, distance in self._caught_in(x, y, radius, group, lambda m: m.kind.size / 2):
                self._resolve_monster_hit(
                    monster, group, blast_damage(distance), player, quest_system, blow_at(monster.x, monster.y)
                )

    def _blast_critters(self, x, y, radius, blast_damage, knockback, by_player: bool, player: Player):
        for critter, distance in self._caught_in(x, y, radius, self.critters, lambda cr: cr.hit_radius):
            if critter.dead:
                continue
            hurt = blast_damage(distance)
            kb_dir = self._dir_from(x, y, critter.x, critter.y)
            self._pop_damage(critter.x, critter.y - critter.size / 2, hurt, False)
            if critter.receive_damage(hurt):
                self._kill_critter(critter, player, kb_dir, by_player=by_player)
                continue
            self._knockback(critter, critter.size / 2, kb_dir, knockback, self.blocked)
            critter.startle()
            if by_player:
                self.aggro_pack(critter)

    def _blast_npcs(self, x, y, radius, blast_damage, blow_at, player: Player, quest_system: QuestSystem):
        for npc, distance in self._caught_in(x, y, radius, self.npcs, lambda _n: c.Entities.NPC_SIZE / 2):
            self._resolve_npc_hit(npc, blast_damage(distance), player, quest_system, blow_at(npc.x, npc.y))

    def _blast_player(self, x, y, radius, blast_damage, knockback, player_mult, by_player: bool, player: Player):
        """The blast is not choosy about who it throws: standing next to a keg costs the
        player health and the ground it puts between them and wherever they meant to be."""
        distance = math.hypot(player.x - x, player.y - y)
        if distance >= radius:
            return
        # What the death screen names: the keg is the player's own doing, the creeper
        # somebody else's.
        killer = "a powder keg" if by_player else "a creeper"
        player.receive_damage(round(blast_damage(distance) * player_mult), source=killer)
        self._knockback(player, c.Player.SIZE / 2, self._dir_from(x, y, player.x, player.y), knockback, self.blocked)

    def _chain_kegs(self, x, y, depth: int, player: Player, quest_system: QuestSystem, by_player: bool):
        """Every keg near enough to go off in turn, one step deeper into the chain."""
        if depth >= c.Explosion.MAX_CHAIN_DEPTH:
            return
        near = [
            keg
            for keg in list(self.breakables)
            if keg.kind == "powder" and math.hypot(keg.x - x, keg.y - y) < c.Explosion.CHAIN_RADIUS
        ]
        for keg in near:
            # Re-checked rather than trusted: the list was taken before the chain started,
            # and a recursive blast below may already have taken this keg off.
            if keg not in self.breakables:
                continue
            self.drop_breakable(keg)
            # A keg is still a keg whatever lit it, but the credit follows the hand that
            # started the chain: nothing a creeper set off pays the player.
            self.explode(keg.x, keg.y, player, quest_system, depth + 1, by_player=by_player)

    def _blast_fx(self, x, y, radius: float, shake: float, message: str):
        """How a blast looks and sounds, which is all of what makes it read as the loudest
        thing in the game: the wash, the freeze, the shockwave going out past what it hurt,
        the fire, the smoke that hangs, and the debris that arcs and lands.

        Kept apart from `explode` so that method is the damage it is named for. Only the
        blast that started a chain announces itself; the kegs it sets off are the same event.
        The scorch is the exception: every blast burns its own ground, so a chain leaves the
        shape it went off in.
        """
        # The mark on the ground first, so everything thrown up by the blast is over it.
        get_decals().scorch(x, y, radius)
        get_shake().add(shake)
        play_sound("crate_break")
        get_flash().trigger(c.Explosion.FLASH_AMOUNT, c.Explosion.FLASH_COLOR)
        get_hitstop().trigger(c.Explosion.HITSTOP_MS)
        get_particles().spawn_burst(
            x, y, (255, 170, 60), count=c.Explosion.FIRE_PARTICLES, speed=13, life=650, size=8, gravity=0.2
        )
        get_particles().spawn_burst(
            x, y, (90, 80, 75), count=c.Explosion.SMOKE_PARTICLES, speed=6, life=1100, size=10, gravity=0.03
        )
        get_particles().spawn_burst(
            x,
            y,
            (150, 110, 70),
            count=c.Explosion.DEBRIS_PARTICLES,
            speed=15,
            life=900,
            size=6,
            gravity=0.55,
            shape="shard",
        )
        for frac, ring_color in zip(c.Explosion.RING_FRACS, c.Explosion.RING_COLORS, strict=True):
            get_impacts().pulse(x, y, radius * frac, ring_color)
        if self.notify and message:
            self.notify(message, (255, 170, 60))

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
