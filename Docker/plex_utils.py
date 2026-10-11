import os
import time
import threading
import requests
import re
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from plexapi.server import PlexServer
from plexapi.exceptions import BadRequest, NotFound

PLEX_URL = os.environ.get('PLEX_URL')
PLEX_TOKEN = os.environ.get('PLEX_TOKEN')
FANART_API_KEY = os.environ.get('FANART_API_KEY')
BASE_OUTPUT_DIR = '/app/ArtistLogos'

# Derive Plex hostname once at startup so plex_proxy can validate it
PLEX_HOST = urlparse(PLEX_URL).hostname if PLEX_URL else None

# Bounded MusicBrainz URL cache — prevents unbounded memory growth on large libraries
_MB_CACHE_MAX = 1000
_mb_url_cache: dict[str, list[str]] = {}
_MA_HEADERS = {"User-Agent": "artist-logo-generator/1.0 (homelab)"}

# Plex connection is lazy: connecting at import meant a Plex outage at container
# start left the app dead until restart. Failed attempts are retried at most
# every _RETRY_SECS so a down Plex doesn't stall every request.
_server = None
_server_fail_time = 0.0
_server_lock = threading.Lock()
_RETRY_SECS = 15


def get_server():
    """Return a connected PlexServer, or None if Plex is unreachable right now."""
    global _server, _server_fail_time
    if _server is not None:
        return _server
    with _server_lock:
        if _server is not None:
            return _server
        if time.time() - _server_fail_time < _RETRY_SECS:
            return None
        try:
            _server = PlexServer(PLEX_URL, PLEX_TOKEN, timeout=10)
        except Exception as e:
            _server_fail_time = time.time()
            print(f"Plex connection error: {type(e).__name__}")  # not str(e): may echo the URL
            return None
        return _server


def plex_headers():
    """Auth header for server-side requests to Plex (keeps the token out of URLs/logs)."""
    return {'X-Plex-Token': PLEX_TOKEN} if PLEX_TOKEN else {}


def _port(u):
    return u.port or (443 if u.scheme == 'https' else 80)


def is_plex_url(url):
    """True only for URLs on the configured Plex scheme, host *and* port."""
    if not PLEX_URL:
        return False
    a, b = urlparse(url), urlparse(PLEX_URL)
    return a.scheme == b.scheme and a.hostname == b.hostname and _port(a) == _port(b)


def get_library(name):
    s = get_server()
    return s.library.section(name) if s else None


def fetch_artist(rating_key):
    """Return the artist for rating_key, or None if it doesn't exist or isn't an artist.

    Raises RuntimeError when Plex itself is unreachable (-> 503 in the app).
    """
    s = get_server()
    if s is None:
        raise RuntimeError("Plex unavailable — check PLEX_URL/PLEX_TOKEN and server connectivity")
    try:
        item = s.fetchItem(int(rating_key))
    except (NotFound, BadRequest):
        return None
    return item if getattr(item, 'type', None) == 'artist' else None


def _clean_title(title):
    # Strip path-significant chars including dots (blocks '..') and slashes.
    return re.sub(r'[\\/*?:"<>|.]', "", title).strip().replace('/', '')


def get_artist_path(title, rating_key):
    """Per-artist state dir, keyed on the Plex ratingKey.

    Titles alone are not unique or path-safe: "?" and "..." sanitise to an empty
    string (resolving to the volume root) and "AC/DC" / "ACDC" collide. The
    ratingKey makes the name unique and rename-proof; the cleaned title is kept
    as a readable prefix only. Dirs created by the old title-only scheme are
    migrated (renamed) on first access.
    """
    key = str(int(rating_key))
    clean = _clean_title(title)[:80].strip()
    name = f"{clean}-{key}" if clean else key
    base = pathlib.Path(BASE_OUTPUT_DIR).resolve()
    candidate = (base / name).resolve()
    # Must be a strict child of BASE_OUTPUT_DIR, never the root itself.
    if candidate.parent != base:
        raise ValueError(f"Unsafe artist path for title: {title!r}")

    if not candidate.exists() and clean:
        legacy = (base / _clean_title(title)).resolve()
        if (legacy.parent == base and legacy.is_dir()
                and ((legacy / 'artist.jpg').exists() or (legacy / '.status').exists())):
            try:
                legacy.rename(candidate)
                print(f"migrated legacy artist dir {legacy.name!r} -> {candidate.name!r}")
            except OSError as e:
                print(f"legacy dir migration failed for {legacy.name!r}: {type(e).__name__}")
    return str(candidate)


def get_fanart_logos(artist_obj):
    try:
        mbid = next((g.id.split('://')[-1] for g in artist_obj.guids if 'mbid' in g.id), None)
    except Exception:
        mbid = None
    if not mbid or not FANART_API_KEY:
        return []
    url = f"https://webservice.fanart.tv/v3/music/{mbid}?api_key={FANART_API_KEY}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return [l['url'] for l in (data.get('hdmusiclogo', []) + data.get('musiclogo', []))]
    except requests.RequestException as e:
        print(f"get_fanart_logos network error: {type(e).__name__}")  # not str(e): it embeds the URL incl. api_key
    return []


def resource_to_url(val):
    """Convert a Plex resource (string, object, or attribute) to an absolute URL.

    Returned URLs never embed the Plex token (they are sent to the browser and
    logged). Server-side fetches authenticate via plex_headers() instead.
    Returns None when a usable URL cannot be derived.
    """
    server = get_server()
    if not val:
        return None

    # If it's already a string
    if isinstance(val, str):
        v = val.strip()
        if v.lower().startswith('http://') or v.lower().startswith('https://'):
            return v
        # relative Plex path
        if v.startswith('/') and server:
            try:
                return server.url(v, includeToken=False)
            except Exception:
                return v
        return v

    # If plexapi resource / object, prefer server.url
    try:
        if server:
            return server.url(val, includeToken=False)
    except Exception:
        pass

    # Fallback to common attributes
    for attr in ('key', 'thumb', 'url'):
        v = getattr(val, attr, None)
        if not v:
            continue
        if isinstance(v, str):
            if v.lower().startswith('http://') or v.lower().startswith('https://'):
                return v
            if server:
                try:
                    return server.url(v, includeToken=False)
                except Exception:
                    return v
            return v
        else:
            try:
                if server:
                    return server.url(v, includeToken=False)
            except Exception:
                try:
                    return str(v)
                except Exception:
                    return None

    try:
        return str(val)
    except Exception:
        return None


def get_metal_archives_logos(artist_obj):
    if not artist_obj:
        return []

    mbid = next((g.id.split('://')[-1] for g in artist_obj.guids if 'mbid' in g.id), None)
    if not mbid:
        return []

    if mbid not in _mb_url_cache:
        time.sleep(1)  # MusicBrainz rate limit: 1 req/sec for anonymous clients
        mb_url = f"https://musicbrainz.org/ws/2/artist/{mbid}?inc=url-rels&fmt=json"
        try:
            res = requests.get(mb_url, headers=_MA_HEADERS, timeout=10)
        except requests.RequestException as e:
            print(f"get_metal_archives_logos MB request failed: {e}")
            return []
        if res.status_code != 200:
            return []
        urls = [
            rel['url']['resource']
            for rel in res.json().get('relations', [])
            if 'metal-archives' in rel.get('url', {}).get('resource', '')
        ]
        # Evict oldest entry when cache is full (insertion-ordered dict, Python 3.7+)
        if len(_mb_url_cache) >= _MB_CACHE_MAX:
            _mb_url_cache.pop(next(iter(_mb_url_cache)))
        _mb_url_cache[mbid] = urls

    ma_urls = _mb_url_cache[mbid]
    if not ma_urls:
        return []

    def _probe_band(ma_url):
        match = re.search(r'/bands/[^/]+/(\d+)', ma_url)
        if not match:
            return None
        band_id = match.group(1)
        shard = "/".join(list(band_id[:4]))
        base = f"https://www.metal-archives.com/images/{shard}/{band_id}_logo"
        for ext in ("jpg", "jpeg", "png", "gif"):
            url = f"{base}.{ext}"
            try:
                r = requests.head(url, headers=_MA_HEADERS, timeout=5)
                if r.status_code == 200:
                    return url
            except requests.RequestException:
                pass
        return None

    logos = []
    with ThreadPoolExecutor(max_workers=min(len(ma_urls), 8)) as pool:
        futures = {pool.submit(_probe_band, u): u for u in ma_urls}
        for future in as_completed(futures):
            result = future.result()
            if result:
                logos.append(result)
    return logos


def get_theaudiodb_images(artist_obj):
    try:
        mbid = next((g.id.split('://')[-1] for g in artist_obj.guids if 'mbid' in g.id), None)
    except Exception:
        mbid = None
    if not mbid:
        return []
    try:
        url = f"https://www.theaudiodb.com/api/v1/json/123/artist-mb.php?i={mbid}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        artists = r.json().get('artists') or []
        if not artists:
            return []
        a = artists[0]
        fields = ['strArtistLogo']
        return [a[f] for f in fields if a.get(f)]
    except Exception as e:
        print(f"get_theaudiodb_images error: {e}")
        return []


def get_artist_posters(artist_obj):
    """Return a best-effort list of poster/artwork URLs for an artist object."""
    posters = []
    if not artist_obj:
        return posters

    try:
        # Try posters() if available
        try:
            p = artist_obj.posters()
            if isinstance(p, dict):
                for _, v in p.items():
                    u = resource_to_url(v)
                    if u:
                        posters.append(u)
            elif isinstance(p, list):
                for v in p:
                    u = resource_to_url(v)
                    if u:
                        posters.append(u)
        except Exception:
            pass

        # Common fallback attributes
        if getattr(artist_obj, 'thumb', None):
            u = resource_to_url(artist_obj.thumb)
            if u:
                posters.append(u)

        if getattr(artist_obj, 'art', None):
            u = resource_to_url(artist_obj.art)
            if u:
                posters.append(u)

        # Sometimes media entries contain artwork
        if getattr(artist_obj, 'media', None):
            for m in artist_obj.media:
                if getattr(m, 'thumb', None):
                    u = resource_to_url(m.thumb)
                    if u:
                        posters.append(u)
    except Exception as e:
        print(f"get_artist_posters error: {e}")

    # Deduplicate while preserving order
    seen = set()
    out = []
    for u in posters:
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out