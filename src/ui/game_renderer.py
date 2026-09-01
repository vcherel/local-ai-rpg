from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

import core.constants as c
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.impact_fx import get_impacts
from core.particles import get_particles
from core.settings import get_settings
from core.swing_arcs import get_swings
from game.entities.item_icons import draw_shape_with_border
from game.entities.items import POTION_EFFECT_LABELS, rarity_color
from ui import widgets
from ui.loading_indicator import LoadingIndicator
from ui.minimap import Minimap

if TYPE_CHECKING:
    from core.camera import Camera
    from game.entities.player import Player
    from game.world import World


class GameRenderer:
    # Everything below sits inside one permanent panel in the top left corner:
    # a row of icon buttons, then coin/item/quest counters, then the two hands and the bomb,
    # then what is worn. Kept as small as it can be read at: the
    # panel is drawn over the world and over anything the screen edge is trying to point
    # at, so every slot here costs the player a piece of the view.
    HUD_PANEL_RECT = pygame.Rect(8, 8, 284, 176)
    HUD_ICON_SIZE = 34
    HUD_ICON_GAP = 6
    # Equip slots, up to four to a row. No captions under them: the ghost glyph says what an
    # empty slot takes, and the captions were what forced the row twice as wide as its icons.
    HUD_SLOT_SIZE = 34
    HUD_SLOT_STEP = 38

    # Potion quickbar, centred just above the player's health bar (drawn by Player.draw
    # at ORIGIN_Y + SIZE/2 + its health_bar_offset).
    # How long the corner save marker stays up, and how much of that is spent fading out.
    SAVE_MARKER_MS = 2200
    SAVE_MARKER_FADE_MS = 900

    QUICK_SLOT_SIZE = 52
    QUICK_SLOT_GAP = 8
    QUICK_BAR_BOTTOM = c.Screen.ORIGIN_Y + c.Player.SIZE // 2 + c.Player.HEALTH_BAR_OFFSET - 12

    def __init__(self, screen):
        self.screen: pygame.Surface = screen

        icon_y = self.HUD_PANEL_RECT.y + 10
        icon_x = self.HUD_PANEL_RECT.x + 10
        step = self.HUD_ICON_SIZE + self.HUD_ICON_GAP
        # (action, rect, icon glyph, tooltip label) for the icon dock row, in draw/hit-test
        # order. The action is what `Game.handle_input` looks the click up by, so a button
        # is one row here rather than a rect named in this file and an `elif` naming it again
        # over there.
        self.dock_buttons = tuple(
            (action, pygame.Rect(icon_x + step * i, icon_y, self.HUD_ICON_SIZE, self.HUD_ICON_SIZE), icon, tooltip)
            for i, (action, icon, tooltip) in enumerate(
                (
                    ("inventory", "bag", "Inventory (I)"),
                    ("quests", "scroll", "Quests (J)"),
                    ("stats", "person", "Character (C)"),
                    ("lore", "book", "Lore (L)"),
                    ("help", "question", "Help (H)"),
                    ("pause", "pause", "Pause (P)"),
                )
            )
        )
        self.dock_bottom = icon_y + self.HUD_ICON_SIZE

        # Reused by `_draw_witness_cones` rather than reallocated per frame.
        self._cone_overlay: pygame.Surface | None = None
        # V, off by default: the cones normally come up only over something worth stealing,
        # and this holds them up everywhere so the player can read a street before walking
        # into it. It never takes a cone away, so the theft warning is untouched. A
        # preference rather than a playthrough, so it outlives New game like the volume does.
        self.always_show_cones = bool(get_settings().get("cones"))

        self.minimap = Minimap(self.screen)
        # Left of the minimap, which owns the top right corner now.
        self.loading_indicator = LoadingIndicator(self.screen, self.minimap.rect.left - 30, 30)
        # Toggled by clicking the loading indicator; lists the LLM's in-flight tasks.
        self.show_llm_tasks = False

    @staticmethod
    def _on_screen(camera: Camera, x, y, margin=60):
        return abs(x - camera.x) <= c.Screen.ORIGIN_X + margin and abs(y - camera.y) <= c.Screen.ORIGIN_Y + margin

    @staticmethod
    def _hidden_indoors(world: World, x, y, interior) -> bool:
        """True when (x, y) stands on a building's floor that isn't the one the player is in.
        That building still has its roof on, so whatever is inside it must not be drawn over
        the top of it."""
        building = world.building_at(x, y)
        return building is not None and building is not interior

    def draw_world(self, camera: Camera, world: World, player: Player, interior=None, interaction=None):
        """`interior` is the building (if any) the player is currently standing inside; that
        one building draws as a roofless cutaway instead of its normal solid block, while
        everything else, indoors or out, keeps drawing in this same pass around it.
        `interaction` is what the interact key would act on right now (Game.current_interaction),
        drawn as the one prompt on screen. The quest arrow is not drawn here: it goes over the
        HUD, so `draw_ui` puts it up last of everything."""
        # Underground the ground is the tunnel and there is nothing else: no sky, no
        # wilderness, no buildings, because none of it is generated where a tunnel is dug.
        # Everything that walks, flies or lies on the floor keeps drawing below exactly as
        # it does on the surface, which is the whole point of a tunnel being world space.
        if world.underground is not None:
            world.underground.draw(self.screen, camera)
            get_decals().draw(self.screen, camera)
            self._draw_entities(camera, world, player, interior, interaction, underground=True)
            return

        self.screen.fill(c.Colors.GREEN)

        # How dark the sky is, asked once for the frame: the wall braziers and the lit
        # windows of a village are the only things out here drawn differently after dark.
        darkness = world.daynight.darkness

        # The one loop long enough for the culling itself to cost something: a few hundred
        # pebbles per chunk, so it asks the world for the chunks it can see rather than
        # walking every one the player has loaded, and measures each against the view here
        # rather than through a call per pebble.
        ox, oy = camera.world_to_screen(0, 0)
        details = c.World.FLOOR_DETAILS
        for x, y, kind in world.floor_details_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + 5):
            sx, sy = x + ox, y + oy
            if not (-5 <= sx <= c.Screen.WIDTH + 5 and -5 <= sy <= c.Screen.HEIGHT + 5):
                continue
            color, radius = details[kind]
            pygame.draw.circle(self.screen, color, (sx, sy), radius)

        # Roads, ponds, grass and flowers: the ground itself, so they go under everything
        # standing on it (the props they came with are drawn further down, with the barrels).
        ground_margin = max(c.Scenery.POND_RADIUS[1], c.Scenery.PATCH_RADIUS[1])
        for item in world.scenery_ground_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + ground_margin):
            if self._on_screen(camera, item.x, item.y, margin=ground_margin):
                item.draw(self.screen, camera)

        # The plaza a village is built around, drawn under its buildings.
        for village in world.villages:
            # A walled town is drawn from a long way outside its plaza: the palisade stands
            # at the edge of the settlement, not at the middle of it.
            # Its grounds either way: the streets between the houses belong to the village
            # and reach every door, so a hamlet culled on its plaza alone lost its lanes.
            reach = village.grounds_radius + 40
            if self._on_screen(camera, village.x, village.y, margin=reach):
                village.draw(self.screen, camera, darkness)

        for building in world.buildings_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + 500):
            if self._on_screen(camera, building.x, building.y, margin=max(building.w, building.h)):
                building.draw(self.screen, camera, player_inside=building is interior, darkness=darkness)

        # Filtered exactly as the entities and the items below are: a splat left on another
        # building's floor is under a roof that is still on, and used to show through it.
        get_decals().draw(self.screen, camera, hidden=lambda x, y: self._hidden_indoors(world, x, y, interior))

        # Up whenever the player is standing in somebody else's room, not only over a chest:
        # taking the furniture apart is watched exactly like emptying the chest is, and the
        # rule is only fair if the eyes are on screen before the swing.
        if (
            self.always_show_cones
            or interior is not None
            or (interaction is not None and interaction.kind in ("chest", "bed"))
        ):
            self._draw_witness_cones(camera, world, player)

        # Lying on the ground and under everything that walks over it: a trap is meant to be
        # caught sight of, not read off the top of whoever is about to step in it.
        for trap in world.traps:
            if self._on_screen(camera, trap.x, trap.y):
                trap.draw(self.screen, camera)

        for breakable in world.breakables:
            if self._on_screen(camera, breakable.x, breakable.y):
                breakable.draw(self.screen, camera)

        # A canopy is overhead, so it belongs in front of whatever stands under it: it is
        # held back here and drawn after the entities, faded where anything is beneath it.
        canopies = []
        for item in world.scenery_props_in_range(camera.x, camera.y, c.Screen.ORIGIN_X + 100):
            if not self._on_screen(camera, item.x, item.y, margin=70):
                continue
            if item.kind in c.Scenery.CANOPY_KINDS and not item.felled:
                canopies.append(item)
            else:
                item.draw(self.screen, camera)

        for poi in world.pois:
            if self._on_screen(camera, poi.x, poi.y):
                poi.draw(self.screen, camera)

        self._draw_entities(
            camera,
            world,
            player,
            interior,
            interaction,
            overlay=lambda: self._draw_canopies(camera, world, player, canopies),
        )

    def _draw_canopies(self, camera: Camera, world: World, player: Player, canopies):
        """The leaves, drawn over everything standing on the ground and faded out wherever
        something is standing under them.

        A tree that simply draws under the bodies never reads as a tree at all, since a
        player walking through a wood is painted on top of every canopy; one that draws over
        them swallows whatever it covers. Both are answered the same way: the canopy goes in
        front and turns see-through the moment anything is beneath it."""
        if not canopies:
            return
        bodies = [(player.x, player.y)]
        for group in (world.npcs, world.monsters, world.bosses, world.critters):
            bodies.extend((body.x, body.y) for body in group if self._on_screen(camera, body.x, body.y))
        # Loot counts as something under the tree: a drop nobody can see is a drop nobody
        # walks over, and the magnet only reaches what the player has come close to.
        bodies.extend(
            (item.x, item.y) for item in world.items if not item.picked_up and self._on_screen(camera, item.x, item.y)
        )
        for canopy in canopies:
            shaded = any(canopy.shades(x, y) for x, y in bodies)
            canopy.draw(self.screen, camera, alpha=c.Scenery.CANOPY_FADE_ALPHA if shaded else 255)

    def _draw_entities(
        self,
        camera: Camera,
        world: World,
        player: Player,
        interior,
        interaction,
        underground=False,
        overlay=None,
    ):
        """Everything standing on whatever was drawn under it: the same pass indoors, outdoors
        and underground, since all three are the one world and the one set of entity lists.

        `overlay` is whatever belongs over the bodies but under the HUD (the canopies), drawn
        here rather than after the call so a prompt or an arrow is never buried by leaves."""

        def visible(x, y, margin=60) -> bool:
            return self._on_screen(camera, x, y, margin) and not self._hidden_indoors(world, x, y, interior)

        # Under everything alive: a boss's summons opens the ground before anything stands
        # up out of it, so the mark belongs with the shadows rather than over the bodies.
        for boss in world.bosses:
            boss.draw_summon_marks(self.screen, camera)

        # A laid mine lies on the ground like a trap does, for the same reason: it is meant
        # to be caught sight of, not read off the top of whoever is about to step on it. A
        # grenade still in the air is drawn here too, and a tunnel has both like anywhere else.
        for bomb in world.bombs:
            if self._on_screen(camera, bomb.x, bomb.y):
                bomb.draw(self.screen, camera)

        for critter in world.critters:
            if visible(critter.x, critter.y):
                critter.draw(self.screen, camera)

        for npc in world.npcs:
            if visible(npc.x, npc.y):
                npc.draw(self.screen, camera)

        for monster in world.monsters:
            if visible(monster.x, monster.y):
                monster.draw(self.screen, camera)

        for boss in world.bosses:
            if visible(boss.x, boss.y, margin=boss.kind.size + c.Boss.SLAM_RADIUS):
                boss.draw(self.screen, camera)

        for item in (i for i in world.items if not i.picked_up):
            if visible(item.x, item.y):
                item.draw(self.screen, camera)

        for projectile in world.projectiles:
            projectile.draw(self.screen, camera)

        # Under the particles and over the entities: the arc says how much ground the
        # swing covered, the particles say what it landed on.
        get_swings().draw(self.screen, camera)
        get_impacts().draw(self.screen, camera)
        get_particles().draw(self.screen, camera)
        get_floating_text().draw(self.screen, camera)

        # Over everything alive and under the player: what is out past the lantern is not
        # seen at all, which is the tunnel's real difficulty and the reason to go back up.
        # The player themselves is drawn on top of it, and their bar later still, because
        # the HUD is not something the dark or the leaves may swallow.
        if underground:
            world.underground.draw_dark(self.screen, camera, player)

        player.draw(self.screen)

        if overlay is not None:
            overlay()

        # Over the canopies: the player's health bar, the points on it and the struggle bar
        # are HUD that happens to be drawn in the world, and leaves may not sit on top of
        # them. Everything else about the player is a body and stays under the branches.
        player.draw_health_bar_overlay(self.screen)
        self._draw_struggle_bar(player)

        if interaction is not None:
            self._draw_interaction_prompt(camera, interaction)
        self.draw_boss_bar(world, player)

    def _draw_struggle_bar(self, player: Player):
        """What is left of a bear trap's hold, over the player's head.

        Drawn only while the jaws are on them, and only because escaping is something they
        do: every movement key pressed takes a bite out of this bar (`Game._struggle`), and
        without it the effort would be a body that has stopped answering the keys for a
        while. Not a prompt, so it never competes with the one on-screen interaction."""
        if not player.rooted:
            return
        width, height = 90, 9
        x = c.Screen.ORIGIN_X - width // 2
        y = c.Screen.ORIGIN_Y - c.Player.SIZE - 34
        pygame.draw.rect(self.screen, (24, 22, 20), (x - 2, y - 2, width + 4, height + 4), border_radius=3)
        pygame.draw.rect(self.screen, c.Traps.PLATE_COLOR, (x, y, width, height))
        pygame.draw.rect(self.screen, c.Traps.JAW_COLOR, (x, y, round(width * player.root_progress), height))
        label = c.Fonts.small.render("Caught!", True, c.Colors.WHITE)
        self.screen.blit(label, label.get_rect(center=(c.Screen.ORIGIN_X, y - 12)))
        # What to actually do about it. A bar draining on its own says "wait"; the keys say
        # the seconds are the player's to take back, which is the whole of how a trap works.
        self._draw_struggle_keys(y + height + 8)

    def _draw_struggle_keys(self, top: int):
        """The keys to mash, drawn as chips under the struggle bar and pulsing so they read
        as an instruction rather than as a readout."""
        keys = ("W", "S", "Space")
        pulse = 0.6 + 0.4 * math.sin(pygame.time.get_ticks() / 110.0)
        chips = [c.Fonts.small.render(key, True, c.Colors.WHITE) for key in keys]
        tail = c.Fonts.small.render("to break free", True, c.Colors.WHITE)
        gap, pad = 5, 5
        total = sum(chip.get_width() + pad * 2 for chip in chips) + gap * len(chips) + tail.get_width()
        x = c.Screen.ORIGIN_X - total // 2
        for chip in chips:
            rect = pygame.Rect(x, top, chip.get_width() + pad * 2, chip.get_height() + 2)
            pygame.draw.rect(self.screen, (40, 36, 32), rect, border_radius=3)
            pygame.draw.rect(self.screen, tuple(round(v * pulse) for v in c.Traps.JAW_COLOR), rect, 1, border_radius=3)
            self.screen.blit(chip, (rect.x + pad, rect.y + 1))
            x = rect.right + gap
        self.screen.blit(tail, (x, top + 1))

    def _draw_lift_bar(self, progress: float):
        """How far the beam across a barred gate has come up, over the player's head.

        The same bar a bear trap's hold is drawn as, for the same reason: the effort is
        something the player is doing rather than something being done to them, and without
        it a held key is a body that has stopped answering. Nothing is drawn until they have
        actually started, so a gate they are only standing at is only a prompt."""
        if progress <= 0:
            return
        width, height = 90, 9
        x = c.Screen.ORIGIN_X - width // 2
        y = c.Screen.ORIGIN_Y - c.Player.SIZE - 34
        pygame.draw.rect(self.screen, (24, 22, 20), (x - 2, y - 2, width + 4, height + 4), border_radius=3)
        pygame.draw.rect(self.screen, (58, 52, 44), (x, y, width, height))
        pygame.draw.rect(self.screen, c.Villages.GATE_LEAF, (x, y, round(width * min(1.0, progress)), height))
        label = c.Fonts.small.render("Lifting the bar...", True, c.Colors.WHITE)
        self.screen.blit(label, label.get_rect(center=(c.Screen.ORIGIN_X, y - 12)))

    def _draw_witness_cones(self, camera: Camera, world: World, player: Player):
        """What every villager who could catch the player stealing can actually see, drawn on
        the ground while a chest or a bed is in reach.

        Only up while the player is stood over something that isn't theirs: the cone is the
        question "is anyone looking right now", and a street permanently full of wedges would
        be wallpaper. `always_show_cones` (V) is the player asking for that wallpaper anyway,
        which is a choice they make rather than the state the game hands them.

        One rule, and the colour follows the wedge: white is somebody watching, red is the
        player standing in what they are watching. Which is only readable because a villager
        the walls have already answered (`World.sight_reaches`: another building, or round the
        back of this one) is not drawn at all. A cone lying across the player used to stay
        pale for exactly that reason, and a wedge that says nothing about whether you are
        caught is worse than no wedge."""
        radius = world.witness_radius()
        room = world.theft_room(player.x, player.y)
        watchers = [npc for npc in world.watchers_near(player.x, player.y) if world.sight_reaches(npc, room)]
        if not watchers:
            return

        if self._cone_overlay is None:
            # One surface for the life of the renderer: a fresh screen-sized alpha surface
            # per frame is an allocation the size of the window, every frame, for a wedge.
            self._cone_overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay = self._cone_overlay
        overlay.fill((0, 0, 0, 0))
        for npc in watchers:
            # A villager whose whole cone is off screen is not worth casting: the cones are
            # drawn to be read, and the check that matters has already been made elsewhere.
            if not self._on_screen(camera, npc.x, npc.y, margin=radius):
                continue
            points = [camera.world_to_screen(x, y) for x, y in world.vision_polygon(npc, radius)]
            # The walls are already answered by which villagers are on this list, so what is
            # left is exactly the wedge the player can see on the ground.
            seen = npc.sees(player.x, player.y, radius)
            # Kept faint: several of these overlap on a busy street, and they are drawn on
            # the ground the player is trying to read, not over it.
            pygame.draw.polygon(overlay, (200, 70, 60, 38) if seen else (230, 225, 200, 16), points)
            pygame.draw.lines(overlay, (200, 70, 60, 90) if seen else (230, 225, 200, 40), True, points, 1)
        self.screen.blit(overlay, (0, 0))

    def _draw_interaction_prompt(self, camera: Camera, interaction):
        """The one prompt on screen, floating over whatever the interact key would act on.
        A merchant also gets its trade key on a second line underneath."""
        x, y = camera.world_to_screen(interaction.x, interaction.y)
        y -= 30
        bob = math.sin(pygame.time.get_ticks() / 260.0) * 3

        lines = [c.Fonts.small.render(interaction.label, True, c.Colors.WHITE)]
        if interaction.hint:
            lines.append(c.Fonts.small.render(interaction.hint, True, c.Colors.ACCENT))

        width = max(surface.get_width() for surface in lines) + 16
        height = sum(surface.get_height() for surface in lines) + 6 * len(lines)
        box = pygame.Rect(0, 0, width, height)
        box.midbottom = (round(x), round(y + bob))
        widgets.draw_panel(self.screen, box)

        line_y = box.y + 3
        for surface in lines:
            self.screen.blit(surface, (box.centerx - surface.get_width() // 2, line_y))
            line_y += surface.get_height() + 6

    def _draw_icon(self, kind: str, center: tuple, size: int, color: tuple):
        """A small flat glyph for a HUD icon button. `size` is roughly the icon's radius."""
        cx, cy = center
        r = size
        if kind == "bag":
            top_w, bot_w = r * 0.9, r * 1.3
            top_y, bot_y = cy - r * 0.3, cy + r * 0.9
            pygame.draw.polygon(
                self.screen,
                color,
                [(cx - top_w / 2, top_y), (cx + top_w / 2, top_y), (cx + bot_w / 2, bot_y), (cx - bot_w / 2, bot_y)],
                2,
            )
            pygame.draw.arc(self.screen, color, pygame.Rect(cx - r * 0.4, cy - r * 1.3, r * 0.8, r * 1.0), 3.4, 6.0, 2)
        elif kind == "scroll":
            rect = pygame.Rect(cx - r * 0.7, cy - r * 0.9, r * 1.4, r * 1.8)
            pygame.draw.rect(self.screen, color, rect, 2, border_radius=3)
            for i in range(3):
                ly = rect.top + rect.height * 0.32 + i * rect.height * 0.22
                pygame.draw.line(self.screen, color, (rect.left + 4, ly), (rect.right - 4, ly), 1)
        elif kind == "person":
            pygame.draw.circle(self.screen, color, (cx, cy - r * 0.5), r * 0.4, 2)
            pygame.draw.arc(
                self.screen, color, pygame.Rect(cx - r * 0.7, cy - r * 0.1, r * 1.4, r * 1.3), 3.14, 6.28, 2
            )
        elif kind == "book":
            rect = pygame.Rect(cx - r * 0.9, cy - r * 0.7, r * 1.8, r * 1.4)
            pygame.draw.rect(self.screen, color, rect, 2)
            pygame.draw.line(self.screen, color, (cx, rect.top), (cx, rect.bottom), 2)
        elif kind == "question":
            label = c.Fonts.button.render("?", True, color)
            self.screen.blit(label, label.get_rect(center=center))
        elif kind == "pause":
            bar_w, gap, h = max(2, int(r * 0.35)), r * 0.4, r * 1.4
            pygame.draw.rect(self.screen, color, pygame.Rect(cx - gap - bar_w, cy - h / 2, bar_w, h))
            pygame.draw.rect(self.screen, color, pygame.Rect(cx + gap, cy - h / 2, bar_w, h))
        elif kind == "coin":
            pygame.draw.circle(self.screen, color, center, r * 0.9, 2)
            label = c.Fonts.small.render("$", True, color)
            self.screen.blit(label, label.get_rect(center=center))

    def _draw_dock_button(self, rect: pygame.Rect, icon: str, mouse_pos) -> bool:
        """Draw one dock icon. Returns whether it's hovered, so the caller can draw its
        tooltip last: it hangs below the row, over the stat chips drawn after the loop."""
        hover = rect.collidepoint(mouse_pos)
        widgets.draw_button(self.screen, rect, "", c.Fonts.button, hovered=hover)
        self._draw_icon(icon, rect.center, rect.width * 0.32, c.Colors.WHITE)
        return hover

    def _draw_tooltip(self, anchor: pygame.Rect, text: str):
        label = c.Fonts.small.render(text, True, c.Colors.WHITE)
        pad = 6
        box = pygame.Rect(anchor.left, anchor.bottom + 4, label.get_width() + pad * 2, label.get_height() + pad * 2)
        widgets.draw_panel(self.screen, box)
        self.screen.blit(label, (box.x + pad, box.y + pad))

    def _draw_stat_chip(self, x: int, y: int, icon: str, value: int) -> int:
        """Draw an icon + number pair at (x, y), returning the x position right after it."""
        icon_size = 9
        self._draw_icon(icon, (x + icon_size, y + icon_size), icon_size, c.Colors.MUTED)
        label = c.Fonts.text.render(str(value), True, c.Colors.WHITE)
        text_x = x + icon_size * 2 + 6
        self.screen.blit(label, (text_x, y + icon_size - label.get_height() // 2))
        return text_x + label.get_width() + 22

    def draw_ui(
        self,
        nb_items,
        nb_coins,
        nb_quests,
        llm_tasks,
        player: Player,
        world: World,
        camera: Camera,
        saved_ms: int = 0,
        gate_lift: float = 0.0,
        quest_target=None,
    ):
        active_task_count = len(llm_tasks)
        mouse_pos = pygame.mouse.get_pos()

        self.minimap.draw(world, player)

        widgets.draw_panel(self.screen, self.HUD_PANEL_RECT)
        hovered_dock = None
        for _action, rect, icon, tooltip in self.dock_buttons:
            if self._draw_dock_button(rect, icon, mouse_pos):
                hovered_dock = (rect, tooltip)

        stats_y = self.dock_bottom + 10
        x = self.HUD_PANEL_RECT.x + 10
        x = self._draw_stat_chip(x, stats_y, "coin", nb_coins)
        x = self._draw_stat_chip(x, stats_y, "bag", nb_items)
        self._draw_stat_chip(x, stats_y, "scroll", nb_quests)

        self._draw_equipped(player, top=stats_y + 28)
        self._draw_potion_bar(player)
        self._draw_mana_bar(player)
        self._draw_guard_bar(player)

        # Last, so the panel's own contents can't cover it.
        if hovered_dock is not None:
            self._draw_tooltip(*hovered_dock)

        self._draw_save_marker(saved_ms)
        self._draw_lift_bar(gate_lift)

        self.loading_indicator.update()
        if active_task_count > 0:
            self.loading_indicator.draw_task_indicator(active_task_count)
        else:
            # Nothing running: the icon is gone, so there's nothing left to reopen from.
            self.show_llm_tasks = False

        if self.show_llm_tasks:
            self._draw_llm_task_panel(llm_tasks)

        # Last of everything: the arrow to the tracked quest is the one thing on screen that
        # is useless where it cannot be seen, so nothing on the HUD is allowed over it.
        self.draw_offscreen_indicators(camera, quest_target, (self.HUD_PANEL_RECT,))

    def _quick_slot_rects(self) -> list[pygame.Rect]:
        step = self.QUICK_SLOT_SIZE + self.QUICK_SLOT_GAP
        count = c.Potions.QUICK_SLOTS
        total = count * self.QUICK_SLOT_SIZE + (count - 1) * self.QUICK_SLOT_GAP
        left = c.Screen.ORIGIN_X - total // 2
        top = self.QUICK_BAR_BOTTOM - self.QUICK_SLOT_SIZE
        return [pygame.Rect(left + i * step, top, self.QUICK_SLOT_SIZE, self.QUICK_SLOT_SIZE) for i in range(count)]

    def _draw_potion_bar(self, player: Player):
        """The potion quickbar above the health bar: one slot per quick key, with the
        live buff chips floating just over it."""
        potions = player.quick_potions()
        rects = self._quick_slot_rects()

        for i, rect in enumerate(rects):
            item = potions[i] if i < len(potions) else None
            border = rarity_color(item.rarity) if item else c.Colors.SLOT_BORDER
            widgets.draw_slot(self.screen, rect, border_color=border)

            if item is not None:
                widgets.draw_item_scaled(self.screen, item, rect.centerx + 2, rect.centery - 3, 32)
                if item.quantity > 1:
                    count = c.Fonts.small.render(f"x{item.quantity}", True, c.Colors.WHITE)
                    self.screen.blit(count, (rect.right - count.get_width() - 4, rect.bottom - count.get_height() - 2))
            else:
                draw_shape_with_border(self.screen, "flask", rect.center, 14, (60, 60, 70), 2, (84, 84, 98))

            key_label = c.Fonts.small.render(c.Potions.QUICK_KEYS[i].upper(), True, c.Colors.MUTED)
            self.screen.blit(key_label, (rect.x + 4, rect.y + 2))

        self._draw_buff_chips(player, bottom=rects[0].top - 6)

    def _draw_save_marker(self, saved_ms: int):
        """A small disc and the word "Saved" in the bottom right corner, fading out over a
        couple of seconds after every save. The game saves itself on a clock and at the
        moments worth not replaying; without this, none of that is visible to the player."""
        left = self.SAVE_MARKER_MS - (pygame.time.get_ticks() - saved_ms)
        if left <= 0:
            return
        alpha = int(255 * min(1.0, left / self.SAVE_MARKER_FADE_MS))

        label = c.Fonts.small.render("Saved", True, c.Colors.MUTED)
        label.set_alpha(alpha)
        x = c.Screen.WIDTH - 16 - label.get_width()
        y = c.Screen.HEIGHT - 16 - label.get_height()
        self.screen.blit(label, (x, y))

        disc = pygame.Surface((12, 12), pygame.SRCALPHA)
        pygame.draw.circle(disc, (*c.Colors.ACCENT, alpha), (6, 6), 5)
        self.screen.blit(disc, (x - 18, y + label.get_height() // 2 - 6))

    # The player's health bar is drawn by the entity itself (Player.draw, under the body at
    # `Player.HEALTH_BAR_OFFSET`); the mana bar hangs directly under it and the guard bar
    # under that, so the whole stack follows the one offset.
    MANA_BAR_HEIGHT = 14

    def _mana_bar_bottom(self) -> int:
        health_bottom = c.Screen.ORIGIN_Y + c.Player.SIZE // 2 + c.Player.HEALTH_BAR_OFFSET + c.Player.HEALTH_BAR_HEIGHT
        return health_bottom + 4 + self.MANA_BAR_HEIGHT

    def _draw_mana_bar(self, player: Player):
        """The mana pool, drawn as a second bar under the health bar and always shown.

        Magic costs something now, and what it costs has to be as readable as health: a bolt
        that does not come out because the pool is empty must be something the player saw
        coming. It dims while the pool is held short of regenerating, so the pause after a
        volley is visible too."""
        width = 800
        rect = pygame.Rect(0, 0, width, self.MANA_BAR_HEIGHT)
        rect.bottomleft = (c.Screen.ORIGIN_X - width // 2, self._mana_bar_bottom())

        holding = pygame.time.get_ticks() - player.last_cast_ms < c.Magic.REGEN_DELAY_MS
        fill = c.Magic.EMPTY_COLOR if holding else c.Magic.BAR_COLOR
        ratio = max(0.0, min(1.0, player.mana / max(1, player.max_mana)))
        pygame.draw.rect(self.screen, c.Colors.MENU_BACKGROUND, rect)
        pygame.draw.rect(self.screen, fill, (rect.x, rect.y, round(rect.width * ratio), rect.height))
        pygame.draw.rect(self.screen, c.Colors.BORDER, rect, 3)

        label = c.Fonts.small.render(f"{int(player.mana)}/{player.max_mana}", True, c.Colors.WHITE)
        self.screen.blit(label, (rect.right - label.get_width() - 6, rect.centery - label.get_height() // 2))

    def _draw_guard_bar(self, player: Player):
        """The shield's guard, drawn just under the health bar and only while a shield is
        carried. It brightens while the block is up and turns red once the guard breaks,
        so the player can see what holding block is costing them."""
        if not player.has_shield():
            return
        width, height = 400, 10
        rect = pygame.Rect(0, 0, width, height)
        rect.midtop = (c.Screen.ORIGIN_X, self._mana_bar_bottom() + 6)

        broken = player.guard_broken()
        fill = (200, 70, 60) if broken else ((150, 210, 255) if player.blocking else (90, 130, 175))
        pygame.draw.rect(self.screen, c.Colors.SLOT_BG, rect)
        ratio = max(0.0, player.guard / c.Shield.GUARD_MAX)
        pygame.draw.rect(self.screen, fill, (rect.x, rect.y, round(rect.width * ratio), rect.height))
        pygame.draw.rect(self.screen, c.Colors.SLOT_BORDER, rect, 2)

        if broken:
            label = c.Fonts.small.render("Guard broken", True, (255, 150, 140))
            self.screen.blit(label, (rect.centerx - label.get_width() // 2, rect.bottom + 2))

    def _draw_buff_chips(self, player: Player, bottom: int):
        # (dot colour, rendered label) per chip: the potion buffs, then the post-death
        # weakness, which is a timed effect like the rest and shouldn't be invisible or
        # unexplained.
        chips = []
        for effect, remaining, _magnitude in player.active_buffs():
            text = f"{POTION_EFFECT_LABELS.get(effect, effect)} {int(remaining) + 1}s"
            # Not every buff comes out of a flask: a weapon affix (bloodlust) has no
            # liquid colour of its own, and used to crash the HUD looking for one.
            color = c.Potions.COLORS.get(effect, c.Colors.RED)
            chips.append((color, c.Fonts.small.render(text, True, c.Colors.WHITE)))

        weakened = player.weakness_remaining()
        if weakened > 0:
            # Just the state and how long is left: what it costs is spelled out on the death
            # screen, and three penalties do not fit in a chip.
            text = f"Weakened {int(weakened) + 1}s"
            chips.append((c.Colors.RED, c.Fonts.small.render(text, True, c.Colors.WHITE)))

        if not chips:
            return

        pad = 8
        gap = 6
        dot_space = 16
        widths = [label.get_width() + pad * 2 + dot_space for _, label in chips]
        height = chips[0][1].get_height() + 8
        x = c.Screen.ORIGIN_X - (sum(widths) + gap * (len(widths) - 1)) // 2
        y = bottom - height

        for (color, label), width in zip(chips, widths, strict=True):
            rect = pygame.Rect(x, y, width, height)
            widgets.draw_panel(self.screen, rect)
            pygame.draw.circle(self.screen, color, (rect.x + pad + 4, rect.centery), 5)
            self.screen.blit(label, (rect.x + pad + dot_space, rect.centery - label.get_height() // 2))
            x += width + gap

    def _draw_equipped(self, player: Player, top: int) -> int:
        """The HUD paper-doll, in two rows: what a button or a key spends (the two hands and
        the bomb), then what is worn.

        Each of the three carries the button or key that uses it, so the strip says what to
        press as well as what is held. The ammo slot carries the count of the quiver the
        next shot would spend, in red once it is empty. Returns the y it ends at, so what
        comes under it doesn't have to guess."""
        slot = self.HUD_SLOT_SIZE
        left = self.HUD_PANEL_RECT.x + 10
        rows = (
            [entry for entry in widgets.EQUIP_SLOTS if entry[0] in widgets.ACTION_SLOTS],
            [entry for entry in widgets.EQUIP_SLOTS if entry[0] not in widgets.ACTION_SLOTS],
        )

        y = top
        for row in rows:
            for i, (slot_name, _caption, glyph) in enumerate(row):
                item = player.equipped_item(slot_name)
                if slot_name == "ammo" and item is None:
                    # Nothing loaded still fires the cheapest quiver carried, so that is what
                    # the slot shows rather than an empty socket over a full bag of arrows.
                    item = player.ready_ammo()
                rect = pygame.Rect(left + i * self.HUD_SLOT_STEP, y, slot, slot)

                border = rarity_color(item.rarity) if item else c.Colors.SLOT_BORDER
                widgets.draw_slot(self.screen, rect, border_color=border)
                if item is not None:
                    widgets.draw_item_scaled(self.screen, item, rect.centerx, rect.centery, 26)
                else:
                    draw_shape_with_border(self.screen, glyph, rect.center, 12, (60, 60, 70), 2, (84, 84, 98))

                key = widgets.SLOT_KEYS.get(slot_name)
                if key is not None:
                    label = c.Fonts.small.render(key, True, c.Colors.ACCENT)
                    self.screen.blit(label, (rect.x + 4, rect.y + 2))

                if slot_name == "ammo":
                    left_over = player.ammo_count()
                    label = c.Fonts.small.render(str(left_over), True, c.Colors.WHITE if left_over else c.Colors.RED)
                    self.screen.blit(label, (rect.right - label.get_width() - 2, rect.bottom - label.get_height()))
                elif item is not None and item.quantity > 1:
                    count = c.Fonts.small.render(str(item.quantity), True, c.Colors.WHITE)
                    self.screen.blit(count, (rect.right - count.get_width() - 2, rect.bottom - count.get_height()))
            y += slot + 4
        return y - 4

    def _draw_llm_task_panel(self, llm_tasks):
        width = 240
        pad = 10
        row_h = 34
        header_h = 26
        height = header_h + pad + max(len(llm_tasks), 1) * row_h + pad
        right = c.Screen.WIDTH - 10
        top = self.loading_indicator.rect.bottom + 6
        panel = pygame.Rect(right - width, top, width, height)
        widgets.draw_panel(self.screen, panel)

        title = c.Fonts.button.render(f"LLM tasks ({len(llm_tasks)})", True, c.Colors.ACCENT)
        self.screen.blit(title, (panel.x + pad, panel.y + pad))

        y = panel.y + pad + header_h
        for task in llm_tasks:
            running = task["state"] == "running"
            bullet = "●" if running else "○"
            color = c.Colors.WHITE if running else c.Colors.BORDER
            label = c.Fonts.small.render(f"{bullet} {task['category']}", True, color)
            self.screen.blit(label, (panel.x + pad, y))

            status = f"running  {task['elapsed']:.1f}s" if running else "queued"
            status_surface = c.Fonts.small.render(status, True, c.Colors.BORDER)
            self.screen.blit(status_surface, (panel.x + pad + 16, y + 15))
            y += row_h

    def draw_boss_bar(self, world: World, player: Player):
        """A wide health bar pinned near the top of the screen for the nearest engaged boss."""
        active = [b for b in world.bosses if b.distance_to_point((player.x, player.y)) <= c.Boss.AGGRO_RANGE]
        if not active:
            return
        boss = min(active, key=lambda b: b.distance_to_point((player.x, player.y)))

        width, height = c.Boss.BAR_WIDTH, c.Boss.BAR_HEIGHT
        x = (c.Screen.WIDTH - width) // 2
        y = c.Boss.BAR_TOP
        fill_color = c.Colors.BOSS_BAR_ENRAGED if boss.enraged else c.Colors.BOSS_BAR
        ratio = max(boss.hp / boss.max_hp, 0)

        pygame.draw.rect(self.screen, c.Colors.MENU_BACKGROUND, (x - 3, y - 3, width + 6, height + 6))
        pygame.draw.rect(self.screen, (20, 20, 24), (x, y, width, height))
        pygame.draw.rect(self.screen, fill_color, (x, y, int(width * ratio), height))
        pygame.draw.rect(self.screen, c.Colors.BORDER, (x, y, width, height), 2)

        label = boss.display_name + ("  [ENRAGED]" if boss.enraged else "")
        name_surface = c.Fonts.button.render(label, True, c.Colors.WHITE)
        self.screen.blit(name_surface, ((c.Screen.WIDTH - name_surface.get_width()) // 2, y - 26))

    @staticmethod
    def _slide_clear(x: float, y: float, blocked: pygame.Rect) -> tuple[float, float]:
        """Push a point out of a rect by whichever of the four ways out is the shortest move.

        What keeps the arrow as close as it can be to the direction it is actually pointing:
        it is nudged aside by the panel covering it rather than sent to a corner."""
        if not blocked.collidepoint(x, y):
            return x, y
        moves = ((blocked.left, y), (blocked.right, y), (x, blocked.top), (x, blocked.bottom))
        costs = (x - blocked.left, blocked.right - x, y - blocked.top, blocked.bottom - y)
        return min(zip(costs, moves, strict=True))[1]

    def draw_offscreen_indicators(self, camera: Camera, target, blocked: tuple = ()):
        """One arrow, for the one place the player is being sent: where they died while their
        things are still lying there, and the tracked quest's target otherwise. Pointing at
        every dropped item and every boss on the map turned the screen edge into noise;
        ordinary loot is found by looking at it (Item.draw's ground glow), not by following
        an arrow.

        `blocked` is what the arrow may not end up under: the HUD panel with the game on
        screen, the open panel while a menu is up (the arrow is drawn over the menu then, so
        it slides round the panel instead of going out with the rest of the HUD)."""
        if target is None:
            return

        screen_x, screen_y = camera.world_to_screen(target[0], target[1])
        if 0 <= screen_x <= c.Screen.WIDTH and 0 <= screen_y <= c.Screen.HEIGHT:
            return

        margin = 30
        arrow_size = 32
        center_x = c.Screen.WIDTH // 2
        center_y = c.Screen.HEIGHT // 2
        dx = screen_x - center_x
        dy = screen_y - center_y
        distance = math.hypot(dx, dy)
        if distance == 0:
            return

        dx /= distance
        dy /= distance
        arrow_x = max(margin, min(center_x + dx * (center_x - margin), c.Screen.WIDTH - margin))
        arrow_y = max(margin, min(center_y + dy * (center_y - margin), c.Screen.HEIGHT - margin))

        # Whatever is drawn over this spot gets out of the way of the arrow rather than the
        # other way round, and the ring is re-clamped afterwards so nothing slides off screen.
        for rect in blocked:
            arrow_x, arrow_y = self._slide_clear(arrow_x, arrow_y, rect.inflate(arrow_size * 2, arrow_size * 2))
        arrow_x = max(margin, min(arrow_x, c.Screen.WIDTH - margin))
        arrow_y = max(margin, min(arrow_y, c.Screen.HEIGHT - margin))

        angle = math.atan2(dy, dx)
        arrow_points = [(arrow_size, 0), (-arrow_size // 2, -arrow_size // 2), (-arrow_size // 2, arrow_size // 2)]
        # Drawn onto its own surface, in that surface's coordinates, so the polygon can be
        # blitted with an alpha the screen's own draw calls wouldn't give it.
        local_points = [
            (
                px * math.cos(angle) - py * math.sin(angle) + arrow_size * 1.5,
                px * math.sin(angle) + py * math.cos(angle) + arrow_size * 1.5,
            )
            for px, py in arrow_points
        ]

        arrow_surface = pygame.Surface((arrow_size * 3, arrow_size * 3), pygame.SRCALPHA)
        pygame.draw.polygon(arrow_surface, (*c.Colors.YELLOW, 120), local_points)
        pygame.draw.polygon(arrow_surface, (*c.Colors.BLACK, 150), local_points, 1)
        self.screen.blit(arrow_surface, (arrow_x - arrow_size * 1.5, arrow_y - arrow_size * 1.5))

    def draw_fps(self, fps):
        fps_text = c.Fonts.small.render(f"FPS: {int(fps)}", True, c.Colors.MENU_BACKGROUND)
        self.screen.blit(fps_text, (self.screen.get_width() - 60, self.screen.get_height() - 20))
