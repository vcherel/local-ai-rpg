from __future__ import annotations

import math
import random
from functools import lru_cache
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.damage_fx import draw_cracks, get_damage_fx
from game.entities.terrain import river_points_for_chunk
from game.entities.village import register_site_cache, site_grounds_radius, village_site

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.buildings import Building


class PointOfInterest:
    """A wilderness landmark scattered between villages, so exploring away from the beaten
    path finds something worth the detour.

    "ruins" is a smashable loot cache (game.loot.open_poi_cache); "shrine" says what it is
    the first time the player walks up to it and can then be prayed at once, answering with
    a timed blessing or with a curse (World.pray_at_shrine); "camp" is either of two things,
    rolled from the POI's id so it never changes under the player. A bandit camp posts guards
    around a cache that stays shut until they are dead; a traveller camp holds a camper who
    trades and points the way. Either camp's fire can be rested at once nothing hostile is
    standing near it. "farmstead" is a second lootable cache with a look of its own;
    "graveyard", "watchtower" and "stones" are places rather than rewards, each saying what
    it is the first time it is reached; "signpost" reads out the way to somewhere the player
    has never walked and marks it on the map, like a rumour. "cave" is a mouth in the rock
    leading into the same dark a village well drops into (`World.enter_cave`), which is what
    puts the underground within reach of somebody who never walked into a town.
    """

    def __init__(self, x, y, kind="ruins", poi_id=""):
        self.x = x
        self.y = y
        self.kind = kind
        # Stable identity ("cx:cy" of the chunk that generated it): the world is endless
        # and POIs are regenerated from their chunk every time it loads, so only what the
        # player changed (looted, discovered, camper spawned) is saved, keyed by this.
        self.id = poi_id
        self.looted = False
        self.discovered = False  # shrine announced itself / traveller camp met
        self.prayed = False  # this shrine has already answered, for good or ill
        self.npc_spawned = False  # traveller camp: its camper already exists in world.npcs
        # Bandit camp garrison, as a count rather than as entities. None until the camp has
        # first been seen, then the number of ordinary guards still alive plus whether the
        # leader is. This is the camp: the monsters standing in it are put there from these
        # numbers when its chunk loads and taken away with the chunk, so a camp costs the
        # same whether the player found five of them or five hundred.
        self.guards_alive: int | None = None
        self.leader_alive = False
        # How much more the cache has to take before it gives. Session-only on purpose:
        # a POI is rebuilt from its chunk seed every time the chunk loads, and half a
        # strongbox's worth of dents is not worth a line in the save.
        self.cache_hp = c.PointsOfInterest.CACHE_HP

    @property
    def variant(self) -> str:
        """Either bandit or traveller for a camp, empty for anything else. Rolled from the id,
        so a camp is the same kind of camp every time its chunk loads."""
        if self.kind != "camp":
            return ""
        roll = random.Random(f"camp:{self.id}").random()
        return "bandit" if roll < c.PointsOfInterest.CAMP_BANDIT_CHANCE else "traveller"

    @property
    def has_loot(self) -> bool:
        return self.kind in ("ruins", "farmstead") or self.variant == "bandit"

    @property
    def has_fire(self) -> bool:
        """Every camp keeps a fire going, cleared out or not: it is what the player rests at,
        and a bandit camp is worth remembering precisely because taking it leaves one burning
        out in the wilds. What a sacked camp loses is its tents, not its fire."""
        return self.kind == "camp"

    @property
    def touched(self) -> bool:
        """True once this POI holds state worth saving; an untouched one is fully described
        by its chunk seed."""
        return self.looted or self.discovered or self.prayed or self.npc_spawned or self.guards_alive is not None

    @property
    def guards_remaining(self) -> int:
        """How many bandits should be standing here, leader included."""
        return (self.guards_alive or 0) + (1 if self.leader_alive else 0)

    @property
    def guards_defeated(self) -> bool:
        """True once this camp's garrison has actually been killed, as opposed to never
        having been posted. What opens a bandit camp's cache."""
        return self.guards_alive is not None and self.guards_remaining == 0

    def guard_killed(self, leader: bool):
        """Take one bandit off the camp's roll. The count is the only record of the fight:
        the guards themselves come and go with the chunk."""
        if leader:
            self.leader_alive = False
        elif self.guards_alive:
            self.guards_alive -= 1

    def distance_to_point(self, point) -> float:
        return math.hypot(self.x - point[0], self.y - point[1])

    def state(self) -> dict:
        return {
            "looted": self.looted,
            "discovered": self.discovered,
            "npc_spawned": self.npc_spawned,
            "prayed": self.prayed,
            "guards_alive": self.guards_alive,
            "leader_alive": self.leader_alive,
        }

    def apply_state(self, state: dict):
        self.looted = state.get("looted", False)
        self.discovered = state.get("discovered", False)
        self.npc_spawned = state.get("npc_spawned", False)
        self.prayed = state.get("prayed", False)
        # A save from before camps counted their garrison leaves this None, so the camp
        # rolls a fresh one the next time it is walked up to.
        self.guards_alive = state.get("guards_alive")
        self.leader_alive = state.get("leader_alive", False)

    def draw(self, screen: pygame.Surface, camera: Camera):
        sx, sy = camera.world_to_screen(self.x, self.y)
        # A cache being forced open flinches and cracks like any other breakable, so the
        # blows land visibly instead of the pile sitting untouched until it gives.
        offset = get_damage_fx().offset(f"poi:{self.id}")
        center = (round(sx) + offset[0], round(sy) + offset[1])
        _DRAWERS.get(self.kind, PointOfInterest._draw_ruins)(self, screen, center)

        if self.has_loot and not self.looted and self.cache_hp < c.PointsOfInterest.CACHE_HP:
            wear = pygame.Rect(0, 0, 56, 44)
            wear.center = center
            draw_cracks(screen, wear, self.cache_hp / c.PointsOfInterest.CACHE_HP, self.id)

    def _draw_farmstead(self, screen, center):
        """A caved-in barn with its fence still half standing. Lootable like a ruins pile,
        so once emptied the barn is drawn open and the cart is tipped over."""
        cx, cy = center
        rng = random.Random(f"farm:{self.x},{self.y}")
        barn = pygame.Rect(0, 0, 76, 54)
        barn.center = (cx, cy - 6)
        pygame.draw.rect(screen, (128, 96, 66), barn, border_radius=3)
        pygame.draw.rect(screen, (78, 56, 38), barn, 3, border_radius=3)
        roof = pygame.Rect(barn.left + 6, barn.top + 6, barn.width - 12, barn.height - 14)
        pygame.draw.rect(screen, (146, 74, 56) if not self.looted else (96, 72, 60), roof)
        # The collapsed corner: a hole in the roof, wider once the place has been searched.
        hole = pygame.Rect(0, 0, 26 if not self.looted else 38, 20 if not self.looted else 28)
        hole.center = (roof.centerx + 8, roof.centery)
        pygame.draw.ellipse(screen, (52, 40, 32), hole)

        for i in range(5):
            post_x = cx - 62 + i * 14
            pygame.draw.line(screen, (110, 88, 60), (post_x, cy + 26), (post_x, cy + 12 + rng.randint(0, 6)), 3)
        pygame.draw.line(screen, (110, 88, 60), (cx - 62, cy + 18), (cx - 8, cy + 18), 2)

        cart = pygame.Rect(0, 0, 34, 16)
        cart.center = (cx + 62, cy + 20)
        pygame.draw.rect(screen, (120, 92, 58), cart, border_radius=3)
        pygame.draw.circle(screen, (74, 56, 36), (cart.left + 6, cart.bottom), 7)
        pygame.draw.circle(screen, (74, 56, 36), (cart.right - 6, cart.bottom), 7)

    def _draw_cave(self, screen, center):
        """A shoulder of rock with a black mouth in it. The opening is drawn as flat black
        rather than as shaded stone, because the one thing it has to say from across the
        screen is that it goes somewhere."""
        cx, cy = center
        rng = random.Random(f"cave:{self.x},{self.y}")
        face = pygame.Rect(0, 0, 128, 88)
        face.center = (cx, cy)
        pygame.draw.ellipse(screen, (118, 114, 106), face)
        pygame.draw.ellipse(screen, (78, 76, 70), face, 3)
        # Boulders piled either side of the opening, so the rock reads as a hillside rather
        # than as one grey blob with a hole in it.
        for side in (-1, 1):
            for step in range(2):
                pos = (round(cx + side * (58 + step * 20)), round(cy + 16 + step * 10))
                grey = rng.randint(124, 146)
                pygame.draw.circle(screen, (grey, grey - 4, grey - 12), pos, rng.randint(11, 18))
        mouth = pygame.Rect(0, 0, 62, 58)
        mouth.midbottom = (cx, cy + 36)
        pygame.draw.ellipse(screen, (24, 22, 20), mouth)
        # The lit lip over the opening, so the mouth reads as an overhang rather than as a
        # hole painted on a rock.
        pygame.draw.arc(screen, (152, 148, 138), mouth.inflate(10, 10), 0.2, math.pi - 0.2, 4)

    def _draw_graveyard(self, screen, center):
        cx, cy = center
        rng = random.Random(f"grave:{self.x},{self.y}")
        # A graveyard is read from its stones, not from a border drawn round them: the plot
        # rectangle made it a fenced allotment dropped in a field. The rows are still real
        # (one stone size, a fixed spacing) but they run over a much wider stretch of
        # ground, several of them are missing and every one leans its own way, so the shape
        # reads as a place people were buried in rather than as a grid.
        columns, rows = 6, 4
        step_x, step_y = 74, 78
        width, height = 16, 24
        for slot in range(columns * rows):
            ox = (slot % columns - (columns - 1) / 2) * step_x + rng.uniform(-14, 14)
            oy = (slot // columns - (rows - 1) / 2) * step_y + rng.uniform(-12, 12)
            if rng.random() < 0.28:
                # Nothing left of this one but the ground it settled into.
                mound = pygame.Rect(0, 0, width + 14, 12)
                mound.center = (round(cx + ox), round(cy + oy))
                pygame.draw.ellipse(screen, (84, 82, 62), mound)
                continue
            stone = pygame.Rect(0, 0, width, height)
            stone.center = (round(cx + ox), round(cy + oy))
            lean = rng.choice((-2, -1, 0, 0, 1, 2))
            stone.move_ip(lean, 0)
            grey = rng.randint(132, 148)
            pygame.draw.rect(screen, (grey, grey, grey - 6), stone, border_top_left_radius=8, border_top_right_radius=8)
            pygame.draw.rect(screen, (78, 78, 74), stone, 2, border_top_left_radius=8, border_top_right_radius=8)
            # The mound in front of it, so the stones read as graves rather than as rubble.
            mound = pygame.Rect(0, 0, width + 8, 8)
            mound.midtop = stone.midbottom
            pygame.draw.ellipse(screen, (78, 70, 54), mound)
            # Somebody still comes: a few of the graves are kept, and the flowers are what
            # says so from a distance.
            if rng.random() < 0.35:
                color = rng.choice(((228, 96, 112), (236, 202, 92), (170, 128, 220), (240, 240, 232)))
                for _ in range(rng.randint(2, 4)):
                    head = (round(mound.centerx + rng.uniform(-14, 14)), round(mound.centery + rng.uniform(-2, 8)))
                    pygame.draw.line(screen, (66, 108, 52), (head[0], head[1] + 6), head, 2)
                    pygame.draw.circle(screen, color, head, rng.randint(3, 4))

    def _draw_watchtower(self, screen, center):
        cx, cy = center
        pygame.draw.circle(screen, (60, 58, 52), (cx + 6, cy + 8), 40)
        pygame.draw.circle(screen, (158, 152, 140), (cx, cy), 38)
        pygame.draw.circle(screen, (96, 92, 84), (cx, cy), 38, 3)
        pygame.draw.circle(screen, (108, 104, 96), (cx, cy), 22)
        # Merlons around the rim, with one stretch fallen away.
        for i in range(10):
            if i in (3, 4):
                continue
            angle = 2 * math.pi * i / 10
            pos = (round(cx + math.cos(angle) * 32), round(cy + math.sin(angle) * 32))
            pygame.draw.circle(screen, (178, 172, 160), pos, 7)
        rng = random.Random(f"tower:{self.x},{self.y}")
        for _ in range(5):
            ox, oy = rng.uniform(-70, 70), rng.uniform(-60, 60)
            if math.hypot(ox, oy) < 44:
                continue
            pygame.draw.circle(screen, (140, 136, 126), (round(cx + ox), round(cy + oy)), rng.randint(4, 9))

    def _draw_stones(self, screen, center):
        cx, cy = center
        count = 7
        for i in range(count):
            angle = 2 * math.pi * i / count
            px, py = cx + math.cos(angle) * 54, cy + math.sin(angle) * 38
            stone = pygame.Rect(0, 0, 16, 34)
            stone.center = (round(px), round(py))
            pygame.draw.rect(screen, (146, 142, 160), stone, border_radius=5)
            pygame.draw.rect(screen, (92, 90, 108), stone, 2, border_radius=5)
        # The ring breathes: enough to say something is still in these stones, no more.
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 900.0)
        glow = pygame.Surface((140, 110), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (170, 160, 220, round(30 * pulse)), glow.get_rect())
        screen.blit(glow, (cx - 70, cy - 55))

    def _draw_signpost(self, screen, center):
        cx, cy = center
        pygame.draw.line(screen, (96, 72, 46), (cx, cy + 26), (cx, cy - 30), 5)
        rng = random.Random(f"sign:{self.x},{self.y}")
        for i, side in enumerate((1, -1)):
            board = pygame.Rect(0, 0, 44, 14)
            board.center = (cx + side * 22, cy - 20 + i * 18)
            pygame.draw.rect(screen, (176, 142, 92), board, border_radius=2)
            pygame.draw.rect(screen, (104, 80, 48), board, 2, border_radius=2)
            # Weathered lettering, three worn strokes rather than readable words.
            for stroke in range(3):
                sx = board.left + 7 + stroke * 11
                pygame.draw.line(
                    screen, (104, 80, 48), (sx, board.centery - 2), (sx + rng.randint(3, 6), board.centery + 2), 1
                )

    def _draw_ruins(self, screen, center):
        size = c.PointsOfInterest.SIZE
        # Seeded from world position, stable across camera panning; fewer, smaller
        # stones once looted so a cleared ruin visibly reads as picked over.
        rng = random.Random(f"{self.x},{self.y}")
        count = 4 if self.looted else 6
        max_r = (6, 9) if self.looted else (8, 16)
        for _ in range(count):
            ox = rng.uniform(-size * 0.5, size * 0.5)
            oy = rng.uniform(-size * 0.3, size * 0.3)
            r = rng.randint(*max_r)
            pos = (round(center[0] + ox), round(center[1] + oy))
            pygame.draw.circle(screen, (140, 138, 130), pos, r)
            pygame.draw.circle(screen, (95, 93, 86), pos, r, 2)

    def _draw_camp(self, screen, center):
        cx, cy = center
        bandit = self.variant == "bandit"

        self._draw_tent(screen, (cx, cy), dark=bandit, collapsed=bandit and self.looted)
        if bandit:
            # A second tent and a planted banner: this one is somebody's holdout, not a
            # place to spend the night. Both go down with the camp.
            self._draw_tent(screen, (cx - 54, cy + 22), dark=True, scale=0.8, collapsed=self.looted)
            pole_top = (cx + 12, cy - 46) if not self.looted else (cx + 34, cy - 6)
            pygame.draw.line(screen, (70, 52, 34), (cx + 12, cy + 6), pole_top, 3)
            flag = [pole_top, (pole_top[0] + 28, pole_top[1] + 8), (pole_top[0], pole_top[1] + 18)]
            pygame.draw.polygon(screen, (120, 40, 40) if not self.looted else (80, 60, 55), flag)
        else:
            # A bedroll by the fire, and the pack the camper trades out of.
            roll = pygame.Rect(0, 0, 40, 16)
            roll.center = (cx - 46, cy + 22)
            pygame.draw.rect(screen, (170, 150, 110), roll, border_radius=7)
            pygame.draw.rect(screen, (105, 88, 62), roll, 2, border_radius=7)
            pack = pygame.Rect(0, 0, 20, 22)
            pack.center = (cx - 80, cy - 6)
            pygame.draw.rect(screen, (128, 92, 56), pack, border_radius=4)
            pygame.draw.rect(screen, (72, 52, 32), pack, 2, border_radius=4)

        self._draw_fire(screen, (cx + 40, cy + 12), lit=self.has_fire)

    @staticmethod
    def _draw_tent(screen, center, dark: bool, scale: float = 1.0, collapsed: bool = False):
        cx, cy = center
        tent_w, tent_h = round(46 * scale), round(34 * scale)
        if collapsed:
            # Cut down: the same cloth, flat on the ground.
            tent_h = round(tent_h * 0.35)
        cloth = (104, 88, 66) if dark else (150, 120, 80)
        tent = [(cx - tent_w // 2, cy + tent_h // 2), (cx, cy - tent_h // 2), (cx + tent_w // 2, cy + tent_h // 2)]
        pygame.draw.polygon(screen, cloth, tent)
        pygame.draw.polygon(screen, (95, 72, 45), tent, 2)
        flap = [(cx, cy - tent_h // 2), (cx, cy + tent_h // 2), (cx - round(8 * scale), cy + tent_h // 2)]
        pygame.draw.polygon(screen, tuple(round(v * 0.78) for v in cloth), flap)

    @staticmethod
    def _draw_fire(screen, pos, lit: bool):
        pygame.draw.circle(screen, (90, 60, 40), pos, 11)
        if not lit:
            pygame.draw.circle(screen, (70, 65, 60), pos, 6)
            return
        # Flame height flickers on the clock, so a live camp reads from across the screen.
        flicker = 1.0 + 0.25 * math.sin(pygame.time.get_ticks() / 130.0)
        pygame.draw.circle(screen, (230, 130, 40), pos, round(6 * flicker))
        pygame.draw.circle(screen, (250, 200, 80), pos, round(3 * flicker))

    def _draw_shrine(self, screen, center):
        cx, cy = center
        base = pygame.Rect(0, 0, 30, 12)
        base.center = (cx, cy + 20)
        pygame.draw.rect(screen, (150, 148, 140), base)
        pygame.draw.rect(screen, (105, 103, 96), base, 2)
        pillar = pygame.Rect(0, 0, 16, 40)
        pillar.center = (cx, cy - 4)
        pygame.draw.rect(screen, (170, 168, 158), pillar)
        pygame.draw.rect(screen, (110, 108, 100), pillar, 2)
        top = pygame.Rect(0, 0, 24, 10)
        top.center = (cx, cy - 26)
        pygame.draw.rect(screen, (190, 185, 140), top)
        pygame.draw.rect(screen, (110, 108, 100), top, 2)
        if not self.prayed:
            # A shrine still holding an answer glows faintly, so a spent one is told apart
            # from one worth walking to without reading a prompt.
            pulse = 0.6 + 0.4 * math.sin(pygame.time.get_ticks() / 500.0)
            glow = pygame.Surface((60, 60), pygame.SRCALPHA)
            pygame.draw.circle(glow, (230, 220, 150, round(45 * pulse)), (30, 30), 26)
            screen.blit(glow, (cx - 30, cy - 36))


# What draws each kind, named explicitly rather than off the kind's own name, so a search
# for `_draw_cave` finds both ends of it. Built once here rather than per draw call: this
# used to be a dict literal rebuilt for every landmark on screen, every frame. Anything not
# listed is a ruins pile.
_DRAWERS = {
    "camp": PointOfInterest._draw_camp,
    "shrine": PointOfInterest._draw_shrine,
    "farmstead": PointOfInterest._draw_farmstead,
    "graveyard": PointOfInterest._draw_graveyard,
    "watchtower": PointOfInterest._draw_watchtower,
    "stones": PointOfInterest._draw_stones,
    "signpost": PointOfInterest._draw_signpost,
    "cave": PointOfInterest._draw_cave,
}


@lru_cache(maxsize=2048)
def poi_site(cx: int, cy: int) -> tuple[float, float, str] | None:
    """Where this chunk's landmark stands and what kind it is, or None for a chunk that
    holds none. A pure function of the coordinates, so it can be asked about a chunk nobody
    has walked into: what the footpaths through the wilderness are drawn to, exactly as
    `village_site` is what the roads between settlements are drawn from.

    Everything that decides against a landmark is in here except the one test that needs
    the world as it stands, the buildings already generated nearby, which `pois_for_chunk`
    makes on top of this.
    """
    rng = random.Random(f"poi:{cx},{cy}")
    if rng.random() > c.PointsOfInterest.PER_CHUNK_CHANCE:
        return None

    size = c.World.CHUNK_SIZE
    margin = c.PointsOfInterest.CHUNK_MARGIN
    x = cx * size + rng.randint(margin, size - margin)
    y = cy * size + rng.randint(margin, size - margin)

    center = c.World.WORLD_SIZE // 2
    if math.hypot(x - center, y - center) < c.PointsOfInterest.MIN_DIST_FROM_CENTER:
        return None
    # Three chunks out rather than two: a walled town's grounds reach further than a
    # chunk, so a landmark two chunks away was cleared of a settlement it stood inside.
    for nx in range(cx - 3, cx + 4):
        for ny in range(cy - 3, cy + 4):
            site = village_site(nx, ny)
            if site is None:
                continue
            # Cleared by the settlement's real grounds, not by its centre point: a walled
            # town's wall, towers and ditch reach further than any fixed distance, which is
            # how a graveyard used to be laid out against somebody's gate.
            clear = max(c.Villages.MIN_DIST_FROM_POI, site_grounds_radius(nx, ny) + c.PointsOfInterest.VILLAGE_MARGIN)
            if math.hypot(x - site[0], y - site[1]) < clear:
                return None

    # Nothing is built in the water. The river's course is a pure function of the chunk
    # like everything else here, so it can be asked about before the landmark exists.
    river, _ = river_points_for_chunk(cx, cy)
    if any(math.hypot(x - wx, y - wy) < radius + c.PointsOfInterest.MIN_DIST_FROM_WATER for wx, wy, radius in river):
        return None

    kinds, weights = zip(*c.PointsOfInterest.KIND_WEIGHTS)
    return x, y, rng.choices(kinds, weights=weights)[0]


def pois_for_chunk(cx: int, cy: int, buildings: list[Building]) -> list[PointOfInterest]:
    """The points of interest belonging to one chunk, generated from its coordinates.

    Deterministic, so a chunk looks the same every time the player walks back into it, and
    endless, so there is always something to find however far out they go. At most one per
    chunk, placed away from the chunk's own edges, which keeps neighbouring landmarks apart
    without any cross-chunk lookups. Where it stands is `poi_site`; the one thing decided
    here is whether a building already generated is standing on the spot.
    """
    site = poi_site(cx, cy)
    if site is None:
        return []
    x, y, kind = site
    if any(
        b.covers(x, y, c.PointsOfInterest.MIN_DIST_FROM_BUILDING)
        or math.hypot(x - b.x, y - b.y) < max(b.w, b.h) / 2 + c.PointsOfInterest.MIN_DIST_FROM_BUILDING
        for b in buildings
    ):
        return []
    return [PointOfInterest(x, y, kind, poi_id=f"{cx}:{cy}")]


# Where a landmark may stand is decided from the village sites, so it is forgotten with
# them whenever a world registers a settlement the region grid never offered.
register_site_cache(poi_site.cache_clear)
