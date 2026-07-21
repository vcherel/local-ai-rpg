from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.particles import get_particles
from game.entities.entities import draw_human
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
    )


class Boss(Monster):
    """A named, multi-phase boss. Extends Monster for chasing and melee, and layers on
    telegraphed special abilities, an enrage phase, knockback immunity and a big health bar.

    `quest_tag` links a boss spawned by a slay_boss quest back to that quest; None otherwise."""

    def __init__(self, x, y, template: c.BossKind = c.BOSS_KINDS[0], quest_tag: str | None = None):
        super().__init__(x, y, _kind_from_boss(template))
        self.template = template
        self.quest_tag = quest_tag
        # Display identity, filled in by the LLM after spawn; a plain fallback until then.
        self.name = template.archetype.capitalize()
        self.title = ""
        self.knockback_immune = True

        self.enraged = False
        self.ability_cd = random.uniform(*c.Boss.ABILITY_COOLDOWN_RANGE_MS)
        # Milliseconds left in a slam's warning telegraph; 0 when no slam is winding up.
        self.slam_windup = 0.0

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
            self.move(player, dt, world.blocked)
            self.ability_cd -= dt
            if self.ability_cd <= 0 and self.slam_windup <= 0:
                self._use_ability(world, player)
                self.ability_cd = random.uniform(*c.Boss.ABILITY_COOLDOWN_RANGE_MS) * self._cd_mult
        else:
            self.update_attack_anim(dt)

    def _apply_enrage_stats(self):
        self.enraged = True
        self.kind = replace(
            self.kind,
            speed=self.kind.speed * c.Boss.ENRAGE_SPEED_MULT,
            damage=int(round(self.kind.damage * c.Boss.ENRAGE_DAMAGE_MULT)),
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
                damage = int(round(damage * c.Boss.ENRAGE_DAMAGE_MULT))
            player.receive_damage(damage)

    def _cast_volley(self, world: World, player: Player):
        play_sound("shoot")
        base = math.atan2(player.y - self.y, player.x - self.x) + math.pi / 2  # match Projectile's up-facing angle
        spread = math.radians(c.Boss.VOLLEY_SPREAD_DEG)
        count = c.Boss.VOLLEY_COUNT
        damage = c.Boss.VOLLEY_DAMAGE
        if self.enraged:
            damage = int(round(damage * c.Boss.ENRAGE_DAMAGE_MULT))
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
                )
            )

    def _summon_adds(self, world: World):
        play_sound("monster_death")
        kind = next((k for k in c.MONSTER_KINDS if k.name == self.template.summon_kind), c.MONSTER_KINDS[0])
        for _ in range(c.Boss.SUMMON_COUNT):
            angle = random.uniform(0, 2 * math.pi)
            x = self.x + math.cos(angle) * c.Boss.SUMMON_RADIUS
            y = self.y + math.sin(angle) * c.Boss.SUMMON_RADIUS
            if not world.blocked(x, y, kind.size / 2):
                world.monsters.append(Monster(x, y, kind))
        get_particles().spawn_burst(self.x, self.y, self.template.color, count=18, speed=5, life=500, size=5)

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

        draw_human(
            screen,
            sx,
            sy,
            size,
            self.flash_color(self.kind.color),
            self.orientation,
            self.attack_progress,
            self.attack_hand,
        )

        label = c.Fonts.button.render(self.name, True, c.Colors.WHITE)
        screen.blit(label, (sx - label.get_width() // 2, sy - size // 2 - 34))
