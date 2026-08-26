import math
import random
from collections import OrderedDict

import pygame

import core.constants as c
from core.status_fx import draw_bubbles
from core.utils import frames
from game.entities.gear import draw_accessory, draw_armor_band, draw_shield, draw_weapon, gear_padding


class Gait:
    """The walk cycle, shared by everything in the world that moves on legs.

    Advanced by the ground actually covered rather than by the clock, which is the whole
    trick: a rooted thing, a monster wading a river, a villager pinned against a wall and a
    corpse all stop animating for free, and nothing needs to be told how fast it is going.
    One number in (where it is now), one number out (how far through the stride it is,
    -1 to 1), so the arms, the legs and the bob all read the same walk.
    """

    def __init__(self, x, y):
        self.phase = random.uniform(0, 2 * math.pi)
        self.amount = 0.0
        self._x, self._y = x, y

    def step(self, x, y) -> float:
        moved = math.hypot(x - self._x, y - self._y)
        self._x, self._y = x, y
        self.phase = (self.phase + moved / c.Entities.GAIT_STRIDE * 2 * math.pi) % (2 * math.pi)
        # Eased rather than switched, so coming to a halt settles the arms instead of
        # freezing them wherever the last frame left them.
        walking = 1.0 if moved > c.Entities.GAIT_DEADZONE else 0.0
        self.amount += (walking - self.amount) * c.Entities.GAIT_EASE
        return math.sin(self.phase) * self.amount


class Entity:
    def __init__(self, x, y, color, size, hp, max_hp):
        self.x = x
        self.y = y
        self.orientation = random.uniform(0, 2 * math.pi)
        self.color = color
        self.size = size
        self.hp = hp
        self.max_hp = max_hp
        self.attack_in_progress = False
        self.attack_progress = 0.0
        self.attack_hand = "left"
        self.last_damage_ms = 0
        # Held where it stands until this tick (a bear trap's jaws, the only thing that
        # roots). Session-only and shared by everything that moves, since the trap does not
        # care what it caught: whoever is rooted still turns, still swings, still bleeds.
        self.rooted_until_ms = 0
        self.root_span_ms = 0
        # Slowed rather than held: a frost staff's bolt leaves whatever it touched walking
        # at `chill_mult` of its pace until this tick. Read by every mover the same way
        # `rooted` is, and deliberately never a stop, since a bear trap is the only thing
        # in the world that takes movement away entirely.
        self.chilled_until_ms = 0
        self.chill_factor = 1.0
        # The walk cycle. Read once per frame by whatever draws this thing, from its own
        # movement, so nothing has to remember to keep it turning.
        self.gait = Gait(x, y)
        # The shove it is still travelling under, in pixels per 60fps frame. A blow hands
        # over an impulse rather than a new position (`apply_impulse`), and it is spent one
        # frame at a time by `advance_impulse` like any other movement, walls included.
        self.kb_vx = 0.0
        self.kb_vy = 0.0
        # The id of the door this one has committed to walking through (World._door_goal),
        # dropped once it is on the same side of the wall as whatever it is chasing. Without
        # it the goal flips between the doorstep and the threshold as the body crosses, and
        # the chaser shivers in the gap instead of coming through.
        self.door_commit = None
        # The corner of an obstacle this one is currently walking round (World._detour_corner),
        # dropped the moment nothing stands between it and what it is chasing. `door_commit`
        # for the open ground: both ways round a wall cost the same from the middle of it,
        # and a body that re-decides every frame rocks on the spot instead of walking.
        self.route_corner = None

    def root(self, duration_ms: int):
        now = pygame.time.get_ticks()
        self.rooted_until_ms = max(self.rooted_until_ms, now + duration_ms)
        # How long the hold was when it was put on, kept fixed so working it shorter shows
        # as the bar emptying rather than as the same bar over a shorter clock.
        self.root_span_ms = max(self.root_span_ms if self.rooted else 0, self.rooted_until_ms - now)

    @property
    def rooted(self) -> bool:
        return pygame.time.get_ticks() < self.rooted_until_ms

    @property
    def root_progress(self) -> float:
        """How much of the hold is left, 1 just caught to 0 free. What the struggle bar over
        a caught player draws, so working a leg loose is visible rather than felt."""
        if self.root_span_ms <= 0 or not self.rooted:
            return 0.0
        return min(1.0, (self.rooted_until_ms - pygame.time.get_ticks()) / self.root_span_ms)

    def shorten_root(self, ms: int) -> bool:
        """Work a foot loose by that much, never past free. False when nothing is holding
        this one, so a caller can tell a struggle from a keypress into thin air."""
        if not self.rooted:
            return False
        self.rooted_until_ms = max(pygame.time.get_ticks(), self.rooted_until_ms - ms)
        return True

    def chill(self, duration_ms: int, factor: float):
        """Slow this thing down for a while. A fresh chill takes the harsher of the two
        factors and the later of the two deadlines, so shooting something twice never
        leaves it faster than one bolt would have."""
        self.chill_factor = min(self.chill_factor, factor) if self.chilled else factor
        self.chilled_until_ms = max(self.chilled_until_ms, pygame.time.get_ticks() + duration_ms)

    @property
    def chilled(self) -> bool:
        return pygame.time.get_ticks() < self.chilled_until_ms

    @property
    def chill_mult(self) -> float:
        return self.chill_factor if self.chilled else 1.0

    def status_effects(self) -> list:
        """Which status bubbles float over this body right now, worst first.

        The base pair is what every mover can catch; a kind that carries more of its own
        (a monster burning, the player's flasks) extends this rather than replacing it.
        """
        effects = []
        if self.rooted:
            effects.append("root")
        if self.chilled:
            effects.append("chill")
        return effects

    # How far over the head the bubbles float. Raised by anything that already flies a
    # marker up there (a villager's badge), so the two never sit on each other.
    STATUS_BUBBLE_LIFT = 26

    def draw_status_bubbles(self, screen, x, y, size):
        draw_bubbles(screen, x, y - size // 2 - self.STATUS_BUBBLE_LIFT, self.status_effects())

    @property
    def staggered(self) -> bool:
        """Still travelling under a shove hard enough that it is not walking anywhere of its
        own accord this frame. It still turns, still swings, still bleeds: what it has lost
        is its footing, which is the follow-through the impulse is worth."""
        return math.hypot(self.kb_vx, self.kb_vy) > c.Combat.KNOCKBACK_STAGGER_SPEED

    def receive_damage(self, damage):
        """Returns True if the entity died"""
        self.hp -= damage
        self.last_damage_ms = pygame.time.get_ticks()
        return self.hp <= 0

    @property
    def dead(self) -> bool:
        """Down and awaiting removal from whatever list holds it.

        A blow can be resolved against something already killed earlier in the same frame
        (a cleave and the explosion it set off, an arrow arriving after the swing that
        finished the target), and every death path ends in a `list.remove`, which raises
        the second time. Everything that resolves a hit checks this first, so a corpse
        takes no further damage, drops no second purse and is removed exactly once."""
        return self.hp <= 0

    def flash_color(self, color):
        """Blend toward white briefly after taking a hit, for visual feedback."""
        if not self.last_damage_ms:
            return color
        elapsed = pygame.time.get_ticks() - self.last_damage_ms
        if elapsed >= c.Entities.FLASH_MS:
            return color
        t = (1 - elapsed / c.Entities.FLASH_MS) * 0.75
        return tuple(int(comp + (255 - comp) * t) for comp in color)

    def distance_to_point(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])

    def start_attack_anim(self, hand=None):
        """`hand` forces which arm swings, so a visible weapon animates in the hand holding it."""
        if not self.attack_in_progress:
            self.attack_in_progress = True
            self.attack_progress = 0.0
            self.attack_hand = hand or random.choice(["left", "right"])

    def update_attack_anim(self, dt, speed_mult=1.0):
        if self.attack_in_progress:
            self.attack_progress += dt * c.Entities.SWING_SPEED * speed_mult
            if self.attack_progress >= 1.0:
                self.attack_progress = 0.0
                self.attack_in_progress = False

    def draw_health_bar(self, screen, x, y, width, height, color, border_width):
        pygame.draw.rect(screen, c.Colors.MENU_BACKGROUND, (x, y, width, height))
        ratio = max(self.hp / self.max_hp, 0)
        pygame.draw.rect(screen, color, (x, y, width * ratio, height))
        pygame.draw.rect(screen, c.Colors.BORDER, (x, y, width, height), border_width)

    def draw(
        self,
        screen,
        x,
        y,
        size,
        color,
        angle=0.0,
        attack_progress=0.0,
        attack_hand=None,
        gear=None,
        health_bar=True,
    ):
        """`health_bar` off leaves the bar to the caller, which is how the player's own bar
        is kept out of this pass and drawn over the canopies instead, and how the title
        screen's village shows a street of people with no HUD floating under them."""
        walk = self.gait.step(self.x, self.y)
        draw_human(screen, x, y, size, self.flash_color(color), angle, attack_progress, attack_hand, gear, walk)

        if health_bar:
            self.draw_health_bar(
                screen,
                x - c.Entities.HEALTH_BAR_WIDTH // 2,
                y + size // 2 + c.Entities.HEALTH_BAR_OFFSET,
                c.Entities.HEALTH_BAR_WIDTH,
                c.Entities.HEALTH_BAR_HEIGHT,
                color,
                c.Entities.HEALTH_BAR_BORDER,
            )
            self.draw_status_bubbles(screen, x, y, size)


# Bodies drawn from a kept sprite, bounded because a crowd carries one each: the least
# recently asked for goes when it is full. A swing is stepped this finely through its arc,
# which is finer than the few frames one lasts.
_SPRITE_CACHE: OrderedDict = OrderedDict()
_SPRITE_CACHE_MAX = 160
_ATTACK_STEPS = 16


# How far a shove is allowed to carry a body between two collision tests.
KNOCKBACK_STEP = 8.0


def step_along(body, step_x: float, step_y: float, blocked, radius: float) -> tuple[float, float]:
    """Move `body` by (step_x, step_y), one axis at a time. Returns the step actually taken.

    Testing the axes separately is what lets a wall on one of them stop that axis and leave
    the other running, so a body walking into a house slides along its front instead of
    grinding to a halt against it. The one definition of that, shared by everything that
    walks: the player, villagers, monsters and animals all move by it, so a change to how a
    wall is met is a change in one place.

    What comes back is what was left of the step after the walls took their share, which is
    how a wanderer knows it is grinding against something and should pick somewhere else to
    stroll to (`Wander.step`). Everything else just moves and ignores it.

    A free function rather than an `Entity` method because a `Critter` is not an Entity and
    still has to walk, the same reason `push_apart` and `advance_impulse` are free.
    """
    if blocked is not None and blocked(body.x + step_x, body.y, radius):
        step_x = 0
    body.x += step_x
    if blocked is not None and blocked(body.x, body.y + step_y, radius):
        step_y = 0
    body.y += step_y
    return step_x, step_y


def step_towards(body, angle: float, speed: float, blocked, radius: float) -> tuple[float, float]:
    """`step_along` for the callers that have a heading and a pace rather than a vector."""
    return step_along(body, math.cos(angle) * speed, math.sin(angle) * speed, blocked, radius)


def apply_impulse(body, kb_dir, distance: float):
    """Hand a body the velocity a shove is worth instead of moving it there.

    A blow used to teleport its target the whole way at once, which is why the pole, the
    weapon whose entire job is moving people, had nothing to show for it. The impulse is
    sized so the body coasts exactly `distance` as it decays (a geometric series summing to
    v0 / (1 - decay)), and it is spent frame by frame through `advance_impulse` with the
    same collision every step takes, so a shove into a wall stops at the wall.

    Impulses add rather than replace: two blows landing at once throw somebody twice as far.
    """
    if not kb_dir or distance <= 0:
        return
    speed = distance * (1.0 - c.Combat.KNOCKBACK_DECAY)
    body.kb_vx += kb_dir[0] * speed
    body.kb_vy += kb_dir[1] * speed


def advance_impulse(body, dt, radius: float, blocked=None) -> bool:
    """Spend one frame of whatever shove a body is under. True while it is still moving.

    Walked out in hops no longer than KNOCKBACK_STEP for the reason a projectile is: testing
    only where the shove ends puts the body on the far side of a thin wall, and a pole shoves
    things far enough for that to be most of a room."""
    speed = math.hypot(body.kb_vx, body.kb_vy)
    if speed <= c.Combat.KNOCKBACK_REST_SPEED:
        body.kb_vx = body.kb_vy = 0.0
        return False
    step = frames(dt)
    step_x, step_y = body.kb_vx * step, body.kb_vy * step
    hops = max(1, math.ceil(math.hypot(step_x, step_y) / KNOCKBACK_STEP))
    hop_x, hop_y = step_x / hops, step_y / hops
    for _ in range(hops):
        moved = False
        if blocked is None or not blocked(body.x + hop_x, body.y, radius):
            body.x += hop_x
            moved = True
        if blocked is None or not blocked(body.x, body.y + hop_y, radius):
            body.y += hop_y
            moved = True
        if not moved:
            # Into a wall: the shove is spent there rather than grinding along it.
            body.kb_vx = body.kb_vy = 0.0
            return False
    decay = c.Combat.KNOCKBACK_DECAY**step
    body.kb_vx *= decay
    body.kb_vy *= decay
    return True


def push_apart(body, crowd, radius: float, radius_of, blocked=None):
    """Shove a body out of anything standing in the same place as it.

    Chasers stop moving the moment they are in reach, which is exactly when they pile into
    one body; this runs whether they are walking or swinging, so the pile comes apart on its
    own. Shared by a pack of monsters and by an angry village's mob, because a dozen
    villagers stacked on one pixel is the same problem as a dozen wolves: `radius_of` is all
    that differs between them.

    One held in a trap is not shoved out of it: the jaws are what keep it there, and the
    crowd piling in behind would otherwise carry it free."""
    if not crowd or body.rooted:
        return
    push_x = push_y = 0.0
    for other in crowd:
        if other is body:
            continue
        dx, dy = body.x - other.x, body.y - other.y
        gap = math.hypot(dx, dy)
        overlap = radius + radius_of(other) - gap
        if overlap <= 0:
            continue
        if gap < 1e-6:
            # Exactly on top of each other: shove along its own bearing rather than
            # dividing by nothing.
            dx, dy, gap = math.cos(body.slot_angle), math.sin(body.slot_angle), 1.0
        push_x += dx / gap * overlap * c.Entities.SEPARATION_PUSH
        push_y += dy / gap * overlap * c.Entities.SEPARATION_PUSH
    if push_x == 0.0 and push_y == 0.0:
        return
    if blocked is None or not blocked(body.x + push_x, body.y, radius):
        body.x += push_x
    if blocked is None or not blocked(body.x, body.y + push_y, radius):
        body.y += push_y


def _gear_key(gear: dict | None):
    """A gear dict as something hashable. Every value in one is a colour, a name or a flag,
    so the dict is its own key once it is flattened."""
    if not gear:
        return None
    return tuple(sorted((slot, tuple(sorted(spec.items()))) for slot, spec in gear.items()))


def _body_sprite(size, color, attack_progress, attack_hand, gear, arm_swing, key):
    """One body drawn facing up its own surface: the circle, what it is wearing, its two
    arms wherever the stride and the swing have put them, and whatever each hand holds.

    Kept, because it is the same handful of circles frame after frame: what really changes
    as somebody walks past is which way they are facing, and that is a rotation of the
    finished sprite rather than a different sprite."""
    sprite = _SPRITE_CACHE.get(key)
    if sprite is not None:
        _SPRITE_CACHE.move_to_end(key)
        return sprite

    border_thickness = 2
    arm_radius = size // 3.5
    extra_space = arm_radius * 2

    # Make surface larger to accommodate rotation
    base_width = size + border_thickness * 2 + extra_space * 2
    base_height = size + border_thickness * 2

    # Add padding for rotation (diagonal of the surface)
    padding = int(math.sqrt(base_width**2 + base_height**2) - min(base_width, base_height)) // 2 + 10
    # A held weapon sticks out well past the body, so it needs room on the sprite surface.
    if gear:
        padding += gear_padding(gear, size)

    char_surf = pygame.Surface((base_width + padding * 2, base_height + padding * 2), pygame.SRCALPHA)

    x_offset = extra_space + padding
    y_offset = padding

    body_center = (x_offset + size // 2 + border_thickness, y_offset + size // 2 + border_thickness)
    pygame.draw.circle(char_surf, c.Colors.BLACK, body_center, size // 2 + border_thickness)
    pygame.draw.circle(char_surf, color, body_center, size // 2)

    if gear and gear.get("armor"):
        draw_armor_band(char_surf, body_center, size, gear["armor"]["color"], gear["armor"]["outline"])
    if gear and gear.get("accessory"):
        draw_accessory(char_surf, body_center, size, gear["accessory"]["color"], gear["accessory"]["outline"])

    arm_y = y_offset + (size + border_thickness * 2) // 3.5
    distance_arm = 10

    def draw_arm(cx, cy):
        pygame.draw.circle(char_surf, c.Colors.BLACK, (cx, cy), arm_radius)
        pygame.draw.circle(char_surf, color, (cx, cy), arm_radius - border_thickness)

    # Forward is up in the sprite's own space, so a stride carries one arm up the surface
    # and the other down it. Opposite arms, like anything that walks on two legs.
    left_arm_x = padding + arm_radius + distance_arm
    left_arm_y = arm_y
    if attack_hand == "left":
        left_arm_x += int(attack_progress * 15)
        left_arm_y -= int(attack_progress * 15)
    else:
        left_arm_y -= arm_swing
    draw_arm(left_arm_x, left_arm_y)

    right_arm_x = base_width + padding - arm_radius - distance_arm
    right_arm_y = arm_y
    if attack_hand == "right":
        right_arm_x -= int(attack_progress * 15)
        right_arm_y -= int(attack_progress * 15)
    else:
        right_arm_y += arm_swing
    draw_arm(right_arm_x, right_arm_y)

    # The shield is worn on the offhand side of the body rather than held, so it goes on
    # before the hands: what that arm is holding is drawn over it.
    if gear and gear.get("offhand"):
        draw_shield(char_surf, body_center, gear["offhand"], size)

    # One weapon per hand, and a hand with nothing in it is simply not drawn holding
    # anything: bare hands are a loadout the player can choose, not a missing sprite.
    # Hand one is the right arm (the left mouse button), hand two the left.
    hands = (("hand2", "left", (left_arm_x, left_arm_y)), ("hand1", "right", (right_arm_x, right_arm_y)))
    for slot, hand, arm in hands:
        spec = gear.get(slot) if gear else None
        if spec is None or not spec.get("kind"):
            continue
        swing = attack_progress if attack_hand == hand else 0.0
        draw_weapon(char_surf, arm, spec, size, hand, swing)

    _SPRITE_CACHE[key] = char_surf
    if len(_SPRITE_CACHE) > _SPRITE_CACHE_MAX:
        _SPRITE_CACHE.popitem(last=False)
    return char_surf


def draw_human(
    surface: pygame.Surface,
    x: int,
    y: int,
    size: int,
    color: tuple,
    angle: float,
    attack_progress: float = 0.0,
    attack_hand: str | None = None,
    gear: dict | None = None,
    walk: float = 0.0,
):
    """`walk` is how far through the stride this body is (game/entities/entities.py `Gait`):
    the arms swing fore and aft with it and the whole sprite lifts a little at each step, so
    a person crossing a field reads as walking rather than sliding. The arm mid attack keeps
    its swing: what it is doing matters more than where it is in its stride."""
    # The stride is stepped to whole pixels of arm swing and a swing to a sixteenth of its
    # arc, so a street of people is a handful of sprites rather than one per body per frame.
    # Both steps are finer than the animation they carry, and both are what the sprite is
    # drawn from as well as what it is keyed on: nothing is drawn away from where it was
    # asked to be, it is asked for in whole steps.
    arm_swing = round(walk * c.Entities.GAIT_ARM)
    attack_progress = round(attack_progress * _ATTACK_STEPS) / _ATTACK_STEPS if attack_hand else 0.0
    key = (size, color, attack_progress, attack_hand, _gear_key(gear), arm_swing)
    char_surf = _body_sprite(size, color, attack_progress, attack_hand, gear, arm_swing, key)

    if angle != 0:
        char_surf = pygame.transform.rotate(char_surf, math.degrees(-angle))

    # The body lifts at each step. Applied after the rotation, so it is a bob on the screen
    # rather than a slide along whatever way the sprite happens to be facing. Squared rather
    # than absolute: |sin| has a corner at every zero crossing, which is a jolt twice a
    # stride, where sin squared rises and falls smoothly through the same two peaks.
    bob = walk * walk * c.Entities.GAIT_BOB
    rect = char_surf.get_rect(center=(x, y - bob))
    surface.blit(char_surf, rect)
