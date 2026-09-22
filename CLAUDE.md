# rpg-ai

A 2D open-world RPG where all AI runs locally. NPCs generate dialogue via an LLM, quests are created dynamically from conversations, and the world context is AI-generated at startup.

## How to run

```bash
uv run game
```

Plays with no model at all (`llm/offline.py`). AI dialogue wants CUDA drivers, a hand built
`llama-cpp-python` and the model at `models/Qwen2.5-7B-Instruct-Q2_K.gguf`: `uv run fetch-model`
downloads it, `uv run doctor` says what a machine is missing. See README for setup. The binding is
installed by hand and unlocked, so never run a plain `uv sync` here: it strips it. Use `uv sync --inexact`.

## Design notes

The rules behind the systems (why a village turns hostile as a whole, why a tunnel is ordinary world space, why healing is scarce) live in `docs/design/`, one file per subject with an index in `docs/design/README.md`. Read the one that covers what you are changing. Each file ends with a Rules section: the invariants of that subject, read before changing it. This file holds the map and the engineering rules that apply everywhere.

## File map

One line per file, saying what it owns. Update this when adding, removing or substantially repurposing a file: this list is what keeps lookups fast instead of requiring a codebase search. Keep entries to a line; anything longer belongs in `docs/design/`.

`saves/save.json`: persisted game state (gitignored). `saves/llm_probe.json`: what `uv run doctor` last found out about this machine's ability to generate (gitignored). `models/`: GGUF model files (gitignored).

### scripts/verify
How a change here is checked, all headless and none of them loading the model. `scripts/verify/README.md` says what is reproducible and what is not.
- `scripts/verify/harness.py`: `boot()`, a real `Game` on dummy SDL with the LLM stubbed and a virtual clock; `step()` is one frame
- `scripts/verify/refs.py`: every module parses and every `self.x()` names something defined in `src`
- `scripts/verify/smoke.py`: N frames, then checks the world for non-finite coordinates, bad hp, orphan items
- `scripts/verify/render.py`: the fixed shots, drawn offscreen to PNG
- `scripts/verify/render_diff.py`: those shots on this tree against a git ref, pixel by pixel
- `scripts/verify/frame_profile.py`: update/draw split, frame percentiles, then a cProfile table
- `scripts/verify/spawn_rates.py`: what `pick_monster_kind` rolls per distance band
- `scripts/verify/shots.py`: regenerates the README's pictures; not a check

### Container
How the game is handed to somebody who will not install it. Offline only: no CUDA, no llama-cpp-python, no weights.
- `Dockerfile`: the image, running off `src` on `PYTHONPATH`
- `.dockerignore`: what never goes in (weights, saves, logs, screenshots)
- `scripts/container/build.sh`: builds the image
- `scripts/container/push.sh`: publishes it to `vcherel/rpg-ai` with the token in `.env`
- `scripts/container/play.sh`: the one file another machine needs to pull and run it

### rpg_ai
- `src/rpg_ai/__main__.py`: entry point; pygame and LLM queue setup, loading screen, main menu to game loop
- `src/rpg_ai/fetch_model.py`: `uv run fetch-model`, downloads the weights into `models/`
- `src/rpg_ai/doctor.py`: `uv run doctor`, what this machine can run and the command for what it cannot

### game
- `src/game/game.py`: `Game`, the main loop, input handling and the key/dock/interact action tables
- `src/game/interactions.py`: `Interaction` and `GameInteractions`, the single E prompt on screen
- `src/game/sleeping.py`: `GameSleep`, a night in a bed: its prompt, its refusals and the fade to morning
- `src/game/world.py`: `World`, the shared state (entity lists, buildings, saving) and the per-frame `update`
- `src/game/combat.py`: `WorldCombat`, every blow against a body and its aftermath
- `src/game/breaking.py`: `WorldBreaking`, blows against the built world (scenery, props, windows, doors)
- `src/game/gore.py`: `WorldGore`, what a blow looks like where it landed (blood, hit feedback, damage numbers)
- `src/game/explosives.py`: `WorldExplosives`, bombs, creepers, and the one `explode`
- `src/game/projectiles.py`: `WorldProjectiles`, everything in flight
- `src/game/places.py`: `WorldPlaces`, camps, campfires, shrines, wells, caves and tunnels
- `src/game/social.py`: `WorldSocial`, warnings, anger, amends, notoriety, raids, notice boards
- `src/game/witnesses.py`: `WorldWitnesses`, sight, crime witnesses, reports and hush money
- `src/game/bosses.py`: `WorldBosses`, where and how often a boss is stood up, quest bosses
- `src/game/shops.py`: `WorldShops`, merchant stock and restocking
- `src/game/streaming.py`: `WorldStreaming`, chunk load/unload and the scenery indexes
- `src/game/spawning.py`: `WorldSpawning`, population caps and safe placement
- `src/game/navigation.py`: `WorldNavigation`, line of sight, walls, chase waypoints and detours
- `src/game/villagers.py`: `WorldVillagers`, every villager's frame: mob and militia orders, fighting, fleeing, curfew
- `src/game/blow.py`: `Blow`, how one blow landed, the value every damage path passes
- `src/game/events.py`: `EventSystem`, random world events (merchant, treasure, blood night, rumours, crisis)
- `src/game/quest.py`: `Quest` dataclass and its serialisation
- `src/game/record.py`: `Record`, the playthrough tally and its milestones
- `src/game/loot.py`: every loot roll, all drawing from one `_roll_loot_item` table

### game/entities
- `src/game/entities/entities.py`: `Statuses` (damage and status effects) and `Entity`
- `src/game/entities/gear.py`: drawing the gear a character visibly wears
- `src/game/entities/player.py`: `Player`, movement, inventory, equip slots, hands
- `src/game/entities/player_bonuses.py`: `PlayerBonuses`, every number gear, accessories and buffs are worth
- `src/game/entities/npcs.py`: `NPC`, villagers: hostility, grudges, warnings, surrender, bedtime
- `src/game/entities/wander.py`: `Wander`, idle then stroll movement shared by NPCs, critters and idle monsters
- `src/game/entities/monsters.py`: `Monster`, `pick_monster_kind`, chasing, steering and monster behaviours
- `src/game/entities/monster_art.py`: vector art per monster silhouette behind `draw_monster`
- `src/game/entities/boss.py`: `Boss(Monster)`, rising, enrage, shrinking and telegraphed attacks
- `src/game/entities/village.py`: `Village`, one settlement: defences, gates, night shutting
- `src/game/entities/village_art.py`: `VillageArt`, a settlement's look (plaza, lanes, walls)
- `src/game/entities/village_layout.py`: a settlement's composition as pure arithmetic over a seed
- `src/game/entities/village_sites.py`: where settlements stand on the endless map
- `src/game/entities/village_streets.py`: `StreetGrid`, the lane network inside one settlement
- `src/game/entities/village_generation.py`: `generate_village` and `generate_starting_world`
- `src/game/entities/buildings.py`: `Building`, footprint, interior, furniture, doors, locks
- `src/game/entities/building_art.py`: `BuildingArt`, a building's look
- `src/game/entities/scenery.py`: `Scenery`, one piece of wilderness (tree, boulder, pond, road, bridge, grass)
- `src/game/entities/terrain.py`: biomes, roads, footpaths, rivers and their crossings per chunk
- `src/game/entities/traps.py`: `BearTrap`, hunters' traps around settlements
- `src/game/entities/tunnel.py`: `Tunnel`, underground rooms reached by a well or a cave
- `src/game/entities/bomb.py`: `Bomb`, the mine and the grenade
- `src/game/entities/breakables.py`: `Breakable`, outdoor props near buildings with persisted hp
- `src/game/entities/poi.py`: `PointOfInterest`, wilderness landmarks per chunk
- `src/game/entities/critter.py`: `Critter`, all wildlife
- `src/game/entities/items.py`: `Item`, types, stacking, rarity, affixes, value, icons
- `src/game/entities/item_icons.py`: vector art behind every item icon
- `src/game/entities/projectile.py`: `Projectile`, anything in flight and its flags
- `src/game/entities/stats.py`: `Stats`, use based progression and level ups

### llm
- `src/llm/llm_request_queue.py`: `LLMRequestQueue`, every LLM call serialised onto a worker thread
- `src/llm/decide.py`: `decide`, the model picking one of a few labelled answers
- `src/llm/fit.py`: sizing the model to the GPU by arithmetic, never by trial
- `src/llm/preflight.py`: whether this install can generate at all, without crashing to find out
- `src/llm/offline.py`: the no model answers, one per LLM category
- `src/llm/dialogue_manager.py`: `DialogueManager`, the NPC dialogue window and the decisions read off each line
- `src/llm/quest_system.py`: `QuestSystem`, conversations into quests, one builder and completion hook per type
- `src/llm/merchant_system.py`: `generate_shop_inventories`, one batched call per town
- `src/llm/name_generator.py`: `NPCNameGenerator`, buffered background name generation
- `src/llm/death_taunts.py`: `DeathTauntGenerator`, the buffered death screen line

### core
- `src/core/constants/`: all game constants in one namespace (`import core.constants as c`), split by subject
- `src/core/save.py`: `SaveSystem`, atomic JSON saving; its key list is what the save owns
- `src/core/settings.py`: `Settings`, preferences that outlive a playthrough
- `src/core/camera.py`: `Camera` and screen shake
- `src/core/screen_fx.py`: full screen effects (hitstop, vignettes, flashes, banners) and `Overlay`
- `src/core/damage_fx.py`: the flinch, flash and cracks on a struck prop
- `src/core/swing_arcs.py`: the trail a melee attack leaves
- `src/core/impact_fx.py`: `ImpactPulse`, the visible wave of an area effect
- `src/core/daynight.py`: `DayNightCycle`, time of day, curfew and the night tint
- `src/core/weather.py`: `WeatherSystem`, rain and fog
- `src/core/decals.py`: ground blood splats, one recipe per weapon family
- `src/core/floating_text.py`: rising damage numbers
- `src/core/mainthread.py`: `post`/`drain`, how a worker thread changes the world
- `src/core/utils.py`: `ConversationHistory`, `frames(dt)`, random helpers, LLM response parsers
- `src/core/dialogue_log.py`: finished conversations written to `logs/dialogues/`
- `src/core/llm_log.py`: every generation appended to `logs/llm_calls.jsonl`
- `src/core/particles.py`: world space particle bursts
- `src/core/audio.py`: `SoundManager`, procedural sound effects
- `src/core/music.py`: `MusicPlayer`, a chord pad per context, rendered up front
- `src/core/status_fx.py`: particles around anything carrying a timed effect
- `src/core/text_fx.py`: outlined world space text

### ui
- `src/ui/widgets.py`: shared menu and HUD draw primitives and the equip slot definitions
- `src/ui/game_renderer.py`: `GameRenderer`, drawing the world and the HUD
- `src/ui/minimap.py`: `Minimap` and the status strips under it
- `src/ui/conversation_ui.py`: `ConversationUI`, the dialogue box
- `src/ui/notification.py`: `ToastNotification`, on screen popups
- `src/ui/quest_tracker.py`: `QuestTracker`, the HUD quest widget
- `src/ui/loading_indicator.py`: the spinner while the LLM generates

### ui/menus
- `src/ui/menus/base_menu.py`: `BaseMenu`, shared menu scaffolding and the one click action keys
- `src/ui/menus/menu_scene.py`: `MenuScene`, the live village behind the title screen
- `src/ui/menus/main_menu.py`: `MainMenu`, the title screen
- `src/ui/menus/pause_menu.py`: `PauseMenu`, save, sound and keyboard layout toggles
- `src/ui/menus/context_menu.py`: `ContextMenu`, the world lore
- `src/ui/menus/inventory_menu.py`: `InventoryMenu`, the item grid, equipping and the paper doll
- `src/ui/menus/shop_menu.py`: `ShopMenu`, buying, selling and bartering
- `src/ui/menus/board_menu.py`: `BoardMenu`, a settlement's notice board
- `src/ui/menus/quest_menu.py`: `QuestMenu`, active and completed quests
- `src/ui/menus/stats_menu.py`: `StatsMenu`, stats, progression and the playthrough tally
- `src/ui/menus/help_menu.py`: `HelpMenu`; `CONTROLS` is the only record of the key map
- `src/ui/menus/game_over.py`: `run_game_over`, the death screen

## Rules

Engineering rules that apply to every change. The game design rules are in the Rules section of each `docs/design/` file.

- The LLM runs on a background thread via `LLMRequestQueue`. Never call `llama_cpp` directly from the main thread. And a worker never touches the world: what it does with the model's answer is posted through `core/mainthread.py` and runs on the next frame, because a list or a dict the frame is walking is not one a thread may grow, and a payout that ran on a worker could be run twice.
- A CUDA failure is an abort, so what can be known about it beforehand is known beforehand and for nothing. llama.cpp writes a line and calls `abort()`, which no `except` survives: a build compiled for another card would take the game down at the first villager, and it says which cards it was built for, so it is asked (`preflight.blocking_warning`) and never loaded. Everything else is arithmetic: `llm/fit.py` sizes the context and the layers off the card's free VRAM and the model's own header, and the game loads once on the result. A launch never spends a model load to prove a model loads; `uv run doctor` is where a real generation is paid for, and its verdict is read back here for free.
- When the game needs a choice rather than text, it asks for a decision (`llm/decide.py`, `docs/design/decisions.md`): a few lettered answers, the model's odds over them read off one pass, a draw from those odds, and the number it is worth decided by code. Every decision carries its own `offline` odds, so it has an answer with no model. Judgements about the player are asked of the model as an onlooker, not in the voice of an angry NPC, which found nothing convincing.
- The model is optional and the game is whole without it. `llama-cpp-python` is not a dependency (the wheel PyPI resolves to is CPU only and fails silently) and neither are the weights: `model_available()` decides once per session, and with no model every call in the queue is answered by `llm/offline.py`, one local answer per category. A new LLM call is a new row there, not a new place that assumes a model.
- A frame builds at most `World.CHUNK_LOADS_PER_FRAME` steps of chunk, nearest first, and stops starting them once it has spent `World.CHUNK_BUILD_BUDGET_MS`, except on ground the player could walk onto (`World.CHUNK_URGENT_RADIUS`). A chunk is two steps, its ground and then its wilderness, because a settlement and a wood in one update is what a border crossing is felt as. `prepare` is the exception on both counts, because nothing is on screen yet.
- What the wilderness is looked up through is kept up as it arrives, never rebuilt: a chunk files its own pieces (`WorldStreaming._index_scenery`) and takes them away again with itself, and anything that changes what a piece blocks goes back through `rework_scenery`. Walking the whole held wilderness to rebuild four indexes was most of what a border crossing cost.
- Nothing heavy runs in Python on a background thread while the world is being drawn. Every pygame call on the main thread lets go of the GIL and has to take it back, so a worker doing arithmetic costs the frame a switch interval per call: rendering one music pad on demand took the frame from 16 ms to 85 ms. Work that has to be done in the background is done before the player has control (the pads, on the loading screen) or not at all; the model's own threads are waiting on C, which is the case this is not about.
- `src/` is the package root; all imports are relative to it (e.g. `import core.constants as c`).
- Verify before committing, always through `scripts/verify/`: `refs.py` and `smoke.py` after any multi-file change, `render_diff.py` after anything that draws, `frame_profile.py` on both sides of a performance claim. Report what they printed rather than that they passed. There is no pytest suite: `refs.py` and `smoke.py` are what the pre-push hook runs, so a push is the one place they are not optional.
- Don't launch the game (`uv run game`, or any script that opens a pygame window) to verify a change, and don't ask Valentin to launch it. To self-check a rendering change, a throwaway script that renders to an offscreen `Surface` is fine, with `SDL_VIDEODRIVER=dummy` set before `pygame.init()`.
- `World` is one class split across files by mixin (`world.py` state, `combat.py` blows against a body, `breaking.py` blows against the built world, `explosives.py` blasts, `projectiles.py` what is in flight, `streaming.py` the map, `places.py` what happens at a place, `social.py` what a settlement thinks of the player, `witnesses.py` who saw the player do it, `bosses.py` standing one up, `shops.py` the shelves, `navigation.py` getting there, `spawning.py` keeping the ground populated, `villagers.py` what a villager does with their frame). They share the same entity lists; pick the file by what you are changing, not by defaulting to `world.py`.
- The map is endless and deterministic, what stands on it is generated on demand and kept. Anything regenerated from a chunk seed must stay a pure function of `(cx, cy)`, with player changes in `World.poi_state`. Villages are the exception and go through `World._ensure_village`. A building is named off its settlement's chunk and its slot, never off a fresh uuid, since its wing and its roof are rolled from that name and its wing is what its neighbour is shoved off: a random name would lay the same seed's houses down in different places in each process.
- Exactly one interaction prompt is on screen at a time, drawn from `Game.current_interaction`.
- A playthrough goes in the save, a preference goes in `core/settings.py`: New game wipes one and must not touch the other.
- Nothing walks the whole building list per frame; go through `buildings_near`/`buildings_in_range`. The same rule for what is drawn: a frame asks for the chunks it can see (`floor_details_in_range`, `scenery_*_in_range`) and measures the rest against the view before drawing it.
- What holds still is painted once and kept: a building's walls and roof (`BuildingArt._shell`, dropped by `reset_geometry`), a body facing up its own sprite (`_body_sprite`, keyed on everything it is made of with the stride and the swing in whole steps), a full-screen effect and the sky over it (`screen_fx.Overlay`, keyed on the one number that shapes it, in steps no coarser than the effect itself). What changes is drawn live over the top, in the order it always was.
- A tunable is a constant, a shade of paint is not: every number that changes how the game plays or reads goes in `core/constants/`, but the vector art files (`building_art.py`, `poi.py`, `scenery.py`, `breakables.py`) keep their shades inline, because a colour that exists only inside one silhouette is the drawing rather than a dial.
- A monster's look is its kind's `shape`, an animal's behaviour is its `temperament`, an item's icon is derived from its name and type. Adding one means adding a table row, not a branch.
- Anything handed to the player must end up in `world.items` or its id will not resolve on reload.
