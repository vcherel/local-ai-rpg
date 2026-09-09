#!/usr/bin/env bash
# Build the offline image and write the two files a friend needs: the image as one
# loadable archive, and the script that runs it.
set -euo pipefail

cd "$(dirname "$0")/../.."
IMAGE="${IMAGE:-rpg-ai:offline}"
OUT="${OUT:-dist}"

docker build --tag "$IMAGE" .
mkdir -p "$OUT"
docker save "$IMAGE" | gzip -9 > "$OUT/rpg-ai-offline.tar.gz"
cp scripts/container/play.sh "$OUT/play.sh"
chmod +x "$OUT/play.sh"

echo
echo "Send both files from $OUT/:"
ls -lh "$OUT"
echo
echo "On his machine:  docker load < rpg-ai-offline.tar.gz  &&  ./play.sh"
