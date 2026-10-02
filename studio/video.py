"""Step 4: render the review video (1080p) with the per-video theme.

Each segment = website screenshot moving under a "camera" (smart zoom to the thing being talked
about, with a highlight), framed by a themed foreground (browser frame, logo). On top of that, the
segment caption slides in (style per video), and a "callout" sticker with an icon pops in for the
key fact. Segments are joined with themed transitions; an animated intro card, progress bar and an
animated verdict end card are added. Audio = narration + original background music (ducked under
the voice) + sound effects timed to the animations.
"""
import os
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import config, icons
from .tts import duration
from .visuals import (background, fit, font, head_font, head_upper, load_logo, logo_chip,
                      lum, mix, paste_shadowed, readable_on, round_corners, rounded, shadow_text, wrap)

W, H, FPS = config.VIDEO_W, config.VIDEO_H, config.FPS
PAD = 0.35            # breath after each segment
OUTRO = 8.0           # end card (room for YouTube end-screen elements)
INTRO = 2.6           # intro card overlaid on the first seconds
CAP_D = 0.45          # caption entrance animation length
CALLOUT_AT = 1.1      # seconds into a segment (after the transition) when the callout pops in
UP = 1 if config.FAST_RENDER else 2   # zoompan supersampling (smoother motion)
X264 = ["-c:v", "libx264", "-preset", "ultrafast" if config.FAST_RENDER else "veryfast",
        "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])


def _hex(c):
    return "0x%02x%02x%02x" % tuple(c[:3])


def _cap(theme, text):
    return text.upper() if head_upper(theme["head_font"]) else text


def ease_out(p):
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def ease_back(p, s=1.7):
    p = min(1.0, max(0.0, p))
    return 1 + (s + 1) * (p - 1) ** 3 + s * (p - 1) ** 2


def _fade(im, k):
    """Multiply an RGBA image's alpha by k (0..1)."""
    if k >= 0.999:
        return im
    out = im.copy()
    out.putalpha(im.getchannel("A").point(lambda v: int(v * max(0.0, k))))
    return out


def _crop(layer):
    box = layer.getchannel("A").getbbox()
    if not box:
        return None, (0, 0)
    return layer.crop(box), (box[0], box[1])


# ------------------------------------------------------------------ foreground layers
def _frame_bar_height(theme):
    if theme["layout"] == "cinema":
        return 0
    return {"mac_dark": 52, "mac_light": 52, "minimal": 36, "floating": 0}[theme["frame"]]


def _draw_frame(fg, theme, domain):
    """Draws shadow + browser chrome around the content hole into the background canvas."""
    cx, cy, cw, ch, r = theme["cx"], theme["cy"], theme["cw"], theme["ch"], theme["radius"]
    bar = _frame_bar_height(theme)
    sh_op = 70 if theme["light"] else 170
    from .visuals import shadow
    s, pad = shadow((cw, ch + bar), r, blur=30, opacity=sh_op)
    fg.alpha_composite(s, (cx - pad, cy - bar - pad + 16))
    d = ImageDraw.Draw(fg)
    if bar:
        light_chrome = theme["frame"] == "mac_light" or (theme["frame"] == "minimal" and theme["light"])
        col = (236, 238, 242) if light_chrome else theme["panel"]
        tcol = (60, 64, 72) if light_chrome else theme["chrome_text"]
        top = round_corners(Image.new("RGBA", (cw, bar + r), (*col, 255)), r, top_only=True)
        fg.alpha_composite(top, (cx, cy - bar))
        if theme["frame"] == "minimal":
            d.text((cx + cw / 2, cy - bar / 2), domain, font=font("SemiBold", 18), fill=tcol, anchor="mm")
        else:
            for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
                d.ellipse([cx + 22 + i * 26, cy - bar / 2 - 7, cx + 36 + i * 26, cy - bar / 2 + 7], fill=c)
            pill = mix(col, (0, 0, 0), 0.25) if not light_chrome else (255, 255, 255)
            d.rounded_rectangle([cx + 120, cy - bar + 10, cx + 120 + min(640, cw // 2), cy - 10], 16, fill=pill)
            f = font("Medium", 21)
            d.text((cx + 146, cy - bar / 2), "https://", font=f, fill=mix(tcol, col, 0.45), anchor="lm")
            d.text((cx + 146 + d.textlength("https://", font=f), cy - bar / 2), domain, font=f,
                   fill=tcol, anchor="lm")


def _cut_hole(fg, theme):
    cx, cy, cw, ch, r = theme["cx"], theme["cy"], theme["cw"], theme["ch"], theme["radius"]
    bar = _frame_bar_height(theme)
    a = fg.getchannel("A")
    hole = Image.new("L", fg.size, 0)
    hd = ImageDraw.Draw(hole)
    if theme["layout"] == "cinema":
        hd.rectangle([0, 0, W, H], fill=255)
    else:
        hd.rounded_rectangle([cx, cy - (r if bar else 0), cx + cw - 1, cy + ch - 1], r, fill=255)
        if bar:
            hd.rectangle([cx, cy - r, cx + cw - 1, cy], fill=0)    # bar area stays opaque
            hd.rectangle([cx, cy, cx + cw - 1, cy + r], fill=255)
    a = Image.composite(Image.new("L", fg.size, 0), a, hole)
    fg.putalpha(a)
    return fg


def _caption(fg, theme, x, y, max_w, text, size, idx, total, light_text=None, max_lines=1, icon=None):
    """Draw the segment caption in the theme's caption style (optionally with an icon badge).
    Returns bottom y."""
    d = ImageDraw.Draw(fg)
    acc, acc_t = theme["accent"], theme["accent_text"]
    tcol = light_text or theme["text"]
    text = _cap(theme, text)
    hf = lambda s: head_font(theme["head_font"], s)
    style = theme["caption"]
    badge = None
    if style == "glass":
        return _glass_caption(fg, theme, x, y, max_w, text, size, light_text, max_lines, icon)
    if icon and style != "pill":
        bs = int(size * 1.05)
        badge = icons.badge(icon, bs, acc, readable_on(acc), "circle" if theme["radius"] > 16 else "square")
        if badge is not None:
            max_w -= bs + 22
    if max_lines == 1:
        f = fit(d, text, hf, max_w - (60 if style in ("bar", "pill") else 0) - (70 if icon and style == "pill" else 0), size)
        lines = [text]
    else:
        f = hf(size)
        lines = wrap(d, text, f, max_w)
        while len(lines) > max_lines and size > 30:
            size -= 4
            f = hf(size)
            lines = wrap(d, text, f, max_w)
    lh = int(f.size * 1.12)
    if style == "tag":
        d.text((x, y), f"{idx:02d} / {total:02d}", font=font("Bold", max(18, size * 0.42)), fill=acc_t)
        y += int(size * 0.62)
    if badge is not None:
        fg.alpha_composite(badge, (int(x), int(y + max(0, (lh - badge.height) // 2))))
        x += badge.width + 22
    if style == "pill":
        g = icons.glyph(icon, int(f.size * 0.9), readable_on(acc)) if icon else None
        gw = g.width + 18 if g is not None else 0
        widest = max(d.textlength(l, font=f) for l in lines)
        box = rounded((widest + 56 + gw, lh * len(lines) + 30), 18, (*acc, 255))
        fg.alpha_composite(box, (int(x), int(y)))
        if g is not None:
            fg.alpha_composite(g, (int(x + 26), int(y + 15 + (lh - g.height) // 2)))
        for i, l in enumerate(lines):
            d.text((x + 28 + gw, y + 15 + i * lh), l, font=f, fill=readable_on(acc))
        return y + lh * len(lines) + 30
    if style == "bar":
        d.rounded_rectangle([x, y + 4, x + 10, y + lh * len(lines) - 6], 5, fill=acc)
        x += 30
    for i, l in enumerate(lines):
        ly = y + i * lh
        if style == "underline":
            tw = d.textlength(l, font=f)
            d.rounded_rectangle([x, ly + lh * 0.98, x + tw, ly + lh * 0.98 + max(6, f.size // 9)],
                                4, fill=(*acc, 255))
        d.text((x, ly), l, font=f, fill=tcol)
    return y + lh * len(lines)


def _glass_caption(fg, theme, x, y, max_w, text, size, light_text, max_lines, icon):
    """Frosted lower-third: translucent rounded panel, accent stripe, optional icon inside."""
    d = ImageDraw.Draw(fg)
    acc = theme["accent"]
    hf = lambda s: head_font(theme["head_font"], s)
    dark = lum(theme["bg1"]) < 140 or light_text is not None
    g = icons.glyph(icon, int(size * 0.82), acc if lum(acc) > 80 or not dark else (255, 255, 255)) if icon else None
    gw = g.width + 20 if g is not None else 0
    f = fit(d, text, hf, max_w - 90 - gw, size) if max_lines == 1 else hf(size)
    lines = [text] if max_lines == 1 else wrap(d, text, f, max_w - 90 - gw)[:max_lines]
    lh = int(f.size * 1.12)
    widest = max(d.textlength(l, font=f) for l in lines)
    panel = rounded((widest + 70 + gw, lh * len(lines) + 34), 22, (12, 14, 20, 150) if dark else (255, 255, 255, 200))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([0, 0, panel.width - 1, panel.height - 1], 22,
                         outline=(255, 255, 255, 46) if dark else (0, 0, 0, 22), width=2)
    pd.rounded_rectangle([18, 18, 24, panel.height - 18], 3, fill=(*acc, 255))
    fg.alpha_composite(panel, (int(x), int(y)))
    if g is not None:
        fg.alpha_composite(g, (int(x + 40), int(y + 17 + (lh - g.height) // 2)))
    for i, l in enumerate(lines):
        d.text((x + 42 + gw, y + 17 + i * lh), l, font=f, fill=(255, 255, 255) if dark else (16, 18, 24))
    return y + lh * len(lines) + 34


def build_foreground(theme, info, logo, brand):
    """Static parts of every website segment: background, browser frame, logo. Built once."""
    base = background(theme, (W, H))
    cx, cy, cw, ch = theme["cx"], theme["cy"], theme["cw"], theme["ch"]
    lay = theme["layout"]
    if lay != "cinema":
        _draw_frame(base, theme, info["domain"])
    fg = _cut_hole(base, theme)
    d = ImageDraw.Draw(fg)
    if lay == "full":
        if logo is not None:
            chip = logo_chip(logo, 32)
            fg.alpha_composite(chip, (cx + cw - chip.width, cy + ch + 34 + (12 if theme["caption"] == "tag" else 0)))
    elif lay == "side":
        if logo is not None:
            chip = logo_chip(logo, 40)
            fg.alpha_composite(chip, (80, cy + ch - chip.height))
        else:
            d.text((80, cy + ch), brand, font=font("Bold", 34), fill=theme["muted"], anchor="ls")
    elif lay == "stage":
        if logo is not None:
            chip = logo_chip(logo, 38)
            fg.alpha_composite(chip, (cx + cw - chip.width, 78))
    elif lay == "spotlight":
        if logo is not None:
            chip = logo_chip(logo, 30)
            fg.alpha_composite(chip, (cx + cw - chip.width, cy + ch + 40))
    else:  # cinema: dark gradient at the bottom so the caption stays readable
        grad = Image.new("L", (1, 256))
        grad.putdata([int(min(225, max(0, (i - 60) * 1.4))) for i in range(256)])
        shade = Image.new("RGBA", (W, 460), (6, 8, 12, 255))
        shade.putalpha(grad.resize((W, 460)))
        fg.alpha_composite(shade, (0, H - 460))
        if logo is not None:
            chip = logo_chip(logo, 28)
            paste_shadowed(fg, chip, (W - chip.width - 56, H - 150 + (40 - chip.height) // 2),
                           chip.height // 2, 16, 140, 6)
    return fg


def caption_layer(theme, seg, idx, total, icon=None):
    """The animated part: caption (+ index number / icon). Returns (cropped RGBA, (x, y))."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy, ch = theme["cx"], theme["cy"], theme["ch"]
    cap = seg["caption"]
    lay = theme["layout"]
    if lay == "full":
        _caption(layer, theme, cx, cy + ch + 26, 1180, cap, 46, idx, total, icon=icon)
    elif lay == "side":
        if theme["caption"] == "tag":
            _caption(layer, theme, 80, 300, 470, cap, 64, idx, total, max_lines=4, icon=icon)
        else:
            d.text((80, 200), f"{idx:02d}", font=head_font(theme["head_font"], 120), fill=theme["accent_text"])
            _caption(layer, theme, 80, 360, 470, cap, 62, idx, total, max_lines=3, icon=icon)
    elif lay == "stage":
        _caption(layer, theme, cx, 70, 1080, cap, 66, idx, total, icon=icon)
    elif lay == "spotlight":
        _caption(layer, theme, cx, cy + ch + 26, 1150, cap, 46, idx, total, icon=icon)
    else:  # cinema: caption on a dark glass panel over the full-screen website
        glass = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _caption(glass, {**theme, "text": (255, 255, 255),
                         "accent_text": theme["accent"] if lum(theme["accent"]) > 110 else (255, 255, 255)},
                 110, H - 190, 1300, cap, 60, idx, total, light_text=(255, 255, 255), icon=icon)
        box = glass.getchannel("A").getbbox()
        if box and theme["caption"] != "pill":
            panel = rounded((box[2] - box[0] + 64, box[3] - box[1] + 48), 22, (8, 10, 14, 175))
            layer.alpha_composite(panel, (box[0] - 32, box[1] - 24))
        layer.alpha_composite(glass)
    return _crop(layer)


def callout_card(theme, text, icon):
    """Sticker for the segment's key fact, e.g. "$0 monthly fee" with a money icon."""
    style = theme["callout"]
    acc = theme["accent"]
    text = text.strip()
    f = font("ExtraBold", 40) if style != "sticker" else head_font(theme["head_font"], 46)
    if style == "sticker":
        text = _cap(theme, text)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = min(int(tmp.textlength(text, font=f)), 640)
    f = fit(tmp, text, lambda s: font("ExtraBold", s) if style != "sticker" else head_font(theme["head_font"], s),
            640, f.size)
    tw = int(tmp.textlength(text, font=f))
    h = 104
    if style == "pill":
        bg, fgc, ibg, ifg = acc, readable_on(acc), None, readable_on(acc)
    elif style == "sticker":
        bg, fgc, ibg, ifg = acc, readable_on(acc), readable_on(acc), acc
    elif style == "glass":
        bg, fgc, ibg, ifg = (10, 12, 16), (255, 255, 255), None, theme["accent"] if lum(acc) > 90 else (255, 255, 255)
    else:  # card
        bg = (255, 255, 255) if not theme["light"] else (22, 24, 30)
        fgc = (18, 20, 26) if not theme["light"] else (255, 255, 255)
        ibg, ifg = acc, readable_on(acc)
    icon_im = None
    if icon:
        if ibg is not None:
            icon_im = icons.badge(icon, 68, ibg, ifg, "circle")
        else:
            icon_im = icons.glyph(icon, 48, ifg)
    iw = (icon_im.width + 20) if icon_im is not None else 0
    w = tw + iw + 64
    m = 60                                             # margin: room for the soft shadow
    radius = h // 2 if style in ("pill", "sticker") else 22
    card = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    from .visuals import shadow
    sh, sp = shadow((w, h), radius, blur=16, opacity=110 if not theme["light"] else 55)
    card.alpha_composite(sh, (m - sp, m - sp + 10))
    if style == "sticker":
        card.alpha_composite(rounded((w + 12, h + 12), radius + 6, (255, 255, 255, 255)), (m - 6, m - 6))
    card.alpha_composite(rounded((w, h), radius, (*bg, 215 if style == "glass" else 255)), (m, m))
    d = ImageDraw.Draw(card)
    if style == "glass":
        d.rounded_rectangle([m, m, m + 8, m + h], 4, fill=(*acc, 255))
    x = m + 32
    if icon_im is not None:
        card.alpha_composite(icon_im, (x - 6, m + (h - icon_im.height) // 2))
        x += iw
    d.text((x, m + h / 2), text, font=f, fill=fgc, anchor="lm")
    if style == "sticker":
        card = card.rotate(theme["thumb_tilt"] * 0.6, Image.BICUBIC, expand=True)
    out, _ = _crop(card)
    return out


def callout_position(theme, card):
    cx, cy, cw = theme["cx"], theme["cy"], theme["cw"]
    lay = theme["layout"]
    if lay == "side":
        return 60, 600
    if lay == "cinema":
        return W - card.width - 40, 40
    bar = _frame_bar_height(theme)
    return cx + cw - card.width + 24, cy - bar - card.height // 2 + 6     # sits on the top edge


def callout_frames(card, start_frame, work, tag):
    """Pop-in animation as an image sequence: transparent until start_frame, then scales in."""
    pad = int(max(card.width, card.height) * 0.12)
    cw, chh = card.width + pad * 2, card.height + pad * 2
    blank = work / f"co_{tag}_blank.png"
    Image.new("RGBA", (cw, chh), (0, 0, 0, 0)).save(blank)
    pattern = work / f"co_{tag}_%04d.png"
    k = 0
    for k in range(start_frame):
        dst = Path(str(pattern) % k)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(blank.name, dst)
    n = 12
    for j in range(n):
        p = (j + 1) / n
        s = 0.55 + 0.45 * ease_back(p)
        im = card.resize((max(1, int(card.width * s)), max(1, int(card.height * s))), Image.BICUBIC)
        im = _fade(im, min(1, p * 2.2))
        frame = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        frame.alpha_composite(im, ((cw - im.width) // 2, (chh - im.height) // 2))
        frame.save(str(pattern) % (start_frame + j), compress_level=1)
    return pattern, pad


def mobile_frame(theme, shot, seg, idx, total, logo):
    frame = background(theme, (W, H))
    phone_h = 900
    sc = Image.open(shot).convert("RGB")
    sc = sc.resize((int(sc.width * phone_h / sc.height), phone_h), Image.LANCZOS)
    bez = 16
    body = rounded((sc.width + bez * 2, phone_h + bez * 2), 64, (8, 8, 10, 255))
    body.alpha_composite(round_corners(sc, 50), (bez, bez))
    right = theme["layout"] != "side"
    px = 1240 if right else 300
    py = (H - body.height) // 2
    paste_shadowed(frame, body, (px, py), 64, 34, 70 if theme["light"] else 190, 18)
    tx = 180 if right else 900
    d = ImageDraw.Draw(frame)
    d.text((tx, 300), "ON YOUR PHONE", font=font("Bold", 32), fill=theme["accent_text"])
    _caption(frame, theme, tx, 360, 860, seg["caption"], 76, idx, total, max_lines=3)
    if logo is not None:
        frame.alpha_composite(logo_chip(logo, 44), (tx, 760))
    return frame


# ------------------------------------------------------------------ highlight + camera
def highlight(shot_path, box, theme, out_path):
    im = Image.open(shot_path).convert("RGBA")
    if box:
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        p = 14
        rect = [x - p, y - p, x + w + p, y + h + p]
        acc = theme["accent"]
        while lum(acc) > 150:                       # pages are mostly white: keep the marker visible
            acc = mix(acc, (0, 0, 0), 0.15)
        style = theme["highlight"]
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if style == "spotlight":                    # soft accent glow around the key text (no dimming)
            glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle([rect[0] - 6, rect[1] - 6, rect[2] + 6, rect[3] + 6], 20,
                                                   outline=(*acc, 150), width=14)
            im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
            d.rounded_rectangle(rect, 14, outline=(*acc, 255), width=4)
        elif style == "underline":
            d.rounded_rectangle([x - 6, y + h - 2, x + w + 6, y + h + 9], 5, fill=(*acc, 235))
        else:
            d.rounded_rectangle(rect, 14, fill=(*acc, 34), outline=(*acc, 255), width=6)
        im.alpha_composite(layer)
    im.convert("RGB").save(out_path)


def camera(kind, frames, theme, box=None, speed=0.45):
    """zoompan z/x/y expressions. Coordinates are in the supersampled content image."""
    sx, sy = theme["cw"] * UP / 1920, theme["ch"] * UP / 1080
    A = max(1, int(frames * speed))
    e = f"(pow(min(1,on/{A}),2)*(3-2*min(1,on/{A})))"
    clampx = lambda v: f"max(0,min(iw-iw/zoom,{v}))"
    clampy = lambda v: f"max(0,min(ih-ih/zoom,{v}))"
    if kind in ("focus_in", "focus_out") and box:
        bw, bh = box["w"] + 120, box["h"] + 120
        Z = max(1.2, min(1.9, 1920 * 0.55 / bw, 1080 * 0.6 / bh))
        px, py = (box["x"] + box["w"] / 2) * sx, (box["y"] + box["h"] / 2) * sy
        if kind == "focus_in":
            z = f"1+{Z - 1:.3f}*{e}"
            cxe, cye = f"({px:.1f}*{e}+iw/2*(1-{e}))", f"({py:.1f}*{e}+ih/2*(1-{e}))"
        else:
            z = f"{Z:.3f}-{Z - 1.04:.3f}*{e}"
            cxe, cye = f"({px:.1f}*(1-{e})+iw/2*{e})", f"({py:.1f}*(1-{e})+ih/2*{e})"
        return z, clampx(f"{cxe}-iw/zoom/2"), clampy(f"{cye}-ih/zoom/2")
    n = frames
    return {
        "zoom_in": (f"1+0.08*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "pan_down": ("1.12", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*on/{n}"),
        "pan_right": ("1.15", f"(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)*0.3"),
        "zoom_out": (f"1.14-0.10*on/{n}", "(iw-iw/zoom)*0.2", "(ih-ih/zoom)*0.15"),
    }[kind]


# ------------------------------------------------------------------ animated intro & outro
def _text_layer(theme, xy, text, fnt, fill, anchor):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_text(layer, xy, text, fnt, fill, anchor=anchor, opacity=120 if not theme["light"] else 40)
    return _crop(layer)


def intro_frames(theme, info, data, logo, first_shot, work):
    """Animated intro as RGBA frames (overlaid on the first segment, fading out at the end)."""
    brand = data.get("brand") or info["domain"]
    bg = background(theme, (W, H))
    hf = lambda s: head_font(theme["head_font"], s)
    style = theme["intro"]
    d = ImageDraw.Draw(bg)
    q1, q2 = _cap(theme, f"Is {brand}"), _cap(theme, "worth using?")
    els = []      # (image, (x, y), start, dur, (dx, dy), kind)
    if style == "split":
        sc = Image.open(first_shot).convert("RGB").resize((1100, 619), Image.LANCZOS)
        card = round_corners(sc, 22).rotate(theme["thumb_tilt"] * 0.6, Image.BICUBIC, expand=True)
        els.append((card, (860, 230), 0.0, 0.6, (420, 0), "slide"))
        x, y = 110, 330
    else:
        x, y = (W // 2, 560) if style == "logo_pop" else (150, 420)
    if style == "headline":
        sc = Image.open(first_shot).convert("RGB").resize((900, 506), Image.LANCZOS)
        for k, (tilt, pos) in enumerate(((-7, (1180, 120)), (5, (1080, 520)))):
            card = rounded((908, 514), 20, (255, 255, 255, 255))
            card.alpha_composite(round_corners(sc.convert("RGBA"), 16), (4, 4))
            holder = Image.new("RGBA", (1100, 760), (0, 0, 0, 0))
            paste_shadowed(holder, card.rotate(tilt, Image.BICUBIC, expand=True), (60, 40), 20, 26,
                           60 if theme["light"] else 170, 16)
            els.append((holder, (pos[0] - 60, pos[1] - 40), 0.05 + k * 0.12, 0.6, (500, 0), "slide"))
    if logo is not None:
        chip = logo_chip(logo, 70 if style == "logo_pop" else 52)
        pos = ((W - chip.width) // 2, 300) if style == "logo_pop" else (x, y - chip.height - 50)
        holder = Image.new("RGBA", (chip.width + 80, chip.height + 80), (0, 0, 0, 0))
        paste_shadowed(holder, chip, (40, 40), chip.height // 2, 20, 150, 10)
        els.append((holder, (pos[0] - 40, pos[1] - 40), 0.12, 0.45, (0, 0), "pop"))
    anchor = "ma" if style == "logo_pop" else "la"
    f = fit(d, q1, hf, 1500 if style != "split" else 720, 120)
    for k, (txt, col, yy) in enumerate(((q1, theme["text"], y), (q2, theme["accent_text"], y + int(f.size * 1.1)))):
        im, at = _text_layer(theme, (x, yy), txt, f, col, anchor)
        if im is not None:
            els.append((im, at, 0.28 + k * 0.16, 0.5, (0, 70), "slide"))
    cat = data.get("category_name", "")
    label = f"{cat.upper()}  ·  2026 REVIEW" if cat else "2026 REVIEW"
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((x, y + int(f.size * 2.4)), label, font=font("Bold", 30), fill=theme["muted"],
                             anchor=anchor)
    im, at = _crop(lay)
    if im is not None:
        els.append((im, at, 0.75, 0.4, (0, 20), "slide"))

    n = int(INTRO * FPS)
    fade_from = INTRO - 0.55
    for i in range(n):
        t = i / FPS
        frame = bg.copy()
        for im, (ex, ey), st, du, (dx, dy), kind in els:
            p = (t - st) / du
            if p <= 0:
                continue
            if kind == "pop":
                s = 0.4 + 0.6 * ease_back(p)
                el = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.BICUBIC)
                pos = (int(ex + (im.width - el.width) / 2), int(ey + (im.height - el.height) / 2))
                frame.alpha_composite(_fade(el, min(1, p * 2)), pos)
            else:
                e = ease_out(p)
                frame.alpha_composite(_fade(im, min(1, p * 1.6)),
                                      (int(ex + dx * (1 - e)), int(ey + dy * (1 - e))))
        if t > fade_from:
            frame = _fade(frame, 1 - ease_out((t - fade_from) / (INTRO - fade_from)))
        frame.save(work / f"intro_{i:03d}.png", compress_level=1)
    return work / "intro_%03d.png"


def outro_frames(theme, data, logo, work, anim=2.4):
    """Animated verdict card (score counts up, ring fills, verdict lands). Returns frame pattern."""
    verdict = data.get("verdict", "Worth it for some")
    vcol = {"Worth it": (46, 204, 113), "Not worth it": (231, 76, 60)}.get(verdict, (255, 196, 0))
    if theme["light"]:
        vcol = mix(vcol, (0, 0, 0), 0.25)
    try:
        score = max(0.0, min(10.0, float(data.get("score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    hf = lambda s: head_font(theme["head_font"], s)
    vtext = _cap(theme, verdict.upper())
    bg = background(theme, (W, H))
    meas = ImageDraw.Draw(bg)
    ring = theme["outro"] == "ring"

    def layer(draw_fn):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(lay), lay)
        return _crop(lay)

    if ring:
        chip = logo_chip(logo, 60) if logo is not None else None
        label = layer(lambda d, l: d.text((160, 420), "THE VERDICT", font=font("Bold", 36), fill=theme["muted"]))
        lines = wrap(meas, vtext, hf(110), 860)[:3]
        vlay = layer(lambda d, l: [d.text((160, 480 + i * 120), ln, font=hf(110), fill=vcol)
                                   for i, ln in enumerate(lines)])
        nxt = layer(lambda d, l: d.text((160, 900), "Watch the next review  →", font=font("Bold", 38),
                                        fill=theme["muted"]))
    else:
        chip = logo_chip(logo, 66) if logo is not None else None
        label = layer(lambda d, l: d.text((W / 2, 380), "THE VERDICT", font=font("Bold", 40),
                                          fill=theme["muted"], anchor="mm"))
        vlay = layer(lambda d, l: d.text((W / 2, 500), vtext, font=fit(meas, vtext, hf, 1500, 130),
                                         fill=vcol, anchor="mm"))
        nxt = layer(lambda d, l: d.text((W / 2, 800), "Watch the next review  →", font=font("Bold", 42),
                                        fill=theme["muted"], anchor="mm"))

    n = int(anim * FPS)
    for i in range(n):
        t = i / FPS
        fr = bg.copy()
        d = ImageDraw.Draw(fr)
        if chip is not None:
            p = (t - 0.05) / 0.45
            if p > 0:
                s = 0.5 + 0.5 * ease_back(p)
                c = chip.resize((max(1, int(chip.width * s)), max(1, int(chip.height * s))), Image.BICUBIC)
                pos = (160, 260) if ring else ((W - c.width) // 2, 170 + (chip.height - c.height) // 2)
                fr.alpha_composite(_fade(c, min(1, p * 2)), pos)
        for (im, (x, y)), st, du, dx, dy in ((label, 0.2, 0.4, 0, 20), (vlay, 0.45, 0.5, -80 if ring else 0, 0 if ring else 40),
                                             (nxt, 1.5, 0.5, 0, 20)):
            if im is None:
                continue
            p = (t - st) / du
            if p > 0:
                e = ease_out(p)
                fr.alpha_composite(_fade(im, min(1, p * 1.6)), (int(x + dx * (1 - e)), int(y + dy * (1 - e))))
        prog = ease_out((t - 0.6) / 1.1)
        shown = score * prog
        if ring:
            cxr, cyr, r = 1400, 520, 230
            d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=mix(theme["bg1"], theme["text"], 0.15), width=26)
            if shown > 0.01:
                d.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90, -90 + 360 * shown / 10, fill=vcol, width=26)
            d.text((cxr, cyr - 10), f"{shown:.1f}", font=hf(150), fill=theme["text"], anchor="mm")
            d.text((cxr, cyr + 95), "OUT OF 10", font=font("Bold", 30), fill=theme["muted"], anchor="mm")
        elif t > 0.6:
            d.text((W / 2, 650), f"{shown:.1f} / 10", font=hf(84), fill=theme["text"], anchor="mm")
            bw = 520
            d.rounded_rectangle([W / 2 - bw / 2, 720, W / 2 + bw / 2, 732], 6, fill=mix(theme["bg1"], theme["text"], 0.15))
            if shown > 0.01:
                d.rounded_rectangle([W / 2 - bw / 2, 720, W / 2 - bw / 2 + bw * shown / 10, 732], 6, fill=vcol)
        fr.convert("RGB").save(work / f"outro_{i:03d}.png", compress_level=1)
    return work / "outro_%03d.png"


# ------------------------------------------------------------------ render
def _zoompan(z, x, y, frames, w, h):
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS}"


def _slide_expr(anim, x0, y0, st):
    e = f"(1-pow(1-min(1,max(0,(t-{st:.3f})/{CAP_D})),3))"
    dx, dy = {"slide_up": (0, 70), "drop": (0, -60), "slide_left": (140, 0), "slide_right": (-140, 0),
              "fade_up": (0, 26)}.get(anim, (0, 40))
    return f"{x0}+{dx}*(1-{e})", f"{y0}+{dy}*(1-{e})"


def _music_track(theme, seconds, work):
    """Path to the background music for this video, or None."""
    user = config.ASSETS_DIR / "music.mp3"
    if user.exists():
        return user
    if theme.get("music", "off") == "off":
        return None
    from .music import compose
    try:
        return compose(theme["music"], seconds + 1, theme["seed"], work / "music.wav")
    except Exception as e:                           # music is a nice-to-have; never fail a video
        print(f"   ! music skipped: {e}")
        return None


def _sfx_track(theme, events, seconds, work):
    if theme.get("sfx", "off") == "off" or not events:
        return None
    from .sfx import build_track
    try:
        return build_track(events, seconds, theme["sfx"], theme["seed"], work / "sfx.wav")
    except Exception as e:
        print(f"   ! sound effects skipped: {e}")
        return None


def render(data, info, out_dir: Path, theme: dict) -> Path:
    work = out_dir / "render"
    work.mkdir(exist_ok=True)
    logo = load_logo(out_dir / info["logo"]) if info.get("logo") else None
    brand = data.get("brand") or info["domain"]
    segs = data["segments"]
    total = len(segs)
    trans = theme["transitions"]
    T = 0.0 if trans == ["cut"] else 0.5
    rnd = random.Random(theme["seed"] + "cam")
    plain_moves = ["zoom_in", "pan_down", "zoom_out", "pan_right"]
    rnd.shuffle(plain_moves)
    theme.setdefault("cap_anim", "slide_up")          # older videos (rerender) predate these options
    theme.setdefault("callout", "card")
    if "music" not in theme:
        from .music import MOODS
        theme["music"] = config.MUSIC if config.MUSIC in MOODS + ["off"] else random.Random(theme["seed"]).choice(MOODS)
    theme.setdefault("sfx", "soft" if config.SFX else "off")

    theme.setdefault("bg_image", str(out_dir / info["screenshots"][0]["file"]))
    fg = work / "fg.png"
    build_foreground(theme, info, logo, brand).save(fg)
    events = [(0.0, "whoosh"), (0.45, "impact"), (0.8, "pop"), (INTRO - 0.5, "whoosh")]

    clips, lens, start = [], [], 0.0
    for i, seg in enumerate(segs):
        d_i = round((seg["duration"] + PAD) * FPS) / FPS
        seg["clip_duration"] = d_i
        n = int(round((d_i + T) * FPS))
        clip = work / f"clip_{i:02d}.mp4"
        shot = out_dir / seg["screenshot"]
        icon = icons.pick(seg)
        callout = (seg.get("callout") or "").strip()
        cap_at = INTRO - 0.35 if i == 0 else T + 0.12
        inputs, fl = [], []
        if i > 0 and T:
            events.append((start, "whoosh"))
        if seg["screenshot"] == "mobile.png":
            still = work / f"still_{i:02d}.png"
            mobile_frame(theme, shot, seg, i + 1, total, logo).convert("RGB").save(still)
            inputs = ["-i", str(still)]
            fl.append(f"[0:v]scale={W * UP}:{H * UP},{_zoompan(f'1+0.05*on/{n}', 'iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)', n, W, H)}[v0]")
            last = "v0"
        else:
            hl = work / f"hl_{i:02d}.png"
            box = seg.get("focus_box")
            highlight(shot, box, theme, hl)
            kind = "focus_in" if box else plain_moves[i % len(plain_moves)]
            speed = rnd.uniform(0.3, 0.55)
            z, x, y = camera(kind, n, theme, box, speed=speed)
            if box:
                events.append((start + max(1, int(n * speed)) / FPS, "tick"))
            cw, ch = theme["cw"], theme["ch"]
            inputs = ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={(n + 2) / FPS:.3f}",
                      "-i", str(hl), "-loop", "1", "-framerate", str(FPS), "-i", str(fg)]
            fl.append(f"[1:v]scale={cw * UP}:{ch * UP},setsar=1,{_zoompan(z, x, y, n, cw, ch)}[z]")
            fl.append(f"[0:v][z]overlay={theme['cx']}:{theme['cy']}:shortest=1[b]")
            fl.append("[2:v]format=rgba[f];[b][f]overlay=0:0:shortest=1[v0]")
            last = "v0"
            # caption (animated entrance)
            cap_im, (cx0, cy0) = caption_layer(theme, seg, i + 1, total, icon=None if callout else icon)
            if cap_im is not None:
                cp = work / f"cap_{i:02d}.png"
                cap_im.save(cp)
                k = len([a for a in inputs if a == "-i"])
                inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(cp)]
                ex, ey = _slide_expr(theme["cap_anim"], cx0, cy0, cap_at)
                fl.append(f"[{k}:v]format=rgba,fade=t=in:st={cap_at:.3f}:d={CAP_D * 0.8:.3f}:alpha=1[cp];"
                          f"[{last}][cp]overlay=x='{ex}':y='{ey}':shortest=1[v1]")
                last = "v1"
                events.append((start + cap_at, "pop"))
            # callout sticker with icon (pops in)
            co_at = (INTRO + 0.6) if i == 0 else T + CALLOUT_AT
            if callout and d_i + T - co_at > 1.5:
                card = callout_card(theme, callout, icon)
                px, py = callout_position(theme, card)
                pattern, pad = callout_frames(card, int(co_at * FPS), work, f"{i:02d}")
                k = len([a for a in inputs if a == "-i"])
                inputs += ["-framerate", str(FPS), "-i", str(pattern)]
                fl.append(f"[{k}:v]format=rgba[co];[{last}][co]overlay={px - pad}:{py - pad}[v2]")
                last = "v2"
                events.append((start + co_at, "blip"))
        if i == 0 and theme.get("intro"):
            pattern = intro_frames(theme, info, data, logo, out_dir / info["screenshots"][0]["file"], work)
            k = len([a for a in inputs if a == "-i"])
            inputs += ["-framerate", str(FPS), "-i", str(pattern)]
            fl.append(f"[{k}:v]format=rgba[ic];[{last}][ic]overlay=0:0:eof_action=pass[vi]")
            last = "vi"
        _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fl),
              "-map", f"[{last}]", "-frames:v", str(n), "-an", *X264, str(clip)])
        clips.append(clip)
        lens.append(n / FPS)
        start += n / FPS - T
        print(f"   clip {i + 1}/{total} ({d_i:.1f}s, {seg['screenshot']}, "
              f"{'focus' if seg.get('focus_box') else 'move'}{', ' + icon if icon else ''}"
              f"{', callout' if callout else ''})")

    outro_start = start
    pattern = outro_frames(theme, data, logo, work)
    outro = work / "outro.mp4"
    on = int(OUTRO * FPS)
    _run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(pattern), "-filter_complex",
          f"[0:v]tpad=stop_mode=clone:stop_duration={OUTRO:.2f}[v]",
          "-map", "[v]", "-frames:v", str(on), *X264, str(outro)])
    clips.append(outro)
    lens.append(OUTRO)
    events += [(outro_start - 1.05, "riser"), (outro_start + 0.5, "impact"), (outro_start + 1.75, "ding")]
    if T:
        events.append((outro_start, "whoosh"))

    # ---- assemble: transitions + narration + progress bar + music + sound effects
    content = sum(s["clip_duration"] for s in segs)
    total_len = content + OUTRO
    args, fl = [], []
    for c in clips:
        args += ["-i", str(c)]
    for k in range(len(clips)):
        fl.append(f"[{k}:v]settb=AVTB,fps={FPS},format=yuv420p[c{k}]")
    if T == 0:
        fl.append("".join(f"[c{k}]" for k in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[vx]")
    else:
        acc_len, prev = lens[0], "c0"
        for k in range(1, len(clips)):
            name = trans[(k - 1) % len(trans)]
            out = "vx" if k == len(clips) - 1 else f"x{k}"
            fl.append(f"[{prev}][c{k}]xfade=transition={name}:duration={T}:offset={acc_len - T:.3f}[{out}]")
            acc_len += lens[k] - T
            prev = out
    vout = "vx"
    if theme.get("progress"):
        args += ["-f", "lavfi", "-i", f"color=c={_hex(theme['accent'])}:s={W}x5:r={FPS}"]
        pb = len(clips)
        fl.append(f"[{vout}][{pb}:v]overlay=x='-w+w*min(1,t/{content:.2f})':y={H - 5}:shortest=1[vp]")
        vout = "vp"
    a0 = len([a for a in args if a == "-i"])
    for s in segs:
        args += ["-i", s["audio"]]
    for j, s in enumerate(segs):
        fl.append(f"[{a0 + j}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"apad,atrim=0:{s['clip_duration']:.3f}[a{j}]")
    fl.append("".join(f"[a{j}]" for j in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1,"
              f"apad=whole_dur={total_len:.3f}[narr]")
    mixes = ["narr"]
    music = _music_track(theme, total_len, work)
    sfx = _sfx_track(theme, events, total_len, work)
    nxt = a0 + len(segs)
    if music is not None:
        loop = ["-stream_loop", "-1"] if music.suffix == ".mp3" else []
        args += [*loop, "-i", str(music)]
        fl.append("[narr]asplit=2[narr_m][narr_sc]")
        fl.append(f"[{nxt}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.36[mus];"
                  f"[mus][narr_sc]sidechaincompress=threshold=0.015:ratio=4:attack=25:release=500[duck]")
        mixes = ["narr_m", "duck"]
        nxt += 1
    if sfx is not None:
        args += ["-i", str(sfx)]
        fl.append(f"[{nxt}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.32[fx]")
        mixes.append("fx")
        nxt += 1
    if len(mixes) > 1:
        fl.append("".join(f"[{m}]" for m in mixes) +
                  f"amix=inputs={len(mixes)}:duration=first:normalize=0[premix]")
    else:
        fl.append("[narr]anull[premix]")
    fl.append("[premix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[mix]")    # YouTube loudness
    aout = "mix"
    final = out_dir / "video.mp4"
    _run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex", ";".join(fl),
          "-map", f"[{vout}]", "-map", f"[{aout}]", "-t", f"{total_len:.3f}", *X264,
          "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(final)])
    print(f"   video ready: {duration(final):.0f}s · layout {theme['layout']}, {theme['mode']}, "
          f"{theme['bg']}, font {theme['head_font']}, captions {theme['caption']}/{theme['cap_anim']}, "
          f"callouts {theme['callout']}, music {theme.get('music')}, sfx {theme.get('sfx')}, "
          f"transitions {'/'.join(trans)}")
    return final


def chapters(segments):
    """YouTube chapters: first at 0:00, at least 3, each >= 10 s."""
    out, t, last = [], 0.0, None
    for seg in segments:
        if last is None or t - last >= 10:
            out.append((t, seg["caption"]))
            last = t
        t += seg["clip_duration"]
    if len(out) < 3:
        return ""
    return "\n".join(f"{int(s // 60)}:{int(s % 60):02d} {title}" for s, title in out)
