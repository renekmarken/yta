"""Step 5: three clickable 1280x720 thumbnails per video.

Each video gets 3 variations to choose from, all different in layout (10 formats), colours (10
high-contrast palettes) and hook text ("IS IT WORTH IT?", "IS IT A SCAM?", "LEGIT OR HYPE?"...).
Every one shows the product's logo big and clear. Nothing is placed by guesswork: the logo, the
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
from .visuals import (background, fit, font, head_font, load_logo, logo_chip, lum, mix,
                      paste_shadowed, readable_on, rounded, round_corners, shadow_text)

TW, TH = 1280, 720

LAYOUTS = ["tilt_right", "split", "stack", "phone", "sticker",
           "big_fact", "verdict", "lens", "yes_no", "poster"]

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


def _blur_bg(shot, darken=0.38, tint=None):
    bg = _cover(shot, (TW, TH)).filter(ImageFilter.GaussianBlur(12))
    bg = ImageEnhance.Brightness(bg).enhance(darken).convert("RGBA")
    if tint:
        bg.alpha_composite(Image.new("RGBA", (TW, TH), (*tint, 40)))
    return bg


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


def _solid(pal, theme, style="spotlight"):
    """Palette background with a little depth (glow, dots or diagonal stripes)."""
    b1, b2, txt = pal["bg1"], pal["bg2"], pal["text"]
    return background({**theme, "bg": style, "bg1": b1, "bg2": b2, "accent": pal["accent"],
                       "accent2": pal["pop"], "light": lum(b1) > 150, "text": txt}, (TW, TH))

# ------------------------------------------------------------------ hooks (the big text)
# "|" breaks the line, "*" marks the accent word(s). The first variation matches the video's title
# style; the other two use different hooks, so you can test which one gets clicked.
HOOKS = {
    "worth": "IS IT|*WORTH *IT?",
    "worth_using": "WORTH|USING *IT?",
    "scam": "IS IT A|*SCAM?",
    "legit": "*LEGIT|OR HYPE?",
    "catch": "WHAT'S THE|*CATCH?",
    "expect": "WHAT TO|*EXPECT?",
    "truth": "THE HONEST|*TRUTH",
    "fees": "*HIDDEN|FEES?",
    "before": "WATCH|*FIRST!",
    "dont": "DON'T USE|IT *YET!",
    "good": "IS IT|ANY *GOOD?",
    "works": "DOES IT|*WORK?",
}
FAMILY = {"worth_using": "worth", "good": "works"}               # too similar to show side by side
STYLE_HOOK = {"scam": "scam", "expect": "expect", "worth": "worth_using", "legit": "legit",
              "before": "before", "catch": "catch", "truth": "truth", "fees": "fees", "dont": "dont",
              "actually": "worth", "good": "good", "honest": "worth"}


def hook(key):
    lines = [[w.lstrip("*") for w in ln.split()] for ln in HOOKS[key].split("|")]
    accent = {w.lstrip("*") for w in HOOKS[key].replace("|", " ").split() if w.startswith("*")}
    return {"key": key, "lines": lines, "accent": accent, "text": " ".join(" ".join(l) for l in lines)}


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
                if "text" not in (k1, k2):
                    continue
                if min(r1[2], r2[2]) - max(r1[0], r2[0]) > tol and min(r1[3], r2[3]) - max(r1[1], r2[1]) > tol:
                    out.append(f"{n1} / {n2}")
        return out

    def outside(self, margin=16):
        return [n for n, k, r in self.items if k == "text" and
                (r[0] < margin or r[1] < margin or r[2] > TW - margin or r[3] > TH - margin)]


def _head_metrics(theme, lines, max_w, max_h, size=160, sticker=False, stroke=7):
    """Biggest font for the hook that fits max_w x max_h. Returns (font, width, height, top, line step)."""
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    texts = [" ".join(l) for l in lines]
    extra = 44 if sticker else stroke * 2
    while True:
        f = head_font(theme["head_font"], size)
        top, bot = f.getbbox("HQ?!")[1], f.getbbox("HQ?!")[3]
        cap = bot - top
        step = cap + (46 if sticker else max(14, int(f.size * 0.13)) + stroke)
        w = max(d.textlength(t, font=f) for t in texts) + extra
        h = step * (len(lines) - 1) + cap + (28 if sticker else stroke * 2)
        if (w <= max_w and h <= max_h) or size <= 40:
            return f, w, h, top, step
        size -= 3


def _headline(canvas, B, x, y, theme, hk, max_w, max_h, accent, align="left", text_col=(255, 255, 255),
              stroke=7, size=160, sticker=None, outline=(10, 10, 12), metrics=None):
    """The hook in huge type with its accent word(s) coloured; its visual top is at y. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    f, w, h, top, step = metrics or _head_metrics(theme, hk["lines"], max_w, max_h, size, bool(sticker), stroke)
    pad = 22 if sticker else stroke
    for li, words in enumerate(hk["lines"]):
        full = " ".join(words)
        tw = d.textlength(full, font=f)
        lx = x - tw / 2 if align == "center" else (x - tw - pad if align == "right" else x + pad)
        vis = y + (14 if sticker else stroke) + li * step       # visual top of this line
        ly = vis - top
        if sticker:                                             # each line on a tilted label
            cap = f.getbbox("HQ?!")[3] - top
            box = rounded((int(tw + pad * 2), int(cap + 28)), 10, (*sticker[0], 255))
            box = box.rotate(sticker[2] * (1 if li % 2 else -1), Image.BICUBIC, expand=True)
            paste_shadowed(canvas, box, (lx - pad, vis - 14), 10, 12, 140, 8)
        cx = lx
        for wd in words:
            hot = wd in hk["accent"]
            if sticker:
                col = sticker[1]
                if hot:
                    col = accent if abs(lum(accent) - lum(sticker[0])) > 90 else \
                        ((255, 212, 0) if lum(sticker[0]) < 128 else (214, 24, 36))
            else:
                col = accent if hot else text_col
            ol = outline if abs(lum(col) - lum(outline)) > 90 else ((255, 255, 255) if lum(col) < 128 else (10, 10, 12))
            st = 0 if sticker else max(stroke, 5 if lum(col) < 90 else 0)
            shadow_text(canvas, (cx, ly), wd, f, col, stroke=st, stroke_fill=ol, opacity=0 if sticker else 190)
            cx += d.textlength(wd + " ", font=f)
    x0 = x - w / 2 if align == "center" else (x - w if align == "right" else x)
    B.add("headline", (x0, y, x0 + w, y + h))
    return y + h


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
            pill=None, pill_col=(255, 212, 0), pill_size=48, pill_tilt=0, align="left", gap=30, **head):
    """Logo at the top, pill at the bottom, the hook as big as the space between allows."""
    y = top
    if brand is not None:
        y = _brand(canvas, B, x, top, logo, brand, theme, align=align, dark_text=dark, max_w=max_w) + gap
    img = _pill_img(pill, pill_col, pill_size, min(max_w, 600), pill_tilt) if pill else None
    pill_y = bottom - img.height if img else bottom
    space = pill_y - (gap if img else 0) - y
    m = _head_metrics(theme, hk["lines"], max_w, space, head.get("size", 160), bool(head.get("sticker")),
                      head.get("stroke", 7))
    hy = y + max(0, space - m[2]) * 0.42
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


def _arrow(canvas, start, end, color, width=22, head=56, outline=(14, 15, 18)):
    """Thick curved-ish arrow (two segments) with an outlined head."""
    import math
    (x1, y1), (x2, y2) = start, end
    mx, my = (x1 + x2) / 2, min(y1, y2) - 40
    d = ImageDraw.Draw(canvas)
    pts = [(x1 + (mx - x1) * t * 2, y1 + (my - y1) * t * 2) if t < 0.5 else
           (mx + (x2 - mx) * (t - 0.5) * 2, my + (y2 - my) * (t - 0.5) * 2) for t in [i / 20 for i in range(21)]]
    ang = math.atan2(y2 - pts[-3][1], x2 - pts[-3][0])
    tip = (x2, y2)
    left = (x2 - head * math.cos(ang - 0.55), y2 - head * math.sin(ang - 0.55))
    right = (x2 - head * math.cos(ang + 0.55), y2 - head * math.sin(ang + 0.55))
    shaft = pts[:-2]
    d.line(shaft, fill=outline, width=width + 12, joint="curve")
    d.polygon([tip, left, right], fill=outline)
    d.line(shaft, fill=color, width=width, joint="curve")
    inset = [(tip[0] - 7 * math.cos(ang), tip[1] - 7 * math.sin(ang)),
             (left[0] + 5 * math.cos(ang - 1.2), left[1] + 5 * math.sin(ang - 1.2)),
             (right[0] + 5 * math.cos(ang + 1.2), right[1] + 5 * math.sin(ang + 1.2))]
    d.polygon(inset, fill=color)


def key_fact(data):
    """The most clickable real number from the review's fact stickers: ('$0', 'MONTHLY FEE')."""
    best = None
    for seg in data.get("segments", []):
        c = (seg.get("callout") or "").strip()
        m = re.search(r"(\$\s?\d[\d,.]*(?:\s?/\s?(?:mo|month|yr|year))?|\d[\d,.]*\s?%|\d[\d,.]*\s?(?:x|stars?|★))", c, re.I)
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
SCREEN_LAYOUTS = ["tilt_right", "split", "stack", "phone", "lens", "big_fact"]
BRAND_LAYOUTS = ["verdict", "poster", "yes_no", "sticker"]


def _fits(layout, hk, has_mobile, fact):
    return not ((layout == "phone" and not has_mobile) or (layout == "big_fact" and not fact)
                or (layout == "yes_no" and not hk["text"].endswith("?")))


def pick_layouts(theme, hooks, has_mobile, fact):
    """One layout per variation, all different; at least one shows the site, one puts the logo first."""
    rnd = random.Random(theme["seed"] + "variants")
    first = theme.get("thumb") or "tilt_right"
    if not _fits(first, hooks[0], has_mobile, fact):
        first = "tilt_right"
    out = [first]
    for i, hk in enumerate(hooks[1:], 1):
        fam = BRAND_LAYOUTS if out[0] in SCREEN_LAYOUTS and i == 1 else \
            (SCREEN_LAYOUTS if i == 1 else SCREEN_LAYOUTS + BRAND_LAYOUTS)
        cands = [l for l in fam if l not in out and _fits(l, hk, has_mobile, fact)] or \
                [l for l in LAYOUTS if l not in out and _fits(l, hk, has_mobile, fact)]
        out.append(rnd.choice(cands))
    return out


def pick_palettes(theme, n=3):
    rnd = random.Random(theme["seed"] + "palettes")
    first = theme.get("thumb_palette") or pick_palette(theme)
    rest = [p for p in PALETTES if p != first]
    rnd.shuffle(rest)
    light = first in LIGHT_PALETTES
    rest.sort(key=lambda p: (p in LIGHT_PALETTES) == light)    # mix light and dark looks
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


def render(data, info, out_dir, theme, layout, pal_name, hk, pill_text):
    """Draw one thumbnail. Returns (image, Boxes)."""
    B = Boxes()
    theme = {**theme, "head_font": theme.get("thumb_font") or theme["head_font"]}   # bold display fonts here
    shot = Image.open(out_dir / info["screenshots"][0]["file"]).convert("RGB")
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    b1, b2, ptxt, pacc, ppop = PALETTES[pal_name]
    pal = {"bg1": b1, "bg2": b2, "text": ptxt, "accent": pacc, "pop": ppop}
    pal_light = pal_name in LIGHT_PALETTES
    acc = pacc
    brand_col = theme["accent"]
    fact = key_fact(data)
    rnd = random.Random(theme["seed"] + layout)
    outline = (10, 10, 12) if lum(ptxt) > 128 else (255, 255, 255)
    pop = ppop if ppop not in (ptxt,) else brand_col
    tilt = abs(theme.get("thumb_tilt", 5)) or 5

    if layout == "tilt_right":
        bg = _blur_bg(shot, tint=b2)
        _left_fade(bg)
        card = _card(shot, 700, -tilt)
        cx, cy = TW - card.width + 150, 150
        paste_shadowed(bg, card, (cx, cy), 30, 26, 200, 20)
        B.add("screenshot", (cx, cy, cx + card.width, cy + card.height), "hero")
        _column(bg, B, theme, 58, 46, TH - 46, cx - 58 - 30, hk, acc, logo=logo, brand=brand,
                pill=pill_text, pill_col=ppop if lum(b1) < 90 and ppop != (255, 255, 255) else brand_col)

    elif layout == "split":
        bg = _cover(shot, (TW, TH), focus=busiest_point(shot, (1000, 900)), zoom=1.2,
                    anchor=(0.73, 0.5)).convert("RGBA")
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (720, 0), (600, TH), (0, TH)], fill=255)
        bg = Image.composite(_solid(pal, theme, "gradient"), bg, mask)
        ImageDraw.Draw(bg).line([(720, 0), (600, TH)], fill=acc if not pal_light else ppop, width=12)
        B.add("screenshot", (612, 0, TW, TH), "hero")
        _column(bg, B, theme, 54, 44, TH - 46, 540, hk, acc, logo=logo, brand=brand, dark=pal_light,
                pill=pill_text, pill_col=ppop if ppop != ptxt else brand_col, pill_size=44, text_col=ptxt,
                stroke=0 if pal_light else 6, outline=outline)

    elif layout == "stack":
        bg = _blur_bg(shot, darken=0.33, tint=b1)
        left, right = _card(shot, 520, 8), _card(shot, 520, -8)
        lpos, rpos = (-170, 500), (TW - right.width + 170, 510)
        for c, pos in ((left, lpos), (right, rpos)):
            paste_shadowed(bg, c, pos, 30, 22, 190, 16)
            B.add("screenshot", (pos[0], pos[1], pos[0] + c.width, pos[1] + c.height), "hero")
        veil = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        ImageDraw.Draw(veil).ellipse([140, -160, TW - 140, TH - 120], fill=(6, 8, 12, 150))
        bg.alpha_composite(veil.filter(ImageFilter.GaussianBlur(70)))
        _column(bg, B, theme, TW // 2, 34, 486, 1080, hk, acc, logo=logo, brand=brand, align="center", gap=22)
        img = _pill_img(pill_text, acc, 44, rpos[0] - (lpos[0] + left.width) - 50)
        _pill(bg, B, TW // 2, TH - 50 - img.height, pill_text, acc, align="center", img=img)

    elif layout == "phone":
        bg = _solid(pal, theme, "mesh") if not pal_light else _solid(PALETTES_DARK(pal), theme, "mesh")
        ph = Image.open(out_dir / "mobile.png").convert("RGB")
        ph = ph.resize((int(ph.width * 640 / ph.height), 640), Image.LANCZOS)
        body = rounded((ph.width + 24, ph.height + 24), 48, (8, 8, 10, 255))
        body.alpha_composite(round_corners(ph.convert("RGBA"), 38), (12, 12))
        body = body.rotate(theme.get("thumb_tilt", 5), Image.BICUBIC, expand=True)
        px = TW - body.width - 70
        paste_shadowed(bg, body, (px, 30), 48, 30, 210, 22)
        B.add("phone", (px, 30, px + body.width, 30 + body.height), "hero")
        _column(bg, B, theme, 58, 46, TH - 46, min(720, px - 58 - 40), hk,
                acc if not pal_light else (255, 212, 0), logo=logo, brand=brand,
                pill=pill_text, pill_col=ppop if not pal_light else brand_col)

    elif layout == "sticker":
        base_col = acc if lum(acc) > 60 else b1
        bg = background({**theme, "bg": "dots", "light": lum(base_col) > 150, "bg1": base_col,
                         "bg2": mix(base_col, (0, 0, 0), 0.18),
                         "text": (0, 0, 0) if lum(base_col) > 150 else (255, 255, 255)}, (TW, TH))
        card = _card(shot, 640, tilt)
        cx, cy = TW - card.width + 110, TH - card.height + 150
        paste_shadowed(bg, card, (cx, cy), 30, 24, 170, 18)
        B.add("screenshot", (cx, cy, cx + card.width, cy + card.height), "hero")
        dark_base = lum(base_col) > 110
        sticker = ((14, 15, 18), (255, 255, 255), 2.5) if dark_base else ((255, 255, 255), (14, 15, 18), 2.5)
        hl = ppop if ppop not in ((255, 255, 255), (14, 15, 18)) and abs(lum(ppop) - lum(base_col)) > 60 else \
            (brand_col if lum(brand_col) > 60 else (255, 80, 60))
        # the text column stops above the screenshot where they share a side
        _column(bg, B, theme, 64, 44, TH - 46, cx - 64 - 36, hk, hl, logo=logo, brand=brand,
                dark=lum(base_col) > 150, pill=pill_text, pill_col=(14, 15, 18) if dark_base else (255, 255, 255),
                pill_size=44, sticker=sticker, size=150)

    elif layout == "big_fact":
        # Giant real number (from the review) + arrow to where it appears on the site.
        bg = _solid(pal, theme, rnd.choice(["spotlight", "diagonal"]))
        name, focus, box = _best_focus(data, info)
        src = Image.open(out_dir / name).convert("RGB")
        crop = _cover(src, (700, 560), focus=focus or busiest_point(src, (900, 700)), zoom=1.15)
        card = _card(crop, 560, -tilt * 0.7, border=10)
        cx, cy = TW - card.width + 30, (TH - card.height) // 2 + 10
        paste_shadowed(bg, card, (cx, cy), 30, 28, 200, 20)
        B.add("screenshot", (cx, cy, cx + card.width, cy + card.height), "hero")
        col_w = cx - 52 - 70
        top = _brand(bg, B, 52, 40, logo, brand, theme, height=84, dark_text=pal_light, max_w=col_w, label=False) + 24
        m = _head_metrics(theme, hk["lines"], col_w, 210, 120, stroke=6)
        hy = TH - 44 - m[2]
        _headline(bg, B, 52, hy, theme, hk, col_w, 210, acc if not pal_light else pacc, text_col=ptxt,
                  stroke=0 if pal_light else 6, outline=outline, metrics=m)
        big, small = fact
        d = ImageDraw.Draw(bg)
        avail = hy - 26 - top
        sf = fit(d, small or "X", lambda s: font("Black", s), col_w, 50)
        small_h = int(sf.size * 1.3) if small else 0
        hf = lambda s: head_font(theme["head_font"], s)
        size = 230
        while size > 60:
            f = hf(size)
            bb = d.textbbox((0, 0), big, font=f, stroke_width=10)
            if bb[2] - bb[0] <= col_w and (bb[3] - bb[1]) + small_h <= avail:
                break
            size -= 4
        fcol = acc if abs(lum(acc) - lum(b1)) > 70 else ptxt
        block = (bb[3] - bb[1]) + small_h
        fy = top + (avail - block) * 0.45 - bb[1]
        shadow_text(bg, (52 - bb[0], fy), big, f, fcol, stroke=10,
                    stroke_fill=(14, 15, 18) if lum(fcol) > 110 else (255, 255, 255), opacity=150)
        nb = d.textbbox((52 - bb[0], fy), big, font=f, stroke_width=10)
        B.add("big number", nb)
        if small:
            shadow_text(bg, (56, nb[3] + 6), small, sf, ptxt, stroke=0 if pal_light else 4, stroke_fill=outline,
                        opacity=0 if pal_light else 140)
            B.add("number label", d.textbbox((56, nb[3] + 6), small, font=sf, stroke_width=4))
        _arrow(bg, (nb[2] + 18, (nb[1] + nb[3]) / 2), (cx + 110, cy + card.height * 0.32),
               ppop if ppop != ptxt else (255, 72, 66), outline=(14, 15, 18) if lum(ppop) > 128 else (255, 255, 255))

    elif layout == "verdict":
        # Score ring as the hook, the logo tile as the subject.
        bg = _solid(pal, theme, rnd.choice(["spotlight", "mesh"]))
        vcol, vicon = _verdict_style(data)
        tile = _logo_tile(logo, brand, theme, 220, tilt=-4)
        paste_shadowed(bg, tile, (60, 44), 44, 26, 170, 18)
        B.add("logo", (60, 44, 60 + tile.width, 44 + tile.height))
        d = ImageDraw.Draw(bg)
        nf = fit(d, f"{brand.upper()} REVIEW", lambda s: font("Black", s), 420, 36)
        d.text((64, 44 + tile.height + 18), f"{brand.upper()} REVIEW", font=nf, fill=ptxt)
        nb = B.add("brand name", d.textbbox((64, 44 + tile.height + 18), f"{brand.upper()} REVIEW", font=nf))
        cxr, cyr, r = 985, 350, 200
        ring = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rd.ellipse([cxr - r - 18, cyr - r - 18, cxr + r + 18, cyr + r + 18], fill=(14, 15, 18, 235))
        rd.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=(60, 62, 70, 255), width=30)
        rd.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90, -90 + 360 * _score(data) / 10, fill=(*vcol, 255), width=30)
        paste_shadowed(bg, ring.crop((cxr - r - 18, cyr - r - 18, cxr + r + 19, cyr + r + 19)),
                       (cxr - r - 18, cyr - r - 18), r + 18, 30, 200, 18)
        B.add("score", (cxr - r - 18, cyr - r - 18, cxr + r + 18, cyr + r + 18), "hero")
        hf = lambda s: head_font(theme["head_font"], s)
        d.text((cxr, cyr - 18), f"{_score(data):.1f}", font=fit(d, "10.0", hf, r * 1.4, 160), fill=(255, 255, 255),
               anchor="mm")
        d.text((cxr, cyr + 100), "/ 10", font=font("Black", 40), fill=(170, 174, 184), anchor="mm")
        b = icons.badge(vicon, 116, vcol, (255, 255, 255))
        if b is not None:
            paste_shadowed(bg, b, (cxr + r - 76, cyr - r - 16), 58, 16, 170, 8)
        _column(bg, B, theme, 60, nb[3] + 28, TH - 46, cxr - r - 18 - 60 - 36, hk, acc if not pal_light else pacc,
                pill=pill_text, pill_col=pop, pill_size=44, pill_tilt=-2, text_col=ptxt,
                stroke=0 if pal_light else 7, outline=outline, gap=24)

    elif layout == "lens":
        # Real screenshot with a magnifying glass on the key number.
        name, focus, box = _best_focus(data, info)
        src = Image.open(out_dir / name).convert("RGB")
        fpt = focus or busiest_point(src, (500, 400))
        bgimg = _cover(src, (TW, TH), focus=fpt, zoom=1.05, anchor=(0.62, 0.5))
        bg = ImageEnhance.Brightness(bgimg.filter(ImageFilter.GaussianBlur(7))).enhance(0.5).convert("RGBA")
        shade = mix(b1, (0, 0, 0), 0.55) if not pal_light else (12, 12, 16)
        _left_fade(bg, strength=255, reach=0.72, color=shade)
        _left_fade(bg, strength=200, reach=0.5, color=shade)
        lr = 200
        zoom_w = (box["w"] + 90) if box else 300            # source pixels shown inside the lens
        base = max(lr * 2 / src.width, lr * 2 / src.height)
        zoom = _cover(src, (lr * 2, lr * 2), focus=fpt, zoom=max(1.0, (lr * 2 / max(zoom_w, 1)) / base))
        mask = Image.new("L", (lr * 2, lr * 2), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, lr * 2 - 1, lr * 2 - 1], fill=255)
        lens = Image.new("RGBA", (lr * 2 + 40, lr * 2 + 40), (0, 0, 0, 0))
        ImageDraw.Draw(lens).ellipse([0, 0, lr * 2 + 39, lr * 2 + 39], fill=(*acc, 255))
        inner = zoom.convert("RGBA")
        inner.putalpha(mask)
        lens.alpha_composite(inner, (20, 20))
        lx, ly = 770, 96
        handle = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        ImageDraw.Draw(handle).line([(lx + lr * 2 - 10, ly + lr * 2 - 10), (lx + lr * 2 + 110, ly + lr * 2 + 110)],
                                    fill=(*acc, 255), width=46)
        bg.alpha_composite(handle)
        paste_shadowed(bg, lens, (lx, ly), lr + 20, 30, 210, 18)
        B.add("lens", (lx, ly, lx + lens.width, ly + lens.height), "hero")
        _column(bg, B, theme, 56, 46, TH - 46, lx - 56 - 40, hk, acc, logo=logo, brand=brand,
                pill=pill_text, pill_col=pop, pill_size=46, pill_tilt=2)

    elif layout == "yes_no":
        # Curiosity split: YES or NO? with the logo in the middle.
        left = background({**theme, "bg": "spotlight", "bg1": (20, 120, 60), "bg2": (6, 60, 30),
                           "accent": (60, 230, 120), "light": False}, (TW, TH))
        right = background({**theme, "bg": "spotlight", "bg1": (150, 20, 28), "bg2": (70, 6, 12),
                            "accent": (255, 80, 80), "light": False}, (TW, TH))
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (TW // 2 + 70, 0), (TW // 2 - 70, TH), (0, TH)], fill=255)
        bg = Image.composite(left, right, mask)
        d = ImageDraw.Draw(bg)
        d.line([(TW // 2 + 70, 0), (TW // 2 - 70, TH)], fill=(255, 255, 255), width=10)
        one = {**hk, "lines": [[w for l in hk["lines"] for w in l]]}
        m = _head_metrics(theme, one["lines"], 1160, 120, 130, stroke=6)
        band_h = int(m[2] + 40)
        bg.alpha_composite(Image.new("RGBA", (TW, band_h), (14, 15, 18, 235)), (0, 0))
        _headline(bg, B, TW // 2, 20, theme, one, 1160, 120, (255, 212, 0), align="center", stroke=6, metrics=m)
        hf = lambda s: head_font(theme["head_font"], s)
        mid = (band_h + TH) // 2 - 10
        for txt, icon, x, col in (("YES", "check", 230, (60, 230, 120)), ("NO", "close", TW - 230, (255, 90, 90))):
            b = icons.badge(icon, 140, (255, 255, 255), col)
            if b is not None:
                paste_shadowed(bg, b, (x - 70, mid - 150), 70, 20, 170, 10)
            f = fit(d, "YES", hf, 300, 140)
            shadow_text(bg, (x, mid + 10), txt, f, (255, 255, 255), stroke=8, anchor="ma", opacity=170)
            B.add(txt, d.textbbox((x, mid + 10), txt, font=f, anchor="ma", stroke_width=8))
        tile = _logo_tile(logo, brand, theme, 230, tilt=3)
        tx, ty = TW // 2 - tile.width // 2, mid - tile.height // 2 - 40
        paste_shadowed(bg, tile, (tx, ty), 46, 30, 210, 22)
        B.add("logo", (tx, ty, tx + tile.width, ty + tile.height))
        name = f"{brand.upper()} REVIEW"
        nf = fit(d, name, lambda s: font("Black", s), 380, 34)
        nw = d.textlength(name, font=nf)
        ny = ty + tile.height + 22
        d.rounded_rectangle([TW / 2 - nw / 2 - 22, ny, TW / 2 + nw / 2 + 22, ny + nf.size + 26], 14, fill=(14, 15, 18))
        d.text((TW / 2, ny + 13), name, font=nf, fill=(255, 255, 255), anchor="ma")
        B.add("brand name", (TW / 2 - nw / 2 - 22, ny, TW / 2 + nw / 2 + 22, ny + nf.size + 26))

    else:  # poster: bold logo-first poster
        bg = _solid(pal, theme, rnd.choice(["diagonal", "dots", "aurora"]))
        tile = _logo_tile(logo, brand, theme, 300, tilt=-5)
        tx, ty = 60, 76
        paste_shadowed(bg, tile, (tx, ty), 60, 34, 200, 24)
        B.add("logo", (tx, ty, tx + tile.width, ty + tile.height))
        d = ImageDraw.Draw(bg)
        nf = fit(d, brand.upper(), lambda s: font("Black", s), tile.width, 44)
        d.text((tx + tile.width / 2, ty + tile.height + 18), brand.upper(), font=nf, fill=ptxt, anchor="ma")
        nb = B.add("brand name", d.textbbox((tx + tile.width / 2, ty + tile.height + 18), brand.upper(),
                                            font=nf, anchor="ma"))
        ic = icons.pick({"callout": (fact or ("", ""))[1], "caption": hk["text"], "text": hk["text"]}) or "help"
        b = icons.badge(ic, 120, pop, readable_on(pop))
        if b is not None:
            b = b.rotate(12, Image.BICUBIC, expand=True)
            paste_shadowed(bg, b, (tx + tile.width - 76, ty - 52), 60, 18, 170, 10)
        col_l = tx + tile.width + 56
        m = _head_metrics(theme, hk["lines"], TW - 56 - col_l, TH - 96 - 56, 190, stroke=0 if pal_light else 8)
        _headline(bg, B, TW - 56, 56 + (TH - 96 - 56 - m[2]) * 0.45, theme, hk, 0, 0,
                  acc if not pal_light else pacc, text_col=ptxt, align="right", stroke=0 if pal_light else 8,
                  outline=outline, metrics=m)
        img = _pill_img(pill_text, (14, 15, 18) if not pal_light else (255, 255, 255), 40,
                        TW - 56 - m[1] - 30 - tx, -2)
        _pill(bg, B, tx, max(nb[3] + 24, TH - 46 - img.height), pill_text, None, img=img)

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
        im, B = render(data, info, out_dir, theme, lay, pal, hk, _pill_text(data, hk, fact, i - 1))
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
