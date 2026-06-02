# Artist Logo Generator

A lightweight web UI and backend for browsing, editing and setting artist posters/logos in a Plex (music) library. It provides multiple logo sources:
- **fanart.tv** — HD clearLOGO's via the fanart.tv API
- **Metal Archives** — Band logos for metal/rock artists via MusicBrainz MBID lookup and Metal Archives image resolution
- **Custom text logos** — Generate logos using fonts from Google Fonts

The logos can either be set manually, artist by artist, or in bulk by using the most popular fanart.tv logo for each artist.

By default the tool will leave margins on all sides of the logo so that it'll look good both on desktop and mobile. This can however be overridden with the zoom slider.

The tool is able to invert the logo (useful if it's black with white outlines for example), change the contrast, add a white mask or a tints of colours. You can also upload logos and edit and save them using this app.

I was inspired by [this](https://github.com/LemonFaceSour/BandLogos) repo but wanted something that was able to set logos for all my artists, which is why I created this tool. I'm sharing it here since I figured other people might want to do the same, but I'm not planning on adding more features, fixing any issues, or maintaining it more than for my own use in the future.

## Fork Changes: Metal Archives Pipeline + Security Hardening

This fork adds the Metal Archives logo pipeline alongside important security improvements and performance enhancements:

### New: Metal Archives Pipeline
- **Metal Archives logo source**: Artists with MusicBrainz IDs can now retrieve band logos from Metal Archives by:
  1. Looking up MusicBrainz MBID from Plex artist metadata
  2. Querying MusicBrainz for Metal Archives relations
  3. Probing Metal Archives for available logo image files (`.jpg`, `.png`, `.gif`, etc.)
  4. Returning accessible logos to the frontend
- **MusicBrainz caching**: Responses are cached per MBID to avoid redundant API calls.
- **Rate limiting**: MusicBrainz requests are rate-limited to 1 request/second to comply with API requirements.
- **Improved API headers**: Includes proper User-Agent header for better compatibility.

### Security
- **SSRF protection**: External image proxy validates against an allowlist (`fanart.tv`, `metal-archives.com`) to prevent Server-Side Request Forgery attacks.
- **Input validation**: All endpoints validate `rating_key` parameters (must be numeric) and required fields before processing.
- **URL validation**: All URLs parsed and validated before being used in requests or returned to clients.
- **Better error handling**: More specific exception handling with logging for network errors and API failures. 

# Screenshots
*fanart.tv view*
![alt text](https://github.com/joakimkingstrom/artist-logo-generator/blob/main/screenshots/SCR-20260205-uggm.png)
*browse existing artist pictures from plex with the ability to save*
![alt text](https://github.com/joakimkingstrom/artist-logo-generator/blob/main/screenshots/SCR-20260205-ugle.png)
*text generator view*
![alt text](https://github.com/joakimkingstrom/artist-logo-generator/blob/main/screenshots/SCR-20260205-ugsl.png)
*plex music library*
![alt text](https://github.com/joakimkingstrom/artist-logo-generator/blob/main/screenshots/SCR-20260205-ulxa.png)
*mobile plex library with round logos*
![alt text](https://github.com/joakimkingstrom/artist-logo-generator/blob/main/screenshots/image.png)

# Key files
- `Docker/` – application source and Flask app (`app.py`, `logic.py`, `plex_utils.py`) and static assets.
- `Docker/templates/index.html` – main UI template.
- `Docker/static/js/` – frontend modules: `editor.js`, `colorpicker.js`, `preview.js`, `lightbox.js`.
- `Docker/static/css/` – styles: `base.css`, `editor.css`, `controls.css`, `lightbox.css`.
- `Docker/Dockerfile` – image build for the app.
- `compose.yaml` – optional compose definition.
- `.env.example` – environment variables file.

# Quick start (Docker)

1. Build image (from repo root):

```bash
# from project root
docker build -t plex-artist-logos -f Docker/Dockerfile .
# or use compose if provided
docker compose up --build
```

2. Visit the app in your browser (default `http://localhost:5000` unless overridden by compose).

# Important endpoints
- `/` – main UI with fanart.tv, Metal Archives, and custom text logo tabs.
- `/get_options/<rating_key>` – returns available fanart.tv logos for an artist via the fanart.tv API. Validates `rating_key` is numeric.
- `/get_metal_archives/<rating_key>` – **NEW**: returns Metal Archives band logos by resolving MusicBrainz MBID → Metal Archives band ID → image URLs. Caches MusicBrainz responses; respects 1 req/sec rate limiting.
- `/get_posters/<rating_key>` – returns Plex poster resources for an artist. Validates `rating_key` is numeric.
- `/set_poster` – POST to set a poster for an artist in Plex (used by the lightbox "Use as artist image"). Validates `rating_key` and URL domain against allowlist.
- `/preview_text` – generate preview for text-based logos.
- `/save` and `/save_custom` – save selected/generated logos back to Plex. Validates required fields and URL domains.
- `/proxy_image?url=...` – image proxy to avoid cross-origin issues. Only allows whitelisted domains (fanart.tv, metal-archives.com).
- `/plex_proxy/<rating_key>` – proxy current artist image from Plex.

# Editing the UI
- Frontend logic lives in `Docker/static/js/` and styles in `Docker/static/css/`.
- `templates/index.html` is the single page template; JS files are loaded at the bottom of the page.

# Notes and troubleshooting
- The app normalises Plex resource URLs via `resource_to_url()` in `Docker/plex_utils.py`.
- If cross-origin image masking fails, check `/proxy_image` behaviour and ensure Plex URLs are accessible to the service.
- Use browser devtools network panel to inspect proxied image requests when debugging thumbnails or lightbox images.
- **SSRF protection**: The image proxy (`/proxy_image` and `/set_poster`) only allows requests to whitelisted domains (`fanart.tv`, `metal-archives.com`). To add additional domains, update `_ALLOWED_PROXY_HOSTS` in `Docker/app.py`.
- **MusicBrainz caching & rate limiting**: Metal Archives logo lookups cache MusicBrainz responses per MBID in `_mb_url_cache` to avoid redundant API calls. The app also respects MusicBrainz API rate limits (1 request/second) via `time.sleep()` in `get_metal_archives_logos()`. This prevents rate limiting errors when fetching multiple Metal Archives logos and improves performance for duplicate MBIDs.
- **User-Agent headers**: Both Metal Archives and MusicBrainz requests include a proper User-Agent header (`artist-logo-generator/1.0 (homelab)`) for better API compatibility and identification.

# Fonts
- The file `Docker/fonts.txt` lists font family names (one per line) used by the text-generator UI. Lines starting with `#` are treated as comments and ignored.
- Behaviour: on startup the app reads `fonts.txt` to populate the font selector and will attempt to download any missing fonts from Google Fonts (saved to the font directory used by `logic.py`). The download is best-effort — network access to Google Fonts is required and not all font families map cleanly to a single TTF/OTF/WOFF file.
- To add a font: add its Google Fonts family name to `Docker/fonts.txt` (one per line), then restart the service so the app can attempt to download it.

`Made together with Github copilot.`