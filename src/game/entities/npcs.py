from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.text_fx import draw_outlined_text
from core.utils import frames, random_color
from game.entities.entities import Entity, push_apart, step_towards
from game.entities.items import AMMO_BUNDLE, Item, item_type_from_name, rarity_tier, roll_bonus, roll_rarity
from game.entities.wander import Wander
from game.quest import Quest

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player
    from llm.name_generator import NPCNameGenerator

# How the NPC feels about the player, worst first: the prompt hint fed to their dialogue and
# the dot drawn by their name. One ladder, so the two can't drift apart.
AFFINITY_TIERS = (
    (20, "You dislike the player and are cold, curt, or suspicious of them. ", (200, 60, 60)),
    (40, "You are wary of the player and not particularly warm towards them. ", (200, 140, 60)),
    (60, "", (180, 180, 180)),
    (80, "You like the player and are warm and friendly towards them. ", (120, 200, 120)),
    (
        None,
        "You consider the player a close friend and are especially warm, generous, and open with them. ",
        (255, 200, 60),
    ),
)


class NPC(Entity):
    def __init__(self, x, y):
        super().__init__(x, y, random_color(), c.Entities.NPC_SIZE, c.Entities.NPC_HP, c.Entities.NPC_HP)
        self.name = None
        self.quest: Quest | None = None
        self.is_merchant = False
        # True for an NPC spawned to hold a recover_stolen quest's item; shows a marker
        # so the player can spot them without already knowing where to look.
        self.is_thief = False
        self.shop_items: list[Item] = []
        self.shop_prices: dict[str, int] = {}
        self.shop_ready = False
        # When this merchant next puts new wares out (wall clock, like every other deadline
        # in the world, so quitting is not a way of skipping the wait). What is already on
        # the shelf stays: a restock is a delivery, not a new shop.
        self.restock_at = 0.0
        self.home = (x, y)
        self.wander = Wander(
            c.Entities.NPC_WANDER_SPEED,
            c.Entities.NPC_WANDER_RADIUS,
            c.Entities.NPC_IDLE_MIN_MS,
            c.Entities.NPC_IDLE_MAX_MS,
        )
        self.affinity = c.Affinity.START
        # Turned on the player, along with the rest of their village (World.provoke_village).
        # A hostile villager stops wandering, stops trading and comes at the player with
        # whatever is to hand. Anger is a countdown (wall clock, so quitting can't wait it
        # out for free) rather than a state: a scuffle is lived down. A killing is not, and
        # sets `grudge` instead, which no clock ever clears (World.hold_grudge).
        self.hostile_until = 0.0
        self.grudge = False
        self.attack_ready_ms = 0
        # A mob surrounds the player the way a pack does: each of them holds its own bearing
        # around whoever they are fighting (World.assign_surround_slots), and only a few may
        # swing at once. The rest close the circle. Nobody in a village is a tactician; a
        # dozen of them standing in a ring is simply what a dozen angry people look like.
        self.slot_angle = random.uniform(0, 2 * math.pi)
        self.attack_token = True
        # The next stone this one may throw, for those who keep their distance instead.
        self.next_stone_ms = 0
        # Until when this one is looking down whatever they just put in the air. Aiming and
        # facing are the same act (`aim_at`), and this is what stops the ordinary wander
        # and greet turning the body back the other way while the shot is still leaving it.
        self.aim_until_ms = 0
        # The shout hanging over this one's head after the player's first offence: they are
        # warning the player rather than fighting them, and the village is still calm. Set
        # by `warn`, worn for `Villages.WARNING_MS`, and never saved: a warning is the
        # moment, the strike it recorded is what the village remembers (World.village_strikes).
        self.warned_until_ms = 0
        # Cut down and done fighting, in whichever way this one answers for
        # (`Villages.ROUT_HP_FRAC`). Someone who took up arms for the place falls back
        # shouting, and the shout is spent once (`called_help`). Everyone else yields: they
        # drop what they are holding and kneel under a white flag until this runs out, and
        # while it does they are nobody's enemy, not even their own village's. Neither is
        # saved: a fight is a moment, and what a village remembers is its anger.
        self.surrender_until = 0.0
        self.called_help = False
        # Whether this one has already thrown down their weapon once. Nobody yields twice:
        # once they are back on their feet they run for a door like anyone else, which is
        # what stops a surrender being a farmer kneeling on a loop.
        self.yielded = False
        # Where this one stood last frame, and how long they have meant to move without
        # managing it: what says a body is wedged in a corner it is standing on legally
        # (`WorldNavigation.unwedge`). Session-only, like everything else about a step.
        self.wedge_spot: tuple | None = None
        self.wedge_ms = 0.0
        # Whether this one takes up arms when a monster walks into their settlement, rolled
        # off their home so the same house always sends the same person out. Cached because
        # it is asked every frame.
        self._militia: bool | None = None
        # What this one has in their hands, rolled with the militia flag off the same home
        # seed: a name, resolved through the ordinary weapon archetypes, so a villager's
        # reach, damage and cadence all come from the table the player's own weapons use.
        self._weapon_name: str | None = None
        # A posted guard: stands their watch instead of wandering, always takes up arms,
        # and carries something a farmer does not (World._post_guards).
        self.is_guard = False
        # A guard posted in a tower with a bow: everything a guard is, plus shots at
        # whatever their settlement has turned on (World._post_guards, _loose_arrows).
        self.is_archer = False
        self.next_arrow_ms = 0
        # How well defended the settlement this one belongs to is (`Village.tier`), which
        # decides which weapon ladder they draw from. Nothing about a village's strength
        # lives on the person: this only picks a pool.
        self.defence_tier = 0
        # Whatever last drew blood on this one that was not the player, and until when they
        # remember it (`threaten`). Anybody bitten turns round and swings, militia roll or
        # not: a farmer with a slime on him is not a bystander. Session-only, like every
        # other fact about a fight.
        self.threatened_by = None
        self.threat_until = 0.0

    @property
    def hostile(self) -> bool:
        # Somebody kneeling with their hands up is not fighting anyone, whatever their
        # village decided a minute ago: a surrender outranks even a grudge for as long as it
        # lasts, which is what makes sparing them a thing the player can actually do.
        return not self.surrendered and (self.grudge or time.time() < self.hostile_until)

    @property
    def surrendered(self) -> bool:
        """Down on one knee with a white flag up, and out of the fight while it lasts."""
        return time.time() < self.surrender_until

    def surrender(self):
        """Yield: drop what is in your hands and kneel. A farmer's answer to being cut down
        to nothing, where a militiaman's is to fall back shouting for help."""
        self.surrender_until = time.time() + c.Villages.SURRENDER_S
        self.yielded = True
        self.warned_until_ms = 0

    @property
    def anger_remaining(self) -> float:
        """Seconds until this one calms down; 0 when calm, inf on a grudge."""
        if self.grudge:
            return math.inf
        return max(0.0, self.hostile_until - time.time())

    def anger(self, seconds: float, permanent: bool = False):
        """Turn on the player for a while. A fresh offence adds to whatever is left rather
        than replacing it, up to a ceiling: keep swinging and they keep hating you, but the
        clock never runs so long that the settlement is written off for the save."""
        if permanent:
            self.grudge = True
        self.affinity = c.Affinity.MIN
        self.hostile_until = time.time() + min(self.anger_remaining + seconds, c.Villages.ANGER_CAP_S)

    def _cool_off(self):
        """Called each frame: the moment the countdown runs out, put a little goodwill back.
        Not all of it. They will trade with the player again and remember why they stopped."""
        if self.hostile_until and not self.hostile:
            self.hostile_until = 0.0
            self.affinity = max(self.affinity, c.Affinity.FORGIVEN)

    def threaten(self, attacker):
        """Remember whoever just hurt this one, so they fight back instead of standing there.

        Being bitten is its own reason to swing: it does not go through the militia roll and
        it does not care whose ground the fight is on, which is what makes a monster in a
        street an event rather than a farmer being eaten in silence. Fresh damage keeps the
        memory topped up; once it runs out they go back to their day."""
        self.threatened_by = attacker
        self.threat_until = time.time() + c.Villages.THREAT_MEMORY_S

    @property
    def threat(self):
        """Who this one is fighting back against, or None once the memory has run out or the
        thing that hurt them is dead."""
        if self.threatened_by is None or time.time() >= self.threat_until:
            return None
        if getattr(self.threatened_by, "hp", 1) <= 0:
            self.threatened_by = None
            return None
        return self.threatened_by

    def melee_standoff(self, target_size: float) -> float:
        """How far off a target this one means to stand: their own weapon's reach, less the
        margin every ring point is drawn in by.

        The one place the distance is worked out, so what `_hunt` accepts as in reach and
        what the world sends them to stand at are the same number. Someone with a spear
        holds it at the length of the spear; someone with a knife has to walk in."""
        reach = c.Entities.NPC_ATTACK_RANGE * self.weapon.reach_mult
        return max(0.0, reach + target_size / 2 - c.Entities.CHASE_RING_MARGIN)

    @property
    def is_militia(self) -> bool:
        """Whether this one meets a monster in the street or runs from it. Merchants never
        fight: their stock is their life, and a shopkeeper with a sword is a different game."""
        if self.is_guard:
            return True
        if self._militia is None:
            seed = f"militia:{round(self.home[0])}:{round(self.home[1])}"
            fraction = c.Villages.MILITIA_FRACTION_BY_TIER[self._tier_index(c.Villages.MILITIA_FRACTION_BY_TIER)]
            self._militia = not self.is_merchant and random.Random(seed).random() < fraction
        return self._militia

    def _tier_index(self, ladder) -> int:
        """This one's settlement tier, clamped to whatever ladder is being read off it."""
        return max(0, min(self.defence_tier, len(ladder) - 1))

    @property
    def weapon_name(self) -> str:
        """The tool or weapon in this one's hands. Rolled off their home like the militia
        flag, so the same house always turns out the same person with the same thing."""
        if self._weapon_name is None:
            rng = random.Random(f"weapon:{round(self.home[0])}:{round(self.home[1])}")
            if self.is_archer:
                pool = c.Entities.ARCHER_WEAPONS
            elif self.is_guard:
                pool = c.Entities.GUARD_WEAPON_TIERS[self._tier_index(c.Entities.GUARD_WEAPON_TIERS)]
            elif self.is_militia:
                pool = c.Entities.MILITIA_WEAPON_TIERS[self._tier_index(c.Entities.MILITIA_WEAPON_TIERS)]
            else:
                pool = c.Entities.VILLAGER_WEAPON_TIERS[self._tier_index(c.Entities.VILLAGER_WEAPON_TIERS)]
            self._weapon_name = rng.choice(pool)
        return self._weapon_name

    @property
    def weapon(self):
        return c.weapon_archetype(self.weapon_name)

    def gear(self) -> dict:
        """What is drawn in this one's hands, in the shape `draw_human` wants. A villager
        carries one thing and it is always melee: the stones a mob throws are picked up off
        the ground, not kept in a quiver."""
        if self.surrendered:
            # The one thing a surrender has to read as from across the street: their hands
            # are empty.
            return {}
        return {
            "hand1": {
                "kind": c.weapon_look(self.weapon_name),
                "color": c.Entities.WEAPON_COLOR,
                "outline": c.Entities.WEAPON_OUTLINE,
            }
        }

    def aim_at(self, x: float, y: float) -> float:
        """Turn to face (x, y) and hold that facing while the shot leaves, returning the
        bearing a `Projectile` wants (measured from straight up, clockwise).

        The one place a villager's aim is worked out, so what they are drawn looking at and
        what they actually loose at can never be two different directions. Sprites face up,
        which is the quarter turn."""
        angle = math.atan2(y - self.y, x - self.x)
        self.orientation = angle + math.pi / 2
        self.aim_until_ms = pygame.time.get_ticks() + c.Entities.NPC_AIM_HOLD_MS
        return math.atan2(x - self.x, self.y - y)

    @property
    def aiming(self) -> bool:
        return pygame.time.get_ticks() < self.aim_until_ms

    def warn(self, x: float, y: float):
        """The player's first offence against this one's village: turn on them, shout, and
        leave it there. Nobody goes hostile off a warning, which is the whole point of it."""
        self.warned_until_ms = pygame.time.get_ticks() + c.Villages.WARNING_MS
        self.aim_at(x, y)
        self.start_attack_anim("left")

    @property
    def warning(self) -> bool:
        return pygame.time.get_ticks() < self.warned_until_ms

    def sees(self, x: float, y: float, radius: float) -> bool:
        """Whether (x, y) falls inside this one's field of view: near enough, and inside the
        wedge they are actually facing. Sprites face up, so the facing angle is the drawn
        orientation less a quarter turn."""
        if self.distance_to_point((x, y)) > radius:
            return False
        facing = self.orientation - math.pi / 2
        bearing = math.atan2(y - self.y, x - self.x)
        offset = abs((bearing - facing + math.pi) % (2 * math.pi) - math.pi)
        return offset <= math.radians(c.Crime.VIEW_CONE_DEG) / 2

    @property
    def can_talk(self) -> bool:
        """False once this NPC has turned on the player: no conversation, no shop, no
        quest hand-in from someone trying to kill you."""
        return not self.hostile

    @property
    def has_active_quest(self):
        return self.quest is not None and not self.quest.is_completed

    def _affinity_tier(self) -> tuple:
        return next(tier for tier in AFFINITY_TIERS if tier[0] is None or self.affinity < tier[0])

    def affinity_descriptor(self) -> str:
        """A prompt hint reflecting how the NPC feels about the player, or "" when neutral."""
        return self._affinity_tier()[1]

    def affinity_tier_color(self) -> tuple:
        return self._affinity_tier()[2]

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "name": self.name,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "color": list(self.color),
            "orientation": self.orientation,
            "quest": self.quest.to_dict() if self.quest else None,
            "is_merchant": self.is_merchant,
            "is_guard": self.is_guard,
            "is_archer": self.is_archer,
            "defence_tier": self.defence_tier,
            "is_thief": self.is_thief,
            # Absolute wall clock, like the rest cooldowns: quitting while a village is
            # angry must not be a way of waiting the anger out.
            "hostile_until": self.hostile_until,
            "grudge": self.grudge,
            "affinity": self.affinity,
            "shop_ready": self.shop_ready,
            "restock_at": self.restock_at,
            "home": list(self.home),
            "shop_items": [{**item.to_dict(), "shop_price": self.shop_prices[item.id]} for item in self.shop_items],
        }

    @classmethod
    def from_dict(cls, data: dict, items_by_id: dict[str, Item]) -> NPC:
        npc = cls(data["x"], data["y"])
        npc.name = data["name"]
        npc.max_hp = data.get("max_hp", npc.max_hp)
        npc.hp = data["hp"]
        npc.color = tuple(data["color"])
        npc.orientation = data["orientation"]
        if data["quest"]:
            npc.quest = Quest.from_dict(data["quest"], items_by_id)
        npc.is_merchant = data["is_merchant"]
        npc.is_guard = data.get("is_guard", False)
        npc.is_archer = data.get("is_archer", False)
        npc.defence_tier = data.get("defence_tier", 0)
        if npc.is_guard:
            # A guard holds their post rather than strolling the street, on a reload as
            # much as on the frame they were first stood there.
            npc.wander.radius = c.Villages.GUARD_POST_RADIUS
        npc.is_thief = data.get("is_thief", False)
        # A save from before anger had a clock recorded it as a plain flag; those villagers
        # were angry for good, so they load as a grudge rather than silently forgiving.
        npc.hostile_until = data.get("hostile_until", 0.0)
        npc.grudge = data.get("grudge", data.get("hostile", False))
        npc.affinity = data.get("affinity", c.Affinity.START)
        npc.shop_ready = data["shop_ready"]
        npc.restock_at = data.get("restock_at", 0.0)
        npc.home = tuple(data["home"])
        for entry in data["shop_items"]:
            price = entry["shop_price"]
            item_data = {k: v for k, v in entry.items() if k != "shop_price"}
            item = Item.from_dict(item_data)
            npc.shop_items.append(item)
            npc.shop_prices[item.id] = price
        return npc

    def restock_in(self) -> float:
        """Seconds until this merchant's next delivery; 0 once it is due. Read by the shop
        menu's countdown and by the world that actually puts the wares out."""
        return max(0.0, self.restock_at - time.time())

    def set_shop(self, shop_data: list):
        self.shop_items.clear()
        self.shop_prices.clear()
        self.add_stock(shop_data)
        self.shop_ready = True

    @property
    def stock_luck(self) -> float:
        """How far up the rarity ladder this merchant's shelf leans, off their settlement's
        own tier (`Villages.SHOP_LUCK_PER_TIER`). A town four days out sells better steel
        than the one the player started next to, for the same reason its monsters are worse:
        the walk is what buys it. Nothing about the item tables changes, only which end of
        them a roll tends to land on."""
        return self.defence_tier * c.Villages.SHOP_LUCK_PER_TIER

    def add_stock(self, shop_data: list):
        """Put wares on the shelf beside whatever is already there, and start the clock on
        the next delivery. Everything a merchant ever sells arrives through here.

        Rarity is always this shop's own roll, never the model's: what the LLM writes about a
        ware is what it is called, and it has no idea how deep into the wilds the town it is
        being sold in stands."""
        for entry in shop_data:
            # The name is the better authority on what a ware is: the model routinely
            # lists a shield as "armor", which put it in the body-armour slot and left
            # the offhand empty. Its own answer is only used for a name that says
            # nothing (a curio, a pelt).
            named_type = item_type_from_name(entry["name"])
            item_type = named_type if named_type != "misc" else (entry.get("item_type") or "misc")
            rarity = roll_rarity(luck=self.stock_luck)
            quantity = entry.get("quantity", AMMO_BUNDLE if item_type == "ammo" else 1)
            item = Item(0, 0, entry["name"], item_type, roll_bonus(item_type, rarity), rarity, quantity=quantity)
            self.shop_items.append(item)
            self.shop_prices[item.id] = round(entry["price"] * rarity_tier(rarity).price_mult)
        self.restock_at = time.time() + c.Villages.SHOP_RESTOCK_S

    def assign_name(self, npc_name_generator: NPCNameGenerator):
        if self.name is None:
            self.name = npc_name_generator.get_name()

    def update(self, player: Player, dt, *args, **kwargs):
        """One frame, with whatever this one is aiming at held in front of them.

        Everything below picks a facing from what it is doing: walking, greeting, swinging.
        A villager who has just loosed an arrow or thrown a stone is doing none of those,
        and turning them back to face their footsteps on the next frame is what had archers
        shooting sideways. So the aim wins for as long as it is held, and the frame is run
        underneath it."""
        aimed = self.orientation if self.aiming else None
        damage = self._act(player, dt, *args, **kwargs)
        if aimed is not None:
            self.orientation = aimed
        return damage

    def _act(
        self,
        player: Player,
        dt,
        blocked=None,
        waypoint=None,
        target=None,
        refuge=None,
        face_player=True,
        terrain_mult: float = 1.0,
        standoff: float = 0.0,
        crowd=None,
    ):
        """One frame of this villager's life, returning the damage their swing just landed
        on `target` (0 for none) so the world can resolve it: the same villager can be
        swinging at the player or at a monster in their street, and only the world knows
        which lists to take the blow off.

        The world decides what they are doing and hands it in: `target` is who they are
        fighting, `refuge` a point to run to (a frightened villager heading for a door), and
        `face_player` False keeps them looking where they were, which is what stops a vision
        cone from pointing at the player no matter where they stand.

        `terrain_mult` is the ground: a villager wading a river is as slow in it as anything
        else, so the frame is simply shortened for them.

        `standoff` is how far off the target they mean to stand: a hair inside arm's reach
        for whoever is doing the fighting, well out of it for the ones who would rather
        throw something from the back of the crowd.

        `crowd` is everyone else in the same fight, so a mob presses in as a ring rather
        than stacking on the one spot nearest the player."""
        dt *= terrain_mult
        if crowd:
            push_apart(self, crowd, c.Entities.NPC_SIZE / 2, lambda other: c.Entities.NPC_SIZE / 2, blocked)
        # A stone thrown from the back of a mob starts a swing too, and that one is not in
        # `_hunt`: the animation is advanced here so it always finishes wherever it began.
        if target is None:
            self.update_attack_anim(dt)
        self._cool_off()
        if target is not None:
            return self._hunt(target, dt, blocked, waypoint, standoff)
        if refuge is not None:
            self._run_to(refuge, dt, blocked)
            return 0

        if (
            face_player
            and not self.hostile
            and self.distance_to_point(player.get_pos()) < (c.Entities.NPC_WANDER_PAUSE_DISTANCE)
        ):
            # atan2(dy, dx) measures from the x-axis; sprites face up, so rotate a quarter turn
            self.orientation = math.atan2(player.y - self.y, player.x - self.x) + math.pi / 2
            return 0

        if self.rooted or self.staggered:
            return 0
        moved_angle = self.wander.step(self, dt, self.home, c.Entities.NPC_SIZE / 2, blocked)
        # Face the way it actually moved, not the way it wanted to: a slider looks along
        # the wall, and one pinned against a building stops staring straight into it.
        if moved_angle is not None:
            self.orientation = moved_angle + math.pi / 2
        return 0

    def _step_towards(self, point, dt, blocked, speed_mult: float = 1.0) -> float:
        """Walk at a point, sliding along whatever is in the way. Returns the heading.

        A villager caught in a bear trap, or still sliding from a blow that shoved them,
        still faces where they were going and still swings at whatever comes into reach;
        they just don't get there under their own power."""
        angle = math.atan2(point[1] - self.y, point[0] - self.x)
        if self.rooted or self.staggered:
            return angle
        radius = c.Entities.NPC_SIZE / 2
        speed = c.Entities.NPC_HOSTILE_SPEED * speed_mult * self.chill_mult * frames(dt)
        step_towards(self, angle, speed, blocked, radius)
        return angle

    def _run_to(self, refuge, dt, blocked=None):
        """A villager with no stomach for the fight, making for the nearest door. They stop
        once they are on the spot rather than jittering on it."""
        if self.distance_to_point(refuge) <= c.Entities.NPC_ATTACK_RANGE:
            return
        self.orientation = self._step_towards(refuge, dt, blocked) + math.pi / 2

    def _ring_point(self, target, standoff: float, blocked=None) -> tuple:
        """The spot this one is trying to hold: its own bearing around the target, at
        `standoff`.

        A spot nobody can stand in is worse than none, so a blocked bearing shuffles a
        little way round the ring either side of itself before giving up. It used to fall
        straight back to the target's own position, which is what had every villager whose
        slot was against a wall converging on the same pixel: the fallback was the pile.
        With nowhere on the ring to stand, they hold where they are and let the ones with
        room do the work."""
        if standoff <= 0:
            return target.x, target.y
        radius = c.Entities.NPC_SIZE / 2
        for offset in (0.0, 0.5, -0.5, 1.0, -1.0):
            bearing = self.slot_angle + offset
            x = target.x + math.cos(bearing) * standoff
            y = target.y + math.sin(bearing) * standoff
            if blocked is None or not blocked(x, y, radius):
                return x, y
        return self.x, self.y

    def _hunt(self, target, dt, blocked=None, waypoint=None, standoff: float = 0.0) -> int:
        """Walk at whatever this one is fighting and swing when it is in reach, returning the
        damage landed this frame. Deliberately simpler than a monster's chase: villagers are
        farmers with sticks, not hunters. They walk to their place around the target (round a
        wall when the world hands them a waypoint) and hit whatever comes into range.

        The swing needs the token the world deals out (`attack_token`), so a crowd presses in
        from every side with only a few arms moving at a time instead of a dozen villagers
        landing a blow each on the same frame, which was less a fight than a woodchipper."""
        dist = self.distance_to_point((target.x, target.y))
        place = self._ring_point(target, standoff, blocked)
        goal = waypoint if waypoint is not None else place
        angle = math.atan2(goal[1] - self.y, goal[0] - self.x)
        self.orientation = angle + math.pi / 2

        # A waypoint is a step on the way, never a destination: arriving at the corner of a
        # house or at a doorstep is no reason to stand there while the fight is elsewhere.
        # Only reaching the place on the ring is standing still.
        if waypoint is not None or self.distance_to_point(goal) > c.Entities.CHASE_ARRIVE:
            self._step_towards(goal, dt, blocked)
        else:
            # Standing on its spot: look at what it is fighting rather than at the ground.
            self.orientation = math.atan2(target.y - self.y, target.x - self.x) + math.pi / 2

        damage = 0
        now = pygame.time.get_ticks()
        weapon = self.weapon
        reach = c.Entities.NPC_ATTACK_RANGE * weapon.reach_mult
        in_reach = dist <= reach + target.size // 2
        if in_reach and self.attack_token and now >= self.attack_ready_ms:
            # Cadence, reach and damage all come off whatever they are holding: the woman
            # with the pitchfork keeps the player at arm's length and the one with the
            # kitchen knife has to get close and hit twice.
            self.attack_ready_ms = now + weapon.cooldown_ms
            self.start_attack_anim("right")
            damage = max(1, round(c.Entities.NPC_DAMAGE * weapon.damage_mult))

        self.update_attack_anim(dt)
        return damage

    @property
    def routed(self) -> bool:
        """Cut down this far and this one is done fighting: they break for the nearest door.
        A mob that thins out as it loses is a mob; one that fights to the last farmer over a
        stolen loaf is a machine."""
        return self.hp <= self.max_hp * c.Villages.ROUT_HP_FRAC

    def _badge(self) -> tuple | None:
        """(font, symbol, color) for the marker floating over this NPC's head, or None."""
        if self.surrendered:
            return None  # a white flag is drawn instead, and it is not a badge
        if self.hostile:
            return c.Fonts.badge, "!", c.Colors.RED
        # Not angry yet, and saying so. Orange rather than red: the difference between the
        # two badges is the difference between a warning and a fight.
        if self.warning:
            return c.Fonts.badge, "!", c.Colors.ORANGE
        if self.has_active_quest:
            return c.Fonts.badge, "!", c.Colors.YELLOW
        if self.is_thief:
            return c.Fonts.badge, "?", (190, 70, 220)
        if self.is_merchant:
            color = (100, 255, 100) if self.shop_ready else (120, 120, 80)
            return c.Fonts.badge_small, "$", color
        return None

    @staticmethod
    def _draw_white_flag(screen: pygame.Surface, x: float, y: float):
        """The one cue that says this one has yielded, and the reason it is not a badge: an
        exclamation mark in another colour is a thing to read, a rag on a stick is a thing to
        recognise. It waves, because a still flag over a still body reads as neither."""
        wave = math.sin(time.time() * 3) * 3
        top = y - c.Entities.NPC_SIZE // 2 - 26
        pole = (round(x - 10), round(top))
        pygame.draw.line(screen, (120, 96, 66), pole, (round(x - 10), round(top + 26)), 3)
        cloth = ((pole[0], pole[1]), (pole[0] + 22 + wave, pole[1] + 6), (pole[0], pole[1] + 13))
        pygame.draw.polygon(screen, (238, 238, 232), cloth)
        pygame.draw.polygon(screen, (150, 150, 145), cloth, 1)

    def draw(self, screen: pygame.Surface, camera: Camera, health_bar: bool = True):
        """`health_bar` off is the title screen's village, where nobody is fighting anyone
        and a row of full green bars would read as HUD rather than as people."""
        screen_x, screen_y = camera.world_to_screen(self.x, self.y)
        super().draw(
            screen,
            screen_x,
            screen_y,
            c.Entities.NPC_SIZE,
            self.color,
            self.orientation,
            attack_progress=self.attack_progress,
            attack_hand=self.attack_hand,
            health_bar=health_bar,
            gear=self.gear(),
        )

        if self.surrendered:
            self._draw_white_flag(screen, screen_x, screen_y)

        badge = self._badge()
        if badge is not None:
            font, symbol, color = badge
            bob_offset = math.sin(time.time() * 4) * 4
            text = font.render(symbol, True, color)
            text_rect = text.get_rect(center=(screen_x, screen_y - c.Entities.NPC_SIZE // 2 - 20 + bob_offset))
            screen.blit(text, text_rect)

        if self.name:
            name_rect = draw_outlined_text(
                screen,
                self.name,
                c.Fonts.small,
                c.Colors.WHITE,
                center=(screen_x, screen_y + c.Entities.NPC_SIZE // 2 + 30),
            )

            # Only shown once the player's actions have actually moved the relationship,
            # so untouched NPCs don't clutter the world with a neutral marker.
            if self.affinity != c.Affinity.START:
                pygame.draw.circle(screen, self.affinity_tier_color(), (name_rect.left - 13, name_rect.centery), 5)
