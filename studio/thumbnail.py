"""Step 5: clickable 1280x720 thumbnail — logo, brand name and "WORTH USING IT?" — in one of
several layouts chosen by the video's theme (tilted card, split, centered stack, phone, sticker).

Optional: assets/thumbnail_overlay.png (1280x720, transparent) is drawn on top of every thumbnail.
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from . import config
from .visuals import (background, fit, font, head_font, load_logo, logo_chip, lum, mix,
                      paste_shadowed, readable_on, rounded, round_corners, shadow_text)

TW, TH = 1280, 720


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


def _left_fade(bg, strength=235, reach=0.75):
    grad = Image.new("L", (TW, 1))
    grad.putdata([int(strength * max(0, 1 - x / (TW * reach))) for x in range(TW)])
    shade = Image.new("RGBA", (TW, TH), (8, 9, 12, 255))
    shade.putalpha(grad.resize((TW, TH)))
    bg.alpha_composite(shade)


def _card(shot, width, tilt, border=8):
    card = shot.resize((width, int(width * shot.height / shot.width)), Image.LANCZOS)
    framed = rounded((card.width + border * 2, card.height + border * 2), 22, (255, 255, 255, 255))
    framed.alpha_composite(round_corners(card.convert("RGBA"), 16), (border, border))
    return framed.rotate(tilt, resample=Image.BICUBIC, expand=True)


def _headline(canvas, x, y, theme, max_w, accent, align="left", text_col=(255, 255, 255),
              stroke=7, size=150, sticker=None):
    """'WORTH / USING IT?' with one accent word. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    rnd = random.Random(theme["seed"] + "hl")
    hf = lambda s: head_font(theme["head_font"], s)
    f = fit(d, "USING IT?", hf, max_w, size)
    accent_word = rnd.choice(["IT?", "IT?", "WORTH"])
    lines = [["WORTH"], ["USING", "IT?"]]
    lh = int(f.size * 1.02)
    for li, words in enumerate(lines):
        full = " ".join(words)
        tw = d.textlength(full, font=f)
        lx = x - tw / 2 if align == "center" else x
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
            shadow_text(canvas, (cx, ly), w, f, col, stroke=0 if sticker else stroke,
                        opacity=0 if sticker else 190)
            cx += d.textlength(w + " ", font=f)
    return y + lh * 2


def _pill(canvas, x, y, text, color, align="left", size=50):
    d = ImageDraw.Draw(canvas)
    text = text.upper()
    f = fit(d, text, lambda s: font("Black", s), 560, size)
    tw = int(d.textlength(text, font=f))
    pill = rounded((tw + 56, int(f.size * 1.6)), 18, (*color, 255))
    px = x - pill.width // 2 if align == "center" else x
    paste_shadowed(canvas, pill, (px, y), 18, 14, 170, 8)
    ImageDraw.Draw(canvas).text((px + 28, y + pill.height / 2), text, font=f, fill=readable_on(color),
                                anchor="lm")


def _brand(canvas, x, y, logo, brand, theme, height=78, align="left", label=True, dark_text=False):
    """Logo chip + brand name label. Returns bottom y."""
    d = ImageDraw.Draw(canvas)
    bottom = y
    if logo is not None:
        chip = logo_chip(logo, height, radius=24)
        cx = x - chip.width // 2 if align == "center" else x
        paste_shadowed(canvas, chip, (cx, y), 24, 16, 170, 8)
        bottom = y + chip.height
        if label:
            name = f"{brand.upper()} REVIEW"
            f = font("Black", 26)
            lx = x if align == "left" else x
            d.text((lx, bottom + 14), name, font=f, fill=(20, 20, 24) if dark_text else (235, 238, 244),
                   anchor="ma" if align == "center" else "la")
            bottom += 44
    else:
        f = fit(d, brand.upper(), lambda s: head_font(theme["head_font"], s), 600, 92)
        shadow_text(canvas, (x, y), brand.upper(), f, (20, 20, 24) if dark_text else (255, 255, 255),
                    stroke=0 if dark_text else 5, opacity=0 if dark_text else 180,
                    anchor="ma" if align == "center" else "la")
        bottom = y + int(f.size * 1.1)
    return bottom


def make_thumbnail(data, info, out_dir: Path, theme: dict) -> Path:
    first = out_dir / info["screenshots"][0]["file"]
    shot = Image.open(first).convert("RGB")
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    acc = theme["thumb_accent"]
    brand_col = theme["accent"]
    hook = data.get("thumbnail_subtitle") or "Honest review"
    layout = theme["thumb"]
    has_mobile = (out_dir / "mobile.png").exists()
    if layout == "phone" and not has_mobile:
        layout = "tilt_right"

    if layout == "tilt_right":
        bg = _blur_bg(shot, tint=brand_col)
        _left_fade(bg)
        card = _card(shot, 760, theme["thumb_tilt"] if theme["thumb_tilt"] < 0 else -theme["thumb_tilt"])
        paste_shadowed(bg, card, (TW - card.width + 150, 150), 30, 26, 200, 20)
        _brand(bg, 60, 50, logo, brand, theme)
        _headline(bg, 56, 236, theme, 690, acc)
        _pill(bg, 60, 572, hook, brand_col if lum(brand_col) > 60 else acc)

    elif layout == "split":
        dark_panel = theme["mode"] != "light"
        panel_col = theme["bg1"] if dark_panel else (250, 250, 248)
        bg = _cover(shot, (TW, TH), focus=busiest_point(shot, (1000, 900)), zoom=1.2,
                    anchor=(0.73, 0.5)).convert("RGBA")
        mask = Image.new("L", (TW, TH), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (720, 0), (600, TH), (0, TH)], fill=255)
        panel = background({**theme, "bg": "gradient", "bg1": panel_col,
                            "bg2": mix(panel_col, brand_col, 0.25)}, (TW, TH))
        bg = Image.composite(panel, bg, mask)
        ImageDraw.Draw(bg).line([(720, 0), (600, TH)], fill=acc, width=10)
        txt = (255, 255, 255) if dark_panel else (18, 20, 26)
        _brand(bg, 56, 46, logo, brand, theme, height=70, dark_text=not dark_panel)
        _headline(bg, 52, 232, theme, 560, acc if dark_panel else mix(brand_col, (0, 0, 0), 0.2),
                  text_col=txt, stroke=0 if not dark_panel else 6)
        _pill(bg, 56, 580, hook, brand_col if lum(brand_col) > 60 else acc, size=44)

    elif layout == "stack":
        bg = _blur_bg(shot, darken=0.33, tint=brand_col)
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
        bg = background({**theme, "bg": "mesh", "bg1": mix(theme["bg1"], (0, 0, 0), 0.3)
                         if not theme["light"] else (16, 18, 26), "bg2": mix(brand_col, (0, 0, 0), 0.6)},
                        (TW, TH))
        ph = Image.open(out_dir / "mobile.png").convert("RGB")
        ph = ph.resize((int(ph.width * 640 / ph.height), 640), Image.LANCZOS)
        body = rounded((ph.width + 24, ph.height + 24), 48, (8, 8, 10, 255))
        body.alpha_composite(round_corners(ph.convert("RGBA"), 38), (12, 12))
        body = body.rotate(theme["thumb_tilt"], Image.BICUBIC, expand=True)
        paste_shadowed(bg, body, (TW - body.width - 60, 40), 48, 30, 210, 22)
        _brand(bg, 60, 50, logo, brand, theme)
        _headline(bg, 56, 236, theme, 640, acc)
        _pill(bg, 60, 572, hook, brand_col if lum(brand_col) > 60 else acc)

    else:  # sticker
        base_col = acc
        bg = background({**theme, "bg": "dots", "light": lum(base_col) > 150, "bg1": base_col,
                         "bg2": mix(base_col, (0, 0, 0), 0.18),
                         "text": (0, 0, 0) if lum(base_col) > 150 else (255, 255, 255)}, (TW, TH))
        card = _card(shot, 720, abs(theme["thumb_tilt"]))
        paste_shadowed(bg, card, (TW - card.width + 120, TH - card.height + 140), 30, 24, 170, 18)
        _brand(bg, 60, 44, logo, brand, theme, height=70, dark_text=lum(base_col) > 150)
        sticker = ((14, 15, 18), (255, 255, 255), 2.5) if lum(base_col) > 110 else \
                  ((255, 255, 255), (14, 15, 18), 2.5)
        _headline(bg, 70, 236, theme, 640, brand_col if lum(brand_col) > 60 else (255, 80, 60),
                  sticker=sticker, size=140)
        _pill(bg, 66, 590, hook, (14, 15, 18) if lum(base_col) > 110 else (255, 255, 255), size=44)

    overlay = config.ASSETS_DIR / "thumbnail_overlay.png"
    if overlay.exists():
        bg.alpha_composite(Image.open(overlay).convert("RGBA").resize((TW, TH)))
    out = out_dir / "thumbnail.jpg"
    bg.convert("RGB").save(out, quality=92)
    if out.stat().st_size > 2_000_000:
        bg.convert("RGB").save(out, quality=80)
    return out
