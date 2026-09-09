# The game with no model: dialogue, names and lore come from llm/offline.py, so this image
# carries no CUDA, no llama-cpp-python and no weights. It draws to the host's X server.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /usr/local/bin/uv

# The pygame wheel bundles SDL2 but SDL loads these at runtime, and SysFont("dejavusans")
# finds nothing without fontconfig and the font itself: every menu is drawn in it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libx11-6 libxext6 libxrender1 libxrandr2 libxcursor1 libxi6 libxfixes3 \
        libasound2 libpulse0 libgl1 libglib2.0-0 \
        fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /game

# Pygame and numpy at the versions the lockfile pins, and the project itself deliberately
# not installed: its wheel carries only rpg_ai, so the game is run off src on the path.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && rm -rf /root/.cache/uv

COPY src ./src

# Saves, settings and logs are written to paths relative to the working directory, and the
# container runs as whatever uid started it so the X socket is readable. Neither directory
# can therefore be owned by anyone in particular.
RUN mkdir -p /game/saves /game/logs && chmod 777 /game/saves /game/logs

# HOME because SDL wants somewhere to write and /game is not it.
ENV HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/game/src \
    PATH=/game/.venv/bin:$PATH

ENTRYPOINT ["python", "-m", "rpg_ai"]
