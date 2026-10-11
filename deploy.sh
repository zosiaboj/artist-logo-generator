#!/usr/bin/env bash
# Deploy this project to the live docker folder on asgard.
# Usage: ./deploy.sh [--up]    (no flag = sync only; --up = sync + docker compose up -d --build)
# Project (git, dev) -> /mnt/cache/docker/artist-logo-generator (deployed product, no git).
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${DEPLOY_DIR:-/mnt/cache/docker/artist-logo-generator}"

[ -d "$DEST" ] || { echo "deploy dir $DEST missing" >&2; exit 1; }

# --inplace: Docker/fonts.txt is a single-file bind mount; a rename-replace would orphan the container's inode.
rsync -a --inplace --delete --exclude '__pycache__/' --exclude '.claude/' "$SRC/Docker/" "$DEST/Docker/"
install -m 644 "$SRC/compose.yaml" "$DEST/compose.yaml"
# .env is never touched: it lives only in the deploy dir.
[ -f "$DEST/.env" ] || echo "WARN: $DEST/.env missing (copy .env.example and fill in)" >&2

echo "synced $SRC -> $DEST"
if [ "${1:-}" = "--up" ]; then
  cd "$DEST"
  docker compose config -q
  docker compose up -d --build
  docker compose ps
fi
