"""White Screen videos, part 4: three 16:9 thumbnails per video, in the channel's own look.

Modelled on the channel's best performers: a near-black background, ONE clean icon in the middle and
the title underneath, nothing else.

  card      a glossy YouTube-red (or dark grey) rounded tile with a white symbol - a count badge, a red X
            or a "no" sign on its corner when the title calls for it - or a pill counter ("👍 0"), or a
            3D emoji (the heart); under it the title: a white line + a bigger red line ("This Video Has"
            / "5 Comments"), the title in brackets ("[Locked Video]"), or YouTube's own wording in its
            own font ("This video is unlisted" + the small grey line under it)
  sad       the big red YouTube sad face alone ([Removed Video])
  glitch    the same face glitched: RGB split, torn slices, static ([Glitched Video], [Cursed Video])
  counters  YouTube's like | comment counters, both 0
  crossed   a counter pill ("💬 1,000") struck out with a big red brush X

Each title gets a fitting design (see _designs); the old look is in ws_thumb_classic.py.
"""
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import ws_assets as A

TW, TH = 1280, 720
SS = 3                                                    # supersampling for smooth shapes
BG = (10, 10, 11)
RED_TEXT, WHITE, GREY = (255, 34, 34), (255, 255, 255), (170, 170, 170)
TILES = {"red": ((255, 66, 62), (206, 0, 6)), "dark": ((70, 70, 72), (34, 34, 36))}
HEAD = "InterDisplay-Black.otf"                            # the big title lines
UI_MAIN, UI_SUB = "Roboto-Medium.ttf", "Roboto-Regular.ttf"   # YouTube's own wording
MG = {   # Material Icons codepoints
    "delete": 0xe872, "lock": 0xe897, "chat": 0xe0b7, "chat_outline": 0xe0cb, "thumb_up": 0xe8dc,
    "thumb_outline": 0xe9f3, "link": 0xe157, "block": 0xe14b, "pause": 0xe034, "bar_chart": 0xe26b,
    "replay": 0xe042, "visibility_off": 0xe8f5, "visibility": 0xe8f4, "timer": 0xe425,
    "hourglass": 0xe88c, "face": 0xe87c, "cake": 0xe7e9, "screen_rotation": 0xe1c1,
    "error_outline": 0xe001, "close": 0xe5cd, "verified": 0xef76, "push_pin": 0xf10d,
    "favorite": 0xe87d, "help": 0xe887,
}
EMOJI = {   # tile symbol -> the 3D emoji used for the third option
    "delete": "wastebasket", "lock": "locked", "hourglass": "hourglass_not_done", "timer": "stopwatch",
    "push_pin": "pushpin", "favorite": "red_heart", "visibility": "eye", "bar_chart": "bar_chart",
    "cake": "birthday_cake", "link": "link", "block": "no_entry", "face": "face_with_peeking_eye",
}   # symbols without a matching emoji get the tile alone, big, as the third option


# ------------------------------------------------------------------ basics
def _background():
    bg = Image.new("RGBA", (TW, TH), (*BG, 255))
    g = Image.radial_gradient("L").resize((int(TW * 1.25), int(TH * 1.5)))
    m = Image.new("L", (TW, TH), 0)
    m.paste(g.point(lambda v: max(0, 255 - v)), ((TW - g.width) // 2, (TH - g.height) // 2))
    lift = Image.new("RGBA", (TW, TH), (24, 24, 26, 255))
    return Image.composite(lift, bg, m.point(lambda v: int(v * 0.7)))


def _vgrad(w, h, top, bottom):
    t = Image.new("RGBA", (w, h), (*top, 255))
    b = Image.new("RGBA", (w, h), (*bottom, 255))
    return Image.composite(b, t, Image.linear_gradient("L").resize((w, h)))


def _glyph(name, height, color=WHITE):
    """A Material symbol, cropped to its ink and scaled so the ink is `height` px tall."""
    size = int(height * 1.6)
    f = A.font("MaterialIcons-Regular.ttf", size)
    im = Image.new("RGBA", (int(size * 1.5), int(size * 1.5)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((im.width / 2, im.height / 2), chr(MG[name]), font=f, fill=color, anchor="mm")
    im = im.crop(im.getbbox())
    k = height / im.height
    return im.resize((max(1, int(im.width * k)), max(1, int(height))), Image.LANCZOS)


def _shadowed(im, blur=18, dy=12, opacity=170):
    """im with a soft drop shadow, on a bigger transparent canvas (centre unchanged)."""
    pad = blur * 3
    out = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 255))
    sh.putalpha(im.getchannel("A").point(lambda v: v * opacity // 255))
    out.alpha_composite(sh, (pad, pad + dy))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(im, (pad, pad))
    return out


def _paste_center(canvas, im, cx, cy):
    canvas.alpha_composite(im, (int(round(cx - im.width / 2)), int(round(cy - im.height / 2))))


# ------------------------------------------------------------------ icons
def _tile(color, w, glyph, glyph_scale=0.6):
    """A glossy rounded tile, YouTube-logo proportions, with a white symbol."""
    h = int(w * 0.68)
    W, H = w * SS, h * SS
    top, bottom = TILES[color]
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], int(H * 0.3), fill=255)
    tile = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tile.paste(_vgrad(W, H, top, bottom), (0, 0), mask)
    gloss = Image.new("L", (W, H), 0)                         # soft highlight on the upper half
    ImageDraw.Draw(gloss).rounded_rectangle([W * 0.05, H * 0.03, W * 0.95, H * 0.5], int(H * 0.25),
                                            fill=46 if color == "red" else 26)
    gloss = ImageChops.multiply(gloss.filter(ImageFilter.GaussianBlur(H // 16)), mask)
    white = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    white.putalpha(gloss)
    tile.alpha_composite(white)
    if color == "dark":                                       # a faint light edge, like YouTube's dark UI
        rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(rim).rounded_rectangle([1, 1, W - 2, H - 2], int(H * 0.3), outline=(255, 255, 255, 34),
                                              width=max(2, SS * 2))
        tile.alpha_composite(rim)
    tile = tile.resize((w, h), Image.LANCZOS)
    g = _shadowed(_glyph(glyph, h * glyph_scale), blur=6, dy=4, opacity=90)
    _paste_center(tile, g, w / 2, h / 2 + h * 0.01)
    return tile


def _red_disc(d, content=None, text=None):
    """A red circle with a white ring holding a number or a white X."""
    D = d * SS
    im = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse([0, 0, D - 1, D - 1], fill=(255, 255, 255, 255))
    ring = int(D * 0.085)
    dr.ellipse([ring, ring, D - 1 - ring, D - 1 - ring], fill=(236, 16, 20, 255))
    if content == "x":
        k, lw = D * 0.2, int(D * 0.11)
        c = D / 2
        dr.line([c - k, c - k, c + k, c + k], fill=WHITE, width=lw)
        dr.line([c - k, c + k, c + k, c - k], fill=WHITE, width=lw)
    im = im.resize((d, d), Image.LANCZOS)
    if text:
        size = d * (0.56 if len(text) <= 1 else 0.46 if len(text) == 2 else 0.36)
        ImageDraw.Draw(im).text((d / 2, d / 2 + d * 0.02), text, font=A.font("Inter-Black.otf", size), fill=WHITE,
                                anchor="mm")
    return im


def _no_sign(d):
    """A red "no" sign (circle with a slash), with a dark outline so it reads on any tile."""
    D = d * SS
    im = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    out, lw = int(D * 0.07), int(D * 0.17)
    dr.ellipse([0, 0, D - 1, D - 1], outline=(12, 12, 12, 255), width=lw + out * 2)
    dr.ellipse([out, out, D - 1 - out, D - 1 - out], outline=(236, 16, 20, 255), width=lw)
    a = math.radians(45)
    r = D / 2 - out - lw / 2
    c = D / 2
    p0, p1 = (c - r * math.cos(a), c - r * math.sin(a)), (c + r * math.cos(a), c + r * math.sin(a))
    dr.line([p0, p1], fill=(12, 12, 12, 255), width=lw + out * 2)
    dr.line([p0, p1], fill=(236, 16, 20, 255), width=lw)
    return im.resize((d, d), Image.LANCZOS)


def _with_corner(tile, mark, corner):
    """The tile with a badge sticking out of one corner (top-right or bottom-right)."""
    pad = mark.width // 2
    out = Image.new("RGBA", (tile.width + pad, tile.height + pad * 2), (0, 0, 0, 0))
    out.alpha_composite(tile, (0, pad))
    x = tile.width - mark.width // 2 - int(tile.width * 0.06)
    y = 0 if corner == "top" else tile.height + pad * 2 - mark.height - int(tile.height * 0.02)
    out.alpha_composite(mark, (x, y))
    return out


def _pill(glyph, number, h=118, round_=True):
    """YouTube's dark counter: an outline icon and a number ("👍 0", "💬 1,000"), as a full pill
    (round_) or a rounded box."""
    f = A.font("Roboto-Bold.ttf", h * (0.5 if round_ else 0.48))
    g = _glyph(glyph, h * (0.46 if round_ else 0.46))
    tw = ImageDraw.Draw(Image.new("L", (8, 8))).textlength(number, font=f)
    w = int(h * 0.45 + g.width + h * 0.22 + tw + h * (0.5 if round_ else 0.45))
    W, H = w * SS, h * SS
    mask = Image.new("L", (W, H), 0)
    rad = H // 2 if round_ else int(H * 0.28)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], rad, fill=255)
    pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pill.paste(_vgrad(W, H, (58, 58, 60), (38, 38, 40)), (0, 0), mask)
    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle([1, 1, W - 2, H - 2], rad, outline=(255, 255, 255, 30), width=SS * 2)
    pill.alpha_composite(rim)
    pill = pill.resize((w, h), Image.LANCZOS)
    x = int(h * 0.45)
    pill.alpha_composite(g, (x, int((h - g.height) / 2)))
    ImageDraw.Draw(pill).text((x + g.width + h * 0.22, h / 2), number, font=f, fill=WHITE, anchor="lm")
    return pill


def _counters(size=118):
    """YouTube's like | comment counters, both 0: outline icons over the numbers, a divider between."""
    f = A.font("Roboto-Medium.ttf", size * 0.62)
    cols = []
    for name in ("thumb_outline", "chat_outline"):
        g = _glyph(name, size * 0.8, (226, 226, 226))
        col = Image.new("RGBA", (int(size * 1.3), int(size * 1.95)), (0, 0, 0, 0))
        _paste_center(col, g, col.width / 2, size * 0.55)
        ImageDraw.Draw(col).text((col.width / 2, size * 1.55), "0", font=f, fill=(226, 226, 226), anchor="mm")
        cols.append(col)
    gap = int(size * 0.5)
    out = Image.new("RGBA", (cols[0].width * 2 + gap, cols[0].height), (0, 0, 0, 0))
    out.alpha_composite(cols[0], (0, 0))
    out.alpha_composite(cols[1], (cols[0].width + gap, 0))
    x = cols[0].width + gap // 2
    ImageDraw.Draw(out).line([x, size * 0.15, x, out.height - size * 0.15], fill=(110, 110, 110), width=max(2, size // 40))
    return out


def _brush_x(w, h, seed=0):
    """A big red brush-stroke X: two tapered, slightly rough strokes."""
    rnd = random.Random(seed)
    W, H = w * SS, h * SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for (x0, y0, x1, y1) in ((0.04, 0.06, 0.96, 0.94), (0.95, 0.04, 0.05, 0.96)):
        x0, y0, x1, y1 = x0 * W, y0 * H, x1 * W, y1 * H
        n, base = 60, min(W, H) * 0.13
        ang = math.atan2(y1 - y0, x1 - x0)
        nx, ny = -math.sin(ang), math.cos(ang)
        left, right = [], []
        for i in range(n + 1):
            t = i / n
            wdt = base * (0.35 + 0.65 * math.sin(math.pi * min(1, t * 1.15 + 0.05))) * (0.92 + 0.16 * rnd.random())
            cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            left.append((cx + nx * wdt / 2, cy + ny * wdt / 2))
            right.append((cx - nx * wdt / 2, cy - ny * wdt / 2))
        d.polygon(left + right[::-1], fill=(228, 22, 26, 255))
    im = im.filter(ImageFilter.GaussianBlur(SS * 0.6)).resize((w, h), Image.LANCZOS)
    return _shadowed(im, blur=10, dy=6, opacity=150)


def _sad_face(width, kind="sad"):
    return A.yt_face_drawn(kind, width)


def _glitch(face, seed=0):
    """The face torn up: RGB split, shifted slices, static lines and scanlines."""
    rnd = random.Random(seed)
    w, h = face.size
    pad = int(w * 0.12)
    out = Image.new("RGBA", (w + pad * 2, h + pad), (0, 0, 0, 0))
    a = face.getchannel("A")
    for color, dx in (((0, 255, 255), pad + int(w * 0.035)), ((255, 0, 60), pad - int(w * 0.035))):
        ghost = Image.new("RGBA", face.size, (*color, 0))
        ghost.putalpha(a.point(lambda v: v * 120 // 255))
        out.alpha_composite(ghost, (dx, pad // 2))
    out.alpha_composite(face, (pad, pad // 2))
    torn = out.copy()
    for _ in range(9):                                         # torn horizontal slices
        y0 = rnd.randint(0, out.height - 12)
        bh = rnd.randint(int(h * 0.02), int(h * 0.09))
        band = torn.crop((0, y0, out.width, min(out.height, y0 + bh)))
        out.paste(Image.new("RGBA", band.size, (0, 0, 0, 0)), (0, y0))
        out.alpha_composite(band, (rnd.randint(-int(w * 0.05), int(w * 0.05)), y0))
    d = ImageDraw.Draw(out)
    for _ in range(26):                                        # static streaks
        y = rnd.randint(0, out.height - 1)
        x0 = rnd.randint(0, out.width)
        ln = rnd.randint(int(w * 0.05), int(w * 0.5))
        col = rnd.choice([(255, 255, 255), (255, 40, 40), (0, 230, 255), (120, 120, 120)])
        d.line([x0, y, x0 + ln, y], fill=(*col, rnd.randint(70, 200)), width=rnd.randint(1, 4))
    scan = Image.new("L", out.size, 255)                       # scanlines
    sd = ImageDraw.Draw(scan)
    for y in range(0, out.height, 5):
        sd.line([0, y, out.width, y], fill=170, width=2)
    out.putalpha(ImageChops.multiply(out.getchannel("A"), scan))
    return out


# ------------------------------------------------------------------ text
LH = 1.02                                                  # line height, in font sizes


def _fit(text, fontname, size, max_w):
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    while size > 20 and d.textlength(text, font=A.font(fontname, size)) > max_w:
        size -= 2
    return A.font(fontname, size)


def _one_line(text):
    return text[0] == "split" and text[3] and len(text[1]) + len(text[2]) <= 23


def _layout(text):
    """The lines of a title block: [(parts [(text, colour)], font, shadow)], each already fitted."""
    if not text:
        return []
    kind = text[0]
    L = []

    def add(parts, fontname, size, max_w, shadow=True):
        L.append((parts, _fit("".join(t for t, _ in parts), fontname, size, max_w), shadow))

    if kind == "split":
        white, red, red_first = text[1], text[2], text[3]
        if not white or not red:                               # one big red line
            add([(red or white, RED_TEXT)], HEAD, 150, TW * 0.84)
        elif _one_line(text):                                  # "Don't Pause" + " This Video" on one line
            add([(red + " ", RED_TEXT), (white, WHITE)], HEAD, 130, TW * 0.86)
        elif red_first:
            add([(red, RED_TEXT)], HEAD, 136, TW * 0.84)
            add([(white, WHITE)], HEAD, 108, TW * 0.74)
        else:
            add([(white, WHITE)], HEAD, 108, TW * 0.74)
            add([(red, RED_TEXT)], HEAD, 136, TW * 0.84)
    elif kind == "bracket":
        add([(text[1], WHITE)], "Inter-SemiBold.otf", 88, TW * 0.62)
    elif kind == "ui":
        add([(text[1], WHITE)], UI_MAIN, 80, TW * 0.7, shadow=False)
        add([(text[2], GREY)], UI_SUB, 38, TW * 0.74, shadow=False)
    return L


def _text_height(text):
    return sum(f.size * LH for _, f, _ in _layout(text))


def _draw_text(canvas, text, top):
    d = ImageDraw.Draw(canvas)
    y = top
    for parts, f, shadow in _layout(text):
        cy = y + f.size * LH / 2
        full = "".join(t for t, _ in parts)
        w = d.textlength(full, font=f)
        if shadow:
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((TW / 2, cy + f.size * 0.06), full, font=f, fill=(0, 0, 0, 210), anchor="mm")
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(f.size * 0.08)))
        x = TW / 2 - w / 2
        for t, col in parts:
            d.text((x, cy), t, font=f, fill=col, anchor="lm")
            x += d.textlength(t, font=f)
        y += f.size * LH


# ------------------------------------------------------------------ which design for which title
SPLITS = {   # title -> (white part, red part, red first)
    "this video has 1 comment": ("This Video Has", "1 Comment", False),
    "this video has 1 view": ("This Video Has", "1 View", False),
    "this video has 5 comments": ("This Video Has", "5 Comments", False),
    "this video will self destruct in 24 hours...": ("This Video Will Self Destruct", "In 24 Hours...", False),
    "this video will be deleted tomorrow": ("This Video Will Be", "Deleted Tomorrow", False),
    "this video disappears in 1 hour": ("This Video Disappears", "In 1 Hour", False),
    "i'm deleting this in 2 days...": ("I'm Deleting This in", "2 Days...", False),
    "watch this before it's gone...": ("Watch This Before", "It's Gone...", False),
    "can this video get 10 million views?": ("Can This Video Get", "10 Million Views?", False),
    "only 67 people can comment": ("Only 67 People", "Can Comment", False),
    "let's balance the likes & comments": ("Let's Balance The", "Likes & Comments", False),
    "this video won't get 1 million views": ("This Video Won't Get", "1 Million Views", False),
    "this video won't get 1,000 comments": ("This Video Won't Get", "1,000 Comments", False),
    "face reveal...": ("", "Face Reveal...", False),
    "face reveal final chance...": ("Face Reveal", "Final Chance...", False),
    "my real age reveal": ("My REAL Age", "Reveal", False),
    "don't pause this video": ("This Video", "Don't Pause", True),
    "don't watch this video twice": ("This Video Twice", "Don't Watch", True),
    "don't be the 1st person to comment": ("Person To Comment", "Don't Be The 1st", True),
    "this video is upside down": ("This Video Is", "Upside Down", False),
    "first comment gets pinned": ("First Comment", "Gets Pinned", False),
    "the weirdest comment gets pinned...": ("The WEIRDEST Comment", "Gets Pinned...", False),
    "i will heart every comment": ("I Will Heart", "Every Comment", False),
    "only you can comment on this video": ("Only YOU Can Comment", "On This Video", False),
    "only you can watch this video": ("Only You Can Watch", "This Video", False),
    "only verified youtubers can comment": ("Only Verified YouTubers", "Can Comment", False),
    "secret video": ("", "SECRET VIDEO", False),
}


def _split(title):
    key = title.strip().lower()
    if key in SPLITS:
        return ("split", *SPLITS[key])
    t = title.strip()
    if t.lower().startswith("don't ") and len(t.split()) > 2:
        w = t.split()
        return ("split", " ".join(w[2:]), " ".join(w[:2]), True)
    m = re.search(r"\b\d[\d,]*\b", t)
    if m and m.start() > 0:
        return ("split", t[:m.start()].strip(), t[m.start():].strip(), False)
    w = t.split()
    if len(w) <= 2:
        return ("split", "", t, False)
    cut = len(w) // 2
    return ("split", " ".join(w[:cut]), " ".join(w[cut:]), False)


ERROR_UI = [   # keyword -> (symbol, YouTube's message, the small line under it); None = the bracket title
    ("unlist", "link", "This video is unlisted", "Only people with the link can watch this video."),
    ("no access", "block", "No access", "You don't have permission to access this video."),
    ("unavailable", "error_outline", "Video unavailable", "This video is no longer available."),
    ("hidden", "visibility_off", "This video is hidden", "Only the creator can see this video."),
    ("secret", "visibility_off", None, None), ("privat", "lock", None, None), ("lock", "lock", None, None),
    ("delet", "delete", None, None), ("remov", "delete", None, None),
    ("glitch", "error_outline", None, None), ("curse", "error_outline", None, None),
]


def _card(icon, text=None, flip=False):
    return {"kind": "card", "icon": icon, "text": text, "flip": flip}


def _designs(title):
    """Three designs for a title, best first."""
    t = title.lower()
    clean = re.sub(r"\s+", " ", title).strip()
    if re.match(r"^\s*[\[<{(]", title):                         # [Private Video] and friends
        sym, main, sub = next(((s, m, u) for k, s, m, u in ERROR_UI if k in t), ("error_outline", None, None))
        text = ("ui", main, sub) if main else ("bracket", clean)
        face = A.drawn_faces(title)[0]
        tile = _card(("tile", "dark", sym, None), text)
        if re.search(r"glitch|curse", t):
            return [{"kind": "glitch"}, {"kind": "sad", "face": "sad"}, tile]
        if re.search(r"remov|delet", t):
            return [{"kind": "sad", "face": "sad"}, _card(("tile", "red", "delete", None), ("bracket", clean)),
                    {"kind": "glitch"}]
        return [tile, {"kind": "sad", "face": face if face != "dots" else "sad"}, {"kind": "glitch"}]

    split = _split(clean)
    if re.search(r"0 likes and 0 comments", t):
        return [{"kind": "counters", "text": None},
                _card(("pill", "thumb_outline", "0"), ("ui", "This video has 0 likes and 0 comments", "Be the first.")),
                {"kind": "counters", "text": split}]
    if re.search(r"balance the likes", t):
        return [{"kind": "counters", "text": split}, {"kind": "counters", "text": None},
                _card(("tile", "red", "thumb_up", None), split)]
    if re.search(r"has 0 likes", t):
        return [_card(("pill", "thumb_outline", "0"), ("ui", "This video has 0 likes", "Be the first to like this video.")),
                _card(("tile", "red", "thumb_up", "0"), ("split", "This Video Has", "0 Likes", False)),
                {"kind": "counters", "text": None}]
    if re.search(r"has 0 comments", t):
        return [_card(("pill", "chat_outline", "0"), ("ui", "This video has 0 comments", "Be the first to comment.")),
                _card(("tile", "red", "chat", "0"), ("split", "This Video Has", "0 Comments", False)),
                {"kind": "counters", "text": None}]
    m = re.search(r"won't get ([\d,]+) comments", t)
    if m:
        return [{"kind": "crossed", "glyph": "chat_outline", "number": m.group(1)},
                _card(("tile", "red", "chat", "x"), split),
                _card(("pill", "chat_outline", m.group(1)), split)]
    if re.search(r"won't get .*views", t):
        return [_card(("tile", "dark", "bar_chart", "x"), split), _card(("tile", "red", "bar_chart", "x"), split),
                {"kind": "crossed", "glyph": "visibility", "number": re.search(r"[\d,.]+ ?\w*", clean[clean.lower().find("get") + 3:]).group(0).strip()}]
    m = re.search(r"\b(\d+) (people|comments?)\b", t)
    if m and "comment" in t:
        n = m.group(1)
        return [_card(("tile", "red", "chat", n), split), _card(("tile", "dark", "chat", n), split),
                _card(("pill", "chat_outline", n), split)]
    if re.search(r"\bviews?\b", t):
        return [_card(("tile", "dark", "bar_chart", None), split), _card(("tile", "red", "visibility", None), split),
                _card(("emoji", "bar_chart", None), split)]

    rules = [   # keyword -> (tile colour, symbol, corner mark)
        (r"self destruct", ("red", "timer", None)), (r"disappear|before it's gone", ("red", "hourglass", None)),
        (r"delet", ("red", "delete", None)), (r"pause", ("dark", "pause", "no")),
        (r"twice", ("dark", "replay", "no")), (r"1st person|first person", ("red", "chat", "no")),
        (r"upside down", ("dark", "screen_rotation", None)), (r"heart every", ("emoji", "favorite", None)),
        (r"pinned", ("red", "push_pin", None)), (r"age reveal", ("red", "cake", None)),
        (r"face reveal", ("dark", "face", None)), (r"only you can watch", ("dark", "visibility", None)),
        (r"verified", ("dark", "verified", None)), (r"secret", ("dark", "visibility_off", None)),
        (r"comment", ("red", "chat", None)), (r"like", ("red", "thumb_up", None)),
        (r"", ("red", "help", None)),
    ]
    color, sym, mark = next(v for k, v in rules if re.search(k, t))
    flip = "upside down" in t
    if color == "emoji":                                        # the 3D heart is the star; tiles as options
        return [_card(("emoji", EMOJI[sym], None), split), _card(("tile", "red", sym, None), split),
                _card(("tile", "dark", sym, None), split)]
    other = "dark" if color == "red" else "red"
    third = _card(("emoji", EMOJI[sym], mark), split, flip) if sym in EMOJI else _card(("tile", color, sym, mark), None, flip)
    return [_card(("tile", color, sym, mark), split, flip), _card(("tile", other, sym, mark), split, flip), third]


# ------------------------------------------------------------------ rendering
def _icon(spec, big=False, text=None):
    kind = spec[0]
    if kind == "tile":
        _, color, sym, mark = spec
        tile = _tile(color, 470 if big else 400 if text and text[0] in ("bracket", "ui") else 360, sym)
        if mark == "x":
            tile = _with_corner(tile, _red_disc(int(tile.height * 0.42), "x"), "bottom")
        elif mark == "no":
            tile = _with_corner(tile, _no_sign(int(tile.height * 0.62)), "bottom")
        elif mark:
            tile = _with_corner(tile, _red_disc(int(tile.height * 0.44), text=mark), "top")
        return _shadowed(tile)
    if kind == "pill":
        return _shadowed(_pill(spec[1], spec[2], 220, round_=False))
    if kind == "emoji":
        _, name, mark = spec
        im = A.picture(name, 300, shadow=False)
        if mark == "no":
            im = _with_corner(im, _no_sign(int(im.height * 0.45)), "bottom")
        elif mark:
            im = _with_corner(im, _red_disc(int(im.height * 0.4), text=mark), "top")
        return _shadowed(im, blur=16, dy=10, opacity=150)
    raise ValueError(kind)


def _compose(canvas, icon, text, icon_scale=1.0):
    """The icon over the text, the whole group centred on the frame."""
    if icon_scale != 1.0:
        icon = icon.resize((int(icon.width * icon_scale), int(icon.height * icon_scale)), Image.LANCZOS)
    bb = icon.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox() or (0, 0, icon.width, icon.height)
    ih = bb[3] - bb[1]
    th = _text_height(text)
    gap = 34 if th else 0
    top = (TH - (ih + gap + th)) / 2
    canvas.alpha_composite(icon, (int(TW / 2 - (bb[0] + bb[2]) / 2), int(top - bb[1])))
    if th:
        _draw_text(canvas, text, top + ih + gap)


def render(design, data=None, variant=0):
    """One thumbnail (RGB 1280x720) for a design from _designs()."""
    title = (data or {}).get("title_base") or (data or {}).get("title", "")
    rnd_seed = f"{title}-{variant}"
    bg = _background()
    kind = design["kind"]
    if kind == "card":
        _compose(bg, _icon(design["icon"], big=not design.get("text"), text=design.get("text")), design.get("text"))
        if design.get("flip"):
            bg = bg.rotate(180)
    elif kind == "sad":
        face = _shadowed(_sad_face(640, design.get("face", "sad")), blur=24, dy=14)
        _paste_center(bg, face, TW / 2, TH / 2 + 6)
    elif kind == "glitch":
        face = _glitch(_sad_face(620, "sad"), seed=hash(rnd_seed) & 0xffff)
        _paste_center(bg, face, TW / 2, TH / 2)
    elif kind == "counters":
        _compose(bg, _counters(150 if design.get("text") else 210), design.get("text"))
    elif kind == "crossed":
        pill = _pill(design["glyph"], design["number"], 250)
        group = Image.new("RGBA", (pill.width + 120, pill.height + 260), (0, 0, 0, 0))
        _paste_center(group, _shadowed(pill), group.width / 2, group.height / 2)
        x = _brush_x(int(pill.width * 0.62), int(pill.height * 1.9), seed=variant)
        _paste_center(group, x, group.width / 2 - pill.width * 0.14, group.height / 2)  # over the icon, the number shows
        _paste_center(bg, group, TW / 2, TH / 2)
    else:
        raise ValueError(kind)
    return bg.convert("RGB")


def _name(design):
    k = design["kind"]
    if k == "card":
        i = design["icon"]
        return f"{i[0]}-{i[1]}" + (f"-{i[2]}" if i[0] == "tile" else "")
    return k


def make(data, out_dir: Path, count=3):
    """Three different thumbnails for the video, the best design first. Returns the paths."""
    title = data.get("title_base") or data.get("title", "")
    designs = _designs(title)[:count]
    for old in out_dir.glob("*thumbnail*.jpg"):
        old.unlink()
    paths = []
    for i, design in enumerate(designs, 1):
        im = render(design, data, variant=i - 1)
        p = out_dir / f"911video-thumbnail-{i}.jpg"
        im.save(p, quality=92)
        paths.append(p)
    data["thumbs"] = [_name(d) for d in designs]
    return paths
