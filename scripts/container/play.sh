#!/usr/bin/env bash
# Run the game from the image, with the plumbing a windowed program needs out of a
# container: the host's X socket, its cookie, its sound server, and a saves directory that
# outlives the container. Nothing here needs root.
set -euo pipefail

IMAGE="${IMAGE:-rpg-ai:offline}"
# Beside this script, so the whole game is one folder and deleting it leaves nothing behind.
SAVES="${SAVES:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/saves}"

if ! command -v docker >/dev/null; then
    echo "docker is not installed. On Ubuntu or Debian: sudo apt install docker.io" >&2
    exit 1
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "No image called $IMAGE. Load it first: docker load < rpg-ai-offline.tar.gz" >&2
    exit 1
fi
if [ -z "${DISPLAY:-}" ]; then
    echo "DISPLAY is not set, so there is no X server to draw on." >&2
    exit 1
fi

mkdir -p "$SAVES"
args=(
    --rm --interactive --tty
    --ipc=host                        # without it SDL's shared-memory blits fail
    --hostname "$(hostname)"          # the X cookie is looked up by host name
    --user "$(id -u):$(id -g)"
    --env DISPLAY
    --volume /tmp/.X11-unix:/tmp/.X11-unix:ro
    --volume "$SAVES:/game/saves"
)

# The cookie itself, wherever this session keeps it.
xauth_file="${XAUTHORITY:-$HOME/.Xauthority}"
if [ -f "$xauth_file" ]; then
    args+=(--volume "$xauth_file:/tmp/.Xauthority:ro" --env XAUTHORITY=/tmp/.Xauthority)
else
    echo "No X cookie found at $xauth_file. If the window is refused, allow this user once:"
    echo "    xhost +SI:localuser:$(id -un)"
fi

# Pulse or Pipewire's pulse socket if there is one; silence rather than a stalled ALSA
# probe if there is not. The game plays either way.
pulse="/run/user/$(id -u)/pulse/native"
if [ -S "$pulse" ]; then
    args+=(--volume "$pulse:/tmp/pulse-native" --env "PULSE_SERVER=unix:/tmp/pulse-native" --env SDL_AUDIODRIVER=pulse)
else
    args+=(--env SDL_AUDIODRIVER=dummy)
fi

echo "Saves are kept in $SAVES"
exec docker run "${args[@]}" "$IMAGE" "$@"
