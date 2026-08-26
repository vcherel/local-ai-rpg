from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

import core.constants as c
from core.audio import play_sound
from core.particles import get_particles
from game.entities.boss import Boss
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
    "cave": "a cave mouth",
}

# Any kind added later still gets a sentence rather than a KeyError mid-conversation.
_POI_HINT_FALLBACK = "somewhere worth a look"


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
        the camp. Every chunk load stands the survivors back up around the fire, `_unload_chunks`
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
            # It mills about its own fire rather than standing to attention at it, and never
            # wanders off the camp it is the garrison of.
            guard.post_at(poi.x, poi.y, spread)
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
            if isinstance(monster, Boss):
                # The warden is not one of the garrison: killing it empties the vault of the
                # one thing standing over it, and it never stands there again.
                tunnel.warden_alive = False
            else:
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

    def find_bandit_camp(self, x: float, y: float, min_distance: float = 0.0) -> PointOfInterest | None:
        """A bandit camp still held, for a clear_camp quest to send the player at, no nearer
        than `min_distance` from where the quest is being given.

        Loaded chunks first, then rings of chunks outward, generated from their coordinates
        exactly as `_load_chunk` would: a camp is a pure function of its chunk, so a quest
        can name one nobody has walked to yet. Saved state is applied before judging a camp,
        so one the player already emptied is never handed out as a task."""
        held = [
            poi
            for poi in self.pois
            if poi.variant == "bandit"
            and not poi.guards_defeated
            and not poi.looted
            and poi.distance_to_point((x, y)) >= min_distance
        ]
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
                        if poi.guards_defeated or poi.looted:
                            continue
                        if math.hypot(poi.x - x, poi.y - y) >= min_distance:
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

    def _nearest_poi(self, player: Player, reach: float, wanted) -> PointOfInterest | None:
        """The nearest loaded landmark within `reach` that `wanted` says yes to, or None.

        The one shape behind every `*_in_reach`: what differs between a fire, a shrine and a
        cave mouth is how close counts and what makes one worth offering, never how the
        nearest of them is found. Nearest rather than first, so standing between two of
        anything prompts for the one actually underfoot."""
        pos = player.get_pos()
        found = [poi for poi in self.pois if poi.distance_to_point(pos) < reach and wanted(poi)]
        return min(found, key=lambda poi: poi.distance_to_point(pos), default=None)

    def camp_in_reach(self, player: Player) -> PointOfInterest | None:
        """The campfire the player could rest at right now: near enough, still burning, and
        with nothing hostile around it. A fire still on its cooldown is offered anyway, so
        the prompt can say why nothing happens rather than silently vanishing."""
        return self._nearest_poi(
            player,
            c.PointsOfInterest.REST_DISTANCE,
            lambda poi: poi.has_fire and self.camp_is_clear(poi),
        )

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
        play_sound("fire_crackle")
        self._rest_animation(poi.x + 40, poi.y + 12, player)
        if self.notify:
            self.notify("You rest at the fire. Some wounds close, nerves steadied.", (255, 190, 110))

    @staticmethod
    def _rest_animation(fire_x, fire_y, player: Player):
        """The couple of seconds a rest takes to look like one: the fire flaring up, embers
        going off it, and the warmth rising off the player who sat down at it.

        Cosmetic from end to end. The health and the cleared weakness are already theirs
        (the fire is what is on cooldown, not the player), so nothing here can be lost by
        walking away in the middle of it, and nothing has to be checked for interruption."""
        particles = get_particles()
        duration = c.PointsOfInterest.REST_ANIM_MS
        particles.emit_over(
            fire_x, fire_y, duration, interval_ms=110, color=(255, 170, 60), count=5, speed=3, life=800, size=4
        )
        # The embers that get away from it, slower and darker, drifting up off the flame.
        particles.emit_over(
            fire_x, fire_y, duration, interval_ms=180, color=(200, 90, 40), count=2, speed=1.5, life=1400, size=3
        )
        particles.emit_over(
            player.x,
            player.y,
            duration,
            interval_ms=240,
            color=(180, 230, 190),
            count=2,
            speed=1.2,
            life=900,
            size=3,
        )

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
        return self.tunnel_at(village.chunk, "well")

    def tunnel_at(self, chunk: tuple[int, int], kind: str) -> Tunnel:
        """The tunnel reached from this chunk by `kind`, built on first use and kept from
        then on. The one place a tunnel is ever made, so whatever it has already lost to the
        player is put back on it whichever way in they used."""
        tunnel = Tunnel(chunk, kind)
        cached = self.tunnels.get(tunnel.id)
        if cached is not None:
            return cached
        state = self.tunnel_state.get(tunnel.id)
        if state:
            tunnel.apply_state(state)
        self.tunnels[tunnel.id] = tunnel
        return tunnel

    def cave_in_reach(self, player: Player) -> PointOfInterest | None:
        """The cave mouth the player is standing at, or None. Unlike a well, every one of
        them goes somewhere: a cave is what puts the dark within reach of somebody who has
        walked out into the wilds rather than into a village."""
        return self._nearest_poi(player, c.PointsOfInterest.CAVE_ENTER_DISTANCE, lambda poi: poi.kind == "cave")

    def enter_cave(self, player: Player, poi: PointOfInterest):
        """Walk in through a cave mouth, into the same dark a well leads down to."""
        cx, cy = (int(part) for part in poi.id.split(":"))
        self._go_underground(player, self.tunnel_at((cx, cy), "cave"))
        if self.notify:
            self.notify("You duck under the rock and into the dark", (170, 160, 200))

    def enter_tunnel(self, player: Player, village: Village) -> bool:
        """Climb down the well. Returns False when it leads nowhere, which is most of them."""
        tunnel = self.tunnel_for(village)
        if tunnel is None:
            if self.notify:
                self.notify("You look down the well. Water, and a long way down to it.", c.Colors.MUTED)
            return False

        self._go_underground(player, tunnel)
        if self.notify:
            self.notify("You climb down into the dark under the well", (170, 160, 200))
        return True

    def _go_underground(self, player: Player, tunnel: Tunnel):
        """Be down there. Nothing is loaded or unloaded: the tunnel is already part of the
        world, just a very long way from the ground the player was standing on, so this is a
        change of position and of what `World.update` bothers doing. What is waiting is
        stood up now rather than streamed, because nothing streams underground."""
        self.surface_return = (player.x, player.y)
        self.underground = tunnel
        player.x, player.y = tunnel.entrance
        self.projectiles.clear()
        self._populate_tunnel(tunnel)
        play_sound("door")

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
        anywhere, still being updated every frame.

        A cave's warden goes with them, which is the one boss in the game that is ever taken
        off the map alive: it belongs to its vault rather than to the world, so it is held as
        a flag on the tunnel (`warden_alive`) exactly as the garrison is held as a count."""
        self.monsters = [m for m in self.monsters if m.camp_id != tunnel.id]
        self.critters = [cr for cr in self.critters if cr.camp_id != tunnel.id]
        warden = next((b for b in self.bosses if b.camp_id == tunnel.id), None)
        if warden is not None:
            # Whatever the model called it while the player was down there is kept, so it is
            # the same named thing standing over the vault on the next descent.
            tunnel.warden_name = warden.display_name
        self.bosses = [b for b in self.bosses if b.camp_id != tunnel.id]

    def _populate_tunnel(self, tunnel: Tunnel):
        """What is waiting down there: the survivors of its garrison, its hoard the first
        time anyone gets this far, and in a cave the bats, the vault and whatever stands
        over it.

        The garrison is a number exactly as a bandit camp's is (`camp_id` tags each one, which
        keeps them out of the save, out of the despawn and out of the roaming cap), so four of
        five killed survives climbing out, quitting and coming back. Everything else down
        here is held the same way, for the same reason."""
        if tunnel.guards_alive is None:
            tunnel.guards_alive = random.randint(*tunnel.guard_count)
        rng = random.Random(f"tunnel-fill:{tunnel.id}")

        for x, y in tunnel.floor_spots(tunnel.guards_alive, rng, clearance=c.Tunnels.ENTRANCE_CLEARANCE):
            guard = self._new_monster(x, y, danger_bonus=c.Tunnels.GUARD_DANGER_BONUS)
            guard.camp_id = tunnel.id
            # Held to the room it was put in: a garrison that roamed the whole tunnel would
            # be found by walking rather than by looking.
            guard.post_at(x, y, c.Tunnels.CORRIDOR_WIDTH)
            self.monsters.append(guard)

        if not tunnel.hoard_placed:
            tunnel.hoard_placed = True
            luck = self._tunnel_luck(tunnel)
            for x, y in tunnel.floor_spots(random.randint(*c.Tunnels.HOARD), rng, c.Tunnels.ENTRANCE_CLEARANCE):
                self.items.append(Item(x, y, "Lootbox", "lootbox", rarity=roll_rarity(luck=luck)))

        self._populate_cave(tunnel, rng)
        self.tunnel_state[tunnel.id] = tunnel.state()

    @staticmethod
    def _tunnel_distance(tunnel: Tunnel) -> float:
        """How far from the world centre the way into this tunnel stands. The rooms
        themselves are dug a million paces off in their own corner of world space, so their
        own coordinates say nothing about how deep into the wilds the player walked to
        reach them: the chunk the well or the cave mouth sits in is what does."""
        center = c.World.WORLD_SIZE // 2
        size = c.World.CHUNK_SIZE
        return math.hypot((tunnel.chunk[0] + 0.5) * size - center, (tunnel.chunk[1] + 0.5) * size - center)

    def _tunnel_luck(self, tunnel: Tunnel) -> float:
        """How much better what is down here is than what is down nearer home. The dark
        under the starting town is a cellar with a few boxes in it; the dark under a cave
        eight thousand paces out is why anybody walks eight thousand paces. Fed to the same
        rarity ladder everything else in the world rolls on."""
        return self._tunnel_distance(tunnel) / 1000.0 * c.Tunnels.HOARD_LUCK_PER_1000

    def _populate_cave(self, tunnel: Tunnel, rng: random.Random):
        """What a cave has that a well does not: the bats that live in it, the vault at the
        far end, and out past `Tunnels.WARDEN_MIN_DISTANCE` the warden standing over it.

        This is the whole answer to a cave being somewhere to walk past. A well is a cellar
        under a village; a cave is the one place in the world holding a boss that waits to be
        found rather than one that comes looking, and the one reward that is not rolled for."""
        if tunnel.kind == "well" or tunnel.vault is None:
            return

        # Woken by the walking in, every time: bats are not something a cave is cleared of.
        for x, y in tunnel.floor_spots(random.randint(*c.Tunnels.BATS), rng, c.Tunnels.ENTRANCE_CLEARANCE):
            bat = Critter(x, y, c.CRITTER_KINDS_BY_NAME["bat"], home=(x, y), camp_id=tunnel.id)
            self.critters.append(bat)

        if tunnel.warden_alive is None:
            tunnel.warden_alive = self._tunnel_distance(tunnel) >= c.Tunnels.WARDEN_MIN_DISTANCE
        if tunnel.warden_alive:
            # Which one stands here is the tunnel's own roll rather than a fresh one, the way
            # everything else about a place is a pure function of where it is: a warden that
            # was a colossus yesterday is not a warlock today.
            template = random.Random(f"warden:{tunnel.id}").choice(c.BOSS_KINDS)
            warden = self.spawn_boss(*tunnel.vault.center, template=template, name=tunnel.warden_name)
            warden.camp_id = tunnel.id
            # It is already standing there and has been for a long time: the ground opening
            # under it is for something that has just arrived.
            warden.rising = 0.0

        if not tunnel.vault_placed:
            tunnel.vault_placed = True
            box = Item(*tunnel.vault.center, "Lootbox", "lootbox", rarity=c.Tunnels.VAULT_RARITY)
            self.items.append(box)

    def _restore_underground(self, saved: dict | None):
        """Put the player back in the tunnel a save was made in. Without this a game saved
        underground would load with the player standing in the middle of a million paces of
        nothing, with no rock around them and no way back."""
        if not saved:
            return
        tunnel = self._tunnel_from_id(saved.get("id") or "")
        if tunnel is None:
            return
        self.underground = tunnel
        self.surface_return = tuple(saved.get("return") or tunnel.entrance)
        self._populate_tunnel(tunnel)

    def _tunnel_from_id(self, tunnel_id: str) -> Tunnel | None:
        """The tunnel a saved id names, rebuilt from the id alone: "tunnel:cx:cy" for a
        well, "tunnel:cave:cx:cy" for a cave. Read back rather than looked up, since the
        village or the landmark it belongs to may not be loaded at all."""
        parts = tunnel_id.split(":")
        if len(parts) not in (3, 4) or parts[0] != "tunnel":
            return None
        kind = "well" if len(parts) == 3 else parts[1]
        try:
            chunk = (int(parts[-2]), int(parts[-1]))
        except ValueError:
            return None
        return self.tunnel_at(chunk, kind)

    def shrine_in_reach(self, player: Player) -> PointOfInterest | None:
        """The shrine the player could pray at right now: near enough, and not yet answered.
        A spent shrine offers nothing, so it stops prompting entirely."""
        return self._nearest_poi(
            player,
            c.PointsOfInterest.SHRINE_PRAY_DISTANCE,
            lambda poi: poi.kind == "shrine" and not poi.prayed,
        )

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
        # The gates come back off the bar on the next frame of `_bar_gates` now that nobody
        # inside is angry, so the player can walk back into the place they died in.
        return village

    def barred_gate_in_reach(self, player: Player) -> tuple | None:
        """The barred gate the player is standing at, as (village, index), or None.

        The one thing that makes a shut town something to leave rather than something to
        besiege. Read by the prompt and by the hold that actually lifts the beam
        (`Game._lift_gate`), so what the player is offered is exactly what the key works on."""
        for village in self.villages:
            if not village.defended or not village.barred:
                continue
            if village.distance_to_point((player.x, player.y)) > village.grounds_radius:
                continue
            index = village.gate_at(player.x, player.y, c.Buildings.INTERACT_DISTANCE)
            if index is not None:
                return village, index
        return None

    def witness_radius(self) -> float:
        """How far a villager notices a theft right now. Night cuts it, which is what makes
        robbing a house something you do after dark. Shared by the check and the cones the
        renderer draws, so what the player is shown is exactly what is tested."""
        return c.Crime.WITNESS_RADIUS * (c.Crime.NIGHT_WITNESS_MULT if self.daynight.is_night else 1.0)

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
        if not npc.sees(x, y, radius):
            return False
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

    def squatter_witness(self, x: float, y: float) -> NPC | None:
        """Whoever finds the player asleep in a bed that isn't theirs, or None where nobody
        lives close enough to walk in on them.

        Deliberately not `theft_witness`: taking something is an instant somebody either
        had eyes on or did not, and a night is hours of a settlement's people coming and
        going. So there is no cone and no line of sight here, only the household: anyone of
        this settlement standing within `Crime.SQUAT_WITNESS_RADIUS` of the bed by morning
        has found the player in it, which is what makes a tavern room something taken rather
        than something free."""
        village = self.village_at(x, y)
        if village is None:
            return None
        found = [
            npc
            for npc in self.npcs
            if not npc.hostile
            and village.contains_point(npc.x, npc.y)
            and npc.distance_to_point((x, y)) < c.Crime.SQUAT_WITNESS_RADIUS
        ]
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
        if not intruders:
            return fight, flee

        for npc in self.npcs:
            if npc.hostile:
                # Already coming for the player: the monster is the least of their problems.
                continue
            nearest = min(intruders, key=lambda m: npc.distance_to_point((m.x, m.y)))
            distance = npc.distance_to_point((nearest.x, nearest.y))
            boss = isinstance(nearest, Boss)
            if npc.is_militia:
                if distance <= (c.Villages.BOSS_DEFEND_RADIUS if boss else c.Villages.DEFEND_RADIUS):
                    fight[id(npc)] = nearest
            elif distance <= (c.Villages.BOSS_PANIC_RADIUS if boss else c.Villages.PANIC_RADIUS):
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
            # A room whose furniture had to be shuffled round the neck of an L can end up
            # with nowhere to stand a chest: a quest may not send the player to rob one.
            if building.kind == "house"
            and not building.looted
            and building.interior_layout()["chest"] is not None
            and village.contains_point(building.x, building.y)
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
                    candidates.append(((other.x, other.y), _POI_HINT_LABELS.get(other.kind, _POI_HINT_FALLBACK)))
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
