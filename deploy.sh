#!/usr/bin/env bash
# Deploy this project to the live docker folder on asgard.
# Usage: ./deploy.sh [--up]    (no flag = sync only; --up = sync + docker compose up -d --build)
# Project (git, dev) -> /mnt/cache/docker/artist-logo-generator (deployed product, no git).
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${DEPLOY_DIR:-/mnt/cache/docker/artist-logo-generator}"

[ -d "$DEST" ] || { echo "deploy dir $DEST missing" >&2; exit 1; }

# --inplace: Docker/fonts.txt is a single-file bind mount; a rename-replace would orphan the container's inode.
rsync -a --inplace --delete --chmod=D755,F644 --exclude '__pycache__/' --exclude '.claude/' "$SRC/Docker/" "$DEST/Docker/"
install -m 644 "$SRC/compose.yaml" "$DEST/compose.yaml"
# .env is never touched: it lives only in the deploy dir.
# compose.override.yaml (site-specific labels/networks) also lives only in the deploy dir.
[ -f "$DEST/compose.override.yaml" ] || echo "NOTE: $DEST/compose.override.yaml missing (optional; see compose.override.example.yaml)" >&2
[ -f "$DEST/.env" ] || echo "WARN: $DEST/.env missing (copy .env.example and fill in)" >&2

echo "synced $SRC -> $DEST"
if [ "${1:-}" = "--up" ]; then
  cd "$DEST"
  docker compose config -q
  docker compose build
  # The container runs as the unprivileged 'app' user. Named volumes created by the
  # earlier root-running image are root-owned; fix them once (no-op when already
  # correct). cap_drop is ALL in compose, so the helper re-adds just what chown needs.
  docker compose run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --entrypoint sh plex-artist-logos -c \
    'for d in /app/ArtistLogos /app/fonts /app/Logs /app/rembg_models; do [ "$(stat -c %U "$d")" = app ] || chown -R app:app "$d"; done'
  docker compose up -d
  docker compose ps
fi
