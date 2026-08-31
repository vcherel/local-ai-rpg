from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from game.blow import Blow
from game.entities.boss import Boss
from game.entities.buildings import Building
from game.entities.npcs import NPC
from game.entities.projectile import ARROW_COLOR, STONE_COLOR, Projectile
from game.navigation import Point

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


class WorldVillagers:
    """Every villager's frame: what one does about an intruder, a shut door, a bed at
    curfew or an empty street.

    Mixed into `World`, which owns the lists these methods read and mutate (`npcs`,
    `villages`, `buildings`, `projectiles`, `mob`). Split out of `world.py` purely for
    size, the same way the blows and the streaming were: this is one coherent job, driven
    from `_update_npcs` once a frame, and the rest of the class is world state and lookups.

    A settlement acts as a settlement rather than as a crowd of individuals, so the orders
    are worked out for everyone at once (`_mob_orders`, `WorldPlaces.militia_orders`) and
    each villager is then walked through the one they were given.
    """

    def _update_npcs(self, player: Player, dt, quest_system: QuestSystem):
        """Every villager's frame: fighting off an intruder, running for a door, hunting the
        player, or wandering their street.

        The world picks what each of them is doing and hands it to `NPC.update`, which gives
        back whatever its swing landed so the blow can be taken off the right list. A
        villager only ever fights one thing at a time, and defending the settlement comes
        first: a monster in the street is more pressing than a grudge."""
        indoors = self.building_at(player.x, player.y) is not None
        self._restock_merchants()
        fight, flee = self.militia_orders()
        mob = self._mob_orders(player, flee, quest_system)
        # An archer is in the orders so `_loose_arrows` knows what they are shooting at, but
        # never in the crowd: a body on a tower roof is not one of the ring of people pushing
        # in around the player, and being shouldered by that ring is what walked them off it.
        crowd = [npc for npc in self.npcs if id(npc) in mob and not npc.is_archer]
        all_home = self._households_in(mob) if self.daynight.curfew else frozenset()
        defenders = [npc for npc in self.npcs if id(npc) in fight]
        self.assign_surround_slots(crowd, player)
        self._throw_stones(player, mob)
        self._work_gates(player, dt)
        self._loose_arrows(fight, mob, player)

        for npc in self.npcs:
            if npc.is_archer:
                # Posted on a tower roof, which is solid ground: never unstuck off it, never
                # walked off it, never pushed off it. All they do is aim and loose
                # (`_loose_arrows`), so the frame is run with nothing to walk to.
                npc.update(player, dt, self.blocked, face_player=False)
                continue
            if npc.asleep:
                # In bed, which is a piece of furniture and so a solid: the other body in a
                # settlement exempt from being put back on open ground, for the same reason
                # the archer on the roof is. Anything at all to do (dawn, a fight, a monster
                # in the street) has them out of it first, and the `unstick` below is what
                # puts their feet on the floor.
                if self.daynight.curfew and not (id(npc) in mob or id(npc) in fight or id(npc) in flee):
                    # Given the frame anyway, with their own spot as the place to go, so
                    # anger still cools overnight and nothing else moves them.
                    npc.update(player, dt, self.blocked, refuge=(npc.x, npc.y), face_player=False)
                    continue
                npc.asleep = False
            # Anything standing inside a solid is put back on open ground before it tries to
            # move: from in there every step it could take would be refused, and a villager
            # a village was built on top of stayed in the wall for the rest of the save.
            self.unstick(npc, c.Entities.NPC_SIZE / 2)
            # And anything standing on legal ground it cannot get off (the inside corner of
            # an L, the neck between two houses) is prised out of it: that one is invisible
            # to `blocked` and only shows up as a body that has meant to move for a while
            # and has not.
            # Walking home is meaning to move like any other errand. Left out of this, the
            # one rescue written for a body pinned on a corner was switched off for exactly
            # the walk that pins them there.
            going_home = self.daynight.curfew and not npc.is_guard and id(npc) not in mob
            self.unwedge(
                npc,
                c.Entities.NPC_SIZE / 2,
                dt,
                wants_move=bool(
                    id(npc) in mob or id(npc) in fight or id(npc) in flee or going_home or npc.wander.target is not None
                ),
            )
            enemy = fight.get(id(npc))
            # The orders were worked out once for the whole street, so the neighbour who
            # went first may already have finished this one off.
            if enemy is not None and enemy.hp <= 0:
                enemy = None
            if enemy is not None:
                self._npc_fights(npc, enemy, player, dt, quest_system, defenders)
                continue

            shelter = flee.get(id(npc))
            if shelter is not None:
                self._npc_flees(npc, shelter, player, dt)
                continue

            # Night, and nothing to fight: whoever is not already after the player leaves
            # off what they were doing and goes home to bed. A settlement after dark is a
            # street of shut doors and lit windows, which is what makes coming back into one
            # at dusk worth something and makes the wilds at night worth avoiding.
            if self.daynight.curfew and id(npc) not in mob and not npc.is_guard:
                home = self._home_for(npc)
                if home is not None:
                    self._npc_sleeps(npc, home, player, dt, shut=id(home) in all_home)
                    continue

            self._wake_up(npc)
            self._npc_walks(npc, player, dt, mob, crowd, indoors)

    def _npc_fights(self, npc: NPC, enemy, player: Player, dt, quest_system: QuestSystem, defenders: list):
        """One villager's frame spent meeting whatever the settlement sent them at."""
        waypoint = self.chase_waypoint(npc, enemy, c.Entities.NPC_SIZE / 2)
        damage = npc.update(
            player,
            dt,
            self.blocked,
            waypoint,
            target=enemy,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
            standoff=npc.melee_standoff(enemy.size),
            crowd=defenders,
        )
        if not damage:
            return
        # A militia's swing lands on whatever they were sent at, and a boss is kept on its
        # own list: handing the wrong list here would take a dying boss off nothing at all.
        self._resolve_monster_hit(
            enemy,
            self.bosses if isinstance(enemy, Boss) else self.monsters,
            damage,
            player,
            quest_system,
            Blow(kb_dir=self._dir_from(npc.x, npc.y, enemy.x, enemy.y), blocked=self.blocked, by_player=False),
        )

    def _npc_flees(self, npc: NPC, shelter, player: Player, dt):
        """One villager's frame spent running for a door and shutting it behind them, or
        simply spent running.

        `shelter` is a building when there is one to get behind and a bare point when there
        is not (`WorldPlaces._refuge_for`): a rout in a field is still a rout, and it ends
        in open ground rather than in a doorway.

        The way round a wall is handed in as a waypoint and not as the destination: a corner
        is a step, and somebody who arrives at one stops on it."""
        door = isinstance(shelter, Building)
        goal = (shelter.x, shelter.interior_rect().centery) if door else (shelter.x, shelter.y)
        if door:
            self.open_door_for(npc)
        self.pass_gate_for(npc, c.Entities.NPC_SIZE / 2, Point(*goal))
        waypoint = self.chase_waypoint(npc, Point(*goal), c.Entities.NPC_SIZE / 2)
        npc.update(
            player,
            dt,
            self.blocked,
            waypoint,
            refuge=goal,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
        )
        if door and shelter.contains_point(npc.x, npc.y) and not shelter.door_broken:
            # Behind the door and shutting it. The player can be shut out or shut in with
            # them; either way the street is emptier than it was. Whoever is standing in the
            # frame is stepped out of it rather than sealed in it.
            self.shut_door(shelter, player)

    @staticmethod
    def _wake_up(npc: NPC):
        """Morning: somebody who went to bed behind their own shut door opens it again.

        Their wander is anchored on their doorstep, which is outside, so this is all it takes
        to put the street back: without it the first night a settlement kept was the last day
        anybody was seen in it."""
        home = npc.home_building
        if home is not None and home.door_closed and home.contains_point(npc.x, npc.y):
            home.door_open = True

    def plan_morning(self) -> None:
        """Where everybody will be standing by the time the player opens their eyes.

        The one thing a slept night owes the player: hours went by, so the street cannot be
        the exact tableau they lay down in. Everyone is got out of bed here (their door
        opened behind them, like any other dawn) and given a spot on their own patch to be
        found at, drawn the way their wander draws one: somewhere within the radius they
        already stroll, round the doorstep or the post they belong to. A guard's patch is
        their post and a merchant's is their shop, so the plan needs no ladder of roles.

        Nobody hostile is planned: a village that has turned is hunting the player and the
        night changed nothing about that. Neither is a tower archer, who is on their roof
        where they belong."""
        radius = c.Entities.NPC_SIZE / 2
        self.morning_walk = []
        for npc in self.npcs:
            if npc.is_archer or npc.hostile or npc.surrendered:
                continue
            if npc.asleep:
                # Out of bed before they are walked anywhere: the door is only opened for
                # somebody standing inside their own house, which is where they still are.
                self._wake_up(npc)
                npc.asleep = False
            spread = npc.wander.radius
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(spread / 3, spread)
            spot = (npc.home[0] + math.cos(angle) * distance, npc.home[1] + math.sin(angle) * distance)
            target = self.free_spot_near(spot[0], spot[1], radius, rings=3)
            self.morning_walk.append((npc, (npc.x, npc.y), target))
            npc.wander.interrupt()

    def drift_to_morning(self, progress: float) -> None:
        """Move everybody `progress` of the way to the spot `plan_morning` picked for them.

        A night is not a teleport: the fade the player watches is the walk, eased at both
        ends and facing the way it is going, so the gait animates itself off the ground
        covered like any other step. No route is worked out and no wall is slid along,
        because the screen is black across the middle of it and hours are not a stride;
        what matters is that the two ends are real. Once there, everybody is put back on
        open ground and picks a fresh stroll, and the plan is spent."""
        eased = min(1.0, max(0.0, progress))
        eased = eased * eased * (3 - 2 * eased)
        for npc, start, target in self.morning_walk:
            npc.x = start[0] + (target[0] - start[0]) * eased
            npc.y = start[1] + (target[1] - start[1]) * eased
            if target != start:
                npc.orientation = math.atan2(target[1] - start[1], target[0] - start[0]) + math.pi / 2
        if progress < 1.0:
            return
        radius = c.Entities.NPC_SIZE / 2
        for npc, _start, _target in self.morning_walk:
            self.unstick(npc, radius)
            npc.wander.interrupt()
        self.morning_walk = []

    def _households_in(self, mob: dict) -> frozenset:
        """Which homes have everybody who lives there back inside, as ids of the buildings.

        The one thing a villager going to bed cannot work out for themselves: shutting the
        door behind you while your neighbour is still on the step puts them back out into the
        street (`shut_door` clears the frame rather than sealing anyone in it), and the two
        of you do that to each other until morning. So the door is only ever shut by the last
        one in."""
        households: dict = {}
        for npc in self.npcs:
            if npc.is_guard or id(npc) in mob:
                continue
            home = self._home_for(npc)
            if home is None:
                continue
            households.setdefault(id(home), []).append((home, npc))
        return frozenset(
            key for key, people in households.items() if all(home.contains_point(one.x, one.y) for home, one in people)
        )

    def _home_for(self, npc: NPC) -> Building | None:
        """The building this one lives in: the one nearest the doorstep they were stood up
        at, which is the door they came out of.

        A merchant's home is their shop, so a night shuts the shop with them inside it
        rather than leaving them standing in the street beside it. Anyone whose house has
        been streamed out from under them has no home to walk to and simply keeps their
        street.

        Found once and kept on the villager: a building does not move once its settlement is
        laid out, and this is asked of everybody in the world on every frame of every
        night."""
        if npc.home_building is None:
            homes = [b for b in self.buildings_near(*npc.home) if b.has_door]
            # Measured to the doorstep and not to the middle of the building, because a
            # villager's home *is* a doorstep (`World._populate_npcs`): off the centres, the
            # shop across the lane won half the street.
            npc.home_building = min(homes, key=lambda b: math.dist(npc.home, b.door_front()), default=None)
        return npc.home_building

    def _npc_sleeps(self, npc: NPC, home: Building, player: Player, dt, shut: bool = True):
        """One villager's frame spent walking home for the night, getting into bed and
        staying there.

        The same walk as running from a monster (`_npc_flees`), because it is the same act:
        the door is opened, the gate is worked if their house is the other side of one, and
        it is shut behind them. What is different is only where they are going, which is
        their own bed rather than the nearest roof.

        The whole walk is routed, the last stride included. The way round the corner of the
        house is a waypoint and never the destination, or they arrive at the corner and stand
        on it until dawn, and the way across the room is routed too, so the table is walked
        round rather than into.

        Arriving is getting into bed (`_turn_in`), not stopping in the middle of the floor: a
        settlement after dark should be bodies in beds behind lit windows. Whoever the house
        has no bed for stands in the room as they always did."""
        radius = c.Entities.NPC_SIZE / 2
        inside = (home.x, home.interior_rect().centery)
        door = home.door_rect()
        self.pass_gate_for(npc, radius, Point(*inside))
        bed = self._bed_for(npc, home)
        if home.contains_point(npc.x, npc.y):
            goal = inside
            if bed is not None:
                goal = self._bedside(home, bed, radius)
                # Arrived at the foot of it, or simply up against it: either is close enough
                # to climb in. The second half is what a room with the table pushed up to
                # the bed answers, where the foot of it is not somewhere anybody can stand.
                if npc.distance_to_point(goal) <= radius + 8 or self._rect_reach(npc, bed) <= radius + 8:
                    self._turn_in(npc, home, bed)
        else:
            self.open_door_for(npc)
            # Their own door opens for them from further off than a stranger's does: they
            # live here. Left to `open_door_for` alone they walked up to a shut leaf of their
            # own and stood against it.
            if math.hypot(npc.x - door.centerx, npc.y - door.centery) <= c.Buildings.DOOR_BASH_REACH * 3:
                home.door_open = True
            goal = inside
        if not npc.asleep:
            npc.update(
                player,
                dt,
                self.blocked,
                self.chase_waypoint(npc, Point(*goal), radius),
                refuge=goal,
                refuge_reach=radius,
                terrain_mult=self.terrain_speed(npc.x, npc.y),
                face_player=False,
            )
        if shut and home.contains_point(npc.x, npc.y) and not home.door_broken:
            # In for the night, and the door shut behind them, but only once everybody who
            # lives here is in (`_households_in`). Whoever is standing in the frame is
            # stepped out of it rather than sealed in it, exactly as when a village is
            # running from something.
            self.shut_door(home, player)

    def _bed_for(self, npc: NPC, home: Building):
        """The bed in this house that is this one's, or None when the household is bigger
        than the house.

        Dealt once and kept, the way the house itself is: the people who live here in a fixed
        order against the beds in a fixed order, so the same person has the same bed every
        night and two of them never climb into one. A cottage has a single bed and a tavern
        three or four; whoever the house has none for sleeps on their feet, which is what
        everybody used to do."""
        if not npc.bed_dealt:
            npc.bed_dealt = True
            residents = sorted((one for one in self.npcs if self._home_for(one) is home), key=id)
            beds = home.interior_layout()["beds"]
            index = residents.index(npc)
            npc.bed = beds[index] if index < len(beds) else None
        if npc.bed is not None and npc.bed not in home.interior_layout()["beds"]:
            # Broken up while they were out. A pile of splinters is not a bed, and it drops
            # out of the layout the moment it comes apart (`Building.damage_prop_at`).
            npc.bed = None
        return npc.bed

    def _bedside(self, home: Building, bed, radius: float) -> tuple:
        """The floor at the foot of a bed: where somebody stands to get into it.

        A bed is furniture, so it is solid, so the walk home ends beside it rather than on
        it. Off the head-to-foot axis and towards the middle of the room, since the head of
        a bed is against a wall whichever way the house is turned."""
        room = home.interior_rect()
        if bed.height >= bed.width:
            side = 1.0 if room.centery >= bed.centery else -1.0
            spot = (bed.centerx, bed.centery + side * (bed.height / 2 + radius + 4))
        else:
            side = 1.0 if room.centerx >= bed.centerx else -1.0
            spot = (bed.centerx + side * (bed.width / 2 + radius + 4), bed.centery)
        # A room is furnished before anybody is asked to walk across it, so the foot of a bed
        # can have the table standing on it. Somewhere near it will do.
        return self.free_spot_near(spot[0], spot[1], radius, rings=2)

    @staticmethod
    def _rect_reach(npc: NPC, rect) -> float:
        """How far a villager is from the nearest edge of a rectangle."""
        near_x = min(max(npc.x, rect.left), rect.right)
        near_y = min(max(npc.y, rect.top), rect.bottom)
        return math.hypot(npc.x - near_x, npc.y - near_y)

    @staticmethod
    def _turn_in(npc: NPC, home: Building, bed):
        """Get into bed: lie down on it, head to the wall, and stop being a body that walks.

        This is the one place in a settlement something is deliberately put on top of a solid,
        so a sleeper is exempt from `unstick` and `unwedge` for as long as they are in it
        (`_update_npcs`), exactly as a tower archer is exempt from being walked off their
        roof. Anything at all to do puts them back on their feet first."""
        npc.x, npc.y = bed.center
        npc.asleep = True
        npc.wander.interrupt()
        room = home.interior_rect()
        if bed.height >= bed.width:
            heading = -math.pi / 2 if bed.centery <= room.centery else math.pi / 2
        else:
            heading = math.pi if bed.centerx <= room.centerx else 0.0
        npc.orientation = heading + math.pi / 2

    def _npc_walks(self, npc: NPC, player: Player, dt, mob: dict, crowd: list, indoors: bool):
        """One villager's frame spent hunting the player, or spent on their own street."""
        # Only an angry villager actually closing on the player needs a route round the
        # houses; everyone else is wandering and steers for itself.
        chasing = id(npc) in mob
        if chasing:
            self.open_door_for(npc)
            self.pass_gate_for(npc, c.Entities.NPC_SIZE / 2, player)
        waypoint = self.chase_waypoint(npc, player, c.Entities.NPC_SIZE / 2) if chasing else None
        # A villager turns to greet the player in the street, but not through the wall of a
        # house they are standing in: a vision cone that always points at the player is not a
        # cone, and the whole of stealing is choosing a moment nobody is looking.
        damage = npc.update(
            player,
            dt,
            self.blocked,
            waypoint,
            target=player if chasing else None,
            face_player=not indoors,
            terrain_mult=self.terrain_speed(npc.x, npc.y),
            standoff=mob.get(id(npc), 0.0),
            crowd=crowd if chasing else None,
        )
        if damage:
            player.receive_damage(damage, source=npc)

    def _mob_orders(self, player: Player, flee: dict, quest_system: QuestSystem) -> dict:
        """Who in an angry village is actually coming for the player, and how close they mean
        to get: a dict of `id(npc)` to the standoff they hold.

        The same split that decides who meets a monster in the street decides this. Whoever
        `NPC.is_militia` names closes to arm's length and swings; the rest hang back at
        `Villages.MOB_STANDOFF` and throw stones, which is what makes a mob dangerous to walk
        into rather than something to be cut down one farmer at a time. Anyone already badly
        hurt (`NPC.routed`) drops out of the fight and is sent to a door instead, so a mob
        breaks rather than dying to the last of them."""
        orders: dict = {}
        for npc in self.npcs:
            if not npc.hostile:
                continue
            distance = npc.distance_to_point((player.x, player.y))
            # A village is angry everywhere, but only the people the player is standing
            # among fight them: someone whose street this is not carries on with their day
            # rather than walking the length of the settlement to join a fight they cannot
            # see. Whoever is already in it keeps it out to the longer leash, so a fight the
            # player walks away from is broken off rather than dropped the moment they cross
            # a line. An archer is the exception and answers at the range of their bow: they
            # are posted on the wall precisely to shoot what is too far off to reach.
            if npc.is_archer:
                limit = c.Villages.ARCHER_RANGE
            else:
                limit = c.Entities.NPC_HOSTILE_RANGE if id(npc) in self._engaged else c.Villages.MOB_ENGAGE_RANGE
            if distance > limit:
                continue
            if npc.routed:
                if npc.is_militia:
                    for recruit in self.call_for_help(npc):
                        # Nobody hands in a task to someone they have just joined a fight
                        # against, the same rule a provoked village goes by.
                        quest_system.remove_quest(recruit)
                elif not npc.yielded:
                    self.yield_to_player(npc)
                    continue
                shelter = self._refuge_for(npc)
                if shelter is not None:
                    flee[id(npc)] = shelter
                    continue
            if npc.is_archer:
                # An archer holds the wall and shoots off it (`_loose_arrows`); walking out
                # to swing a bow at the player is exactly what they are posted not to do.
                orders[id(npc)] = c.Villages.ARCHER_RANGE * 0.7
            elif npc.is_militia:
                # Their own weapon's length, so the one with the pitchfork fights at the
                # length of a pitchfork instead of walking up the player's nose with it.
                orders[id(npc)] = npc.melee_standoff(c.Player.SIZE)
            else:
                orders[id(npc)] = c.Villages.MOB_STANDOFF
        self._engaged = set(orders)
        return orders

    def _work_gates(self, player: Player, dt):
        """Bar the gates of any settlement that has turned on the player, lean them shut for
        the night, open them again once it is calm and light, and carry every leaf a frame
        along its swing.

        Shutting for the night is not barring: no beam goes across, so anyone on either side
        works one open with a press and walks through (`Village.push_open`). Barring is the
        wall, and only a grudge or a real mob puts it up.

        A gate is the one part of a wall that is ever a wall to the player: while it is
        barred, getting out of a town you have set against you means heaving the beam up
        yourself (`Game._lift_gate`, slow) or hacking your way through it, and a pack that
        followed you in is shut in with you. A gate already beaten down never shuts again.

        One angry villager is not a siege. A settlement only shuts itself once somebody was
        killed here (the grudge nothing runs out) or `Villages.BAR_GATES_MOB` of its people
        are after the player at once, so a caught thief costs the player a fight and not the
        way out of town."""
        for village in self.villages:
            if not village.defended:
                continue
            angry = [npc for npc in self.npcs if npc.hostile and village.contains_point(npc.x, npc.y)]
            village.barred = any(npc.grudge for npc in angry) or len(angry) >= c.Villages.BAR_GATES_MOB
            village.shut_for_night = c.Villages.NIGHT_GATES and self.daynight.curfew
            village.advance_gates(dt, (player.x, player.y))
            if village.barred or village.shut_for_night:
                # Whichever of the two shut it, nothing is ever sealed inside a leaf.
                self.clear_gateways(village, player)

    def _loose_arrows(self, fight: dict, mob: dict, player: Player):
        """The archers posted in the towers, shooting over their own wall.

        They never come down: an archer holds their post and answers whatever the settlement
        is fighting, the monster in the street first and the player second. Their arrow is an
        ordinary `Projectile`, so it hits whatever is standing in the way, and it credits
        nobody (`by_player=False`): a town's kill is the town's."""
        now = pygame.time.get_ticks()
        for npc in self.npcs:
            if not npc.is_archer or now < npc.next_arrow_ms:
                continue
            target = fight.get(id(npc))
            if target is not None and target.hp <= 0:
                target = None
            if target is None and id(npc) in mob:
                target = player
            if target is None:
                continue
            dx, dy = target.x - npc.x, target.y - npc.y
            # Deliberately shorter than the arrow's own flight: a shot loosed at the very
            # limit of its range dies in the air as soon as its target takes a step away.
            if math.hypot(dx, dy) > c.Villages.ARCHER_RANGE * c.Villages.ARCHER_FIRE_FRAC:
                continue
            if not self.line_of_sight(npc.x, npc.y, target.x, target.y, over_walls=True):
                continue
            if not self._lane_clear(npc, target):
                continue
            npc.next_arrow_ms = now + random.randint(*c.Villages.ARCHER_COOLDOWN_MS)
            npc.start_attack_anim()
            play_sound("shoot")
            arrow = Projectile(
                npc.x,
                npc.y,
                npc.aim_at(target.x, target.y),
                c.Villages.ARCHER_DAMAGE,
                color=ARROW_COLOR,
                shake=c.Combat.PLAYER_HURT_SHAKE / 2,
                hostile=target is player,
                owner_id=id(npc),
                source_name=npc.name or "a town archer",
                max_range=c.Villages.ARCHER_RANGE,
                by_player=False,
                over_walls=True,
            )
            arrow.from_npc = True
            self.projectiles.append(arrow)

    def _throw_stones(self, player: Player, mob: dict):
        """The back of the mob doing what a crowd with no swords does: throwing things.

        Only the ones holding their distance throw, only at what they can see, and only on
        their own slow cooldown. One stone is nothing; ten people throwing them is why an
        angry village is somewhere to leave rather than somewhere to fight."""
        now = pygame.time.get_ticks()
        for npc in self.npcs:
            if mob.get(id(npc), 0.0) < c.Villages.MOB_STANDOFF or now < npc.next_stone_ms:
                continue
            dx, dy = player.x - npc.x, player.y - npc.y
            if math.hypot(dx, dy) > c.Villages.MOB_STONE_RANGE:
                continue
            if not self.line_of_sight(npc.x, npc.y, player.x, player.y):
                continue
            if not self._lane_clear(npc, player):
                continue
            npc.next_stone_ms = now + random.randint(*c.Villages.MOB_STONE_COOLDOWN_MS)
            npc.start_attack_anim()
            play_sound("shoot")
            stone = Projectile(
                npc.x,
                npc.y,
                npc.aim_at(player.x, player.y),
                c.Villages.MOB_STONE_DAMAGE,
                style="stone",
                color=STONE_COLOR,
                shake=c.Combat.PLAYER_HURT_SHAKE / 2,
                hostile=True,
                owner_id=id(npc),
                source_name=npc.name or "a villager",
                max_range=c.Villages.MOB_STONE_RANGE,
            )
            stone.from_npc = True
            self.projectiles.append(stone)

    def _lane_clear(self, shooter: NPC, target) -> bool:
        """Whether a villager has a clear lane to what they are shooting at, meaning none of
        their own people standing in it.

        Their shot cannot wound a neighbour any more (`Projectile.from_npc`), but loosing
        one straight through the back of somebody's head still looks like a mistake, and a
        crowded street should thin the volley coming out of the towers rather than leaving
        it untouched. Perpendicular distance to the segment, and only what lies between the
        two of them counts: someone standing behind the shooter is not in the way."""
        dx, dy = target.x - shooter.x, target.y - shooter.y
        span = math.hypot(dx, dy)
        if span == 0:
            return True
        for other in self.npcs:
            if other is shooter or other is target:
                continue
            along = ((other.x - shooter.x) * dx + (other.y - shooter.y) * dy) / span
            if not 0 < along < span:
                continue
            across = abs((other.x - shooter.x) * dy - (other.y - shooter.y) * dx) / span
            if across < c.Villages.FRIENDLY_LANE_WIDTH:
                return False
        return True
