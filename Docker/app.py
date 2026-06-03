import os, base64, re, requests, json
from io import BytesIO
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from PIL import ImageFont
import plex_utils, logic

app = Flask(__name__)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["120 per minute"],
    storage_uri="memory://",
)

# Allowlist for the image proxy and set_poster endpoints.
# Only these external domains may be fetched server-side to prevent SSRF.
_ALLOWED_PROXY_HOSTS = {'assets.fanart.tv', 'www.metal-archives.com'}

# Allowlist for Content-Type headers forwarded to the browser
_ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

def load_default_fonts():
    """Loads default fonts from fonts.txt, with a fallback list."""
    try:
        with open('fonts.txt', 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    except FileNotFoundError:
        print("Warning: fonts.txt not found. Using a hardcoded fallback list.")
        return [
            "Roboto", "Open Sans", "Lato", "Montserrat", "Oswald", "Raleway", "Merriweather", 
            "Pacifico", "Dancing Script", "Bebas Neue", "Anton", "Lobster", "Comfortaa",
            "Cinzel", "Fauna One", "Orbitron", "Press Start 2P", "Special Elite"
        ]

DEFAULT_FONTS = load_default_fonts()

@app.route('/')
def index():
    lib = plex_utils.get_library(os.environ.get('LIBRARY_NAME', 'Music'))
    artists = sorted(lib.all(), key=lambda x: re.sub(r'^(the|a|an)\s+', '', x.title.lower()))
    
    data = []
    for a in artists:
        path = plex_utils.get_artist_path(a.title)
        status_file = os.path.join(path, '.status')
        status = 'none'
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status = f.read().strip()
        data.append({'obj': a, 'status': status})
    return render_template('index.html', artists=data, fonts=DEFAULT_FONTS)

_ALLOWED_FONT_EXTENSIONS = {'.ttf', '.otf', '.woff', '.woff2'}

# Fonts whose glyphs are primarily non-Latin — skip the latin,latin-ext subset
# parameter so the download doesn't fail for fonts that have no Latin coverage.
_CJK_FONTS = {'Noto Sans SC', 'Noto Serif SC', 'Noto Sans JP', 'Noto Serif JP', 'Noto Sans KR',
               'Ma Shan Zheng', 'ZCOOL QingKe HuangYou', 'Shippori Mincho', 'BIZ UDGothic',
               'Zen Kurenaido', 'DotGothic16'}

_MODERN_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_cjk_char_cache = {}          # chars_key → font_path
_cjk_cache_lock = __import__('threading').Lock()

def get_cjk_font_for_text(text):
    """Return a TTF covering the non-Latin characters in text.

    Uses Google Fonts CSS2 text= subsetting to download only the specific glyphs
    needed, converting woff2→TTF in-memory with fonttools. Result is cached by
    the frozenset of non-Latin characters in the text.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None

    cjk_chars = ''.join(sorted(set(c for c in text if logic._is_nonlatin_char(c))))
    if not cjk_chars:
        return None

    with _cjk_cache_lock:
        cached = _cjk_char_cache.get(cjk_chars)
        if cached and os.path.exists(cached):
            return cached

    from urllib.parse import quote
    import hashlib
    css_url = (f"https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400"
               f"&text={quote(cjk_chars)}")
    try:
        css = requests.get(css_url, headers={"User-Agent": _MODERN_UA}, timeout=15).text
        # Match either .woff2 extension or format('woff2') annotation
        woff2_urls = re.findall(r"url\(([^)]+)\)\s*format\(['\"]woff2['\"]\)", css)
        if not woff2_urls:
            woff2_urls = re.findall(r'url\(([^)]+\.woff2[^)]*)\)', css)
        if not woff2_urls:
            print(f"No woff2 URL for CJK chars {cjk_chars!r}")
            return None

        char_hash = hashlib.md5(cjk_chars.encode()).hexdigest()[:10]
        font_path = os.path.join(logic.FONT_DIR, f'cjk_subset_{char_hash}.ttf')

        if not os.path.exists(font_path):
            r = requests.get(woff2_urls[0], timeout=30)
            r.raise_for_status()
            os.makedirs(logic.FONT_DIR, exist_ok=True)
            TTFont(BytesIO(r.content)).save(font_path)
            print(f"CJK subset for {cjk_chars!r} → {font_path} ({os.path.getsize(font_path)//1024} KB)")

        with _cjk_cache_lock:
            _cjk_char_cache[cjk_chars] = font_path
        return font_path

    except Exception as e:
        print(f"CJK font download failed for {cjk_chars!r}: {e}")
        return None

def download_font_if_needed(font_name):
    """Checks if a font is available locally, and if not, downloads it from Google Fonts.

    Only fonts in DEFAULT_FONTS are permitted — rejects arbitrary font names to prevent
    HTTP header injection and path traversal via the font_name parameter.
    """
    if font_name not in DEFAULT_FONTS:
        print(f"Font '{font_name}' is not in the allowed fonts list.")
        return None

    font_basename = f"{font_name.replace(' ', '')}-Regular"
    font_dir = logic.FONT_DIR

    for ext in ['.ttf', '.otf', '.woff', '.woff2']:
        f_path = os.path.join(font_dir, font_basename + ext)
        if os.path.exists(f_path):
            return f_path

    print(f"Font '{font_name}' not found locally. Attempting to download from Google Fonts...")

    try:
        # CJK fonts don't support the latin,latin-ext subset — omit it for those.
        # For Latin fonts: subset=latin,latin-ext forces a single TTF covering
        # extended-Latin (Polish ł, ó, ą, ę etc.) via the old Android UA trick.
        if font_name in _CJK_FONTS:
            css_url = f"https://fonts.googleapis.com/css?family={font_name.replace(' ', '+')}"
        else:
            css_url = f"https://fonts.googleapis.com/css?family={font_name.replace(' ', '+')}:regular&subset=latin,latin-ext"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 2.2; en-us; Nexus One Build/FRF91) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1'
        }
        css_response = requests.get(css_url, headers=headers)
        css_response.raise_for_status()
        css_text = css_response.text

        font_urls = re.findall(r"url\(([^)]+)\)", css_text)
        if not font_urls:
            print(f"Could not find any font URL in the CSS for '{font_name}'.")
            return None

        font_url = font_urls[0]

        extension = ".ttf"
        for allowed_ext in ('.woff2', '.woff', '.otf', '.ttf'):
            if allowed_ext in font_url:
                extension = allowed_ext
                break
        if extension not in _ALLOWED_FONT_EXTENSIONS:
            print(f"Unexpected font extension for '{font_name}', aborting download.")
            return None

        f_path = os.path.join(font_dir, font_basename + extension)
        font_response = requests.get(font_url)
        font_response.raise_for_status()

        os.makedirs(font_dir, exist_ok=True)
        with open(f_path, 'wb') as f:
            f.write(font_response.content)

        print(f"Successfully downloaded and saved '{font_name}' to '{f_path}'.")
        return f_path

    except requests.exceptions.RequestException as e:
        print(f"Error downloading font '{font_name}': {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while downloading font '{font_name}': {e}")
        return None

@app.route('/get_options/<rating_key>')
def get_options(rating_key):
    if not rating_key.isdigit():
        return jsonify({"logos": []}), 400
    artist = plex_utils.fetch_artist(rating_key)
    if not artist:
        return jsonify({"logos": []}), 404
    logos = plex_utils.get_fanart_logos(artist)
    return jsonify({"logos": logos, "google_url": f"https://www.google.com/search?q={artist.title}+transparent+logo+png&tbm=isch"})


@app.route('/get_metal_archives/<rating_key>')
def get_metal_archives(rating_key):
    if not rating_key.isdigit():
        return jsonify({"logos": []}), 400
    artist = plex_utils.fetch_artist(rating_key)
    logos = plex_utils.get_metal_archives_logos(artist)
    return jsonify({"logos": logos})


@app.route('/get_posters/<rating_key>')
def get_posters(rating_key):
    if not rating_key.isdigit():
        return jsonify({"posters": []}), 400
    artist = plex_utils.fetch_artist(rating_key)
    posters = plex_utils.get_artist_posters(artist)
    return jsonify({"posters": posters})


@app.route('/set_poster', methods=['POST'])
def set_poster():
    data = request.json or {}
    rating_key = data.get('rating_key')
    url = data.get('url')
    if not rating_key or not url:
        return jsonify({'status': 'error', 'message': 'rating_key and url required'}), 400

    parsed = urlparse(url)
    if parsed.hostname not in _ALLOWED_PROXY_HOSTS:
        return jsonify({'status': 'error', 'message': 'domain not allowed'}), 403

    artist = plex_utils.fetch_artist(rating_key)
    if not artist:
        return jsonify({'status': 'error', 'message': 'artist not found'}), 404

    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        # Save to a temporary file so plexapi can upload it
        import tempfile
        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        tf.write(resp.content)
        tf.flush()
        tf.close()

        artist.uploadPoster(filepath=tf.name)

        try:
            os.remove(tf.name)
        except Exception:
            pass

        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"set_poster error: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to set poster'}), 500


@app.route('/proxy_image')
def proxy_image():
    url = request.args.get('url')
    if not url:
        return 'url required', 400
    # Normalize input using plex_utils.resource_to_url which handles
    # absolute URLs, plex-relative paths and plexapi resource objects.
    try:
        normalized = plex_utils.resource_to_url(url)
    except Exception as e:
        print(f"proxy_image resource_to_url error for {url}: {e}")
        return jsonify({'status': 'error', 'message': 'invalid url'}), 400

    if not normalized or not (normalized.startswith('http://') or normalized.startswith('https://')):
        return 'invalid url', 400

    parsed = urlparse(normalized)
    allowed_hosts = _ALLOWED_PROXY_HOSTS | ({plex_utils.PLEX_HOST} if plex_utils.PLEX_HOST else set())
    if parsed.hostname not in allowed_hosts:
        return jsonify({'status': 'error', 'message': 'domain not allowed'}), 403

    url = normalized

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        ct = r.headers.get('Content-Type', 'image/jpeg') or 'image/jpeg'
        # Only forward image MIME types — prevents XSS via a malicious upstream Content-Type
        if ct.split(';')[0].strip() not in _ALLOWED_IMAGE_TYPES:
            ct = 'image/jpeg'
        return send_file(BytesIO(r.content), mimetype=ct)
    except Exception as e:
        print(f"proxy_image error fetching {url}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch image'}), 502

@app.route('/save', methods=['POST'])
def save():
    data = request.json or {}
    rating_key = data.get('rating_key')
    url = data.get('url')
    if not rating_key or not url:
        return jsonify({'status': 'error', 'message': 'rating_key and url required'}), 400
    artist = plex_utils.fetch_artist(rating_key)
    if not artist:
        return jsonify({'status': 'error', 'message': 'artist not found'}), 404
    if url.startswith('data:image/svg+xml'):
        try:
            import cairosvg
            svg_bytes = base64.b64decode(url.split(',')[1])
            png_bytes = cairosvg.svg2png(bytestring=svg_bytes, output_width=1000, output_height=1000)
            img = logic.Image.open(BytesIO(png_bytes))
        except Exception as e:
            print(f"SVG conversion failed: {e}")
            return jsonify({'status': 'error', 'message': 'SVG conversion failed — try saving as PNG first'}), 400
    elif url.startswith('data:image'):
        img = logic.Image.open(BytesIO(base64.b64decode(url.split(',')[1])))
    else:
        parsed = urlparse(url)
        if parsed.hostname not in _ALLOWED_PROXY_HOSTS:
            return jsonify({'status': 'error', 'message': 'domain not allowed'}), 403
        img = logic.Image.open(BytesIO(requests.get(url, timeout=20).content))
    
    final = logic.apply_transforms(img, **{k: data.get(k) for k in ['apply_default_size', 'invert', 'make_white', 'contrast', 'zoom', 'monochrome', 'tint']})
    path = plex_utils.get_artist_path(artist.title)
    os.makedirs(path, exist_ok=True)
    final.save(os.path.join(path, "artist.jpg"), "JPEG", quality=95)
    
    with open(os.path.join(path, '.status'), 'w') as f:
        f.write('done')

    if os.environ.get('UPDATE_PLEX', 'false').lower() == 'true': artist.uploadPoster(filepath=os.path.join(path, "artist.jpg"))
    return jsonify({"status": "success"})

@app.route('/save_custom', methods=['POST'])
@limiter.limit("15 per minute")
def save_custom():
    data = request.json or {}
    rating_key = str(data.get('rating_key', ''))
    if not rating_key.isdigit():
        return jsonify({'status': 'error', 'message': 'invalid rating_key'}), 400
    artist = plex_utils.fetch_artist(rating_key)
    if not artist:
        return jsonify({'status': 'error', 'message': 'artist not found'}), 404
    font_name = data.get('font', 'Roboto')
    if font_name not in DEFAULT_FONTS:
        font_name = 'Roboto'

    f_path = download_font_if_needed(font_name)
    if not f_path:
        f_path = ImageFont.load_default()

    cjk_path = get_cjk_font_for_text(artist.title)
    img = logic.generate_text_logo(artist.title, f_path, fallback_font_path=cjk_path,
                                   **{k: data.get(k) for k in ['rows', 'color', 'case']})
    path = plex_utils.get_artist_path(artist.title)
    os.makedirs(path, exist_ok=True)
    img.save(os.path.join(path, "artist.jpg"), "JPEG", quality=95)
    
    with open(os.path.join(path, '.status'), 'w') as f:
        f.write('custom')

    if os.environ.get('UPDATE_PLEX', 'false').lower() == 'true': artist.uploadPoster(filepath=os.path.join(path, "artist.jpg"))
    return jsonify({"status": "success"})

@app.route('/toggle_status/<rating_key>', methods=['POST'])
def toggle_status(rating_key):
    artist = plex_utils.fetch_artist(rating_key)
    path = plex_utils.get_artist_path(artist.title)
    os.makedirs(path, exist_ok=True)
    status_file = os.path.join(path, '.status')
    
    current_status = 'none'
    if os.path.exists(status_file):
        with open(status_file, 'r') as f:
            current_status = f.read().strip()
            
    if current_status == 'none':
        next_status = 'custom'
    elif current_status == 'custom':
        next_status = 'done'
    else: # done
        next_status = 'none'
        
    with open(status_file, 'w') as f:
        f.write(next_status)
        
    return jsonify({'status': 'success', 'new_status': next_status})

@app.route('/bulk_apply_fanart', methods=['POST'])
@limiter.limit("3 per minute")
def bulk_apply_fanart():
    data = request.json or {}
    artist_keys = data.get('artist_keys', [])
    updated_count = 0

    for key in artist_keys:
        try:
            artist = plex_utils.fetch_artist(key)
            logos = plex_utils.get_fanart_logos(artist)

            if logos:
                most_popular_logo_url = logos[0]

                # Apply same domain allowlist as proxy_image to prevent SSRF via fanart.tv response
                parsed_logo = urlparse(most_popular_logo_url)
                if parsed_logo.hostname not in _ALLOWED_PROXY_HOSTS:
                    print(f"bulk_apply_fanart blocked unexpected host: {parsed_logo.hostname}")
                    continue

                img = logic.Image.open(BytesIO(requests.get(most_popular_logo_url, timeout=20).content))
                final = logic.apply_transforms(img, apply_default_size=True) # Using default sizing
                
                path = plex_utils.get_artist_path(artist.title)
                os.makedirs(path, exist_ok=True)
                final.save(os.path.join(path, "artist.jpg"), "JPEG", quality=95)
                
                if os.environ.get('UPDATE_PLEX', 'false').lower() == 'true':
                    artist.uploadPoster(filepath=os.path.join(path, "artist.jpg"))
                
                updated_count += 1
        except Exception as e:
            print(f"Error updating artist {key}: {e}")
            continue
            
    return jsonify({"status": "success", "updated_count": updated_count})

@app.route('/bulk_toggle_status', methods=['POST'])
def bulk_toggle_status():
    data = request.json
    artist_keys = data.get('artist_keys', [])
    updated_artists = []
    
    for key in artist_keys:
        try:
            artist = plex_utils.fetch_artist(key)
            path = plex_utils.get_artist_path(artist.title)
            os.makedirs(path, exist_ok=True)
            status_file = os.path.join(path, '.status')
            
            current_status = 'none'
            if os.path.exists(status_file):
                with open(status_file, 'r') as f:
                    current_status = f.read().strip()
            
            if current_status == 'none':
                next_status = 'custom'
            elif current_status == 'custom':
                next_status = 'done'
            else: # done
                next_status = 'none'
                
            with open(status_file, 'w') as f:
                f.write(next_status)
            
            updated_artists.append({'key': key, 'new_status': next_status})
        except Exception as e:
            print(f"Error updating artist {key}: {e}")
            continue
            
    return jsonify({"status": "success", "updated_count": len(updated_artists), "updated_artists": updated_artists})


@app.route('/preview_text', methods=['POST'])
@limiter.limit("20 per minute")
def preview_text():
    data = request.json or {}
    rating_key = str(data.get('rating_key', ''))
    if not rating_key.isdigit():
        return jsonify({'status': 'error', 'message': 'invalid rating_key'}), 400
    artist = plex_utils.fetch_artist(rating_key)
    if not artist:
        return jsonify({'status': 'error', 'message': 'artist not found'}), 404
    font_name = data.get('font', 'Roboto')
    if font_name not in DEFAULT_FONTS:
        font_name = 'Roboto'

    f_path = download_font_if_needed(font_name)
    if not f_path:
        f_path = ImageFont.load_default()

    cjk_path = get_cjk_font_for_text(artist.title)
    img = logic.generate_text_logo(artist.title, f_path, fallback_font_path=cjk_path,
                                   **{k: data.get(k) for k in ['rows', 'color', 'case']})

    buffered = BytesIO()
    img.save(buffered, format="JPEG")
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return jsonify({"image": img_str})

@app.route('/plex_proxy/<rating_key>')
def plex_proxy(rating_key):
    if not rating_key.isdigit():
        return 'invalid key', 400
    artist = plex_utils.fetch_artist(rating_key)
    if not artist:
        return 'artist not found', 404
    # Use plex_utils to convert artist.thumb into a usable URL
    try:
        thumb_url = plex_utils.resource_to_url(artist.thumb)
        if not thumb_url:
            return 'thumb not available', 404

        # Validate we only fetch from the configured Plex server (prevents confused-deputy SSRF)
        parsed = urlparse(thumb_url)
        if plex_utils.PLEX_HOST and parsed.hostname != plex_utils.PLEX_HOST:
            print(f"plex_proxy blocked unexpected host: {parsed.hostname}")
            return jsonify({'status': 'error', 'message': 'domain not allowed'}), 403

        r = requests.get(thumb_url, timeout=15)
        r.raise_for_status()
        ct = r.headers.get('Content-Type', 'image/jpeg') or 'image/jpeg'
        if ct.split(';')[0].strip() not in _ALLOWED_IMAGE_TYPES:
            ct = 'image/jpeg'
        return send_file(BytesIO(r.content), mimetype=ct)
    except Exception as e:
        print(f"plex_proxy error: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch artist image'}), 500

if __name__ == '__main__':
    print("Downloading all fonts listed in fonts.txt...")
    for font in DEFAULT_FONTS:
        download_font_if_needed(font)
    print("Font download process finished.")
    # CJK subset fonts are downloaded lazily on first preview/save request.
    app.run(host='0.0.0.0', port=5000)