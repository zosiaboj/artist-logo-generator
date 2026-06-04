import os
import time
import requests
import re
import pathlib
from urllib.parse import urlparse
from plexapi.server import PlexServer

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

try:
    server = PlexServer(PLEX_URL, PLEX_TOKEN)
except Exception as e:
    print(f"Plex Connection Error: {e}")
    server = None


def get_library(name):
    return server.library.section(name) if server else None


def fetch_artist(rating_key):
    return server.fetchItem(int(rating_key)) if server else None


def get_artist_path(title):
    # Strip dangerous chars including dots (to block '..') and forward slash
    clean = re.sub(r'[\\/*?:"<>|.]', "", title).strip().replace('/', '')
    base = pathlib.Path(BASE_OUTPUT_DIR).resolve()
    candidate = (base / clean).resolve()
    # Ensure the resolved path stays inside BASE_OUTPUT_DIR
    if not str(candidate).startswith(str(base) + os.sep) and candidate != base:
        raise ValueError(f"Path traversal attempt blocked for title: {title!r}")
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
        print(f"get_fanart_logos network error: {e}")
    return []


def resource_to_url(val):
    """Convert a Plex resource (string, object, or attribute) to an absolute URL.

    Returns None when a usable URL cannot be derived.
    """
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
                return server.url(v, includeToken=True)
            except Exception:
                return v
        return v

    # If plexapi resource / object, prefer server.url
    try:
        if server:
            return server.url(val, includeToken=True)
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
                    return server.url(v, includeToken=True)
                except Exception:
                    return v
            return v
        else:
            try:
                if server:
                    return server.url(v, includeToken=True)
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

    logos = []
    for ma_url in ma_urls:
        match = re.search(r'/bands/[^/]+/(\d+)', ma_url)
        if not match:
            continue
        band_id = match.group(1)
        shard = "/".join(list(band_id[:4]))
        base = f"https://www.metal-archives.com/images/{shard}/{band_id}_logo"
        for ext in ("jpg", "jpeg", "png", "gif"):
            url = f"{base}.{ext}"
            try:
                r = requests.head(url, headers=_MA_HEADERS, timeout=5)
                if r.status_code == 200:
                    logos.append(url)
                    break
            except requests.RequestException:
                pass
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