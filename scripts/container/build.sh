#!/usr/bin/env bash
# Build the offline image. Nothing is written to disk to send anybody: the image goes to
# Docker Hub with push.sh and play.sh fetches it from there.
set -euo pipefail

cd "$(dirname "$0")/../.."
IMAGE="${IMAGE:-vcherel/rpg-ai:offline}"

docker build --tag "$IMAGE" .

size=$(docker image inspect "$IMAGE" --format '{{.Size}}')
echo
echo "Built $IMAGE, $((size / 1048576))MB"
echo "Publish it:  scripts/container/push.sh"
