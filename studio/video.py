"""Step 4: render the review video (1080p) with the per-video theme.

Each segment = website screenshot moving under a "camera" (smart zoom to the thing being talked
about, with a highlight), framed by a themed foreground (browser frame, caption, logo).
Segments are joined with themed transitions; an intro card, progress bar and verdict end card
are added. Narration is laid over the whole timeline in one pass so it stays in sync.
"""
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import config
from .tts import duration
from .visuals import (background, fit, font, head_font, head_upper, is_light, load_logo, logo_chip,
                      lum, mix, paste_shadowed, readable_on, round_corners, rounded, shadow_text, wrap)

W, H, FPS = config.VIDEO_W, config.VIDEO_H, config.FPS
PAD = 0.35            # breath after each segment
OUTRO = 8.0           # end card (room for YouTube end-screen elements)
INTRO = 2.6           # intro card overlaid on the first seconds
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


def _caption(fg, theme, x, y, max_w, text, size, idx, total, light_text=None, max_lines=1):
    """Draw the segment caption in the theme's caption style. Returns bottom y."""
    d = ImageDraw.Draw(fg)
    acc, acc_t = theme["accent"], theme["accent_text"]
    tcol = light_text or theme["text"]
    text = _cap(theme, text)
    hf = lambda s: head_font(theme["head_font"], s)
    if max_lines == 1:
        f = fit(d, text, hf, max_w - (60 if theme["caption"] in ("bar", "pill") else 0), size)
        lines = [text]
    else:
        f = hf(size)
        lines = wrap(d, text, f, max_w)
        while len(lines) > max_lines and size > 30:
            size -= 4
            f = hf(size)
            lines = wrap(d, text, f, max_w)
    lh = int(f.size * 1.12)
    style = theme["caption"]
    if style == "tag":
        d.text((x, y), f"{idx:02d} / {total:02d}", font=font("Bold", max(18, size * 0.42)), fill=acc_t)
        y += int(size * 0.62)
    if style == "pill":
        widest = max(d.textlength(l, font=f) for l in lines)
        box = rounded((widest + 56, lh * len(lines) + 30), 18, (*acc, 255))
        fg.alpha_composite(box, (int(x), int(y)))
        for i, l in enumerate(lines):
            d.text((x + 28, y + 15 + i * lh), l, font=f, fill=readable_on(acc))
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


def build_foreground(theme, seg, idx, total, info, logo, brand):
    base = background(theme, (W, H))
    cx, cy, cw, ch = theme["cx"], theme["cy"], theme["cw"], theme["ch"]
    lay = theme["layout"]
    if lay != "cinema":
        _draw_frame(base, theme, info["domain"])
    fg = _cut_hole(base, theme)
    d = ImageDraw.Draw(fg)
    cap = seg["caption"]
    if lay == "full":
        y = cy + ch + 26
        _caption(fg, theme, cx, y, 1180, cap, 46, idx, total)
        if logo is not None:
            chip = logo_chip(logo, 32)
            fg.alpha_composite(chip, (cx + cw - chip.width, y + (8 if theme["caption"] != "tag" else 20)))
    elif lay == "side":
        if theme["caption"] == "tag":
            _caption(fg, theme, 80, 300, 470, cap, 64, idx, total, max_lines=4)
        else:
            d.text((80, 200), f"{idx:02d}", font=head_font(theme["head_font"], 120), fill=theme["accent_text"])
            _caption(fg, theme, 80, 360, 470, cap, 62, idx, total, max_lines=3)
        if logo is not None:
            chip = logo_chip(logo, 40)
            fg.alpha_composite(chip, (80, cy + ch - chip.height))
        else:
            d.text((80, cy + ch), brand, font=font("Bold", 34), fill=theme["muted"], anchor="ls")
    elif lay == "stage":
        _caption(fg, theme, cx, 70, 1080, cap, 66, idx, total)
        if logo is not None:
            chip = logo_chip(logo, 38)
            fg.alpha_composite(chip, (cx + cw - chip.width, 78))
    else:  # cinema: caption on a dark glass panel over the full-screen website
        grad = Image.new("L", (1, 256))
        grad.putdata([int(min(225, max(0, (i - 60) * 1.4))) for i in range(256)])
        shade = Image.new("RGBA", (W, 460), (6, 8, 12, 255))
        shade.putalpha(grad.resize((W, 460)))
        fg.alpha_composite(shade, (0, H - 460))
        glass = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bottom = _caption(glass, {**theme, "text": (255, 255, 255),
                                  "accent_text": theme["accent"] if lum(theme["accent"]) > 110 else (255, 255, 255)},
                          110, H - 190, 1300, cap, 60, idx, total, light_text=(255, 255, 255))
        box = glass.getchannel("A").getbbox()
        if box and theme["caption"] != "pill":
            panel = rounded((box[2] - box[0] + 64, box[3] - box[1] + 48), 22, (8, 10, 14, 175))
            fg.alpha_composite(panel, (box[0] - 32, box[1] - 24))
        fg.alpha_composite(glass)
        if logo is not None:
            chip = logo_chip(logo, 28)
            paste_shadowed(fg, chip, (W - chip.width - 56, H - 150 + (40 - chip.height) // 2),
                           chip.height // 2, 16, 140, 6)
    return fg


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
        style = theme["highlight"]
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if style == "spotlight":
            dim = Image.new("RGBA", im.size, (0, 0, 0, 62))
            ImageDraw.Draw(dim).rounded_rectangle(rect, 14, fill=(0, 0, 0, 0))
            im.alpha_composite(dim)
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


# ------------------------------------------------------------------ intro & outro cards
def intro_card(theme, info, data, logo, first_shot):
    brand = data.get("brand") or info["domain"]
    im = background(theme, (W, H))
    d = ImageDraw.Draw(im)
    hf = lambda s: head_font(theme["head_font"], s)
    style = theme["intro"]
    q1, q2 = _cap(theme, f"Is {brand}"), _cap(theme, "worth using?")
    if style == "split":
        sc = Image.open(first_shot).convert("RGB").resize((1100, 619), Image.LANCZOS)
        card = round_corners(sc, 22)
        im.alpha_composite(card.rotate(theme["thumb_tilt"] * 0.6, Image.BICUBIC, expand=True), (860, 230))
        x, y = 110, 330
    else:
        x, y = (W // 2, 560) if style == "logo_pop" else (150, 420)
    if style == "headline":
        sc = Image.open(first_shot).convert("RGB").resize((900, 506), Image.LANCZOS)
        for k, (tilt, pos) in enumerate(((-7, (1180, 120)), (5, (1080, 520)))):
            card = rounded((908, 514), 20, (255, 255, 255, 255))
            card.alpha_composite(round_corners(sc.convert("RGBA"), 16), (4, 4))
            paste_shadowed(im, card.rotate(tilt, Image.BICUBIC, expand=True), pos, 20, 26,
                           60 if theme["light"] else 170, 16)
    if logo is not None:
        chip = logo_chip(logo, 70 if style == "logo_pop" else 52)
        pos = ((W - chip.width) // 2, 300) if style == "logo_pop" else (x, y - chip.height - 50)
        paste_shadowed(im, chip, pos, chip.height // 2, 20, 150, 10)
    anchor = "ma" if style == "logo_pop" else "la"
    f = fit(d, q1, hf, 1500 if style != "split" else 720, 120)
    shadow_text(im, (x, y), q1, f, theme["text"], anchor=anchor, opacity=120 if not theme["light"] else 40)
    shadow_text(im, (x, y + int(f.size * 1.1)), q2, f, theme["accent_text"], anchor=anchor,
                opacity=120 if not theme["light"] else 40)
    cat = data.get("category_name", "")
    label = f"{cat.upper()}  ·  2026 REVIEW" if cat else "2026 REVIEW"
    ly = y + int(f.size * 2.4)
    d.text((x, ly), label, font=font("Bold", 30), fill=theme["muted"], anchor=anchor)
    return im


def outro_card(theme, data, logo):
    im = background(theme, (W, H))
    d = ImageDraw.Draw(im)
    verdict = data.get("verdict", "Worth it for some")
    vcol = {"Worth it": (46, 204, 113), "Not worth it": (231, 76, 60)}.get(verdict, (255, 196, 0))
    if theme["light"]:
        vcol = mix(vcol, (0, 0, 0), 0.25)
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    hf = lambda s: head_font(theme["head_font"], s)
    vtext = _cap(theme, verdict.upper())
    if theme["outro"] == "ring":
        cxr, cyr, r = 1400, 520, 230
        d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=mix(theme["bg1"], theme["text"], 0.15), width=26)
        d.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90, -90 + 360 * score / 10, fill=vcol, width=26)
        d.text((cxr, cyr - 10), f"{score:.1f}", font=hf(150), fill=theme["text"], anchor="mm")
        d.text((cxr, cyr + 95), "OUT OF 10", font=font("Bold", 30), fill=theme["muted"], anchor="mm")
        if logo is not None:
            im.alpha_composite(logo_chip(logo, 60), (160, 260))
        d.text((160, 420), "THE VERDICT", font=font("Bold", 36), fill=theme["muted"])
        for i, line in enumerate(wrap(d, vtext, hf(110), 860)[:3]):
            d.text((160, 480 + i * 120), line, font=hf(110), fill=vcol)
        d.text((160, 900), "Watch the next review  →", font=font("Bold", 38), fill=theme["muted"])
        return im
    if logo is not None:
        chip = logo_chip(logo, 66)
        im.alpha_composite(chip, ((W - chip.width) // 2, 170))
    d.text((W / 2, 380), "THE VERDICT", font=font("Bold", 40), fill=theme["muted"], anchor="mm")
    d.text((W / 2, 500), vtext, font=fit(d, vtext, hf, 1500, 130), fill=vcol, anchor="mm")
    d.text((W / 2, 650), f"{score:.1f} / 10", font=hf(84), fill=theme["text"], anchor="mm")
    d.text((W / 2, 800), "Watch the next review  →", font=font("Bold", 42), fill=theme["muted"], anchor="mm")
    return im


# ------------------------------------------------------------------ render
def _zoompan(z, x, y, frames, w, h):
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS}"


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

    clips, lens = [], []
    for i, seg in enumerate(segs):
        d_i = round((seg["duration"] + PAD) * FPS) / FPS
        seg["clip_duration"] = d_i
        n = int(round((d_i + T) * FPS))
        clip = work / f"clip_{i:02d}.mp4"
        shot = out_dir / seg["screenshot"]
        inputs, fl = [], []
        if seg["screenshot"] == "mobile.png":
            still = work / f"still_{i:02d}.png"
            mobile_frame(theme, shot, seg, i + 1, total, logo).convert("RGB").save(still)
            inputs = ["-i", str(still)]
            fl.append(f"[0:v]scale={W * UP}:{H * UP},{_zoompan(f'1+0.05*on/{n}', 'iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)', n, W, H)}[v0]")
        else:
            fg = work / f"fg_{i:02d}.png"
            build_foreground(theme, seg, i + 1, total, info, logo, brand).save(fg)
            hl = work / f"hl_{i:02d}.png"
            box = seg.get("focus_box")
            highlight(shot, box, theme, hl)
            if box:
                kind = "focus_in"
            else:
                kind = plain_moves[i % len(plain_moves)]
            z, x, y = camera(kind, n, theme, box, speed=rnd.uniform(0.3, 0.55))
            cw, ch = theme["cw"], theme["ch"]
            inputs = ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={(n + 2) / FPS:.3f}",
                      "-i", str(hl), "-loop", "1", "-framerate", str(FPS), "-i", str(fg)]
            fl.append(f"[1:v]scale={cw * UP}:{ch * UP},setsar=1,{_zoompan(z, x, y, n, cw, ch)}[z]")
            fl.append(f"[0:v][z]overlay={theme['cx']}:{theme['cy']}:shortest=1[b]")
            fl.append("[2:v]format=rgba[f];[b][f]overlay=0:0:shortest=1[v0]")
        last = "v0"
        if i == 0 and theme.get("intro"):
            card = work / "intro.png"
            intro_card(theme, info, data, logo, out_dir / info["screenshots"][0]["file"]).convert("RGB").save(card)
            k = len([a for a in inputs if a == "-i"])
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{INTRO:.2f}", "-i", str(card)]
            fl.append(f"[{k}:v]format=rgba,"
                      f"fade=t=out:st={INTRO - 0.6:.2f}:d=0.6:alpha=1[ic];"
                      f"[{last}][ic]overlay=0:0:eof_action=pass[v1]")
            last = "v1"
        _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fl),
              "-map", f"[{last}]", "-frames:v", str(n), "-an", *X264, str(clip)])
        clips.append(clip)
        lens.append(n / FPS)
        print(f"   clip {i + 1}/{total} ({d_i:.1f}s, {seg['screenshot']}, "
              f"{'focus' if seg.get('focus_box') else 'move'})")

    out_png = work / "outro.png"
    outro_card(theme, data, logo).convert("RGB").save(out_png)
    outro = work / "outro.mp4"
    on = int(OUTRO * FPS)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(out_png), "-filter_complex",
          f"[0:v]scale={W * UP}:{H * UP},{_zoompan(f'1+0.035*on/{on}', 'iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)', on, W, H)}[v]",
          "-map", "[v]", "-frames:v", str(on), *X264, str(outro)])
    clips.append(outro)
    lens.append(OUTRO)

    # ---- assemble: transitions + narration + progress bar (+ optional music)
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
        args += ["-f", "lavfi", "-i", f"color=c={_hex(theme['accent'])}:s={W}x7:r={FPS}"]
        pb = len(clips)
        fl.append(f"[{vout}][{pb}:v]overlay=x='-w+w*min(1,t/{content:.2f})':y={H - 7}:shortest=1[vp]")
        vout = "vp"
    a0 = len([a for a in args if a == "-i"])
    for s in segs:
        args += ["-i", s["audio"]]
    for j, s in enumerate(segs):
        fl.append(f"[{a0 + j}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"apad,atrim=0:{s['clip_duration']:.3f}[a{j}]")
    fl.append("".join(f"[a{j}]" for j in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1,"
              f"apad=whole_dur={total_len:.3f}[narr]")
    aout = "narr"
    music = config.ASSETS_DIR / "music.mp3"
    if music.exists():
        mi = a0 + len(segs)
        args += ["-stream_loop", "-1", "-i", str(music)]
        fl.append(f"[{mi}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.07[m];"
                  f"[narr][m]amix=inputs=2:duration=first:normalize=0[mix]")
        aout = "mix"
    final = out_dir / "video.mp4"
    _run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex", ";".join(fl),
          "-map", f"[{vout}]", "-map", f"[{aout}]", "-t", f"{total_len:.3f}", *X264,
          "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(final)])
    print(f"   video ready: {duration(final):.0f}s · layout {theme['layout']}, {theme['mode']}, "
          f"{theme['bg']}, font {theme['head_font']}, transitions {'/'.join(trans)}")
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
