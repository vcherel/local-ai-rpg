<div align="center">

# Local AI RPG

**A 2D open world RPG where every line of dialogue is written by an LLM running on your own GPU.**

Talk to anyone in your own words. Quests come out of the conversation. Nothing leaves your machine.

<img src="https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
<img src="https://img.shields.io/badge/engine-pygame-1f8b4c" alt="pygame">
<img src="https://img.shields.io/badge/LLM-Qwen2.5--7B%20(local)-8a3ffc" alt="Local LLM">
<img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">

<img src="assets/village.png" alt="Screenshot" width="100%">

</div>

- Conversations with villagers using a local LLM
- NPCs can give quests
- Full combat system
- Loot with rarities and stats evolution
- An endless generated world

<table>
<tr>
<td width="50%"><img src="assets/talk.png" alt="Screenshot"></td>
<td width="50%"><img src="assets/fight.png" alt="Screenshot"></td>
</tr>
<tr>
<td width="50%"><img src="assets/boss.png" alt="Screenshot"></td>
<td width="50%"><img src="assets/cave.png" alt="Screenshot"></td>
</tr>
<tr>
<td width="50%"><img src="assets/inventory.png" alt="Screenshot"></td>
<td width="50%"></td>
</tr>
</table>

## Play it

Two commands, any OS, no compiler and nothing to download but the repo.

```bash
git clone https://github.com/vcherel/local-ai-rpg.git
cd local-ai-rpg
uv sync
uv run game
```

(`uv` is the Python package manager this uses. It installs its own Python:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.)

That gives you the whole game with the AI turned off: villagers speak from a written bank of
lines, and quests come off the notice boards. Everything else, the world, the fighting, the
loot, is the real thing.

## Turn the AI on

For villagers who actually answer what you type, and quests written out of the conversation,
the game needs a model on your own machine. Linux, an NVIDIA GPU with 4GB of VRAM or more (a
GTX 1650 is enough), and CUDA drivers.

**1. System packages**

A compiler and the maths libraries, needed to build the piece that runs the model.

```bash
sudo apt update
sudo apt install -y build-essential cmake python3.12-dev libomp-dev libopenblas-dev
```

**2. llama-cpp-python, built for your GPU**

This is what runs the model. The version on PyPI is CPU only and fails quietly, slow and
never touching the card, so it is compiled here instead, which takes a few minutes. Replace
`75` with your card's [compute capability](https://developer.nvidia.com/cuda-gpus)
(75 is Turing: GTX 1650, RTX 20xx).

```bash
CMAKE_ARGS="-DGGML_CUDA=1 -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=75" \
uv pip install llama-cpp-python --force-reinstall --no-cache-dir
```

**3. The model** (~2.9GB)

The weights themselves, one file, downloaded into `models/`.

```bash
uv run fetch-model
```

**4. Check it**

Says what this machine has, and the exact command for whatever is missing. The two failures
worth catching are a build that never reaches the GPU and a model too big for the VRAM: both
of them otherwise look like the game simply being slow.

```bash
uv run doctor
```

```
[  ok  ] GPU: NVIDIA GeForce GTX 1650, 4096 MiB
[  ok  ] llama-cpp-python: 0.3.31, GPU offload available
[  ok  ] Model: models/Qwen2.5-7B-Instruct-Q2_K.gguf, 2.8GB
```

Then `uv run game` as before. The title screen says which of the two modes you are in.

## The model

**Qwen2.5-7B-Instruct**, quantized to Q2_K (~2.9GB), chosen so the whole thing fits in a
GTX 1650's 4GB of VRAM. Swap in a bigger model or a higher quant by dropping another GGUF in `models/`, at the cost
of VRAM and speed.

## License

MIT.
