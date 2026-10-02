"""Step 5: three clean, clickable 1280x720 thumbnails per video.

One visual language for all of them (modelled on the styles that work on YouTube):
  * one calm background colour per thumbnail (royal blue, navy, ocean, crimson, emerald, violet,
    charcoal), built from the product's own blurred screenshot, never two clashing hues;
  * the product's logo big on a white badge, with a small "BRAND REVIEW" line;
  * the hook in huge condensed type (Anton): white letters, black outline, one word in yellow;
  * one yellow label with a second hook in black;
  * crisp, real screenshots or the phone app as the picture.
Five layouts: centre stack (screenshots on both sides), YES/NO split, logo left with phone or
screenshot, half-screen site, and score. Every item is measured and checked so nothing important
overlaps (or sits under YouTube's duration badge), and nothing is left empty.

The 3 options of a video differ in layout, colour and hook ("IS IT WORTH IT?", "IS IT A SCAM?"...);
option 1 matches the video's title. Optional: assets/thumbnail_overlay.png is drawn on top.
"""
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import config, icons
from .visuals import fit, font, head_font, load_logo, mix, paste_shadowed, rounded, round_corners

TW, TH = 1280, 720
YELLOW, INK, WHITE = (255, 214, 0), (12, 12, 14), (255, 255, 255)
HEAD = "anton"                                   # bundled in assets/fonts (falls back to Inter)

LAYOUTS = ["stack", "left", "split", "score", "yes_no", "laptop", "number", "banner"]

# Calm single-hue backgrounds: (dark, mid). Text is always white/yellow, labels yellow/black.
PALETTES = {
    "royal": ((6, 30, 130), (20, 110, 255)),
    "midnight": ((6, 10, 48), (34, 58, 180)),
    "ocean": ((0, 44, 92), (0, 140, 230)),
    "crimson": ((80, 0, 10), (225, 16, 40)),
    "emerald": ((0, 56, 30), (0, 170, 84)),
    "violet": ((36, 4, 92), (128, 46, 255)),
    "magenta": ((70, 0, 52), (220, 20, 140)),
    "charcoal": ((8, 8, 12), (52, 56, 72)),
}
LIGHT_PALETTES = set()                           # every scheme is dark, so white text always reads


# ------------------------------------------------------------------ hooks (the big text)
# "|" breaks the line, "*" makes a word yellow, "!" makes a line full size. Without "!", the line
# with the yellow word is huge and the other one a smaller lead-in ("IS IT A" / "SCAM?").
HOOKS = {
    "worth": "IS IT|*WORTH *IT?",
    "worth_using": "!WORTH|!USING *IT?",
    "scam": "IS IT A|*SCAM?",
    "legit": "LEGIT OR|*HYPE?",
    "catch": "WHAT'S THE|*CATCH?",
    "expect": "WHAT TO|*EXPECT?",
    "truth": "THE HONEST|*TRUTH",
    "fees": "!HIDDEN|!*FEES?",
    "before": "!WATCH|!*FIRST!",
    "dont": "DON'T USE|IT *YET!",
    "good": "IS IT|ANY *GOOD?",
    "works": "DOES IT|*WORK?",
}
FAMILY = {"worth_using": "worth", "good": "works"}               # too similar to show side by side
STYLE_HOOK = {"scam": "scam", "expect": "expect", "worth": "worth_using", "legit": "legit",
              "before": "before", "catch": "catch", "truth": "truth", "fees": "fees", "dont": "dont",
              "actually": "worth", "good": "good", "honest": "worth"}
LEAD_IN = 0.64                                                    # size of the small lead-in line


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


# ------------------------------------------------------------------ facts from the review
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


def _score(data):
    try:
        return max(0.0, min(10.0, float(data.get("score", 0))))
    except (TypeError, ValueError):
        return 0.0


def pick_palette(theme, recent=()):
    rnd = random.Random(theme["seed"] + "pal")
    names = list(PALETTES)
    return rnd.choice([n for n in names if n not in recent] or names)


# ------------------------------------------------------------------ placement checks
TIMESTAMP = (TW - 230, TH - 80, TW, TH)          # YouTube's duration badge covers this corner


class Boxes:
    """Where the important things went. kind: "text" (logo, hook, label...), "hero" (screenshot, phone,
    score ring), "zone" (keep clear). Text may not touch anything; heroes may touch each other."""

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
                if "text" not in (k1, k2) or "backdrop" in (k1, k2):      # badges may sit on a backdrop
                    continue
                if min(r1[2], r2[2]) - max(r1[0], r2[0]) > tol and min(r1[3], r2[3]) - max(r1[1], r2[1]) > tol:
                    out.append(f"{n1} / {n2}")
        return out

    def outside(self, margin=16):
        return [n for n, k, r in self.items if k == "text" and
                (r[0] < margin or r[1] < margin or r[2] > TW - margin or r[3] > TH - margin)]


# ------------------------------------------------------------------ pictures from the site
def _cover(im, size, focus=None, anchor=(0.5, 0.5)):
    r = max(size[0] / im.width, size[1] / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    fx, fy = focus if focus else (im.width / r / 2, im.height / r / 2)
    x = int(max(0, min(im.width - size[0], fx * r - size[0] * anchor[0])))
    y = int(max(0, min(im.height - size[1], fy * r - size[1] * anchor[1])))
    return im.crop((x, y, x + size[0], y + size[1]))


def _detail(im):
    """How much readable detail (text, buttons, pictures) an image has, 0..1."""
    small = im.convert("L").resize((max(1, im.width // 6), max(1, im.height // 6)))
    e = small.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    return sum(e.getdata()) / 255 / max(1, e.width * e.height)


def _busiest(im, win):
    """Centre (in image pixels) of the most detailed window of the given output size."""
    r = max(win[0] / im.width, win[1] / im.height)
    ww, wh = win[0] / r, win[1] / r                        # window size in image pixels
    small = im.convert("L").resize((max(1, im.width // 8), max(1, im.height // 8)))
    e = small.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    sw, shh = max(1, int(ww / 8)), max(1, int(wh / 8))
    best, at = -1, (im.width / 2, im.height / 2)
    for x in range(0, max(1, e.width - sw + 1), 4):
        for y in range(0, max(1, e.height - shh + 1), 4):
            v = sum(e.crop((x, y, x + sw, y + shh)).getdata())
            if v > best:
                best, at = v, ((x + sw / 2) * 8, (y + shh / 2) * 8)
    return at


def _pages(info, out_dir):
    """The website screenshots worth showing (top of each page), most detailed first; blank ones
    (bot checks, loading screens) are left out."""
    pages = []
    for s in info["screenshots"]:
        if s["file"] == "mobile.png":
            continue
        try:
            im = Image.open(out_dir / s["file"]).convert("RGB")
        except OSError:
            continue
        top = im.crop((0, 0, im.width, min(im.height, int(im.width * 0.62))))
        pages.append((_detail(top), top))
    good = [p for p in pages if p[0] > 0.012] or pages
    good.sort(key=lambda p: -p[0])
    return [p[1] for p in good]


def _phone_shot(out_dir):
    p = out_dir / "mobile.png"
    if not p.exists():
        return None
    im = Image.open(p).convert("RGB")
    return im if _detail(im) > 0.01 else None


def _card(shot, width, tilt):
    """A website screenshot as a crisp card: thin white frame, rounded corners."""
    border = 8
    card = shot.resize((width, int(width * shot.height / shot.width)), Image.LANCZOS)
    framed = rounded((card.width + border * 2, card.height + border * 2), 22, (255, 255, 255, 255))
    framed.alpha_composite(round_corners(card.convert("RGBA"), 15), (border, border))
    return framed.rotate(tilt, Image.BICUBIC, expand=True) if tilt else framed


def _laptop(shot, screen_w):
    """Laptop mockup: dark bezel around the site, aluminium base."""
    sw, sh = screen_w, int(screen_w * 0.625)
    scr = _cover(shot, (sw, sh), anchor=(0.5, 0.0))
    bez = 16
    lid = rounded((sw + bez * 2, sh + bez * 2 + 10), 22, (16, 16, 20, 255))
    lid.paste(scr, (bez, bez))
    base_w, base_h = int((sw + bez * 2) * 1.14), 26
    im = Image.new("RGBA", (base_w, lid.height + base_h), (0, 0, 0, 0))
    im.alpha_composite(lid, ((base_w - lid.width) // 2, 0))
    base = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    bd.rounded_rectangle([0, 0, base_w - 1, base_h - 1], 12, fill=(198, 202, 210, 255))
    bd.rectangle([0, 0, base_w - 1, 6], fill=(226, 229, 235, 255))
    bd.rounded_rectangle([base_w // 2 - 70, 0, base_w // 2 + 70, 9], 5, fill=(160, 164, 172, 255))
    im.alpha_composite(base, (0, lid.height))
    return im


def _phone(shot, height, tilt):
    """Phone mockup: black bezel, rounded screen."""
    scr = shot.resize((int(shot.width * (height - 28) / shot.height), height - 28), Image.LANCZOS)
    scr = scr.crop((0, 0, scr.width, scr.height))
    body = rounded((scr.width + 28, height), 58, (10, 10, 12, 255))
    ImageDraw.Draw(body).rounded_rectangle([2, 2, body.width - 3, body.height - 3], 56, outline=(70, 72, 80), width=3)
    body.alpha_composite(round_corners(scr.convert("RGBA"), 44), (14, 14))
    return body.rotate(tilt, Image.BICUBIC, expand=True) if tilt else body


# ------------------------------------------------------------------ background
def _backdrop(shot, pal, light_at=(640, 330)):
    """Single-hue background: the site's screenshot blurred and tinted in the palette colour, a soft
    lighter centre, two faint diagonal light bands and darker edges. `pal` is a name or (dark, mid)."""
    dark, mid = PALETTES[pal] if isinstance(pal, str) else pal
    base = Image.new("RGB", (TW, TH), dark)
    glow = Image.radial_gradient("L").resize((TW * 2, TH * 2))
    glow = glow.crop((TW - light_at[0], TH - light_at[1], 2 * TW - light_at[0], 2 * TH - light_at[1]))
    base = Image.composite(base, Image.new("RGB", (TW, TH), mid), glow.point(lambda v: min(255, int(v * 1.25))))
    if shot is not None:
        ghost = _cover(shot, (TW, TH)).filter(ImageFilter.GaussianBlur(16)).convert("L")
        ghost = ImageOps.colorize(ImageOps.autocontrast(ghost), dark, mix(mid, (255, 255, 255), 0.25))
        base = Image.blend(base, ghost, 0.18)
    base = ImageEnhance.Color(base).enhance(1.45)                 # rich, saturated colour
    bg = base.convert("RGBA")
    bands = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    d = ImageDraw.Draw(bands)
    light = (*mix(mid, (255, 255, 255), 0.3), 26)
    d.polygon([(TW * 0.08, TH), (TW * 0.42, 0), (TW * 0.56, 0), (TW * 0.22, TH)], fill=light)
    d.polygon([(TW * 0.62, TH), (TW * 0.9, 0), (TW * 0.97, 0), (TW * 0.69, TH)], fill=light)
    bg.alpha_composite(bands.filter(ImageFilter.GaussianBlur(3)))
    edge = Image.radial_gradient("L").resize((TW, TH)).point(lambda v: max(0, int((v - 110) * 0.9)))
    shade = Image.new("RGBA", (TW, TH), (*mix(dark, (0, 0, 0), 0.25), 255))
    shade.putalpha(edge)
    bg.alpha_composite(shade)
    return bg


def _glow(canvas, rect, color, spread=60, alpha=150):
    """Soft light behind an object, same hue as the background (never a second colour)."""
    x0, y0, x1, y1 = rect
    layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0, y0, x1, y1], 40, fill=(*color, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(spread)))


# ------------------------------------------------------------------ type
def _hf(size):
    return head_font(HEAD, size)


def _fit_hook(hk, max_w, max_h, start=280):
    """Biggest hook that fits max_w x max_h. Tries the hook's own lines and, when there's height to
    spare, one word per line for the big lines ("WORTH IT?" -> "WORTH" / "IT?")."""
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    options = [(hk["lines"], hk["big"])]
    sl, sb = [], []
    for l, b in zip(hk["lines"], hk["big"]):
        parts = [[w] for w in l] if b and len(l) > 1 else [l]
        sl += parts
        sb += [b] * len(parts)
    if len(sl) != len(hk["lines"]) and len(sl) <= 4:
        options.append((sl, sb))
    best = None
    for lines, big in options:
        scales = [1.0] * len(lines) if all(big) or not any(big) else [1.0 if b else LEAD_IN for b in big]
        size = start
        while True:
            fonts = [_hf(max(14, int(size * s))) for s in scales]
            boxes = [f.getbbox("HQ?!") for f in fonts]
            caps = [b[3] - b[1] for b in boxes]
            stroke = max(5, int(size * 0.05))
            gap = max(8, int(size * 0.06))
            widths = [d.textlength(" ".join(l), font=f) for l, f in zip(lines, fonts)]
            w = max(widths) + stroke * 2
            h = sum(caps) + gap * (len(lines) - 1) + stroke * 2
            if (w <= max_w and h <= max_h) or size <= 40:
                break
            size -= 3
        m = {"lines": lines, "fonts": fonts, "tops": [b[1] for b in boxes], "caps": caps, "widths": widths,
             "w": w, "h": h, "stroke": stroke, "gap": gap, "size": size}
        if best is None or size > best["size"] + 6:
            best = m
    return best


def _draw_hook(canvas, B, m, x, y, accent, align="left"):
    """White words, one yellow, black outline and a soft drop shadow. (x, y) = top-left or top-centre."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    words = []
    vy = y + m["stroke"]
    d = ImageDraw.Draw(canvas)
    for line, f, top, cap, tw in zip(m["lines"], m["fonts"], m["tops"], m["caps"], m["widths"]):
        lx = x - tw / 2 if align == "center" else x + m["stroke"]
        cx = lx
        for wd in line:
            col = YELLOW if wd in accent else WHITE
            words.append((cx, vy - top, wd, f, col))
            sd.text((cx, vy - top + 9), wd, font=f, fill=(0, 0, 0, 170), stroke_width=m["stroke"],
                    stroke_fill=(0, 0, 0, 170))
            cx += d.textlength(wd + " ", font=f)
        vy += cap + m["gap"]
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    for cx, cy, wd, f, col in words:
        d.text((cx, cy), wd, font=f, fill=col, stroke_width=m["stroke"], stroke_fill=INK)
    x0 = x - m["w"] / 2 if align == "center" else x
    B.add("hook", (x0, y, x0 + m["w"], y + m["h"]))
    return y + m["h"]


def _label(text, fill=YELLOW, fg=INK, size=40, max_w=560):
    """Rounded label: yellow with black text (or dark with white text)."""
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    text = text.upper()
    f = fit(d, text, lambda s: font("Black", s), max_w - 60, size)
    tw = int(d.textlength(text, font=f))
    h = int(f.size * 1.7)
    im = rounded((tw + 60, h), 18, (*fill, 255))
    ImageDraw.Draw(im).text((30, h / 2), text, font=f, fill=fg, anchor="lm")
    return im


def _logo_badge(logo, brand, max_w, max_h):
    """White rounded badge with the logo as big as fits (or the name in big type)."""
    pad = int(max_h * 0.2)
    if logo is not None:
        lg = logo.copy()
        lg.thumbnail((max_w - pad * 2, max_h - pad * 2), Image.LANCZOS)
        if lg.height < (max_h - pad * 2) * 0.6:                # wide wordmark: slimmer badge
            h = lg.height + pad * 2
        else:
            h = max_h
        badge = rounded((lg.width + pad * 2, h), 26, (255, 255, 255, 255))
        badge.alpha_composite(lg, (pad, (h - lg.height) // 2))
        return badge
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    f = fit(d, brand.upper(), _hf, max_w - pad * 2, int(max_h * 0.62))
    tw = int(d.textlength(brand.upper(), font=f))
    bb = f.getbbox(brand.upper())
    badge = rounded((tw + pad * 2, (bb[3] - bb[1]) + pad * 2), 26, (255, 255, 255, 255))
    ImageDraw.Draw(badge).text((pad, pad - bb[1]), brand.upper(), font=f, fill=INK)
    return badge


def _brand_block(canvas, B, logo, brand, x, y, max_w, max_h, align="left", review=True, pal=None):
    """Logo badge + "BRAND REVIEW" under it. Returns bottom y."""
    badge = _logo_badge(logo, brand, max_w, max_h)
    bx = x - badge.width // 2 if align == "center" else x
    paste_shadowed(canvas, badge, (bx, y), 26, 24, 150, 10)
    B.add("logo", (bx, y, bx + badge.width, y + badge.height))
    bottom = y + badge.height
    if review:
        d = ImageDraw.Draw(canvas)
        text = f"{brand.upper()} REVIEW"
        f = fit(d, text, lambda s: font("Black", s), max_w, 34)
        anchor = "ma" if align == "center" else "la"
        tx = x if align == "center" else x + 4
        col = mix(WHITE, PALETTES[pal][1], 0.18) if pal else (230, 234, 245)
        d.text((tx, bottom + 18), text, font=f, fill=col, anchor=anchor)
        bb = d.textbbox((tx, bottom + 18), text, font=f, anchor=anchor)
        B.add("brand name", bb)
        bottom = bb[3]
    return bottom


def _column(canvas, B, hk, x, top, bottom, max_w, label_text, align="left", label_fill=YELLOW, label_fg=INK):
    """Hook (as big as the space allows) with the label under it, all between top and bottom."""
    lab = _label(label_text, label_fill, label_fg, 40, min(max_w, 600)) if label_text else None
    lab_h = lab.height + 26 if lab else 0
    m = _fit_hook(hk, max_w, bottom - top - lab_h)
    block = m["h"] + lab_h
    y = top + max(0, (bottom - top - block) * 0.5)
    y = _draw_hook(canvas, B, m, x, y, hk["accent"], align)
    if lab:
        lx = x - lab.width // 2 if align == "center" else x + 4
        paste_shadowed(canvas, lab, (lx, y + 26), 18, 16, 140, 8)
        B.add("label", (lx, y + 26, lx + lab.width, y + 26 + lab.height))


# ------------------------------------------------------------------ layouts
def _fits(layout, hk, has_phone, has_pages, has_fact=True):
    if layout == "yes_no" and not hk["text"].endswith("?"):          # YES / NO needs a question
        return False
    if layout == "number" and not has_fact:
        return False
    return not (layout in ("split", "laptop", "banner") and not has_pages)


def pick_layouts(theme, hooks, has_phone, has_pages, has_fact=True):
    """One layout per variation, all different."""
    rnd = random.Random(theme["seed"] + "variants")
    ok = lambda l, hk: _fits(l, hk, has_phone, has_pages, has_fact)
    first = theme.get("thumb")
    if first not in LAYOUTS or not ok(first, hooks[0]):
        first = rnd.choice([l for l in ("stack", "left", "split", "laptop", "banner") if ok(l, hooks[0])])
    out = [first]
    for hk in hooks[1:]:
        cands = [l for l in LAYOUTS if l not in out and ok(l, hk)]
        out.append(rnd.choice(cands))
    return out


def pick_palettes(theme, n=3):
    rnd = random.Random(theme["seed"] + "palettes")
    first = theme.get("thumb_palette")
    if first not in PALETTES:
        first = pick_palette(theme)
    rest = [p for p in PALETTES if p != first]
    rnd.shuffle(rest)
    return [first] + rest[:n - 1]


def _label_text(data, hk, fact, i):
    sub = (data.get("thumbnail_subtitle") or "").strip()
    norm = lambda s: re.sub(r"[^a-z]", "", s.lower())
    if fact and (i == 1 or not sub):
        return f"{fact[0]} {fact[1]}".strip()[:26]
    if sub and norm(sub) not in norm(hk["text"]) and norm(hk["text"]) not in norm(sub):
        return sub[:26]
    return "HONEST REVIEW"


def render(data, info, out_dir, theme, layout, pal, hk, label_text, variant=0):
    """Draw one thumbnail. Returns (image, Boxes)."""
    B = Boxes()
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    pages = _pages(info, out_dir)
    phone = _phone_shot(out_dir)
    first = pages[0] if pages else (phone or Image.new("RGB", (1280, 800), PALETTES[pal][1]))
    dark, mid = PALETTES[pal]
    flip = -1 if variant % 2 else 1

    if layout in ("laptop", "number", "banner"):
        bg = _render_extra(layout, None, B, data, hk, label_text, logo, brand, pal, first, phone, pages, flip)

    elif layout == "stack":
        # logo top-centre, hook in the middle, screenshots leaning in from both sides
        bg = _backdrop(first, pal)
        shots = (pages + pages)[:2] if pages else [phone, phone]
        for side, shot in ((-1, shots[0]), (1, shots[1])):
            card = _card(shot, 470, 8 * side * -1)
            x = -230 if side < 0 else TW - card.width + 230
            y = (TH - card.height) // 2 + 40
            _glow(bg, (x, y, x + card.width, y + card.height), mix(mid, WHITE, 0.25), 50, 90)
            paste_shadowed(bg, card, (x, y), 22, 28, 190, 16)
            B.add(f"screenshot {side}", (x, y, x + card.width, y + card.height), "hero")
        top = _brand_block(bg, B, logo, brand, TW // 2, 34, 600, 140, "center", pal=pal) + 16
        _column(bg, B, hk, TW // 2, top, TH - 30, 650, label_text, "center")

    elif layout == "yes_no":
        green = _backdrop(first, "emerald", (300, 420))
        red = _backdrop(first, "crimson", (980, 420))
        green.alpha_composite(Image.new("RGBA", (TW, TH), (20, 170, 70, 70)))
        red.alpha_composite(Image.new("RGBA", (TW, TH), (210, 30, 30, 70)))
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (TW // 2 + 60, 0), (TW // 2 - 60, TH), (0, TH)], fill=255)
        bg = Image.composite(green, red, mask)
        ImageDraw.Draw(bg).line([(TW // 2 + 60, 0), (TW // 2 - 60, TH)], fill=(255, 255, 255, 230), width=6)
        one = {**hk, "lines": [[w for l in hk["lines"] for w in l]], "big": [True]}
        m = _fit_hook(one, 1180, 118, 150)
        band_h = int(m["h"] + 34)
        bg.alpha_composite(Image.new("RGBA", (TW, band_h), (*INK, 240)), (0, 0))
        _draw_hook(bg, B, m, TW // 2, (band_h - m["h"]) // 2, one["accent"], "center")
        mid_y = (band_h + TH) // 2 + 10
        for txt, icon, x, col in (("YES", "check", 255, (30, 200, 90)), ("NO", "close", TW - 255, (235, 60, 60))):
            b = icons.badge(icon, 132, WHITE, col)
            if b is not None:
                paste_shadowed(bg, b, (x - 66, mid_y - 190), 66, 18, 150, 8)
                B.add(f"{txt} icon", (x - 66, mid_y - 190, x + 66, mid_y - 58))
            ym = _fit_hook({"lines": [[txt]], "big": [True], "accent": set()}, 330, 200, 220)
            _draw_hook(bg, B, ym, x, mid_y - 36, set(), "center")
        badge = _logo_badge(logo, brand, 330, 190).rotate(-3, Image.BICUBIC, expand=True)
        tx, ty = TW // 2 - badge.width // 2, mid_y - badge.height // 2 - 40
        paste_shadowed(bg, badge, (tx, ty), 30, 30, 200, 18)
        B.add("logo", (tx, ty, tx + badge.width, ty + badge.height))
        lab = _label(f"{brand} review", INK, WHITE, 32, 380)
        lx, ly = TW // 2 - lab.width // 2, ty + badge.height + 22
        paste_shadowed(bg, lab, (lx, ly), 18, 16, 140, 8)
        B.add("label", (lx, ly, lx + lab.width, ly + lab.height))

    elif layout in ("left", "score"):
        bg = _backdrop(first, pal, (900, 360))
        if layout == "score":
            cx, cy, r = 985, 372, 205
            _glow(bg, (cx - r, cy - r, cx + r, cy + r), mix(mid, WHITE, 0.35), 70, 150)
            ring = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ring)
            rd.ellipse([cx - r - 16, cy - r - 16, cx + r + 16, cy + r + 16], fill=(*INK, 236))
            rd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 40), width=30)
            rd.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + 360 * _score(data) / 10, fill=(*YELLOW, 255), width=30)
            paste_shadowed(bg, ring.crop((cx - r - 16, cy - r - 16, cx + r + 17, cy + r + 17)),
                           (cx - r - 16, cy - r - 16), r + 16, 30, 190, 16)
            d = ImageDraw.Draw(bg)
            d.text((cx, cy - 16), f"{_score(data):.1f}", font=fit(d, "10.0", _hf, r * 1.35, 200), fill=WHITE,
                   anchor="mm", stroke_width=4, stroke_fill=INK)
            d.text((cx, cy + 108), "OUT OF 10", font=font("Black", 32), fill=(200, 204, 214), anchor="mm")
            B.add("score", (cx - r - 16, cy - r - 16, cx + r + 16, cy + r + 16), "hero")
            hero_x = cx - r - 16
        elif phone is not None:
            ph = _phone(phone, 660, 6 * flip)
            px, py = TW - ph.width - 100, (TH - ph.height) // 2
            _glow(bg, (px, py, px + ph.width, py + ph.height), mix(mid, WHITE, 0.3), 60, 130)
            paste_shadowed(bg, ph, (px, py), 56, 32, 210, 22)
            B.add("phone", (px, py, px + ph.width, py + ph.height), "hero")
            hero_x = px
        else:
            card = _card(first, 660, -6 * flip)
            px, py = TW - card.width + 140, (TH - card.height) // 2 + 20
            _glow(bg, (px, py, px + card.width, py + card.height), mix(mid, WHITE, 0.3), 60, 130)
            paste_shadowed(bg, card, (px, py), 22, 30, 200, 18)
            B.add("screenshot", (px, py, px + card.width, py + card.height), "hero")
            hero_x = px
        col_w = min(640, hero_x - 50 - 36)
        top = _brand_block(bg, B, logo, brand, 50, 40, min(560, col_w), 150, pal=pal) + 10
        _column(bg, B, hk, 46, top, TH - 34, col_w, label_text)

    else:  # split: the site crisp on the right half, a smooth fade into the colour panel
        bg = _backdrop(first, pal, (330, 360))
        x0 = 690
        right = _cover(first, (TW - x0, TH), focus=_busiest(first, (TW - x0, TH))).convert("RGBA")
        shade = Image.linear_gradient("L").rotate(-90).resize((60, TH)).point(lambda v: int(v * 0.75))
        sh = Image.new("RGBA", (60, TH), (0, 0, 0, 255))
        sh.putalpha(shade)                                     # soft shadow cast onto the panel
        bg.alpha_composite(sh, (x0 - 60, 0))
        bg.alpha_composite(right, (x0, 0))
        ImageDraw.Draw(bg).line([(x0, 0), (x0, TH)], fill=(*YELLOW, 255), width=6)
        B.add("screenshot", (x0, 0, TW, TH), "hero")
        top = _brand_block(bg, B, logo, brand, 50, 40, 560, 150, pal=pal) + 10
        _column(bg, B, hk, 46, top, TH - 34, x0 - 46 - 36, label_text)

    overlay = config.ASSETS_DIR / "thumbnail_overlay.png"
    if overlay.exists():
        bg.alpha_composite(Image.open(overlay).convert("RGBA").resize((TW, TH)))
    return bg, B


def _render_extra(layout, bg_args, B, data, hk, label_text, logo, brand, pal, first, phone, pages, flip):
    """The newer layouts: laptop (+ phone), big real number, banner."""
    dark, mid = PALETTES[pal]
    if layout == "laptop":
        bg = _backdrop(first, pal, (920, 360))
        lap = _laptop(first, 560)
        lx, ly = TW - lap.width - 34, (TH - lap.height) // 2 - (20 if phone is not None else 0)
        _glow(bg, (lx, ly, lx + lap.width, ly + lap.height), mix(mid, WHITE, 0.3), 60, 140)
        paste_shadowed(bg, lap, (lx, ly), 20, 30, 200, 18)
        B.add("laptop", (lx, ly, lx + lap.width, ly + lap.height), "hero")
        hero_x = lx
        if phone is not None:
            ph = _phone(phone, 400, 4 * flip)
            px, py = lx + lap.width - ph.width + 20, TH - ph.height - 24
            px = min(px, TW - ph.width - 12)
            paste_shadowed(bg, ph, (px, py), 40, 26, 210, 16)
            B.add("phone", (px, py, px + ph.width, py + ph.height), "hero")
        col_w = min(620, hero_x - 50 - 30)
        top = _brand_block(bg, B, logo, brand, 50, 40, min(560, col_w), 150, pal=pal) + 10
        _column(bg, B, hk, 46, top, TH - 34, col_w, label_text)
        return bg

    if layout == "number":
        big, small = key_fact(data)
        bg = _backdrop(first, pal, (940, 330))
        d = ImageDraw.Draw(bg)
        nm = _fit_hook({"lines": [[big]], "big": [True], "accent": {big}}, 560, 330, 360)
        nx, ny = 960, 130
        _glow(bg, (nx - nm["w"] / 2, ny, nx + nm["w"] / 2, ny + nm["h"]), mix(mid, WHITE, 0.35), 70, 150)
        _draw_hook(bg, B, nm, nx, ny, {big}, "center")
        if small:
            f = fit(d, small, lambda s: font("Black", s), 520, 54)
            d.text((nx, ny + nm["h"] + 26), small, font=f, fill=WHITE, anchor="ma", stroke_width=3, stroke_fill=INK)
            B.add("number label", d.textbbox((nx, ny + nm["h"] + 26), small, font=f, anchor="ma", stroke_width=3))
        top = _brand_block(bg, B, logo, brand, 50, 40, 560, 150, pal=pal) + 10
        _column(bg, B, hk, 46, top, TH - 34, 620, label_text)
        return bg

    # banner: the site as a wide window across the top, logo on its lower edge, hook in one huge line
    bg = _backdrop(first, pal, (640, 560))
    win_w, win_h = 1160, 380
    shot = _cover(first, (win_w, win_h), focus=_busiest(first, (win_w, win_h)), anchor=(0.5, 0.4))
    win = rounded((win_w, win_h + 40), 26, (255, 255, 255, 255))
    win.alpha_composite(round_corners(shot.convert("RGBA"), 22), (0, 40))
    wx, wy = (TW - win_w) // 2, -40
    _glow(bg, (wx, 0, wx + win_w, wy + win.height), mix(mid, WHITE, 0.3), 60, 120)
    paste_shadowed(bg, win, (wx, wy), 26, 30, 210, 20)
    B.add("screenshot", (wx, 0, wx + win_w, wy + win.height), "backdrop")
    badge = _logo_badge(logo, brand, 470, 124)
    bx, by = wx + 28, wy + win.height - badge.height // 2
    paste_shadowed(bg, badge, (bx, by), 26, 24, 190, 12)
    B.add("logo", (bx, by, bx + badge.width, by + badge.height))
    one = {**hk, "lines": [[w for l in hk["lines"] for w in l]], "big": [True]}
    lab = _label(label_text, YELLOW, INK, 38, 560) if label_text else None
    room_top = by + badge.height + 14
    room = TH - 30 - room_top - ((lab.height + 16) if lab else 0)
    m = _fit_hook(one, 1210, room, 240)
    y = room_top + max(0, (room - m["h"]) // 2)
    _draw_hook(bg, B, m, TW // 2, y, one["accent"], "center")
    if lab:
        lx, ly = TW // 2 - lab.width // 2, y + m["h"] + 16
        paste_shadowed(bg, lab, (lx, ly), 18, 16, 140, 8)
        B.add("label", (lx, ly, lx + lab.width, ly + lab.height))
    return bg


def make_thumbnails(data, info, out_dir: Path, theme: dict, count=3):
    """Three different thumbnails (layout, colours and hook text all differ). Files:
    911video-thumbnail-1.jpg ... -3.jpg (1 = matches the title). Returns their paths."""
    has_phone = _phone_shot(out_dir) is not None
    has_pages = bool(_pages(info, out_dir))
    fact = key_fact(data)
    keys = pick_hooks(data, theme, count)
    hooks = [hook(k) for k in keys]
    layouts = pick_layouts(theme, hooks, has_phone, has_pages, fact is not None)
    palettes = pick_palettes(theme, count)
    for old in out_dir.glob("*thumbnail*.jpg"):
        old.unlink()
    paths = []
    for i, (lay, pal, hk) in enumerate(zip(layouts, palettes, hooks), 1):
        im, B = render(data, info, out_dir, theme, lay, pal, hk, _label_text(data, hk, fact, i - 1), variant=i - 1)
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


# ------------------------------------------------------------------ Risk Case thumbnails
# A different look from the reviews: near-black with a red glow, the logo big, the story's damage in
# huge glowing red letters ("$70,000 GONE."), "WHAT HAPPENED?" with warning signs, and the post itself.
RED, DANGER = (255, 38, 44), ((16, 0, 4), (128, 6, 18))
RISK_LAYOUTS = ["alarm", "post", "evidence"]


def _red_text(canvas, B, m, x, y, align="center"):
    """Huge red letters with a red glow and a black outline."""
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    d = ImageDraw.Draw(canvas)
    vy = y + m["stroke"]
    words = []
    for line, f, top, cap, tw in zip(m["lines"], m["fonts"], m["tops"], m["caps"], m["widths"]):
        lx = x - tw / 2 if align == "center" else x + m["stroke"]
        txt = " ".join(line)
        gd.text((lx, vy - top), txt, font=f, fill=(*RED, 230), stroke_width=m["stroke"] + 18, stroke_fill=(*RED, 230))
        words.append((lx, vy - top, txt, f))
        vy += cap + m["gap"]
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(34)))
    for lx, ly, txt, f in words:
        d.text((lx, ly + 8), txt, font=f, fill=(0, 0, 0, 160), stroke_width=m["stroke"], stroke_fill=(0, 0, 0, 160))
    for lx, ly, txt, f in words:
        d.text((lx, ly), txt, font=f, fill=RED, stroke_width=m["stroke"], stroke_fill=(20, 0, 2))
    x0 = x - m["w"] / 2 if align == "center" else x
    B.add("big text", (x0, y, x0 + m["w"], y + m["h"]))
    return y + m["h"]


def _warn_line(canvas, B, text, x, y, size, align="center"):
    """'WHAT HAPPENED?' in white with a yellow warning sign on each side. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    f = _hf(size)
    tw = d.textlength(text, font=f)
    sign = icons.glyph("warning", int(size * 0.95), (255, 200, 0))
    gap = 18
    total = tw + ((sign.width + gap) * 2 if sign is not None else 0)
    x0 = x - total / 2 if align == "center" else x
    bb = f.getbbox(text)
    if sign is not None:
        paste_shadowed(canvas, sign, (x0, y + (bb[3] - bb[1] - sign.height) // 2 + 4), 10, 10, 120, 4)
        tx = x0 + sign.width + gap
    else:
        tx = x0
    d.text((tx, y - bb[1]), text, font=f, fill=WHITE, stroke_width=5, stroke_fill=INK)
    if sign is not None:
        paste_shadowed(canvas, sign, (tx + tw + gap, y + (bb[3] - bb[1] - sign.height) // 2 + 4), 10, 10, 120, 4)
    B.add("warning line", (x0, y, x0 + total, y + bb[3] - bb[1] + 10))
    return y + bb[3] - bb[1] + 10


def render_risk(data, info, out_dir, theme, layout, variant=0):
    """One Risk Case thumbnail. Returns (image, Boxes)."""
    B = Boxes()
    story = data.get("story") or {}
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    big = (story.get("thumb_big") or f"{story.get('amount') or 'ACCOUNT'} GONE.").upper()
    small = (story.get("thumb_small") or "WHAT HAPPENED?").upper()
    pages = _pages(info, out_dir)
    card_src = out_dir / "story.png"
    post = Image.open(card_src).convert("RGB") if card_src.exists() else None
    first = pages[0] if pages else post
    bg = _backdrop(first, DANGER, (640, 420) if layout == "alarm" else (380, 400))
    words = big.split()
    lines = [words] if len(words) <= 1 or len(big) <= 9 else [words[:-1], words[-1:]]
    hk = {"lines": lines, "big": [True] * len(lines), "accent": set()}

    if layout == "alarm":            # logo top-centre, giant red damage, warning line, screenshots faint behind
        if pages:
            for side, shot in ((-1, pages[0]), (1, (pages + pages)[1])):
                card = _card(shot, 430, 7 * -side)
                card.putalpha(card.getchannel("A").point(lambda a: int(a * 0.55)))
                x = -210 if side < 0 else TW - card.width + 210
                bg.alpha_composite(card, (x, (TH - card.height) // 2 + 60))
        top = _brand_block(bg, B, logo, brand, TW // 2, 30, 560, 140, "center", review=False) + 20
        m = _fit_hook(hk, 820, TH - top - 150, 260)
        y = _red_text(bg, B, m, TW // 2, top, "center")
        _warn_line(bg, B, small, TW // 2, min(y + 24, TH - 110), 74)

    else:                            # logo top-left, red damage left, the post (or the site) on the right
        hero = post if (layout == "post" and post is not None) else (pages[0] if pages else post)
        if hero is not None:
            crop = hero.crop((210, 130, 1710, 950)) if hero is post else hero
            card = _card(crop, 620, -5 if variant % 2 == 0 else 5)
            cx, cy = TW - card.width + 60, (TH - card.height) // 2 + 20
            _glow(bg, (cx, cy, cx + card.width, cy + card.height), RED, 60, 150)
            paste_shadowed(bg, card, (cx, cy), 22, 30, 210, 18)
            B.add("post" if hero is post else "screenshot", (cx, cy, cx + card.width, cy + card.height), "hero")
            if layout == "evidence":
                b = icons.badge("warning", 150, (255, 200, 0), INK)
                if b is not None:
                    bx, by = cx - 40, cy - 40                   # on the card's corner, not over the text
                    paste_shadowed(bg, b, (bx, by), 75, 24, 200, 10)
            hero_x = cx
        else:
            hero_x = TW - 60
        col_w = min(660, hero_x - 46 - 30)
        top = _brand_block(bg, B, logo, brand, 46, 34, min(540, col_w), 140, review=False) + 18
        m = _fit_hook(hk, col_w, TH - top - 140, 240)
        y = _red_text(bg, B, m, 46, top, "left")
        _warn_line(bg, B, small, 46, min(y + 22, TH - 110), 64, "left")

    overlay = config.ASSETS_DIR / "thumbnail_overlay.png"
    if overlay.exists():
        bg.alpha_composite(Image.open(overlay).convert("RGBA").resize((TW, TH)))
    return bg, B


def make_risk_thumbnails(data, info, out_dir: Path, theme: dict, count=3):
    """Three Risk Case thumbnails (different layouts). Same file names as the reviews."""
    rnd = random.Random(theme["seed"] + "risk")
    layouts = RISK_LAYOUTS[:]
    rnd.shuffle(layouts)
    for old in out_dir.glob("*thumbnail*.jpg"):
        old.unlink()
    paths = []
    for i, lay in enumerate(layouts[:count], 1):
        im, B = render_risk(data, info, out_dir, theme, lay, variant=i - 1)
        problems = B.clashes() + [f"{n} near the edge" for n in B.outside()]
        if problems:
            print(f"   ! risk thumbnail {i} ({lay}): {', '.join(problems)}")
        out = out_dir / f"911video-thumbnail-{i}.jpg"
        im.convert("RGB").save(out, quality=92)
        paths.append(out)
    theme["thumbs"] = [f"risk/{l}" for l in layouts[:count]]
    return paths
