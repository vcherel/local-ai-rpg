"""What a blow does to the built world rather than to a body.

Mixed into `World` beside `WorldCombat`, which is what decides who was hit and for how
much. Split out because the two answer different questions and only one of them is ever the
reason to open the file: a change to what a swing takes off a hit-point pool is a change
here, and a change to what a swing catches is a change there. Everything in here works the
same way, whatever it is standing in front of: the blow comes off a pool, the prop flinches
while it holds, and only the blow that empties the pool pays anything.
"""

from __future__ import annotations

import itertools
import math
import random
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import get_shake
from core.particles import get_particles
from core.screen_fx import get_hitstop
from game.entities.breakables import Breakable
from game.entities.buildings import Building
from game.entities.critter import Critter
from game.entities.items import Item
from game.entities.poi import PointOfInterest
from game.loot import break_crate, open_poi_cache

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


class WorldBreaking:
    """Everything the world is made of that answers a weapon: a house's furniture and its
    windows, the door and the barred gate across a gap, the firewood against a wall, a tree,
    a boulder, an outdoor prop and a landmark's cache.

    Mixed into `World`, which owns the lists and the lookups these methods read
    (`buildings_in_range`, `scenery_near`, `pois`, `breakables`, `items`). The wear each of
    them draws while it holds is `WorldGore`'s, and what a blow is worth before it gets here
    is `WorldCombat`'s.
    """

    def _swing_at_scenery(self, player, quest_system, arch, pos, hit_radius, base_damage):
        """Nothing living in range: the swing goes into the scenery. Props take the weapon's
        damage rather than breaking on contact, so a heavy hammer clears a barrel in one blow
        and a dagger has to work at it."""
        prop_damage = max(1, round(base_damage * arch.damage_mult))
        blow = player.orientation

        for building in self.buildings_in_range(*pos, c.World.CHUNK_SIZE):
            # Only the floor the swing actually lands on: furniture is reached by standing
            # in the room with it, never through the wall. A bed against the front wall used
            # to take the blow aimed at the window beside it, swung from the street.
            if not any(floor.collidepoint(*pos) for floor in building.interior_rects()):
                continue
            hit = building.damage_prop_at(pos, hit_radius, prop_damage)
            if hit is not None:
                index, rect, kind, destroyed = hit
                if destroyed:
                    self._break_prop(player, building, rect, kind)
                else:
                    self._prop_chip(
                        rect.centerx, rect.centery, (150, 110, 70), "crate_break", building.prop_key(index), blow
                    )
                return

        gate_hit = self._gate_in_reach(pos, hit_radius)
        if gate_hit is not None:
            self._hit_gate(*gate_hit, prop_damage, blow)
            return

        poi_hit = next(
            (
                p
                for p in self.pois
                if p.has_loot and not p.looted and p.distance_to_point(pos) < hit_radius + c.PointsOfInterest.HIT_RADIUS
            ),
            None,
        )
        if poi_hit is not None:
            self._hit_poi(player, poi_hit, prop_damage, blow)
            return

        prop_poi = next(
            (
                p
                for p in self.pois
                if p.wreckable and p.distance_to_point(pos) < hit_radius + c.PointsOfInterest.HIT_RADIUS
            ),
            None,
        )
        if prop_poi is not None:
            self._wreck_poi(prop_poi, prop_damage, blow)
            return

        breakable = next(
            (b for b in self.breakables if b.distance_to_point(pos) < hit_radius + c.Breakables.HIT_RADIUS), None
        )
        if breakable is not None:
            self._hit_breakable(player, breakable, prop_damage, quest_system, blow)
            return

        pile_hit = self._woodpile_in_reach(pos, hit_radius)
        if pile_hit is not None:
            self._chop_woodpile(player, pile_hit, arch, prop_damage, blow)
            return

        wild = self._wilderness_in_reach(pos, hit_radius)
        if wild is not None:
            if wild.choppable:
                self._chop_tree(player, wild, arch, prop_damage, blow)
            else:
                self._smash_boulder(player, wild, arch, prop_damage, blow)
            return

        window_hit = self._find_window_in_reach(pos, hit_radius)
        if window_hit is not None:
            building, idx, window = window_hit
            self._hit_window(player, building, idx, window, prop_damage, blow)

    def _woodpile_in_reach(self, pos, hit_radius: float):
        """The stack of firewood a swing at `pos` lands on, or None. The one exterior extra
        of a building that stands in the way (`Building.woodpile_rect`), so the one a blow
        aimed at nothing else should find rather than pass through."""
        for building in self.buildings_in_range(*pos, c.World.CHUNK_SIZE):
            pile = building.woodpile_rect()
            if pile is None:
                continue
            nearest_x = min(max(pos[0], pile.left), pile.right)
            nearest_y = min(max(pos[1], pile.top), pile.bottom)
            if math.hypot(pos[0] - nearest_x, pos[1] - nearest_y) < hit_radius + c.Woodpile.HIT_RADIUS:
                return building
        return None

    def _chop_woodpile(self, player: Player, building: Building, arch, prop_damage: int, blow: float):
        """One swing into the firewood stacked against a house. It reads as solid and it is
        solid, so it comes apart like the tree it was cut from: an axe does the work several
        times over, and what is left on the ground is logs.

        The pile is gone for good once it gives (`Building.woodpile_hp`, saved with the
        house), which takes its collision away with it."""
        pile = building.woodpile_rect()
        mult = c.Woodpile.AXE_MULT if arch.name == "axe" else c.Woodpile.OTHER_MULT
        building.woodpile_hp -= max(1, round(prop_damage * mult))
        if building.woodpile_hp > 0:
            self._prop_chip(pile.centerx, pile.centery, c.Woodpile.COLOR, "crate_break", building.woodpile_key(), blow)
            return

        get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(
            pile.centerx, pile.centery, c.Woodpile.COLOR, count=20, speed=5, life=550, size=4, gravity=0.4
        )
        player.stats.train("strength", c.Woodpile.XP_PER_BREAK)
        for _ in range(random.randint(*c.Woodpile.LOG_DROPS)):
            log = Item(pile.centerx + random.uniform(-14, 14), pile.centery + random.uniform(-14, 14), "Log", "misc")
            log.rarity = "common"
            log.start_pop_anim(pile.centerx, pile.centery)
            self.items.append(log)

    def _wilderness_in_reach(self, pos, hit_radius: float):
        """The tree or the boulder a swing at `pos` lands on, or None. The two things in the
        wilderness that answer a weapon, found the same way and each by its own reach."""
        for item in self.scenery_near(*pos):
            if item.choppable:
                reach = c.Trees.HIT_RADIUS
            elif item.smashable:
                reach = c.Boulders.HIT_RADIUS
            else:
                continue
            if math.hypot(item.x - pos[0], item.y - pos[1]) < hit_radius + reach:
                return item
        return None

    def _chop_tree(self, player: Player, tree, arch, prop_damage: int, blow: float):
        """One swing into a trunk. An axe is what a tree is felled with and does the work
        several times over; anything else is somebody hitting a tree with the wrong thing,
        which is slow but not impossible.

        A felled tree leaves a stump and a couple of logs on the ground, and the world
        remembers it was cut (`World.felled`) so it is still down when the chunk streams
        back in."""
        mult = c.Trees.AXE_MULT if arch.name == "axe" else c.Trees.OTHER_MULT
        tree.hp -= max(1, round(prop_damage * mult))
        self._prop_chip(tree.x, tree.y, c.Trees.STUMP_COLOR, "crate_break", tree.key, blow)
        if tree.hp > 0:
            return

        # Through the world rather than on the tree itself: what a piece of wilderness
        # blocks is what files it, so a trunk becoming a stump has to be filed again or the
        # player goes on walking round a tree lying on the ground.
        self.rework_scenery(tree, tree.fell)
        if tree.key:
            self.felled.add(tree.key)
        play_sound("gate_break")
        get_shake().add(c.Trees.FALL_SHAKE)
        get_particles().spawn_burst(tree.x, tree.y, (110, 150, 70), count=26, speed=6, life=700, size=5, gravity=0.3)
        player.stats.train("strength", c.Trees.XP_PER_FELL)
        for _ in range(random.randint(*c.Trees.LOG_DROPS)):
            log = Item(tree.x + random.uniform(-16, 16), tree.y + random.uniform(-16, 16), "Log", "misc")
            log.rarity = "common"
            log.start_pop_anim(tree.x, tree.y)
            self.items.append(log)

    def _smash_boulder(self, player: Player, boulder, arch, prop_damage: int, blow: float):
        """One swing into a rock. A hammer is what breaks stone and does the work several
        times over; an edge chips at it, which is slow but not impossible.

        A broken boulder leaves rubble and a few stones on the ground, and the world
        remembers it was broken (`World.smashed`) so it is still open when the chunk streams
        back in, exactly as a felled tree is."""
        mult = c.Boulders.HAMMER_MULT if arch.name == "hammer" else c.Boulders.OTHER_MULT
        boulder.hp -= max(1, round(prop_damage * mult))
        self._prop_chip(boulder.x, boulder.y, c.Boulders.RUBBLE_COLOR, "hit", boulder.key, blow)
        if boulder.hp > 0:
            return

        self.rework_scenery(boulder, boulder.smash)
        if boulder.key:
            self.smashed.add(boulder.key)
        play_sound("crate_break")
        get_shake().add(c.Boulders.SHAKE)
        get_particles().spawn_burst(
            boulder.x,
            boulder.y,
            c.Boulders.RUBBLE_COLOR,
            count=24,
            speed=7,
            life=600,
            size=5,
            gravity=0.5,
            shape="shard",
        )
        player.stats.train("strength", c.Boulders.XP_PER_SMASH)
        for _ in range(random.randint(*c.Boulders.STONE_DROPS)):
            stone = Item(boulder.x + random.uniform(-16, 16), boulder.y + random.uniform(-16, 16), "Stone", "misc")
            stone.rarity = "common"
            stone.start_pop_anim(boulder.x, boulder.y)
            self.items.append(stone)

    def _wreck_poi(self, poi: PointOfInterest, prop_damage: int, blow: float):
        """One swing into a landmark that is a prop rather than a place: a signpost. It
        comes down like a barrel, pays nothing, and stays down (`PointOfInterest.wrecked`),
        which costs the player whatever was written on it."""
        poi.prop_hp -= prop_damage
        if poi.prop_hp > 0:
            self._prop_chip(poi.x, poi.y, (150, 120, 80), "crate_break", f"poi:{poi.id}", blow)
            return
        poi.wrecked = True
        get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(
            poi.x, poi.y, (150, 120, 80), count=18, speed=6, life=520, size=4, gravity=0.5, shape="shard"
        )
        if self.notify:
            self.notify("The signpost comes down", c.Colors.MUTED)

    def _find_window_in_reach(self, pos, hit_radius):
        """Nearest unbroken window (on any non-landmark building) a swing reaches, as
        (building, index, rect), or None.

        Measured to the pane rather than to the middle of it. A window is three times as
        wide as it is deep and sits a wall's depth back from the face the player is stood
        against, so a reach taken from its centre covered a circle narrower than the pane
        itself: standing plainly in front of one and swinging at it missed unless the player
        happened to be lined up with the middle. What the reach is for is how far short of
        the glass a blow may land, which is what a distance to the rectangle answers."""
        px, py = pos
        best = None
        for building in self.buildings_in_range(px, py, c.World.CHUNK_SIZE):
            for idx, window in enumerate(building.window_rects()):
                if idx in building.broken_windows:
                    continue
                near_x = min(max(px, window.left), window.right)
                near_y = min(max(py, window.top), window.bottom)
                dist = math.hypot(px - near_x, py - near_y)
                if dist < hit_radius + c.Buildings.WINDOW_HIT_RADIUS and (best is None or dist < best[0]):
                    best = (dist, building, idx, window)
        return None if best is None else (best[1], best[2], best[3])

    def _hit_window(self, player: Player, building: Building, idx: int, window, damage: int, angle: float = 0.0):
        """Crack a window, and shatter it once it has taken enough."""
        remaining = building.window_hp.get(idx, c.Buildings.WINDOW_HP) - damage
        if remaining > 0:
            building.window_hp[idx] = remaining
            self._prop_chip(
                window.centerx, window.centery, (210, 230, 240), "glass_break", f"{building.id}:window:{idx}", angle
            )
            return
        building.window_hp.pop(idx, None)
        self._break_window(player, building, idx, window)

    def _blocking_door(self, chaser, player: Player) -> Building | None:
        """The shut door standing between a chaser and the player, once the chaser is at it.

        A door is the one obstacle in the world that cannot be walked round, which is exactly
        why it is the one a monster is allowed to break. Either the player is inside and the
        chaser out, or the other way about: anything else means the door is not what is
        keeping them apart."""
        building = self.building_at(player.x, player.y) or self.building_at(chaser.x, chaser.y)
        if building is None or not building.door_closed:
            return None
        if building.contains_point(chaser.x, chaser.y) == building.contains_point(player.x, player.y):
            return None
        door = building.door_rect()
        if math.hypot(chaser.x - door.centerx, chaser.y - door.centery) > c.Buildings.DOOR_BASH_REACH:
            return None
        return building

    def _gate_in_reach(self, pos, reach: float, shut_too: bool = False):
        """The gate a blow at `pos` lands on, as (village, index), or None.

        Barred and not merely shut, for a blow of the player's: a gate closed for the night
        has no beam across it and opens to a press from either side, so hacking one down
        would be work nobody has any reason to do. Only the wall a settlement puts between
        itself and you answers a weapon. `shut_too` is the chaser's reading: a wolf does
        not know what a press is, and a leaf leaned shut for the night is a wall to it
        until it has clawed through."""
        for village in self._village_solids_by_chunk.get(self._chunk_of(*pos), ()):
            if not village.barred and not (shut_too and village.shut_for_night):
                continue
            index = village.gate_at(pos[0], pos[1], reach)
            if index is not None:
                return village, index
        return None

    def _hit_gate(self, village, index: int, damage: int, angle: float = 0.0):
        """Land a blow on a shut gate, and put it through once it has taken enough. The
        one part of a wall that ever gives: a settlement that has shut you out (or in) can
        be answered with a weapon rather than only with a walk round to the next side."""
        gate = village.defences()["gates"][index]
        rect = gate["rect"]
        if not village.damage_gate(index, damage):
            self._prop_chip(
                rect.centerx, rect.centery, c.Villages.GATE_LEAF, "crate_break", village.gate_key(index), angle
            )
            return
        # A gate going over is not a crate breaking: it gets its own sound, its own kick and
        # its own animation (`Village.gate_fall_progress`), so beating one down never reads
        # as the same event as somebody opening it.
        get_shake().add(c.Combat.CRATE_SHAKE * 2.0)
        get_hitstop().trigger(c.Combat.HITSTOP_KILL_MS)
        play_sound("gate_break")
        get_particles().spawn_burst(
            rect.centerx,
            rect.centery,
            c.Villages.GATE_LEAF,
            count=44,
            speed=9,
            life=800,
            size=6,
            gravity=0.5,
            shape="shard",
        )
        # The dust off a beam that size going down, hanging after the splinters have landed.
        get_particles().spawn_burst(
            rect.centerx, rect.centery, (120, 105, 88), count=20, speed=3, life=1100, size=9, gravity=0.03
        )
        if self.notify:
            self.notify("The gate gives way", c.Colors.WHITE)

    def _bashers(self, player: Player):
        """Everything close enough to be held up by something and off its bash cooldown: the
        monsters, and the animals that have turned on the player.

        The loop both `bash_doors` and `bash_gates` are: the same box cull and the same
        clock, written once. What is actually in the way, and the blow it takes, is the
        caller's business, so the cooldown is spent by `_wind_up_bash` only once something
        has been found to swing at.
        """
        now = pygame.time.get_ticks()
        hunters = [critter for critter in self.critters if critter.hostile and critter.kind.damage > 0]
        for chaser in itertools.chain(self.monsters, hunters):
            # Cheap box test first: only something already on the player can be held up by
            # anything between them, and this runs over every monster alive every frame.
            if abs(chaser.x - player.x) > c.World.DETECTION_RANGE or abs(chaser.y - player.y) > c.World.DETECTION_RANGE:
                continue
            if now >= chaser.next_bash_ms:
                yield chaser

    @staticmethod
    def _wind_up_bash(chaser):
        """Put a monster or an animal on its bash cooldown with its blow coming round.

        A leaf is bashed on its own cadence rather than on the attacker's swing clock, so
        this is the animation only: no wind-up to read and no blow to land. An animal has
        no arm to bring round, so it is its lunge."""
        now = pygame.time.get_ticks()
        chaser.next_bash_ms = now + c.Buildings.DOOR_BASH_COOLDOWN_MS
        if isinstance(chaser, Critter):
            chaser.lunge_until_ms = now + c.Wildlife.GATE_LUNGE_MS
        else:
            chaser.start_attack_anim()

    def bash_gates(self, player: Player, damage_mult: float = 1.0):
        """Let a monster or an animal shut out by a gate beat on it, exactly as it would a
        door.

        A gate is barred because the settlement has turned on the player, which is also when
        a pack is most likely to be standing at it: the wall is not breakable, the way round
        is a long one, and the leaf across the gap is the one thing in the way that answers a
        swing. A gate leaned shut for the night is the same wall to whatever chased the
        player up to it, and it is beaten on the same way rather than stood against until
        dawn; every blow marks the attacker (`gate_bash_ms`), which is what turns the guard
        out to meet it (`WorldSocial.militia_orders`)."""
        for chaser in self._bashers(player):
            hit = self._gate_in_reach((chaser.x, chaser.y), c.Buildings.DOOR_BASH_REACH, shut_too=True)
            if hit is None:
                continue
            village, index = hit
            # Only if it is actually what stands between them: inside looking out, or the
            # other way about, either side of the line the gateway is cut in.
            if not village.gate_between(index, chaser.x, chaser.y, player.x, player.y):
                continue
            self._wind_up_bash(chaser)
            chaser.gate_bash_ms = pygame.time.get_ticks()
            rect = village.defences()["gates"][index]["rect"]
            angle = math.atan2(rect.centery - chaser.y, rect.centerx - chaser.x)
            self._hit_gate(village, index, round(chaser.kind.damage * damage_mult), angle)

    def bash_doors(self, player: Player, damage_mult: float = 1.0):
        """Let every monster held up at a shut door beat on it.

        Kept here rather than on `Monster` for the same reason a monster's arrow is: the door
        belongs to the world, and what happens to it is a blow landing on a hit-point pool
        like any other. It takes the monster's own damage, so a troll is through a door in a
        few swings and a slime is a long while about it, and the hole it leaves is permanent."""
        for monster in self._bashers(player):
            building = self._blocking_door(monster, player)
            if building is None:
                continue
            self._wind_up_bash(monster)
            door = building.door_rect()
            angle = math.atan2(door.centery - monster.y, door.centerx - monster.x)
            self._hit_door(building, round(monster.kind.damage * damage_mult), angle)

    def _hit_door(self, building: Building, damage: int, angle: float = 0.0):
        """Land a blow on a shut door, and put it through once it has taken enough."""
        door = building.door_rect()
        if not building.damage_door(damage):
            self._prop_chip(door.centerx, door.centery, c.Buildings.DOOR_COLOR, "crate_break", building.door_key, angle)
            return
        get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
        play_sound("crate_break")
        get_particles().spawn_burst(
            door.centerx,
            door.centery,
            c.Buildings.DOOR_COLOR,
            count=18,
            speed=6,
            life=520,
            size=4,
            gravity=0.5,
            shape="shard",
        )

    def _break_window(self, player: Player, building: Building, idx: int, window):
        """Shatter a window. No loot, and two things that are not the crash: the hole is a
        way into the house (`Building.window_gaps`, which is what makes a locked door worth
        answering), and putting somebody's window through in front of them is vandalism like
        wrecking their room, answered on the same ladder by whoever saw it."""
        building.broken_windows.add(idx)
        self.report_crime(window.centerx, window.centery, player)
        get_shake().add(c.Combat.WINDOW_SHAKE)
        play_sound("glass_break")
        get_particles().spawn_burst(
            window.centerx,
            window.centery,
            (210, 230, 240),
            count=16,
            speed=6,
            life=500,
            size=3,
            gravity=0.5,
            shape="shard",
        )

    def _break_loot(self, x, y, coins, loot_item, place_item):
        """Spill what a smashed container held onto the ground near (x, y) via `place_item`.
        Nothing is credited here and nothing is announced: the coins are laid down as a
        purse like any other drop, so everything a break pays is walked over to be
        collected, and the pickup is the one toast it gets. A second one at the break said
        the same thing a moment earlier and sat over the item names as they were gathered."""
        spilled = []
        if coins > 0:
            spilled.append(Item(x, y, "Purse", "coins", rarity="common", quantity=coins))
        if loot_item is not None:
            spilled.append(loot_item)
        for item in spilled:
            item.x = x + random.uniform(-20, 20)
            item.y = y + random.uniform(-20, 20)
            item.start_pop_anim(x, y)
            place_item(item)

    def _break_prop(self, player: Player, building: Building, rect, kind: str):
        """Take a piece of furniture apart: splinters, and for the two kinds that hold wares
        a few coins and a small chance of a dropped item.

        The piece has already been removed from the interior's collision set by
        `damage_prop_at`; here we handle the feedback and the loot. Coins are credited
        straight away; an item (if any) pops out onto the floor for the player to walk over
        and collect, rather than jumping straight into the inventory. A table pays nothing,
        which is the point: most of a room is somebody's furniture, not a container.
        """
        self._break_effects(rect.centerx, rect.centery, (150, 110, 70), 20)
        # Wrecking somebody's room is a crime like emptying their chest: whoever sees it
        # comes for the player alone, and the rest of the street never hears about it.
        self.report_crime(rect.centerx, rect.centery, player)
        if kind not in c.Buildings.FURNITURE_LOOT:
            return
        coins, loot_item = break_crate()
        self._break_loot(rect.centerx, rect.centery, coins, loot_item, building.dropped_items.append)

    def _hit_poi(self, player: Player, poi: PointOfInterest, damage: int, angle: float = 0.0):
        """Work at a ruins pile or a camp cache. It takes several blows to force one open,
        which is why the guard check comes first: nobody chips away at a strongbox with
        three bandits still standing over it."""
        if poi.kind == "camp" and not self.camp_is_clear(poi):
            if self.notify:
                self.notify("The camp is still guarded", c.Colors.MUTED)
            return
        poi.cache_hp -= damage
        if poi.cache_hp > 0:
            self._prop_chip(poi.x, poi.y, (150, 140, 120), "crate_break", f"poi:{poi.id}", angle)
            return
        self._break_poi(player, poi)

    def _break_poi(self, player: Player, poi: PointOfInterest):
        """Smash a wilderness ruins pile or bandit camp cache: same feedback as an outdoor
        barrel, better odds and rarity since it took more effort to find. Left in place
        afterwards (not removed like a breakable) so the ruin/camp still reads as a landmark,
        just picked over.

        A bandit camp's cache stays shut while its owners are still on their feet, which
        `_hit_poi` checks before any blow lands on it: the loot is the reward for clearing
        the camp, not for running past it."""
        poi.looted = True
        self._break_effects(poi.x, poi.y, (150, 140, 120), 20)
        coins, loot_item = open_poi_cache(player.loot_luck())
        self._break_loot(poi.x, poi.y, coins, loot_item, self.items.append)

    def _hit_breakable(
        self, player: Player, breakable: Breakable, damage: int, quest_system: QuestSystem, angle: float = 0.0
    ):
        """Take a swing at an outdoor prop. A bush goes down in one, a barrel takes a
        beating; either way the reward only comes when it finally gives."""
        breakable.hp -= damage
        if breakable.hp > 0:
            color = (80, 150, 65) if breakable.kind == "bush" else (150, 110, 70)
            self._prop_chip(
                breakable.x,
                breakable.y,
                color,
                "bush_rustle" if breakable.kind == "bush" else "hit",
                breakable.damage_key,
                angle,
            )
            return
        self._break_breakable(player, breakable, quest_system)

    def _break_breakable(self, player: Player, breakable: Breakable, quest_system: QuestSystem):
        """Smash an outdoor prop. A barrel plays out like a shop crate: juice, coins,
        and a small chance of a dropped item landing straight in the open world. A powder
        keg pays nothing and goes off instead. Anything planted is pure decoration: a
        satisfying puff and nothing else, so the world has more to smash without inflating
        the loot economy. Either way the prop is gone for good, no debris left behind."""
        self.drop_breakable(breakable)

        if breakable.kind == "powder":
            self.explode(breakable.x, breakable.y, player, quest_system)
            return

        if not breakable.loot:
            get_shake().add(c.Combat.DECOR_BREAK_SHAKE)
            play_sound("bush_rustle")
            get_particles().spawn_burst(
                breakable.x, breakable.y, (80, 150, 65), count=14, speed=4, life=450, size=4, gravity=0.3
            )
            return

        self._break_effects(breakable.x, breakable.y, (150, 110, 70), 18)
        coins, loot_item = break_crate()
        self._break_loot(breakable.x, breakable.y, coins, loot_item, self.items.append)
