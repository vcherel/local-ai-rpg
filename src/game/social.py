"""What a settlement thinks of the player, and what it does about it.

Mixed into `World` beside `WorldPlaces`, on the same entity lists. `WorldPlaces` is the
ground and what stands on it; this is the people on that ground keeping score: who saw
what, the warning ladder each offence climbs, a village turning and the blood price that
buys it back, what the country around has heard, the raid a blood night sends, the
notices pinned to a board, and the militia orders an angry town acts on as one.
"""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

import core.constants as c
from core.audio import play_sound
from core.screen_fx import get_banner
from game.entities.boss import Boss
from game.entities.monsters import pick_monster_kind
from game.entities.npcs import NPC
from game.navigation import Point

if TYPE_CHECKING:
    from game.entities.buildings import Building
    from game.entities.monsters import Monster
    from game.entities.player import Player
    from game.entities.village import Village


class WorldSocial:
    """Every settlement's opinion of the player and what it costs them."""

    def _village_crowd(self, npc: NPC) -> tuple:
        """The settlement this NPC belongs to and everyone standing on its grounds. A camper
        or a wandering merchant out in the wilds has no village behind them, only themselves."""
        village = self.village_at(npc.x, npc.y)
        if village is None:
            return None, [npc]
        return village, [other for other in self.npcs if village.contains_point(other.x, other.y)]

    def _strike_key(self, npc: NPC) -> str:
        """Whose patience is being spent. A settlement keeps one ledger for all of its
        people; a camper or a wandering merchant out in the wilds keeps their own, since
        there is nobody behind them to warn the player on their behalf."""
        village = self.village_at(npc.x, npc.y)
        if village is not None:
            return f"{village.chunk[0]}:{village.chunk[1]}"
        return f"lone:{round(npc.home[0])}:{round(npc.home[1])}"

    def strike_village(self, npc: NPC, player: Player, offence: str = c.Villages.DEFAULT_OFFENCE) -> bool:
        """Record an offence of this kind against this settlement and answer whether it has
        run out of patience, which is what actually turns the place on the player.

        Nobody goes from a farmer to a mob over one blow. The first offence of a kind is a
        warning the player can see and hear: whoever it landed on rounds on them, shouts in
        the words that kind of offence deserves, and wears an orange badge for a moment while
        the village goes on with its day. Do the same thing again inside
        `Villages.STRIKE_WINDOW_S` and the ladder is finished. Wait the window out and the
        place has let that one go.

        Every kind keeps its own ledger (`Villages.OFFENCES`), so a shove, a hand in a chest
        and a bed taken for the night are three separate conversations rather than one
        counter the player spends without knowing which of their sins is being counted.

        Two things skip the ladder outright: a settlement already angry (there is nothing
        left to warn about), and a killing, which never comes through here at all."""
        if npc.hostile:
            return True
        key = self._strike_key(npc)
        now = time.time()
        ledger = self.village_strikes.setdefault(key, {})
        record = ledger.get(offence)
        fresh = record is not None and now - record["at"] < c.Villages.STRIKE_WINDOW_S
        count = (record["count"] if fresh else 0) + 1
        # A place that has already heard about the player does not spend a warning on them:
        # the ladder arrives one rung short, which is the whole of what a reputation costs
        # before anybody has drawn anything (`Notoriety.NO_WARNING_LEVEL`).
        if self.notoriety_at(npc.x, npc.y) >= c.Notoriety.NO_WARNING_LEVEL:
            count += 1
        if count >= c.Villages.STRIKES_BEFORE_ANGER:
            ledger.pop(offence, None)
            if not ledger:
                self.village_strikes.pop(key, None)
            return True
        ledger[offence] = {"count": count, "at": now}
        self.shout_warning(npc, player, offence)
        return False

    def warnings_at(self, x: float, y: float) -> list[tuple[str, float]]:
        """Every warning still standing against the player where they are, as (label,
        seconds left), soonest to expire first.

        A warning the player cannot see the end of is a trap: they have no way of knowing
        whether the next stray swing is the one that turns the town. The HUD reads this
        (`Minimap._draw_strips`), so what is drawn is exactly what the ladder will test."""
        village = self.village_at(x, y)
        if village is None:
            return []
        ledger = self.village_strikes.get(f"{village.chunk[0]}:{village.chunk[1]}", {})
        now = time.time()
        pending = []
        for offence, record in ledger.items():
            left = c.Villages.STRIKE_WINDOW_S - (now - record["at"])
            if left > 0:
                pending.append((c.Villages.OFFENCES[offence]["label"], left))
        return sorted(pending, key=lambda entry: entry[1])

    def forget_stale_strikes(self):
        """Drop every warning whose window has run out. The ladder tests the clock itself, so
        this changes nothing about what a village will do; it is what stops the HUD showing a
        countdown that has already reached zero, and what keeps the save from carrying a
        ledger of offences nobody remembers."""
        now = time.time()
        for key in list(self.village_strikes):
            ledger = {
                offence: record
                for offence, record in self.village_strikes[key].items()
                if now - record["at"] < c.Villages.STRIKE_WINDOW_S
            }
            if ledger:
                self.village_strikes[key] = ledger
            else:
                self.village_strikes.pop(key)

    def shout_warning(self, npc: NPC, player: Player, offence: str = c.Villages.DEFAULT_OFFENCE):
        """One villager warning the player off, and their street noticing.

        The warning has to be legible from the fight itself rather than from a line of text
        alone, so it is three things at once: they round on the player, an orange badge goes
        up over their head, and anyone near enough to have heard it looks up too. What they
        shout is what the player actually did: nobody is told to put a bed back."""
        npc.warn(player.x, player.y)
        play_sound("shout")
        for other in self.npcs:
            if other is npc or other.hostile:
                continue
            if other.distance_to_point((npc.x, npc.y)) < c.Villages.MOB_ENGAGE_RANGE:
                other.warn(player.x, player.y)
        if self.notify:
            name = npc.name or "A villager"
            shouts = c.Villages.OFFENCES[offence]["shouts"]
            self.notify(f"{name}: {random.choice(shouts)}", c.Colors.ORANGE)

    def yield_to_player(self, npc: NPC):
        """A villager with no fight left in them throwing down their weapon.

        Cut a farmer to `Villages.ROUT_HP_FRAC` and they used to keep walking at the player
        without swinging, which read as a broken villager rather than a beaten one. This is
        that moment made real: they kneel, their hands are empty, a white flag goes up over
        them and for `Villages.SURRENDER_S` they are nobody's enemy. What the player does
        with somebody who has yielded is theirs to decide, and cutting one down is answered
        without any ladder at all (`WorldCombat._resolve_npc_hit`)."""
        npc.surrender()
        play_sound("shout")
        if self.notify:
            name = npc.name or "A villager"
            self.notify(f"{name} throws down their weapon", c.Colors.WHITE)

    def call_for_help(self, npc: NPC) -> list[NPC]:
        """A militiaman falling back, and what their shout costs the player: everyone who
        hears it. Returns whoever just took up arms because of it.

        The other half of a rout. Whoever took up arms for this place does not kneel; they
        give ground shouting, and a shout is worth more than the sword they were losing
        with. Spent once each (`NPC.called_help`), so a fight that drags on is not a siren."""
        if npc.called_help:
            return []
        npc.called_help = True
        play_sound("shout")
        recruits = [
            other
            for other in self.npcs
            if not other.hostile
            and not other.surrendered
            and other is not npc
            and other.distance_to_point((npc.x, npc.y)) < c.Villages.HELP_SHOUT_RANGE
        ]
        for other in recruits:
            other.anger(c.Villages.ANGER_S)
        if self.notify:
            name = npc.name or "A villager"
            self.notify(f"{name}: {random.choice(c.Villages.HELP_SHOUTS)}", c.Colors.RED)
        return recruits

    def provoke_village(self, npc: NPC) -> list[NPC]:
        """Turn a settlement on the player after one of its people is struck, returning
        everyone who just went hostile (so the caller can strike their quests off).

        Everyone whose home village this is drops what they were doing and comes for the
        player, their goodwill gone and any quest they were offering with it. Violence in
        town is a decision, not a stray click, but it is one the place eventually lives down:
        the anger runs on a clock (`Villages.ANGER_S`), and swinging again while they are
        still furious pushes that clock further out. Killing someone is what makes it
        permanent, and that goes through `hold_grudge` instead.
        """
        village, crowd = self._village_crowd(npc)

        newly_hostile = [other for other in crowd if not other.hostile]
        for other in crowd:
            other.anger(c.Villages.ANGER_S)
        # The dogs go with their people. A settlement turning on the player turns everything
        # it keeps on the player, and a dog is faster than a villager.
        if village is not None:
            key = f"{village.chunk[0]}:{village.chunk[1]}"
            for dog in self.critters:
                if dog.village_key == key:
                    dog.aggro()
        if newly_hostile:
            self.record_deed(npc.x, npc.y, c.Notoriety.WEIGHT_BRAWL)
        if newly_hostile and self.notify:
            name = village.name if village is not None and village.name else "The locals"
            self.notify(f"{name} turns on you!", c.Colors.RED)
        return newly_hostile

    def hold_grudge(self, npc: NPC) -> list[NPC]:
        """A villager is dead by the player's hand, and that one is never forgiven.

        Anger is a countdown; a killing is not. Everyone on this settlement's grounds is
        turned for good, with no clock left to run out, which is what keeps a death heavier
        than a brawl now that a brawl can be waited out."""
        village, crowd = self._village_crowd(npc)
        newly_hostile = [other for other in crowd if not other.hostile]
        for other in crowd:
            if other is not npc:
                other.anger(c.Villages.ANGER_S, permanent=True)
        # The rest of the world hears about it too. A grudge stops at the settlement that
        # holds it; what the neighbours know is the deed, and a killing is most of a
        # reputation on its own (`notoriety_at`).
        self.record_deed(npc.x, npc.y, c.Notoriety.WEIGHT_KILL)
        if self.notify:
            name = village.name if village is not None and village.name else "The locals"
            self.notify(f"{name} will never forgive you", c.Colors.RED)
        return newly_hostile

    def pacify_village(self, x: float, y: float) -> Village | None:
        """The settlement the player just died to lets it go, and only that one.

        Death is the price paid; carrying on a fight with a corpse's killers on the other
        side of the world is not part of it, and the player waking up at spawn to a town
        still barred against them has nothing left to do about it. So the place that killed
        them forgets outright, grudge included: they got their own back. Every other village
        keeps whatever it held, which is why this takes a point rather than sweeping the
        world.

        The point is where the player fell, so dying just outside the wall counts as dying
        to the town whose archers did it."""
        village = self.village_at(x, y, c.Villages.DEFEND_MARGIN)
        if village is None:
            village = min(
                (
                    other
                    for other in self.villages
                    if other.distance_to_point((x, y)) < c.Entities.NPC_HOSTILE_RANGE + other.grounds_radius
                ),
                key=lambda other: other.distance_to_point((x, y)),
                default=None,
            )
        if village is None:
            return None
        for npc in self.npcs:
            if not village.contains_point(npc.x, npc.y):
                continue
            npc.grudge = False
            npc.hostile_until = 0.0
            npc.affinity = max(npc.affinity, c.Affinity.FORGIVEN)
        key = f"{village.chunk[0]}:{village.chunk[1]}"
        self.village_strikes.pop(key, None)
        for dog in self.critters:
            if dog.village_key == key:
                dog.hostile = False
        # The gates come back off the bar on the next frame of `_work_gates` now that nobody
        # inside is angry, so the player can walk back into the place they died in.
        return village

    # ------------------------------------------------------------------ word of mouth

    def record_deed(self, x: float, y: float, weight: float):
        """Remember that the player did something here that people talk about.

        A grudge belongs to the settlement holding it, which left the town an hour's walk
        away greeting a murderer as a stranger. A deed belongs to the ground instead: it is
        kept as a point, a weight and the moment it happened, and every settlement inside
        `Notoriety.TRAVEL_DISTANCE` reads the same sum. Nothing here turns anybody hostile;
        what it spends is patience and goodwill, which is what word of mouth spends."""
        self.deeds.append({"x": x, "y": y, "weight": weight, "at": time.time()})
        self.forget_stale_deeds()

    def forget_stale_deeds(self):
        """Drop everything nobody repeats any more. Called wherever a deed is recorded and
        once a frame with the strikes, so what the HUD reads, what a shop charges and what
        the save carries are all the same short list."""
        cutoff = time.time() - c.Notoriety.FADE_S
        self.deeds = [deed for deed in self.deeds if deed["at"] > cutoff]

    def notoriety_at(self, x: float, y: float) -> float:
        """How much the people standing here have heard about the player, 0 to 1.

        Each deed fades two ways at once, with the distance from where it was done and with
        the time since. Both are straight lines rather than curves: what matters is that a
        killing two valleys over is worth something and a killing on the next street is
        worth most of a reputation, and a straight line says that as well as anything the
        player could not see anyway. Clamped at `Notoriety.FULL`, so the effects have a top."""
        now = time.time()
        total = 0.0
        for deed in self.deeds:
            distance = math.hypot(deed["x"] - x, deed["y"] - y)
            if distance >= c.Notoriety.TRAVEL_DISTANCE:
                continue
            age = now - deed["at"]
            if age >= c.Notoriety.FADE_S:
                continue
            reach = 1.0 - distance / c.Notoriety.TRAVEL_DISTANCE
            freshness = 1.0 - age / c.Notoriety.FADE_S
            total += deed["weight"] * reach * freshness
        return min(total, c.Notoriety.FULL)

    def notoriety_label(self, x: float, y: float) -> str | None:
        """What to call the player's standing here, or None while nobody has heard anything
        worth a word. The one place the level is turned into language, so the strip under the
        minimap and anything else that ever says it cannot drift apart."""
        level = self.notoriety_at(x, y)
        if level < c.Notoriety.LABELS[0][0]:
            return None
        return next(label for threshold, label in c.Notoriety.LABELS if level < threshold)

    # ------------------------------------------------------------------ the blood price

    def blood_price(self, village: Village) -> int:
        """What this settlement wants to let the player back in.

        Priced off what was done and off what the place is: a brawl it would have forgotten
        on its own is cheap, a killing it never forgets is not, and a deep wilds town asks
        more than a border hamlet. Rounded (`Amends.ROUNDING`), because a price is a figure
        somebody says out loud."""
        price = c.Amends.BASE + c.Amends.PER_TIER * village.tier
        if any(npc.grudge for npc in self.npcs if village.contains_point(npc.x, npc.y)):
            price *= c.Amends.GRUDGE_MULT
        step = c.Amends.ROUNDING
        return int(round(price / step) * step)

    def amends_at(self, x: float, y: float) -> tuple | None:
        """The settlement standing here that wants the player dead and what it would take to
        stop, as (village, price), or None where there is nothing to pay for.

        Read by the strip under the minimap and by the key that pays, so what the player is
        quoted is exactly what they are charged. The margin is the one a village defends
        itself out to: standing at the gate of a town that has barred itself is the ordinary
        way this comes up, and that spot is outside the wall."""
        village = self.village_at(x, y, c.Villages.DEFEND_MARGIN)
        if village is None:
            return None
        if not any(npc.hostile for npc in self.npcs if village.contains_point(npc.x, npc.y)):
            return None
        return village, self.blood_price(village)

    def pay_blood_price(self, player: Player) -> tuple | None:
        """Buy this settlement's forgiveness with coins, or answer why it cannot be bought.

        Returns (village, price) once it is paid and None when there is nobody here to pay,
        so the caller says the one thing that is true. Everything it undoes is what dying
        here would have undone (`pacify_village`), plus the deeds done on this ground: the
        village that was paid stops repeating them, which is the only thing that ever takes
        notoriety back."""
        found = self.amends_at(player.x, player.y)
        if found is None:
            return None
        village, price = found
        if player.coins < price:
            return None
        player.add_coins(-price)
        self.pacify_village(village.x, village.y)
        self.settle_deeds(village)
        play_sound("quest_complete")
        return village, price

    def settle_deeds(self, village: Village):
        """Rub out what was done on one settlement's ground. Paid for, so nobody there
        brings it up again, and the neighbours stop hearing about it with them: a deed is
        remembered by where it happened, and this is where it happened."""
        reach = village.grounds_radius + c.Villages.DEFEND_MARGIN
        self.deeds = [deed for deed in self.deeds if math.hypot(deed["x"] - village.x, deed["y"] - village.y) > reach]

    def raid_village(self, village: Village, player: Player) -> bool:
        """Point a blood night at a settlement: a wave stood up outside its grounds and left
        to walk in, and whether one actually started.

        Nothing about the fight itself is new. The raiders are ordinary monsters posted on
        the settlement (`Monster.post_at`), so they roam toward it while they have seen
        nobody and take whoever they meet; the militia split, the panic, the gates and the
        tower archers all answer them as they answer anything else that walked in. What is
        new is the reason for the player to stand in somebody else's street: a village that
        was defended is the one thing in the game that raises a whole settlement's opinion
        at once (`end_raid`).

        Only a settlement the player is near enough to reach is ever raided, and never one
        already fighting them: a town that wants the player dead is not a town they can save.
        """
        if self.raid is not None or not village.discovered:
            return False
        if village.distance_to_point((player.x, player.y)) > c.Raid.MAX_DISTANCE:
            return False
        if any(npc.hostile for npc in self.npcs if village.contains_point(npc.x, npc.y)):
            return False

        key = f"{village.chunk[0]}:{village.chunk[1]}"
        count = c.Raid.SIZE_BY_TIER[min(village.tier, len(c.Raid.SIZE_BY_TIER) - 1)]
        stood_up = 0
        for index in range(count):
            angle = 2 * math.pi * (index + random.random()) / count
            reach = village.grounds_radius + c.Raid.SPAWN_MARGIN
            x = village.x + math.cos(angle) * reach
            y = village.y + math.sin(angle) * reach
            monster = self._new_monster(x, y, c.Raid.DANGER_BONUS)
            spot = self.free_spot_near(x, y, monster.kind.size / 2)
            if self.blocked(*spot, monster.kind.size / 2):
                continue
            monster.x, monster.y = spot
            monster.raid_key = key
            # Posted on the settlement rather than on where it was stood up: it roams
            # toward the place while it has seen nobody, which is a raid arriving instead
            # of a ring of monsters waiting to be walked into.
            monster.post_at(village.x, village.y, village.grounds_radius)
            self.monsters.append(monster)
            stood_up += 1
        if not stood_up:
            return False

        self.raid = {
            "key": key,
            "x": village.x,
            "y": village.y,
            # Measured past this settlement's own grounds rather than from its middle: a
            # walled town is a thousand paces across, and a leash drawn from the plaza would
            # have written half of its own raiders off before they reached the wall.
            "leash": village.grounds_radius + c.Raid.LEASH,
            "kills": 0,
            "until": time.time() + c.Raid.DURATION_S,
        }
        name = village.name or "A settlement"
        get_banner().trigger("RAID", f"{name} is under attack", c.Colors.RED)
        play_sound("shout")
        return True

    def raiders(self) -> list:
        """Whatever is left of the raid, wherever it has got to. Its leash reaches past the
        settlement's grounds rather than stopping at them: a monster chasing a militiaman
        into the fields is still part of the raid, and one that has wandered `Raid.LEASH`
        beyond the place it was sent at is a monster again."""
        if self.raid is None:
            return []
        return [
            monster
            for monster in self.monsters
            if monster.raid_key == self.raid["key"]
            and math.hypot(monster.x - self.raid["x"], monster.y - self.raid["y"]) <= self.raid["leash"]
        ]

    def credit_raid_kill(self, monster: Monster):
        """One raider down by the player's hand. Counted rather than paid on the spot: what
        the village is grateful for is the raid being over, not each body."""
        if self.raid is not None and monster.raid_key == self.raid["key"]:
            self.raid["kills"] += 1

    def update_raid(self):
        """End the raid once there is nothing left of it or its time has run out, and pay
        for it. Called once a frame with everything else the surface does.

        The thanks are the whole point and they are deliberately not a reward the player can
        farm: a raid they took no real part in (`Raid.THANKS_MIN_KILLS`) pays nothing at all,
        and what it pays is affinity with everyone still standing, which is the mirror of
        `provoke_village` turning all of them at once."""
        if self.raid is None:
            return
        if self.raiders() and time.time() < self.raid["until"]:
            return
        kills = self.raid["kills"]
        village = self.village_at(self.raid["x"], self.raid["y"])
        self.raid = None
        if kills < c.Raid.THANKS_MIN_KILLS or village is None:
            return
        for npc in self.npcs:
            if village.contains_point(npc.x, npc.y) and not npc.hostile:
                npc.affinity = min(c.Affinity.MAX, npc.affinity + c.Raid.THANKS_AFFINITY)
        if self.notify:
            name = village.name or "The village"
            self.notify(f"{name} owes you for the night", c.Colors.GREEN)

    # ------------------------------------------------------------------ the notice board

    def board_in_reach(self, player: Player) -> Village | None:
        """The notice board the player is standing at, or None. One per settlement, on the
        rim of its plaza (`Village.board_pos`)."""
        for village in self.villages:
            if village.distance_to_point((player.x, player.y)) > village.grounds_radius:
                continue
            bx, by = village.board_pos()
            if math.hypot(player.x - bx, player.y - by) <= c.Board.INTERACT_DISTANCE:
                return village
        return None

    def board_offers(self, village: Village) -> list[dict]:
        """What is pinned to this settlement's board right now, rolled here and kept on the
        village until the board is worth walking back to (`Board.REFRESH_S`).

        Every one of them is an ordinary quest written the way the model would have written
        it: the same `{has_quest, quest_type, ...}` reading `QuestSystem` builds from, so a
        notice taken off a board and a task agreed to in a conversation are the same object
        by the time anything else in the game sees it. Rolled locally because a board is
        what the game has to offer when the one model in it is busy.

        Session only, like the lanes between the houses: a notice nobody took is not
        something a save has to carry, and a board is re-read on the next visit anyway."""
        now = time.time()
        if village.notices and now < village.notices_rolled_at + c.Board.REFRESH_S:
            return village.notices
        village.notices_rolled_at = now
        # By title, so a board never pins the same hunt up twice: two notices asking for six
        # slimes are one notice and an empty peg.
        rolled: dict[str, dict] = {}
        for _ in range(c.Board.OFFERS * 3):
            if len(rolled) >= c.Board.OFFERS:
                break
            offer = self._roll_notice(village)
            if offer is not None:
                rolled.setdefault(offer["title"], offer)
        village.notices = list(rolled.values())
        return village.notices

    def _roll_notice(self, village: Village) -> dict | None:
        """One notice: a hunt, a camp to empty or a thing to bring back, whichever the world
        around this settlement can actually supply. Each is a title the board shows and the
        quest reading the quest system builds from."""
        kinds = ["kill_mob", "fetch"]
        camp = self.find_bandit_camp(village.x, village.y, c.Quests.MIN_TARGET_DISTANCE)
        if camp is not None:
            kinds.append("clear_camp")
        kind = random.choice(kinds)
        if kind == "clear_camp":
            return {
                "title": "Bandits in the wilds",
                "info": {
                    "has_quest": True,
                    "quest_type": "clear_camp",
                    "quest_description": "A camp of bandits is preying on the road. Empty it.",
                    "item_name": "",
                    "monster_hint": "",
                    "kill_count": "",
                    "reward_item": "",
                },
            }
        if kind == "kill_mob":
            center = c.World.WORLD_SIZE // 2
            monster = pick_monster_kind(math.hypot(village.x - center, village.y - center))
            count = random.randint(*c.Board.KILL_COUNT_RANGE)
            return {
                "title": f"Wanted: {count} {monster.name}",
                "info": {
                    "has_quest": True,
                    "quest_type": "kill_mob",
                    "quest_description": f"{monster.name}s have been seen too close to the houses. Thin them out.",
                    "item_name": "",
                    "monster_hint": monster.name,
                    "kill_count": str(count),
                    "reward_item": "",
                },
            }
        item = random.choice(c.Board.WANTED_ITEMS)
        return {
            "title": f"Wanted: {item}",
            "info": {
                "has_quest": True,
                "quest_type": "fetch",
                "quest_description": f"Somebody here needs {item.lower()} and has no way of fetching it themselves.",
                "item_name": item,
                "monster_hint": "",
                "kill_count": "",
                "reward_item": "",
            },
        }

    def board_poster(self, village: Village) -> NPC | None:
        """Who a notice off this board turns out to have been posted by: somebody who lives
        here, is still speaking to the player and is not already waiting on a task.

        A board quest is given by a person rather than by a plank, so handing it in is the
        conversation every other quest is handed in through and nothing about the tracker,
        the arrow or the reward had to learn that boards exist."""
        candidates = [
            npc
            for npc in self.npcs
            if village.contains_point(npc.x, npc.y)
            and not npc.hostile
            and not npc.has_active_quest
            and not npc.is_merchant
        ]
        if not candidates:
            return None
        # Somebody who already has a name first. A name is generated on a worker and waited
        # for when it is not ready (`NPCNameGenerator.get_name`), and a board is read in the
        # middle of a street rather than at the start of a conversation: nothing here is
        # worth holding a frame for when the village is full of people already named.
        named = [npc for npc in candidates if npc.name]
        return random.choice(named or candidates)

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
        windows are in: a villager standing in front of the facade sees straight in, one
        standing round the back does not. Waiting for the street to clear is still the
        answer, and now so is robbing the far side of a house."""
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
        return (npc.x - room.x) * nx + (npc.y - room.y) * ny > 0

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
        it is. Everybody else is answered exactly as a theft is (`can_see`): near enough for
        the hour's light (`squat_witness_radius`), facing this way, and standing somewhere
        the room is open to them. Somebody still in their own bed across the street has seen
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
            lives_here = room is not None and self._home_for(npc) is room
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

    def catch_thief(self, npc: NPC, player: Player, offence: str = "theft") -> NPC | None:
        """One villager catches the player at something, and either warns them or comes for
        them. Returns whoever turned hostile, or None when it was only a warning.

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

    def militia_orders(self) -> tuple[dict, dict]:
        """What each villager is doing about the monsters inside their settlement: who is
        going to meet one, and who is running for a door.

        Two dicts keyed by `id(npc)`: the monster to fight, and the building to hide in. A
        settlement is not a crowd of identical people, so the roll is per villager and made
        once from their home (`NPC.is_militia`): the same house always sends the same person
        out, and the rest bolt. Worked out once a frame for the whole world rather than per
        NPC, since the intruders are the short list and the villagers are the long one."""
        fight: dict = {}
        flee: dict = {}
        # A boss on the grounds is an intruder like any other, and the one that counts most:
        # a settlement that went about its day around a thing twice the size of its gate
        # read as the world forgetting to look. It carries its own, wider radii, because a
        # boss is a reason to run from further off than a wolf is.
        # Anything still in a disguise is not on this list either: a village that turned out
        # its militia on a husk nobody has seen through would be doing the player's looking
        # for them, and would put the thing down before they ever met one.
        arrived = [m for m in self.monsters if m.revealed] + [boss for boss in self.bosses if boss.rising <= 0]
        intruders = [m for m in arrived if self.village_at(m.x, m.y, c.Villages.DEFEND_MARGIN) is not None]
        # Somebody being bitten is its own fight, so the loop is still walked with nothing on
        # anyone's grounds: what is chewing on a farmer out in a field is nobody's intruder.
        if not intruders and not any(npc.threatened_by is not None for npc in self.npcs):
            return fight, flee

        for npc in self.npcs:
            if npc.hostile:
                # Already coming for the player: the monster is the least of their problems.
                continue
            # Anybody something has actually bitten fights back, militia roll or not and
            # wherever they are standing: the roll decides who walks towards a fight, not
            # who defends themselves in one. They break like anyone else once they are cut
            # down far enough (`NPC.routed`), so a farmer swings, loses and runs for a door
            # rather than dying on the spot or never lifting a hand.
            threat = npc.threat
            if threat is not None:
                if not npc.routed:
                    fight[id(npc)] = threat
                    continue
                refuge = self._refuge_for(npc, threat)
                if refuge is not None:
                    flee[id(npc)] = refuge
                    continue
            if not intruders:
                continue
            nearest = min(intruders, key=lambda m: npc.distance_to_point((m.x, m.y)))
            distance = npc.distance_to_point((nearest.x, nearest.y))
            boss = isinstance(nearest, Boss)
            if npc.is_militia and not npc.routed:
                if distance <= (c.Villages.BOSS_DEFEND_RADIUS if boss else c.Villages.DEFEND_RADIUS):
                    fight[id(npc)] = nearest
            elif distance <= (c.Villages.BOSS_PANIC_RADIUS if boss else c.Villages.PANIC_RADIUS):
                refuge = self._refuge_for(npc, nearest)
                if refuge is not None:
                    flee[id(npc)] = refuge
        return fight, flee

    def _refuge_for(self, npc: NPC, threat=None) -> Building | Point | None:
        """Where this one breaks for: the nearest building they can get behind a door of, or
        open ground away from `threat` when there is no door within reach.

        Any door will do; a frightened person takes the nearest one, not their own. The
        second answer is what a rout in a field is: with no shelter this used to give back
        nothing at all, and the caller fell straight through to the ordinary orders, so a
        farmer cut to nothing out in the open turned round and fought on at full aggression.
        A rout has to end in something, and running is the something."""
        shelters = [b for b in self.buildings_near(npc.x, npc.y) if b.has_door and not b.door_broken]
        nearest = min(shelters, key=lambda b: npc.distance_to_point((b.x, b.y)), default=None)
        if nearest is not None or threat is None:
            return nearest
        angle = math.atan2(npc.y - threat.y, npc.x - threat.x)
        return Point(npc.x + math.cos(angle) * c.Villages.ROUT_RUN, npc.y + math.sin(angle) * c.Villages.ROUT_RUN)

    def house_to_rob(self, npc: NPC) -> Building | None:
        """A house in this NPC's village whose chest nobody has emptied yet, for a steal quest
        to name. None out in the wilds, or in a village already picked clean."""
        village = self.village_at(npc.x, npc.y)
        if village is None:
            return None
        houses = [
            building
            for building in self.buildings
            # A room whose furniture had to be shuffled round the neck of an L can end up
            # with nowhere to stand a chest: a quest may not send the player to rob one.
            if building.kind == "house"
            and not building.looted
            and building.interior_layout()["chest"] is not None
            and village.contains_point(building.x, building.y)
        ]
        return random.choice(houses) if houses else None
