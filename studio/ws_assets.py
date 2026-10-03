"""White Screen videos, part 2: the picture library shared by the videos and the thumbnails.

  character(emotion)   the channel's masked blue-hoodie character, 27 emotions, cut out of the owner's
                       sheet (assets/whitescreen/characters/*.webp)
  yt_face(name)        30 red "YouTube face" icons from the owner's sheet (assets/whitescreen/ytfaces)
  icon(name, size)     clean 3D-style icons drawn here at any size: like, comment, bell, lock, trash...
  arrow(), ring()      a clean red arrow / hand-drawn-style highlight ring
  ui(name, w)          YouTube-interface mock-ups in YouTube's own font (Roboto), dark theme:
                       "0 Comments", the like bar, "Delete your channel?", "This video is private."...
  draw_text(...)       big display text (Airone) with a fallback font for the few characters Airone lacks
"""
import math
import random
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import config

ROOT = config.ASSETS_DIR / "whitescreen"
FONTS = config.ASSETS_DIR / "fonts"
MATERIAL = FONTS / "MaterialIcons-Regular.ttf"
RED, YT_RED, BLUE, INK, WHITE = (255, 30, 38), (255, 0, 0), (36, 110, 255), (15, 15, 15), (255, 255, 255)
GLYPH = {"thumb_up": 0xe8dc, "thumb_down": 0xe8db, "chat_bubble": 0xe0ca, "notifications": 0xe7f4,
         "lock": 0xe897, "delete": 0xe872, "hourglass_full": 0xe88c, "push_pin": 0xf10d, "favorite": 0xe87d,
         "visibility": 0xe8f4, "help": 0xe887, "warning": 0xe002, "local_fire_department": 0xef55,
         "workspace_premium": 0xe7af, "sort": 0xe164, "share": 0xe80d, "download": 0xf090,
         "playlist_add": 0xe03b, "more_vert": 0xe5d4, "play_arrow": 0xe037, "error_outline": 0xe001,
         "verified": 0xef76, "check_circle": 0xe86c, "reply": 0xe15e}


# ------------------------------------------------------------------ fonts and text
@lru_cache(maxsize=256)
def font(name, size):
    return ImageFont.truetype(str(FONTS / name), int(size))


def airone(size):
    return font("Airone.otf", size)


@lru_cache(maxsize=1)
def _airone_chars():
    from fontTools.ttLib import TTFont
    return set(TTFont(str(FONTS / "Airone.otf")).getBestCmap())


def runs(text):
    """Split text into (chunk, use_fallback) runs: Airone has letters, digits and . ! ? only."""
    have = _airone_chars()
    out = []
    for ch in text:
        fb = ord(ch) not in have and not ch.isspace()
        if out and out[-1][1] == fb:
            out[-1][0] += ch
        else:
            out.append([ch, fb])
    return [(t, f) for t, f in out]


def text_size(text, size):
    """(width, ascent-to-baseline box height) of Airone text with the fallback font."""
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    w = 0
    for t, fb in runs(text):
        f = font("Inter-Black.otf", size * 0.92) if fb else airone(size)
        w += d.textlength(t, font=f)
    top, bottom = airone(size).getbbox("HQ0")[1], airone(size).getbbox("HQ0")[3]
    return w, bottom - top


def draw_text(canvas, xy, text, size, fill=INK, stroke=0, stroke_fill=INK, anchor="mm"):
    """Airone text (fallback glyphs in Inter Black) centred on xy (anchor mm) or from its left (lm)."""
    d = ImageDraw.Draw(canvas)
    w, h = text_size(text, size)
    x = xy[0] - w / 2 if anchor == "mm" else xy[0]
    base = airone(size)
    bb = base.getbbox("HQ0", anchor="ls")              # cap height above the baseline
    baseline = xy[1] + (-bb[1]) / 2                    # caps centred on xy
    for t, fb in runs(text):
        f = font("Inter-Black.otf", size * 0.92) if fb else base
        d.text((x, baseline), t, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill, anchor="ls")
        x += d.textlength(t, font=f)
    return w, h


def fit_size(text, max_w, max_h, start=260, floor=40):
    size = start
    while size > floor:
        w, h = text_size(text, size)
        if w <= max_w and h <= max_h:
            break
        size -= 4
    return size


# ------------------------------------------------------------------ the owner's assets
@lru_cache(maxsize=64)
def _load(path):
    return Image.open(path).convert("RGBA")


def character(emotion):
    p = ROOT / "characters" / f"{emotion}.webp"
    if not p.exists():
        p = ROOT / "characters" / "shocked.webp"
    return _load(str(p)).copy()


def characters():
    return sorted(p.stem for p in (ROOT / "characters").glob("*.webp"))


def yt_face(name, crisp=True):
    """A red YouTube face. crisp: the sheet's fuzzy glow edge trimmed to a clean outline."""
    p = ROOT / "ytfaces" / f"{name}.webp"
    if not p.exists():
        p = ROOT / "ytfaces" / "sad.webp"
    im = _load(str(p)).copy()
    if crisp:
        a = im.getchannel("A").filter(ImageFilter.MinFilter(5)).point(lambda v: 255 if v > 128 else 0)
        a = a.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
        im.putalpha(a)
        im = im.crop(a.getbbox())
    return im


# which red YouTube face fits which error title
ERROR_FACE = [("privat", ["lock", "neutral", "neutral_dark"]), ("delet", ["sad", "trash", "dead_dark", "worried_dark"]),
              ("remov", ["sad", "sad_gray", "cracked"]), ("unlist", ["neutral", "dots", "neutral_dark"]),
              ("glitch", ["glitch", "cracked", "broken_play"]), ("curse", ["dead", "dead_dark", "furious"]),
              ("lock", ["lock"]), ("access", ["exclaim", "warning", "angry"]), ("secret", ["question", "dots", "shock"]),
              ("hidden", ["dots", "question", "neutral_dark"]), ("unavailable", ["exclaim", "sad_gray", "warning"]),
              ("content", ["neutral", "sad"]), ("", ["neutral", "sad", "worried_dark"])]


def error_faces(title):
    t = title.lower()
    return next(faces for key, faces in ERROR_FACE if key in t)


# ------------------------------------------------------------------ drawn icons
def glyph(name, size, color=WHITE):
    f = ImageFont.truetype(str(MATERIAL), int(size))
    im = Image.new("RGBA", (int(size * 1.4), int(size * 1.4)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((im.width / 2, im.height / 2), chr(GLYPH[name]), font=f, fill=color, anchor="mm")
    return im.crop(im.getbbox())


def _shadow(im, blur=None, offset=None, opacity=150):
    blur = blur or max(4, im.width // 18)
    offset = offset if offset is not None else max(3, im.width // 25)
    pad = blur * 3
    out = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2 + offset), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, opacity))
    sh.putalpha(ImageChops.multiply(im.getchannel("A"), Image.new("L", im.size, opacity)))
    out.alpha_composite(sh, (pad, pad + offset))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(im, (pad, pad))
    return out


def _badge(size, color, shape="circle", ring=True):
    """A glossy 3D disc / rounded square: base colour, darker bottom, soft top highlight, white rim."""
    s = size * 4                                     # draw big, scale down: smooth edges
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    box = [0, 0, s - 1, s - 1]
    dark = tuple(int(c * 0.72) for c in color)
    if shape == "circle":
        d.ellipse(box, fill=(*dark, 255))
        d.ellipse([s * 0.02, 0, s * 0.98, s * 0.94], fill=(*color, 255))
    else:
        d.rounded_rectangle(box, s // 4, fill=(*dark, 255))
        d.rounded_rectangle([0, 0, s - 1, s * 0.94], s // 4, fill=(*color, 255))
    hl = Image.new("L", (s, s), 0)
    ImageDraw.Draw(hl).ellipse([s * 0.12, s * 0.04, s * 0.88, s * 0.5], fill=70)
    hl = hl.filter(ImageFilter.GaussianBlur(s // 20))
    white = Image.new("RGBA", (s, s), (255, 255, 255, 0))
    white.putalpha(ImageChops.multiply(hl, base.getchannel("A")))
    base.alpha_composite(white)
    if ring:
        rim = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rim)
        w = s // 26
        if shape == "circle":
            rd.ellipse([w // 2, w // 2, s - w // 2 - 1, s - w // 2 - 1], outline=(255, 255, 255, 235), width=w)
        else:
            rd.rounded_rectangle([w // 2, w // 2, s - w // 2 - 1, s - w // 2 - 1], s // 4, outline=(255, 255, 255, 235), width=w)
        base.alpha_composite(rim)
    return base.resize((size, size), Image.LANCZOS)


ICON_STYLE = {   # name -> (glyph, badge colour, glyph colour, shape)
    "like": ("thumb_up", BLUE, WHITE, "circle"), "dislike": ("thumb_down", (60, 60, 66), WHITE, "circle"),
    "comment": ("chat_bubble", (30, 30, 34), WHITE, "circle"), "bell": ("notifications", (255, 196, 0), WHITE, "circle"),
    "lock": ("lock", RED, WHITE, "rounded"), "trash": ("delete", RED, WHITE, "rounded"),
    "hourglass": ("hourglass_full", RED, WHITE, "rounded"), "pin": ("push_pin", (255, 186, 0), WHITE, "circle"),
    "heart": ("favorite", RED, WHITE, "circle"), "eye": ("visibility", (28, 28, 32), WHITE, "circle"),
    "question": ("help", (28, 28, 32), WHITE, "circle"), "warning": ("warning", (255, 196, 0), INK, "rounded"),
    "fire": ("local_fire_department", (255, 110, 0), WHITE, "circle"), "crown": ("workspace_premium", (255, 186, 0), WHITE, "circle"),
}
FACE_ICON = {"sad_face": "sad", "dead_face": "dead", "glitch_face": "glitch", "cracked_face": "cracked",
             "crying_face": "crying", "angry_face": "furious", "happy_face": "happy", "dots_face": "dots"}


def icon(name, size):
    """A finished icon (with shadow), about `size` px wide. 'subscribe' is the red button."""
    if name in FACE_ICON:
        im = yt_face(FACE_ICON[name])
        im = im.resize((size, int(size * im.height / im.width)), Image.LANCZOS)
        return _shadow(im)
    if name == "subscribe":
        return _shadow(subscribe_button(size))
    g, color, gcolor, shape = ICON_STYLE.get(name, ICON_STYLE["like"])
    b = _badge(size, color, shape)
    gl = glyph(g, size * 0.56, gcolor)
    b.alpha_composite(gl, ((size - gl.width) // 2, (size - gl.height) // 2 - size // 40))
    return _shadow(b)


def subscribe_button(width, subscribed=False):
    h = int(width * 0.27)
    s = 3
    im = Image.new("RGBA", (width * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bg = (236, 236, 236) if subscribed else (255, 0, 0)
    fg = INK if subscribed else WHITE
    d.rounded_rectangle([0, 0, width * s - 1, h * s - 1], h * s // 2, fill=bg)
    # the YouTube play badge
    px, py, pw, ph = h * s * 0.35, h * s * 0.24, h * s * 0.72, h * s * 0.52
    d.rounded_rectangle([px, py, px + pw, py + ph], ph * 0.28, fill=fg)
    tri = [(px + pw * 0.4, py + ph * 0.27), (px + pw * 0.4, py + ph * 0.73), (px + pw * 0.68, py + ph * 0.5)]
    d.polygon(tri, fill=bg)
    label = "SUBSCRIBED" if subscribed else "SUBSCRIBE"
    f = font("Roboto-Black.ttf", h * s * 0.42)
    d.text((px + pw + h * s * 0.28, h * s / 2), label, font=f, fill=fg, anchor="lm")
    return im.resize((width, h), Image.LANCZOS)


def cursor(size, hand=False):
    """The classic white mouse pointer with a black outline."""
    s = 4
    im = Image.new("RGBA", (size * s, int(size * 1.5) * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = size * s
    pts = [(0, 0), (0, k * 1.15), (k * 0.3, k * 0.86), (k * 0.52, k * 1.36), (k * 0.68, k * 1.29),
           (k * 0.47, k * 0.8), (k * 0.86, k * 0.8)]
    d.polygon(pts, fill=INK)
    inner = [(x * 0.8 + k * 0.08, y * 0.8 + k * 0.12) for x, y in pts]
    d.polygon(inner, fill=WHITE)
    return im.resize((size, int(size * 1.5)), Image.LANCZOS)


def arrow(length, color=RED, curve=0.35, width=None, outline=INK):
    """A clean, thick curved arrow pointing right (rotate as needed), with an even dark outline."""
    s = 3
    L = length * s
    w = (width or length * 0.12) * s
    H = int(L * 0.8)
    pad = int(w * 2)
    mask = Image.new("L", (int(L * 1.15) + pad * 2, H + pad * 2), 0)
    d = ImageDraw.Draw(mask)
    pts = []
    n = 48
    for i in range(n + 1):
        t = i / n
        pts.append((pad + L * 0.03 + t * L * 0.74, pad + H * 0.7 - math.sin(t * math.pi * 0.92) * H * curve))
    d.line(pts, fill=255, width=int(w), joint="curve")
    r = w / 2
    d.ellipse([pts[0][0] - r, pts[0][1] - r, pts[0][0] + r, pts[0][1] + r], fill=255)
    ang = math.atan2(pts[-1][1] - pts[-6][1], pts[-1][0] - pts[-6][0])
    hl, hw = w * 2.3, w * 1.55
    bx, by = pts[-1]
    tip = (bx + math.cos(ang) * hl, by + math.sin(ang) * hl)
    side = lambda k: (bx + math.cos(ang + k * math.pi / 2) * hw - math.cos(ang) * w * 0.15,
                      by + math.sin(ang + k * math.pi / 2) * hw - math.sin(ang) * w * 0.15)
    d.polygon([tip, side(1), side(-1)], fill=255)
    grow = int(max(3, w * 0.22)) | 1
    edge = mask.filter(ImageFilter.MaxFilter(grow * 2 + 1)) if outline else None
    im = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    if edge is not None:
        im.paste(Image.new("RGBA", mask.size, (*outline, 255)), (0, 0), edge)
    im.paste(Image.new("RGBA", mask.size, (*color, 255)), (0, 0), mask)
    im = im.crop(im.getbbox())
    return im.resize((max(1, im.width // s), max(1, im.height // s)), Image.LANCZOS)


def ring(w, h, color=RED, width=None, seed=0):
    """A marker-style highlight ring (slightly uneven, overshooting at the end), like a hand-drawn circle."""
    s = 3
    rnd = random.Random(seed)
    W, H = int(w * s), int(h * s)
    lw = int((width or max(6, min(w, h) * 0.07)) * s)
    im = Image.new("RGBA", (W + lw * 2, H + lw * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = im.width / 2, im.height / 2
    pts = []
    start = rnd.uniform(-0.6, 0.2)
    for i in range(80):
        t = start + i / 79 * (2 * math.pi + 0.5)
        r = 1 + 0.03 * math.sin(t * 3 + rnd.random())
        pts.append((cx + math.cos(t) * W / 2 * r, cy + math.sin(t) * H / 2 * r * (1 + 0.04 * (i / 79))))
    d.line(pts, fill=color, width=lw, joint="curve")
    return im.resize((im.width // s, im.height // s), Image.LANCZOS)


# ------------------------------------------------------------------ YouTube interface mock-ups (dark theme)
YT_BG, YT_PANEL, YT_TEXT, YT_MUTED, YT_PILL = (15, 15, 15), (33, 33, 33), (241, 241, 241), (170, 170, 170), (39, 39, 39)


def _avatar(size):
    ch = character("wave")
    s = min(ch.width, ch.height)
    face = ch.crop(((ch.width - s) // 2, 0, (ch.width + s) // 2, s)).resize((size, size), Image.LANCZOS)
    bg = Image.new("RGBA", (size, size), (110, 190, 255, 255))
    bg.alpha_composite(face)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    bg.putalpha(mask.resize((size, size), Image.LANCZOS))
    return bg


def _pill(d, xy, text, f, fill=YT_PILL, fg=YT_TEXT, icon_name=None, icon_img=None):
    x, y, h = xy
    pad = h * 0.45
    tw = d.textlength(text, font=f) if text else 0
    iw = h * 0.5 if (icon_name or icon_img) else 0
    w = pad * 2 + iw + (h * 0.22 if iw and text else 0) + tw
    d.rounded_rectangle([x, y, x + w, y + h], h / 2, fill=fill)
    return x + w, (x + pad, y + h / 2, iw, tw)


def ui(name, width, title="", count="0", channel=None, note=""):
    """A YouTube-interface card (dark theme) as an RGBA image `width` px wide."""
    s = 2
    W = width * s
    ch_name = channel or config.CHANNEL_NAME
    reg, med, bold = (lambda z: font("Roboto-Regular.ttf", z * s)), (lambda z: font("Roboto-Medium.ttf", z * s)), (lambda z: font("Roboto-Bold.ttf", z * s))
    u = width / 100                                     # 1% of the width, in output pixels

    def canvas(h):
        im = Image.new("RGBA", (W, int(h * s)), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle([0, 0, W - 1, int(h * s) - 1], int(3 * u * s), fill=(*YT_BG, 255),
                                             outline=(60, 60, 60, 255), width=max(2, int(0.35 * u * s)))
        return im, ImageDraw.Draw(im)

    def paste_glyph(im, g, x, y, size, color=YT_TEXT):
        gl = glyph(g, size * s, color)
        im.alpha_composite(gl, (int(x * s), int(y * s - gl.height / 2)))
        return gl.width / s

    if name in ("comments_zero", "pinned_comment"):
        h = width * (0.56 if name == "comments_zero" else 0.44)
        im, d = canvas(h)
        d.text((5 * u * s, 8 * u * s), "Comments", font=bold(6.2 * u), fill=YT_TEXT, anchor="lm")
        cw = d.textlength("Comments", font=bold(6.2 * u)) / s
        d.text(((5 * u + cw + 2.5 * u) * s, 8 * u * s), count, font=reg(6.2 * u), fill=YT_MUTED, anchor="lm")
        paste_glyph(im, "sort", 74 * u, 8 * u, 5 * u)
        d.text((81 * u * s, 8 * u * s), "Sort by", font=med(4.4 * u), fill=YT_TEXT, anchor="lm")
        if name == "comments_zero":
            av = _avatar(int(9 * u * s))
            im.alpha_composite(av, (int(5 * u * s), int(15 * u * s)))
            d.text((17 * u * s, 19.5 * u * s), "Add a comment...", font=reg(5 * u), fill=YT_MUTED, anchor="lm")
            d.line([(17 * u * s, 24 * u * s), (95 * u * s, 24 * u * s)], fill=(90, 90, 90), width=max(2, int(0.3 * u * s)))
            bub = Image.new("RGBA", (int(13 * u * s), int(13 * u * s)), (0, 0, 0, 0))
            ImageDraw.Draw(bub).ellipse([0, 0, bub.width - 1, bub.height - 1], fill=(48, 48, 48, 255))
            g = glyph("chat_bubble", 6.5 * u * s, (200, 200, 200))
            bub.alpha_composite(g, ((bub.width - g.width) // 2, (bub.height - g.height) // 2))
            im.alpha_composite(bub, (int((50 - 6.5) * u * s), int(28 * u * s)))
            d.text((50 * u * s, 46 * u * s), "No comments yet", font=med(5 * u), fill=YT_TEXT, anchor="mm")
            d.text((50 * u * s, 51 * u * s), "Be the first to comment.", font=reg(3.6 * u), fill=YT_MUTED, anchor="mm")
        else:
            av = _avatar(int(9 * u * s))
            im.alpha_composite(av, (int(5 * u * s), int(17 * u * s)))
            paste_glyph(im, "push_pin", 17 * u, 18.5 * u, 3.6 * u, YT_MUTED)
            d.text((21.5 * u * s, 18.5 * u * s), f"Pinned by @{ch_name}", font=reg(3.6 * u), fill=YT_MUTED, anchor="lm")
            d.text((17 * u * s, 25 * u * s), "@viewer  ·  1 minute ago", font=reg(3.6 * u), fill=YT_MUTED, anchor="lm")
            d.text((17 * u * s, 32 * u * s), title or "FIRST!", font=bold(6.4 * u), fill=YT_TEXT, anchor="lm")
            paste_glyph(im, "thumb_up", 17 * u, 38.5 * u, 4 * u)
            d.text((23 * u * s, 38.5 * u * s), "1", font=reg(3.8 * u), fill=YT_MUTED, anchor="lm")
            paste_glyph(im, "thumb_down", 29 * u, 38.5 * u, 4 * u)
            d.text((37 * u * s, 38.5 * u * s), "Reply", font=med(3.8 * u), fill=YT_TEXT, anchor="lm")
        return im.resize((width, int(h)), Image.LANCZOS)

    if name in ("likes_zero", "likes_and_comments_zero"):
        h = width * (0.36 if name == "likes_zero" else 0.5)
        im, d = canvas(h)
        t = title or "This Video Has 0 Likes"
        tsz = 5.6 * u
        while d.textlength(t, font=bold(tsz)) > 90 * u * s and tsz > 3 * u:
            tsz -= 0.2 * u
        d.text((5 * u * s, 8 * u * s), t, font=bold(tsz), fill=YT_TEXT, anchor="lm")
        av = _avatar(int(9 * u * s))
        im.alpha_composite(av, (int(5 * u * s), int(13 * u * s)))
        d.text((16.5 * u * s, 15.5 * u * s), ch_name, font=med(4.4 * u), fill=YT_TEXT, anchor="lm")
        nw = d.textlength(ch_name, font=med(4.4 * u)) / s
        paste_glyph(im, "check_circle", 16.5 * u + nw + 1.2 * u, 15.5 * u, 3.4 * u, YT_MUTED)
        d.text((16.5 * u * s, 20 * u * s), "1.27M subscribers", font=reg(3.4 * u), fill=YT_MUTED, anchor="lm")
        d.rounded_rectangle([74 * u * s, 13.5 * u * s, 95 * u * s, 21.5 * u * s], 4 * u * s, fill=(241, 241, 241))
        d.text((84.5 * u * s, 17.5 * u * s), "Subscribe", font=med(3.8 * u), fill=INK, anchor="mm")
        y = 26 * u
        d.rounded_rectangle([5 * u * s, y * s, 30 * u * s, (y + 8 * u) * s], 4 * u * s, fill=YT_PILL)
        paste_glyph(im, "thumb_up", 8 * u, y + 4 * u, 4.4 * u)
        d.text((15 * u * s, (y + 4 * u) * s), count, font=med(4.2 * u), fill=YT_TEXT, anchor="lm")
        d.line([(21 * u * s, (y + 1.6 * u) * s), (21 * u * s, (y + 6.4 * u) * s)], fill=(80, 80, 80), width=max(2, int(0.3 * u * s)))
        paste_glyph(im, "thumb_down", 23.5 * u, y + 4 * u, 4.4 * u)
        x = 33 * u
        for g, label in (("share", "Share"), ("download", "Download"), ("playlist_add", "Save")):
            tw = d.textlength(label, font=med(3.6 * u)) / s
            d.rounded_rectangle([x * s, y * s, (x + tw + 10 * u) * s, (y + 8 * u) * s], 4 * u * s, fill=YT_PILL)
            paste_glyph(im, g, x + 2.4 * u, y + 4 * u, 3.8 * u)
            d.text(((x + 7.4 * u) * s, (y + 4 * u) * s), label, font=med(3.6 * u), fill=YT_TEXT, anchor="lm")
            x += tw + 12 * u
        if name == "likes_and_comments_zero":
            d.rounded_rectangle([5 * u * s, 38 * u * s, 95 * u * s, 47 * u * s], 2.5 * u * s, fill=YT_PANEL)
            d.text((8 * u * s, 41 * u * s), "Comments", font=bold(3.8 * u), fill=YT_TEXT, anchor="lm")
            d.text((8 * u * s, 44.6 * u * s), "No comments yet", font=reg(3.4 * u), fill=YT_MUTED, anchor="lm")
        return im.resize((width, int(h)), Image.LANCZOS)

    if name == "delete_channel":
        h = width * 0.5
        im, d = canvas(h)
        av = _avatar(int(16 * u * s))
        im.alpha_composite(av, (int(5 * u * s), int(5 * u * s)))
        d.text((25 * u * s, 10 * u * s), ch_name, font=bold(6 * u), fill=YT_TEXT, anchor="lm")
        d.text((25 * u * s, 16.5 * u * s), f"@{ch_name.upper()[:4]} · 1.27M subscribers", font=reg(3.6 * u), fill=YT_MUTED, anchor="lm")
        d.rounded_rectangle([10 * u * s, 25 * u * s, 90 * u * s, 47 * u * s], 2.5 * u * s, fill=YT_PANEL, outline=(70, 70, 70), width=2)
        d.text((14 * u * s, 30 * u * s), "Delete your channel?", font=bold(5 * u), fill=YT_TEXT, anchor="lm")
        d.text((14 * u * s, 35 * u * s), "This will permanently delete your channel and all of its content.",
               font=reg(2.6 * u), fill=YT_MUTED, anchor="lm")
        d.rounded_rectangle([55 * u * s, 38.5 * u * s, 86 * u * s, 44.5 * u * s], 1.2 * u * s, fill=(204, 0, 0))
        d.text((70.5 * u * s, 41.5 * u * s), "DELETE CHANNEL", font=bold(3.4 * u), fill=WHITE, anchor="mm")
        c = cursor(int(5 * u * s))
        im.alpha_composite(c, (int(80 * u * s), int(41 * u * s)))
        return im.resize((width, int(h)), Image.LANCZOS)

    if name == "delete_video":
        h = width * 0.3
        im = Image.new("RGBA", (W, int(h * s)), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, W - 1, int(h * s) - 1], int(5 * u * s), fill=(220, 20, 30), outline=WHITE, width=int(1.2 * u * s))
        g = glyph("delete", 18 * u * s, WHITE)
        im.alpha_composite(g, (int(7 * u * s), int((h * s - g.height) / 2)))
        label = title or "DELETE VIDEO"
        fsz = 11 * u * s
        while d.textlength(label, font=font("Roboto-Black.ttf", fsz)) > 62 * u * s and fsz > 10:
            fsz -= 2
        d.text((31 * u * s, h * s / 2), label, font=font("Roboto-Black.ttf", fsz), fill=WHITE, anchor="lm")
        c = cursor(int(9 * u * s))
        im = im.resize((width, int(h)), Image.LANCZOS)
        out = Image.new("RGBA", (int(width * 1.06), int(h * 1.3)), (0, 0, 0, 0))
        out.alpha_composite(im)
        cc = c.resize((c.width // s, c.height // s), Image.LANCZOS)
        out.alpha_composite(cc, (int(width * 0.86), int(h * 0.6)))
        return out

    if name in ("private_player", "video_unavailable"):
        h = width * 9 / 16
        im = Image.new("RGBA", (W, int(h * s)), (0, 0, 0, 255))
        d = ImageDraw.Draw(im)
        if name == "private_player":
            face = yt_face("lock")
            face = face.resize((int(34 * u * s), int(34 * u * s * face.height / face.width)), Image.LANCZOS)
            im.alpha_composite(face, (int((W - face.width) / 2), int(h * s * 0.22)))
            d.text((W / 2, h * s * 0.75), note or "This video is private.", font=med(5 * u), fill=YT_TEXT, anchor="mm")
            d.text((W / 2, h * s * 0.83), "Only the person who uploaded the video can watch it.", font=reg(3 * u), fill=YT_MUTED, anchor="mm")
        else:
            d.ellipse([16 * u * s, h * s * 0.3, 36 * u * s, h * s * 0.3 + 20 * u * s], outline=YT_MUTED, width=int(1.6 * u * s))
            d.text((26 * u * s, h * s * 0.3 + 10 * u * s), "!", font=bold(13 * u), fill=YT_MUTED, anchor="mm")
            d.text((42 * u * s, h * s * 0.44), "Video unavailable", font=med(6.4 * u), fill=YT_TEXT, anchor="lm")
            d.text((42 * u * s, h * s * 0.54), note or "This video is private.", font=reg(3.8 * u), fill=YT_MUTED, anchor="lm")
        return im.resize((width, int(h)), Image.LANCZOS)

    if name == "view_count":
        h = width * 0.26
        im = Image.new("RGBA", (W, int(h * s)), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, W - 1, int(h * s) - 1], int(5 * u * s), fill=(18, 18, 18), outline=RED, width=int(1.6 * u * s))
        g = glyph("visibility", 15 * u * s, WHITE)
        im.alpha_composite(g, (int(8 * u * s), int((h * s - g.height) / 2)))
        d.text((30 * u * s, h * s / 2), f"{count} VIEW" + ("" if count == "1" else "S"), font=font("Roboto-Black.ttf", 12 * u * s),
               fill=WHITE, anchor="lm")
        return im.resize((width, int(h)), Image.LANCZOS)

    raise ValueError(f"unknown ui {name}")


UI_NAMES = ["comments_zero", "likes_zero", "likes_and_comments_zero", "pinned_comment", "delete_video",
            "delete_channel", "private_player", "video_unavailable", "view_count"]


def yt_face_drawn(kind, width, color=(235, 18, 24)):
    """A crisp, glossy red YouTube-logo face drawn at any size (for the big thumbnail icon).
    kind: lock, sad, neutral, worried, dead, trash, hourglass, exclaim, question, dots, crying, angry, glitch."""
    s = 3
    Wd, Hd = width * s, int(width * 0.7) * s
    pad = Wd // 14
    im = Image.new("RGBA", (Wd + pad * 2, Hd + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = [pad, pad, pad + Wd, pad + Hd]
    r = int(Hd * 0.3)
    dark = tuple(int(c * 0.62) for c in color[:3])
    gray = kind in ("dots",)
    body = (120, 120, 124) if gray else color
    dark = (70, 70, 74) if gray else dark
    d.rounded_rectangle([box[0], box[1] + Hd * 0.04, box[2], box[3]], r, fill=(*dark, 255))       # 3D bottom edge
    d.rounded_rectangle([box[0], box[1], box[2], box[3] - Hd * 0.05], r, fill=(*body, 255))
    hl = Image.new("L", im.size, 0)                                                                 # top highlight
    ImageDraw.Draw(hl).rounded_rectangle([box[0] + Wd * 0.06, box[1] + Hd * 0.04, box[2] - Wd * 0.06, box[1] + Hd * 0.45],
                                         r, fill=60)
    hl = ImageChops.multiply(hl.filter(ImageFilter.GaussianBlur(Wd // 40)), im.getchannel("A"))
    white = Image.new("RGBA", im.size, (255, 255, 255, 0))
    white.putalpha(hl)
    im.alpha_composite(white)
    cx, cy = pad + Wd / 2, pad + Hd * 0.47
    u = Wd / 100
    W_ = (255, 255, 255, 255)
    eye = u * 5.2

    def eyes(y=cy - 7 * u, dx=15 * u):
        for sx in (-1, 1):
            d.ellipse([cx + sx * dx - eye, y - eye * 1.15, cx + sx * dx + eye, y + eye * 1.15], fill=W_)

    def mouth_arc(up, y=cy + 12 * u, w=20 * u, h=9 * u):
        lw = int(5.4 * u)
        if up:      # sad: arc bulging up
            d.arc([cx - w, y - h, cx + w, y + h * 1.6], 200, 340, fill=W_, width=lw)
        else:
            d.arc([cx - w, y - h * 1.6, cx + w, y + h], 20, 160, fill=W_, width=lw)

    def glyph_center(name, size_u):
        g = glyph(name, size_u * u, (255, 255, 255))
        im.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))

    if kind == "lock":
        glyph_center("lock", 56)
    elif kind == "trash":
        glyph_center("delete", 56)
    elif kind == "hourglass":
        glyph_center("hourglass_full", 54)
    elif kind == "exclaim":
        glyph_center("error_outline", 56)
    elif kind == "question":
        glyph_center("help", 54)
    elif kind == "dots":
        for k in (-1, 0, 1):
            d.ellipse([cx + k * 18 * u - 6 * u, cy - 6 * u, cx + k * 18 * u + 6 * u, cy + 6 * u], fill=W_)
    elif kind == "dead":
        lw = int(5.4 * u)
        for sx in (-1, 1):
            ex, ey = cx + sx * 15 * u, cy - 7 * u
            d.line([ex - 5 * u, ey - 5 * u, ex + 5 * u, ey + 5 * u], fill=W_, width=lw)
            d.line([ex - 5 * u, ey + 5 * u, ex + 5 * u, ey - 5 * u], fill=W_, width=lw)
        d.line([cx - 13 * u, cy + 13 * u, cx + 13 * u, cy + 13 * u], fill=W_, width=lw)
    else:
        eyes()
        lw = int(5.4 * u)
        if kind in ("neutral",):
            d.line([cx - 15 * u, cy + 15 * u, cx + 15 * u, cy + 11 * u], fill=W_, width=lw)
        elif kind == "angry":
            for sx in (-1, 1):
                d.line([cx + sx * 24 * u, cy - 17 * u, cx + sx * 8 * u, cy - 11 * u], fill=W_, width=lw)
            mouth_arc(True)
        elif kind == "worried":
            for sx in (-1, 1):
                d.line([cx + sx * 22 * u, cy - 14 * u, cx + sx * 9 * u, cy - 19 * u], fill=W_, width=lw)
            mouth_arc(True)
        elif kind == "crying":
            mouth_arc(True)
            for sx in (-1, 1):
                x = cx + sx * 15 * u
                d.rounded_rectangle([x - 3.5 * u, cy - 2 * u, x + 3.5 * u, cy + 22 * u], int(3.5 * u), fill=(90, 175, 255, 255))
        else:                                    # sad (and glitch: sad + cut)
            mouth_arc(True)
    if kind == "glitch":
        arr = im.copy()
        for k in range(5):
            y0 = int(pad + Hd * (0.15 + 0.17 * k))
            band = arr.crop((0, y0, im.width, y0 + int(Hd * 0.06)))
            im.paste(Image.new("RGBA", band.size, (0, 0, 0, 0)), (0, y0))
            im.alpha_composite(band, (int((k % 2 * 2 - 1) * Wd * 0.03), y0))
    return im.resize((im.width // s, im.height // s), Image.LANCZOS)


DRAWN_FACE = [("privat", ["lock", "neutral"]), ("delet", ["sad", "trash", "dead"]), ("remov", ["sad", "worried"]),
              ("unlist", ["neutral", "dots"]), ("glitch", ["glitch", "dead"]), ("curse", ["dead", "angry"]),
              ("lock", ["lock"]), ("access", ["exclaim", "angry"]), ("secret", ["question", "dots"]),
              ("hidden", ["dots", "question"]), ("unavailable", ["exclaim", "sad"]), ("content", ["neutral", "sad"]),
              ("", ["neutral", "sad", "worried"])]


def drawn_faces(title):
    t = title.lower()
    return next(f for key, f in DRAWN_FACE if key in t)


# ------------------------------------------------------------------ the big asset library
# emoji/    355 glossy 3D emoji (Microsoft Fluent Emoji, MIT), index.json = the words each one fits
# objects/  unique YouTube-style 3D objects drawn by Gemini (tools/ws_hd_assets.py)
# ui/       the owner's UI sheet cut out: subscribe buttons, bells, like/dislike, share, play, LIVE...
# arrows/   the owner's arrow sheet cut out, each arrow with its tail and tip (arrows.json), rings, bursts
import json  # noqa: E402

import numpy as np  # noqa: E402


@lru_cache(maxsize=1)
def emoji_index():
    p = ROOT / "emoji" / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _names(folder):
    return sorted(p.stem for p in (ROOT / folder).glob("*.webp"))


@lru_cache(maxsize=1)
def library():
    """Every picture asset by name -> path (objects first, then the UI pieces, then emoji)."""
    out = {}
    for folder in ("emoji", "ui", "objects"):                    # later folders win a name clash
        for n in _names(folder):
            out[n] = ROOT / folder / f"{n}.webp"
    return out


# icon names used by scripts -> the best picture for it, in order of preference
ICON_ASSET = {
    "like": ["like_button", "like_blue", "thumbs_up"], "dislike": ["dislike_button", "dislike_red", "thumbs_down"],
    "comment": ["comment_bubble", "speech_balloon"], "bell": ["bell_ringing", "bell_gold_ring", "bell"],
    "subscribe": ["subscribe_red", "subscribe_red_cursor"], "lock": ["padlock_red", "locked"],
    "trash": ["trash_can", "wastebasket"], "hourglass": ["hourglass_red", "hourglass_not_done"],
    "pin": ["pin_red", "pushpin"], "heart": ["heart_glossy", "red_heart"], "eye": ["eye_glowing", "eyes"],
    "question": ["question_3d", "red_question_mark"], "warning": ["warning_red", "warning"],
    "fire": ["fire_big", "fire"], "crown": ["crown_gold", "crown"], "trophy": ["trophy_gold", "trophy"],
    "clock": ["alarm_clock_red", "alarm_clock"], "calendar": ["calendar_x", "tear_off_calendar"],
    "play": ["play_red", "play_big"], "share": ["share_red_circle"], "live": ["live"],
}


def asset_names():
    return sorted(set(library()) | set(ICON_ASSET))


def find_asset(word):
    """The picture that goes with a word ("deleted" -> trash, "100" -> hundred points...), or None."""
    w = "".join(ch for ch in str(word).lower() if ch.isalnum())
    if not w:
        return None
    if w in ICON_ASSET:
        return w
    lib = library()
    if w in lib:
        return w
    for name in lib:                                            # objects/ui by their own name
        if name.split("_")[0] == w and not (ROOT / "emoji" / f"{name}.webp").exists():
            return name
    for name, words in emoji_index().items():
        if w in words or (len(w) > 4 and w.rstrip("s") in words):
            return name
    return None


def picture(name, size, shadow=True):
    """Any asset (an ICON_ASSET name, a library name or a drawn icon) fitted into a size x size box."""
    path = None
    cands = ICON_ASSET.get(name, []) + [name]
    for part in str(name).split("_"):                           # "comment_bubble" -> the comment pictures
        cands += ICON_ASSET.get(part, [])
        found = find_asset(part)
        if found:
            cands += ICON_ASSET.get(found, []) + [found]
    for cand in cands:
        if cand in library():
            path = library()[cand]
            break
    if path is None:
        return icon(name if name in ICON_STYLE or name in FACE_ICON or name == "subscribe" else "question", size)
    im = _load(str(path)).copy()
    k = size / max(im.width, im.height)
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    return _shadow(im) if shadow else im


@lru_cache(maxsize=1)
def _arrow_meta():
    p = ROOT / "arrows" / "arrows.json"
    return json.loads(p.read_text()) if p.exists() else {}


ARROW_STYLES = {   # which sheet arrows suit which look
    "bold": ["bold_swoop", "bold_up", "bold_straight", "bold_block", "bold_down", "bold_curl_down"],
    "clean": ["arc", "arc2", "arc_down", "swoop_white", "curl_down", "curve_down", "hook_up", "block"],
    "brush": ["brush_right", "brush_right2", "brush_up", "brush_arc", "brush_long"],
    "fun": ["loop", "loop2", "dashed", "dashed_arc", "wavy", "zigzag", "elbow"],
}


def point_arrow(canvas, start, end, name=None, seed=0, style=None, max_thick=None):
    """Paste one of the owner's arrows so its tail is at `start` and its tip lands exactly on `end`.
    The arrow is mirrored instead of turned upside down, so its curve and shading stay natural."""
    meta = _arrow_meta()
    if not meta:                                                # no sheet: the drawn arrow
        L = math.dist(start, end)
        im = arrow(int(L / 0.9))
        ang = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
        im = im.rotate(-ang, Image.BICUBIC, expand=True)
        canvas.alpha_composite(im, (int(end[0] - im.width / 2 - (end[0] - start[0]) / 2),
                                    int(end[1] - im.height / 2 - (end[1] - start[1]) / 2)))
        return
    rnd = random.Random(seed)
    if name not in meta:                                        # the arrows that need the least turning
        pool = [n for n in (ARROW_STYLES.get(style) or meta) if n in meta]
        tx, ty = end[0] - start[0], end[1] - start[1]
        want = math.atan2(ty, abs(tx))                          # mirrored to point right

        def turn_of(n):
            vx, vy = meta[n]["tip"][0] - meta[n]["tail"][0], meta[n]["tip"][1] - meta[n]["tail"][1]
            return abs((want - math.atan2(vy, vx) + math.pi) % (2 * math.pi) - math.pi)
        best = sorted(pool, key=turn_of)[:3]
        name = rnd.choice(best)
    m = meta[name]
    im = _load(str(ROOT / "arrows" / f"{name}.webp")).copy()
    tail, tip = np.array(m["tail"], float), np.array(m["tip"], float)
    target = np.array(end, float) - np.array(start, float)
    if target[0] < 0:                                           # pointing left: mirror, don't flip over
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
        tail[0], tip[0] = im.width - tail[0], im.width - tip[0]
    v = tip - tail
    k = np.linalg.norm(target) / max(1.0, np.linalg.norm(v))
    if max_thick:                                               # never fatter than max_thick px
        k = min(k, max_thick / max(1.0, min(im.width, im.height)))
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    tail, tip = tail * k, tip * k
    v = tip - tail
    turn = math.atan2(target[1], target[0]) - math.atan2(v[1], v[0])   # radians, y down
    deg = -math.degrees(turn)                                   # PIL turns counter-clockwise on screen
    c = np.array([im.width / 2, im.height / 2])
    rot = im.rotate(deg, Image.BICUBIC, expand=True)
    c2 = np.array([rot.width / 2, rot.height / 2])
    cs, sn = math.cos(turn), math.sin(turn)
    d = tip - c
    tip2 = c2 + np.array([cs * d[0] - sn * d[1], sn * d[0] + cs * d[1]])
    canvas.alpha_composite(rot, (int(round(end[0] - tip2[0])), int(round(end[1] - tip2[1]))))


def mark(name, width):
    """A ring, burst, underline or cross from the owner's sheet, `width` px wide."""
    p = ROOT / "arrows" / f"{name}.webp"
    im = _load(str(p)).copy()
    return im.resize((width, max(1, int(im.height * width / im.width))), Image.LANCZOS)


def sheet_ring(w, h, seed=0):
    """A hand-drawn ring from the owner's sheet stretched around a w x h spot."""
    rings = [n for n in _names("arrows") if n.startswith("ring_") and n not in ("ring_arrow", "ring_dashed")]
    if not rings:
        return ring(w, h, seed=seed)
    im = _load(str(ROOT / "arrows" / f"{random.Random(seed).choice(rings)}.webp")).copy()
    return im.resize((int(w * 1.22 + 34), int(h * 1.55 + 30)), Image.LANCZOS)
