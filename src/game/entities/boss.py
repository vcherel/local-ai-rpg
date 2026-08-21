from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.impact_fx import get_impacts
from core.particles import get_particles
from core.text_fx import draw_outlined_text
from game.entities.monster_art import draw_monster
from game.entities.monsters import Monster
from game.entities.projectile import Projectile

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player
    from game.world import World
    from llm.quest_system import QuestSystem


def _kind_from_boss(template: c.BossKind) -> c.MonsterKind:
    """A boss reuses all of Monster's chase/melee/draw machinery, which keys off a
    MonsterKind, so we synthesise one from the boss template's stats."""
    return c.MonsterKind(
        name=f"boss:{template.archetype}",
        color=template.color,
        size=template.size,
        hp=template.hp,
        speed=template.speed,
        attack_range=template.attack_range,
        damage=template.damage,
        min_distance=0,
        weight=0,
        shape=template.shape,
        weapon=template.weapon,
        eye_color=template.eye_color,
    )


class Boss(Monster):
    """A named, multi-phase boss. Extends Monster for chasing and melee, and layers on
    telegraphed special abilities, an enrage phase, knockback immunity and a big health bar.

    `quest_tag` links a boss spawned by a slay_boss quest back to that quest; None otherwise."""

    knockback_immune = True
    # Clear of the name a boss carries over its head.
    STATUS_BUBBLE_LIFT = 62

    def __init__(self, x, y, template: c.BossKind = c.BOSS_KINDS[0], quest_tag: str | None = None):
        super().__init__(x, y, _kind_from_boss(template))
        self.template = template
        self.quest_tag = quest_tag
        # Display identity, filled in by the LLM after spawn; a plain fallback until then.
        self.name = template.archetype.capitalize()
        self.title = ""

        self.enraged = False
        self.ability_cd = random.uniform(*c.Boss.ABILITY_COOLDOWN_RANGE_MS)
        # Milliseconds left in a slam's warning telegraph; 0 when no slam is winding up.
        self.slam_windup = 0.0
        # Spots marked for a summons that has not arrived yet, each carrying where it lands,
        # what lands there and how long is left of its telegraph. Session-only: a fight left
        # mid-cast is a fight the player walked out of.
        self.pending_summons: list[dict] = []

    # ------------------------------------------------------------------ identity / save

    def set_identity(self, text: str):
        """Parse an LLM name like 'Gorroth, the Bonecrusher' into name + title."""
        text = " ".join(text.strip().strip('"').split())
        if not text:
            return
        if "," in text:
            name, title = text.split(",", 1)
            self.name = name.strip()[:40] or self.name
            self.title = title.strip().lstrip("- ")[:60]
        else:
            self.name = text[:40]

    @property
    def display_name(self) -> str:
        return f"{self.name}, {self.title}" if self.title else self.name

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "hp": self.hp,
            "archetype": self.template.archetype,
            "name": self.name,
            "title": self.title,
            "enraged": self.enraged,
            "quest_tag": self.quest_tag,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Boss:
        template = next((k for k in c.BOSS_KINDS if k.archetype == data["archetype"]), c.BOSS_KINDS[0])
        boss = cls(data["x"], data["y"], template, quest_tag=data.get("quest_tag"))
        boss.hp = data["hp"]
        boss.name = data.get("name", boss.name)
        boss.title = data.get("title", "")
        if data.get("enraged"):
            boss._apply_enrage_stats()
        return boss

    # ------------------------------------------------------------------ per-frame update

    @property
    def _cd_mult(self) -> float:
        return c.Boss.ENRAGE_COOLDOWN_MULT if self.enraged else 1.0

    def update_boss(self, world: World, player: Player, dt, quest_system: QuestSystem):
        dist = self.distance_to_point((player.x, player.y))

        if not self.enraged and self.hp <= self.max_hp * c.Boss.ENRAGE_HP_RATIO:
            self._enrage(world)

        # A slam telegraph resolves on its own timer, even if the player runs out of range.
        if self.slam_windup > 0:
            self.slam_windup -= dt
            if self.slam_windup <= 0:
                self._resolve_slam(player)

        if dist <= c.Boss.AGGRO_RANGE:
            # Monster.move handles the chase and the basic melee swing.
            waypoint = world.chase_waypoint(self, player, self.kind.size / 2)
            # A boss only ever wants the player; the villagers a plain monster would turn on
            # are beneath it. Monster.move hands its swing back rather than landing it.
            damage = self.move(
                player,
                dt,
                world.blocked,
                waypoint,
                world.night_damage_mult(),
                c.Boss.AGGRO_RANGE,
                terrain_mult=world.terrain_speed(self.x, self.y),
            )
            if damage:
                player.receive_damage(damage, source=self)
            self.ability_cd -= dt
            if self.ability_cd <= 0 and self.slam_windup <= 0:
                self._use_ability(world, player)
                self.ability_cd = random.uniform(*c.Boss.ABILITY_COOLDOWN_RANGE_MS) * self._cd_mult
        else:
            self.update_attack_anim(dt)

        # Last, so anything arriving this frame is stood up after the boss has had its own.
        self._advance_summons(world, dt)

    def _apply_enrage_stats(self):
        self.enraged = True
        self.kind = replace(
            self.kind,
            speed=self.kind.speed * c.Boss.ENRAGE_SPEED_MULT,
            damage=round(self.kind.damage * c.Boss.ENRAGE_DAMAGE_MULT),
        )

    def _enrage(self, world: World):
        self._apply_enrage_stats()
        get_shake().add(c.Boss.SLAM_SHAKE)
        get_particles().spawn_burst(self.x, self.y, self.template.aura, count=26, speed=7, life=650, size=6)
        play_sound("monster_death")
        if world.notify:
            world.notify(f"{self.name} enrages!", c.Colors.BOSS_BAR_ENRAGED)

    # ------------------------------------------------------------------ abilities

    def _use_ability(self, world: World, player: Player):
        # Don't restart a slam that's already telegraphing.
        options = [a for a in self.template.abilities if not (a == "slam" and self.slam_windup > 0)]
        if not options:
            return
        ability = random.choice(options)
        if ability == "slam":
            self._start_slam()
        elif ability == "volley":
            self._cast_volley(world, player)
        elif ability == "summon":
            self._summon_adds(world)

    def _start_slam(self):
        self.slam_windup = c.Boss.SLAM_TELEGRAPH_MS
        play_sound("shoot")

    def _resolve_slam(self, player: Player):
        self.slam_windup = 0.0
        get_shake().add(c.Boss.SLAM_SHAKE)
        get_particles().spawn_burst(self.x, self.y, self.template.aura, count=30, speed=9, life=600, size=6)
        play_sound("attack")
        if self.distance_to_point((player.x, player.y)) <= c.Boss.SLAM_RADIUS + c.Player.SIZE / 2:
            damage = c.Boss.SLAM_DAMAGE
            if self.enraged:
                damage = round(damage * c.Boss.ENRAGE_DAMAGE_MULT)
            # Sourced on the boss so a raised shield can take the edge off a slam the
            # player saw coming and turned to face.
            player.receive_damage(damage, source=self)

    def _cast_volley(self, world: World, player: Player):
        play_sound("shoot")
        base = math.atan2(player.y - self.y, player.x - self.x) + math.pi / 2  # match Projectile's up-facing angle
        spread = math.radians(c.Boss.VOLLEY_SPREAD_DEG)
        count = c.Boss.VOLLEY_COUNT
        damage = c.Boss.VOLLEY_DAMAGE
        if self.enraged:
            damage = round(damage * c.Boss.ENRAGE_DAMAGE_MULT)
        for i in range(count):
            offset = spread * (i / (count - 1) - 0.5) if count > 1 else 0.0
            world.projectiles.append(
                Projectile(
                    self.x,
                    self.y,
                    base + offset,
                    damage,
                    style="bolt",
                    color=self.template.aura,
                    shake=4.0,
                    hostile=True,
                    owner_id=id(self),
                    source_name=self.display_name,
                    max_range=c.Projectile.MONSTER_RANGE,
                )
            )

    def _summon_adds(self, world: World):
        """Call for help, and mark the ground it is coming out of.

        Nothing is stood up on the frame the ability fires. Each spot is marked instead, and
        what arrives there arrives when the mark has run its course (`_advance_summons`): a
        fight that grows three bodies with no warning reads as a spawn bug, where a ring
        opening in the dirt reads as the boss doing something and gives the player the room
        to walk out of it."""
        play_sound("summon")
        kind = next((k for k in c.MONSTER_KINDS if k.name == self.template.summon_kind), c.MONSTER_KINDS[0])
        for _ in range(c.Boss.SUMMON_COUNT):
            angle = random.uniform(0, 2 * math.pi)
            x = self.x + math.cos(angle) * c.Boss.SUMMON_RADIUS
            y = self.y + math.sin(angle) * c.Boss.SUMMON_RADIUS
            if world.blocked(x, y, kind.size / 2):
                continue
            self.pending_summons.append({"x": x, "y": y, "kind": kind, "left": c.Boss.SUMMON_TELEGRAPH_MS})
            get_impacts().pulse(x, y, kind.size, self.template.aura)
            get_particles().spawn_burst(x, y, self.template.aura, count=10, speed=3, life=520, size=4)
        get_particles().spawn_burst(self.x, self.y, self.template.color, count=18, speed=5, life=500, size=5)
        if self.pending_summons and world.notify:
            world.notify(f"{self.name} calls something up!", self.template.aura)

    def _advance_summons(self, world: World, dt):
        """Carry every marked spot a frame along, and stand up whatever has finished
        arriving. Runs whether or not the player is still in range: a summons already called
        for is on its way, and walking off is meant to buy distance, not cancel it."""
        for summon in list(self.pending_summons):
            summon["left"] -= dt
            if summon["left"] > 0:
                continue
            self.pending_summons.remove(summon)
            kind = summon["kind"]
            if world.blocked(summon["x"], summon["y"], kind.size / 2):
                continue
            monster = Monster(summon["x"], summon["y"], kind)
            # Held where it stands for a moment: it is climbing out of the ground, and a
            # body that runs on the frame it appears never reads as having arrived at all.
            monster.root(c.Boss.SUMMON_EMERGE_MS)
            world.monsters.append(monster)
            get_impacts().pulse(summon["x"], summon["y"], kind.size * 1.4, self.template.aura)
            get_particles().spawn_burst(
                summon["x"], summon["y"], self.template.color, count=16, speed=6, life=420, size=5
            )
            play_sound("monster_death")

    def draw_summon_marks(self, screen, camera: Camera):
        """The ground opening where something is about to stand: a ring drawing itself shut
        as the arrival gets closer, under everything alive like the shadow it is."""
        for summon in self.pending_summons:
            progress = 1.0 - max(0.0, summon["left"]) / c.Boss.SUMMON_TELEGRAPH_MS
            x, y = camera.world_to_screen(summon["x"], summon["y"])
            radius = round(summon["kind"].size * (0.5 + progress * 0.6))
            pygame.draw.circle(screen, (18, 14, 20), (x, y), radius)
            pygame.draw.circle(screen, self.template.aura, (x, y), radius, max(1, round(2 + progress * 3)))

    # ------------------------------------------------------------------ drawing

    def draw(self, screen, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        size = self.kind.size

        # Pulsing aura ring behind the body so a boss reads as more than a big monster.
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 220.0)
        aura_r = int(size * 0.9 + pulse * 8)
        aura = pygame.Surface((aura_r * 2, aura_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(aura, (*self.template.aura, 70), (aura_r, aura_r), aura_r)
        pygame.draw.circle(aura, (*self.template.aura, 130), (aura_r, aura_r), aura_r, 3)
        screen.blit(aura, (sx - aura_r, sy - aura_r))

        # Slam telegraph: a warning ring that fills in as the pound lands.
        if self.slam_windup > 0:
            frac = 1.0 - self.slam_windup / c.Boss.SLAM_TELEGRAPH_MS
            r = c.Boss.SLAM_RADIUS
            ring = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(ring, (255, 70, 50, 60), (r, r), r)
            pygame.draw.circle(ring, (255, 90, 60, 220), (r, r), r, 4)
            pygame.draw.circle(ring, (255, 200, 120, 200), (r, r), max(2, int(r * frac)), 3)
            screen.blit(ring, (sx - r, sy - r))

        draw_monster(
            screen,
            sx,
            sy,
            size,
            self.flash_color(self.kind.color),
            self.orientation,
            self.kind.shape,
            attack_progress=self.attack_progress,
            attack_hand=self.attack_hand,
            weapon=self.kind.weapon,
            # Enraging brightens its eyes, the one tell that reads from across the arena.
            eye_color=tuple(min(255, v + 60) for v in self.kind.eye_color) if self.enraged else self.kind.eye_color,
            # A boss is never idling as far as the player is concerned: its eyes are always lit.
            aggro=True,
            phase=self.art_phase,
            walk=self.gait.step(self.x, self.y),
        )

        name_y = sy - size // 2 - 34 + c.Fonts.button.get_height() // 2
        draw_outlined_text(screen, self.name, c.Fonts.button, c.Colors.WHITE, center=(sx, name_y))
        self.draw_status_bubbles(screen, sx, sy, size)
