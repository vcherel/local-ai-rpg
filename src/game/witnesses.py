"""Who sees the player do something they should not have, and what they do about it."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from game.entities.npcs import NPC
from llm.decide import decide, later, odds, pick

if TYPE_CHECKING:
    from game.entities.player import Player


class WorldWitnesses:
    """Sight, the witness a crime is seen by, and the report or the look away they give.

    Mixed into `World` beside `WorldSocial`, which keeps the score a report adds to.
    """

    def witness_radius(self) -> float:
        """How far a villager notices a theft right now. Night cuts it, which is what makes
        robbing a house something you do after dark. Shared by the check and the cones the
        renderer draws, so what the player is shown is exactly what is tested."""
        night = c.Crime.NIGHT_WITNESS_MULT if self.daynight.is_night else 1.0
        # Weather is the second thing that shortens it, and it stacks with the dark: a house
        # robbed in fog at night is barely watched at all, which is what makes a fogbank
        # worth waiting for rather than walking through.
        return c.Crime.WITNESS_RADIUS * night * self.weather.sight_mult()

    def watchers_near(self, x: float, y: float) -> list[NPC]:
        """Everyone close enough to (x, y) that their field of view is worth drawing, whether
        or not (x, y) actually falls inside it."""
        radius = self.witness_radius()
        return [npc for npc in self.npcs if not npc.hostile and npc.distance_to_point((x, y)) <= radius]

    def theft_room(self, x: float, y: float):
        """The room a theft at (x, y) happens in: the building whose floor it stands on, or
        None out in the open. The one thing sight is decided against, so a chest, a bed and
        a smashed table all belong to the same room and are watched the same way."""
        return self.building_at(x, y)

    def can_see(self, npc: NPC, x: float, y: float, radius: float, room) -> bool:
        """Whether this villager can catch what is happening at (x, y), which is in `room`.

        Near enough, facing the right way, and standing somewhere the room is open to. No
        line is walked: what a wall does to sight is already answered by which room each of
        the two is standing in, and answering it that way is a handful of comparisons rather
        than a ray per villager per frame.

        Three cases, and they are the whole rule. Out in the open, anyone else out in the
        open sees you. Inside a room, whoever is in that room with you sees you and whoever
        is inside a *different* building sees nothing, because they have their own walls and
        their own roof between. From outside, a room is open along the wall its door and its
        windows are in, and only while one of them is actually open: a villager in front of
        the facade of a house whose door stands open sees straight in, one standing round
        the back does not, and nobody at all sees in once the door is shut and the panes are
        whole. Waiting for the street to clear is still the answer, so is robbing the far
        side of a house, and so now is shutting the door behind you."""
        return npc.sees(x, y, radius) and self.sight_reaches(npc, room)

    def sight_reaches(self, npc: NPC, room) -> bool:
        """Whether this villager is standing anywhere `room` is open to, the half of `can_see`
        the walls answer and the wedge knows nothing about.

        Its own method because the cones are drawn off it: a villager the walls have already
        answered is not drawn at all, so a wedge lying across the player is never a wedge
        that cannot see them."""
        standing_in = self.building_at(npc.x, npc.y)
        if room is None:
            return standing_in is None
        if standing_in is not None:
            return standing_in is room
        nx, ny = room.outward()
        if (npc.x - room.x) * nx + (npc.y - room.y) * ny <= 0:
            return False
        # The facade is a wall like the other three until something in it is open. A door
        # standing open, a door beaten down and a window put through are the three, and the
        # last is why going in through the pane is not free: the hole stays a hole.
        return room.door_open or room.door_broken or bool(room.broken_windows)

    def vision_polygon(self, npc: NPC, radius: float, rays: int = 12) -> list[tuple]:
        """The wedge this villager is looking down, in world coordinates: their own position
        followed by the far end of each ray.

        Nothing cuts it short, because nothing cuts `can_see` short either: the wedge is the
        angle and the distance, and which side of a wall the two of them stand on is the
        other half of the rule rather than a bite out of this shape. Drawing it is a dozen
        points, so there is nothing left worth caching."""
        half = math.radians(c.Crime.VIEW_CONE_DEG) / 2
        facing = npc.orientation - math.pi / 2
        points = [(npc.x, npc.y)]
        for step in range(rays + 1):
            angle = facing - half + 2 * half * step / rays
            points.append((npc.x + math.cos(angle) * radius, npc.y + math.sin(angle) * radius))
        return points

    def theft_witness(self, x: float, y: float) -> NPC | None:
        """Whoever sees the player helping themselves at (x, y), or None if nobody is looking.

        Deliberately no roll: near enough, facing the right way and standing where the room
        is open to them is the whole test, so getting caught is a decision the player made
        and not luck. All three are what the renderer draws on the ground while a chest or a
        bed is in reach, so which side of the house you rob is a real answer rather than a
        guess. Anyone already hostile is past caring what else the player takes."""
        radius = self.witness_radius()
        room = self.theft_room(x, y)
        seen = [npc for npc in self.watchers_near(x, y) if self.can_see(npc, x, y, radius, room)]
        return min(seen, key=lambda npc: npc.distance_to_point((x, y)), default=None)

    def squat_witness_radius(self) -> float:
        """How far a stranger asleep in somebody's bed is noticed from, right now.

        Wider than a theft's, because a night is hours rather than an instant, and cut by
        the same thing: the light. Full in daylight, down to `Crime.NIGHT_WITNESS_MULT` of
        itself at the depth of night, so being up and gone before the street is worth as
        much as robbing a house after dark is."""
        return c.Crime.SQUAT_WITNESS_RADIUS * (1.0 - (1.0 - c.Crime.NIGHT_WITNESS_MULT) * self.daynight.darkness)

    def squatter_witness(self, x: float, y: float) -> NPC | None:
        """Whoever finds the player asleep in a bed that isn't theirs, or None if nobody
        does.

        Two ways of being found, and they are the whole rule. The household is the first:
        whoever lives in this room walks past its bed every morning, so neither the light
        nor which way they happen to be turned saves the player from the people whose house
        it is, unless they are already asleep in it themselves. Everybody else is answered
        exactly as a theft is (`can_see`): near enough for the hour's light
        (`squat_witness_radius`), facing this way, and standing somewhere the room is open
        to them. Somebody still in their own bed across the street has seen
        nothing at all.

        Which makes an empty house on the dark edge of a settlement a bed the player can
        actually take, and the tavern with its keeper asleep next door a gamble."""
        village = self.village_at(x, y)
        if village is None:
            return None
        room = self.theft_room(x, y)
        radius = self.squat_witness_radius()
        found = []
        for npc in self.npcs:
            if npc.hostile or not village.contains_point(npc.x, npc.y):
                continue
            # Asleep is asleep, in your own bed as much as in anybody else's: a household
            # that has turned in catches nothing, which is what makes the tavern with its
            # keeper already down for the night a room worth taking, and a gamble on the
            # hour rather than on which door you picked.
            lives_here = room is not None and not npc.asleep and self._home_for(npc) is room
            if lives_here or (not npc.asleep and self.can_see(npc, x, y, radius, room)):
                found.append(npc)
        return min(found, key=lambda npc: npc.distance_to_point((x, y)), default=None)

    def report_crime(self, x: float, y: float, player: Player) -> NPC | None:
        """Somebody wrecking a room somebody else owns, answered exactly as a theft is: the
        one villager who saw it turns on the player and nobody else hears about it. Its own
        ledger, though, and its own wording: breaking a chair is not taking one. The cones
        are on the ground the whole time the player is standing indoors, so a swing taken in
        front of a witness is a decision rather than an ambush."""
        witness = self.theft_witness(x, y)
        if witness is not None:
            self.catch_thief(witness, player, "vandalism")
        return witness

    def catch_thief(self, npc: NPC, player: Player, offence: str = "theft"):
        """One villager catches the player at something, and makes up their mind about it.

        Being seen is still the cones and nothing else. What they do about it is theirs: a
        decision (`llm/decide.py`) over telling, looking away, or asking to be paid to
        forget it, off who they are and how they feel about the player. They round on the
        player and stand there deciding with a "?" over them for at most
        `Crime.WITNESS_THINK_MS`, and `settle_witnesses` carries it out. Somebody already
        deciding, or already waiting on their money, is not asked twice."""
        if npc.pondering is not None or npc.hushing:
            return
        if npc.hostile:
            self._report(npc, player, offence)
            return
        npc.aim_at(player.x, player.y)
        npc.pondering_offence = offence
        npc.pondering_until = pygame.time.get_ticks() + c.Crime.WITNESS_THINK_MS
        args = (
            self.context or c.World.FALLBACK_CONTEXT,
            npc.name,
            npc.temperament,
            npc.affinity,
            offence,
            self.notoriety_at(npc.x, npc.y),
        )
        npc.pondering = later(lambda: self._witness_decides(*args))
        self.witnesses.append(npc)

    @staticmethod
    def _witness_odds(temperament: str | None, affinity: float) -> dict:
        return odds(
            c.Crime.WITNESS_OFFLINE,
            c.Crime.WITNESS_TEMPERAMENT_ODDS.get(temperament),
            {"look_away": affinity / c.Affinity.START},
        )

    @classmethod
    def _witness_decides(cls, context, name, temperament, affinity, offence, notoriety) -> str:
        """The worker's half of `catch_thief`: what the witness does, as a label.

        Asked of the model as a narrator rather than in the witness's own voice: asked as
        themselves it hardly ever raised the alarm whoever they were, asked what somebody
        of their kind does it answers like somebody who has met people."""
        who = name or "The villager"
        kind = c.Temperament.KINDS[temperament][0] if temperament in c.Temperament.KINDS else "an ordinary sort"
        caught = {
            "theft": "helping themselves to what is in a chest in somebody's house",
            "squatting": "asleep in a bed that is not theirs",
            "vandalism": "wrecking a room in somebody's house",
        }
        situation = (
            f"{who} is a villager: {kind}. They have just caught the player {caught.get(offence, caught['theft'])}."
        )
        if notoriety >= c.Notoriety.NO_WARNING_LEVEL:
            situation += " Word is the player has done worse elsewhere."
        return decide(
            situation,
            f"What does {who} do?",
            {
                "report": "Raise the alarm",
                "look_away": "Pretend not to have seen anything",
                "blackmail": "Demand a bribe",
            },
            f"You narrate an RPG with this context: {context}.",
            "witness",
            offline=cls._witness_odds(temperament, affinity),
            # Their liking is the game's to weigh rather than the model's: told the witness
            # likes the player, it had a brave one ask for a bribe.
            prior=odds(c.Crime.WITNESS_PRIOR, {"look_away": affinity / c.Affinity.START}),
            trust=c.Crime.WITNESS_MODEL_TRUST,
        ).choice

    def settle_witnesses(self, player: Player) -> list[NPC]:
        """Carry out whatever the witnesses have decided, and what the ones waiting on hush
        money do when it does not come. Once a frame. Returns whoever turned on the player,
        so the caller can strike their quests off."""
        turned = []
        now = pygame.time.get_ticks()
        for npc in list(self.witnesses):
            pending = npc.pondering
            if not pending.done and now < npc.pondering_until:
                continue
            self.witnesses.remove(npc)
            npc.pondering = None
            if npc not in self.npcs:
                continue
            # A model too busy to answer in time is answered for it, off the same odds.
            choice = pending.poll() if pending.done else None
            if choice is None:
                choice = pick(self._witness_odds(npc.temperament, npc.affinity))
            if choice == "blackmail" and player.coins < c.Crime.HUSH_MIN:
                choice = "report"
            name = npc.name or "A villager"
            if choice == "look_away":
                if self.notify:
                    self.notify(f"{name} saw that, and looks away", c.Colors.MUTED)
            elif choice == "blackmail":
                npc.hush_price = max(c.Crime.HUSH_MIN, round(player.coins * c.Crime.HUSH_SHARE))
                npc.hush_until = time.time() + c.Crime.HUSH_WAIT_S
                self.hushers.append(npc)
                if self.notify:
                    self.notify(f"{name} saw that. {npc.hush_price} coins and they forget it", c.Colors.ORANGE)
            elif self._report(npc, player, npc.pondering_offence) is not None:
                turned.append(npc)
        for npc in list(self.hushers):
            if npc.hush_price and time.time() < npc.hush_until:
                continue
            self.hushers.remove(npc)
            if not npc.hush_price or npc not in self.npcs:
                continue
            npc.hush_price = 0
            if self.notify:
                self.notify(f"{npc.name or 'A villager'} got tired of waiting", c.Colors.ORANGE)
            if self._report(npc, player, npc.pondering_offence) is not None:
                turned.append(npc)
        return turned

    def pay_hush(self, npc: NPC, player: Player) -> bool:
        """Pay a witness what they asked to forget it. False when the purse is short."""
        if not npc.hushing or player.coins < npc.hush_price:
            return False
        player.add_coins(-npc.hush_price)
        npc.hush_price = 0
        play_sound("pickup")
        if self.notify:
            self.notify(f"{npc.name or 'They'} pockets it and forgets what they saw", c.Colors.YELLOW)
        return True

    def _report(self, npc: NPC, player: Player, offence: str) -> NPC | None:
        """The witness tells: they warn the player or come for them. Returns whoever turned
        hostile, or None when it was only a warning.

        The single exception to violence's all-or-nothing rule: what one person catches is
        between them and the player, so the rest of the village goes on with its day.
        Swinging back at the one who caught you is what turns the whole place, through the
        usual `provoke_village`. They cool off on their own clock like anyone else, a while
        after the player has stopped taking their things.

        Being caught runs the same ladder a blow does (`strike_village`), on the ledger of
        whatever kind of thing it was, so the first time the player is caught at each is
        answered with a shout rather than a knife."""
        if not self.strike_village(npc, player, offence):
            return None
        npc.anger(c.Crime.THEFT_ANGER_S)
        self.record_deed(npc.x, npc.y, c.Notoriety.WEIGHT_THEFT)
        if self.notify:
            name = npc.name or "A villager"
            caught = {
                "theft": f"{name} catches you in the act!",
                "squatting": f"{name} finds you asleep in their bed!",
                "vandalism": f"{name} sees what you did to the place!",
            }
            self.notify(caught.get(offence, f"{name} catches you in the act!"), c.Colors.RED)
        return npc
