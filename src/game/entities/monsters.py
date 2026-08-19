from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from game.entities.entities import Entity, push_apart
from game.entities.monster_art import draw_monster, weapon_hand

if TYPE_CHECKING:
    from core.camera import Camera


def pick_monster_kind(distance_from_center: float) -> c.MonsterKind:
    """Pick a kind for this distance from the world center.

    A kind unlocks at its `min_distance` and then fades out again: its weight halves every
    `Entities.DEPTH_HALF_LIFE` past that point, down to `DEPTH_MIN_WEIGHT_FRAC` of what it
    started at. Without the fade, walking out only ever *added* kinds to the roll, so the
    deep wilds stayed mostly slimes with the occasional troll: more variety rather than
    more danger. With it, the weak things thin out behind the player.
    """
    eligible = [kind for kind in c.MONSTER_KINDS if distance_from_center >= kind.min_distance]
    weights = []
    for kind in eligible:
        depth = distance_from_center - kind.min_distance
        fade = 0.5 ** (depth / c.Entities.DEPTH_HALF_LIFE)
        weights.append(kind.weight * max(fade, c.Entities.DEPTH_MIN_WEIGHT_FRAC))
    return random.choices(eligible, weights=weights)[0]


class Monster(Entity):
    # Bosses shrug off knockback; a plain monster does not.
    knockback_immune = False

    def __init__(self, x, y, kind: c.MonsterKind = c.MONSTER_KINDS[0]):
        super().__init__(x, y, kind.color, kind.size, kind.hp, kind.hp)
        self.kind = kind
        # The bearing this one takes around the player: it walks to its own point on a ring
        # just inside its reach rather than to the player's exact position, so a pack comes
        # in from several sides. A pack's members are given evenly spread bearings when they
        # are stood up (World._spawn_monster_away_from); a lone monster rolls its own.
        self.slot_angle = random.uniform(0, 2 * math.pi)
        # Which side it committed to when it last had to go round something, and how long
        # that commitment holds. Steering without it re-decides every frame at the edge of
        # an obstacle, which reads as a monster shivering against a wall rather than
        # walking round it.
        self.steer_side = 0
        self.steer_hold_ms = 0
        # Whether it is one of the few allowed to swing right now (World.assign_surround_slots).
        # Everything else on the ring keeps its place and waits its turn, so a pack presses
        # in from all sides instead of taking turns in a queue at the front.
        self.attack_token = True
        # Which way round the ring it circles while it waits for one.
        self.circle_side = random.choice((-1, 1))
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
        # Earliest tick this one may swing at a closed door again (World.bash_door).
        self.next_bash_ms = 0
        # Charger state (kind.charge): when the current windup/rush ends, the heading it
        # committed to, and the earliest tick it may line up another one.
        self.charge_windup_until_ms = 0
        self.charge_until_ms = 0
        self.charge_angle = 0.0
        self.charge_ready_ms = 0
        # Detonator state (kind.detonate): when its fuse was lit, 0 while it is still walking.
        # Once lit it is never put out; killing it or leaving its blast are the answers.
        self.fuse_started_ms = 0
        # Flanker state (kind.flank_deg): which side it is currently swinging round, and
        # when it next switches.
        self.flank_side = random.choice((-1, 1))
        self.flank_flip_ms = 0
        # Drawing only: whether it has noticed the player (its eyes flare, which is the one
        # warning it gives before it starts coming), and its own offset into the idle breath
        # so a pack of them does not pulse as one animal.
        self.aggro = False
        self.art_phase = random.random()

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

    @property
    def melee_reach(self) -> int:
        """How close this one has to be to land a swing. A ranged kind's `attack_range` is
        how far it can shoot rather than how far it can reach, so it gets a knife's reach:
        an archer cornered into fighting must not be hitting from across the clearing."""
        return c.Entities.RANGED_MELEE_RANGE if self.kind.ranged else self.kind.attack_range

    @property
    def shot_readiness(self) -> float:
        """How far along a ranged kind is toward its next shot, 0 to 1. Drawn as the arrow
        being pulled back, so a shot is telegraphed rather than arriving out of a still pose."""
        if not self.kind.ranged or not self.kind.shot_cooldown_ms:
            return 0.0
        remaining = self.next_shot_ms - pygame.time.get_ticks()
        return min(1.0, max(0.0, 1.0 - remaining / self.kind.shot_cooldown_ms))

    @property
    def fusing(self) -> bool:
        return bool(self.fuse_started_ms)

    @property
    def fuse_progress(self) -> float:
        """How far through its fuse a detonator is, 0 to 1. Drawn as the flash and the ring,
        so the seconds the player has are read off the screen rather than counted."""
        if not self.fuse_started_ms:
            return 0.0
        elapsed = pygame.time.get_ticks() - self.fuse_started_ms
        return min(1.0, max(0.0, elapsed / c.Creeper.FUSE_MS))

    def fuse_expired(self) -> bool:
        """The fuse has burned out: the world takes this one off the map and sets the blast
        off where it is standing (WorldCombat.detonate_creeper)."""
        return self.fusing and self.fuse_progress >= 1.0

    def _tick_fuse(self, dist, aware, target):
        """Light the fuse once the target is inside the blast, and never put it out again.

        Committing is the whole of the counterplay: from that moment it is a timer the player
        can walk out of, shove out of with a cudgel or kill inside, rather than a swing they
        have to stand there and block."""
        if self.fusing or not aware:
            return
        if dist < c.Creeper.TRIGGER_RANGE + target.size / 2:
            self.fuse_started_ms = pygame.time.get_ticks()
            play_sound("fuse")

    def start_attack_anim(self, dist):
        """Return True in case of hit to the player"""
        was_attacking = self.attack_in_progress
        # The armed hand is the one that swings: an axe hanging off the still arm while the
        # empty one flails reads as a bug rather than as an attack.
        super().start_attack_anim(weapon_hand(self.kind.weapon) if self.kind.weapon else None)
        return not was_attacking and dist < self.melee_reach + c.Player.SIZE // 2

    # Deflection angles tried when the straight line to the player is blocked, smallest
    # first; each is tried to both sides, the committed one leading.
    _STEER_OFFSETS_DEG = (0, 30, 60, 90, 120, 150)

    def _probe_clear(self, angle, probe, blocked, radius) -> bool:
        """Is the whole leg out to `probe` walkable, not just the point at the end of it?

        Sampling the tip alone let a monster pick a heading straight through a wall as long
        as there was open ground on the far side of it."""
        for i in range(1, c.World.STEER_PROBE_SAMPLES + 1):
            reach = probe * i / c.World.STEER_PROBE_SAMPLES
            if blocked(self.x + math.cos(angle) * reach, self.y + math.sin(angle) * reach, radius):
                return False
        return True

    def _commit_side(self, side: int):
        self.steer_side = side
        self.steer_hold_ms = pygame.time.get_ticks() + c.World.STEER_COMMIT_MS

    def _steer(self, target_angle, blocked, radius, speed, goal_dist=None):
        """Pick the least deflected heading that stays clear a few steps ahead. Probing at
        a lookahead distance rather than one step makes a monster commit to going around a
        wall while it still has room, instead of grinding into it until it happens to slide free.

        The probe never reaches past the goal itself: a player standing in a corner has a wall
        a step behind them, and steering round a wall that lies beyond where the monster is
        trying to stand is what used to leave it circling just out of reach.

        A deflection, once taken, is held for a moment and tried first next frame. A monster
        that re-decides which way round a trunk to go on every frame goes nowhere, and going
        the long way round consistently beats changing your mind at the halfway point."""
        if blocked is None:
            return target_angle
        far = max(speed * c.World.STEER_LOOKAHEAD, radius + c.World.STEER_MIN_PROBE)
        if goal_dist is not None:
            far = max(radius + c.World.STEER_CLOSE_PROBE, min(far, goal_dist))
        if pygame.time.get_ticks() >= self.steer_hold_ms:
            self.steer_side = 0
        lead = self.steer_side or 1
        # The short probe is the fallback: in a corner or between two pieces of furniture
        # every long probe is blocked, and giving up there is what used to leave a monster
        # grinding into a table while the player stood two steps away.
        for probe in (far, radius + c.World.STEER_CLOSE_PROBE):
            for offset_deg in self._STEER_OFFSETS_DEG:
                for side in (0,) if offset_deg == 0 else (lead, -lead):
                    angle = target_angle + math.radians(offset_deg) * side
                    if not self._probe_clear(angle, probe, blocked, radius):
                        continue
                    if side:
                        self._commit_side(side)
                    return angle
        # Boxed in on every heading that still points somewhere useful: run along whatever
        # is in the way rather than into it, which is what gets a monster out of the corner
        # it walked itself into.
        for side in (lead, -lead):
            angle = target_angle + math.pi / 2 * side
            if self._probe_clear(angle, radius + c.World.STEER_CLOSE_PROBE, blocked, radius):
                self._commit_side(side)
                return angle
        return target_angle

    def _aim_point(self, target, blocked, radius: float, cornered: bool = False) -> tuple:
        """Where this one is trying to stand: its own bearing on a ring just inside its own
        reach, so a group ends up around the player rather than all on the same spot. A kind
        with a long reach settles further out for free.

        Falls back to the player's own position when that spot is inside something (a corner,
        a wall behind the player): a slot nobody can stand in is worse than no slot at all."""
        if self.kind.ranged and not cornered:
            standoff = float(self.kind.keep_distance)
        else:
            # Cornered, a shooter wants the same place a melee kind does: knife range.
            standoff = max(0.0, self.melee_reach + target.size / 2 - c.Entities.CHASE_RING_MARGIN)
        for bearing in (self.slot_angle, math.atan2(self.y - target.y, self.x - target.x)):
            x = target.x + math.cos(bearing) * standoff
            y = target.y + math.sin(bearing) * standoff
            if blocked is None or not blocked(x, y, radius):
                return x, y
        # Nothing clear anywhere on the ring: a melee kind walks straight at its target and
        # lets steering sort the last few steps out, a shooter holds where it is standing.
        return (self.x, self.y) if self.kind.ranged else (target.x, target.y)

    def _separate(self, crowd, blocked, radius: float):
        """Push out of anything standing in the same place, through the same shove an angry
        village's mob uses (`entities.push_apart`)."""
        push_apart(self, crowd, radius, lambda other: other.kind.size / 2, blocked)

    def cornered(self, dist: float) -> bool:
        """A ranged kind with the player right on top of it. It has nowhere useful to back
        off to, so it stops retreating, stops shooting and swings instead: closing the gap
        is meant to be the answer to an archer, not the start of a stalemate."""
        return self.kind.ranged and dist < self.kind.keep_distance * c.Entities.CORNERED_FRAC

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

    def move(
        self,
        target,
        dt,
        blocked=None,
        waypoint=None,
        damage_mult: float = 1.0,
        detection=None,
        crowd=None,
        terrain_mult: float = 1.0,
    ) -> int:
        """Chase `target`, or `waypoint` when one is given: a door the monster has to walk
        through first because its target is on the other side of a wall (see World.chase_waypoint).
        The attack swing always keys off the real distance to the target, waypoint or not.

        The target is usually the player, but a monster that has walked into a settlement is
        given the villager it is nearest instead (World._monster_target), which is what makes
        a village something monsters attack rather than scenery they walk past. Damage is
        returned rather than applied: only the world knows whether a blow that landed has to
        go through the player's shield or through a villager's death.

        `damage_mult` and `detection` come from the world rather than the monster, because
        both are properties of the moment: everything hits harder and notices sooner at
        night, and a monster that spawned at noon is no gentler for it once the sun is down.

        A ranged kind never closes: it holds `keep_distance` and backs off (slower than it
        advances) when the player gets inside it, leaving the shooting itself to the world,
        until the player is right on top of it and it has to fight. A charger crosses the gap
        in one telegraphed rush instead of walking, and a flanker bends its approach to one
        side so a group of them comes in from several angles at once.

        `crowd` is the other chasers nearby: whoever is standing where this one wants to be
        gets shouldered aside, which is what keeps a pack a ring rather than a single body.

        `terrain_mult` is what the ground under it costs: nothing in the world swims well,
        so a monster that follows the player into a river is slowed for as long as it is in
        the water, which is what makes crossing one a real answer to being chased."""
        dist = math.hypot(target.x - self.x, target.y - self.y)
        senses = c.World.DETECTION_RANGE if detection is None else detection
        # Chilled by a frost bolt: it still turns, still swings and still shoots, it just
        # covers less ground doing it, exactly like the water and unlike a trap.
        move_factor = dt * c.TARGET_FPS / 1000.0 * terrain_mult * self.chill_mult
        # Caught in a bear trap: every step below is scaled by this, so it turns, swings and
        # shoots from where it stands and simply cannot cross the ground to the player.
        if self.rooted:
            move_factor = 0.0
        radius = self.kind.size / 2

        aware = dist < senses + target.size // 2
        self.aggro = aware
        # A detonator plants itself the moment its fuse is lit: what happens next is a timer,
        # and a bomb that kept walking would be unavoidable rather than dodgeable.
        if self.kind.detonate:
            self._tick_fuse(dist, aware, target)
            if self.fusing:
                move_factor = 0.0
        # Held back off the attack tokens with the target in reach: circle rather than
        # stand. Its own bearing is what it walks to, so turning that turns the whole ring.
        if not self.attack_token and not self.kind.ranged and dist < self.melee_reach + target.size:
            self.slot_angle += math.radians(c.Entities.CIRCLE_SPEED_DEG) * self.circle_side * move_factor
        cornered = self.cornered(dist)
        retreating = self.kind.ranged and not cornered and dist < self.kind.keep_distance

        goal = waypoint if waypoint is not None else self._aim_point(target, blocked, radius, cornered)
        gdx, gdy = goal[0] - self.x, goal[1] - self.y
        goal_dist = math.hypot(gdx, gdy)
        # Standing still is only allowed once the monster can act from where it is: a shooter
        # holding its distance, or a melee kind close enough to land its swing. Otherwise a
        # slot a few pixels short of reach would have it wait politely out of range forever.
        settled = (self.kind.ranged and not cornered) or dist < self.melee_reach + target.size / 2
        arrived = waypoint is None and goal_dist <= c.Entities.CHASE_ARRIVE and settled
        # Facing follows the walk, except once it has taken its place: the angle to a spot
        # it is already standing on is noise, and what it wants to face then is its target.
        target_angle = math.atan2(gdy, gdx)
        self.orientation = math.atan2(target.y - self.y, target.x - self.x) if arrived else target_angle

        charging = self.kind.charge and self._charge(dist, aware, move_factor, radius, blocked)
        if charging:
            self.orientation = self.charge_angle
        elif aware and not arrived:
            speed = self.kind.speed * move_factor
            if retreating:
                speed *= c.Entities.RETREAT_SPEED_MULT
            move_angle = target_angle if waypoint is not None else self._flank(target_angle, dist)
            angle = self._steer(move_angle, blocked, radius, speed, goal_dist)
            step_x = math.cos(angle) * speed
            step_y = math.sin(angle) * speed
            # Move one axis at a time so a wall on one axis lets the monster slide along it.
            if blocked is not None and blocked(self.x + step_x, self.y, radius):
                step_x = 0
            self.x += step_x
            if blocked is not None and blocked(self.x, self.y + step_y, radius):
                step_y = 0
            self.y += step_y

        self._separate(crowd, blocked, radius)

        damage = 0
        # A detonator never swings: its whole attack is the blast the world sets off for it.
        swings = not self.kind.detonate and (not self.kind.ranged or cornered)
        if swings and self.attack_token and dist < self.melee_reach * 10:
            if self.start_attack_anim(dist):
                damage = round(self.kind.damage * damage_mult)

        # atan2(dy, dx) measures from the x-axis; sprites face up, so rotate a quarter turn
        self.orientation += math.pi / 2

        self.update_attack_anim(dt)
        return damage

    def draw(self, screen, camera: Camera):
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        self._draw_charge_telegraph(screen, screen_x, screen_y)
        self._draw_fuse_telegraph(screen, screen_x, screen_y)
        body_color = self.flash_color(self.kind.color)
        if self.fusing:
            body_color = self._fuse_color(body_color)
        draw_monster(
            screen,
            screen_x,
            screen_y,
            self.kind.size,
            body_color,
            self.orientation,
            self.kind.shape,
            attack_progress=self.attack_progress,
            attack_hand=self.attack_hand,
            weapon=self.kind.weapon,
            eye_color=self.kind.eye_color,
            aggro=self.aggro,
            phase=self.art_phase,
            nock=self.shot_readiness,
            walk=self.gait.step(self.x, self.y),
        )
        bar_width, bar_height = 60, 8
        self.draw_health_bar(
            screen,
            screen_x - bar_width // 2,
            screen_y + self.kind.size // 2 + 10,
            bar_width,
            bar_height,
            self.kind.color,
            2,
        )

    def _fuse_color(self, color) -> tuple:
        """The body whitening out as the fuse burns, faster the closer it is to going off.
        The ring says where the blast reaches; this says when."""
        beat = (math.sin(pygame.time.get_ticks() / (140 - 90 * self.fuse_progress)) + 1) / 2
        mix = (0.3 + 0.7 * self.fuse_progress) * beat
        return tuple(round(channel + (255 - channel) * mix) for channel in color[:3])

    def _draw_fuse_telegraph(self, screen, screen_x, screen_y):
        """The ground a lit detonator is about to take with it: the outer ring is exactly the
        radius the blast is applied over, and the filled disc closing on it is the fuse."""
        if not self.fusing:
            return
        center = (round(screen_x), round(screen_y))
        radius = round(c.Creeper.RADIUS)
        pygame.draw.circle(screen, (190, 80, 55), center, radius, 2)
        pygame.draw.circle(screen, (255, 170, 60), center, max(2, round(radius * self.fuse_progress)), 3)

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
