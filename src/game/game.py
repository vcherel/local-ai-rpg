from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

import pygame

import core.constants as c
from core.audio import play_sound
from core.camera import Camera, get_shake
from core.decals import get_decals
from core.floating_text import get_floating_text
from core.impact_fx import get_impacts
from core.music import get_music
from core.particles import get_particles
from core.screen_fx import draw_blood_veil, get_banner, get_flash, get_hitstop, get_trap_fx, get_vignette
from core.swing_arcs import get_swings
from game.entities.items import rarity_color, roll_rarity
from game.entities.player import Player
from game.loot import open_lootbox
from game.record import Record
from game.world import World
from llm.death_taunts import DeathTauntGenerator
from llm.dialogue_manager import DialogueManager
from llm.llm_request_queue import get_llm_tasks, llm_busy
from llm.name_generator import NPCNameGenerator
from ui.game_renderer import GameRenderer
from ui.menus.context_menu import ContextMenu
from ui.menus.game_over import run_game_over
from ui.menus.help_menu import HelpMenu
from ui.menus.inventory_menu import InventoryMenu
from ui.menus.pause_menu import PauseMenu
from ui.menus.quest_menu import QuestMenu
from ui.menus.shop_menu import ShopMenu
from ui.menus.stats_menu import StatsMenu
from ui.notification import ToastNotification

if TYPE_CHECKING:
    from core.save import SaveSystem
    from game.entities.items import Item


# The keys a player mashes to work a leg out of a bear trap: the same ones they walk with,
# since that is what a body pinned in the grass would be trying to do with them.
_STRUGGLE_KEYS = (pygame.K_z, pygame.K_w, pygame.K_s, pygame.K_SPACE)


class Interaction(NamedTuple):
    """What the interact key acts on right now, and the prompt drawn over it. `hint` is a
    second line for an extra key on the same target (a merchant's trade key)."""

    # Which kind of thing this is, and the key into `Game.interact_actions`, which is the
    # one list of them. Loot is not among them: it is collected by the magnet in
    # `Game._sweep_loot`, never by a key.
    kind: str
    target: object
    label: str
    x: float
    y: float
    hint: str = ""


class Game:
    def __init__(self, screen, clock, save_system: SaveSystem):
        """Stand a session up, in the one order it can be built in: the menus first, since
        the world reports its lore and its loot into them, then the world and the player in
        it, then the systems that talk to both, and last the tables that name methods on all
        three."""
        self.screen = screen
        self.clock: pygame.time.Clock = clock
        self.camera = Camera()
        self.save_system = save_system

        self._build_menus()
        self._build_world()
        self._build_systems()
        self._build_action_tables()
        self._restore_player_state()

    def _build_menus(self):
        """Every screen that can be open over the world, and the toast under them all."""
        self.context_window = ContextMenu(self.screen)
        self.inventory_menu = InventoryMenu(self.screen)
        self.quest_menu = QuestMenu(self.screen)
        self.shop_menu = ShopMenu(self.screen)
        self.stats_menu = StatsMenu(self.screen)
        self.help_menu = HelpMenu(self.screen)
        self.pause_menu = PauseMenu(self.screen)
        # Every full-screen menu, for the one question asked of all of them at once: is any
        # open, and therefore is the world paused. Their input and draw calls stay written
        # out one by one below, since each takes its own arguments and the order matters.
        self.menus = (
            self.context_window,
            self.quest_menu,
            self.inventory_menu,
            self.shop_menu,
            self.stats_menu,
            self.help_menu,
            self.pause_menu,
        )
        self.loot_notification = ToastNotification(self.screen)
        # id of the last picked-up item flagged as a gear upgrade; F equips it.
        self.pending_upgrade_id = None
        # When the game last wrote itself to disk: the autosave interval counts from here,
        # and the HUD marks it briefly so a save is something the player sees happen. Backdated
        # past the marker's lifetime so entering the world doesn't flash "Saved" on arrival.
        self.last_save_ms = pygame.time.get_ticks() - GameRenderer.SAVE_MARKER_MS

    def _build_world(self):
        """The world, the player standing somewhere survivable in it, and the ground around
        that spot generated before the first frame the player controls."""
        self.world = World(self.save_system, self.context_window, self.loot_notification.show)
        self.game_renderer = GameRenderer(self.screen)

        self.player = Player(self.save_system, self.save_system.load("coins", 0))
        # A new game spawns at the fixed world centre, which the starting town's grid often
        # covers, so the player would start standing in a wall. Applied to a loaded position
        # too, which frees a save left stuck inside one, and it looks past the walls: a save
        # made mid-fight would otherwise load the player back under whatever they were
        # fighting, with no chance to react while the first frame is still being drawn.
        self.player.x, self.player.y = self.world.safe_spot_near(self.player.x, self.player.y, c.Player.SIZE / 2)
        # Generate the ground around that spot now, while the screen is still black and the
        # opening lore is being written onto it, rather than on the first frame the player
        # controls. It also settles them out of anything a fresh chunk grew on top of them.
        self.world.prepare(self.player)

    def _build_systems(self):
        """What talks to the world and the player both: conversation, quests, the background
        writers, the tally, and the per-frame flags the run loop keeps."""
        self.dialogue_manager = DialogueManager(self.screen, self.world.items, self.player, self.world.npcs)
        # slay_boss quests spawn their target through the world.
        self.dialogue_manager.quest_system.world = self.world
        # A quest handed in is worth a save of its own: it is the one thing in a session
        # that can't be earned back by walking the same ground again.
        self.dialogue_manager.quest_system.on_complete = self._on_quest_completed
        self.npc_name_generator = NPCNameGenerator(self.save_system)
        # What the playthrough has added up to: deaths and quests handed in, and what those
        # two numbers have already paid out.
        self.record = Record(self.save_system)
        self.death_taunts = DeathTauntGenerator(self.save_system, self.record)
        self.active_menu = False
        # Set by the pause menu's "Quit to menu"; breaks the run loop so control
        # returns to the main menu (game state is saved on the way out).
        self.quit_to_menu = False
        # Set when the window is closed: the process exits instead of returning to the menu.
        self.quit_app = False

        # Until when the music is still calling this a fight. Set by anything hostile being
        # near and read a few seconds later, so a pack picked off one at a time stays one
        # fight instead of crossfading in and out of the combat pad between kills.
        self._combat_until = 0
        # The building the player is currently standing inside, or None outdoors. Recomputed
        # every frame from the player's position; a building's interior is just its own
        # footprint in world space, so there is no separate coordinate space or mode switch.
        self.interior = None
        # What E would act on this frame (Game.current_interaction), recomputed each update
        # and drawn as the single on-screen prompt.
        self.interaction: Interaction | None = None
        # How far the player has got with the beam across a barred gate, 0 to 1. The one
        # interaction in the game that is held rather than pressed, so it is the one that
        # needs a frame-by-frame state of its own; taking a hit costs part of it, and letting
        # go loses all of it (`_lift_gate`).
        self.gate_lift = 0.0
        self._lift_hp = 0

    def _build_action_tables(self):
        """The three tables that name what a press or a click does, built last because every
        one of them points into a menu, the world or the renderer.

        A key, a dock icon and an interaction prompt are the same idea three times: one row
        per thing the player can do, rather than a branch written out in the handler.
        """
        # What each icon in the HUD dock does, keyed by the action its row in
        # `GameRenderer.dock_buttons` carries, so the two lists are read against each other.
        self.dock_actions = {
            "inventory": self.inventory_menu.toggle,
            "quests": self.quest_menu.toggle,
            "stats": self.stats_menu.toggle,
            "lore": self._show_lore,
            "help": self.help_menu.toggle,
            "pause": self.pause_menu.toggle,
        }

        # The whole key map as one table. `HelpMenu.CONTROLS` is what tells the player about it.
        self.key_actions = {
            pygame.K_1: self._swap_hands,
            pygame.K_g: self._use_bomb,
            pygame.K_e: self._interact,
            pygame.K_b: self._trade_nearby,
            pygame.K_f: self._equip_pending_upgrade,
            pygame.K_i: self.inventory_menu.toggle,
            pygame.K_j: self.quest_menu.toggle,
            pygame.K_c: self.stats_menu.toggle,
            pygame.K_l: self._show_lore,
            pygame.K_h: self.help_menu.toggle,
            pygame.K_m: self.game_renderer.minimap.toggle,
            pygame.K_p: self.pause_menu.toggle,
            pygame.K_ESCAPE: self.pause_menu.toggle,
        }

        # What E does to each kind of thing it can be offered, keyed by `Interaction.kind`.
        # Every handler takes the interaction's target, whether or not it needs it, so a new
        # interaction is one row here and one `_offer_*` rather than another branch. A gate
        # is the one that does nothing on a press: the beam is heaved up by holding the key
        # (`_lift_gate`), and the prompt says so.
        self.interact_actions = {
            "npc": self._talk_to,
            "chest": lambda _target: self._open_interior_chest(),
            "bed": lambda _target: self._sleep_in_bed(),
            "door": self._use_door,
            "gate": lambda _target: None,
            "well": self._climb_down_well,
            "cave": self._enter_cave,
            "ladder": self._climb_back_up,
            "camp": lambda camp: self.world.rest_at_camp(self.player, camp),
            "shrine": lambda shrine: self.world.pray_at_shrine(self.player, shrine),
        }

    def _restore_player_state(self):
        """Relink the saved inventory and active quests to the world's reloaded items."""
        items_by_id = {item.id: item for item in self.world.items}

        for item_id in self.save_system.load("inventory", []):
            item = items_by_id.get(item_id)
            if item is not None:
                self.player.inventory.append(item)

        self.player.restock_bars()

        quest_system = self.dialogue_manager.quest_system
        for npc in self.world.npcs:
            if npc.has_active_quest:
                quest_system.active_quests.append(npc.quest)

    def update_camera(self):
        self.camera.set_pos(self.player.get_pos())

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                # Closing the window ends the whole game, not just this session.
                self.quit_app = True
                return False

            if self.context_window.handle_event(event):
                continue

            if self.inventory_menu.handle_event(event, self.player):
                continue

            if self.shop_menu.handle_event(event):
                continue

            if self.dialogue_manager.handle_event(event, self.npc_name_generator):
                continue

            if self.quest_menu.handle_event(event, self.dialogue_manager.quest_system):
                continue

            if self.stats_menu.handle_event(event):
                continue

            if self.help_menu.handle_event(event):
                continue

            if self.pause_menu.handle_event(event, self._save_from_menu, self._quit_to_menu):
                continue

            if not self.active_menu:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        self._handle_left_click(event)

                    elif event.button == 3:  # Right click: whatever hand two is holding
                        self.world.handle_attack(self.player, self.dialogue_manager.quest_system, hand=1)

                if event.type == pygame.KEYDOWN:
                    self._handle_key(event)

        if self.dialogue_manager.shop_requested and not self.dialogue_manager.active:
            npc = self.dialogue_manager.current_npc
            if npc is not None and npc.is_merchant:
                self.shop_menu.open(npc, self.player, self.world.items)
            self.dialogue_manager.shop_requested = False

        return True

    def _handle_left_click(self, event):
        """A left click in the world: a HUD button if it landed on one, a swing otherwise.

        The dock buttons are looked up by action out of `GameRenderer.dock_buttons`, so a new
        one is one row there and one row in `self.dock_actions` rather than a rect named in
        this file and named again over there.
        """
        for action, rect, _icon, _tooltip in self.game_renderer.dock_buttons:
            if rect.collidepoint(event.pos):
                self.dock_actions[action]()
                return

        if self.dialogue_manager.quest_tracker.handle_event(event, self.dialogue_manager.quest_system):
            return

        if self.game_renderer.loading_indicator.rect.collidepoint(event.pos):
            self.game_renderer.show_llm_tasks = not self.game_renderer.show_llm_tasks
            return

        self.world.handle_attack(self.player, self.dialogue_manager.quest_system)

    def _handle_key(self, event):
        """One in-world key press. The potion quickbar's letters are checked first because
        they read the key rather than name it; everything else is a plain key looked up in
        `self.key_actions`."""
        # A movement key pressed while the jaws are on the player is a struggle rather than
        # a step: the trap takes the seconds back one press at a time.
        if event.key in _STRUGGLE_KEYS and self._struggle():
            return
        if event.unicode.lower() in c.Potions.QUICK_KEYS:
            self._drink_quick_potion(c.Potions.QUICK_KEYS.index(event.unicode.lower()))
            return

        action = self.key_actions.get(event.key)
        if action is not None:
            action()

    def _struggle(self) -> bool:
        """One tug against a bear trap's jaws, and whether there was anything to tug at.

        A trap is the only thing in the world that takes movement away, so the seconds it
        costs are not meant to be sat out: every press works the leg further loose
        (`Traps.STRUGGLE_MS`), with the jaws jerking so the effort reads as progress. The
        bar over the player's head is drawn from what is left of the hold."""
        if not self.player.shorten_root(c.Traps.STRUGGLE_MS):
            return False
        get_particles().spawn_burst(self.player.x, self.player.y, c.Traps.JAW_COLOR, count=5, speed=4, life=260, size=3)
        get_shake().add(c.Traps.STRUGGLE_SHAKE)
        play_sound("bush_rustle")
        return True

    def _show_lore(self):
        if self.world.context:
            self.context_window.show(self.world.context)

    def _award_loot(self, rarity: str, label: str):
        coins, loot_item = open_lootbox(self.player.x, self.player.y, rarity)
        self.player.gain_coins(coins)

        message = f"{label}: +{coins} coins"
        if loot_item is not None:
            # A stackable merges into an existing stack; only a genuinely new entry joins the master list.
            if self.player.add_item(loot_item) is loot_item:
                self.world.items.append(loot_item)
            message += f" and a {loot_item.rarity} {loot_item.name}!"

        self.loot_notification.show(message, rarity_color(rarity))
        play_sound("lootbox_open")
        if loot_item is not None:
            self._offer_upgrade(loot_item)

    def _open_lootbox(self, lootbox: Item):
        self.world.items.remove(lootbox)
        self._award_loot(lootbox.rarity, "Lootbox")

    def _offer_upgrade(self, item: Item) -> bool:
        """Flag a just-acquired item as an upgrade and prompt to equip it with F. Returns
        whether it said anything, so a caller can fall back to its own message."""
        if not self.player.is_upgrade(item):
            return False
        self.pending_upgrade_id = item.id
        self.loot_notification.show(f"New {item.name} (+{item.bonus}), press F to equip", rarity_color(item.rarity))
        return True

    def _announce_pickup(self, item: Item):
        """Say something for every item that reaches the inventory. An upgrade gets the F
        prompt; anything else at least names itself, since a pickup that isn't an upgrade
        (a second bow while a stronger staff is equipped, a pelt, a potion) used to be
        silent apart from the sound."""
        if self._offer_upgrade(item):
            return
        label = f"Picked up {item.name}"
        if item.quantity > 1:
            label += f" x{item.quantity}"
        self.loot_notification.show(label, rarity_color(item.rarity))

    def _equip_pending_upgrade(self):
        if self.pending_upgrade_id is None:
            return
        item = next((i for i in self.player.inventory if i.id == self.pending_upgrade_id), None)
        self.pending_upgrade_id = None
        if item is None:
            return
        self.player.equip(item)
        self.loot_notification.show(f"Equipped {item.name}", rarity_color(item.rarity))

    def _swap_hands(self):
        """Exchange the two weapons over: what the left click was using goes to the right
        button and back. The same move the bag offers, without opening it, so the answer the
        other hand carries is one press away mid fight.

        An empty hand swaps like any other, since bare hands on a button is a loadout rather
        than a missing weapon, which is why the report names both sides."""
        self.player.swap_hands()
        held = [self.player.hand_weapon(hand) for hand in range(c.Player.HANDS)]
        names = [item.name if item is not None else "bare hands" for item in held]
        self.loot_notification.show(f"Left: {names[0]}  |  Right: {names[1]}", c.Colors.ACCENT)

    def _use_bomb(self):
        """Spend one out of the bomb slot: a mine laid underfoot, a grenade thrown at the
        cursor. A key of its own rather than a mouse button, because a bomb is a piece of
        ground the player has decided to fight over rather than a weapon a hand swings."""
        bomb = self.player.equipped_item("bomb")
        if bomb is None:
            self.loot_notification.show("No bomb equipped", c.Colors.MUTED)
            return
        self.world.use_bomb(self.player, bomb)

    def _drink_quick_potion(self, slot: int):
        """Drink the potion bound to a HUD quick key, if that slot holds one."""
        potions = self.player.quick_potions()
        if slot >= len(potions) or potions[slot] is None:
            return
        potion = potions[slot]
        result = self.player.use_potion(potion)
        if result is None:
            self.loot_notification.show("Already at full health", c.Colors.MUTED)
        else:
            self.loot_notification.show(f"{potion.name}: {result}", potion.color)

    def current_interaction(self) -> Interaction | None:
        """The single thing the interact key acts on right now: the nearest interactable in
        reach, indoors or out. The prompt drawn on screen comes from the same call, so a
        tavern full of beds can't stack labels and the prompt can never point at something
        other than what the key does."""
        best: tuple | None = None  # (distance, Interaction)

        def offer(interaction: Interaction, dist: float):
            nonlocal best
            if best is None or dist < best[0]:
                best = (dist, interaction)

        def reach_of(x, y) -> float:
            return math.hypot(self.player.x - x, self.player.y - y)

        self._offer_indoors(offer, reach_of)
        self._offer_doors(offer, reach_of)
        self._offer_gate(offer, reach_of)
        self._offer_underground(offer, reach_of)
        self._offer_places(offer, reach_of)
        self._offer_npc(offer, reach_of)
        return None if best is None else best[1]

    def _offer_indoors(self, offer, reach_of):
        """The chest and the beds of the room the player is standing in, if they are in one."""
        if self.interior is not None:
            indoor_reach = c.Buildings.INTERACT_DISTANCE
            layout = self.interior.interior_layout()
            chest = layout["chest"]
            if chest and not self.interior.looted:
                dist = reach_of(chest.centerx, chest.centery)
                if dist <= indoor_reach:
                    # A chest only ever stands in somebody's house, so opening it is theft
                    # and the prompt says so rather than dressing it up as loot.
                    label = self._watched_label("E: steal from the chest")
                    offer(Interaction("chest", chest, label, chest.centerx, chest.top), dist)

            for bed in layout["beds"]:
                dist = reach_of(bed.centerx, bed.centery)
                if dist <= indoor_reach:
                    offer(Interaction("bed", bed, self._bed_label(), bed.centerx, bed.top), dist)

    def _offer_doors(self, offer, reach_of):
        """Every front door in reach, and whether E would open it or shut it."""
        for building in self.world.buildings_near(self.player.x, self.player.y):
            if not building.has_door or building.door_broken:
                continue
            door = building.door_rect()
            dist = reach_of(door.centerx, door.centery)
            if dist > c.Buildings.INTERACT_DISTANCE:
                continue
            if building.door_overlaps(self.player.x, self.player.y, c.Player.SIZE / 2):
                # Standing in the doorway: the only thing E may do here is open it. Offering
                # to close a door around oneself is how one used to end up sealed in it.
                if building.door_open:
                    continue
                label = "E: open the door"
            else:
                label = "E: close the door" if building.door_open else "E: open the door"
            offer(Interaction("door", building, label, door.centerx, door.top - 10), dist)

    def _offer_gate(self, offer, reach_of):
        """The barred gate the player is standing at, and the only prompt in the game that
        is held rather than pressed. A town that has shut itself is not a box: the beam can
        be heaved up from the inside, it just takes long enough that doing it with a mob at
        your back is a decision (`_lift_gate`)."""
        found = self.world.barred_gate_in_reach(self.player)
        if found is None:
            return
        village, index = found
        leaf = village.defences()["gates"][index]["rect"]
        label = f"Hold E: heave the bar up ({int((1 - self.gate_lift) * c.Villages.GATE_LIFT_S) + 1}s)"
        offer(Interaction("gate", found, label, leaf.centerx, leaf.top - 10), reach_of(leaf.centerx, leaf.centery))

    def _offer_underground(self, offer, reach_of):
        """The two ends of the dark: the way back up when down there, the two ways down when
        on the surface. Never both, since one of them is always somewhere else."""
        if self.world.underground is not None:
            # The one way back up, and the only thing to interact with down there besides
            # what is lying on the floor.
            tunnel = self.world.underground
            if tunnel.at_exit(self.player.x, self.player.y):
                label = "E: climb back up" if tunnel.kind == "well" else "E: leave the cave"
                offer(Interaction("ladder", tunnel, label, *tunnel.entrance), reach_of(*tunnel.entrance))
        else:
            village = self.world.well_in_reach(self.player)
            if village is not None:
                # Deliberately not "climb down": which wells go anywhere is what walking over
                # to one is for, and a prompt that already knew would answer the question.
                offer(
                    Interaction("well", village, "E: look down the well", village.x, village.y - 40),
                    reach_of(village.x, village.y),
                )

            cave = self.world.cave_in_reach(self.player)
            if cave is not None:
                offer(
                    Interaction("cave", cave, "E: enter the cave", cave.x, cave.y - 50),
                    reach_of(cave.x, cave.y),
                )

    def _offer_places(self, offer, reach_of):
        """A campfire to rest at and a shrine to pray at: the places that answer once and
        then go quiet for a while."""
        camp = self.world.camp_in_reach(self.player)
        if camp is not None:
            cooling = self.world.rest_ready_in(camp.id)
            label = f"E: fire burned low ({int(cooling) + 1}s)" if cooling > 0 else "E: rest at the fire"
            offer(Interaction("camp", camp, label, camp.x + 40, camp.y), reach_of(camp.x, camp.y))

        shrine = self.world.shrine_in_reach(self.player)
        if shrine is not None:
            offer(
                Interaction("shrine", shrine, "E: pray at the shrine", shrine.x, shrine.y - 40),
                reach_of(shrine.x, shrine.y),
            )

    def _offer_npc(self, offer, reach_of):
        """Whoever is close enough to talk to, and the reason they won't when they won't."""
        npc = self.world.npc_in_reach(self.player)
        # A merchant still waiting on its stock, someone who has turned on the player, or a
        # world whose context hasn't generated yet: no prompt for something the key wouldn't do.
        if (
            npc is not None
            and npc.can_talk
            and self.world.context is not None
            and not (npc.is_merchant and not npc.shop_ready)
        ):
            if self._threat_nearby():
                # Nobody stands in the street making conversation with a wolf twenty paces
                # off. Kill it or walk away from it first.
                label = f"{npc.name or 'They'} won't talk with that out there"
            elif llm_busy():
                # One model serves the whole game and the call already running cannot be
                # cut short, so a conversation opened now would sit on an empty box.
                label = f"{npc.name} is busy..." if npc.name else "Busy..."
            else:
                label = f"E: talk to {npc.name}" if npc.name else "E: talk"
            hint = "B: trade" if npc.is_merchant else ""
            offer(Interaction("npc", npc, label, npc.x, npc.y - c.Entities.NPC_SIZE, hint), reach_of(npc.x, npc.y))

    def _interact(self):
        """Run whatever the on-screen prompt is offering, out of `self.interact_actions`."""
        interaction = self.current_interaction()
        if interaction is None:
            return
        self.interact_actions[interaction.kind](interaction.target)

    def _climb_down_well(self, village):
        self.world.enter_tunnel(self.player, village)
        self.save_data()

    def _enter_cave(self, poi):
        self.world.enter_cave(self.player, poi)
        self.save_data()

    def _climb_back_up(self, _tunnel):
        self.world.leave_tunnel(self.player)
        self.save_data()

    def _threat_nearby(self) -> bool:
        """Whether anything hostile is close enough to make a conversation absurd. Shared by
        the prompt and the talk key so the two can't disagree, exactly like the busy check."""
        return bool(self.world.hostiles_near(self.player.x, self.player.y, c.Entities.TALK_SAFE_RADIUS))

    def _talk_to(self, npc):
        if self.world.context is None or not npc.can_talk or (npc.is_merchant and not npc.shop_ready):
            return
        if self._threat_nearby():
            self.loot_notification.show(f"{npc.name or 'They'} won't talk with danger this close", c.Colors.MUTED)
            return
        if llm_busy():
            self.loot_notification.show(f"{npc.name or 'They'} looks busy, give it a moment", c.Colors.MUTED)
            return
        self.player.stats.train("bartering", c.Stats.XP_PER_TALK_BARTERING)
        self.player.stats.train("persuasion", c.Stats.XP_PER_TALK)
        self.dialogue_manager.interact_with_npc(npc, self.npc_name_generator, self.world)

    def _trade_nearby(self):
        """Open a merchant's shop straight from the world, skipping the conversation."""
        npc = self.world.npc_in_reach(self.player)
        if npc is None or not npc.is_merchant or not npc.shop_ready or not npc.can_talk:
            return
        self.shop_menu.open(npc, self.player, self.world.items)

    def _sweep_loot(self, dt):
        """The whole of picking things up. Anything lying within the magnet's reach flies at
        the player and is collected on contact, so loot is taken by walking over it and the
        interact key is left for doors, beds, chests and people.

        Loot standing on another building's floor is left alone, the same rule the renderer
        draws by: nothing is dragged out through a wall."""
        for item in list(self.world.items):
            if item.picked_up:
                continue
            if self.world.building_at(item.x, item.y) is not self.interior:
                # Behind a wall: no pull at all, and whatever it had built up is let go, so
                # walking back into the room starts it moving from a standstill.
                item.magnet_speed = 0.0
                continue
            if self._magnet(item, dt):
                self._pickup_world_item(item)

        if self.interior is not None:
            for item in list(self.interior.dropped_items):
                if self._magnet(item, dt):
                    self._pickup_dropped_item(item)

    def _magnet(self, item: Item, dt) -> bool:
        """Pull one piece of loot a frame's worth toward the player, and say whether it got
        there. Out of the magnet's reach it simply lets go of whatever pull it had."""
        if item.distance_to_point((self.player.x, self.player.y)) > c.Player.MAGNET_RADIUS:
            item.magnet_speed = 0.0
            return False
        return item.magnet_toward(self.player.x, self.player.y, dt)

    @staticmethod
    def _pickup_burst(item: Item):
        """The puff of colour every pickup leaves behind, whatever became of the item."""
        get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)

    def _pickup_world_item(self, item: Item):
        item.picked_up = True
        if item.item_type == "coins":
            # A purse is money on the ground, not an object: it is credited and gone,
            # never carried, so it leaves the master item list rather than sitting in the
            # save as something picked up.
            self.world.items.remove(item)
            self.player.gain_coins(item.quantity)
            self.loot_notification.show(f"+{item.quantity} coins", c.Colors.ACCENT)
            play_sound("pickup")
            self._pickup_burst(item)
            return
        if item.item_type == "lootbox":
            self._open_lootbox(item)
            self._pickup_burst(item)
            return

        # If it merges into a stack (ammo, potions), drop the now-orphaned world item.
        if self.player.add_item(item) is not item and item in self.world.items:
            self.world.items.remove(item)
        self._collect_item(item)

    def _collect_item(self, item: Item):
        """Feedback shared by every item pickup. The caller has already settled the item
        into the inventory and the world's master item list."""
        play_sound("pickup")
        self._announce_pickup(item)
        self._pickup_burst(item)

    def _pop_levelups(self):
        """Drain any stat level-ups queued this frame and pop the gold text/sparkle/chime
        over the player. Centralised here so every Stats.train() call site gets it for free."""
        levelups = self.player.stats.pending_levelups
        if not levelups:
            return
        self.player.stats.pending_levelups = []
        for name, level in levelups:
            get_floating_text().spawn(
                self.player.x,
                self.player.y - c.Player.SIZE / 2,
                f"{c.STAT_LABELS[name]} up! Lv {level}",
                c.Colors.ACCENT,
                big=True,
                life=1600,
            )
            get_particles().spawn_burst(
                self.player.x, self.player.y, c.Colors.ACCENT, count=18, speed=3.5, life=600, size=5
            )
            play_sound("level_up")

    def _pickup_dropped_item(self, item: Item):
        self.interior.dropped_items.remove(item)
        item.picked_up = True
        # If ammo merges into a stack, register the item purely so a saved inventory
        # id can still find it after reload; it never renders or drops again.
        if self.player.add_item(item) is item:
            self.world.items.append(item)
        self._collect_item(item)

    def _open_interior_chest(self):
        """Empty the chest in someone's house. Free, silent, and entirely between the player
        and whoever happens to be standing outside."""
        building = self.interior
        building.looted = True
        self._award_loot(roll_rarity(luck=self.player.loot_luck()), "Stolen goods")
        stolen = self.dialogue_manager.quest_system.on_theft(building.id)
        if stolen is not None:
            self.loot_notification.show(f"You take the {stolen.name}", c.Colors.YELLOW)
        self._check_witness()

    def _bed_cooling(self) -> float:
        """Seconds before this bed is worth lying in again. Every bed in the world has the
        same cooldown, the tavern's included: a room of them is not a row of full heals. The
        prompt and the key both read it from here so they can't disagree about whether it
        will work."""
        return self.world.rest_ready_in(self.interior.id)

    def _watched_label(self, label: str) -> str:
        """The prompt over something that isn't the player's, with whoever can see them
        doing it named on it. The cones on the ground say where the eyes are; this says the
        theft is being watched right now, which is the part worth reading before pressing E."""
        witness = self.world.theft_witness(self.player.x, self.player.y)
        if witness is None:
            return label
        return f"{label} ({witness.name or 'someone'} is watching)"

    def _bed_label(self) -> str:
        """What the prompt over a bed says. No bed is paid for and none of them is the
        player's, so all of them read the same way: whether it is still warm, and who is
        watching them climb into it."""
        if self._sleep_threat():
            return "Too dangerous to sleep with that out there"
        cooling = self._bed_cooling()
        if cooling > 0:
            return f"E: this bed is still warm ({int(cooling) + 1}s)"
        label = "E: sleep in their bed" if self.interior.kind == "house" else "E: take a room"
        return self._watched_label(label)

    def _use_door(self, building):
        """Open or shut a door. Shutting one is the only way to put a wall between the player
        and whatever is chasing them, which is the point: a monster can beat a door down, but
        it takes it several swings and they are audible."""
        radius = c.Player.SIZE / 2
        in_doorway = building.door_overlaps(self.player.x, self.player.y, radius)
        if in_doorway and building.door_open:
            # The prompt refuses this too; the key must not disagree with it.
            return
        building.toggle_door()
        play_sound("door")
        if building.door_closed and in_doorway:
            # Never shut a door on oneself. One step in or one step out along the wall's own
            # normal, not a ring search: the doorway is the only gap in that wall, so a
            # search for somewhere free can come back with nowhere and leave the player
            # standing in the leaf that just swung shut.
            self.player.x, self.player.y = building.clear_of_door(self.player.x, self.player.y, radius)
            self.player.x, self.player.y = self.world.free_spot_near(self.player.x, self.player.y, radius)

    def _sleep_in_bed(self):
        # A bed is the one full night's rest in the game: unlike a campfire it heals
        # everything, shakes off the post-death weakness and puts the night behind the
        # player. None of them is bought and none of them is the player's: a tavern room
        # is taken rather than paid for, exactly like a villager's own bed, so both cost
        # the risk of being seen and both leave that bed cold for a while. Nobody sleeps
        # with something hostile in the street, the same refusal a campfire makes through
        # `camp_is_clear`.
        if self._sleep_threat():
            self.loot_notification.show("Too dangerous to sleep with that out there", c.Colors.RED)
            return

        remaining = self._bed_cooling()
        if remaining > 0:
            self.loot_notification.show(f"You slept here recently. Again in {int(remaining) + 1}s", c.Colors.MUTED)
            return
        self.world.rest_in_house(self.interior)

        play_sound("quest_complete")
        self._sleep_until_dawn()
        self.player.clear_death_debuff()
        self.player.max_hp = self.player.effective_max_hp()
        self.player.hp = self.player.max_hp
        self.loot_notification.show("You sleep until dawn and wake fully rested", c.Colors.GREEN)
        # Not a theft, and never worded as one: the household finds a stranger in the bed.
        self._check_witness("squatting")
        # A night is hours of world clocks moved on; nobody wants to sleep it twice.
        self.save_data()

    def _lift_gate(self, dt):
        """Heaving the bar off a gate the town shut on the player, one frame at a time.

        A settlement that has turned is not a box the player is locked in until they have
        chopped their way out: the beam can be lifted from the inside. It just takes
        `Villages.GATE_LIFT_S` of standing still with both hands on it, and a blow landing
        costs a share of that (`Villages.GATE_LIFT_HIT_LOSS`), so doing it with a mob behind
        you is a decision rather than an escape hatch. Walking away or letting go of the key
        loses the lot: this is a beam, not a progress bar that waits.

        Once it is up, the player steps through the way the settlement's own people do
        (`Village.gate_side_point`), and it drops back into place behind them."""
        hurt = self.player.hp < self._lift_hp
        self._lift_hp = self.player.hp
        holding = self.interaction is not None and self.interaction.kind == "gate"
        if not holding or not pygame.key.get_pressed()[pygame.K_e]:
            self.gate_lift = 0.0
            return
        if hurt:
            self.gate_lift = max(0.0, self.gate_lift - c.Villages.GATE_LIFT_HIT_LOSS)
        self.gate_lift += dt / 1000 / c.Villages.GATE_LIFT_S
        if self.gate_lift < 1.0:
            return
        self.gate_lift = 0.0
        village, index = self.interaction.target
        village.lift_bar(index)
        play_sound("door")
        radius = c.Player.SIZE / 2
        self.player.x, self.player.y = village.gate_side_point(index, self.player.x, self.player.y, radius, across=True)
        self.player.x, self.player.y = self.world.free_spot_near(self.player.x, self.player.y, radius)
        self.loot_notification.show("You heave the bar up and slip through", c.Colors.GREEN)

    def _sleep_threat(self) -> bool:
        """Whether anything hostile is close enough to make lying down absurd. Shared by the
        prompt and the key, like every other refusal."""
        return bool(self.world.hostiles_near(self.player.x, self.player.y, c.Buildings.SLEEP_SAFE_RADIUS))

    def _sleep_until_dawn(self):
        """Fade out, run the world forward to just after dawn, fade back in.

        Deliberately not instant: the tint moving under the fade is the only thing that says
        hours went by. Nothing in the world takes a step while it runs (`World.update` is not
        called), but every clock in it moves, and whatever was coursing through the player's
        veins at bedtime has worn off by morning."""
        skip_ms = self.world.daynight.time_until(c.Buildings.SLEEP_WAKE_PROGRESS)
        duration = c.Buildings.SLEEP_FADE_MS
        overlay = pygame.Surface((c.Screen.WIDTH, c.Screen.HEIGHT))
        overlay.fill((0, 0, 0))

        elapsed = 0.0
        while elapsed < duration:
            # Input is swallowed for the second and a half this lasts; the pump is only
            # there so the window keeps answering the OS.
            pygame.event.pump()
            step = min(self.clock.tick(60), duration - elapsed)
            elapsed += step
            self.world.pass_time(skip_ms * (step / duration) / 1000)

            self.game_renderer.draw_world(self.camera, self.world, self.player, self.interior, None, None)
            self.world.daynight.draw(self.screen, self.world.events.blood_intensity)
            # Full black at the halfway mark, clear at both ends.
            overlay.set_alpha(int(255 * math.sin(math.pi * elapsed / duration)))
            self.screen.blit(overlay, (0, 0))
            pygame.display.flip()

        # Whatever was pressed while the screen was black is not an instruction about the
        # morning, so it is dropped rather than replayed the moment the player can see.
        pygame.event.clear()
        self.player.clear_buffs()

    def _check_witness(self, offence: str = "theft"):
        """See whether anyone caught the player helping themselves in someone's house.

        The one place a single NPC turns hostile on their own: whoever saw it comes for the
        player, and the rest of the village never hears about it. Swinging back at them is
        what turns the whole settlement, through the usual `World.provoke_village`.

        The first time is a warning rather than a knife (`World.strike_village`), and a
        villager who has only shouted still has their quest and still talks. Which ledger it
        is spent on is `offence`: a bed taken for the night is not a hand in a chest, and
        the two are counted apart.

        A bed is found rather than watched (`World.squatter_witness`): a night is hours of a
        household coming and going, not the instant a lid is lifted."""
        finder = self.world.squatter_witness if offence == "squatting" else self.world.theft_witness
        witness = finder(self.player.x, self.player.y)
        if witness is None:
            return
        if self.world.catch_thief(witness, self.player, offence) is None:
            return
        # Nobody sees a task through for someone they are trying to kill.
        self.dialogue_manager.quest_system.remove_quest(witness)
        play_sound("player_hurt")

    def _save_from_menu(self):
        """Manual save from the pause menu, with an on-screen confirmation."""
        self.save_data()
        self.loot_notification.show("Game saved", c.Colors.GREEN)

    def _on_quest_completed(self):
        """A quest handed in: count it, pay out if that one crossed a milestone, and save.

        The milestone reward goes through the same lootbox every other windfall in the game
        does, so the tenth quest pays the way a boss does rather than in a number that only
        exists on the character screen."""
        milestone = self.record.add_quest()
        if milestone is not None:
            count, rarity = milestone
            self._award_loot(rarity, f"{count} quests completed")
        self.save_data()

    def _respawn(self):
        """Death has a real cost, not just a free full-heal at the same spot: dock coins,
        weaken the player for a while, and put them back at world spawn so they can't keep
        swinging at what killed them. The run carries on from there."""
        # Read before the player is moved: whichever settlement they fell in front of is the
        # one that lets its anger go, since dying to a town is the town getting its own back.
        self.world.pacify_village(self.player.x, self.player.y)
        coins_lost = self.player.apply_death_penalty()
        # Counted before the taunt is drawn, so the line the player is about to read can be
        # one this very death just unlocked.
        milestone_deaths = self.record.add_death()
        # Read before anything else touches the player: the screen wants to know what killed
        # them, and the taunt was written long before this death happened.
        killer = self.player.last_hit_by
        taunt = self.death_taunts.take()
        self.player.last_hit_by = ""
        self.player.hp = self.player.max_hp
        center = c.World.WORLD_SIZE // 2
        # Dying underground puts the player back on the surface like any other death: the
        # tunnel keeps whatever is left of its garrison, and the walk back down is the price.
        self.world.abandon_tunnel()
        # Nothing that was after the player is waiting for them at the spawn point: the pack
        # is sent back out into the wilds (the respawn loop restocks it soon enough, further
        # out), the player is placed clear of whatever is left, and the window they arrive in
        # covers the seconds it takes to work out where they are.
        self.world.clear_hostiles_around(center, center, c.World.SAFE_RADIUS)
        self.player.x, self.player.y = self.world.safe_spot_near(center, center, c.Player.SIZE / 2)
        # Whatever was in the air when the player died shouldn't greet them at spawn.
        self.world.projectiles.clear()
        self.interior = None
        self.interaction = None
        self.update_camera()
        self.save_data()

        run_game_over(self.screen, self.clock, coins_lost, c.Death.DEBUFF_DURATION_S, taunt, killer)
        # Granted after the death screen, not before: it holds for seconds of wall-clock time
        # and would otherwise be spent staring at it.
        self.player.grant_spawn_grace()
        self.loot_notification.show(f"You died. -{coins_lost} coins", c.Colors.RED)
        if milestone_deaths is not None:
            # Dying enough times is not an achievement, so it does not pay in loot. It pays
            # in the game having more to say about it.
            self.loot_notification.show(f"{milestone_deaths} deaths: death has found new words", c.Colors.MUTED)

    def _quit_to_menu(self):
        """Leave the game and return to the main menu; run() saves as it exits."""
        self.quit_to_menu = True

    def save_data(self):
        # NPC names persist themselves as they're generated/consumed; nothing to do here.
        # Building interiors are just world space now, so the player's and monsters'
        # positions are always plain world coordinates, indoors or out.
        self.save_system.update("player", self.player.to_dict())
        self.player.save_stats()
        self.save_system.update("inventory", [item.id for item in self.player.inventory])

        for key, value in self.world.serialize().items():
            self.save_system.update(key, value)

        self.save_system.save_all()
        # What the corner marker counts down from, and what the autosave interval is
        # measured against, so a save from any other path pushes the periodic one back.
        self.last_save_ms = pygame.time.get_ticks()

    def run(self):
        # The spawn grace opens on the first frame the player can actually see the world
        # rather than here, for the same reason it is granted after the death screen: the
        # opening lore holds for as long as the model takes and as long as the player
        # reads, and a window spent staring at black text is no window at all.
        granted_grace = False

        while True:
            self.active_menu = self.dialogue_manager.active or any(menu.active for menu in self.menus)

            if not self.handle_input() or self.quit_to_menu:
                break

            # Skip world simulation while a menu is open to save computation, but keep
            # rendering the world every frame so menus show it behind their dim overlay
            # instead of it going stale (and progressively darker as the overlay restacks).
            if not self.active_menu:
                if not granted_grace:
                    granted_grace = True
                    self.player.grant_spawn_grace()
                self._update_frame()

            self._draw_frame()

            if pygame.time.get_ticks() - self.last_save_ms >= c.World.AUTOSAVE_INTERVAL_S * 1000:
                self.save_data()

            if self.player.hp <= 0:
                self._respawn()

            pygame.display.flip()
            # The typing in a conversation wants the extra frames; nothing else does.
            self.clock.tick(180 if self.dialogue_manager.active else 60)

        self.save_data()
        # Generation threads can still be queued behind other LLM calls; from here on they
        # belong to a session that is over and must leave the save file to the next game.
        self.world.close()
        self.npc_name_generator.close()
        self.death_taunts.close()

    def _update_frame(self):
        """One step of the world. Only runs with no menu open, which is what pausing is."""
        dt = self.clock.get_time()
        # A heavy hit freezes gameplay motion for a few frames without slowing the camera
        # shake/particles/damage numbers below, so the impact reads as a freeze-frame
        # rather than the whole game stuttering.
        gameplay_dt = get_hitstop().apply(dt)
        in_water = self.world.water_at(self.player.x, self.player.y)
        self.player.move(self.camera.get_pos(), gameplay_dt, self.world.blocked, in_water)
        self.world.update(self.player, gameplay_dt, self.dialogue_manager.quest_system, self.npc_name_generator)
        self._pop_levelups()
        # A building's interior is just its own footprint; re-derive which one (if any) the
        # player is standing in rather than tracking a separate mode.
        self.interior = self.world.building_at(self.player.x, self.player.y)
        self._sweep_loot(gameplay_dt)
        self.interaction = self.current_interaction()
        self._lift_gate(gameplay_dt)
        self.update_camera()
        for system in (get_shake(), get_particles(), get_swings(), get_impacts()):
            system.update(dt)
        for system in (get_floating_text(), get_decals(), get_vignette(), get_flash(), get_trap_fx(), get_banner()):
            system.update(dt)
        # The music answers what is happening rather than only what time it is: the pads
        # crossfade between contexts, and through dusk and dawn when nothing louder is going
        # on than the sky changing.
        get_music().update(dt, self.world.daynight.darkness, self._music_context())

    def _music_context(self) -> str:
        """What the world is doing, as one of `core.music.CONTEXTS`.

        A priority rather than a blend, because two of these at once is the ordinary case: a
        boss on a blood night is a boss, and a fight in a street is a fight. The order is
        what is most immediately about to kill the player first, and where they are standing
        last. `_combat_until` is a short hold, so a pack picked off one at a time is one
        fight rather than eight crossfades."""
        player = self.player
        if any(boss.distance_to_point(player.get_pos()) < c.Music.BOSS_RANGE for boss in self.world.bosses):
            return "boss"
        if self.world.events.blood_intensity > 0:
            return "blood"
        now = pygame.time.get_ticks()
        pos = player.get_pos()
        near = c.Music.COMBAT_RANGE
        # A husk still wearing its villager is not a fight and must not sound like one: the
        # score giving it away would be a worse tell than anything on the sprite.
        hostile = any(m.revealed and m.distance_to_point(pos) < near for m in self.world.monsters) or any(
            npc.hostile and npc.distance_to_point(pos) < near for npc in self.world.npcs
        )
        if hostile:
            self._combat_until = now + c.Music.COMBAT_HOLD_MS
        if now < self._combat_until:
            return "combat"
        if self.world.underground is None and self.world.village_at(player.x, player.y) is not None:
            return "village"
        return "night" if self.world.daynight.darkness > 0.5 else "day"

    def _draw_frame(self):
        """The world, then the sky over it, then the HUD, then whatever menu is open. Drawn
        every frame whether or not the world moved, so a menu never sits over a stale view."""
        quest_target = self.world.quest_target(self.dialogue_manager.quest_tracker.tracked, self.player)
        self.game_renderer.draw_world(
            self.camera,
            self.world,
            self.player,
            self.interior,
            None if self.active_menu else self.interaction,
            quest_target,
        )
        # No sky underground: the tunnel draws its own darkness around the player instead.
        if self.world.underground is None:
            self.world.daynight.draw(self.screen, self.world.events.blood_intensity)
        # Underground or not: a blood night is on the world, and the tunnel is world space.
        draw_blood_veil(self.screen, self.world.events.blood_intensity)
        get_vignette().draw(self.screen)
        # Over the sky and the vignette, under the HUD: a blast's wash and a trap's jaws are
        # things happening to the world, not readouts.
        get_flash().draw(self.screen)
        get_trap_fx().draw(self.screen)
        get_banner().draw(self.screen)

        if not self.active_menu:
            self.game_renderer.draw_ui(
                len(self.player.inventory),
                self.player.coins,
                len(self.dialogue_manager.quest_system.active_quests),
                get_llm_tasks(),
                self.player,
                self.world,
                self.camera,
                self.last_save_ms,
                self.gate_lift,
                quest_target,
            )

        self.context_window.update()
        self.dialogue_manager.draw()
        if not self.active_menu:
            self.dialogue_manager.quest_tracker.draw(
                self.dialogue_manager.quest_system, self.game_renderer.minimap.content_bottom + 10
            )
            self.loot_notification.draw()
        self.inventory_menu.draw(self.player)
        self.quest_menu.draw(self.dialogue_manager.quest_system)
        self.shop_menu.draw()
        self.stats_menu.draw(self.player, self.record)
        self.help_menu.draw()
        self.pause_menu.draw()
        self.context_window.draw()
        # The world coming up out of the black the opening lore was written on. Last of all,
        # so it covers the HUD as well: nothing should be readable before the world.
        self.context_window.draw_fade()

        if not self.active_menu:
            self.game_renderer.draw_fps(self.clock.get_fps())
