#!/usr/bin/env bash
# The whole game. Fetches it the first time, then runs it on this machine's screen.
set -euo pipefail

IMAGE="${IMAGE:-vcherel/rpg-ai:offline}"
# Beside this script, so the game is one folder and deleting it leaves nothing behind.
SAVES="${SAVES:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/saves}"

command -v docker >/dev/null || { echo "docker is not installed. On Ubuntu: sudo apt install docker.io" >&2; exit 1; }
[ -n "${DISPLAY:-}" ] || { echo "DISPLAY is not set, so there is no screen to draw on." >&2; exit 1; }

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "First run: fetching the game. This happens once."
    docker pull "$IMAGE"
fi

mkdir -p "$SAVES"
args=(
    --rm --interactive --tty
    --ipc=host                    # without it SDL's shared-memory blits fail
    --hostname "$(hostname)"      # X looks its permissions up by host name
    --user "$(id -u):$(id -g)"
    --env DISPLAY
    --volume /tmp/.X11-unix:/tmp/.X11-unix:ro
    --volume "$SAVES:/game/saves"
)

# The secret X hands out to say who may draw on the screen, wherever this session keeps it.
xauth="${XAUTHORITY:-$HOME/.Xauthority}"
if [ -f "$xauth" ]; then
    args+=(--volume "$xauth:/tmp/.Xauthority:ro" --env XAUTHORITY=/tmp/.Xauthority)
else
    echo "No X cookie found. If the window is refused, run once: xhost +SI:localuser:$(id -un)"
fi

# Sound if this machine has any; silence rather than a stalled ALSA probe if it has not.
pulse="/run/user/$(id -u)/pulse/native"
if [ -S "$pulse" ]; then
    args+=(--volume "$pulse:/tmp/pulse" --env PULSE_SERVER=unix:/tmp/pulse --env SDL_AUDIODRIVER=pulse)
else
    args+=(--env SDL_AUDIODRIVER=dummy)
fi

exec docker run "${args[@]}" "$IMAGE" "$@"
