# rpg-ai

A 2D open-world RPG where all AI runs locally. NPCs generate dialogue via an LLM, quests are created dynamically from conversations, and the world context is AI-generated at startup.

## How to run

```bash
uv run game
```

Requires CUDA drivers and the model at `models/Qwen2.5-7B-Instruct-Q2_K.gguf`. See README for setup.

## File map

One line per file. Update this when adding, removing, or substantially repurposing a file, this list is what keeps lookups fast instead of requiring a codebase search.

`saves/save.json`: persisted game state (gitignored). `models/`: GGUF model files (gitignored).

### rpg_ai
- `src/rpg_ai/__main__.py`: entry point. Initialises Pygame, LLM queue, save system, then loops from main menu to game

### game
- `src/game/game.py`: `Game` class, main loop, input handling, state orchestration
- `src/game/world.py`: `World` class, world entities (NPCs, monsters, bosses, items), AI context generation, boss spawning (landmark guardian, roaming, quest) and per-frame boss updates; `persist_world` flushes generated state (context, shops, boss/landmark names) to disk the moment a background thread finishes it
- `src/game/events.py`: `EventSystem`, random world events (merchant, treasure, blood night, rumours, village crisis)
- `src/game/quest.py`: `Quest` dataclass (fetch/kill_mob/loot_mob/recover_stolen/slay_boss types), to_dict/from_dict (de)serialisation
- `src/game/loot.py`: `open_lootbox` rolls coins/item from a lootbox rarity; `break_crate` rolls the smaller coins/common-item reward from a smashed shop or tavern crate (coins credited straight away, the item left for the caller to drop on the floor)

### game/entities
- `src/game/entities/entities.py`: `Entity` base class (hp, damage, attack animation), `draw_human` sprite renderer
- `src/game/entities/player.py`: `Player(Entity)`, movement, inventory (`add_item` merges ammo stacks), equipment slots (`equip`/`is_upgrade`) split into separate melee and ranged weapon slots (a bow/staff and a sword can be equipped and carried at once, `_equip_slot` routes a weapon item by its archetype) plus armor/accessory, affix-effect helpers (crit/lifesteal/burn/execute/thorns/dodge/regen-still/coinfind/xpgain/pierce) each taking a `ranged` flag to read the matching weapon slot, `heal`, `gain_coins` (coin-find), thorns/dodge in `receive_damage`
- `src/game/entities/npcs.py`: `NPC(Entity)`, tracks per-NPC `affinity` (LLM-judged relationship level, feeds dialogue tone/quest rewards/shop prices)
- `src/game/entities/monsters.py`: `Monster(Entity)`, `pick_monster_kind` (spawn selection by distance from center), `apply_burn` + burn-tick state (weapon burn affix, ticked in `World.update`)
- `src/game/entities/boss.py`: `Boss(Monster)`, a named LLM-titled boss with an enrage phase and telegraphed abilities (slam AoE, hostile bolt volley, summon adds), knockback immune; spawned at the landmark, by roaming, by events and by slay_boss quests
- `src/game/entities/buildings.py`: `Building`, `generate_buildings`, `set_active_buildings`, town layout and building placement; shop and tavern crates are breakable (`break_crate_at`, per-crate `broken_crates` state, debris drawing); smashed crates can drop an item into per-building `dropped_items` (not persisted), picked up via `pickup_dropped_item`; `window_rects` gives the two windows flanking the door on every non-landmark building's facade, shatterable (`broken_windows` state, persisted)
- `src/game/entities/breakables.py`: `Breakable`, `generate_breakables`, outdoor props scattered near houses/shops/taverns (deterministic per building, weighted by kind): "barrel" smashes once for the same coin/item odds as a shop crate; "pot"/"bush" are pure decoration, no reward. Gone for good once smashed, no debris state (unlike interior crates)
- `src/game/entities/items.py`: `Item` (weapon/armor/accessory/ammo/misc; ammo stacks via `quantity`, misc are sellable "valuables" drawn as a coin), rarity rolling (`roll_rarity`, `rarity_tier`, `rarity_color`), `roll_bonus`, `roll_affixes`/`affix_label` (weapon/armor special effects stored in `Item.affixes`), expanded `ACCESSORY_FLAVORS` (+crit/lifesteal/coinfind/xpgain/pierce) with `ACCESSORY_FLAVOR_LABELS`, `base_value` (sell worth used by shop and inventory tooltip), shape/polygon drawing for item icons, `start_pop_anim` for a dropped item hopping out of its source and settling
- `src/game/entities/projectile.py`: `Projectile`, a fired arrow or magic bolt travelling in a straight line until it hits or runs out of range (`style`, `color`, `knockback`, `shake`, `hostile` for boss bolts that damage the player, `pierce`/`hit_ids` for the arrow-pierce accessory)
- `src/game/entities/stats.py`: `Stats` class, use-based character progression (xp, training, derived bonuses like attack/damage reduction/speed)

### llm
- `src/llm/llm_request_queue.py`: `LLMRequestQueue`, serialises all LLM calls onto a worker thread; use `generate_response_queued` / `generate_response_stream_queued`
- `src/llm/dialogue_manager.py`: `DialogueManager`, manages NPC dialogue window (streaming, quest detection and affinity analysis on close)
- `src/llm/quest_system.py`: `QuestSystem`, analyses conversation for quests, creates items, handles completion/rewards
- `src/llm/merchant_system.py`: `generate_shop_inventory`, asks the LLM for a shop's item list
- `src/llm/name_generator.py`: `NPCNameGenerator`, background-thread generation of NPC names ahead of time; persists the ready buffer and used-name history so a continued game reuses them instead of regenerating

### core
- `src/core/constants.py`: all game constants (screen size, player stats, LLM hyperparameters, colours, fonts); `WeaponArchetype` per-family combat feel (reach/swing/damage/cooldown/knockback/crit/cleave/shake) resolved by `weapon_archetype(name)`, plus `Combat` tuning; `Affixes` weapon/armor effect pools + rarity-scaled magnitudes and burn timing; `BossKind`/`BOSS_KINDS` archetype templates (brute/warlock/colossus) and `Boss` tuning (enrage, abilities, rewards, spawn caps, health bar)
- `src/core/save.py`: `SaveSystem`, atomic thread-safe JSON save system; background generators persist on completion via `save_all` (keys: `context`, `coins`, `name_buffer`, `used_names`, `breakables`, plus player/world state)
- `src/core/camera.py`: `Camera`, world to screen coordinate translation; `ScreenShake`/`get_shake` global camera-shake state applied in the translation
- `src/core/screen_fx.py`: `Hitstop`/`get_hitstop`, a brief freeze-frame (slows gameplay dt, not render dt) triggered on crits/kills/boss deaths; `HurtVignette`/`get_vignette`, a red screen-edge flash triggered when the player takes damage
- `src/core/daynight.py`: `DayNightCycle`, owned by `World` (`world.daynight`), tracks elapsed time within a repeating cycle and exposes `darkness`/`is_night`; `draw` overlays an ambient night tint outdoors (only, drawn from `Game.run()` next to `get_vignette().draw`), overridden by a fixed dark red tint during blood night regardless of time of day; `is_night` also speeds up monster respawn in `World.update` (weaker than, and not stacked with, the blood night respawn multiplier)
- `src/core/decals.py`: `Decal`, `DecalSystem`/`get_decals`, capped session-only ground blood splats (small on a hit, bigger "pool" on a kill), drawn beneath entities in both outdoor and interior rendering
- `src/core/floating_text.py`: `FloatingText`, `FloatingTextSystem`/`get_floating_text`, rising/fading damage numbers popping over a hit (bigger and gold on a crit)
- `src/core/utils.py`: `ConversationHistory`, random color/coordinate helpers, `parse_shop_inventory` / `parse_response_quest_analysis` / `parse_response_affinity_analysis` (LLM response parsing)
- `src/core/dialogue_log.py`: `write_conversation`, persists finished NPC conversations to Markdown files under `logs/dialogues/`
- `src/core/llm_log.py`: `log_call`, appends every LLM generation (any category, streaming or not) as a JSON line to `logs/llm_calls.jsonl`, with prompts, response, duration, and token counts, for later quality/speed analysis
- `src/core/particles.py`: `Particle`, `ParticleSystem`, world-space particle bursts for combat/pickup feedback; `spawn_burst` (omnidirectional) and `spawn_directional_burst` (cone away from an angle) both take an optional `gravity` (fake-z arc, so a particle launches up and settles back onto the ground plane instead of floating forever) and `shape` ("circle" or a rotating "shard", for wood/glass debris)
- `src/core/audio.py`: `SoundManager`, procedural sound effects synthesised in memory (no audio asset files)

### ui
- `src/ui/widgets.py`: shared menu/HUD draw primitives (flat square panels, buttons, slots, scaled item icons); all menus and the HUD draw through these for one consistent dark theme
- `src/ui/game_renderer.py`: `GameRenderer`, draws the world, entities, camera-relative UI
- `src/ui/conversation_ui.py`: `ConversationUI`, dialogue text box rendering, scrolling, text input
- `src/ui/notification.py`: `ToastNotification`, on-screen popups
- `src/ui/quest_tracker.py`: `QuestTracker`, permanent top right HUD widget showing one tracked quest in full plus swap chips for the rest, collapsible; owned by `DialogueManager` (`dialogue_manager.quest_tracker`), replaces the old slide-in "new quest" banner
- `src/ui/loading_indicator.py`: `LoadingIndicator`, spinner shown while the LLM is generating

### ui/menus
- `src/ui/menus/base_menu.py`: `BaseMenu`, shared menu scaffolding other menus subclass
- `src/ui/menus/main_menu.py`: `MainMenu`, `run_main_menu`, title screen / new-continue-quit
- `src/ui/menus/pause_menu.py`: `PauseMenu`, with a manual Save game button
- `src/ui/menus/context_menu.py`: `ContextMenu(BaseMenu)`, streaming popup for ambient/context LLM text
- `src/ui/menus/inventory_menu.py`: `InventoryMenu(BaseMenu)`, item list, equip/unequip
- `src/ui/menus/shop_menu.py`: `ShopMenu(BaseMenu)`, `_sell_price`, buy/sell UI and pricing (bartering stat and NPC affinity both swing prices)
- `src/ui/menus/quest_menu.py`: `QuestMenu(BaseMenu)`, active/completed quest list
- `src/ui/menus/stats_menu.py`: `StatsMenu(BaseMenu)`, character stats/progression display
- `src/ui/menus/help_menu.py`: `HelpMenu(BaseMenu)`, controls/help screen
- `src/ui/menus/game_over.py`: `run_game_over`, death screen

## Architecture notes

- The LLM runs on a background thread via `LLMRequestQueue`. Never call `llama_cpp` directly from the main thread.
- `src/` is the package root; all imports are relative to it (e.g. `from core.constants import ...`).
- No tests exist; skip the pre-push hook accordingly.
- Don't launch the game (`uv run game`, or any script that opens a pygame window) to verify a change, and don't ask Valentin to launch it and report back. It pops a real window on his live desktop. State what changed and stop; he'll test it himself if he wants to.
- To self-check a rendering/UI change, a throwaway script that imports just the drawing code, stubs out heavy objects, and renders to an offscreen `Surface`/PNG is fine, but set `SDL_VIDEODRIVER=dummy` before `pygame.init()` in it. Without that, `pygame.display.set_mode(...)` pops a real window on Valentin's desktop too, same problem as launching the game.
- Indoor and outdoor coordinates are the same regime as far as drawing and distance checks go. `Camera` is a pure translation (`world_to_screen` just subtracts camera pos and adds screen origin), and when the player is inside a building `Game` sets `player.x/y` to that building's local room coordinates and points the camera at them. So interior furniture, monsters, projectiles and items can call the exact same `camera.world_to_screen` / `distance_to_point` code paths outdoor entities use; nothing needs a separate indoor code path for positioning or drawing.
- Item persistence works by id: `SaveSystem` stores `inventory`/`equipped` as item id lists and `items` as the one master list of full item dicts (see the key list in `src/core/save.py`). Anything handed to the player has to end up in `world.items` or its id won't resolve on reload and the item silently vanishes. For items that are granted instantly (chest, lootbox) rather than picked up off the ground, they're appended already flagged `picked_up = True`, purely so the id resolves later; they never render or get picked up again.
- Interior-only state (`Game.indoor_monsters`, `Game.indoor_projectiles`, `Building.dropped_items`) is session-only and not written to the save file. A `Building` object itself lives for the whole process, so e.g. dropped crate loot survives leaving and re-entering the room, but not a save/reload.
- Particles, floating damage numbers and blood decals are each one global session-only system (`get_particles`/`get_floating_text`/`get_decals`), updated once per frame in `Game.run()` rather than inside `World.update` (which only runs outdoors), so both the outdoor and indoor branches animate them the same way. They're drawn in both `GameRenderer.draw_world` and `draw_interior`; nothing separates outdoor coordinates from a given building's interior coordinates for them, same as the general indoor/outdoor drawing note above.
- `Hitstop` (`core/screen_fx.py`) only slows the `dt` fed to gameplay updates (player/monster movement, `World.update`, projectiles); camera shake, particles, floating text and decals keep advancing on the real `dt` so the freeze reads as a snap rather than the whole frame stalling.
