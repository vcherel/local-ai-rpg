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
- `src/game/world.py`: `World` class, world entities (NPCs, monsters, items), AI context generation
- `src/game/events.py`: `EventSystem`, random world events (merchant, treasure, blood night, rumours, village crisis)
- `src/game/quest.py`: `Quest` dataclass (fetch/kill_mob/loot_mob/recover_stolen types), to_dict/from_dict (de)serialisation
- `src/game/loot.py`: `open_lootbox`, rolls coins/item from a lootbox rarity

### game/entities
- `src/game/entities/entities.py`: `Entity` base class (hp, damage, attack animation), `draw_human` sprite renderer
- `src/game/entities/player.py`: `Player(Entity)`, movement, inventory, equipment slots
- `src/game/entities/npcs.py`: `NPC(Entity)`, tracks per-NPC `affinity` (LLM-judged relationship level, feeds dialogue tone/quest rewards/shop prices)
- `src/game/entities/monsters.py`: `Monster(Entity)`, `pick_monster_kind` (spawn selection by distance from center)
- `src/game/entities/buildings.py`: `Building`, `generate_buildings`, `set_active_buildings`, town layout and building placement
- `src/game/entities/items.py`: `Item`, rarity rolling (`roll_rarity`, `rarity_tier`, `rarity_color`), `roll_bonus`, shape/polygon drawing for item icons
- `src/game/entities/stats.py`: `Stats` class, use-based character progression (xp, training, derived bonuses like attack/damage reduction/speed)

### llm
- `src/llm/llm_request_queue.py`: `LLMRequestQueue`, serialises all LLM calls onto a worker thread; use `generate_response_queued` / `generate_response_stream_queued`
- `src/llm/dialogue_manager.py`: `DialogueManager`, manages NPC dialogue window (streaming, quest detection and affinity analysis on close)
- `src/llm/quest_system.py`: `QuestSystem`, analyses conversation for quests, creates items, handles completion/rewards
- `src/llm/merchant_system.py`: `generate_shop_inventory`, asks the LLM for a shop's item list
- `src/llm/name_generator.py`: `NPCNameGenerator`, background-thread generation of NPC names ahead of time

### core
- `src/core/constants.py`: all game constants (screen size, player stats, LLM hyperparameters, colours, fonts)
- `src/core/save.py`: `SaveSystem`, JSON save system (keys: `context`, `coins`, `name`)
- `src/core/camera.py`: `Camera`, world to screen coordinate translation only
- `src/core/utils.py`: `ConversationHistory`, random color/coordinate helpers, `parse_shop_inventory` / `parse_response_quest_analysis` / `parse_response_affinity_analysis` (LLM response parsing)
- `src/core/dialogue_log.py`: `write_conversation`, persists finished NPC conversations to Markdown files under `logs/dialogues/`
- `src/core/llm_log.py`: `log_call`, appends every LLM generation (any category, streaming or not) as a JSON line to `logs/llm_calls.jsonl`, with prompts, response, duration, and token counts, for later quality/speed analysis
- `src/core/particles.py`: `Particle`, `ParticleSystem`, world-space particle bursts for combat/pickup feedback
- `src/core/audio.py`: `SoundManager`, procedural sound effects synthesised in memory (no audio asset files)

### ui
- `src/ui/game_renderer.py`: `GameRenderer`, draws the world, entities, camera-relative UI
- `src/ui/conversation_ui.py`: `ConversationUI`, dialogue text box rendering, scrolling, text input
- `src/ui/notification.py`: `QuestNotification`, `ToastNotification`, on-screen popups
- `src/ui/loading_indicator.py`: `LoadingIndicator`, spinner shown while the LLM is generating

### ui/menus
- `src/ui/menus/base_menu.py`: `BaseMenu`, shared menu scaffolding other menus subclass
- `src/ui/menus/main_menu.py`: `MainMenu`, `run_main_menu`, title screen / new-continue-quit
- `src/ui/menus/pause_menu.py`: `PauseMenu`
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
