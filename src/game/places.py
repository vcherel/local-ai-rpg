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
from game.entities.village import Village
from game.entities.village_sites import village_site
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
    shrine they pray at, the dark a well or a cave leads down to, the directions a signpost
    or a camper gives, and the ground the minimap remembers. What a settlement thinks of
    the player is `WorldSocial` (game/social.py), not here.

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
        # The cells change size on the way down, so the last one walked through means
        # nothing any more.
        self._last_reveal_cell = None
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
        self._last_reveal_cell = None
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
        return self._tunnel_distance(tunnel) / c.Tunnels.HOARD_LUCK_PACES * c.Tunnels.HOARD_LUCK_PER_PACES

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

    def sprung_trap_in_reach(self, player: Player):
        """The shut bear trap the player could set again, or None. Nothing else about a trap
        is ever offered: a trap still waiting is left well alone."""
        # Never from inside the jaws: setting one under your own foot would shut it on the
        # foot, which is a prompt that punishes the player for taking it.
        clear = c.Traps.TRIGGER_RADIUS + c.Player.SIZE / 2
        best = None
        for trap in self.traps:
            if not trap.sprung:
                continue
            distance = trap.distance_to_point(player.get_pos())
            if clear < distance < c.Traps.REARM_DISTANCE and (best is None or distance < best[0]):
                best = (distance, trap)
        return None if best is None else best[1]

    def rearm_trap(self, trap):
        """Haul the jaws back open and set the plate. Whoever laid the line is long gone, so
        a trap the player has already paid for is one they can turn round and leave for
        whatever comes after them: it costs nothing but the seconds it takes, and from then
        on it shuts on the next thing along, the player included."""
        trap.sprung = False
        self.trap_state.pop(trap.id, None)
        play_sound("trap_snap")
        get_particles().spawn_burst(trap.x, trap.y, (150, 148, 140), count=10, speed=4, life=320, size=3, gravity=0.4)
        if self.notify:
            self.notify("The trap is set again", c.Colors.MUTED)

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

    def mark_death_drop(self, x: float, y: float):
        """Pin where the player died, so the coins and the gear on the ground there can be
        walked back to from world spawn. One pin at a time: dying on the way to your last
        death's things moves it, since what was there is now here."""
        self.death_drop = {"x": x, "y": y}

    def _clear_reached_death_drop(self, player: Player):
        """Rub the pin out once the player is standing where they fell. Close enough to see
        it is close enough: from there the loot's own ground glow and the magnet take over,
        whether or not anything is actually left to pick up."""
        if self.death_drop is None:
            return
        distance = math.hypot(self.death_drop["x"] - player.x, self.death_drop["y"] - player.y)
        if distance <= c.Minimap.DEATH_CLEAR_DISTANCE:
            self.death_drop = None

    def _clear_reached_rumors(self, player: Player):
        self.rumor_marks = [
            mark
            for mark in self.rumor_marks
            if math.hypot(mark["x"] - player.x, mark["y"] - player.y) > c.Minimap.RUMOR_CLEAR_DISTANCE
        ]

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

    def shut_gate_in_reach(self, player: Player) -> tuple | None:
        """The gate the player is standing at that is shut but not barred, as (village,
        index), or None.

        A village shuts itself for the night without deciding anything about the player, so
        this one is a press rather than a hold (`Village.push_open`): the cost of arriving
        after dark is a beat at the gate. A barred gate is never offered here, since it is
        the other prompt's (`barred_gate_in_reach`)."""
        for village in self.villages:
            if not village.defended or village.barred or not village.shut_for_night:
                continue
            if village.distance_to_point((player.x, player.y)) > village.grounds_radius:
                continue
            index = village.gate_at(player.x, player.y, c.Buildings.INTERACT_DISTANCE)
            if index is not None and not village.gate_ajar(index):
                return village, index
        return None

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
                if poi.wrecked:
                    # Nothing left to read: whoever put the post through took the directions
                    # with it, and walking up to it again will not bring them back.
                    continue
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

    @property
    def fog_cell(self) -> int:
        """How coarsely the map remembers where the player has been. One size on the surface
        and a much finer one underground, where the whole place would otherwise be a single
        cell. Both are cells of the same world grid, so the tunnels sit in their own far-off
        corner of it and nothing has to know which kind a saved cell was."""
        return c.Fog.TUNNEL_CELL if self.underground is not None else c.Fog.CELL

    def is_explored(self, x, y) -> bool:
        """True once the player has walked close enough to this spot for the map to remember it."""
        cell = self.fog_cell
        return (int(x // cell), int(y // cell)) in self.explored

    def _reveal_around(self, player: Player):
        """Remember the ground around the player. Only recomputed when they cross into a new
        cell, so the common case costs one comparison.

        Underground the reach is the lantern's rather than the horizon's, and only floor is
        remembered: rock is not somewhere the player has been, and leaving it out is what
        makes the map draw the rooms and the corridors themselves as they are walked instead
        of a smear over the middle of them."""
        tunnel = self.underground
        cell = self.fog_cell
        radius = c.Fog.TUNNEL_REVEAL_RADIUS if tunnel is not None else c.Fog.REVEAL_RADIUS
        here = (int(player.x // cell), int(player.y // cell))
        if here == self._last_reveal_cell:
            return
        self._last_reveal_cell = here
        span = int(radius // cell) + 1
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                gx, gy = here[0] + dx, here[1] + dy
                center = ((gx + 0.5) * cell, (gy + 0.5) * cell)
                if math.hypot(center[0] - player.x, center[1] - player.y) > radius:
                    continue
                if tunnel is not None and not tunnel.contains_point(*center):
                    continue
                self.explored.add((gx, gy))
