# rpg-ai

A 2D open-world RPG where all AI runs locally. NPCs generate dialogue via an LLM, quests are created dynamically from conversations, and the world context is AI-generated at startup.

## How to run

```bash
uv run game
```

Requires CUDA drivers and the model at `models/Qwen2.5-7B-Instruct-Q2_K.gguf`. See README for setup.

## Design notes

The rules behind the systems (why a village turns hostile as a whole, why a tunnel is ordinary world space, why healing is scarce) live in `docs/design/`, one file per subject with an index in `docs/design/README.md`. Read the one that covers what you are changing. This file holds the map and the short rules; that folder holds the reasoning.

## File map

One line per file, saying what it owns. Update this when adding, removing or substantially repurposing a file: this list is what keeps lookups fast instead of requiring a codebase search. Keep entries to a line; anything longer belongs in `docs/design/`.

`saves/save.json`: persisted game state (gitignored). `models/`: GGUF model files (gitignored).

### rpg_ai
- `src/rpg_ai/__main__.py`: entry point; Pygame and LLM queue setup, main menu to game loop, a fresh `SaveSystem` per session

### game
- `src/game/game.py`: `Game`, the main loop, input handling and state orchestration; `_handle_key` is the whole key map as one table, `_handle_left_click` dispatches HUD clicks by action, `current_interaction`/`_interact` are the one prompt and the one E, `_sweep_loot` the loot magnet, `save_data` the one path to disk, `_respawn` and `_sleep_until_dawn` the two things that move the player without walking
- `src/game/world.py`: `World`, the state everything reads (entity lists, buildings, shops, saving) plus the per-frame `update`; four jobs are mixed in from `combat.py`, `projectiles.py`, `streaming.py` and `places.py`. Also here: chunk-bucketed building/wall lookup, chase navigation (`chase_waypoint`, `_detour_corner`), `assign_surround_slots`, spawn caps and safe placement, terrain speed and line of sight, village defence orders, impulses and `unstick`
- `src/game/combat.py`: `WorldCombat`, every blow and its aftermath: `handle_attack`, the target-group table, cleave falloff, thrust lanes, knockback, crits, gore, weapon affixes and elements, breakables/windows/gates/props, bear traps, and `explode`
- `src/game/projectiles.py`: `WorldProjectiles`, everything in flight: `_fire_ranged` (mana, ammo, style), monster shots, and what each projectile strikes
- `src/game/places.py`: `WorldPlaces`, what the player does at a place once they have walked to it: camps, campfire rest, shrines, wells and caves, tunnels, theft and witnesses, village anger, directions and rumours, explored cells, `pass_time`
- `src/game/streaming.py`: `WorldStreaming`, how the map appears around the player: chunk load/unload, scenery reindexing, village creation, `prepare`, and the background naming/lore threads
- `src/game/events.py`: `EventSystem`, random world events (travelling merchant, treasure, blood night, rumours, village crisis); `blood_intensity` is the one number the blood night is read through
- `src/game/quest.py`: `Quest` dataclass (fetch/kill_mob/loot_mob/recover_stolen/slay_boss/clear_camp/steal/deliver) and its (de)serialisation; `COUNTED_QUEST_TYPES` is the one list of counter-finished types
- `src/game/loot.py`: every loot roll (lootbox, crate, POI cache, villager purse, quest reward, shop stock), all drawing from one `_roll_loot_item` table and taking the player's `loot_luck`

### game/entities
- `src/game/entities/entities.py`: `Entity` base (hp, damage, attack anim, `root`, `chill`), impulses and stagger, `push_apart`, `Gait` (the one walk cycle), `draw_human`
- `src/game/entities/gear.py`: drawing the gear a character visibly wears: weapon per hand by archetype, shield, armour ring, accessory gem
- `src/game/entities/player.py`: `Player`, movement, inventory and stacking, equip slots (two melee plus ranged, shield, armor, accessory, ammo), the weapon bar and potion quickbar, potions and buffs, mana, shield block, affix effects, death weakness, spawn grace, `gear()`
- `src/game/entities/npcs.py`: `NPC`, villagers: timed hostility and grudges, hunting/routing/stone throwing, the vision cone, militia and guard roles, weapons rolled off the home seed, affinity, shop stock and restock clock, wandering
- `src/game/entities/wander.py`: `Wander`, the idle-then-stroll movement shared by NPCs and critters
- `src/game/entities/monsters.py`: `Monster`, `pick_monster_kind` (spawn by distance, fading kinds out again), chasing and ring slots, steering, ranged kinds that keep distance, charge/flank/detonate behaviours, burn ticks
- `src/game/entities/monster_art.py`: the vector art per silhouette (`humanoid`, `goblin`, `hulk`, `skeleton`, `wraith`, `blob`, `beast`, `robed`, `creeper`) behind `draw_monster`; shadow, breath and eyes are shared by all of them
- `src/game/entities/boss.py`: `Boss(Monster)`, a named LLM-titled boss with an enrage phase and telegraphed abilities (slam, bolt volley, summons), knockback immune
- `src/game/entities/village.py`: `Village`, `village_site`, `generate_village`, `generate_starting_world`; grid layout round a plaza, `defences()` (wall, gates, towers, outworks), `tier`, `grounds_radius`
- `src/game/entities/buildings.py`: `Building`, one building's footprint (one rect or an L), facade offsets, interior layout and furniture, front door, windows, roof style; the footprint, floors and wall shell are worked out once and kept (`reset_geometry` drops them); `set_active_buildings`
- `src/game/entities/scenery.py`: the wilderness: per-chunk biome clumps, trees/boulders/ponds/grass, roads and footpaths, rivers and bridges, plus the collision and water indexes
- `src/game/entities/traps.py`: `BearTrap`, `traps_for_chunk`, the hunters' traps laid in a band around settlements; persisted only as which ones have shut
- `src/game/entities/tunnel.py`: `Tunnel`, `has_tunnel`, the rooms dug far out in world space, reached by a village well or a wilderness cave; floor-based collision, the exit shaft, and the player's own light
- `src/game/entities/breakables.py`: `Breakable`, `generate_breakables`, outdoor props near buildings (barrel, powder keg, planted decoration), each with persisted hp
- `src/game/entities/poi.py`: `PointOfInterest`, `pois_for_chunk`, `poi_site`, wilderness landmarks generated per chunk (ruins, shrine, camp, farmstead, graveyard, watchtower, stones, signpost, cave); only `state()` is saved
- `src/game/entities/critter.py`: `Critter`, `pick_critter_kind`, all wildlife: temperament-driven behaviour, fleeing with stamina, quadruped drawing
- `src/game/entities/items.py`: `Item` and everything about one: types, stacking, potions, rarity and affix rolling, accessory flavors, `base_value`, inventory sections, `icon_shape`, coin purses, the ground marker and magnet
- `src/game/entities/item_icons.py`: `draw_shape_with_border`, the vector art behind every item icon, one function per shape in `_SHAPES`
- `src/game/entities/projectile.py`: `Projectile`, an arrow/bolt/stone/boomerang in flight; hops no longer than it is wide, `hostile`/`by_player`/`over_walls`/`pierce` flags, boomerang return
- `src/game/entities/stats.py`: `Stats`, use-based progression (xp, training, derived bonuses, magic and swimming), queueing `pending_levelups`

### llm
- `src/llm/llm_request_queue.py`: `LLMRequestQueue`, all LLM calls serialised onto a worker thread, interactive categories first; `generate_response_queued` / `generate_response_stream_queued`, `poll=True` for the main thread, `llm_busy()`
- `src/llm/dialogue_manager.py`: `DialogueManager`, the NPC dialogue window: streaming replies, the merchant Shop button and purse, end-of-conversation detection, quest analysis on close
- `src/llm/quest_system.py`: `QuestSystem`, conversation analysis into quests, one `_build_*` per type and one completion hook per type, reward coins clamped into `QUEST_COIN_BANDS`
- `src/llm/merchant_system.py`: `generate_shop_inventories`, one batched call stocking every merchant in a town, with a local fallback per shop
- `src/llm/name_generator.py`: `NPCNameGenerator`, background NPC name generation buffered in the save
- `src/llm/death_taunts.py`: `DeathTauntGenerator`, the death-screen line, written ahead of need and buffered like names

### core
- `src/core/constants/`: all game constants in one flat namespace (`import core.constants as c`), split into `ui.py`, `player.py`, `combat.py`, `bestiary.py`, `world.py` and `items.py`, so a constant is filed by what it tunes. `Fonts` is the one name rebound at runtime by `__main__`
- `src/core/save.py`: `SaveSystem`, atomic thread-safe JSON saving; the key list at the top is the record of what the save owns
- `src/core/camera.py`: `Camera` world-to-screen translation plus `ScreenShake`/`get_shake`
- `src/core/screen_fx.py`: `Hitstop`, `HurtVignette`, `ScreenFlash` and `TrapSnap`, the four full-screen effects, all read once a frame in `Game.run`
- `src/core/damage_fx.py`: the flinch, flash and cracks drawn on a struck prop, keyed by string in a session-only registry
- `src/core/swing_arcs.py`: the trail a melee attack leaves, over exactly the wedge or lane the hit test accepts
- `src/core/impact_fx.py`: `ImpactRing`, the ring and bolts an area effect draws so several damage numbers have something visible behind them
- `src/core/daynight.py`: `DayNightCycle`, elapsed time in the cycle, `darkness`/`is_night`/`phase`/`time_until`, and the ambient night tint
- `src/core/decals.py`: capped session-only ground blood splats, including the directional `spawn_spray` a kill throws
- `src/core/floating_text.py`: rising damage numbers, bigger and gold on a crit
- `src/core/utils.py`: `ConversationHistory`, `frames(dt)` (the one definition of a delta in frames), random helpers, and the LLM response parsers
- `src/core/dialogue_log.py`: `write_conversation`, finished conversations written to `logs/dialogues/`
- `src/core/llm_log.py`: `log_call` / `log_parse_failure`, every generation appended to `logs/llm_calls.jsonl`
- `src/core/particles.py`: world-space particle bursts, omnidirectional or in a cone, with optional gravity and shard shapes
- `src/core/audio.py`: `SoundManager`, procedural sound effects synthesised in memory

### ui
- `src/ui/widgets.py`: shared menu/HUD draw primitives (panels, buttons, slots, icons), `EQUIP_SLOTS` as the one definition of the equip slots, `wrap_text`, `draw_scrollbar`
- `src/ui/game_renderer.py`: `GameRenderer`, drawing the world and the HUD: entities and buildings in range, the underground branch, health/mana/guard bars, potion bar and buff chips, equipped paper-doll, weapon bar, the icon dock (`dock_buttons` rows), witness cones, the one interaction prompt, the quest-target arrow, the save marker
- `src/ui/minimap.py`: `Minimap`, explored cells and what stands on them plus rumour marks, with the village-name and day/night strips under it; `content_bottom` is where whatever stacks below hangs from
- `src/ui/conversation_ui.py`: `ConversationUI`, the dialogue box: rendering, scrolling, text input, close button
- `src/ui/notification.py`: `ToastNotification`, word-wrapped on-screen popups
- `src/ui/quest_tracker.py`: `QuestTracker`, the HUD widget showing one tracked quest plus swap chips for the rest
- `src/ui/loading_indicator.py`: `LoadingIndicator`, the spinner shown while the LLM is generating

### ui/menus
- `src/ui/menus/base_menu.py`: `BaseMenu`, shared menu scaffolding and the reused dim overlay
- `src/ui/menus/menu_scene.py`: `MenuScene`, the live village the title screen stands over, rolled fresh per launch and holding no save and no player
- `src/ui/menus/main_menu.py`: `MainMenu`, `run_main_menu`, the title screen; returns "new_game"/"continue" and leaves save handling to `__main__`
- `src/ui/menus/pause_menu.py`: `PauseMenu`, with a manual Save game button
- `src/ui/menus/context_menu.py`: `ContextMenu`, the world lore: written onto black as an intro at session start, an ordinary panel when asked for with L
- `src/ui/menus/inventory_menu.py`: `InventoryMenu`, the sectioned item grid, equip/unequip, drinking a potion, right-click bar assignment, Equip best, the paper-doll and the hover tooltip
- `src/ui/menus/shop_menu.py`: `ShopMenu`, buy/sell with bartering and affinity pricing, restock countdown, bulk-sell buttons, two independently scrolling columns
- `src/ui/menus/quest_menu.py`: `QuestMenu`, the active/completed quest list
- `src/ui/menus/stats_menu.py`: `StatsMenu`, character stats and progression
- `src/ui/menus/help_menu.py`: `HelpMenu`, the controls screen; `CONTROLS` is the only written record of the key map
- `src/ui/menus/game_over.py`: `run_game_over`, the death screen: what killed the player, a taunt, the penalty and what Weakened costs

## Rules

The short version. `docs/design/` explains each of these.

- The LLM runs on a background thread via `LLMRequestQueue`. Never call `llama_cpp` directly from the main thread.
- `src/` is the package root; all imports are relative to it (e.g. `import core.constants as c`).
- No tests exist; skip the pre-push hook accordingly.
- Don't launch the game (`uv run game`, or any script that opens a pygame window) to verify a change, and don't ask Valentin to launch it. To self-check a rendering change, a throwaway script that renders to an offscreen `Surface` is fine, with `SDL_VIDEODRIVER=dummy` set before `pygame.init()`.
- `World` is one class split across four files by mixin (`world.py` state, `combat.py` blows, `streaming.py` the map, `places.py` what happens at a place). They share the same entity lists; pick the file by what you are changing, not by defaulting to `world.py`.
- The map is endless and deterministic, what stands on it is generated on demand and kept. Anything regenerated from a chunk seed must stay a pure function of `(cx, cy)`, with player changes in `World.poi_state`. Villages are the exception and go through `World._ensure_village`.
- Difficulty is distance from the world centre, pulled by three levers (which kinds, how many, what has a name). Nothing scales a monster's own stat block.
- The spawn point is protected three ways at once: nothing hostile spawned near it, the player placed by `safe_spot_near`, and `Death.SPAWN_GRACE_S` of grace.
- Healing is scarce and each source has one job (potion, campfire, bed, slow passive trickle). New healing goes through one of the four, not beside them.
- A crowd surrounds rather than queues: everything chasing one target goes through `World.assign_surround_slots`.
- Violence against a villager is a whole-settlement event through `WorldCombat._resolve_npc_hit`. Theft is the one exception and turns exactly one witness.
- Nothing the player did not do pays the player: `by_player=False` withholds every reward and consequence, never the kill.
- Nothing in the world breaks in a single hit, and every hit-point pool draws its own wear through `core/damage_fx.py`.
- A door (and a gate) is the only obstacle a chaser may break. If a monster cannot reach the player, the answer is navigation, not demolition.
- A weapon family answers a question rather than being a bigger number; a bigger number is a rarity roll.
- Exactly one interaction prompt is on screen at a time, drawn from `Game.current_interaction`.
- No boss is stood up near the start, on a settlement's grounds or on somebody's floor: every spawn goes through `World.boss_spawn_ok`.
- A quest sends the player out of town (`World.quest_target_spot`) and the walk is what the coins pay for (`quest_system.coin_band`).
- The minimap draws memory, not radar: explored cells only, plus rumour marks.
- Nothing walks the whole building list per frame; go through `buildings_near`/`buildings_in_range`.
- A monster's look is its kind's `shape`, an animal's behaviour is its `temperament`, an item's icon is derived from its name and type. Adding one means adding a table row, not a branch.
- Anything handed to the player must end up in `world.items` or its id will not resolve on reload.
