"""Drawing helpers: fonts, colours, backgrounds, logos, rounded shapes."""
import colorsys
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

FONTS = config.ASSETS_DIR / "fonts"

# Headline fonts: id -> (file, size scale, force uppercase). Missing files are simply skipped;
# tools/get_fonts.py (run automatically in the cloud) downloads the extra ones.
HEAD_FONTS = {
    "inter": ("Inter-Black.otf", 1.0, False),
    "interdisplay": ("InterDisplay-Black.otf", 1.0, False),
    "poppins": ("Poppins-Bold.ttf", 0.95, False),
    "archivo": ("ArchivoBlack-Regular.ttf", 0.9, False),
    "anton": ("Anton-Regular.ttf", 1.12, True),
    "bebas": ("BebasNeue-Regular.ttf", 1.3, True),
}
BODY = {"Black": "Inter-Black.otf", "ExtraBold": "InterDisplay-ExtraBold.otf",
        "Bold": "Inter-Bold.otf", "SemiBold": "Inter-SemiBold.otf", "Medium": "Inter-Medium.otf",
        "Poppins": "Poppins-Medium.ttf"}
_cache = {}


def available_head_fonts():
    return [k for k, (f, _, _) in HEAD_FONTS.items() if (FONTS / f).exists()]


def font(weight="Bold", size=40):
    k = ("b", weight, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(str(FONTS / BODY[weight]), int(size))
    return _cache[k]


def head_font(fid, size):
    f, scale, _ = HEAD_FONTS.get(fid, HEAD_FONTS["inter"])
    if not (FONTS / f).exists():
        f, scale, _ = HEAD_FONTS["inter"]
    k = ("h", f, int(size * scale))
    if k not in _cache:
        _cache[k] = ImageFont.truetype(str(FONTS / f), int(size * scale))
    return _cache[k]


def head_upper(fid):
    return HEAD_FONTS.get(fid, HEAD_FONTS["inter"])[2]


# ------------------------------------------------------------------ colour
def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a[:3], b[:3]))


def shift_hue(c, deg, sat=None, val=None):
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c[:3]))
    h = (h + deg / 360) % 1
    s = s if sat is None else sat
    v = v if val is None else val
    return tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h, s, v))


def readable_on(color):
    return (15, 17, 22) if lum(color) > 150 else (255, 255, 255)


def text_safe(color, bg_light):
    """Version of an accent colour that is readable as text on the given background."""
    if bg_light:
        while lum(color) > 120:
            color = mix(color, (0, 0, 0), 0.15)
    else:
        while lum(color) < 110:
            color = mix(color, (255, 255, 255), 0.15)
    return color


def brand_color(logo, screenshot=None):
    """Most characteristic saturated colour of the logo (or first screenshot). None if grey."""
    src = logo or (Image.open(screenshot).convert("RGBA") if screenshot else None)
    if src is None:
        return None
    small = src.copy()
    small.thumbnail((120, 120))
    counts = {}
    for r, g, b, a in small.convert("RGBA").getdata():
        if a < 128:
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if (mx - mn) / (mx or 1) < 0.35 or mx < 110:
            continue
        key = (r // 24 * 24, g // 24 * 24, b // 24 * 24)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    best = max(counts, key=lambda k: counts[k] * (0.5 + (max(k) - min(k)) / (max(k) or 1)))
    if lum(best) < 95:
        best = mix(best, (255, 255, 255), (95 - lum(best)) / 160)
    return best


# ------------------------------------------------------------------ shapes
def rounded(size, radius, fill):
    im = Image.new("RGBA", (int(size[0]), int(size[1])), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius, fill=fill)
    return im


def round_corners(im, radius, top_only=False, bottom_only=False):
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius, fill=255)
    if top_only:
        d.rectangle([0, radius, im.size[0], im.size[1]], fill=255)
    if bottom_only:
        d.rectangle([0, 0, im.size[0], im.size[1] - radius], fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def shadow(size, radius, blur=30, opacity=150, color=(0, 0, 0)):
    pad = blur * 3
    im = Image.new("RGBA", (int(size[0]) + pad * 2, int(size[1]) + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([pad, pad, pad + size[0], pad + size[1]], radius,
                                         fill=(*color, opacity))
    return im.filter(ImageFilter.GaussianBlur(blur)), pad


def paste_shadowed(canvas, im, xy, radius=20, blur=26, opacity=160, dy=14):
    sh, pad = shadow(im.size, radius, blur=blur, opacity=opacity)
    canvas.alpha_composite(sh, (int(xy[0] - pad), int(xy[1] - pad + dy)))
    canvas.alpha_composite(im, (int(xy[0]), int(xy[1])))


# ------------------------------------------------------------------ backgrounds
def background(theme, size):
    W, H = size
    c1, c2, acc = theme["bg1"], theme["bg2"], theme["accent"]
    style = theme["bg"]
    rnd = random.Random(theme["seed"])
    angle = theme.get("bg_angle", 90)
    import math
    sw, shh = max(2, W // 8), max(2, H // 8)
    dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    vals = [(x / sw) * dx * (W / H) + (y / shh) * dy for y in range(shh) for x in range(sw)]
    lo, hi = min(vals), max(vals)
    g = Image.new("L", (sw, shh))
    g.putdata([int(255 * (v - lo) / ((hi - lo) or 1)) for v in vals])
    g = g.resize(size, Image.BICUBIC)
    base = Image.composite(Image.new("RGB", size, c2), Image.new("RGB", size, c1), g).convert("RGBA")

    if style == "blurshot" and theme.get("bg_image") and Path(theme["bg_image"]).exists():
        shot = Image.open(theme["bg_image"]).convert("RGB")
        r = max(W / shot.width, H / shot.height) * 1.15
        shot = shot.resize((int(shot.width * r) + 1, int(shot.height * r) + 1), Image.BILINEAR)
        shot = shot.crop(((shot.width - W) // 2, (shot.height - H) // 2, (shot.width - W) // 2 + W,
                          (shot.height - H) // 2 + H)).filter(ImageFilter.GaussianBlur(H // 22))
        tint = Image.new("RGB", size, c1)
        keep = 0.22 if not theme["light"] else 0.35       # mostly the theme colour, a hint of the site
        base = Image.blend(tint, shot, keep).convert("RGBA")
        glow = Image.radial_gradient("L").resize((int(W * 1.3), int(H * 1.3)), Image.BICUBIC)
        light = Image.new("RGBA", glow.size, (*mix(c1, acc, 0.4), 0))
        light.putalpha(glow.point(lambda v: int(max(0, 90 - v * 0.6))))
        base.alpha_composite(light, (int(-W * 0.15), int(-H * 0.55)))
    elif style == "mesh":
        small = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(small)
        blobs = [acc, theme.get("accent2", acc), mix(c1, acc, 0.5)]
        for col in blobs:
            r = rnd.randint(H // 10, H // 5)
            x, y = rnd.randint(0, W // 4), rnd.randint(0, H // 4)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(*col, theme.get("blob_alpha", 70)))
        small = small.filter(ImageFilter.GaussianBlur(H // 22))
        base.alpha_composite(small.resize(size, Image.BICUBIC))
    elif style == "spotlight":
        rg = Image.radial_gradient("L").resize((int(W * 1.4), int(H * 1.6)), Image.BICUBIC)
        glow = Image.new("RGBA", rg.size, (*mix(c1, acc, 0.35), 0))
        glow.putalpha(rg.point(lambda v: int(max(0, 150 - v * 0.75))))
        base.alpha_composite(glow, (int(-W * 0.2), int(-H * 0.9)))
    elif style == "aurora":
        small = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(small)
        cols = [acc, theme.get("accent2", acc), mix(acc, (255, 255, 255), 0.3)]
        for k, col in enumerate(cols):
            y = rnd.randint(-H // 40, H // 12) + k * H // 30
            pts = [(x, y + int(math.sin(x / (W / 4) * math.pi * 2 + k) * H // 24))
                   for x in range(-20, W // 4 + 40, 20)]
            d.line(pts, fill=(*col, theme.get("blob_alpha", 70) + 30), width=H // 22)
        small = small.filter(ImageFilter.GaussianBlur(H // 30))
        base.alpha_composite(small.resize(size, Image.BICUBIC))
    elif style == "diagonal":
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        step = rnd.choice([90, 120, 160])
        col = (*mix(c1, acc, 0.5), 22 if not theme["light"] else 18)
        for x in range(-H, W + H, step):
            d.polygon([(x, 0), (x + step // 2, 0), (x + step // 2 + H, H), (x + H, H)], fill=col)
        fade = Image.linear_gradient("L").resize(size, Image.BICUBIC).point(lambda v: int(v * 0.9))
        layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", size, 0), fade))
        base.alpha_composite(layer)
    elif style in ("grid", "dots"):
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        line = (*theme["text"], 16 if theme["light"] else 14)
        step = 64 if style == "grid" else 38
        if style == "grid":
            for x in range(0, W, step):
                d.line([(x, 0), (x, H)], fill=line, width=1)
            for y in range(0, H, step):
                d.line([(0, y), (W, y)], fill=line, width=1)
        else:
            for x in range(step // 2, W, step):
                for y in range(step // 2, H, step):
                    d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(*theme["text"], 34))
        fade = Image.radial_gradient("L").resize(size, Image.BICUBIC).point(lambda v: 255 - v)
        layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", size, 0), fade))
        base.alpha_composite(layer)
    if theme.get("grain", True):                     # fine film grain: modern feel, no colour banding
        base.alpha_composite(_grain(size, 9 if not theme["light"] else 6))
    return base


_grain_cache = {}


def _grain(size, strength):
    k = (size, strength)
    if k not in _grain_cache:
        noise = Image.effect_noise(size, 64).point(lambda v: 255 if v > 128 else 0)
        layer = Image.new("RGBA", size, (255, 255, 255, 0))
        layer.putalpha(noise.point(lambda v: strength if v else 0))
        dark = Image.new("RGBA", size, (0, 0, 0, 0))
        dark.putalpha(noise.point(lambda v: 0 if v else strength))
        layer.alpha_composite(dark)
        _grain_cache[k] = layer
    return _grain_cache[k]


# ------------------------------------------------------------------ logos & text
def load_logo(path):
    if not path or not Path(path).exists():
        return None
    return Image.open(path).convert("RGBA")


def is_light(im):
    small = im.copy()
    small.thumbnail((80, 80))
    px = [p for p in small.getdata() if p[3] > 100]
    if not px:
        return False
    return sum(lum(p) for p in px) / len(px) > 200


def logo_chip(logo, height, radius=None, light_bg=None):
    """Logo on a chip that keeps it readable whatever its colours."""
    lg = logo.copy()
    lg.thumbnail((int(height * 5.5), height), Image.LANCZOS)
    pad = int(height * 0.38)
    if light_bg is None:
        light_bg = not is_light(logo)
    chip_bg = (255, 255, 255, 255) if light_bg else (22, 24, 30, 255)
    r = (lg.height + pad * 2) // 2 if radius is None else radius
    chip = rounded((lg.width + pad * 2, lg.height + pad * 2), r, chip_bg)
    chip.alpha_composite(lg, (pad, pad))
    return chip


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, make_font, max_w, start, min_size=18):
    size = start
    while size > min_size and draw.textlength(text, font=make_font(size)) > max_w:
        size -= 2
    return make_font(size)


def shadow_text(canvas, xy, text, fnt, fill, stroke=0, stroke_fill=(10, 10, 12), blur=8,
                opacity=190, offset=(5, 7), anchor="la"):
    if opacity:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((xy[0] + offset[0], xy[1] + offset[1]), text, font=fnt,
                                fill=(0, 0, 0, opacity), stroke_width=stroke,
                                stroke_fill=(0, 0, 0, opacity), anchor=anchor)
        canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(canvas).text(xy, text, font=fnt, fill=fill, stroke_width=stroke,
                                stroke_fill=stroke_fill, anchor=anchor)
