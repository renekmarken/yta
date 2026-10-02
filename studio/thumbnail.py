"""Step 5: clickable 1280x720 thumbnail.

Every thumbnail has the site's logo, its name and "WORTH USING IT?", but the format changes from
video to video (10 layouts) and so does the colour scheme (10 high-contrast palettes), avoiding the
looks of the last few videos. Click-through basics are built in: one focal point, very few words,
huge high-contrast type with outlines, a curiosity hook, and a real number from the review where
one exists (taken from the video's fact stickers, so it is never invented).

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


def _headline(canvas, x, y, theme, max_w, accent, align="left", text_col=(255, 255, 255),
              stroke=7, size=150, sticker=None, lines=None, outline=(10, 10, 12)):
    """'WORTH / USING IT?' with one accent word. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    rnd = random.Random(theme["seed"] + "hl")
    hf = lambda s: head_font(theme["head_font"], s)
    lines = lines or [["WORTH"], ["USING", "IT?"]]
    longest = max((" ".join(l) for l in lines), key=lambda t: d.textlength(t, font=hf(size)))
    f = fit(d, longest, hf, max_w, size)
    accent_word = rnd.choice(["IT?", "IT?", "WORTH"])
    lh = int(f.size * 1.02)
    for li, words in enumerate(lines):
        full = " ".join(words)
        tw = d.textlength(full, font=f)
        lx = x - tw / 2 if align == "center" else (x - tw if align == "right" else x)
        ly = y + li * lh
        if sticker:                                      # each line on a tilted label
            pad = 18
            box = rounded((tw + pad * 2, f.size * 1.05), 10, (*sticker[0], 255))
            box = box.rotate(sticker[2] * (1 if li else -1), Image.BICUBIC, expand=True)
            paste_shadowed(canvas, box, (lx - pad, ly - 4), 10, 12, 140, 8)
        cx = lx
        for w in words:
            col = accent if w == accent_word and not sticker else (sticker[1] if sticker else text_col)
            if sticker and w == accent_word:
                col = accent if lum(accent) < 140 or lum(sticker[0]) < 128 else mix(accent, (0, 0, 0), 0.5)
            ol = outline if abs(lum(col) - lum(outline)) > 90 else ((255, 255, 255) if lum(col) < 128 else (10, 10, 12))
            shadow_text(canvas, (cx, ly), w, f, col, stroke=0 if sticker else max(stroke, 5 if lum(col) < 90 else 0),
                        stroke_fill=ol, opacity=0 if sticker else 190)
            cx += d.textlength(w + " ", font=f)
    return y + lh * len(lines)


def _pill(canvas, x, y, text, color, align="left", size=50, tilt=0):
    d = ImageDraw.Draw(canvas)
    text = text.upper()
    f = fit(d, text, lambda s: font("Black", s), 560, size)
    tw = int(d.textlength(text, font=f))
    pill = rounded((tw + 56, int(f.size * 1.6)), 18, (*color, 255))
    ImageDraw.Draw(pill).text((28, pill.height / 2), text, font=f, fill=readable_on(color), anchor="lm")
    if tilt:
        pill = pill.rotate(tilt, Image.BICUBIC, expand=True)
    px = x - pill.width // 2 if align == "center" else (x - pill.width if align == "right" else x)
    paste_shadowed(canvas, pill, (px, y), 18, 14, 170, 8)
    return pill.width, pill.height


def _brand(canvas, x, y, logo, brand, theme, height=78, align="left", label=True, dark_text=False):
    """Logo chip + brand name label. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    bottom = y
    if logo is not None:
        chip = logo_chip(logo, height, radius=24)
        cx = x - chip.width // 2 if align == "center" else (x - chip.width if align == "right" else x)
        paste_shadowed(canvas, chip, (cx, y), 24, 16, 170, 8)
        bottom = y + chip.height
        if label:
            name = f"{brand.upper()} REVIEW"
            f = font("Black", 26)
            anchor = {"center": "ma", "right": "ra"}.get(align, "la")
            d.text((x, bottom + 14), name, font=f, fill=(20, 20, 24) if dark_text else (235, 238, 244),
                   anchor=anchor)
            bottom += 44
    else:
        f = fit(d, brand.upper(), lambda s: head_font(theme["head_font"], s), 600, 92)
        anchor = {"center": "ma", "right": "ra"}.get(align, "la")
        shadow_text(canvas, (x, y), brand.upper(), f, (20, 20, 24) if dark_text else (255, 255, 255),
                    stroke=0 if dark_text else 5, opacity=0 if dark_text else 180, anchor=anchor)
        bottom = y + int(f.size * 1.1)
    return bottom


def _logo_tile(logo, brand, theme, size=260, tilt=0):
    """Big white rounded square with the logo (or brand name) — the hero of brand-first layouts."""
    tile = rounded((size, size), size // 5, (255, 255, 255, 255))
    if logo is not None:
        lg = logo.copy()
        lg.thumbnail((int(size * 0.74), int(size * 0.62)), Image.LANCZOS)
        tile.alpha_composite(lg, ((size - lg.width) // 2, (size - lg.height) // 2))
    else:
        d = ImageDraw.Draw(tile)
        f = fit(d, brand, lambda s: head_font(theme["head_font"], s), size * 0.82, size // 3)
        d.text((size / 2, size / 2), brand, font=f, fill=(14, 15, 18), anchor="mm")
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
def make_thumbnail(data, info, out_dir: Path, theme: dict) -> Path:
    original = theme
    theme = {**theme, "head_font": theme.get("thumb_font") or theme["head_font"]}   # bold display fonts here
    first = out_dir / info["screenshots"][0]["file"]
    shot = Image.open(first).convert("RGB")
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    pal_name = theme.get("thumb_palette") or pick_palette(theme)
    b1, b2, ptxt, pacc, ppop = PALETTES[pal_name]
    pal = {"bg1": b1, "bg2": b2, "text": ptxt, "accent": pacc, "pop": ppop}
    pal_light = pal_name in LIGHT_PALETTES
    acc = pacc
    brand_col = theme["accent"]
    hook = data.get("thumbnail_subtitle") or "Honest review"
    layout = theme["thumb"]
    has_mobile = (out_dir / "mobile.png").exists()
    fact = key_fact(data)
    if layout == "phone" and not has_mobile:
        layout = "tilt_right"
    if layout == "big_fact" and not fact:
        layout = "verdict"
    rnd = random.Random(theme["seed"] + "thumb")
    outline = (10, 10, 12) if lum(ptxt) > 128 else (255, 255, 255)

    if layout == "tilt_right":
        bg = _blur_bg(shot, tint=b2)
        _left_fade(bg)
        card = _card(shot, 760, theme["thumb_tilt"] if theme["thumb_tilt"] < 0 else -theme["thumb_tilt"])
        paste_shadowed(bg, card, (TW - card.width + 150, 150), 30, 26, 200, 20)
        _brand(bg, 60, 50, logo, brand, theme)
        _headline(bg, 56, 236, theme, 690, acc)
        _pill(bg, 60, 572, hook, ppop if lum(b1) < 90 and ppop != (255, 255, 255) else brand_col)

    elif layout == "split":
        bg = _cover(shot, (TW, TH), focus=busiest_point(shot, (1000, 900)), zoom=1.2,
                    anchor=(0.73, 0.5)).convert("RGBA")
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (720, 0), (600, TH), (0, TH)], fill=255)
        panel = _solid(pal, theme, "gradient")
        bg = Image.composite(panel, bg, mask)
        ImageDraw.Draw(bg).line([(720, 0), (600, TH)], fill=acc if not pal_light else ppop, width=12)
        _brand(bg, 56, 46, logo, brand, theme, height=70, dark_text=pal_light)
        _headline(bg, 52, 232, theme, 560, acc if not pal_light else pacc, text_col=ptxt,
                  stroke=0 if pal_light else 6)
        _pill(bg, 56, 580, hook, ppop if ppop != ptxt else brand_col, size=44)

    elif layout == "stack":
        bg = _blur_bg(shot, darken=0.33, tint=b1)
        for tilt, pos in ((8, (-140, 400)), (-8, (TW - 470, 410))):
            c = _card(shot, 600, tilt)
            paste_shadowed(bg, c, pos, 30, 22, 190, 16)
        veil = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        ImageDraw.Draw(veil).ellipse([140, -120, TW - 140, TH + 40], fill=(6, 8, 12, 150))
        bg.alpha_composite(veil.filter(ImageFilter.GaussianBlur(70)))
        b = _brand(bg, TW // 2, 34, logo, brand, theme, height=84, align="center")
        _headline(bg, TW // 2, b + 14, theme, 1000, acc, align="center", size=150)
        _pill(bg, TW // 2, 600, hook, acc, align="center", size=42)

    elif layout == "phone":
        bg = _solid(pal, theme, "mesh") if not pal_light else _solid(PALETTES_DARK(pal), theme, "mesh")
        ph = Image.open(out_dir / "mobile.png").convert("RGB")
        ph = ph.resize((int(ph.width * 640 / ph.height), 640), Image.LANCZOS)
        body = rounded((ph.width + 24, ph.height + 24), 48, (8, 8, 10, 255))
        body.alpha_composite(round_corners(ph.convert("RGBA"), 38), (12, 12))
        body = body.rotate(theme["thumb_tilt"], Image.BICUBIC, expand=True)
        paste_shadowed(bg, body, (TW - body.width - 60, 40), 48, 30, 210, 22)
        _brand(bg, 60, 50, logo, brand, theme)
        _headline(bg, 56, 236, theme, 640, acc if not pal_light else (255, 212, 0))
        _pill(bg, 60, 572, hook, ppop if not pal_light else brand_col)

    elif layout == "sticker":
        base_col = acc if lum(acc) > 60 else b1
        bg = background({**theme, "bg": "dots", "light": lum(base_col) > 150, "bg1": base_col,
                         "bg2": mix(base_col, (0, 0, 0), 0.18),
                         "text": (0, 0, 0) if lum(base_col) > 150 else (255, 255, 255)}, (TW, TH))
        card = _card(shot, 720, abs(theme["thumb_tilt"]))
        paste_shadowed(bg, card, (TW - card.width + 120, TH - card.height + 140), 30, 24, 170, 18)
        _brand(bg, 60, 44, logo, brand, theme, height=70, dark_text=lum(base_col) > 150)
        sticker = ((14, 15, 18), (255, 255, 255), 2.5) if lum(base_col) > 110 else \
                  ((255, 255, 255), (14, 15, 18), 2.5)
        hl = ppop if ppop not in ((255, 255, 255), (14, 15, 18)) and abs(lum(ppop) - lum(base_col)) > 60 else \
            (brand_col if lum(brand_col) > 60 else (255, 80, 60))
        _headline(bg, 70, 236, theme, 640, hl, sticker=sticker, size=140)
        _pill(bg, 66, 590, hook, (14, 15, 18) if lum(base_col) > 110 else (255, 255, 255), size=44)

    elif layout == "big_fact":
        # Giant real number (from the review) + arrow to where it appears on the site.
        bg = _solid(pal, theme, rnd.choice(["spotlight", "diagonal"]))
        name, focus, box = _best_focus(data, info)
        src = Image.open(out_dir / name).convert("RGB")
        crop = _cover(src, (760, 560), focus=focus or busiest_point(src, (900, 700)), zoom=1.15)
        card = _card(crop, 640, -abs(theme["thumb_tilt"]) * 0.7, border=10)
        cx, cy = TW - card.width + 70, TH - card.height + 60
        paste_shadowed(bg, card, (cx, cy), 30, 28, 200, 20)
        top = _brand(bg, 56, 40, logo, brand, theme, height=64, dark_text=pal_light) + 6
        big, small = fact
        d = ImageDraw.Draw(bg)
        f = fit(d, big, lambda s: head_font(theme["head_font"], s), 640, 220)
        fcol = acc if abs(lum(acc) - lum(b1)) > 70 else ptxt
        fy = top - int(f.size * 0.12)
        shadow_text(bg, (52, fy), big, f, fcol, stroke=10,
                    stroke_fill=(14, 15, 18) if lum(fcol) > 110 else (255, 255, 255), opacity=150)
        y = fy + int(f.size * 1.02)
        if small:
            sf = fit(d, small, lambda s: font("Black", s), 600, 54)
            shadow_text(bg, (60, y), small, sf, ptxt, stroke=0 if pal_light else 4, stroke_fill=outline,
                        opacity=0 if pal_light else 140)
            y += int(sf.size * 1.25)
        _arrow(bg, (60 + min(560, int(d.textlength(big, font=f))) + 10, fy + f.size * 0.45),
               (cx + 120, cy + 110), ppop if ppop != ptxt else (255, 72, 66),
               outline=(14, 15, 18) if lum(ppop) > 128 else (255, 255, 255))
        band_h = 118
        band = Image.new("RGBA", (TW, band_h), (14, 15, 18, 255))
        bd = ImageDraw.Draw(band)
        bf = fit(bd, "WORTH USING IT?", lambda s: head_font(theme["head_font"], s), 760, 92)
        bcol = acc if lum(acc) > 110 else (255, 212, 0)
        wpart = bd.textlength("WORTH USING ", font=bf)
        bd.text((52, band_h / 2), "WORTH USING ", font=bf, fill=(255, 255, 255), anchor="lm")
        bd.text((52 + wpart, band_h / 2), "IT?", font=bf, fill=bcol, anchor="lm")
        band = band.rotate(1.2, Image.BICUBIC, expand=True)
        bg.alpha_composite(band, (-10, TH - band.height - 18))

    elif layout == "verdict":
        # Score badge as the hook, brand tile as the subject.
        bg = _solid(pal, theme, rnd.choice(["spotlight", "mesh"]))
        vcol, vicon = _verdict_style(data)
        tile = _logo_tile(logo, brand, theme, 250, tilt=-4)
        paste_shadowed(bg, tile, (70, 70), 50, 26, 170, 18)
        d = ImageDraw.Draw(bg)
        nf = fit(d, brand.upper(), lambda s: font("Black", s), 320, 40)
        d.text((70 + tile.width / 2, 70 + tile.height + 26), brand.upper(), font=nf, fill=ptxt, anchor="ma")
        cxr, cyr, r = 960, 330, 215
        ring = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rd.ellipse([cxr - r - 18, cyr - r - 18, cxr + r + 18, cyr + r + 18], fill=(14, 15, 18, 235))
        rd.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=(60, 62, 70, 255), width=30)
        rd.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90, -90 + 360 * _score(data) / 10, fill=(*vcol, 255), width=30)
        paste_shadowed(bg, ring.crop((cxr - r - 18, cyr - r - 18, cxr + r + 19, cyr + r + 19)),
                       (cxr - r - 18, cyr - r - 18), r + 18, 30, 200, 18)
        hf = lambda s: head_font(theme["head_font"], s)
        d.text((cxr, cyr - 18), f"{_score(data):.1f}", font=hf(170), fill=(255, 255, 255), anchor="mm")
        d.text((cxr, cyr + 104), "/ 10", font=font("Black", 40), fill=(170, 174, 184), anchor="mm")
        b = icons.badge(vicon, 120, vcol, (255, 255, 255))
        if b is not None:
            paste_shadowed(bg, b, (cxr + r - 70, cyr - r - 20), 60, 16, 170, 8)
        _headline(bg, 60, 420, theme, 700, acc if not pal_light else pacc, text_col=ptxt,
                  stroke=0 if pal_light else 7, size=118, lines=[["WORTH", "USING", "IT?"]], outline=outline)
        _pill(bg, 64, 580, hook, ppop if ppop not in (ptxt,) else brand_col, size=44, tilt=-2)

    elif layout == "lens":
        # Real screenshot with a magnifying glass on the key number.
        name, focus, box = _best_focus(data, info)
        src = Image.open(out_dir / name).convert("RGB")
        fpt = focus or busiest_point(src, (500, 400))
        bgimg = _cover(src, (TW, TH), focus=fpt, zoom=1.05, anchor=(0.62, 0.5))
        bg = ImageEnhance.Brightness(bgimg.filter(ImageFilter.GaussianBlur(7))).enhance(0.5).convert("RGBA")
        _left_fade(bg, strength=255, reach=0.72, color=mix(b1, (0, 0, 0), 0.55) if not pal_light else (12, 12, 16))
        _left_fade(bg, strength=200, reach=0.5, color=mix(b1, (0, 0, 0), 0.55) if not pal_light else (12, 12, 16))
        lr = 210
        zoom_w = (box["w"] + 90) if box else 300            # source pixels shown inside the lens
        base = max(lr * 2 / src.width, lr * 2 / src.height)
        zoom = _cover(src, (lr * 2, lr * 2), focus=fpt, zoom=max(1.0, (lr * 2 / max(zoom_w, 1)) / base))
        mask = Image.new("L", (lr * 2, lr * 2), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, lr * 2 - 1, lr * 2 - 1], fill=255)
        lens = Image.new("RGBA", (lr * 2 + 40, lr * 2 + 40), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lens)
        ld.ellipse([0, 0, lr * 2 + 39, lr * 2 + 39], fill=(*acc, 255))
        inner = zoom.convert("RGBA")
        inner.putalpha(mask)
        lens.alpha_composite(inner, (20, 20))
        lx, ly = 760, 120
        handle = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        ImageDraw.Draw(handle).line([(lx + lr * 2 - 10, ly + lr * 2 - 10), (lx + lr * 2 + 110, ly + lr * 2 + 110)],
                                    fill=(*acc, 255), width=46)
        bg.alpha_composite(handle)
        paste_shadowed(bg, lens, (lx, ly), lr + 20, 30, 210, 18)
        _brand(bg, 56, 46, logo, brand, theme, height=66)
        _headline(bg, 52, 220, theme, 640, acc, size=140)
        if fact:
            _pill(bg, 58, 560, f"{fact[0]} {fact[1]}".strip()[:22], ppop if ppop != ptxt else brand_col, size=46, tilt=2)
        else:
            _pill(bg, 58, 560, hook, ppop if ppop != ptxt else brand_col, size=46, tilt=2)

    elif layout == "yes_no":
        # Curiosity split: YES or NO? with the brand in the middle.
        bg = Image.new("RGBA", (TW, TH))
        left = background({**theme, "bg": "spotlight", "bg1": (20, 120, 60), "bg2": (6, 60, 30),
                           "accent": (60, 230, 120), "light": False}, (TW, TH))
        right = background({**theme, "bg": "spotlight", "bg1": (150, 20, 28), "bg2": (70, 6, 12),
                            "accent": (255, 80, 80), "light": False}, (TW, TH))
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (TW // 2 + 70, 0), (TW // 2 - 70, TH), (0, TH)], fill=255)
        bg = Image.composite(left, right, mask)
        d = ImageDraw.Draw(bg)
        d.line([(TW // 2 + 70, 0), (TW // 2 - 70, TH)], fill=(255, 255, 255), width=10)
        hf = lambda s: head_font(theme["head_font"], s)
        for txt, icon, x, col in (("YES", "check", 230, (60, 230, 120)), ("NO", "close", TW - 230, (255, 90, 90))):
            b = icons.badge(icon, 150, (255, 255, 255), col)
            if b is not None:
                paste_shadowed(bg, b, (x - 75, 300), 75, 20, 170, 10)
            shadow_text(bg, (x, 470), txt, hf(150), (255, 255, 255), stroke=8, anchor="ma", opacity=170)
        tile = _logo_tile(logo, brand, theme, 230, tilt=3)
        paste_shadowed(bg, tile, (TW // 2 - tile.width // 2, 250), 46, 30, 210, 22)
        top = Image.new("RGBA", (TW, 150), (14, 15, 18, 235))
        bg.alpha_composite(top, (0, 0))
        tf = fit(d, "WORTH USING IT?", hf, 1100, 120)
        tw = d.textlength("WORTH USING ", font=tf)
        full = d.textlength("WORTH USING IT?", font=tf)
        x0 = TW / 2 - full / 2
        d.text((x0, 75), "WORTH USING ", font=tf, fill=(255, 255, 255), anchor="lm")
        d.text((x0 + tw, 75), "IT?", font=tf, fill=(255, 212, 0), anchor="lm")
        nf = fit(d, f"{brand.upper()} REVIEW", lambda s: font("Black", s), 420, 34)
        name = f"{brand.upper()} REVIEW"
        nw = d.textlength(name, font=nf)
        d.rounded_rectangle([TW / 2 - nw / 2 - 22, 548, TW / 2 + nw / 2 + 22, 548 + nf.size + 26], 14, fill=(14, 15, 18))
        d.text((TW / 2, 548 + 13), name, font=nf, fill=(255, 255, 255), anchor="ma")

    else:  # poster: bold brand-first poster
        bg = _solid(pal, theme, rnd.choice(["diagonal", "dots", "aurora"]))
        tile = _logo_tile(logo, brand, theme, 330, tilt=-5)
        paste_shadowed(bg, tile, (60, (TH - tile.height) // 2 - 20), 66, 34, 200, 24)
        d = ImageDraw.Draw(bg)
        nf = fit(d, brand.upper(), lambda s: font("Black", s), 360, 44)
        d.text((60 + tile.width / 2, (TH + tile.height) // 2 + 6), brand.upper(), font=nf, fill=ptxt, anchor="ma")
        _headline(bg, TW - 60, 70, theme, 720, acc if not pal_light else pacc, text_col=ptxt, align="right",
                  stroke=0 if pal_light else 8, size=170, lines=[["WORTH"], ["USING"], ["IT?"]], outline=outline)
        ic = icons.pick({"callout": (fact or ("", ""))[1], "caption": hook, "text": hook}) or "help"
        b = icons.badge(ic, 130, ppop if ppop != ptxt else brand_col, readable_on(ppop if ppop != ptxt else brand_col))
        if b is not None:
            b = b.rotate(12, Image.BICUBIC, expand=True)
            paste_shadowed(bg, b, (60 + tile.width - 70, (TH - tile.height) // 2 - 70), 65, 18, 170, 10)
        _pill(bg, TW - 60, 600, hook, (14, 15, 18) if not pal_light else (255, 255, 255), align="right", size=44, tilt=-2)

    overlay = config.ASSETS_DIR / "thumbnail_overlay.png"
    if overlay.exists():
        bg.alpha_composite(Image.open(overlay).convert("RGBA").resize((TW, TH)))
    original["thumb_palette"] = pal_name          # remembered so the next videos look different
    original["thumb"] = layout
    out = out_dir / "thumbnail.jpg"
    bg.convert("RGB").save(out, quality=92)
    if out.stat().st_size > 2_000_000:
        bg.convert("RGB").save(out, quality=80)
    return out


def PALETTES_DARK(pal):
    """A dark version of a light palette, for layouts that need a dark stage."""
    return {**pal, "bg1": mix(pal["bg1"], (0, 0, 0), 0.82), "bg2": mix(pal["accent"], (0, 0, 0), 0.6),
            "text": (255, 255, 255)}
