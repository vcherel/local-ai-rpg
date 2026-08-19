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
from core.particles import get_particles
from core.screen_fx import get_hitstop, get_vignette
from core.swing_arcs import get_swings
from game.entities.items import rarity_color, roll_rarity
from game.entities.player import Player
from game.loot import open_lootbox
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


class Interaction(NamedTuple):
    """What the interact key acts on right now, and the prompt drawn over it. `hint` is a
    second line for an extra key on the same target (a merchant's trade key)."""

    kind: str  # "npc" | "chest" | "bed" | "door" | "camp" | "shrine" |
    # "well" (climb down into the tunnel) | "ladder" (climb back out). Loot is not on this
    # list: it is collected by the magnet in Game._sweep_loot, never by a key.
    target: object
    label: str
    x: float
    y: float
    hint: str = ""


class Game:
    def __init__(self, screen, clock, save_system: SaveSystem):
        self.screen = screen
        self.clock: pygame.time.Clock = clock
        self.camera = Camera()

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

        self.save_system = save_system
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

        self.dialogue_manager = DialogueManager(self.screen, self.world.items, self.player, self.world.npcs)
        # slay_boss quests spawn their target through the world.
        self.dialogue_manager.quest_system.world = self.world
        # A quest handed in is worth a save of its own: it is the one thing in a session
        # that can't be earned back by walking the same ground again.
        self.dialogue_manager.quest_system.on_complete = self.save_data
        self.npc_name_generator = NPCNameGenerator(self.save_system)
        self.death_taunts = DeathTauntGenerator(self.save_system)
        self.active_menu = False
        # Set by the pause menu's "Quit to menu"; breaks the run loop so control
        # returns to the main menu (game state is saved on the way out).
        self.quit_to_menu = False
        # Set when the window is closed: the process exits instead of returning to the menu.
        self.quit_app = False

        # The building the player is currently standing inside, or None outdoors. Recomputed
        # every frame from the player's position; a building's interior is just its own
        # footprint in world space, so there is no separate coordinate space or mode switch.
        self.interior = None
        # What E would act on this frame (Game.current_interaction), recomputed each update
        # and drawn as the single on-screen prompt.
        self.interaction: Interaction | None = None

        self._restore_player_state()

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
                        if self.game_renderer.inv_button_rect.collidepoint(event.pos):
                            self.inventory_menu.toggle()

                        elif self.game_renderer.quest_button_rect.collidepoint(event.pos):
                            self.quest_menu.toggle()

                        elif self.dialogue_manager.quest_tracker.handle_event(
                            event, self.dialogue_manager.quest_system
                        ):
                            pass

                        elif self.game_renderer.stats_button_rect.collidepoint(event.pos):
                            self.stats_menu.toggle()

                        elif self.game_renderer.lore_button_rect.collidepoint(event.pos):
                            self._show_lore()

                        elif self.game_renderer.help_button_rect.collidepoint(event.pos):
                            self.help_menu.toggle()

                        elif self.game_renderer.pause_button_rect.collidepoint(event.pos):
                            self.pause_menu.toggle()

                        elif self.game_renderer.loading_indicator.rect.collidepoint(event.pos):
                            self.game_renderer.show_llm_tasks = not self.game_renderer.show_llm_tasks

                        else:
                            self.world.handle_attack(self.player, self.dialogue_manager.quest_system)

                    elif event.button == 3:  # Right click: ranged weapon
                        self.world.handle_attack(self.player, self.dialogue_manager.quest_system, ranged=True)

                if event.type == pygame.KEYDOWN:
                    self._handle_key(event)

        if self.dialogue_manager.shop_requested and not self.dialogue_manager.active:
            npc = self.dialogue_manager.current_npc
            if npc is not None and npc.is_merchant:
                self.shop_menu.open(npc, self.player, self.world.items)
            self.dialogue_manager.shop_requested = False

        return True

    def _handle_key(self, event):
        """One in-world key press. The two ranges (the weapon bar's number keys, the
        potion quickbar's letters) are checked first because they read the key rather than
        name it; everything else is a plain key to a method, and `HelpMenu.CONTROLS` is
        what tells the player about it."""
        if pygame.K_1 <= event.key <= pygame.K_1 + c.Player.WEAPON_SLOTS - 1:
            self._select_weapon(event.key - pygame.K_1)
            return
        if event.unicode.lower() in c.Potions.QUICK_KEYS:
            self._drink_quick_potion(c.Potions.QUICK_KEYS.index(event.unicode.lower()))
            return

        action = {
            pygame.K_e: self._interact,
            pygame.K_b: self._trade_nearby,
            pygame.K_f: self._equip_pending_upgrade,
            pygame.K_x: self._swap_melee,
            pygame.K_i: self.inventory_menu.toggle,
            pygame.K_j: self.quest_menu.toggle,
            pygame.K_c: self.stats_menu.toggle,
            pygame.K_l: self._show_lore,
            pygame.K_h: self.help_menu.toggle,
            pygame.K_m: self.game_renderer.minimap.toggle,
            pygame.K_p: self.pause_menu.toggle,
            pygame.K_ESCAPE: self.pause_menu.toggle,
        }.get(event.key)
        if action is not None:
            action()

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

    def _select_weapon(self, slot: int):
        """Draw the weapon on a number-key bar slot. It goes into the melee or the ranged
        slot depending on its archetype, so switching a bow never puts your sword away."""
        item = self.player.select_weapon(slot)
        if item is None:
            self.loot_notification.show(f"No weapon on slot {slot + 1}", c.Colors.MUTED)
            return
        hand = "ranged" if c.weapon_archetype(item.name).ranged else "melee"
        self.loot_notification.show(f"{item.name} ready ({hand})", rarity_color(item.rarity))

    def _swap_melee(self):
        """Switch to the other melee weapon. Both are worn; this is which one swings."""
        item = self.player.swap_melee()
        if item is None:
            self.loot_notification.show("No second melee weapon", c.Colors.MUTED)
            return
        self.loot_notification.show(f"{item.name} in hand", rarity_color(item.rarity))

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

        for building in self.world.buildings_near(self.player.x, self.player.y):
            if not building.has_door or building.door_broken:
                continue
            door = building.door_rect()
            dist = reach_of(door.centerx, door.centery)
            if dist <= c.Buildings.INTERACT_DISTANCE:
                label = "E: close the door" if building.door_open else "E: open the door"
                offer(Interaction("door", building, label, door.centerx, door.top - 10), dist)

        if self.world.underground is not None:
            # The one way back up, and the only thing to interact with down there besides
            # what is lying on the floor.
            tunnel = self.world.underground
            if tunnel.at_exit(self.player.x, self.player.y):
                offer(
                    Interaction("ladder", tunnel, "E: climb back up", *tunnel.entrance),
                    reach_of(*tunnel.entrance),
                )
        else:
            village = self.world.well_in_reach(self.player)
            if village is not None:
                # Deliberately not "climb down": which wells go anywhere is what walking over
                # to one is for, and a prompt that already knew would answer the question.
                offer(
                    Interaction("well", village, "E: look down the well", village.x, village.y - 40),
                    reach_of(village.x, village.y),
                )

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

        return None if best is None else best[1]

    def _interact(self):
        """Run whatever the on-screen prompt is offering."""
        interaction = self.current_interaction()
        if interaction is None:
            return
        if interaction.kind == "npc":
            self._talk_to(interaction.target)
        elif interaction.kind == "chest":
            self._open_interior_chest()
        elif interaction.kind == "bed":
            self._sleep_in_bed()
        elif interaction.kind == "door":
            self._use_door(interaction.target)
        elif interaction.kind == "well":
            self.world.enter_tunnel(self.player, interaction.target)
            self.save_data()
        elif interaction.kind == "ladder":
            self.world.leave_tunnel(self.player)
            self.save_data()
        elif interaction.kind == "camp":
            self.world.rest_at_camp(self.player, interaction.target)
        elif interaction.kind == "shrine":
            self.world.pray_at_shrine(self.player, interaction.target)

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
        pos = (self.player.x, self.player.y)
        for item in list(self.world.items):
            if item.picked_up:
                continue
            if item.distance_to_point(pos) > c.Player.MAGNET_RADIUS:
                item.magnet_speed = 0.0
                continue
            if self.world.building_at(item.x, item.y) is not self.interior:
                continue
            if item.magnet_toward(self.player.x, self.player.y, dt):
                self._pickup_world_item(item)

        if self.interior is not None:
            for item in list(self.interior.dropped_items):
                if item.distance_to_point(pos) > c.Player.MAGNET_RADIUS:
                    item.magnet_speed = 0.0
                    continue
                if item.magnet_toward(self.player.x, self.player.y, dt):
                    self._pickup_dropped_item(item)

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
            get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)
            return
        if item.item_type == "lootbox":
            self._open_lootbox(item)
            get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)
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
        get_particles().spawn_burst(item.x, item.y, item.color, count=12, speed=3, life=450, size=4)

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
        building.toggle_door()
        play_sound("door")
        if building.door_closed:
            # Never shut a door on oneself: standing in the gap when it swings to would wall
            # the player into the doorframe.
            self.player.x, self.player.y = self.world.free_spot_near(self.player.x, self.player.y, c.Player.SIZE / 2)

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
        self._check_witness()
        # A night is hours of world clocks moved on; nobody wants to sleep it twice.
        self.save_data()

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

    def _check_witness(self):
        """See whether anyone caught the player helping themselves in someone's house.

        The one place a single NPC turns hostile on their own: whoever saw it comes for the
        player, and the rest of the village never hears about it. Swinging back at them is
        what turns the whole settlement, through the usual `World.provoke_village`."""
        witness = self.world.theft_witness(self.player.x, self.player.y)
        if witness is None:
            return
        self.world.catch_thief(witness)
        # Nobody sees a task through for someone they are trying to kill.
        self.dialogue_manager.quest_system.remove_quest(witness)
        play_sound("player_hurt")

    def _save_from_menu(self):
        """Manual save from the pause menu, with an on-screen confirmation."""
        self.save_data()
        self.loot_notification.show("Game saved", c.Colors.GREEN)

    def _respawn(self):
        """Death has a real cost, not just a free full-heal at the same spot: dock coins,
        weaken the player for a while, and put them back at world spawn so they can't keep
        swinging at what killed them. The run carries on from there."""
        coins_lost = self.player.apply_death_penalty()
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
        self.update_camera()
        for system in (get_shake(), get_particles(), get_swings(), get_impacts()):
            system.update(dt)
        for system in (get_floating_text(), get_decals(), get_vignette()):
            system.update(dt)

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
        get_vignette().draw(self.screen)

        if not self.active_menu:
            self.game_renderer.draw_ui(
                len(self.player.inventory),
                self.player.coins,
                len(self.dialogue_manager.quest_system.active_quests),
                get_llm_tasks(),
                self.player,
                self.world,
                self.last_save_ms,
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
        self.stats_menu.draw(self.player)
        self.help_menu.draw()
        self.pause_menu.draw()
        self.context_window.draw()
        # The world coming up out of the black the opening lore was written on. Last of all,
        # so it covers the HUD as well: nothing should be readable before the world.
        self.context_window.draw_fade()

        if not self.active_menu:
            self.game_renderer.draw_fps(self.clock.get_fps())
