# Artist Logo Generator

Flask app (fork of an upstream repo) that builds 1000×1000 black-background JPEG artist logos for a Plex music library. Sources: fanart.tv, Metal Archives, Plex posters, or generated text logos (Google Fonts). Optionally pushes the result to Plex and can remove backgrounds with rembg. Runs only as a Docker container on asgard (host port 5005 → container 5000).

## Layout
- `Docker/app.py` — Flask routes, rate limits (flask-limiter), font download, rembg handling. Listens on `0.0.0.0:5000`.
- `Docker/logic.py` — image pipeline (`apply_transforms()`, `generate_text_logo()`).
- `Docker/plex_utils.py` — Plex, fanart.tv, MusicBrainz, Metal Archives helpers. Reads `PLEX_URL`/`PLEX_TOKEN`/`FANART_API_KEY` at import time.
- `Docker/templates/index.html`, `Docker/static/{js,css}` — single-page UI (`editor.js` is the controller). No JS build step; plain files.
- `Docker/fonts.txt` — Google Fonts families to pre-download (one per line, `#` comments). Restart the container after editing.
- `compose.yaml` (generic), `compose.override.example.yaml` (template for site wiring), `deploy.sh`, `.env.example` — deployment.

## Run / deploy
No tests, linter, or CI exist. Dependencies are pinned in `Docker/requirements.txt` (core) and `Docker/requirements-rembg.txt` (rembg/onnxruntime/numpy/scipy, installed only when the image is built with `INSTALL_REMBG=true`, which compose derives from `REMBG_ENABLED`; toggling it needs a rebuild). Python 3.11-slim, served by waitress (8 threads). Add new packages to the right requirements file.
- Syntax check: `python3 -m py_compile Docker/app.py Docker/logic.py Docker/plex_utils.py Docker/validation.py`
- Deploy: `./deploy.sh` syncs `Docker/` and `compose.yaml` to `/mnt/cache/docker/artist-logo-generator` on asgard. `./deploy.sh --up` also runs `docker compose config -q` and `docker compose up -d --build`. Run it on asgard or a host with that path. Override the target with `DEPLOY_DIR`.
- Site wiring is kept out of the repo: `compose.override.yaml` lives only in the deploy dir (git-ignored; `deploy.sh` never touches it) and holds the Sablier labels and `proxy` network. The override also drops the host port (`ports: !reset []`). The Traefik route is a file-provider entry in `/mnt/cache/docker/traefik/dynamic/sablier-artist-logos.yml` (`lan-only@file` then Sablier) pointing at `http://plex-artist-logos:5000` over the `proxy` network, not labels or port 5005. Don't put infra-specific labels in `compose.yaml`.
- Logs: `docker compose logs -f plex-artist-logos` (from the deploy dir).
- Env vars (see `.env.example`): `PLEX_URL`, `PLEX_TOKEN`, `FANART_API_KEY`, `LIBRARY_NAME` (compose hardcodes `Music`), `UPDATE_PLEX`, `REMBG_ENABLED`. Optional: `REMBG_CACHE_SIZE`, `REMBG_EAGER_WARMUP`.

## Conventions
- Commits use conventional prefixes: `feat:`, `fix:`, `perf:`, `chore:`, `compose:`.
- Routes take an artist `rating_key` and validate it with `.isdigit()`. Keep that check on new routes.
- External image fetches are limited to an allowlist (fanart.tv, metal-archives.com). Extend the allowlist rather than bypassing it.
- Artist state is flat files in `/app/ArtistLogos/<cleaned title>-<ratingKey>/` (`artist.jpg` plus `.status` = `none|custom|done`), stored in the `data` volume. Before the app first overwrites a Plex poster (`UPDATE_PLEX=true`, or `/set_poster`) it saves the poster Plex shows to `original.<ext>` + `original.json` in that dir (written once, never overwritten; backup failure aborts the change). `POST /revert_poster/<key>` restores it (re-selects the recorded Plex poster entry, else re-uploads the backup); `GET /original_poster/<key>` serves it; the UI shows "Revert to original" when it exists.
- Output is always 1000×1000 JPEG. `zoom` is ignored when `apply_default_size=True` (bulk apply).

## Pitfalls
- `.env` exists only in the deploy dir on asgard, never in this repo. `deploy.sh` never touches it. Don't read, print, or commit it.
- `deploy.sh` uses `rsync --inplace` on purpose: `fonts.txt` is a single-file bind mount, and a rename-replace would orphan the container's inode.
- `CLAUDE.md` and `.claude/` are gitignored and partly stale. It says the repo is a live mount of asgard and to deploy with `/deploy-to-asgard`, but `deploy.sh` is the current flow. Its security-issue list (path traversal, error disclosure, etc.) is an audit snapshot, so re-verify before assuming it's still open.
- Push only to the fork (`origin`). Never open PRs against `upstream`.
- Memory is tuned: `MALLOC_ARENA_MAX=2` in the Dockerfile and `mem_limit: 3g` in compose. Heavy image or rembg changes can hit the limit. rembg downloads a ~175 MB model on first start.
- Fonts come from the Google Fonts CSS API using an old Android UA to get single-file TTF. Don't change the UA, or you get unicode-range-split woff2 files.
- The service is Sablier-managed (labels in the deploy-dir override, `sablier.group=media-tools`) and idles to zero. A stopped container is normal, not a crash. The container is `cap_drop: ALL` with `no-new-privileges`, so new features that need privileges or writes outside the volumes will fail.
- Running git here may fail with "dubious ownership". Use `git -c safe.directory=$PWD ...`.
