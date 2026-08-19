from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING, List

import core.constants as c
from core.audio import play_sound
from core.particles import get_particles
from game.entities.critter import Critter
from game.entities.items import Item, roll_rarity
from game.entities.npcs import NPC
from game.entities.poi import PointOfInterest, pois_for_chunk
from game.entities.tunnel import Tunnel, has_tunnel
from game.entities.village import Village, village_site
from game.loot import roll_shop_stock

if TYPE_CHECKING:
    from game.entities.buildings import Building
    from game.entities.monsters import Monster
    from game.entities.player import Player
    from llm.quest_system import QuestSystem


# What a camper or a signpost calls each kind of landmark when giving directions.
_POI_HINT_LABELS = {
    "ruins": "old ruins",
    "camp": "somebody's camp",
    "shrine": "a forgotten shrine",
    "farmstead": "an abandoned farmstead",
    "graveyard": "an old graveyard",
    "watchtower": "a ruined watchtower",
    "stones": "a ring of standing stones",
    "signpost": "a crossroads",
}


def _compass_direction(dx: float, dy: float) -> str:
    """The bearing from one point to another, in the words a person would use."""
    names = ("east", "south east", "south", "south west", "west", "north west", "north", "north east")
    index = round(math.atan2(dy, dx) / (math.pi / 4)) % 8
    return names[index]


class WorldPlaces:
    """The places the player walks up to, and what they can do when they get there.

    Mixed into `World` beside `WorldCombat` and `WorldStreaming`, working on the same
    entity lists. What lives here is everything a landmark or a household answers to: a
    bandit camp's garrison and its cache, the fire and the bed the player rests at, the
    shrine they pray at, the directions a signpost or a camper gives, the ground the
    minimap remembers, and what a village does about violence or theft.

    `WorldStreaming` decides where these places are and when they exist; this is what
    happens once the player is standing in front of one.
    """

    def _populate_camp(self, poi: PointOfInterest):
        """Put a camp's occupants on the ground as its chunk loads.

        A bandit camp's garrison is a number, not a set of entities: the first sighting rolls
        how many bandits live here, and from then on that count (and the leader's own flag) is
        the camp. Every chunk load stands the survivors back up around the fire, `_unload_chunk`
        takes them away again, and only a kill lowers the count, so walking off can never empty
        a camp and finding a hundred camps costs no more memory than finding one. They roll
        their kind as if the camp stood deeper into the wilds, so the cache behind them is
        worth the fight. A traveller camp instead gets its camper, a permanent NPC like any
        villager, spawned once for the whole save (`npc_spawned`)."""
        if poi.kind != "camp":
            return
        if poi.variant == "traveller":
            self._spawn_camper(poi)
            return
        if poi.looted:
            return
        if poi.guards_alive is None:
            poi.guards_alive = random.randint(c.PointsOfInterest.CAMP_GUARD_MIN, c.PointsOfInterest.CAMP_GUARD_MAX)
            poi.leader_alive = True

        spread = c.PointsOfInterest.CAMP_GUARD_SPREAD
        for i in range(poi.guards_remaining):
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(spread * 0.5, spread)
            x = poi.x + math.cos(angle) * distance
            y = poi.y + math.sin(angle) * distance
            leader = poi.leader_alive and i == poi.guards_remaining - 1
            guard = self._new_monster(x, y, danger_bonus=c.PointsOfInterest.CAMP_LEADER_DANGER_BONUS if leader else 0)
            guard.camp_id = poi.id
            guard.camp_leader = leader
            self.monsters.append(guard)

        # Camp dogs come and go with the garrison rather than being counted with it: they
        # are wildlife, so they can't hold a camp open, but a camp with bandits still in it
        # has its dogs. Once the garrison is dead the kennel stays empty.
        if not poi.guards_remaining:
            return
        for _ in range(random.Random(f"dogs{poi.id}").randint(*c.Wildlife.CAMP_DOGS)):
            angle = random.uniform(0, 2 * math.pi)
            x = poi.x + math.cos(angle) * spread
            y = poi.y + math.sin(angle) * spread
            self.critters.append(Critter(x, y, c.CRITTER_KINDS_BY_NAME["dog"], home=(x, y), camp_id=poi.id))

    def on_guard_killed(self, monster: Monster, quest_system: QuestSystem):
        """Strike a fallen bandit off its camp's roll, which is what decides whether the cache
        opens and how many stand there when the chunk next loads. Emptying the roll is also
        what finishes a clear_camp quest, whether or not the camp's chunk is still loaded.

        A tunnel's garrison is held the same way and for the same reason, so it is answered
        here rather than in a routine of its own."""
        tunnel = self.tunnels.get(monster.camp_id)
        if tunnel is not None:
            tunnel.guard_killed()
            self.tunnel_state[tunnel.id] = tunnel.state()
            return
        poi = next((p for p in self.pois if p.id == monster.camp_id), None)
        if poi is not None:
            poi.guard_killed(monster.camp_leader)
            self.poi_state[poi.id] = poi.state()
            if poi.guards_defeated:
                quest_system.on_camp_cleared(poi.id)
            return
        # The camp's chunk unloaded while this guard was still chasing the player: its POI
        # object is gone, so the saved state is the only copy left to edit.
        state = self.poi_state.get(monster.camp_id)
        if state is None:
            return
        if monster.camp_leader:
            state["leader_alive"] = False
        else:
            state["guards_alive"] = max(0, (state.get("guards_alive") or 0) - 1)
        if not state.get("guards_alive") and not state.get("leader_alive"):
            quest_system.on_camp_cleared(monster.camp_id)

    def find_bandit_camp(self, x: float, y: float) -> PointOfInterest | None:
        """A bandit camp still held, for a clear_camp quest to send the player at.

        Loaded chunks first, then rings of chunks outward, generated from their coordinates
        exactly as `_load_chunk` would: a camp is a pure function of its chunk, so a quest
        can name one nobody has walked to yet. Saved state is applied before judging a camp,
        so one the player already emptied is never handed out as a task."""
        held = [poi for poi in self.pois if poi.variant == "bandit" and not poi.guards_defeated and not poi.looted]
        if held:
            return min(held, key=lambda poi: poi.distance_to_point((x, y)))

        size = c.World.CHUNK_SIZE
        cx0, cy0 = self._chunk_of(x, y)
        for ring in range(1, c.World.CAMP_SEARCH_RINGS + 1):
            for cx in range(cx0 - ring, cx0 + ring + 1):
                for cy in range(cy0 - ring, cy0 + ring + 1):
                    if max(abs(cx - cx0), abs(cy - cy0)) != ring:
                        continue
                    center = ((cx + 0.5) * size, (cy + 0.5) * size)
                    for poi in pois_for_chunk(cx, cy, self.buildings_in_range(*center, c.World.CHUNK_SIZE)):
                        if poi.variant != "bandit":
                            continue
                        state = self.poi_state.get(poi.id)
                        if state:
                            poi.apply_state(state)
                        if not poi.guards_defeated and not poi.looted:
                            return poi
        return None

    def _spawn_camper(self, poi: PointOfInterest):
        """The trader living at a traveller camp: a merchant like any other, but stocked
        from the local loot tables rather than the LLM, since a lone camper in the wilds
        shouldn't hold the queue up behind a shop generation call."""
        if poi.npc_spawned:
            return
        poi.npc_spawned = True
        npc = NPC(poi.x + 62, poi.y + 60)
        npc.is_merchant = True
        npc.color = c.Colors.MERCHANT
        npc.home = (npc.x, npc.y)
        npc.set_shop(roll_shop_stock(c.PointsOfInterest.CAMPER_STOCK_SIZE))
        self.npcs.append(npc)

    def camp_is_clear(self, poi: PointOfInterest) -> bool:
        """True when a camp is safe to loot and to rest at.

        Two conditions, and they answer different questions. A bandit camp's garrison has to
        have been killed (`guards_defeated`, a count that survives the guards themselves
        being unloaded), which is what makes the cache the reward for taking the camp rather
        than for walking away and back. And whatever the camp, nothing hostile may be standing
        near the fire right now, so a wandering wolf still stops the player resting mid-fight."""
        if poi.variant == "bandit" and not poi.guards_defeated:
            return False
        threats = self.monsters + self.bosses + [cr for cr in self.critters if cr.hostile]
        return not any(
            entity.distance_to_point((poi.x, poi.y)) < c.PointsOfInterest.CAMP_CLEAR_RADIUS for entity in threats
        )

    def camp_in_reach(self, player: Player) -> PointOfInterest | None:
        """The campfire the player could rest at right now: near enough, still burning, and
        with nothing hostile around it. A fire still on its cooldown is offered anyway, so
        the prompt can say why nothing happens rather than silently vanishing."""
        pos = player.get_pos()
        camps = [
            poi
            for poi in self.pois
            if poi.has_fire
            and poi.distance_to_point(pos) < c.PointsOfInterest.REST_DISTANCE
            and self.camp_is_clear(poi)
        ]
        return min(camps, key=lambda poi: poi.distance_to_point(pos), default=None)

    def rest_ready_in(self, key: str) -> float:
        """Seconds until this fire or bed will serve the player again; 0 when it's ready now.
        Keyed by POI id for a campfire, by building id for a villager's bed."""
        return max(0.0, self.rest_cooldowns.get(key, 0.0) - time.time())

    def rest_at_camp(self, player: Player, poi: PointOfInterest):
        """Sit at a camp's fire: some health back, and the post-death weakness cleared.

        Not a full heal and not repeatable: this particular fire goes cold on the player for
        REST_COOLDOWN_S afterwards. Otherwise any cleared camp is a health button to stand
        next to, and the walk back to town for a bed or a potion stops meaning anything.
        """
        remaining = self.rest_ready_in(poi.id)
        if remaining > 0:
            if self.notify:
                self.notify(f"This fire has burned low. Usable again in {int(remaining) + 1}s", c.Colors.MUTED)
            return
        self.rest_cooldowns[poi.id] = time.time() + c.PointsOfInterest.REST_COOLDOWN_S
        player.heal(player.max_hp * c.PointsOfInterest.REST_HEAL_FRAC)
        player.clear_death_debuff()
        play_sound("rest")
        get_particles().spawn_burst(poi.x + 40, poi.y + 12, (255, 170, 60), count=18, speed=3, life=700, size=4)
        if self.notify:
            self.notify("You rest at the fire. Some wounds close, nerves steadied.", (255, 190, 110))

    # ------------------------------------------------------------------ under the well

    def well_in_reach(self, player: Player) -> Village | None:
        """The village well the player is standing at, or None. Every settlement has one and
        every one of them can be looked down; only some of them go anywhere."""
        pos = player.get_pos()
        reach = c.Villages.WELL_RADIUS + c.Buildings.INTERACT_DISTANCE
        near = [village for village in self.villages if village.distance_to_point(pos) <= reach]
        return min(near, key=lambda village: village.distance_to_point(pos), default=None)

    def tunnel_for(self, village: Village) -> Tunnel | None:
        """The dug-out under this village's well, built on first use and kept from then on.
        None for a well that is only a well."""
        if not has_tunnel(village.chunk):
            return None
        tunnel = Tunnel(village.chunk)
        cached = self.tunnels.get(tunnel.id)
        if cached is not None:
            return cached
        state = self.tunnel_state.get(tunnel.id)
        if state:
            tunnel.apply_state(state)
        self.tunnels[tunnel.id] = tunnel
        return tunnel

    def enter_tunnel(self, player: Player, village: Village) -> bool:
        """Climb down the well. Returns False when it leads nowhere, which is most of them.

        Nothing is loaded or unloaded: the tunnel is already part of the world, just a very
        long way from the ground the player was standing on, so this is a change of position
        and of what `World.update` bothers doing. What is waiting down there is stood up now
        rather than streamed, because nothing streams underground."""
        tunnel = self.tunnel_for(village)
        if tunnel is None:
            if self.notify:
                self.notify("You look down the well. Water, and a long way down to it.", c.Colors.MUTED)
            return False

        self.surface_return = (player.x, player.y)
        self.underground = tunnel
        player.x, player.y = tunnel.entrance
        self.projectiles.clear()
        self._populate_tunnel(tunnel)
        play_sound("door")
        if self.notify:
            self.notify("You climb down into the dark under the well", (170, 160, 200))
        return True

    def leave_tunnel(self, player: Player):
        """Back up the ladder, to the well the player climbed down. The garrison stays where
        it is: a tunnel is emptied by killing what is in it, not by walking out."""
        if self.underground is None:
            return
        x, y = self.surface_return or (c.World.WORLD_SIZE // 2, c.World.WORLD_SIZE // 2)
        self.abandon_tunnel()
        player.x, player.y = self.safe_spot_near(x, y, c.Player.SIZE / 2)
        play_sound("door")
        if self.notify:
            self.notify("You climb back out into the open air", c.Colors.WHITE)

    def abandon_tunnel(self):
        """Be somewhere else, without climbing out: what dying underground does. The player's
        own placing is the caller's business, since a death sends them to the world spawn and
        the ladder sends them back to the well."""
        tunnel = self.underground
        if tunnel is None:
            return
        self.tunnel_state[tunnel.id] = tunnel.state()
        self.underground = None
        self.surface_return = None
        self._clear_tunnel_monsters(tunnel)
        self.projectiles.clear()

    def _clear_tunnel_monsters(self, tunnel: Tunnel):
        """Take the tunnel's occupants off the world's lists. They are held as a count like a
        camp's garrison, so they are stood back up from it the next time anyone climbs down;
        left on the list they would be a pack of monsters milling about a million paces from
        anywhere, still being updated every frame."""
        self.monsters = [m for m in self.monsters if m.camp_id != tunnel.id]
        self.critters = [cr for cr in self.critters if cr.camp_id != tunnel.id]

    def _populate_tunnel(self, tunnel: Tunnel):
        """What is waiting down there: the survivors of its garrison, and its hoard the first
        time anyone gets this far.

        The garrison is a number exactly as a bandit camp's is (`camp_id` tags each one, which
        keeps them out of the save, out of the despawn and out of the roaming cap), so four of
        five killed survives climbing out, quitting and coming back."""
        if tunnel.guards_alive is None:
            tunnel.guards_alive = random.randint(*c.Tunnels.GUARDS)
        rng = random.Random(f"tunnel-fill:{tunnel.id}")

        for x, y in tunnel.floor_spots(tunnel.guards_alive, rng):
            guard = self._new_monster(x, y, danger_bonus=c.Tunnels.GUARD_DANGER_BONUS)
            guard.camp_id = tunnel.id
            self.monsters.append(guard)

        if not tunnel.hoard_placed:
            tunnel.hoard_placed = True
            for x, y in tunnel.floor_spots(random.randint(*c.Tunnels.HOARD), rng):
                self.items.append(Item(x, y, "Lootbox", "lootbox", rarity=roll_rarity()))
        self.tunnel_state[tunnel.id] = tunnel.state()

    def _restore_underground(self, saved: dict | None):
        """Put the player back in the tunnel a save was made in. Without this a game saved
        underground would load with the player standing in the middle of a million paces of
        nothing, with no rock around them and no way back."""
        if not saved:
            return
        village = next((v for v in self.villages if Tunnel(v.chunk).id == saved.get("id")), None)
        if village is None:
            return
        tunnel = self.tunnel_for(village)
        if tunnel is None:
            return
        self.underground = tunnel
        self.surface_return = tuple(saved.get("return") or tunnel.entrance)
        self._populate_tunnel(tunnel)

    def shrine_in_reach(self, player: Player) -> PointOfInterest | None:
        """The shrine the player could pray at right now: near enough, and not yet answered.
        A spent shrine offers nothing, so it stops prompting entirely."""
        pos = player.get_pos()
        shrines = [
            poi
            for poi in self.pois
            if poi.kind == "shrine"
            and not poi.prayed
            and poi.distance_to_point(pos) < c.PointsOfInterest.SHRINE_PRAY_DISTANCE
        ]
        return min(shrines, key=lambda poi: poi.distance_to_point(pos), default=None)

    def pray_at_shrine(self, player: Player, poi: PointOfInterest):
        """Take the shrine's one answer: usually a timed blessing, sometimes a curse. Once
        per shrine ever (`prayed` is persisted), so praying is a gamble rather than a tap.

        Blessings are the ordinary potion buffs, read back by the same multipliers, and the
        curses reuse what the game already does to the player: the Weakened state dying
        leaves behind, a bite out of the purse, a bite out of the health bar.
        """
        if poi.prayed:
            return
        poi.prayed = True
        self.poi_state[poi.id] = poi.state()

        if random.random() < c.PointsOfInterest.SHRINE_CURSE_CHANCE:
            kind, message = random.choice(c.PointsOfInterest.SHRINE_CURSES)
            amount = 0
            if kind == "weakness":
                player.apply_weakness(c.PointsOfInterest.SHRINE_CURSE_WEAKNESS_S)
            elif kind == "tithe":
                amount = int(player.coins * c.PointsOfInterest.SHRINE_CURSE_TITHE_FRAC)
                player.add_coins(-amount)
            else:
                player.receive_damage(
                    round(player.max_hp * c.PointsOfInterest.SHRINE_CURSE_WOUND_FRAC), source="an angry shrine"
                )
            get_particles().spawn_burst(poi.x, poi.y - 20, (120, 40, 140), count=22, speed=4, life=800, size=4)
            play_sound("player_hurt")
            if self.notify:
                self.notify(message.format(amount=amount), (190, 90, 200))
            return

        effect, magnitude, duration, message = random.choice(c.PointsOfInterest.SHRINE_BLESSINGS)
        player.apply_buff(effect, magnitude, duration)
        get_particles().spawn_burst(poi.x, poi.y - 20, (240, 225, 150), count=22, speed=4, life=800, size=4)
        play_sound("level_up")
        if self.notify:
            self.notify(message, (245, 230, 150))

    def mark_rumor(self, x: float, y: float, label: str):
        """Put a rumour's subject on the minimap. Session-only and deliberately not saved:
        a rumour is a lead to follow now, not a permanent pin, and it rubs itself out as
        soon as the player has walked close enough to see the place themselves."""
        self.rumor_marks.append({"x": x, "y": y, "label": label})

    def _clear_reached_rumors(self, player: Player):
        self.rumor_marks = [
            mark
            for mark in self.rumor_marks
            if math.hypot(mark["x"] - player.x, mark["y"] - player.y) > c.Minimap.RUMOR_CLEAR_DISTANCE
        ]

    def _village_crowd(self, npc: NPC) -> tuple:
        """The settlement this NPC belongs to and everyone standing on its grounds. A camper
        or a wandering merchant out in the wilds has no village behind them, only themselves."""
        village = self.village_at(npc.x, npc.y)
        if village is None:
            return None, [npc]
        return village, [other for other in self.npcs if village.contains_point(other.x, other.y)]

    def provoke_village(self, npc: NPC) -> List[NPC]:
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
        if newly_hostile and self.notify:
            name = village.name if village is not None and village.name else "The locals"
            self.notify(f"{name} turns on you!", c.Colors.RED)
        return newly_hostile

    def hold_grudge(self, npc: NPC) -> List[NPC]:
        """A villager is dead by the player's hand, and that one is never forgiven.

        Anger is a countdown; a killing is not. Everyone on this settlement's grounds is
        turned for good, with no clock left to run out, which is what keeps a death heavier
        than a brawl now that a brawl can be waited out."""
        village, crowd = self._village_crowd(npc)
        newly_hostile = [other for other in crowd if not other.hostile]
        for other in crowd:
            if other is not npc:
                other.anger(c.Villages.ANGER_S, permanent=True)
        if self.notify:
            name = village.name if village is not None and village.name else "The locals"
            self.notify(f"{name} will never forgive you", c.Colors.RED)
        return newly_hostile

    def witness_radius(self) -> float:
        """How far a villager notices a theft right now. Night cuts it, which is what makes
        robbing a house something you do after dark. Shared by the check and the cones the
        renderer draws, so what the player is shown is exactly what is tested."""
        return c.Crime.WITNESS_RADIUS * (c.Crime.NIGHT_WITNESS_MULT if self.daynight.is_night else 1.0)

    def watchers_near(self, x: float, y: float) -> List[NPC]:
        """Everyone close enough to (x, y) that their field of view is worth drawing, whether
        or not (x, y) actually falls inside it."""
        radius = self.witness_radius()
        return [npc for npc in self.npcs if not npc.hostile and npc.distance_to_point((x, y)) <= radius]

    def theft_witness(self, x: float, y: float) -> NPC | None:
        """Whoever sees the player helping themselves at (x, y), or None if nobody is looking.

        Deliberately no roll: near enough and facing the right way is the whole test, so
        getting caught is a decision the player made and not luck. The cone is what the
        renderer draws on the ground while a chest or a bed is in reach, so waiting for
        somebody to turn their back is a real answer rather than a guess. Anyone already
        hostile is past caring what else the player takes."""
        radius = self.witness_radius()
        seen = [npc for npc in self.watchers_near(x, y) if npc.sees(x, y, radius)]
        return min(seen, key=lambda npc: npc.distance_to_point((x, y)), default=None)

    def rest_in_house(self, building: Building) -> None:
        """Note that this household's bed has been slept in, so it isn't a free full heal to
        stand next to: the same cooldown a campfire gets, kept per building and persisted."""
        self.rest_cooldowns[building.id] = time.time() + c.PointsOfInterest.REST_COOLDOWN_S

    def pass_time(self, seconds: float) -> None:
        """Run the world forward by `seconds` without anything in it taking a step.

        Sleeping is the only thing that calls this. The day cycle is the visible half; the
        other half is every deadline held as a wall-clock time, which would otherwise sit
        untouched through a skipped night and leave a fire still cold and a village still
        furious at dawn. A grudge is deliberately not one of them: no amount of sleeping
        makes a village forget who killed one of them."""
        self.daynight.update(seconds * 1000)
        now = time.time()
        self.rest_cooldowns = {
            key: ready - seconds for key, ready in self.rest_cooldowns.items() if ready - seconds > now
        }
        for npc in self.npcs:
            if npc.hostile_until:
                npc.hostile_until = max(0.0, npc.hostile_until - seconds)

    def catch_thief(self, npc: NPC) -> NPC:
        """One villager catches the player stealing and comes for them, alone.

        The single exception to violence's all-or-nothing rule: theft is between the player
        and whoever saw it, so the rest of the village goes on with its day. Swinging back
        at the one who caught you is what turns the whole place, through the usual
        `provoke_village`. They cool off on their own clock like anyone else, a while after
        the player has stopped taking their things."""
        npc.anger(c.Crime.THEFT_ANGER_S)
        if self.notify:
            name = npc.name or "A villager"
            self.notify(f"{name} catches you in the act!", c.Colors.RED)
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
        intruders = [m for m in self.monsters if self.village_at(m.x, m.y, c.Villages.DEFEND_MARGIN) is not None]
        if not intruders:
            return fight, flee

        for npc in self.npcs:
            if npc.hostile:
                # Already coming for the player: the monster is the least of their problems.
                continue
            nearest = min(intruders, key=lambda m: npc.distance_to_point((m.x, m.y)))
            distance = npc.distance_to_point((nearest.x, nearest.y))
            if npc.is_militia:
                if distance <= c.Villages.DEFEND_RADIUS:
                    fight[id(npc)] = nearest
            elif distance <= c.Villages.PANIC_RADIUS:
                refuge = self._refuge_for(npc)
                if refuge is not None:
                    flee[id(npc)] = refuge
        return fight, flee

    def _refuge_for(self, npc: NPC) -> Building | None:
        """The nearest building this one can get behind a door of. Any door will do: a
        frightened person takes the nearest one, not their own."""
        shelters = [b for b in self.buildings_near(npc.x, npc.y) if b.has_door and not b.door_broken]
        return min(shelters, key=lambda b: npc.distance_to_point((b.x, b.y)), default=None)

    def house_to_rob(self, npc: NPC) -> Building | None:
        """A house in this NPC's village whose chest nobody has emptied yet, for a steal quest
        to name. None out in the wilds, or in a village already picked clean."""
        village = self.village_at(npc.x, npc.y)
        if village is None:
            return None
        houses = [
            building
            for building in self.buildings
            if building.kind == "house" and not building.looted and village.contains_point(building.x, building.y)
        ]
        return random.choice(houses) if houses else None

    def _check_poi_discovery(self, player: Player):
        """The one-time line a landmark gives up the first time the player walks to it: a
        shrine's flavor, a quiet landmark saying what it is, a signpost or a camper pointing
        the way to somewhere still unexplored."""
        pos = player.get_pos()
        for poi in self.pois:
            if poi.discovered or poi.distance_to_point(pos) >= c.PointsOfInterest.DISCOVER_DISTANCE:
                continue
            if poi.kind == "shrine":
                poi.discovered = True
                if self.notify:
                    flavor = random.choice(c.PointsOfInterest.SHRINE_MESSAGES)
                    self.notify(f"{flavor} {c.PointsOfInterest.SHRINE_EXPLANATION}", c.Colors.WHITE)
            elif poi.kind in c.PointsOfInterest.LANDMARK_MESSAGES:
                poi.discovered = True
                if self.notify:
                    self.notify(random.choice(c.PointsOfInterest.LANDMARK_MESSAGES[poi.kind]), c.Colors.WHITE)
            elif poi.kind == "signpost":
                poi.discovered = True
                if self.notify:
                    self.notify(self._signpost_directions(poi), (200, 190, 150))
            elif poi.variant == "traveller":
                poi.discovered = True
                if self.notify:
                    self.notify(self._traveller_directions(poi), (200, 190, 150))

    def unexplored_lead(self, from_x: float, from_y: float):
        """The nearest place the player has not walked to yet, as (distance, x, y, label),
        or None when everything around here is already known. Village sites and points of
        interest are both pure functions of their chunk, so this can point at places that
        have never been generated, which is exactly what makes it worth hearing. Shared by
        a traveller's directions and by the rumours the map marks."""
        best = None
        radius = c.PointsOfInterest.HINT_CHUNK_RADIUS
        cx, cy = self._chunk_of(from_x, from_y)
        size = c.World.CHUNK_SIZE
        for gx in range(cx - radius, cx + radius + 1):
            for gy in range(cy - radius, cy + radius + 1):
                candidates = [(site, "a settlement") for site in [village_site(gx, gy)] if site is not None]
                # Only the buildings around this chunk, not every one ever generated: the
                # POI generator just needs what it must keep clear of, and this runs once
                # per chunk in the search window.
                center = ((gx + 0.5) * size, (gy + 0.5) * size)
                for other in pois_for_chunk(gx, gy, self.buildings_in_range(*center, size)):
                    candidates.append(((other.x, other.y), _POI_HINT_LABELS[other.kind]))
                for (x, y), label in candidates:
                    distance = math.hypot(x - from_x, y - from_y)
                    if distance < c.PointsOfInterest.HINT_MIN_DISTANCE or self.is_explored(x, y):
                        continue
                    if best is None or distance < best[0]:
                        best = (distance, x, y, label)
        return best

    def _signpost_directions(self, poi: PointOfInterest) -> str:
        """What a signpost reads out: the way to the nearest place the player has not walked
        to, marked on the map like a rumour so the lead is worth the detour to read it."""
        best = self.unexplored_lead(poi.x, poi.y)
        if best is None:
            return "The signpost points at places you have already been."
        _distance, x, y, label = best
        bearing = _compass_direction(x - poi.x, y - poi.y)
        self.mark_rumor(x, y, label)
        return f"The signpost still reads: {label}, {bearing} of here."

    def _traveller_directions(self, poi: PointOfInterest) -> str:
        """What the camper at a traveller camp tells the player: where the nearest thing they
        have not walked to yet lies."""
        best = self.unexplored_lead(poi.x, poi.y)
        if best is None:
            return "The camper has nothing left to point you towards."
        distance, x, y, label = best
        bearing = _compass_direction(x - poi.x, y - poi.y)
        reach = "not far" if distance < 1800 else ("a fair walk" if distance < 3200 else "a long way")
        return f"The camper points {bearing}: {label}, {reach} from here."

    def is_explored(self, x, y) -> bool:
        """True once the player has walked close enough to this spot for the map to remember it."""
        cell = c.Fog.CELL
        return (int(x // cell), int(y // cell)) in self.explored

    def _reveal_around(self, player: Player):
        """Remember the ground around the player. Only recomputed when they cross into a new
        cell, so the common case costs one comparison."""
        cell = c.Fog.CELL
        here = (int(player.x // cell), int(player.y // cell))
        if here == self._last_reveal_cell:
            return
        self._last_reveal_cell = here
        span = int(c.Fog.REVEAL_RADIUS // cell) + 1
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                gx, gy = here[0] + dx, here[1] + dy
                center = ((gx + 0.5) * cell, (gy + 0.5) * cell)
                if math.hypot(center[0] - player.x, center[1] - player.y) <= c.Fog.REVEAL_RADIUS:
                    self.explored.add((gx, gy))
