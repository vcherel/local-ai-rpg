from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.utils import frames
from game.entities.entities import Gait
from game.entities.wander import Wander

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player


def pick_critter_kind(distance_from_center: float) -> c.CritterKind:
    """Pick a species that lives this far from the world center. Like monsters, the nastier
    animals only turn up once the player has walked out a way, so the fields around the
    starting town stay rabbits and deer."""
    eligible = [k for k in c.CRITTER_KINDS if k.weight and distance_from_center >= k.min_distance]
    if not eligible:
        eligible = [c.CRITTER_KINDS[0]]
    return random.choices(eligible, weights=[k.weight for k in eligible])[0]


class Critter:
    """An animal: wildlife, a village dog, or something with teeth.

    What it does with the player is entirely its kind's `temperament` (see CritterKind).
    A passive one only ever runs, a retaliator answers a blow and then breaks off when it
    is losing, a predator hunts on sight, a guard dog takes its settlement's side. Running
    is a committed sprint on a held heading rather than a scatter, so catching one is a
    question of stamina: the animal is faster than the player until its wind runs out.

    Session-only, like particles or projectiles: never saved, respawned near the player as
    needed, so a dead one simply leaves its drop behind. Village and camp dogs are stood
    back up from their settlement the same way a camp's garrison is.
    """

    def __init__(
        self,
        x,
        y,
        kind: c.CritterKind,
        home: tuple | None = None,
        village_key: str = "",
        camp_id: str = "",
    ):
        self.x = x
        self.y = y
        self.kind = kind
        self.orientation = random.uniform(0, 2 * math.pi)
        self.max_hp = kind.hp
        self.hp = self.max_hp
        self.last_damage_ms = 0
        # Which settlement stood this dog up, so it can be topped back up when the player
        # returns and turned on the player when its village is provoked.
        self.village_key = village_key
        self.camp_id = camp_id
        self.hostile = kind.temperament == "predator" or bool(camp_id)
        self.last_attack_ms = 0
        self.lunge_until_ms = 0
        # Fleeing: the heading it committed to, when the sprint started, and (when wounded)
        # how long it keeps running whatever the distance to the player.
        self.flee_heading: float | None = None
        self.flee_started_ms = 0
        self.bolt_until_ms = 0
        # Held in a bear trap's jaws until this tick. An animal caught in one still turns
        # and still bites whatever comes within reach; it just cannot leave.
        self.rooted_until_ms = 0
        # The shove it is still travelling under, its own copy of the pair every Entity
        # holds, for the same reason it has its own `root`.
        self.kb_vx = 0.0
        self.kb_vy = 0.0
        self.chilled_until_ms = 0
        self.chill_factor = 1.0
        # A dog belongs somewhere and strolls around it; wildlife roams from wherever it
        # happens to be standing, so its anchor moves with it.
        self.anchored = home is not None
        self.home = home if home is not None else (x, y)
        # The walk cycle, read off its own movement when it is drawn. A critter is not an
        # Entity, so it carries its own, exactly as it carries its own `root`.
        self.gait = Gait(x, y)
        # The door it has committed to coming through, its own copy of the one every Entity
        # holds, for the same reason: a hunting dog routes through a doorway like anything else.
        self.door_commit = None
        radius = c.Wildlife.DOG_WANDER_RADIUS if self.anchored else c.Wildlife.WANDER_RADIUS
        self.wander = Wander(kind.wander_speed, radius, c.Wildlife.IDLE_MIN_MS, c.Wildlife.IDLE_MAX_MS)

    @property
    def size(self) -> int:
        return self.kind.size

    @property
    def hit_radius(self) -> float:
        """How far from its centre the animal can be struck. Not `size / 2`: every critter
        is drawn longer than it is wide, and a quadruped runs well past its own size, so
        half the size missed the head, flank and rear of what was plainly on screen."""
        return self.size * self.kind.hit_radius_mult

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def receive_damage(self, damage) -> bool:
        """Apply damage; True if it died."""
        self.hp -= damage
        self.last_damage_ms = pygame.time.get_ticks()
        return self.hp <= 0

    @property
    def dead(self) -> bool:
        """Down and awaiting removal, exactly as `Entity.dead`: a `Critter` is not an
        `Entity`, so it carries its own copy the way it carries its own `root` and `Gait`."""
        return self.hp <= 0

    def aggro(self):
        """Turn on the player: what a struck retaliator does, what a provoked village dog
        does, and what the rest of the pack does when one of them is attacked."""
        if self.kind.damage and self.kind.temperament != "passive":
            self.hostile = True
            self.flee_heading = None

    def root(self, duration_ms: int):
        self.rooted_until_ms = max(self.rooted_until_ms, pygame.time.get_ticks() + duration_ms)

    @property
    def rooted(self) -> bool:
        return pygame.time.get_ticks() < self.rooted_until_ms

    @property
    def staggered(self) -> bool:
        """Still travelling under a shove, so it gets no step of its own this frame."""
        return math.hypot(self.kb_vx, self.kb_vy) > c.Combat.KNOCKBACK_STAGGER_SPEED

    def chill(self, duration_ms: int, factor: float):
        """Slowed by a frost bolt. Its own copy of `Entity.chill` for the same reason it
        has its own `root`: a critter is not an `Entity`."""
        self.chill_factor = min(self.chill_factor, factor) if self.chilled else factor
        self.chilled_until_ms = max(self.chilled_until_ms, pygame.time.get_ticks() + duration_ms)

    @property
    def chilled(self) -> bool:
        return pygame.time.get_ticks() < self.chilled_until_ms

    @property
    def chill_mult(self) -> float:
        return self.chill_factor if self.chilled else 1.0

    def startle(self):
        """Wounded but alive: run flat out for a while, wherever the player is."""
        self.bolt_until_ms = pygame.time.get_ticks() + c.Wildlife.BOLT_DURATION_MS
        if self.flee_heading is None:
            self.flee_started_ms = pygame.time.get_ticks()

    # Deflection angles tried when the heading is blocked, nearest first, so a running
    # animal skirts a wall instead of pressing into it until it happens to slide free.
    _STEER_OFFSETS_DEG = (0, 25, -25, 50, -50, 80, -80, 115, -115, 150, -150)

    def _steer(self, heading, blocked, radius, speed) -> float:
        if blocked is None:
            return heading
        probe = max(speed * 6, radius + 12)
        for offset_deg in self._STEER_OFFSETS_DEG:
            angle = heading + math.radians(offset_deg)
            if not blocked(self.x + math.cos(angle) * probe, self.y + math.sin(angle) * probe, radius):
                return angle
        return heading

    def _step(self, angle, speed, radius, blocked):
        # Everything an animal does with its legs comes through here, so a trap holding it
        # and a shove still carrying it are one check each: it still faces where it was
        # going, it just doesn't get there under its own power.
        if self.rooted or self.staggered:
            self.orientation = angle
            return
        step_x, step_y = math.cos(angle) * speed, math.sin(angle) * speed
        if blocked is not None and blocked(self.x + step_x, self.y, radius):
            step_x = 0
        self.x += step_x
        if blocked is not None and blocked(self.x, self.y + step_y, radius):
            step_y = 0
        self.y += step_y
        self.orientation = angle

    def update(
        self, player: Player, dt, blocked=None, damage_mult: float = 1.0, waypoint=None, terrain_mult: float = 1.0
    ):
        radius = self.size / 2
        # An animal in water is slowed like everything else: a deer that bolts across a
        # river is easier to catch there than on the bank, which is the point of the bank.
        move_factor = frames(dt) * terrain_mult * self.chill_mult
        now = pygame.time.get_ticks()
        dist = self.distance_to_point((player.x, player.y))

        if self._should_hunt(dist, now):
            self._hunt(player, dist, move_factor, radius, blocked, damage_mult, waypoint, now)
            return

        if self._fleeing(dist, now):
            self._flee(player, move_factor, radius, blocked, now)
            return

        self.flee_heading = None
        if self.rooted or self.staggered:
            return
        anchor = self.home if self.anchored else (self.x, self.y)
        moved_angle = self.wander.step(self, dt * terrain_mult, anchor, radius, blocked)
        if moved_angle is not None:
            self.orientation = moved_angle

    def _should_hunt(self, dist, now) -> bool:
        """Whether it is coming for the player this frame. A predator or a guard dog is
        always willing but only acts on what it can sense; a retaliator that has been beaten
        past `BREAK_OFF_HP_FRAC` gives up for good and runs instead."""
        if not self.hostile:
            return False
        if self.kind.temperament == "retaliate" and self.hp <= self.max_hp * c.Wildlife.BREAK_OFF_HP_FRAC:
            self.hostile = False
            self.bolt_until_ms = now + c.Wildlife.BOLT_DURATION_MS
            return False
        leash = self.kind.detection * (2 if self.kind.temperament == "retaliate" else 1)
        return dist <= leash

    def _hunt(self, player: Player, dist, move_factor, radius, blocked, damage_mult, waypoint, now):
        """Close on the player and bite on a cooldown."""
        if dist > self.kind.attack_range:
            target = waypoint if waypoint is not None else (player.x, player.y)
            heading = math.atan2(target[1] - self.y, target[0] - self.x)
            speed = self.kind.wander_speed * self.kind.chase_speed * move_factor
            self._step(self._steer(heading, blocked, radius, speed), speed, radius, blocked)
            return

        self.orientation = math.atan2(player.y - self.y, player.x - self.x)
        if now - self.last_attack_ms < self.kind.attack_cooldown_ms:
            return
        self.last_attack_ms = now
        self.lunge_until_ms = now + 180
        player.receive_damage(round(self.kind.damage * damage_mult), source=self)

    def _fleeing(self, dist, now) -> bool:
        """True while it should be running: wounded, or the player is inside the distance
        this species tolerates. A predator or an angry dog never gets here."""
        if now < self.bolt_until_ms:
            return True
        if dist < self.kind.flee_distance:
            return True
        # Still winded from the last sprint: keep going rather than stopping dead in front
        # of whatever it was running from.
        return self.flee_heading is not None and now - self.flee_started_ms < self.kind.stamina_ms

    def _flee(self, player: Player, move_factor, radius, blocked, now):
        """Sprint away on a held heading. The heading only bends `FLEE_TURN_RATE_DEG` a frame
        towards straight-away-from-the-player, which is what turns the old on-the-spot
        jitter into an animal that actually pulls away in a line."""
        away = math.atan2(self.y - player.y, self.x - player.x)
        if self.flee_heading is None:
            self.flee_heading = away + random.uniform(-0.35, 0.35)
            self.flee_started_ms = now
        else:
            delta = (away - self.flee_heading + math.pi) % (2 * math.pi) - math.pi
            limit = math.radians(c.Wildlife.FLEE_TURN_RATE_DEG)
            self.flee_heading += max(-limit, min(limit, delta))

        spent = now - self.flee_started_ms
        sprint = self.kind.wander_speed * self.kind.sprint_mult
        speed = (sprint if spent < self.kind.stamina_ms else sprint * c.Wildlife.TIRED_MULT) * move_factor
        self.flee_heading = self._steer(self.flee_heading, blocked, radius, speed)
        self._step(self.flee_heading, speed, radius, blocked)
        # Fleeing resets the wander state, so it picks a fresh spot once it settles.
        self.wander.interrupt()
        if spent > self.kind.stamina_ms + c.Wildlife.RECOVER_MS:
            self.flee_heading = None

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        size = self.size
        color = self.kind.color
        # Flashes white for a moment after a hit, the same read as any other wounded thing.
        if self.last_damage_ms and pygame.time.get_ticks() - self.last_damage_ms < c.Entities.FLASH_MS:
            color = c.Colors.WHITE
        shade = tuple(max(0, v - 45) for v in color)
        # A biting animal throws itself forward for a moment, which is the only tell that
        # the blow came from it and not from whatever else is on screen.
        if pygame.time.get_ticks() < self.lunge_until_ms:
            sx += math.cos(self.orientation) * size * 0.3
            sy += math.sin(self.orientation) * size * 0.3

        def at(forward, side):
            """Point (forward, side) in the critter's own space, in screen coordinates."""
            cos_o, sin_o = math.cos(self.orientation), math.sin(self.orientation)
            return (
                round(sx + cos_o * forward * size - sin_o * side * size),
                round(sy + sin_o * forward * size + cos_o * side * size),
            )

        walk = self.gait.step(self.x, self.y)
        if self.kind.shape == "quadruped":
            self._draw_quadruped(screen, at, color, shade, size, walk)
        else:
            self._draw_small(screen, at, color, shade, size, sx, sy, walk)
        self._draw_health(screen, sx, sy, size)

    def _draw_small(self, screen, at, color, shade, size, sx, sy, walk: float = 0.0):
        # A rabbit does not walk, it hops: the body lifts with the stride and the head keeps
        # its place, which from above is the whole of the animation.
        sy -= walk * walk * size * 0.12
        body = pygame.Rect(0, 0, round(size * 1.3), round(size * 0.85))
        body.center = (round(sx), round(sy))
        pygame.draw.ellipse(screen, color, body)
        pygame.draw.ellipse(screen, shade, body, 1)
        head = at(0.7, 0)
        pygame.draw.circle(screen, color, head, round(size * 0.35))

        if self.kind.name == "rabbit":
            for side in (-1, 1):
                pygame.draw.line(screen, color, head, at(1.1, side * 0.25), 3)
        elif self.kind.name == "fox":
            pygame.draw.circle(screen, (230, 230, 225), at(-0.9, 0), round(size * 0.3))
        elif self.kind.name == "badger":
            # The white stripe down the mask is the whole point of a badger from above.
            pygame.draw.line(screen, (240, 240, 235), at(0.45, 0), at(0.95, 0), 3)

    def _draw_quadruped(self, screen, at, color, shade, size, walk: float = 0.0):
        """Deer, boar, dog and bear all stand on legs and are longer than they are wide, so
        they can't be drawn as one blob the way the small critters are: from this far up a
        plain ellipse with two lines off the front reads as a snail rather than an animal.

        `walk` carries the feet: diagonal pairs move together and opposite pairs against each
        other, which is how a four-legged animal actually crosses the ground and the one thing
        that separates a deer trotting away from a deer being dragged."""
        # Hooves/paws first, so they poke out from under the flank rather than sit on top.
        for forward, splay, lead in ((0.34, 0.46, 1), (-0.38, -0.52, -1)):
            for side in (-1, 1):
                step = walk * c.Entities.GAIT_LEG * lead * side
                pygame.draw.line(screen, shade, at(forward, side * 0.26), at(splay + step, side * 0.5), 3)

        flank = [at(0.5, -0.28), at(0.5, 0.28), at(-0.55, 0.32), at(-0.72, 0.14), at(-0.72, -0.14), at(-0.55, -0.32)]
        pygame.draw.polygon(screen, color, flank)
        pygame.draw.polygon(screen, shade, flank, 1)

        pygame.draw.line(screen, color, at(0.42, 0), at(0.88, 0), max(3, round(size * 0.18)))  # neck
        head = at(0.95, 0)
        pygame.draw.circle(screen, color, head, round(size * 0.2))
        pygame.draw.circle(screen, shade, head, round(size * 0.2), 1)
        pygame.draw.circle(screen, shade, at(1.1, 0), max(2, round(size * 0.1)))  # muzzle

        if self.kind.name == "deer":
            # Antlers: a beam sweeping forward off the brow with a tine on each.
            antler = (60, 44, 28)
            for side in (-1, 1):
                brow, tip = at(1.0, side * 0.12), at(1.32, side * 0.46)
                pygame.draw.line(screen, antler, brow, tip, 2)
                pygame.draw.line(screen, antler, at(1.16, side * 0.29), at(1.1, side * 0.58), 2)
                pygame.draw.line(screen, antler, tip, at(1.5, side * 0.34), 2)
            pygame.draw.circle(screen, (235, 232, 220), at(-0.76, 0), max(2, round(size * 0.13)))  # tail
        elif self.kind.name == "boar":
            for side in (-1, 1):  # tusks curling up out of the snout
                pygame.draw.line(screen, (235, 228, 205), at(1.05, side * 0.1), at(1.3, side * 0.22), 2)
            pygame.draw.line(screen, shade, at(0.1, 0), at(-0.3, 0), max(2, round(size * 0.12)))  # bristled back
        elif self.kind.name == "bear":
            for side in (-1, 1):  # small round ears, the bear's whole silhouette from above
                pygame.draw.circle(screen, shade, at(0.9, side * 0.24), max(2, round(size * 0.11)))
        else:  # dog and wild dog: pricked ears and a tail
            for side in (-1, 1):
                pygame.draw.line(screen, shade, at(0.92, side * 0.16), at(1.05, side * 0.34), 2)
            pygame.draw.line(screen, color, at(-0.7, 0), at(-1.0, 0.18), 3)

    def _draw_health(self, screen, sx, sy, size):
        """A wounded animal carries a small bar, so a fight with something that bites back
        reads like any other fight. Untouched wildlife carries nothing."""
        if self.hp >= self.max_hp:
            return
        width, height = round(size * 1.6), 4
        x, y = round(sx - width / 2), round(sy - size * 1.1)
        pygame.draw.rect(screen, (40, 30, 30), (x, y, width, height))
        fill = max(0, round(width * self.hp / self.max_hp))
        pygame.draw.rect(screen, c.Colors.RED if self.hostile else (150, 190, 110), (x, y, fill, height))
