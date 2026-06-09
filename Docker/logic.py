import os, base64, requests
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageEnhance
from io import BytesIO

FONT_DIR = '/app/fonts'

def _is_nonlatin_char(char):
    cp = ord(char)
    return (
        0x4E00 <= cp <= 0x9FFF or   # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or   # CJK Extension A
        0x3040 <= cp <= 0x30FF or   # Hiragana + Katakana
        0xAC00 <= cp <= 0xD7AF or   # Hangul syllables
        0xF900 <= cp <= 0xFAFF or   # CJK Compatibility Ideographs
        0x0600 <= cp <= 0x06FF or   # Arabic
        0x0590 <= cp <= 0x05FF or   # Hebrew
        0x0900 <= cp <= 0x097F or   # Devanagari
        0x0400 <= cp <= 0x04FF      # Cyrillic
    )

def _split_font_runs(text, primary_font, fallback_font):
    """Splits text into [(chunk, font)] runs, routing non-Latin chars to fallback_font."""
    runs = []
    current = ""
    current_needs_fallback = None
    for char in text:
        needs_fallback = _is_nonlatin_char(char)
        if needs_fallback != current_needs_fallback and current:
            runs.append((current, fallback_font if current_needs_fallback else primary_font))
            current = ""
        current_needs_fallback = needs_fallback
        current += char
    if current:
        runs.append((current, fallback_font if current_needs_fallback else primary_font))
    return runs

def _render_mixed_line(line, primary_font, fallback_font, color):
    """Render a line with font fallback, baseline-aligning runs from different fonts."""
    runs = _split_font_runs(line, primary_font, fallback_font)
    d = ImageDraw.Draw(Image.new('RGBA', (1, 1)))

    run_data = []
    for text, font in runs:
        b = d.textbbox((0, 0), text, font=font)
        run_data.append({'text': text, 'font': font, 'b': b})

    g_top = min(rd['b'][1] for rd in run_data)
    g_bot = max(rd['b'][3] for rd in run_data)
    total_w = sum(rd['b'][2] - rd['b'][0] for rd in run_data)
    total_h = g_bot - g_top

    if total_w <= 0 or total_h <= 0:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))

    line_img = Image.new('RGBA', (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(line_img)
    baseline_y = -g_top
    x = 0
    for rd in run_data:
        b = rd['b']
        draw.text((x - b[0], baseline_y), rd['text'], font=rd['font'], fill=color)
        x += b[2] - b[0]
    return line_img

def apply_transforms(img, apply_default_size=True, invert=False, make_white=False, contrast=1.0, zoom=1.0, monochrome=False, tint=None):
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox: img = img.crop(bbox)
    if make_white:
        alpha = img.getchannel('A')
        img = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img.putalpha(alpha)
    if monochrome:
        r, g, b, a = img.split()
        gray = Image.merge('RGB', (r, g, b)).convert('L').convert('RGB')
        img = Image.merge('RGBA', (*gray.split(), a))
    if invert:
        r, g, b, a = img.split()
        img = Image.merge('RGBA', (*ImageOps.invert(Image.merge('RGB', (r, g, b))).split(), a))
    if float(contrast) != 1.0:
        img = ImageEnhance.Contrast(img).enhance(float(contrast))
    
    canvas_side = 1000  

    if apply_default_size:
        # Fit into 80% of canvas, ignore zoom value from slider
        target_size = int(canvas_side * 0.8)
        ratio = min(target_size / img.width, target_size / img.height) if img.width > 0 and img.height > 0 else 0
        new_size = (int(img.width * ratio), int(img.height * ratio))
    else:
        # Apply zoom first, then fit to canvas if needed
        zoomed_size = (int(img.width * float(zoom)), int(img.height * float(zoom)))
        
        # Now, ensure the zoomed image still fits within the canvas, downscaling if necessary
        if zoomed_size[0] > canvas_side or zoomed_size[1] > canvas_side:
            ratio = min(canvas_side / zoomed_size[0], canvas_side / zoomed_size[1])
            new_size = (int(zoomed_size[0] * ratio), int(zoomed_size[1] * ratio))
        else:
            new_size = zoomed_size

    # Apply tint while the image still has RGBA alpha, matching the CSS mask-image
    # overlay the frontend uses: tint colour shows wherever the logo is opaque.
    if tint:
        try:
            h = str(tint).lstrip('#')
            if len(h) == 3:
                h = ''.join([c*2 for c in h])
            if len(h) == 6:
                r_t, g_t, b_t = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                alpha_ch = img.getchannel('A')
                # Use alpha channel as mask for PNGs with transparency; fall back to
                # luminance for fully-opaque sources (JPEGs, uploaded images).
                if alpha_ch.getextrema()[0] < 255:
                    mask = alpha_ch.point(lambda x: int(x * 0.9))
                else:
                    mask = img.convert('L').point(lambda x: int(x * 0.9))
                tint_layer = Image.new('RGBA', img.size, (r_t, g_t, b_t, 0))
                tint_layer.putalpha(mask)
                img = Image.alpha_composite(img, tint_layer)
        except Exception:
            pass

    if new_size[0] > 0 and new_size[1] > 0:
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    final = Image.new('RGB', (canvas_side, canvas_side), (0, 0, 0))
    final.paste(img, ((canvas_side - img.width) // 2, (canvas_side - img.height) // 2), img)

    return final

def remove_solid_bg(img_bytes, color_hex, threshold=30):
    import numpy as np
    img = Image.open(BytesIO(img_bytes)).convert('RGBA')
    arr = np.array(img)
    r = int(color_hex[1:3], 16)
    g = int(color_hex[3:5], 16)
    b = int(color_hex[5:7], 16)
    diff = np.abs(arr[:, :, :3].astype(int) - [r, g, b]).sum(axis=2)
    arr[:, :, 3] = np.where(diff < threshold * 3, 0, arr[:, :, 3])
    buf = BytesIO()
    Image.fromarray(arr).save(buf, 'PNG')
    return buf.getvalue()

def generate_text_logo(text, font_path, fallback_font_path=None, rows=1, color="white", case="none"):
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    text = str(text)

    if case == "upper": text = text.upper()
    elif case == "lower": text = text.lower()
    words = text.split()
    n = len(words)
    wpl = (n + int(rows) - 1) // int(rows)
    lines = [" ".join(words[i : i + wpl]) for i in range(0, n, wpl)]

    # Raqm shapes joining scripts (Arabic, Hebrew) and reorders bidi text correctly;
    # the basic layout engine draws each codepoint in isolation, left-to-right only.
    try:
        font = ImageFont.truetype(font_path, 400, encoding='utf-8', layout_engine=ImageFont.Layout.RAQM)
    except:
        try:
            font = ImageFont.truetype(font_path, 400, layout_engine=ImageFont.Layout.RAQM)
        except:
            font = ImageFont.load_default()

    fallback_font = None
    if fallback_font_path:
        try:
            fallback_font = ImageFont.truetype(fallback_font_path, 400, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            pass

    use_fallback = fallback_font and any(_is_nonlatin_char(c) for c in text)

    line_imgs = []
    if use_fallback:
        for line in lines:
            line_imgs.append(_render_mixed_line(line, font, fallback_font, color))
    else:
        d = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        for line in lines:
            b = d.textbbox((0, 0), line, font=font)
            li = Image.new('RGBA', (int(b[2]-b[0]), int(b[3]-b[1])), (0,0,0,0))
            ImageDraw.Draw(li).text((-b[0], -b[1]), line, font=font, fill=color)
            line_imgs.append(li)

    max_w = max(l.width for l in line_imgs)
    total_h = sum(l.height for l in line_imgs) + (50 * (len(lines)-1))
    combined = Image.new('RGBA', (max_w, total_h), (0,0,0,0))
    curr_y = 0
    for l in line_imgs:
        combined.paste(l, ((max_w - l.width)//2, curr_y), l)
        curr_y += l.height + 50
    return apply_transforms(combined)