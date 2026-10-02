"""Step 5: three clickable 1280x720 thumbnails per video.

Each video gets 3 variations to choose from, all different in layout (10 formats), colours (10
high-contrast palettes) and hook text ("IS IT WORTH IT?", "IS IT A SCAM?", "LEGIT OR HYPE?"...).
Every one shows the product's logo big and clear on a modern backdrop: the site's own screenshot,
blurred and tinted, with soft colour lights and glows behind the hero objects and the hook's key word. Nothing is placed by guesswork: the logo, the
hook, the pill and the screenshot are measured, the hook gets as big as its space allows, and every
important item is recorded and checked so none sits on top of another (or under YouTube's duration
badge). Numbers shown come from the review's fact stickers, so they're never invented.

Optional: assets/thumbnail_overlay.png (1280x720, transparent) is drawn on top of every thumbnail.
"""

import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from . import config, icons
from .visuals import (fit, font, head_font, load_logo, logo_chip, lum, mix,
                      paste_shadowed, readable_on, shift_hue, rounded, round_corners, shadow_text)

TW, TH = 1280, 720

LAYOUTS = ["circle", "split", "fact", "ring", "lens", "phone"]

# name: (background 1, background 2, text, accent, pop) — tested combinations with strong contrast
PALETTES = {
    "midnight_yellow": ((10, 12, 20), (30, 34, 58), (255, 255, 255), (255, 212, 0), (255, 72, 66)),
    "royal_yellow": ((14, 30, 110), (38, 74, 210), (255, 255, 255), (255, 222, 0), (255, 255, 255)),
    "red_white": ((196, 18, 30), (120, 0, 12), (255, 255, 255), (255, 228, 0), (14, 15, 18)),
    "paper_red": ((250, 249, 245), (226, 230, 238), (14, 15, 18), (228, 30, 42), (14, 15, 18)),
    "purple_lime": ((52, 16, 110), (112, 40, 200), (255, 255, 255), (186, 255, 58), (255, 214, 0)),
    "teal_orange": ((0, 74, 84), (0, 132, 140), (255, 255, 255), (255, 146, 30), (255, 255, 255)),
    "black_green": ((8, 10, 10), (16, 36, 26), (255, 255, 255), (44, 232, 124), (255, 212, 0)),
    "orange_ink": ((255, 122, 18), (232, 76, 0), (14, 15, 18), (255, 255, 255), (14, 15, 18)),
    "pink_yellow": ((232, 36, 120), (150, 10, 80), (255, 255, 255), (255, 236, 0), (14, 15, 18)),
    "sky_navy": ((0, 168, 255), (0, 96, 200), (255, 255, 255), (10, 22, 60), (255, 222, 0)),
}
LIGHT_PALETTES = {"paper_red", "orange_ink"}


# ------------------------------------------------------------------ helpers
def _cover(im, size, focus=None, zoom=1.0, anchor=(0.5, 0.5)):
    r = max(size[0] / im.width, size[1] / im.height) * zoom
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    fx, fy = focus if focus else (im.width / r / 2, im.height / r / 2)
    x = int(max(0, min(im.width - size[0], fx * r - size[0] * anchor[0])))
    y = int(max(0, min(im.height - size[1], fy * r - size[1] * anchor[1])))
    return im.crop((x, y, x + size[0], y + size[1]))


def busiest_point(im, win=(640, 720)):
    """Centre of the most detailed region (text, numbers, buttons) — better crops than blank hero art."""
    small = im.convert("L").resize((im.width // 8, im.height // 8))
    edges = small.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    ww, wh = max(1, win[0] // 8), max(1, min(small.height, win[1] // 8))
    best, best_xy = -1, (im.width / 2, im.height / 2)
    for x in range(0, max(1, small.width - ww), 6):
        for y in range(0, max(1, small.height - wh), 6):
            score = sum(edges.crop((x, y, x + ww, y + wh)).getdata())
            if score > best:
                best, best_xy = score, ((x + ww / 2) * 8, (y + wh / 2) * 8)
    return best_xy


def _left_fade(bg, strength=235, reach=0.75, color=(8, 9, 12)):
    grad = Image.new("L", (TW, 1))
    grad.putdata([int(strength * max(0, 1 - x / (TW * reach))) for x in range(TW)])
    shade = Image.new("RGBA", (TW, TH), (*color, 255))
    shade.putalpha(grad.resize((TW, TH)))
    bg.alpha_composite(shade)


def _card(shot, width, tilt, border=8):
    card = shot.resize((width, int(width * shot.height / shot.width)), Image.LANCZOS)
    framed = rounded((card.width + border * 2, card.height + border * 2), 22, (255, 255, 255, 255))
    framed.alpha_composite(round_corners(card.convert("RGBA"), 16), (border, border))
    return framed.rotate(tilt, resample=Image.BICUBIC, expand=True)


# ------------------------------------------------------------------ hooks (the big text)
# "|" breaks the line, "*" colours a word, "!" makes a line full size. Without "!", the line with the
# coloured word is huge and the other line is a smaller lead-in ("IS IT" / "WORTH IT?"), the classic
# high-CTR look. The first variation matches the video's title style; the other two use other hooks.
HOOKS = {
    "worth": "IS IT|*WORTH *IT?",
    "worth_using": "!WORTH|!USING *IT?",
    "scam": "IS IT A|*SCAM?",
    "legit": "LEGIT OR|*HYPE?",
    "catch": "WHAT'S THE|*CATCH?",
    "expect": "WHAT TO|*EXPECT?",
    "truth": "THE HONEST|*TRUTH",
    "fees": "!*HIDDEN|!FEES?",
    "before": "!WATCH|!*FIRST!",
    "dont": "DON'T USE|IT *YET!",
    "good": "IS IT|ANY *GOOD?",
    "works": "DOES IT|*WORK?",
}
FAMILY = {"worth_using": "worth", "good": "works"}               # too similar to show side by side
STYLE_HOOK = {"scam": "scam", "expect": "expect", "worth": "worth_using", "legit": "legit",
              "before": "before", "catch": "catch", "truth": "truth", "fees": "fees", "dont": "dont",
              "actually": "worth", "good": "good", "honest": "worth"}
LEAD_IN = 0.62                                                    # size of the small lead-in line


def hook(key):
    raw = HOOKS[key].split("|")
    lines = [[w.lstrip("!*") for w in ln.split()] for ln in raw]
    accent = {w.lstrip("!*") for ln in raw for w in ln.split() if w.lstrip("!").startswith("*")}
    if any(ln.startswith("!") for ln in raw):
        big = [ln.startswith("!") for ln in raw]
    else:
        big = [any(w.startswith("*") for w in ln.split()) for ln in raw]
    return {"key": key, "lines": lines, "accent": accent, "big": big,
            "text": " ".join(" ".join(l) for l in lines)}


def pick_hooks(data, theme, n=3):
    """Hook keys for the variations: the title's own style first, then 'worth it?' / 'scam?', then a mix."""
    rnd = random.Random(theme["seed"] + "hooks")
    fam = lambda k: FAMILY.get(k, k)
    keys = [STYLE_HOOK.get(data.get("title_style"), "worth")]
    core = ["worth", "scam"]
    rnd.shuffle(core)
    rest = ["legit", "catch", "worth_using", "good", "expect", "works", "truth"]
    rnd.shuffle(rest)
    for k in core + rest:
        if len(keys) >= n:
            break
        if fam(k) not in {fam(x) for x in keys}:
            keys.append(k)
    return keys[:n]


# ------------------------------------------------------------------ glow & light
def _blob(canvas, cx, cy, r, color, alpha):
    """A big soft light (drawn at quarter size, then scaled up: cheap and very smooth)."""
    q = 4
    layer = Image.new("RGBA", (TW // q, TH // q), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([(cx - r) / q, (cy - r) / q, (cx + r) / q, (cy + r) / q], fill=(*color, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(r / q * 0.5)).resize((TW, TH), Image.BILINEAR))


def _halo(canvas, rect, color, spread=46, alpha=190):
    """Coloured glow around an object (drawn before the object itself)."""
    x0, y0, x1, y1 = rect
    layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0 - spread * 0.3, y0 - spread * 0.3, x1 + spread * 0.3,
                                             y1 + spread * 0.3], radius=40, fill=(*color, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(spread)))


_VIG = {}


def _vignette(canvas, strength=150):
    if strength not in _VIG:
        m = Image.new("L", (TW // 8, TH // 8), 0)
        ImageDraw.Draw(m).ellipse([-TW // 32, -TH // 24, TW // 8 + TW // 32, TH // 8 + TH // 24], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(18)).resize((TW, TH), Image.BILINEAR)
        v = Image.new("RGBA", (TW, TH), (0, 0, 0, 255))
        v.putalpha(m.point(lambda a: int((255 - a) * strength / 255)))
        _VIG[strength] = v
    canvas.alpha_composite(_VIG[strength])


def _glow_bg(shot, base, deep, glow, glow2, light=False, hero=(960, 360), ghost=0.38):
    """Modern backdrop: the site's own screenshot, blurred and tinted, with big soft colour lights."""
    pic = _cover(shot, (TW, TH), zoom=1.15).filter(ImageFilter.GaussianBlur(26))
    pic = ImageEnhance.Color(pic).enhance(0.6)
    if not light:
        pic = ImageEnhance.Brightness(pic).enhance(0.55)
    tint = Image.new("RGB", (TW, TH), base)
    grad = Image.linear_gradient("L").rotate(-60, expand=False).resize((TW, TH))
    tint = Image.composite(Image.new("RGB", (TW, TH), deep), tint, grad)
    bg = Image.blend(tint, pic.convert("RGB"), ghost).convert("RGBA")
    hx, hy = hero
    _blob(bg, hx, hy, 470, glow, 150 if not light else 120)
    _blob(bg, TW - hx, TH - hy * 0.4, 520, glow2, 110 if not light else 90)
    _blob(bg, hx * 0.9, hy - 60, 200, (255, 255, 255), 50 if not light else 90)
    if not light:
        _vignette(bg, 140)
    return bg


def _vivid(c, deg=0, sat=0.85, val=1.0):
    return shift_hue(c, deg, sat=sat, val=val)


def _pal_bg(shot, pal_name, hero=(960, 360), ghost=0.38):
    """Palette backdrop. Lights use vivid hues of the palette's background colour (yellow light on
    dark goes muddy), so dark schemes glow in clean blues, purples, greens or reds."""
    b1, b2, txt, acc, pop = PALETTES[pal_name]
    light = pal_name in LIGHT_PALETTES
    deep = mix(b1, (0, 0, 0), 0.45) if not light else b2
    if light:
        g1, g2 = mix(acc, (255, 255, 255), 0.35), mix(b2, (255, 255, 255), 0.2)
    else:
        g1, g2 = _vivid(b2), _vivid(b2, 40, 0.8, 0.85)
    return _glow_bg(shot, b1, deep, g1, g2, light, hero, ghost)


# ------------------------------------------------------------------ placement
TIMESTAMP = (TW - 230, TH - 80, TW, TH)          # YouTube's duration badge covers this corner


class Boxes:
    """Where the important things went, so nothing important ends up on top of something else.
    kind: "text" (headline, logo, pill...), "hero" (screenshot, phone, score ring), "zone" (keep clear)."""

    def __init__(self):
        self.items = [("timestamp", "zone", TIMESTAMP)]

    def add(self, name, rect, kind="text"):
        x0, y0, x1, y1 = (int(v) for v in rect)
        self.items.append((name, kind, (max(0, x0), max(0, y0), min(TW, x1), min(TH, y1))))
        return rect

    def clashes(self, tol=6):
        out = []
        for i, (n1, k1, r1) in enumerate(self.items):
            for n2, k2, r2 in self.items[i + 1:]:
                kinds = {k1, k2}
                if "text" not in kinds and kinds != {"badge", "zone"}:    # badges may sit on heroes
                    continue
                if min(r1[2], r2[2]) - max(r1[0], r2[0]) > tol and min(r1[3], r2[3]) - max(r1[1], r2[1]) > tol:
                    out.append(f"{n1} / {n2}")
        return out

    def outside(self, margin=16):
        return [n for n, k, r in self.items if k == "text" and
                (r[0] < margin or r[1] < margin or r[2] > TW - margin or r[3] > TH - margin)]


def _head_metrics(theme, hk, max_w, max_h, size=230, sticker=False, stroke=8):
    """Biggest hook that fits, trying the hook's own line breaks and, when there's height to spare,
    one word per line for the big lines ("WORTH IT?" -> "WORTH" / "IT?"). Sets hk's lines to the winner."""
    lines, big = hk["lines"], hk.get("big") or [True] * len(hk["lines"])
    options = [(lines, big)]
    split_l, split_b = [], []
    for l, b in zip(lines, big):
        parts = [[w] for w in l] if b and len(l) > 1 else [l]
        split_l += parts
        split_b += [b] * len(parts)
    if len(split_l) != len(lines) and len(split_l) <= 4:
        options.append((split_l, split_b))
    best = None
    for l, b in options:
        m = _head_metrics_for(theme, {**hk, "lines": l, "big": b}, max_w, max_h, size, sticker, stroke)
        if best is None or m["fonts"][max(range(len(b)), key=lambda i: b[i])].size > \
                best[0]["fonts"][max(range(len(best[2])), key=lambda i: best[2][i])].size + 6:
            best = (m, l, b)
    m, l, b = best
    hk["lines"], hk["big"] = l, b
    return m


def _head_metrics_for(theme, hk, max_w, max_h, size=230, sticker=False, stroke=8):
    """Biggest hook that fits max_w x max_h (the lead-in line smaller). Returns a dict of measurements."""
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    lines, big = hk["lines"], hk.get("big") or [True] * len(hk["lines"])
    scales = [1.0] * len(lines) if all(big) or not any(big) else [1.0 if b else LEAD_IN for b in big]
    pad = 22 if sticker else stroke
    while True:
        fonts = [head_font(theme["head_font"], max(14, int(size * sc))) for sc in scales]
        tops, caps, ys = [], [], []
        y = 14 if sticker else stroke
        for i, f in enumerate(fonts):
            bb = f.getbbox("HQ?!")
            tops.append(bb[1])
            caps.append(bb[3] - bb[1])
            ys.append(y)
            y += caps[-1] + ((46 if sticker else max(12, int(max(f.size, fonts[min(i + 1, len(fonts) - 1)].size)
                                                            * 0.11)) + stroke) if i < len(fonts) - 1 else 0)
        h = y + (14 if sticker else stroke)
        widths = [d.textlength(" ".join(l), font=f) for l, f in zip(lines, fonts)]
        w = max(widths) + pad * 2
        if (w <= max_w and h <= max_h) or size <= 40:
            return {"fonts": fonts, "tops": tops, "caps": caps, "ys": ys, "widths": widths, "w": w, "h": h,
                    "pad": pad, "scales": scales}
        size -= 3


def _headline(canvas, B, x, y, theme, hk, max_w, max_h, accent, align="left", text_col=(255, 255, 255),
              stroke=8, size=230, sticker=None, outline=(10, 10, 12), metrics=None, glow=True):
    """The hook in huge type, accent word(s) coloured and glowing; its visual top is at y. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    m = metrics or _head_metrics(theme, hk, max_w, max_h, size, bool(sticker), stroke)
    pad = m["pad"]
    words_at = []                                               # (line, word, x, y, colour, stroke)
    for li, words in enumerate(hk["lines"]):
        f, tw = m["fonts"][li], m["widths"][li]
        lx = x - tw / 2 if align == "center" else (x - tw - pad if align == "right" else x + pad)
        vis = y + m["ys"][li]
        st_w = stroke if m["scales"][li] == 1.0 else max(4, int(stroke * 0.7))
        if sticker:                                             # each line on a tilted label
            box = rounded((int(tw + pad * 2), int(m["caps"][li] + 28)), 12, (*sticker[0], 255))
            box = box.rotate(sticker[2] * (1 if li % 2 else -1), Image.BICUBIC, expand=True)
            paste_shadowed(canvas, box, (lx - pad, vis - 14), 12, 14, 150, 9)
        cx = lx
        for wd in words:
            hot = wd in hk["accent"]
            if sticker:
                col = sticker[1]
                if hot:
                    col = accent if abs(lum(accent) - lum(sticker[0])) > 90 else                         ((255, 212, 0) if lum(sticker[0]) < 128 else (214, 24, 36))
            else:
                col = accent if hot else text_col
            words_at.append((li, wd, cx, vis - m["tops"][li], col, st_w, hot))
            cx += d.textlength(wd + " ", font=f)
    hot_glow = [w for w in words_at if w[6] and glow and not sticker and lum(w[4]) > 70]
    if hot_glow:                                     # soft light behind the coloured words
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for li, wd, wx, wy, col, st_w, _ in hot_glow:
            ld.text((wx, wy), wd, font=m["fonts"][li], fill=(*col, 150), stroke_width=st_w + 14,
                    stroke_fill=(*col, 150))
        canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(30)))
    for li, wd, wx, wy, col, st_w, hot in words_at:
        ol = outline if abs(lum(col) - lum(outline)) > 90 else ((255, 255, 255) if lum(col) < 128 else (10, 10, 12))
        st = 0 if sticker else max(st_w, 5 if lum(col) < 90 else 0)
        shadow_text(canvas, (wx, wy), wd, m["fonts"][li], col, stroke=st, stroke_fill=ol,
                    opacity=0 if sticker else 215, blur=12, offset=(4, 9))
    x0 = x - m["w"] / 2 if align == "center" else (x - m["w"] if align == "right" else x)
    B.add("headline", (x0, y, x0 + m["w"], y + m["h"]))
    return y + m["h"]


def _pill_img(text, color, size=48, max_w=560, tilt=0):
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    text = text.upper()
    f = fit(d, text, lambda s: font("Black", s), max_w - 56, size)
    tw = int(d.textlength(text, font=f))
    pill = rounded((tw + 56, int(f.size * 1.6)), 18, (*color, 255))
    ImageDraw.Draw(pill).text((28, pill.height / 2), text, font=f, fill=readable_on(color), anchor="lm")
    return pill.rotate(tilt, Image.BICUBIC, expand=True) if tilt else pill


def _pill(canvas, B, x, y, text, color, align="left", size=48, tilt=0, max_w=560, img=None):
    pill = img or _pill_img(text, color, size, max_w, tilt)
    px = x - pill.width // 2 if align == "center" else (x - pill.width if align == "right" else x)
    paste_shadowed(canvas, pill, (px, y), 18, 14, 170, 8)
    B.add("pill", (px, y, px + pill.width, y + pill.height))
    return pill.width, pill.height


def _brand(canvas, B, x, y, logo, brand, theme, height=104, align="left", label=True, dark_text=False, max_w=620):
    """Big logo chip + "BRAND REVIEW" label (or the name in big type when there's no logo). Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    anchor = {"center": "ma", "right": "ra"}.get(align, "la")
    if logo is not None:
        chip = logo_chip(logo, height, radius=26)
        while chip.width > max_w and height > 48:               # very wide wordmarks
            height -= 6
            chip = logo_chip(logo, height, radius=26)
        cx = x - chip.width // 2 if align == "center" else (x - chip.width if align == "right" else x)
        paste_shadowed(canvas, chip, (cx, y), 26, 16, 170, 8)
        B.add("logo", (cx, y, cx + chip.width, y + chip.height))
        bottom = y + chip.height
        if label:
            name = f"{brand.upper()} REVIEW"
            f = fit(d, name, lambda s: font("Black", s), max_w, 30)
            d.text((x, bottom + 14), name, font=f, fill=(20, 20, 24) if dark_text else (235, 238, 244), anchor=anchor)
            bb = d.textbbox((x, bottom + 14), name, font=f, anchor=anchor)
            B.add("brand name", bb)
            bottom = bb[3]
        return bottom
    f = fit(d, brand.upper(), lambda s: head_font(theme["head_font"], s), max_w, 100)
    shadow_text(canvas, (x, y), brand.upper(), f, (20, 20, 24) if dark_text else (255, 255, 255),
                stroke=0 if dark_text else 5, opacity=0 if dark_text else 180, anchor=anchor)
    bb = d.textbbox((x, y), brand.upper(), font=f, anchor=anchor, stroke_width=5)
    B.add("brand name", bb)
    return bb[3]


def _column(canvas, B, theme, x, top, bottom, max_w, hk, accent, *, logo=None, brand=None, dark=False,
            pill=None, pill_col=(255, 212, 0), pill_size=48, pill_tilt=0, align="left", gap=26, **head):
    """Logo at the top, pill at the bottom, the hook as big as the space between allows."""
    y = top
    if brand is not None:
        y = _brand(canvas, B, x, top, logo, brand, theme, align=align, dark_text=dark, max_w=max_w) + gap
    img = _pill_img(pill, pill_col, pill_size, min(max_w, 600), pill_tilt) if pill else None
    pill_y = bottom - img.height if img else bottom
    space = pill_y - (gap if img else 0) - y
    m = _head_metrics(theme, hk, max_w, space, head.get("size", 230), bool(head.get("sticker")),
                      head.get("stroke", 8))
    hy = y + max(0, space - m["h"]) * 0.45
    _headline(canvas, B, x, hy, theme, hk, max_w, space, accent, align=align, metrics=m, **head)
    if img:
        _pill(canvas, B, x, pill_y, pill, pill_col, align=align, img=img)


def _logo_tile(logo, brand, theme, size=260, tilt=0):
    """Big white rounded tile with the logo (or brand name) — the hero of logo-first layouts.
    Wide wordmarks get a wide tile so the logo stays big and readable."""
    wide = logo is not None and logo.width / max(1, logo.height) > 1.5
    w, h = (int(size * 1.6), int(size * 0.8)) if wide else (size, size)
    tile = rounded((w, h), min(w, h) // 5, (255, 255, 255, 255))
    if logo is not None:
        lg = logo.copy()
        r = min(w * (0.84 if wide else 0.74) / lg.width, h * (0.62 if wide else 0.62) / lg.height)
        lg = lg.resize((max(1, int(lg.width * r)), max(1, int(lg.height * r))), Image.LANCZOS)
        tile.alpha_composite(lg, ((w - lg.width) // 2, (h - lg.height) // 2))
    else:
        d = ImageDraw.Draw(tile)
        f = fit(d, brand, lambda s: head_font(theme["head_font"], s), w * 0.82, h // 3)
        d.text((w / 2, h / 2), brand, font=f, fill=(14, 15, 18), anchor="mm")
    return tile.rotate(tilt, Image.BICUBIC, expand=True) if tilt else tile


def _arrow(canvas, start, end, color, width=22, head=56, outline=(14, 15, 18), bend=0.28):
    """Smooth, thick curved arrow (quadratic curve bowing upwards) with an outline and a clean head."""
    import math
    (x1, y1), (x2, y2) = start, end
    dist = math.hypot(x2 - x1, y2 - y1) or 1
    nx, ny = -(y2 - y1) / dist, (x2 - x1) / dist          # normal; bow towards the top of the frame
    if ny > 0:
        nx, ny = -nx, -ny
    mx, my = (x1 + x2) / 2 + nx * dist * bend, (y1 + y2) / 2 + ny * dist * bend
    pts = [((1 - t) ** 2 * x1 + 2 * (1 - t) * t * mx + t * t * x2,
            (1 - t) ** 2 * y1 + 2 * (1 - t) * t * my + t * t * y2) for t in [i / 40 for i in range(41)]]
    ang = math.atan2(y2 - pts[-4][1], x2 - pts[-4][0])
    back = (x2 - head * 0.8 * math.cos(ang), y2 - head * 0.8 * math.sin(ang))
    shaft = [p for p in pts if math.hypot(p[0] - x2, p[1] - y2) > head * 0.7] + [back]
    tri = lambda h: [(x2 + (h - head) * 0.0 * math.cos(ang), y2),
                     (x2 - h * math.cos(ang - 0.5), y2 - h * math.sin(ang - 0.5)),
                     (x2 - h * math.cos(ang + 0.5), y2 - h * math.sin(ang + 0.5))]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.line(shaft, fill=(0, 0, 0, 120), width=width + 14, joint="curve")
    shadow = layer.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(shadow, (4, 7))
    d = ImageDraw.Draw(canvas)
    d.line(shaft, fill=outline, width=width + 12, joint="curve")
    for p in (shaft[0],):
        d.ellipse([p[0] - (width + 12) / 2, p[1] - (width + 12) / 2, p[0] + (width + 12) / 2, p[1] + (width + 12) / 2],
                  fill=outline)
    d.polygon(tri(head + 12), fill=outline)
    d.line(shaft, fill=color, width=width, joint="curve")
    d.ellipse([shaft[0][0] - width / 2, shaft[0][1] - width / 2, shaft[0][0] + width / 2, shaft[0][1] + width / 2],
              fill=color)
    d.polygon(tri(head), fill=color)


def key_fact(data):
    """The most clickable real number from the review's fact stickers: ('$0', 'MONTHLY FEE')."""
    best = None
    for seg in data.get("segments", []):
        c = (seg.get("callout") or "").strip()
        m = re.search(r"(\$\s?\d[\d,.]*(?:[kmb](?![a-z]))?\+?(?:\s?/\s?(?:mo|month|yr|year))?|\d[\d,.]*\s?%"
                      r"|\d[\d,.]*\s?(?:x|stars?|★))", c, re.I)
        if not m:
            continue
        big = m.group(1).replace(" ", "")
        rest = (c[:m.start()] + c[m.end():]).strip(" -–:·,")
        rest = " ".join(rest.split()[:3]).upper()
        rank = 0 if big.startswith("$") else (1 if "%" in big else 2)
        if len(big) <= 9 and (best is None or rank < best[0]):
            best = (rank, big.upper().replace("STARS", "★").replace("STAR", "★"), rest)
    return (best[1], best[2]) if best else None


def _best_focus(data, info):
    """(screenshot, centre, box) of the most clickable highlighted fact: one whose on-screen text
    or sticker has a number ($, %), else the first highlight, else the first screenshot."""
    cands = [s for s in data.get("segments", []) if s.get("focus_box") and s.get("screenshot") != "mobile.png"]
    num = re.compile(r"[$%]|\d")
    cands.sort(key=lambda s: (not num.search(s["focus_box"].get("t", "")), not num.search(s.get("callout") or "")))
    if cands:
        b = cands[0]["focus_box"]
        return cands[0]["screenshot"], (b["x"] + b["w"] / 2, b["y"] + b["h"] / 2), b
    return info["screenshots"][0]["file"], None, None


def _verdict_style(data):
    v = data.get("verdict", "Worth it for some")
    return {"Worth it": ((34, 197, 94), "check"), "Not worth it": ((239, 68, 68), "close")}.get(
        v, ((255, 184, 0), "priority_high"))


def _score(data):
    try:
        return max(0.0, min(10.0, float(data.get("score", 0))))
    except (TypeError, ValueError):
        return 0.0


def pick_palette(theme, recent=()):
    rnd = random.Random(theme["seed"] + "pal")
    names = list(PALETTES)
    fresh = [n for n in names if n not in recent] or names
    return rnd.choice(fresh)

# ------------------------------------------------------------------ layouts
# One grid for every thumbnail: the product's logo big in the top-left corner, the hook huge in the
# left column, a "hero" filling the right side (zoomed-in screenshot with a red circle and an arrow,
# a fact sticker, a score ring, the phone app or a magnifier), all on a blurred, colour-graded
# screenshot of the product with soft lights. Nothing is left empty.
HERO_X = 652                         # where the right-hand hero starts; the text column ends before it
LOGO_BOX = (40, 30, 620, 190)        # x, y, max width, max height of the logo chip
CIRCLE_RED = (255, 38, 48)


def _fits(layout, hk, has_mobile, fact):
    return not ((layout == "phone" and not has_mobile) or (layout == "fact" and not fact))


def pick_layouts(theme, hooks, has_mobile, fact):
    """One layout per variation, all different."""
    rnd = random.Random(theme["seed"] + "variants")
    first = theme.get("thumb")
    if first not in LAYOUTS or not _fits(first, hooks[0], has_mobile, fact):
        first = rnd.choice([l for l in ("circle", "split", "fact") if _fits(l, hooks[0], has_mobile, fact)])
    out = [first]
    for hk in hooks[1:]:
        cands = [l for l in LAYOUTS if l not in out and _fits(l, hk, has_mobile, fact)]
        out.append(rnd.choice(cands))
    return out


def pick_palettes(theme, n=3):
    rnd = random.Random(theme["seed"] + "palettes")
    first = theme.get("thumb_palette") or pick_palette(theme)
    rest = [p for p in PALETTES if p != first]
    rnd.shuffle(rest)
    light = first in LIGHT_PALETTES
    rest.sort(key=lambda p: (p in LIGHT_PALETTES) == light)
    out = [first]
    for p in rest:
        if len(out) >= n:
            break
        if not (p in LIGHT_PALETTES and any(q in LIGHT_PALETTES for q in out)):
            out.append(p)
    return out


def _pill_text(data, hk, fact, i):
    sub = (data.get("thumbnail_subtitle") or "").strip()
    norm = lambda s: re.sub(r"[^a-z]", "", s.lower())
    if fact and (i == 1 or not sub):
        return f"{fact[0]} {fact[1]}".strip()[:24]
    if sub and norm(sub) not in norm(hk["text"]) and norm(hk["text"]) not in norm(sub):
        return sub
    return f"{data.get('verdict') or 'Honest review'}"


def _detail(im):
    """How much readable detail (text, numbers, buttons) an image region has, 0..1."""
    small = im.convert("L").resize((max(1, im.width // 6), max(1, im.height // 6)))
    e = small.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    return sum(e.getdata()) / 255 / max(1, e.width * e.height)


def _hero_source(data, info, out_dir, aspect=0.9):
    """(screenshot, crop box, target point in the crop, target box or None) for the hero: the review's
    highlighted fact when there is one, else the most detailed part of the most detailed screenshot.
    Blank or near-empty crops (cookie walls, loading screens) are skipped."""
    cands = []
    name, focus, box = _best_focus(data, info)
    if focus:
        cands.append((name, focus, box))
    for s in info["screenshots"]:
        if s["file"] != "mobile.png":
            cands.append((s["file"], None, None))
    best = None
    for name, focus, box in cands:
        try:
            src = Image.open(out_dir / name).convert("RGB")
        except OSError:
            continue
        cw = int(src.width * 0.5)
        ch = min(src.height, int(cw * aspect))
        fx, fy = focus or busiest_point(src, (cw, ch))
        x0 = int(max(0, min(src.width - cw, fx - cw / 2)))
        y0 = int(max(0, min(src.height - ch, fy - ch / 2)))
        crop = src.crop((x0, y0, x0 + cw, y0 + ch))
        score = _detail(crop) + (0.05 if box else 0)
        if box:
            target, tbox = (fx - x0, fy - y0), (box["x"] - x0, box["y"] - y0, box["w"], box["h"])
        else:
            tx, ty = busiest_point(crop, (int(cw * 0.34), int(ch * 0.26)))
            target, tbox = (tx, ty), None
        if best is None or score > best[0]:
            best = (score, src, crop, target, tbox)
        if score > 0.06 and (box or best[0] == score):
            break
    _, src, crop, target, tbox = best
    return src, crop, target, tbox


def _rot_point(pt, size, angle, new_size):
    """Where a point of an image lands after PIL's rotate(angle, expand=True)."""
    import math
    a = math.radians(angle)
    cx, cy = size[0] / 2, size[1] / 2
    dx, dy = pt[0] - cx, pt[1] - cy
    return (new_size[0] / 2 + dx * math.cos(a) + dy * math.sin(a),
            new_size[1] / 2 - dx * math.sin(a) + dy * math.cos(a))


def _ring(draw_on, cx, cy, rx, ry, color=CIRCLE_RED, width=11):
    """Hand-drawn style circle: two slightly offset strokes with a white edge and a red glow."""
    glow = Image.new("RGBA", draw_on.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=(*color, 200), width=width + 16)
    draw_on.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(draw_on)
    d.ellipse([cx - rx - 3, cy - ry - 3, cx + rx + 3, cy + ry + 3], outline=(255, 255, 255), width=width + 6)
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=color, width=width)
    d.arc([cx - rx - 10, cy - ry + 4, cx + rx + 6, cy + ry + 10], 200, 330, fill=color, width=width - 3)


def _hero_card(bg, B, crop, target, tbox, tilt, glow_col, circle=True, width=700):
    """Big zoomed-in screenshot card on the right (bleeding off the edge), optional red circle.
    Returns the circle (cx, cy, rx, ry) in canvas coordinates, or the target point."""
    s = width / crop.width
    card = crop.resize((width, int(crop.height * s)), Image.LANCZOS)
    border = 10
    framed = rounded((card.width + border * 2, card.height + border * 2), 26, (255, 255, 255, 255))
    framed.alpha_composite(round_corners(card.convert("RGBA"), 18), (border, border))
    tx, ty = target[0] * s + border, target[1] * s + border
    if tbox:
        rx = max(70, tbox[2] * s / 2 + 34)
        ry = max(46, tbox[3] * s / 2 + 26)
    else:
        rx, ry = 120, 78
    rx, ry = min(rx, framed.width * 0.42), min(ry, framed.height * 0.3)
    if circle:
        _ring(framed, tx, ty, rx, ry)
    rot = framed.rotate(tilt, Image.BICUBIC, expand=True)
    x = HERO_X + 6
    y = max(14, (TH - rot.height) // 2 + 8)
    _halo(bg, (x + 40, y + 40, x + rot.width - 40, y + rot.height - 40), glow_col, 70, 210)
    paste_shadowed(bg, rot, (x, y), 30, 30, 210, 22)
    B.add("screenshot", (x, y, x + rot.width, y + rot.height), "hero")
    px, py = _rot_point((tx, ty), framed.size, tilt, rot.size)
    return x + px, y + py, rx, ry


def _logo_big(canvas, B, logo, brand, theme):
    """The product's logo, big, top-left, on a white chip with a soft glow. Returns its bottom y."""
    x, y, max_w, max_h = LOGO_BOX
    if logo is not None:
        inner = int(max_h / 1.76)
        chip = logo_chip(logo, inner, radius=30, light_bg=True)
        while chip.width > max_w and inner > 30:
            inner -= 4
            chip = logo_chip(logo, inner, radius=30, light_bg=True)
    else:
        d = ImageDraw.Draw(Image.new("L", (8, 8)))
        f = fit(d, brand.upper(), lambda s: head_font(theme["head_font"], s), max_w - 70, int(max_h * 0.55))
        tw = int(d.textlength(brand.upper(), font=f))
        chip = rounded((tw + 70, int(f.size * 1.5)), 28, (255, 255, 255, 255))
        ImageDraw.Draw(chip).text((35, chip.height / 2), brand.upper(), font=f, fill=(14, 15, 18), anchor="lm")
    _halo(canvas, (x, y, x + chip.width, y + chip.height), (255, 255, 255), 34, 70)
    paste_shadowed(canvas, chip, (x, y), 30, 22, 190, 12)
    B.add("logo", (x, y, x + chip.width, y + chip.height))
    return y + chip.height


def _text_style(theme, i, pal_light):
    """plain glowing text, or labels (dark labels with white text / white labels with dark text)."""
    style = ["plain", "labels", "plain"][(i + len(theme["seed"])) % 3]
    if style == "labels":
        return ((14, 15, 18), (255, 255, 255), 2.0) if not pal_light else ((255, 255, 255), (14, 15, 18), 2.0)
    return None


def render(data, info, out_dir, theme, layout, pal_name, hk, pill_text, variant=0):
    """Draw one thumbnail. Returns (image, Boxes)."""
    B = Boxes()
    theme = {**theme, "head_font": theme.get("thumb_font") or theme["head_font"]}   # bold display fonts here
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    b1, b2, ptxt, pacc, ppop = PALETTES[pal_name]
    pal_light = pal_name in LIGHT_PALETTES
    acc = pacc if lum(pacc) >= 80 else (ppop if lum(ppop) > 120 else (255, 212, 0))
    if pal_light:
        acc = pacc if lum(pacc) < 170 else (214, 24, 36)
    fact = key_fact(data)
    outline = (10, 10, 12) if lum(ptxt) > 128 else (255, 255, 255)
    pop = ppop if ppop not in (ptxt,) else theme["accent"]
    glow_col = _vivid(b2) if not pal_light else mix(pacc, (255, 255, 255), 0.2)
    tilt = abs(theme.get("thumb_tilt", 5)) or 5
    tilt = -tilt if (variant % 2 == 0) else tilt * 0.6
    src, crop, target, tbox = _hero_source(data, info, out_dir)

    bg = _pal_bg(src, pal_name, hero=(980, 360), ghost=0.42)
    if not pal_light:
        _left_fade(bg, strength=150, reach=0.58, color=mix(b1, (0, 0, 0), 0.75))
    sticker = _text_style(theme, variant, pal_light)
    head = dict(text_col=ptxt, stroke=0 if pal_light else 8, outline=outline)
    if sticker:
        head = dict(sticker=sticker)
    col_w = HERO_X - 44 - 26
    arrow_to = None

    if layout in ("circle", "fact", "lens"):
        cx, cy, rx, ry = _hero_card(bg, B, crop, target, tbox, tilt, glow_col, circle=(layout != "lens"))
        if layout == "circle":
            arrow_to = (cx - rx - 12, cy)
        elif layout == "lens":
            lr = 150
            zoom = _cover(crop, (lr * 2, lr * 2), focus=target, zoom=2.2)
            mask = Image.new("L", (lr * 2, lr * 2), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, lr * 2 - 1, lr * 2 - 1], fill=255)
            ring_col = acc if not pal_light else pop
            lens = Image.new("RGBA", (lr * 2 + 36, lr * 2 + 36), (0, 0, 0, 0))
            ImageDraw.Draw(lens).ellipse([0, 0, lr * 2 + 35, lr * 2 + 35], fill=(*ring_col, 255))
            inner = zoom.convert("RGBA")
            inner.putalpha(mask)
            lens.alpha_composite(inner, (18, 18))
            lx = int(max(HERO_X + 10, min(TW - lens.width - 30, cx - lens.width / 2)))
            ly = int(max(30, min(TH - lens.height - 120, cy - lens.height / 2)))
            _blob(bg, lx + lens.width / 2, ly + lens.height / 2, lr + 150, ring_col, 150)
            handle = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
            ImageDraw.Draw(handle).line([(lx + lens.width - 40, ly + lens.height - 40),
                                         (lx + lens.width + 70, ly + lens.height + 70)], fill=(*ring_col, 255), width=40)
            bg.alpha_composite(handle)
            paste_shadowed(bg, lens, (lx, ly), lr + 18, 30, 210, 18)
            B.add("lens", (lx, ly, lx + lens.width, ly + lens.height), "hero")
            arrow_to = (lx - 8, ly + lens.height / 2)
        else:  # fact: big number sticker on the card, arrow from it to the circled spot
            big, small = fact
            d = ImageDraw.Draw(bg)
            hf = lambda s: head_font(theme["head_font"], s)
            nf = fit(d, big, hf, 360, 150)
            sf = fit(d, small or " ", lambda s: font("Black", s), 360, 34)
            w = int(max(d.textlength(big, font=nf), d.textlength(small or "", font=sf))) + 64
            h = int(nf.getbbox("$0")[3] - nf.getbbox("$0")[1]) + (int(sf.size * 1.3) if small else 0) + 56
            col = pop if lum(pop) > 60 and pop != (255, 255, 255) else (255, 212, 0)
            st = rounded((w, h), 24, (*col, 255))
            sd = ImageDraw.Draw(st)
            ty0 = 26 - nf.getbbox("$0")[1]
            sd.text((32, ty0), big, font=nf, fill=readable_on(col))
            if small:
                sd.text((34, h - 26 - sf.size), small, font=sf, fill=readable_on(col))
            st = st.rotate(4, Image.BICUBIC, expand=True)
            sx, sy = HERO_X - 6, 36
            paste_shadowed(bg, st, (sx, sy), 24, 22, 200, 14)
            B.add("fact sticker", (sx, sy, sx + st.width, sy + st.height), "badge")
            if cy > sy + st.height + 60:
                _arrow(bg, (sx + st.width * 0.55, sy + st.height + 4), (cx - rx * 0.4, cy - ry - 8),
                       CIRCLE_RED, width=18, head=48, outline=(255, 255, 255))

    elif layout == "split":
        # the live site, crisp and zoomed, filling the right side behind a glowing diagonal edge
        x_top, x_bot = HERO_X + 70, HERO_X - 6
        right = _cover(crop, (TW - x_bot, TH), focus=target, zoom=1.0).convert("RGBA")
        sc = (TW - x_bot) / crop.width if crop.width / crop.height > (TW - x_bot) / TH else TH / crop.height
        layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        layer.alpha_composite(right, (x_bot, 0))
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(x_top, 0), (TW, 0), (TW, TH), (x_bot, TH)], fill=255)
        bg = Image.composite(layer, bg, mask)
        edge = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        ImageDraw.Draw(edge).line([(x_top, 0), (x_bot, TH)], fill=(*acc, 255), width=34)
        bg.alpha_composite(edge.filter(ImageFilter.GaussianBlur(20)))
        ImageDraw.Draw(bg).line([(x_top, 0), (x_bot, TH)], fill=acc, width=9)
        B.add("screenshot", (x_bot, 0, TW, TH), "hero")
        # the target inside the shown part (approximate cover crop maths)
        cxs, cys = right.width / 2, right.height / 2
        cx = x_bot + max(90, min(right.width - 90, cxs + (target[0] - crop.width / 2) * sc))
        cy = max(90, min(TH - 90, cys + (target[1] - crop.height / 2) * sc))
        rx = max(90, (tbox[2] * sc / 2 + 34) if tbox else 130)
        ry = max(60, (tbox[3] * sc / 2 + 26) if tbox else 84)
        _ring(bg, cx, cy, min(rx, 220), min(ry, 140))
        arrow_to = (cx - min(rx, 220) - 12, cy)

    elif layout == "ring":
        vcol, vicon = _verdict_style(data)
        faded = crop.resize((620, int(620 * crop.height / crop.width)), Image.LANCZOS)
        faded = ImageEnhance.Brightness(faded).enhance(0.55 if not pal_light else 0.9).convert("RGBA")
        fcard = rounded((faded.width + 16, faded.height + 16), 24, (255, 255, 255, 120))
        fcard.alpha_composite(round_corners(faded, 18), (8, 8))
        fcard = fcard.rotate(-tilt, Image.BICUBIC, expand=True)
        fcard.putalpha(fcard.getchannel("A").point(lambda a: int(a * 0.75)))
        bg.alpha_composite(fcard, (TW - fcard.width + 60, (TH - fcard.height) // 2))
        cxr, cyr, r = 975, 372, 212
        _blob(bg, cxr, cyr, r + 170, vcol, 140)
        ring = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rd.ellipse([cxr - r - 18, cyr - r - 18, cxr + r + 18, cyr + r + 18], fill=(14, 15, 18, 240))
        rd.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=(60, 62, 70, 255), width=32)
        rd.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90, -90 + 360 * _score(data) / 10, fill=(*vcol, 255), width=32)
        paste_shadowed(bg, ring.crop((cxr - r - 18, cyr - r - 18, cxr + r + 19, cyr + r + 19)),
                       (cxr - r - 18, cyr - r - 18), r + 18, 30, 200, 18)
        B.add("score", (cxr - r - 18, cyr - r - 18, cxr + r + 18, cyr + r + 18), "hero")
        d = ImageDraw.Draw(bg)
        hf = lambda s: head_font(theme["head_font"], s)
        d.text((cxr, cyr - 22), f"{_score(data):.1f}", font=fit(d, "10.0", hf, r * 1.45, 180), fill=(255, 255, 255),
               anchor="mm")
        d.text((cxr, cyr + 104), "/ 10", font=font("Black", 42), fill=(170, 174, 184), anchor="mm")
        b = icons.badge(vicon, 124, vcol, (255, 255, 255))
        if b is not None:
            paste_shadowed(bg, b, (cxr + r - 80, cyr - r - 22), 62, 16, 170, 8)

    else:  # phone
        ph = Image.open(out_dir / "mobile.png").convert("RGB")
        ph = ph.resize((int(ph.width * 640 / ph.height), 640), Image.LANCZOS)
        body = rounded((ph.width + 26, ph.height + 26), 50, (8, 8, 10, 255))
        body.alpha_composite(round_corners(ph.convert("RGBA"), 40), (13, 13))
        body = body.rotate(tilt * 0.8, Image.BICUBIC, expand=True)
        faded = crop.resize((560, int(560 * crop.height / crop.width)), Image.LANCZOS)
        fcard = rounded((faded.width + 16, faded.height + 16), 24, (255, 255, 255, 255))
        fcard.alpha_composite(round_corners(faded.convert("RGBA"), 18), (8, 8))
        fcard = fcard.rotate(-tilt, Image.BICUBIC, expand=True)
        fx, fy = TW - fcard.width + 90, (TH - fcard.height) // 2 + 40
        _halo(bg, (fx + 40, fy + 40, fx + fcard.width, fy + fcard.height - 40), glow_col, 60, 170)
        paste_shadowed(bg, fcard, (fx, fy), 24, 24, 170, 16)
        B.add("screenshot", (fx, fy, fx + fcard.width, fy + fcard.height), "hero")
        px, py = HERO_X + 40, (TH - body.height) // 2
        _halo(bg, (px + 30, py + 30, px + body.width - 30, py + body.height - 30), glow_col, 64, 210)
        paste_shadowed(bg, body, (px, py), 50, 30, 220, 22)
        B.add("phone", (px, py, px + body.width, py + body.height), "hero")

    top = _logo_big(bg, B, logo, brand, theme) + 22
    pill_col = pop if lum(b1) < 90 and pop != (255, 255, 255) else (theme["accent"] if not pal_light else (14, 15, 18))
    _column(bg, B, theme, 44, top, TH - 34, col_w, hk, acc, pill=pill_text, pill_col=pill_col, pill_size=40,
            gap=22, size=250, **head)
    if arrow_to:
        hb = next(r for n, k, r in reversed(B.items) if n == "headline")
        start = (min(hb[2] + 14, HERO_X - 20), hb[1] + (hb[3] - hb[1]) * 0.62)
        if arrow_to[0] - start[0] > 70:
            _arrow(bg, start, arrow_to, CIRCLE_RED, width=18, head=50, outline=(255, 255, 255))

    overlay = config.ASSETS_DIR / "thumbnail_overlay.png"
    if overlay.exists():
        bg.alpha_composite(Image.open(overlay).convert("RGBA").resize((TW, TH)))
    return bg, B


def make_thumbnails(data, info, out_dir: Path, theme: dict, count=3):
    """Three different thumbnails (layout, colours and hook text all differ). Files:
    911video-thumbnail-1.jpg ... -3.jpg (1 = matches the title). Returns their paths."""
    has_mobile = (out_dir / "mobile.png").exists()
    fact = key_fact(data)
    keys = pick_hooks(data, theme, count)
    hooks = [hook(k) for k in keys]
    layouts = pick_layouts(theme, hooks, has_mobile, fact)
    palettes = pick_palettes(theme, count)
    for old in out_dir.glob("*thumbnail*.jpg"):
        old.unlink()
    paths = []
    for i, (lay, pal, hk) in enumerate(zip(layouts, palettes, hooks), 1):
        im, B = render(data, info, out_dir, theme, lay, pal, hk, _pill_text(data, hk, fact, i - 1), variant=i - 1)
        problems = B.clashes() + [f"{n} near the edge" for n in B.outside()]
        if problems:
            print(f"   ! thumbnail {i} ({lay}): {', '.join(problems)}")
        out = out_dir / f"911video-thumbnail-{i}.jpg"
        im.convert("RGB").save(out, quality=92)
        if out.stat().st_size > 2_000_000:
            im.convert("RGB").save(out, quality=80)
        paths.append(out)
    theme["thumb"], theme["thumb_palette"] = layouts[0], palettes[0]      # remembered for variety
    theme["thumbs"] = [f"{l}/{p}/{k}" for l, p, k in zip(layouts, palettes, keys)]
    return paths


def thumbnails(folder: Path):
    """The thumbnail files of a finished video (old folders have a single thumbnail.jpg)."""
    return sorted(Path(folder).glob("*thumbnail*.jpg"))


def choose_thumbnail(folder: Path):
    """The one used for API uploads: a random pick among the variations."""
    found = thumbnails(folder)
    return random.choice(found) if found else None


def PALETTES_DARK(pal):
    """A dark version of a light palette, for layouts that need a dark stage."""
    return {**pal, "bg1": mix(pal["bg1"], (0, 0, 0), 0.82), "bg2": mix(pal["accent"], (0, 0, 0), 0.6),
            "text": (255, 255, 255)}
