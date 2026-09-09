"""Keeping the ground around the player populated, and running what is standing on it.

Mixed into `World`, which owns the lists this fills and empties (`monsters`, `critters`).
Split out because it is the one job that answers "what should be here?" rather than "what
is here?": where a body may be stood up at all, how many of them the ground round the
player holds, where a body that has to go somewhere is put down, and the per-frame step
every monster and animal takes once it is there. The map they stand on is
`WorldStreaming`'s and what a blow between them is worth is `WorldCombat`'s.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import core.constants as c
from core.decals import get_decals
from game.blow import Blow
from game.entities.critter import Critter, pick_critter_kind
from game.entities.monsters import Monster, pick_monster_kind

if TYPE_CHECKING:
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


class WorldSpawning:
    """What stands on the ground around the player, and where it is allowed to stand.

    The caps are a ramp on distance from the world centre rather than one world-wide number
    (`roaming_cap`), the spawn point is protected by refusing the ground itself
    (`_spawn_is_sheltered`), and every placement in the world goes out through the one
    outward search (`ring_search`), differing only in what it accepts.
    """

    def _random_coords_away_from_spawn(self) -> tuple[int, int]:
        center = c.World.WORLD_SIZE // 2
        min_dist = c.World.INITIAL_SPAWN_MIN_DISTANCE
        for _ in range(20):
            x, y = random.randint(0, c.World.WORLD_SIZE), random.randint(0, c.World.WORLD_SIZE)
            if math.hypot(x - center, y - center) < min_dist or self._spawn_is_sheltered(x, y):
                continue
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                return x, y
        # Nothing clear in 20 tries: settle for the last roll rather than looping forever.
        # A monster standing in a wall beats hanging world generation.
        return x, y

    def _new_monster(self, x, y, danger_bonus: int = 0) -> Monster:
        """Tougher kinds unlock farther from the world center, so wandering out gets more
        dangerous. `danger_bonus` rolls the kind as if this spot were that much farther out,
        which is how a camp leader outclasses the guards around it."""
        center = c.World.WORLD_SIZE // 2
        distance_from_center = math.hypot(x - center, y - center) + danger_bonus
        return Monster(x, y, pick_monster_kind(distance_from_center))

    @staticmethod
    def ring_search(x, y, step: float, rings: int, accept) -> tuple[float, float] | None:
        """Walk outward from (x, y) in rings of eight points per ring, `step` apart, and give
        back the first point `accept` says yes to. None when the whole search comes up empty.

        The one definition of "somewhere near here that will do", shared by every placement
        in the world: a body stepping out of a wall, the player being put down clear of what
        killed them, a guardian standing as near its ruin as it is allowed to. What differs
        between them is only what counts as a good spot, which is what `accept` carries.
        """
        for ring in range(1, rings + 1):
            distance = ring * step
            for index in range(ring * 8):
                angle = 2 * math.pi * index / (ring * 8)
                cx, cy = x + math.cos(angle) * distance, y + math.sin(angle) * distance
                if accept(cx, cy):
                    return cx, cy
        return None

    def free_spot_near(self, x, y, radius, rings: int | None = None) -> tuple[float, float]:
        """The nearest standable point to (x, y), which may be (x, y) itself.

        The spawn point is a fixed world coordinate while the starting town is laid out
        around a random centre near it, so the two overlap often; the same is true of any
        village generated later. Rather than move the settlement, whoever is being placed
        steps out to the first clear spot around it.

        `rings` caps how far out the search goes, for a caller who wants a body put back on
        the open ground it is standing in rather than moved to wherever there is room."""
        if not self.blocked(x, y, radius):
            return x, y
        found = self.ring_search(
            x, y, radius * 2, rings or c.World.FREE_SPOT_MAX_RINGS, lambda cx, cy: not self.blocked(cx, cy, radius)
        )
        # Walled in on every side within the search: leave the caller where they were
        # rather than teleporting them somewhere arbitrary.
        return found or (x, y)

    def hostiles_near(self, x, y, radius: float) -> list:
        """Everything within `radius` of (x, y) that would attack the player: monsters,
        bosses, villagers who have turned, and animals currently hunting."""
        near = []
        near += [m for m in self.monsters if m.distance_to_point((x, y)) <= radius]
        near += [b for b in self.bosses if b.distance_to_point((x, y)) <= radius]
        near += [n for n in self.npcs if n.hostile and n.distance_to_point((x, y)) <= radius]
        near += [cr for cr in self.critters if cr.hostile and cr.distance_to_point((x, y)) <= radius]
        return near

    def safe_spot_near(self, x, y, radius, clearance: float | None = None) -> tuple[float, float]:
        """Where to put the player: `free_spot_near` knows only about geometry, and a point
        with no wall in it is not safe if whatever killed the player is standing on it. Same
        outward ring search, with candidates holding anything hostile within `clearance`
        rejected as well, falling back to the geometric answer when the search finds nowhere
        clear (better a rough spawn than a hang)."""
        clearance = c.World.SAFE_SPOT_CLEARANCE if clearance is None else clearance

        def clear(cx, cy) -> bool:
            return not self.blocked(cx, cy, radius) and not self.hostiles_near(cx, cy, clearance)

        if clear(x, y):
            return x, y
        found = self.ring_search(x, y, radius * 2, c.World.FREE_SPOT_MAX_RINGS, clear)
        return found or self.free_spot_near(x, y, radius)

    def clear_hostiles_around(self, x, y, radius: float):
        """Send the roaming monsters standing around (x, y) back out into the wilds. Used
        when the player respawns: the pack that killed them shouldn't still be bearing down
        on the spawn point. Bosses and camp garrisons stay put, being where they belong and
        not something to be rid of by dying."""
        self.monsters = [m for m in self.monsters if m.camp_id or m.distance_to_point((x, y)) > radius]

    def _spawn_is_sheltered(self, x, y) -> bool:
        """Whether (x, y) is ground nothing hostile may be spawned on: inside the ring the
        world centre holds, or on a settlement's grounds or doorstep."""
        center = c.World.WORLD_SIZE // 2
        if math.hypot(x - center, y - center) < c.World.SAFE_RADIUS:
            return True
        return self.village_at(x, y, c.World.VILLAGE_SPAWN_MARGIN) is not None

    def roaming_cap(self, player: Player) -> int:
        """How many roaming monsters the world holds around the player right now. A ramp
        from the near cap on the starting town's doorstep to the far cap out in the wilds,
        rather than one world-wide number: the early game shouldn't be as crowded as the
        ground the player reaches an hour later. The ramp is eased (ROAMING_CAP_CURVE) so
        the near ground stays near-empty for a good walk rather than filling up at once."""
        center = c.World.WORLD_SIZE // 2
        distance = math.hypot(player.x - center, player.y - center)
        span = max(c.World.ROAMING_CAP_FAR_DISTANCE - c.World.SAFE_RADIUS, 1)
        ratio = min(max((distance - c.World.SAFE_RADIUS) / span, 0.0), 1.0) ** c.World.ROAMING_CAP_CURVE
        return round(c.World.ROAMING_CAP_NEAR + (c.World.ROAMING_CAP_FAR - c.World.ROAMING_CAP_NEAR) * ratio)

    def _spawn_monster_away_from(self, player: Player):
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.World.SPAWN_MIN_DISTANCE, c.World.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            # Monsters wander into settlements, but none of them starts life in one or on
            # its doorstep: a village should read as the safe ground between stretches of
            # wilderness. The starting town's ground is wider still (World.SAFE_RADIUS
            # around the world centre), since that is where every run begins and every
            # death sends the player back to.
            # Nothing is stood up on somebody's floor: `blocked` says nothing about a room,
            # since a wall is solid and the boards inside it are not.
            if self._spawn_is_sheltered(x, y) or self.building_at(x, y) is not None:
                continue
            if not self.blocked(x, y, c.MONSTER_MAX_SIZE / 2):
                # What crawls out after dark is what lives deeper in the wilds, but only
                # proportionally so: a flat bonus put bandits on the starting town's
                # doorstep every night, which is the one piece of ground that has to stay
                # survivable. Out past the settled ring the whole bonus applies.
                bonus = 0
                if self.daynight.is_night:
                    center = c.World.WORLD_SIZE // 2
                    from_center = math.hypot(x - center, y - center)
                    bonus = min(
                        c.DayNight.NIGHT_DANGER_BONUS,
                        from_center * c.DayNight.NIGHT_DANGER_DISTANCE_FRAC,
                    )
                # A pack kind (wolves, goblins) is rolled once and then stood up as a group,
                # so the wilds hold a few real fights rather than a scatter of single mobs.
                leader = self._new_monster(x, y, danger_bonus=bonus)
                pack = [leader]
                for _ in range(random.randint(*leader.kind.group) - 1):
                    spread = c.World.PACK_SPREAD
                    mate_x, mate_y = x + random.uniform(-spread, spread), y + random.uniform(-spread, spread)
                    indoors = self.building_at(mate_x, mate_y) is not None
                    if not indoors and not self.blocked(mate_x, mate_y, leader.kind.size / 2):
                        pack.append(Monster(mate_x, mate_y, leader.kind))
                # Each member takes its own bearing around the player, evenly spread from a
                # random start, so a pack closes in as a ring instead of a queue.
                base = random.uniform(0, 2 * math.pi)
                for index, member in enumerate(pack):
                    member.slot_angle = base + 2 * math.pi * index / len(pack)
                self.monsters.extend(pack)
                return

    def _spawn_critter_away_from(self, player: Player):
        """Put one animal, or one herd/pack, on the ground out of sight of the player. Which
        species turns up is a question of how far out this is, the same rule monsters follow:
        rabbits and deer near town, wild dogs and bears deep in the wilds."""
        center = c.World.WORLD_SIZE // 2
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(c.Wildlife.SPAWN_MIN_DISTANCE, c.Wildlife.SPAWN_MAX_DISTANCE)
            x = player.x + math.cos(angle) * dist
            y = player.y + math.sin(angle) * dist
            kind = pick_critter_kind(math.hypot(x - center, y - center))
            # Nothing wild is stood up in somebody's front room either, nor on the roof
            # of the back half of an L: the floor of a house is not blocked ground, so the
            # question is what the footprint covers rather than what stops a body.
            if self.blocked(x, y, kind.size / 2) or self.on_building(x, y, kind.size / 2):
                continue
            for _ in range(random.randint(*kind.group)):
                spread = c.Wildlife.GROUP_SPREAD
                mate_x = x + random.uniform(-spread, spread)
                mate_y = y + random.uniform(-spread, spread)
                indoors = self.on_building(mate_x, mate_y, kind.size / 2)
                if not indoors and not self.blocked(mate_x, mate_y, kind.size / 2):
                    self.critters.append(Critter(mate_x, mate_y, kind))
            return

    def _ensure_village_dogs(self, player: Player):
        """Stand a village's dogs back up when the player is near it. They are wildlife, not
        villagers: session-only, rebuilt from the village rather than saved, the same trick a
        bandit camp's garrison uses. How many a settlement keeps is fixed by its chunk, so
        the same village always has the same pack."""
        for village in self.villages:
            if village.distance_to_point(player.get_pos()) > c.Wildlife.DESPAWN_DISTANCE:
                continue
            key = f"{village.chunk[0]}:{village.chunk[1]}"
            wanted = random.Random(f"dogs{key}").randint(*c.Wildlife.VILLAGE_DOGS)
            living = [cr for cr in self.critters if cr.village_key == key]
            hostile = any(npc.hostile for npc in self.npcs if village.contains_point(npc.x, npc.y))
            size = c.CRITTER_KINDS_BY_NAME["dog"].size / 2
            for _ in range(wanted - len(living)):
                # A dog lives in the street, not in the tavern: the spot is rolled again
                # rather than settled for when it lands on somebody's floor, and a village
                # that has no room for another dog simply keeps the ones it has.
                spot = None
                for _attempt in range(8):
                    angle = random.uniform(0, 2 * math.pi)
                    distance = random.uniform(village.radius * 0.15, village.radius * 0.5)
                    x, y = self.free_spot_near(
                        village.x + math.cos(angle) * distance,
                        village.y + math.sin(angle) * distance,
                        size,
                    )
                    if not self.on_building(x, y, size):
                        spot = (x, y)
                        break
                if spot is None:
                    continue
                x, y = spot
                dog = Critter(x, y, c.CRITTER_KINDS_BY_NAME["dog"], home=(x, y), village_key=key)
                # A village that has already turned on the player doesn't hand back a
                # friendly dog just because this one was stood up afterwards.
                dog.hostile = hostile
                self.critters.append(dog)

    def _monster_target(self, monster: Monster, player: Player):
        """Who this monster is coming for. The player, unless somebody else is nearer and it
        can actually get at them: a villager is prey, not scenery to be filed past.

        It used to take a settlement's grounds to make one worth eating, which left the
        woman standing twenty paces outside her own gate ignored by the wolf beside her while
        it walked round her at the player. So the test is reach and sight instead: anyone
        inside `Villages.DEFEND_RADIUS`, nearer than the player, and not behind a wall.
        Villagers who are already down (`NPC.surrendered`) are as good a target as any: a
        monster is not owed a surrender.

        A camp guard is left out of it. It holds a piece of ground rather than raiding, and
        a garrison drifting off to fight the nearest farmer would empty its own camp. So is
        anything still in a disguise: what it is wearing is worn for the player's benefit,
        and a husk that threw its villager off at a passing farmer would spend the one
        moment it has on somebody who was never going to be surprised by it."""
        if monster.camp_id or not monster.revealed or not self.npcs:
            return player
        reach = min(monster.distance_to_point(player.get_pos()), c.Villages.DEFEND_RADIUS)
        near = sorted(
            (npc for npc in self.npcs if monster.distance_to_point((npc.x, npc.y)) < reach),
            key=lambda npc: monster.distance_to_point((npc.x, npc.y)),
        )
        # Sight is walked step by step, so it is asked about the nearest few and no further:
        # anyone behind three other people is not the one this thing is going to eat.
        for npc in near[: c.Villages.MONSTER_PREY_TRIES]:
            if self.line_of_sight(monster.x, monster.y, npc.x, npc.y):
                return npc
        return player

    def _land_monster_blow(self, monster: Monster, target, damage: int, player: Player, quest_system: QuestSystem):
        """A monster's swing connecting, on the player or on whoever it caught instead. A
        villager cut down by a monster is nothing the player did, so it resolves as friendly
        fire: no provoked village, no purse, and the body stays down for good."""
        if target is player:
            player.receive_damage(damage, source=monster)
            return
        self._resolve_npc_hit(
            target,
            damage,
            player,
            quest_system,
            Blow(
                kb_dir=self._dir_from(monster.x, monster.y, target.x, target.y),
                blocked=self.blocked,
                by_player=False,
                source=monster,
            ),
        )

    def _track_bloody_feet(self, player: Player):
        """Anything walking through fresh blood picks it up and prints it out again for the
        next few strides (`DecalSystem.track_walkers`).

        Only what is near enough to be on screen: a trail nobody can see is bookkeeping, and
        the whole point of the prints is reading which way something walked away from a
        body. Called after everything has taken its step, like the traps, so a foot is
        judged on where it actually ended up this frame."""
        reach = c.World.CHUNK_SIZE
        walkers = [(id(player), player.x, player.y)]
        for group in (self.monsters, self.npcs, self.critters):
            walkers.extend(
                (id(body), body.x, body.y)
                for body in group
                if abs(body.x - player.x) <= reach and abs(body.y - player.y) <= reach
            )
        get_decals().track_walkers(walkers)

    def _update_monsters(self, player: Player, dt, quest_system: QuestSystem, damage_mult: float):
        """Every monster near enough to react, plus the bosses, the burns ticking on both
        and whatever a monster does that is not a step: shooting, bashing a door, exploding."""
        player_pos = player.get_pos()
        detection = c.World.DETECTION_RANGE * (c.DayNight.NIGHT_DETECTION_MULT if self.daynight.is_night else 1.0)
        # And what the weather takes back off it: nothing sees as far through rain, and
        # almost nothing sees through fog, which is the whole of what makes a fogbank
        # somewhere to hide rather than a filter over the screen.
        detection *= self.weather.sight_mult()

        # Monsters far beyond their detection range can't react to the player, so skip
        # their per-frame work entirely (cheap bounding-box test, no sqrt). Never tighter
        # than the screen itself, though: one that has noticed nobody still roams its patch,
        # and a monster standing perfectly still at the edge of the view until the player
        # steps into its detection ring is what made every cave mouth look like an ambush
        # laid in advance.
        update_radius = max(detection + c.Player.SIZE, c.Screen.ORIGIN_X + c.MONSTER_MAX_SIZE)
        nearby = [
            m for m in self.monsters if abs(m.x - player.x) <= update_radius and abs(m.y - player.y) <= update_radius
        ]
        # Who each of them is coming for is settled before any of them moves: the ones
        # converging on the same target are dealt their places around it and the handful of
        # permissions to swing, so a pack closes a circle instead of forming a queue.
        targets = {monster: self._monster_target(monster, player) for monster in nearby}
        by_target: dict = {}
        for monster, target in targets.items():
            by_target.setdefault(id(target), (target, []))[1].append(monster)
        for target, chasers in by_target.values():
            self.assign_surround_slots(chasers, target)

        for monster in nearby:
            target = targets[monster]
            # Anything that has ended up inside a solid (shouldered into a tower by the pack
            # behind it, caught by a door shutting) is put back on open ground first: every
            # step it could take from in there would be refused.
            self.unstick(monster, monster.kind.size / 2)
            waypoint = self.chase_waypoint(monster, target, monster.kind.size / 2)
            # `nearby` doubles as the crowd each monster shoulders its way out of: the ones
            # converging on the player are exactly the ones that pile up on each other.
            damage = monster.move(
                target,
                dt,
                self.blocked,
                waypoint,
                damage_mult,
                detection,
                crowd=nearby,
                terrain_mult=self.terrain_speed(monster.x, monster.y),
            )
            if damage:
                self._land_monster_blow(monster, target, damage, player, quest_system)
        # Fuses burn on the clock rather than on the player being close, so a creeper that
        # drifted out of `nearby` mid-fuse still goes off instead of freezing where it stands.
        for monster in list(self.monsters):
            if monster.fuse_expired():
                self.detonate_creeper(monster, player, quest_system)
        self.fire_monster_shots(player, damage_mult)
        self.bash_doors(player, damage_mult)
        self.bash_gates(player, damage_mult)

        # Monsters left far behind despawn, freeing their slot to respawn near the player.
        # Camp guards are the exception: they hold a place rather than roam, and their camp
        # would look abandoned while its chunk is still loaded. They leave with the chunk
        # instead (see WorldStreaming._unload_chunks). Nothing despawns while the player is
        # underground: every monster on the surface is a world away from a tunnel, and the
        # whole map would empty out and refill itself over one climb down.
        if self.underground is None:
            self.monsters = [
                m for m in self.monsters if m.camp_id or m.distance_to_point(player_pos) <= c.World.DESPAWN_DISTANCE
            ]

        # Burn (weapon affix) ticks over time and can finish a wounded target off.
        self._tick_burns(self.monsters, player, quest_system)
        self._tick_burns(self.bosses, player, quest_system)

        # Bosses never despawn; they chase, cast and enrage on their own schedule.
        for boss in list(self.bosses):
            boss.update_boss(self, player, dt, quest_system)

        self.boss_roam_timer += dt
        if self.underground is None and self.boss_roam_timer >= c.Boss.ROAM_CHECK_INTERVAL_MS:
            self.boss_roam_timer = 0.0
            self._maybe_spawn_roaming_boss(player)

    def _update_critters(self, player: Player, dt, damage_mult: float):
        player_pos = player.get_pos()
        for critter in self.critters:
            self.unstick(critter, critter.size / 2)
            # Only an animal actually coming for the player needs a route round the houses;
            # everything else is wandering or running and steers for itself.
            chasing = critter.hostile and critter.distance_to_point(player_pos) <= critter.kind.detection
            # And an animal is prised off a corner it cannot walk off exactly as a villager
            # is: the inside corner of an L is invisible to `blocked` and a deer that walked
            # into one grazed there for the rest of the session.
            self.unwedge(
                critter,
                critter.size / 2,
                dt,
                wants_move=chasing or critter.flee_heading is not None or critter.wander.target is not None,
            )
            waypoint = self.chase_waypoint(critter, player, critter.size / 2) if chasing else None
            critter.update(
                player, dt, self.blocked, damage_mult, waypoint, terrain_mult=self.terrain_speed(critter.x, critter.y)
            )

    def _restock_surface(self, player: Player, dt):
        """What keeps the ground around the player populated: the village dogs, the wildlife
        despawning behind and respawning ahead, and the roaming monsters up to the cap."""
        player_pos = player.get_pos()
        self._ensure_village_dogs(player)
        self.critters = [
            critter for critter in self.critters if critter.distance_to_point(player_pos) <= c.Wildlife.DESPAWN_DISTANCE
        ]
        if len(self.critters) < c.Wildlife.COUNT:
            self.critter_respawn_timer += dt
            if self.critter_respawn_timer >= c.Wildlife.RESPAWN_INTERVAL_MS:
                self.critter_respawn_timer = 0.0
                self._spawn_critter_away_from(player)

        # Camp guards don't count: they never despawn, so counting them would slowly choke
        # off the roaming population as the player finds more camps.
        roaming = sum(1 for m in self.monsters if not m.camp_id and not m.raid_key)
        if roaming < self.roaming_cap(player):
            self.respawn_timer += dt
            respawn_interval = c.World.RESPAWN_INTERVAL_MS
            blood = self.events.blood_intensity
            if blood > 0:
                # Ramped like the sky, so the wilds fill up as the night reddens.
                respawn_interval /= 1.0 + (c.Events.BLOOD_NIGHT_RESPAWN_MULT - 1.0) * blood
            elif self.daynight.is_night:
                respawn_interval /= c.DayNight.NIGHT_RESPAWN_MULT
            if self.respawn_timer >= respawn_interval:
                self.respawn_timer = 0.0
                self._spawn_monster_away_from(player)
