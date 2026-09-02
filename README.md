# Local AI RPG

A 2D open-world RPG where **all AI runs locally on your machine**. No internet required. Talk freely with NPCs, get AI-generated quests, and explore a world where goals are created dynamically.

![Gameplay](assets/gameplay.png)

## Features

**AI**
- AI-generated conversations with any NPC, with an affinity system that tracks how each NPC feels about you and shifts dialogue tone, quest rewards, and shop prices
- Dynamic quest system: fetch, kill, loot drop, recover stolen item, clear a camp, steal, deliver and slay boss quests, generated from conversation or taken off a village notice board
- The world's lore, its settlement and landmark names, its bosses and its shop stock are all written by the model at run time

**World**
- Endless world: points of interest, villages and terrain stream in per chunk as you walk, so there is no edge to hit
- Villages of houses, shops and taverns you can walk inside, laid out round a plaza with lanes that join the roads outside, walled and gated by how far out they stand
- Wilderness landmarks: ruins to loot, shrines to find, bandit camps to clear and traveller camps to trade at and rest by
- Tunnels and caves under the map, reached by a village well or a cave mouth, lit only as far as the floor you can actually walk to
- Day/night cycle with villagers who go home and get into their own beds, weather that shortens sight rather than filtering the screen, and random world events (wandering merchants, treasure, rumors, blood nights, village crises)
- A minimap that only remembers ground you have actually walked

**Living in the world**
- Villages that warn you before they turn: every kind of offence has its own ladder, its own wording and its own visible countdown
- Turn one anyway and you can buy it back, at a blood price read off how big it is and how long its grudge has run
- Word travels: a deed fades with distance and time, and costs you a rung of warning and a surcharge at every shelf within earshot
- Blood nights send a raid at the settlement nearest you, and helping fight one off is the only thing that lifts a whole village's opinion at once

**Combat and progression**
- Two hands, one weapon in each: left button, right button, and a key to swap them over
- Melee and ranged side by side: weapon families (dagger, sword, axe, hammer, spear, staff, bow) each with their own reach, cadence and weight, plus arrows, mana, crits, knockback and cleave
- A shield worn on the offhand side, where the wedge it shows is the wedge that actually turns a blow, and a guard meter that breaks if you hide behind it
- Bombs in a slot of their own: a mine laid on the ground, a grenade thrown at the cursor
- Named multi-phase bosses that climb out of the ground, with telegraphed abilities and an enrage phase
- Loot with rarity tiers, rolled affixes (lifesteal, burn, thorns, execute and legendary-only signature effects), potions and timed buffs
- Use-based character progression: the stats you lean on are the ones that level
- Huntable wildlife, shops to buy and sell in, and a death that scatters some of what you carried where you fell for you to walk back and take

**Technical**
- Procedural sound effects and a chord pad score that answers what is happening around you
- Visual hit feedback: hit-stop, screen shake, blood decals drawn from the weapon that made the wound, floating damage
- Save and continue your game
- Runs on GTX 1650 and up

## Quick Start

### 1. Install system dependencies
```bash
sudo apt update
sudo apt install -y build-essential cmake python3.12-dev libomp-dev libopenblas-dev
```

### 2. Install uv (if not already installed)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Install llama-cpp-python

**With NVIDIA GPU** (recommended):
```bash
CMAKE_ARGS="-DGGML_CUDA=1 -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=75" \
uv pip install llama-cpp-python --force-reinstall --no-cache-dir
```

**Note**: Change `75` to your GPU architecture ([find yours here](https://developer.nvidia.com/cuda-gpus)). Need CUDA drivers? [Install guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/)

**CPU only** (slower):
```bash
uv pip install llama-cpp-python
```

### 4. Install dependencies
```bash
uv sync
```

### 5. Download AI Model
```bash
mkdir -p models
wget https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q2_K.gguf -P models/
```

Or download manually from [HuggingFace](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF) and put in `models/` folder.

### 6. Run
```bash
uv run game
```

## AI Model

**Qwen2.5-7B-Instruct**, quantized to Q2_K (~2.9GB), chosen so the whole model fits in the
GTX 1650's 4GB of VRAM. Full offload is the only criterion that matters here: a larger
model at a higher quant (Q4_K_M, say) writes better dialogue per token, but it does not
fit, and running it with some layers on the CPU is too slow to talk to. Within what fits,
more parameters at a lower quant beat fewer at a higher one.

It can be upgraded (a bigger model, or a higher quant) at the cost of VRAM and speed, most
likely back into partial CPU offload.
