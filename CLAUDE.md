# rpg-ai

A 2D open-world RPG where all AI runs locally. NPCs generate dialogue via an LLM, quests are created dynamically from conversations, and the world context is AI-generated at startup.

## How to run

```bash
uv run python src/main.py
```

Requires CUDA drivers and the model at `models/Qwen2.5-3B-Instruct-Q4_K_M.gguf`. See README for setup.

## Key files

- `src/main.py`: entry point. Initialises Pygame, LLM queue, save system, then loops from main menu to game
- `src/game/game.py`: main game loop, input handling, state orchestration
- `src/game/world.py`: world entities (NPCs, monsters, items), context generation
- `src/llm/llm_request_queue.py`: serialises all LLM calls onto a worker thread; use `generate_response_queued` / `generate_response_stream_queued`
- `src/llm/dialogue_manager.py`: manages NPC dialogue window (streaming, quest detection on close)
- `src/llm/quest_system.py`: analyses conversation for quests, creates items, handles completion/rewards
- `src/core/constants.py`: all game constants (screen size, player stats, LLM hyperparameters, colours, fonts)
- `src/core/save.py`: JSON save system (keys: `context`, `coins`, `name`)
- `saves/save.json`: persisted game state (gitignored)
- `models/`: GGUF model files (gitignored)

## Architecture notes

- The LLM runs on a background thread via `LLMRequestQueue`. Never call `llama_cpp` directly from the main thread.
- `src/` is the package root; all imports are relative to it (e.g. `from core.constants import ...`).
- No tests exist; skip the pre-push hook accordingly.
