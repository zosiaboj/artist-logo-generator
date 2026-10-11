"""Request validation and size-capped fetching helpers.

Everything user-controlled (JSON fields, data: URLs, remote image URLs) goes
through here so routes get typed, clamped values or an InputError, instead of
a 500 from int(None) / float('abc') or an unbounded read into memory.
"""
import base64
import binascii
import math
import re
import time
from urllib.parse import unquote_to_bytes, urljoin, urlparse

import requests

# Size caps (bytes unless noted)
MAX_UPLOAD_BYTES = 15 * 1024 * 1024        # decoded size of a pasted/uploaded image
MAX_REMOTE_IMAGE_BYTES = 15 * 1024 * 1024  # remote image download
MAX_SVG_BYTES = 2 * 1024 * 1024
MAX_URL_CHARS = 2048
MAX_BULK_KEYS = 5000
MAX_RATING_KEY_CHARS = 12
MAX_REDIRECTS = 3
FETCH_DEADLINE_SECS = 30                   # total wall-clock per download (slow-drip guard)


class InputError(ValueError):
    """Bad client input. `status` is the HTTP status to return."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --- scalar fields ---------------------------------------------------------

def is_rating_key(value):
    s = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ''
    return s.isascii() and s.isdigit() and 0 < len(s) <= MAX_RATING_KEY_CHARS


def rating_key(value):
    if not is_rating_key(value):
        raise InputError('invalid rating_key')
    return str(value)


def rating_keys(value):
    """Validate a list of rating keys: list type, capped length, de-duplicated."""
    if not isinstance(value, list) or not value:
        raise InputError('artist_keys must be a non-empty list')
    if len(value) > MAX_BULK_KEYS:
        raise InputError(f'too many artist_keys (max {MAX_BULK_KEYS})', 413)
    return list(dict.fromkeys(rating_key(k) for k in value))


def num(value, default, lo, hi):
    """Float clamped to [lo, hi]. Missing/blank -> default; non-numeric -> InputError."""
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        raise InputError('expected a number')
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise InputError('expected a number')
    if math.isnan(f) or math.isinf(f):
        raise InputError('expected a finite number')
    return min(max(f, lo), hi)


def flag(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def choice(value, allowed, default):
    return value if isinstance(value, str) and value in allowed else default


_HEX_RE = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def hex_color(value, default=None):
    """Normalise to '#rrggbb'; anything else -> default."""
    if not isinstance(value, str):
        return default
    m = _HEX_RE.match(value.strip())
    if not m:
        return default
    h = m.group(1).lower()
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return '#' + h


def transform_params(data):
    """Validated kwargs for logic.apply_transforms (ranges match the UI sliders, with headroom)."""
    return {
        'apply_default_size': flag(data.get('apply_default_size'), False),
        'invert': flag(data.get('invert')),
        'make_white': flag(data.get('make_white')),
        'monochrome': flag(data.get('monochrome')),
        'contrast': num(data.get('contrast'), 1.0, 0.0, 5.0),
        'zoom': num(data.get('zoom'), 1.0, 0.1, 5.0),
        'tint': hex_color(data.get('tint'), None),
    }


def text_params(data):
    """Validated kwargs for logic.generate_text_logo."""
    return {
        'rows': int(num(data.get('rows'), 1, 1, 4)),
        'color': hex_color(data.get('color'), '#ffffff'),
        'case': choice(data.get('case'), ('upper', 'lower', 'none'), 'none'),
    }


# --- data: URLs ------------------------------------------------------------

_DATA_URL_RE = re.compile(r'^data:(image/[a-zA-Z0-9.+-]+)((?:;[^,;]*)*),')


def decode_data_url(url, max_bytes=MAX_UPLOAD_BYTES):
    """Return (mime, bytes) from an image data: URL, enforcing max_bytes *before* decoding."""
    m = _DATA_URL_RE.match(url[:300]) if isinstance(url, str) else None
    if not m:
        raise InputError('invalid image data URL')
    mime = m.group(1).lower()
    payload = url[m.end():]
    if ';base64' in (m.group(2) or '').lower():
        if len(payload) > max_bytes * 4 // 3 + 16:
            raise InputError('image too large', 413)
        try:
            raw = base64.b64decode(payload)
        except (binascii.Error, ValueError):
            raise InputError('could not decode image data')
    else:
        if len(payload) > max_bytes * 3:
            raise InputError('image too large', 413)
        raw = unquote_to_bytes(payload)
    if len(raw) > max_bytes:
        raise InputError('image too large', 413)
    if not raw:
        raise InputError('empty image data')
    return mime, raw


# SVG: cairosvg can resolve entities and fetch external resources. Logos don't need
# either, so reject anything that references more than local fragments / data: URIs.
_SVG_UNSAFE_RE = re.compile(
    rb'<!ENTITY|<!DOCTYPE[^>]*\['
    rb'|href\s*=\s*["\']\s*(?!#|data:)[^"\']'
    rb'|url\(\s*["\']?\s*(?!#|data:)[^)\s"\']',
    re.IGNORECASE,
)


def check_svg(raw):
    if len(raw) > MAX_SVG_BYTES:
        raise InputError('SVG too large', 413)
    if _SVG_UNSAFE_RE.search(raw):
        raise InputError('SVG with external references or entities is not supported — save it as PNG first')


# --- remote fetch ----------------------------------------------------------

_REDIRECT_CODES = (301, 302, 303, 307, 308)


def fetch_bytes(url, is_allowed, max_bytes=MAX_REMOTE_IMAGE_BYTES, headers_for=None, timeout=20):
    """GET url with a hard size cap. Returns (bytes, content_type).

    - every hop (including redirects, followed manually, max MAX_REDIRECTS) must
      satisfy is_allowed(url), so an allowlisted host can't bounce us elsewhere;
    - headers_for(url) supplies per-hop headers, so credentials are never sent
      to a redirect target;
    - the body is streamed and aborted past max_bytes or FETCH_DEADLINE_SECS.
    """
    deadline = time.monotonic() + FETCH_DEADLINE_SECS
    for _ in range(MAX_REDIRECTS + 1):
        if len(url) > MAX_URL_CHARS or urlparse(url).scheme not in ('http', 'https') or not is_allowed(url):
            raise InputError('domain not allowed', 403)
        with requests.get(url, headers=headers_for(url) if headers_for else None,
                          timeout=timeout, stream=True, allow_redirects=False) as r:
            if r.status_code in _REDIRECT_CODES:
                loc = r.headers.get('Location')
                if not loc:
                    raise InputError('bad redirect from upstream', 502)
                url = urljoin(url, loc)
                continue
            r.raise_for_status()
            cl = r.headers.get('Content-Length', '')
            if cl.isdigit() and int(cl) > max_bytes:
                raise InputError('remote image too large', 413)
            buf = bytearray()
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > max_bytes:
                    raise InputError('remote image too large', 413)
                if time.monotonic() > deadline:
                    raise InputError('upstream too slow', 504)
            return bytes(buf), r.headers.get('Content-Type', '') or ''
    raise InputError('too many redirects', 502)
