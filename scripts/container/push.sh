#!/usr/bin/env bash
# Publish the built image to Docker Hub, which is the only place it is ever handed out
# from: the whole game as far as anybody else is concerned is play.sh, which pulls it.
set -euo pipefail

cd "$(dirname "$0")/../.."
IMAGE="${IMAGE:-vcherel/rpg-ai:offline}"
LATEST="${IMAGE%:*}:latest"

# The credentials, kept out of the repo in .env. A personal access token rather than the
# account password, so it can be revoked on its own.
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi
: "${DOCKERHUB_USER:?DOCKERHUB_USER is not set. Put it in .env}"
: "${DOCKERHUB_TOKEN:?DOCKERHUB_TOKEN is not set. Put it in .env}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "No image called $IMAGE. Build it first: scripts/container/build.sh" >&2
    exit 1
fi

printf '%s' "$DOCKERHUB_TOKEN" | docker login --username "$DOCKERHUB_USER" --password-stdin
docker tag "$IMAGE" "$LATEST"
docker push "$IMAGE"
docker push "$LATEST"

echo
echo "Published. Anyone with play.sh gets it on their next run, or by hand:"
echo "    docker pull $IMAGE"
