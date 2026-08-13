from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from game.entities.entities import Entity

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player


def pick_monster_kind(distance_from_center: float) -> c.MonsterKind:
    """Pick a kind unlocked at this distance from the world center; weaker kinds stay more common."""
    eligible = [kind for kind in c.MONSTER_KINDS if distance_from_center >= kind.min_distance]
    return random.choices(eligible, weights=[kind.weight for kind in eligible])[0]


class Monster(Entity):
    # Bosses shrug off knockback; a plain monster does not.
    knockback_immune = False

    def __init__(self, x, y, kind: c.MonsterKind = c.MONSTER_KINDS[0]):
        super().__init__(x, y, kind.color, kind.size, kind.hp, kind.hp)
        self.kind = kind
        self.target_offset = (random.uniform(-15, 15), random.uniform(-15, 15))
        # Burn (weapon affix) state: damage per tick, ticks left, and the next tick's time.
        self.burn_damage = 0
        self.burn_ticks_remaining = 0
        self.burn_next_ms = 0
        # Id of the bandit camp this monster was posted at, empty for a roaming monster, and
        # whether it is that camp's leader. A guard belongs to its camp rather than to the
        # world: it lives as long as the camp's chunk is loaded, never counts toward the
        # roaming population cap, and its death is recorded on the camp itself.
        self.camp_id = ""
        self.camp_leader = False
        # Ranged kinds only: the earliest tick this one may loose its next shot. World
        # fires it (WorldCombat.fire_monster_shots), since the arrow belongs to the world.
        self.next_shot_ms = 0
        # Charger state (kind.charge): when the current windup/rush ends, the heading it
        # committed to, and the earliest tick it may line up another one.
        self.charge_windup_until_ms = 0
        self.charge_until_ms = 0
        self.charge_angle = 0.0
        self.charge_ready_ms = 0
        # Flanker state (kind.flank_deg): which side it is currently swinging round, and
        # when it next switches.
        self.flank_side = random.choice((-1, 1))
        self.flank_flip_ms = 0

    def apply_burn(self, damage: int):
        """(Re)ignite this monster: refresh the tick count and take the stronger burn."""
        self.burn_damage = max(self.burn_damage, damage)
        self.burn_ticks_remaining = c.Affixes.BURN_TICKS
        self.burn_next_ms = pygame.time.get_ticks() + c.Affixes.BURN_INTERVAL_MS

    # camp_id/camp_leader are deliberately absent: a guard is rebuilt from its camp's own
    # count when the chunk loads, so World.serialize drops guards rather than saving them.
    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "hp": self.hp, "kind": self.kind.name}

    @classmethod
    def from_dict(cls, data: dict) -> Monster:
        kind = next((k for k in c.MONSTER_KINDS if k.name == data["kind"]), c.MONSTER_KINDS[0])
        monster = cls(data["x"], data["y"], kind)
        monster.hp = data["hp"]
        return monster

    def start_attack_anim(self, dist):
        """Return True in case of hit to the player"""
        was_attacking = self.attack_in_progress
        super().start_attack_anim()
        return not was_attacking and dist < self.kind.attack_range + c.Player.SIZE // 2

    # Deflection angles tried when the straight line to the player is blocked, alternating
    # sides so the monster steers around whichever edge of the obstacle is nearer.
    _STEER_OFFSETS_DEG = (0, 30, -30, 60, -60, 90, -90, 120, -120, 150, -150)

    def _steer(self, target_angle, blocked, radius, speed):
        """Pick the least deflected heading that stays clear a few steps ahead. Probing at
        a lookahead distance rather than one step makes a monster commit to going around a
        wall while it still has room, instead of grinding into it until it happens to slide free."""
        if blocked is None:
            return target_angle
        probe = max(speed * c.World.STEER_LOOKAHEAD, radius + c.World.STEER_MIN_PROBE)
        for offset_deg in self._STEER_OFFSETS_DEG:
            angle = target_angle + math.radians(offset_deg)
            nx = self.x + math.cos(angle) * probe
            ny = self.y + math.sin(angle) * probe
            if not blocked(nx, ny, radius):
                return angle
        return target_angle

    def _flank(self, target_angle, dist) -> float:
        """Bend the approach to one side, swapping sides every few seconds. The bend fades
        out as the monster closes, so a flanker circles in and still arrives instead of
        orbiting the player out of reach forever."""
        if not self.kind.flank_deg:
            return target_angle
        now = pygame.time.get_ticks()
        if now >= self.flank_flip_ms:
            self.flank_side = -self.flank_side
            self.flank_flip_ms = now + random.randint(c.Flank.FLIP_MIN_MS, c.Flank.FLIP_MAX_MS)
        fade = min(1.0, max(0.0, (dist - c.Flank.CLOSE_DISTANCE) / c.Flank.CLOSE_DISTANCE))
        return target_angle + math.radians(self.kind.flank_deg) * self.flank_side * fade

    def _charge(self, dist, aware, move_factor, radius, blocked) -> bool:
        """Line up a rush, run it, or decline. True while the charge owns this monster's
        movement, which is the whole of it: the windup is spent planted so the rush can be
        sidestepped, and the heading is locked before it starts so stepping aside works.

        Damage is not special-cased. A charge just delivers the monster to the player at
        speed; the ordinary swing does the rest."""
        now = pygame.time.get_ticks()
        if now < self.charge_windup_until_ms:
            return True
        if now < self.charge_until_ms:
            speed = self.kind.speed * c.Charge.SPEED_MULT * move_factor
            step_x = math.cos(self.charge_angle) * speed
            step_y = math.sin(self.charge_angle) * speed
            if blocked is not None and blocked(self.x + step_x, self.y + step_y, radius):
                # Hit something mid-rush: the charge is spent and it goes back to walking.
                self.charge_until_ms = 0
                return False
            self.x += step_x
            self.y += step_y
            return True
        if aware and now >= self.charge_ready_ms and c.Charge.MIN_RANGE < dist < c.Charge.RANGE:
            self.charge_angle = self.orientation
            self.charge_windup_until_ms = now + c.Charge.WINDUP_MS
            self.charge_until_ms = self.charge_windup_until_ms + c.Charge.DURATION_MS
            self.charge_ready_ms = self.charge_until_ms + c.Charge.COOLDOWN_MS
            return True
        return False

    def move(self, player: Player, dt, blocked=None, waypoint=None, damage_mult: float = 1.0, detection=None):
        """Chase the player, or `waypoint` when one is given: a door the monster has to walk
        through first because the player is on the other side of a wall (see World.chase_waypoint).
        The attack swing always keys off the real distance to the player, waypoint or not.

        `damage_mult` and `detection` come from the world rather than the monster, because
        both are properties of the moment: everything hits harder and notices sooner at
        night, and a monster that spawned at noon is no gentler for it once the sun is down.

        A ranged kind never closes: it walks into its firing range, backs off if the player
        gets inside `keep_distance`, and leaves the shooting itself to the world. A charger
        crosses the gap in one telegraphed rush instead of walking, and a flanker bends its
        approach to one side so a group of them comes in from several angles at once."""
        dx = player.x + self.target_offset[0] - self.x
        dy = player.y + self.target_offset[1] - self.y
        dist = math.hypot(dx, dy)
        senses = c.World.DETECTION_RANGE if detection is None else detection
        move_factor = dt * c.TARGET_FPS / 1000.0
        radius = self.kind.size / 2

        if waypoint is not None:
            target_angle = math.atan2(waypoint[1] - self.y, waypoint[0] - self.x)
        else:
            target_angle = math.atan2(dy, dx)
        self.orientation = target_angle

        aware = dist < senses + c.Player.SIZE // 2
        retreating = self.kind.ranged and dist < self.kind.keep_distance
        charging = self.kind.charge and self._charge(dist, aware, move_factor, radius, blocked)
        if charging:
            self.orientation = self.charge_angle
        elif aware and (retreating or self.kind.attack_range < dist):
            speed = self.kind.speed * move_factor
            move_angle = target_angle if waypoint is not None else self._flank(target_angle, dist)
            angle = self._steer(move_angle + (math.pi if retreating else 0.0), blocked, radius, speed)
            step_x = math.cos(angle) * speed
            step_y = math.sin(angle) * speed
            # Move one axis at a time so a wall on one axis lets the monster slide along it.
            if blocked is not None and blocked(self.x + step_x, self.y, radius):
                step_x = 0
            self.x += step_x
            if blocked is not None and blocked(self.x, self.y + step_y, radius):
                step_y = 0
            self.y += step_y

        if not self.kind.ranged and dist < self.kind.attack_range * 10:
            hit = self.start_attack_anim(dist)
            if hit:
                player.receive_damage(round(self.kind.damage * damage_mult), source=self)

        # atan2(dy, dx) measures from the x-axis; sprites face up, so rotate a quarter turn
        self.orientation += math.pi / 2

        self.update_attack_anim(dt)

    def draw(self, screen, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        self._draw_charge_telegraph(screen, screen_x, screen_y)
        super().draw(
            screen,
            screen_x,
            screen_y,
            self.kind.size,
            self.kind.color,
            self.orientation,
            self.attack_progress,
            self.attack_hand,
            bar_width=60,
            bar_height=8,
            health_bar_offset=10,
        )

    def _draw_charge_telegraph(self, screen, screen_x, screen_y):
        """The lane a winding-up charger is about to cross, drawn under it. Without this the
        rush is unreadable: the monster stands still and then arrives."""
        remaining = self.charge_windup_until_ms - pygame.time.get_ticks()
        if remaining <= 0:
            return
        progress = 1.0 - remaining / c.Charge.WINDUP_MS
        length = c.Charge.RANGE * 0.7 * progress
        end = (
            screen_x + math.cos(self.charge_angle) * length,
            screen_y + math.sin(self.charge_angle) * length,
        )
        pygame.draw.line(screen, (170, 60, 50), (screen_x, screen_y), end, 3)
        pygame.draw.circle(screen, (200, 80, 60), (round(screen_x), round(screen_y)), round(self.kind.size * 0.8), 2)
