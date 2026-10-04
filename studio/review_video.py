"""Review videos, cinematic edition: the website as the star of a premium, editorial-style video.

Every frame has three layers:
  1 background  a huge, heavily blurred, slightly zoomed copy of the same page, darkened at the
                edges, drifting very slowly (no empty space, no distracting detail)
  2 the website razor-sharp, rounded, with a soft shadow and glow, moved by a smooth "camera"
                (push-ins toward the thing being talked about, gentle pans, scrolls)
  3 captions    kinetic, word-synced to the voice: each word rises into place exactly when it is
                spoken, key words light up in the accent colour, the sentence builds and then
                softly clears before the next one

Thirteen layouts, rotated so neighbouring segments never repeat (some only when they fit, e.g.
the phone needs a mobile screenshot, the magnifier needs a spot to magnify):
  center, browser, tilt_left, tilt_right, split_left, split_right, full_bleed, spotlight, stack,
  magnify, duo, scroll, phone

Segments render in parallel (one process each), are joined with soft transitions, and get the
narration, quiet background chords (ducked under the voice) and a few subtle sound effects.
"""
import difflib
import math
import os
import random
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

W, H, FPS = config.VIDEO_W, config.VIDEO_H, config.FPS
PAD = 0.35                 # breath after each segment
T = 0.5                    # transition overlap
OUTRO = 8.0                # end card (room for YouTube end-screen elements)
INTRO = 2.7                # title over the first seconds
FONTS = config.ASSETS_DIR / "fonts"
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS)]
LAYOUTS = ["center", "browser", "tilt_left", "split_left", "full_bleed", "spotlight", "stack", "tilt_right",
           "magnify", "split_right", "duo", "scroll", "phone"]
TRANSITIONS = ["fade", "smoothleft", "smoothup", "fade", "smoothright", "zoomin"]


# ------------------------------------------------------------------ small helpers
@lru_cache(maxsize=64)
def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), int(size))


def ease(p):                                   # ease-out cubic
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def ease_io(p):                                # ease-in-out sine
    p = min(1.0, max(0.0, p))
    return 0.5 - 0.5 * math.cos(math.pi * p)


def back(p, s=1.6):                            # ease-out with a little overshoot
    p = min(1.0, max(0.0, p))
    return 1 + (s + 1) * (p - 1) ** 3 + s * (p - 1) ** 2


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def vivid(c):
    """The accent, made bright enough to glow on a dark, blurred background."""
    c = tuple(int(x) for x in c[:3])
    while lum(c) < 135:
        c = tuple(min(255, int(x + (255 - x) * 0.18)) for x in c)
    if max(c) - min(c) < 40:                    # grey brand colour: a clean electric blue instead
        c = (90, 170, 255)
    return c


def _alpha(im, k):
    if k >= 0.999:
        return im
    out = im.copy()
    out.putalpha(im.getchannel("A").point(lambda v: int(v * max(0.0, k))))
    return out


def rounded_mask(w, h, r):
    s = 3
    m = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * s - 1, h * s - 1], r * s, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def shadow_for(w, h, r, blur=38, spread=14, opacity=170, glow=None):
    """Soft drop shadow (and optional coloured glow) for a w x h card; returns (image, offset)."""
    m = int(blur * 2.5 + spread)
    im = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    a = Image.new("L", im.size, 0)
    ImageDraw.Draw(a).rounded_rectangle([m - spread, m - spread + 18, m + w + spread, m + h + spread + 18], r + spread,
                                        fill=opacity)
    a = a.filter(ImageFilter.GaussianBlur(blur))
    im.paste((0, 0, 0, 255), (0, 0), a)
    if glow:
        g = Image.new("L", im.size, 0)
        ImageDraw.Draw(g).rounded_rectangle([m - 6, m - 6, m + w + 6, m + h + 6], r + 6, fill=90)
        g = g.filter(ImageFilter.GaussianBlur(blur * 1.4))
        col = Image.new("RGBA", im.size, (*glow, 255))
        col.putalpha(g)
        im = Image.alpha_composite(im, col)
    return im, m


# ------------------------------------------------------------------ words: what is said when
def _norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align_words(text, spoken):
    """The script's own words (with punctuation, $5/mo, 40%...) timed by the voice's word list."""
    toks = text.split()
    if not toks:
        return []
    if not spoken:
        return []
    a = [_norm(t) for t in toks]
    b = [_norm(w) for _, _, w in spoken]
    times = [None] * len(toks)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            s, e, _ = spoken[blk.b + k]
            times[blk.a + k] = (s, e)
    # unmatched words ("$5/mo" spoken as "5 dollars a month"): spread between their neighbours
    i = 0
    while i < len(toks):
        if times[i] is None:
            j = i
            while j < len(toks) and times[j] is None:
                j += 1
            t0 = times[i - 1][1] if i > 0 else (spoken[0][0] if spoken else 0.0)
            t1 = times[j][0] if j < len(toks) else (spoken[-1][1] if spoken else t0 + 0.4 * (j - i))
            step = max(0.08, (t1 - t0) / (j - i))
            for k in range(i, j):
                times[k] = (t0 + (k - i) * step, t0 + (k - i + 1) * step)
            i = j
        else:
            i += 1
    return [(s, e, w) for (s, e), w in zip(times, toks)]


KEY = re.compile(r"[$€£%]|\d|^[A-Z]{2,}\W*$")


def phrases(words, max_words=8, max_chars=46):
    """Group timed words into on-screen phrases: break at sentence ends and commas, or when full."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        txt = " ".join(x[2] for x in cur)
        end = re.search(r"[.!?;:]$", w[2]) or (re.search(r",$", w[2]) and len(cur) >= 4)
        if end or len(cur) >= max_words or len(txt) >= max_chars:
            out.append(cur)
            cur = []
    if cur:
        if out and len(cur) <= 2 and len(" ".join(x[2] for x in out[-1] + cur)) <= max_chars + 10:
            out[-1] += cur
        else:
            out.append(cur)
    return out


# ------------------------------------------------------------------ captions
class Captions:
    """Kinetic captions: words rise into place as they are spoken; the key words glow in the accent."""

    def __init__(self, words, accent, brand, size=54, max_w=1500, align="center", backing=True,
                 font="InterDisplay-ExtraBold.otf", max_lines=2):
        self.accent, self.size, self.max_w, self.align, self.backing = accent, size, max_w, align, backing
        self.font = _font(font, size)
        self.space = self.font.getlength(" ")
        brand_words = {_norm(b) for b in (brand or "").split()}
        self.groups = []
        for ph in phrases(words, max_words=8 if align == "center" else 12,
                          max_chars=46 if align == "center" else 80):
            items = []
            for s, e, w in ph:
                key = bool(KEY.search(w)) or _norm(w) in brand_words
                items.append({"s": s, "e": e, "w": w, "key": key})
            self._layout(items, max_lines)
            self.groups.append(items)
        for gi, g in enumerate(self.groups):           # when each phrase leaves: just before the next
            nxt = self.groups[gi + 1][0]["s"] if gi + 1 < len(self.groups) else g[-1]["e"] + 1.2
            g[0]["leave"] = min(g[-1]["e"] + 0.9, nxt - 0.06)
        self._cache = {}

    def _layout(self, items, max_lines):
        lines, cur, cw = [], [], 0.0
        for it in items:
            w = self.font.getlength(it["w"])
            if cur and cw + self.space + w > self.max_w:
                lines.append(cur)
                cur, cw = [], 0.0
            cur.append(it)
            cw += (self.space if len(cur) > 1 else 0) + w
            it["w_px"] = w
        if cur:
            lines.append(cur)
        lh = self.size * 1.22
        for li, line in enumerate(lines):
            lw = sum(it["w_px"] for it in line) + self.space * (len(line) - 1)
            x = -lw / 2 if self.align == "center" else 0
            lx = 0.0
            for it in line:
                it["x"], it["y"], it["line"], it["lx"] = x, li * lh, li, lx
                x += it["w_px"] + self.space
                lx += it["w_px"] + self.space
        items[0]["lines"] = len(lines)
        items[0]["width"] = max(sum(it["w_px"] for it in ln) + self.space * (len(ln) - 1) for ln in lines)

    def _word(self, w, color):
        k = (w, color)
        if k not in self._cache:
            bb = self.font.getbbox(w)
            pad = 12
            im = Image.new("RGBA", (int(bb[2] + pad * 2), int(self.size * 1.5 + pad)), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((pad, pad // 2 + 3), w, font=self.font, fill=(0, 0, 0, 150))
            im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5)))
            d.text((pad, pad // 2), w, font=self.font, fill=color)
            self._cache[k] = (im, pad)
        return self._cache[k]

    def draw(self, canvas, t, anchor):
        """Draw the phrase on screen at time t; anchor = (x, y): centre-bottom for centred captions,
        top-left for side captions. Centred lines stay centred while they build: each new word
        rises into place and the line glides over to make room."""
        started = [g for g in self.groups if g[0]["s"] - 0.05 <= t]
        if not started:
            return
        g = started[-1]
        if t >= g[0]["leave"] + 0.22:
            return
        leave_k = 1 - ease((t - g[0]["leave"]) / 0.22) if t > g[0]["leave"] else 1.0
        lh = self.size * 1.22
        n = g[0]["lines"]
        ax, ay = anchor
        top = ay - n * lh if self.align == "center" else ay
        drop = (1 - leave_k) * 10
        ks = [ease((t - it["s"] + 0.04) / 0.2) for it in g]
        widths = {}
        for it, k in zip(g, ks):                                 # how wide each line is right now
            widths[it["line"]] = widths.get(it["line"], 0.0) + k * (it["w_px"] + self.space)
        widths = {li: max(0.0, w - self.space) for li, w in widths.items()}
        shown_lines = [li for li in widths if widths[li] > 1]
        if not shown_lines:
            return
        if self.backing:
            bw_ = max(widths[li] for li in shown_lines) + 68
            bh_ = (max(shown_lines) + 1) * lh + 28
            bx = ax - bw_ / 2 if self.align == "center" else ax - 34
            appear = ease((t - g[0]["s"] + 0.05) / 0.2)
            box = Image.new("RGBA", (int(bw_) + 2, int(bh_) + 2), (0, 0, 0, 0))
            ImageDraw.Draw(box).rounded_rectangle([0, 0, box.width - 1, box.height - 1], 24,
                                                  fill=(8, 10, 16, int(165 * appear * leave_k)))
            canvas.alpha_composite(box, (int(bx), int(top - 16 + drop)))
        for it, k in zip(g, ks):
            if k <= 0:
                continue
            p = (t - it["s"] + 0.04) / 0.2
            speaking = it["s"] - 0.04 <= t <= it["e"] + 0.12
            color = self.accent if it["key"] else (255, 255, 255) if speaking else (232, 235, 242)
            base, pad = self._word(it["w"], color)
            im = base
            scale = 1.0 + (0.12 * math.sin(min(1.0, p) * math.pi) if it["key"] else 0.0)   # a short pop
            if abs(scale - 1) > 0.01:
                im = im.resize((int(im.width * scale), int(im.height * scale)), Image.BILINEAR)
            a = k * leave_k
            if a < 0.999:
                im = _alpha(im, a)
            rise = (1 - k) * 16
            if self.align == "center":
                x = ax - widths[it["line"]] / 2 + it["lx"]
            else:
                x = ax + it["lx"]
            x -= pad                                              # grows from its left edge: never into the word before
            y = top + it["y"] + rise + drop - pad / 2 - (im.height - base.height) * 0.7
            canvas.alpha_composite(im, (int(x), int(y)))


# ------------------------------------------------------------------ backgrounds
def site_colors(shot, n=3):
    """The page's own strongest colours (ignoring white, black and greys)."""
    small = shot.convert("RGB").copy()
    small.thumbnail((160, 160))
    q = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:48]
    counts = sorted(q.getcolors(), reverse=True)
    out = []
    for cnt, idx in counts:
        c = tuple(pal[idx * 3: idx * 3 + 3])
        if max(c) - min(c) > 45 and 40 < lum(c) < 235:
            out.append(c)
        if len(out) >= n:
            break
    return out


def blurred_bg(shot, dark=0.52, tint=None, extra=1.14):
    """The page, huge and heavily blurred, deepened with soft glows of the site's own colours and
    the accent, darkened toward the edges. A little larger than the frame (room for the drift)."""
    bw, bh = int(W * extra), int(H * extra)
    small = shot.convert("RGB").copy()
    small.thumbnail((360, 360))
    r = max(bw / small.width, bh / small.height)
    small = small.resize((int(small.width * r / 6) + 1, int(small.height * r / 6) + 1), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(9))
    bg = small.resize((bw, bh), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    arr = np.asarray(bg).astype(np.float32)
    bright = arr.mean() / 255                                     # white pages: pull much further down
    arr = arr * (dark * (0.62 if bright > 0.7 else 1.0))
    yy, xx = np.mgrid[0:bh, 0:bw]
    cols = site_colors(shot) + ([tint] if tint is not None else [])
    rnd = random.Random(int(arr.sum()) % 997)
    for i, c in enumerate(cols[:3]):                              # big soft glows of the brand's colours
        gx, gy = rnd.uniform(0.15, 0.85) * bw, rnd.uniform(0.15, 0.85) * bh
        rad = rnd.uniform(0.38, 0.55) * bw
        g = np.exp(-(((xx - gx) ** 2 + (yy - gy) ** 2) / (2 * rad ** 2)))
        arr += np.array(c, np.float32) * g[..., None] * (0.42 if i == 0 else 0.3)
    d = np.sqrt(((xx - bw / 2) / (bw / 2)) ** 2 + ((yy - bh / 2) / (bh / 2)) ** 2)
    vig = np.clip(1.0 - 0.6 * d ** 1.7, 0.12, 1.0)
    arr = arr * vig[..., None]
    arr = arr * np.linspace(1.0, 0.78, bh)[:, None, None]         # a touch darker at the bottom (captions)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGBA")


def bg_frame(bg, t, seed=0.0):
    """Very subtle movement: a slow drift across the oversized blurred background."""
    ex, ey = bg.width - W, bg.height - H
    x = ex / 2 + ex / 2 * 0.9 * math.sin(t * 0.11 + seed)
    y = ey / 2 + ey / 2 * 0.9 * math.cos(t * 0.083 + seed * 1.3)
    return bg.crop((int(x), int(y), int(x) + W, int(y) + H))


# ------------------------------------------------------------------ the camera on the website
def camera_box(shot_w, shot_h, focus, p, kind, view_aspect):
    """The part of the screenshot to show at progress p (0..1): returns (x0, y0, x1, y1)."""
    base_w = shot_w
    base_h = base_w / view_aspect
    if base_h > shot_h:
        base_h = shot_h
        base_w = base_h * view_aspect
    if kind == "focus" and focus:
        fx = focus["x"] + focus["w"] / 2
        fy = focus["y"] + focus["h"] / 2
        z = 1.0 + 0.55 * ease_io(min(1.0, p * 1.6))              # push in toward the spot, then hold
        cw, ch = base_w / z, base_h / z
        cx = shot_w / 2 + (fx - shot_w / 2) * ease_io(min(1.0, p * 1.6))
        cy = base_h / 2 + (fy - base_h / 2) * ease_io(min(1.0, p * 1.6))
    elif kind == "scroll":
        z = 1.0
        cw, ch = base_w, base_h
        cx = shot_w / 2
        cy = ch / 2 + (shot_h - ch) * ease_io(p)
    elif kind == "pan":
        z = 1.12
        cw, ch = base_w / z, base_h / z
        cx = shot_w / 2 - (base_w - cw) / 2 + (base_w - cw) * ease_io(p)
        cy = base_h / 2
    else:                                                       # slow push-in
        z = 1.0 + 0.09 * ease_io(p)
        cw, ch = base_w / z, base_h / z
        cx, cy = shot_w / 2, base_h / 2
    x0 = min(max(0, cx - cw / 2), shot_w - cw)
    y0 = min(max(0, cy - ch / 2), shot_h - ch)
    return x0, y0, x0 + cw, y0 + ch


def view(shot, box, size):
    return shot.crop(tuple(int(round(v)) for v in box)).resize(size, Image.BILINEAR)


def perspective(img, tilt):
    """Turn a card a little in 3D (tilt > 0: right edge closer). Returns RGBA."""
    w, h = img.size
    k = abs(tilt)
    dy = h * k * 0.5
    if tilt > 0:
        dst = [(0, dy), (w, 0), (w, h), (0, h - dy)]
    else:
        dst = [(0, 0), (w, dy), (w, h - dy), (0, h)]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    A = []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    coeffs = np.linalg.solve(np.array(A, float), np.array([c for p in src for c in p], float))
    return img.transform((w, h), Image.PERSPECTIVE, tuple(coeffs), Image.BILINEAR)


# ------------------------------------------------------------------ one segment
class Seg:
    pass


def _browser_bar(w, domain, accent):
    h = 54
    bar = Image.new("RGBA", (w, h), (28, 30, 36, 255))
    d = ImageDraw.Draw(bar)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        d.ellipse([22 + i * 26, 20, 36 + i * 26, 34], fill=c)
    pw = min(560, w - 260)
    px = (w - pw) // 2
    d.rounded_rectangle([px, 11, px + pw, h - 11], 16, fill=(44, 47, 55))
    f = _font("Inter-Medium.otf", 19)
    d.text((px + pw / 2, h / 2), domain, font=f, fill=(210, 214, 222), anchor="mm")
    d.ellipse([px + 16, h / 2 - 5, px + 26, h / 2 + 5], fill=accent)
    return bar


def _phone(shot, scroll_p, height=900):
    """A phone mock-up with the mobile screenshot, scrolled by scroll_p."""
    sw = int(height * 0.462)
    sh = height
    scr_w, scr_h = sw - 28, sh - 28
    src = shot
    r = max(scr_w / src.width, scr_h / src.height)              # cover the screen
    pw, full_h = int(src.width * r + 0.5), int(src.height * r + 0.5)
    page = src.resize((pw, full_h), Image.BILINEAR)
    off = int((full_h - scr_h) * ease_io(scroll_p)) if full_h > scr_h else 0
    xo = (pw - scr_w) // 2
    screen = page.crop((xo, off, xo + scr_w, off + scr_h))
    body = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle([0, 0, sw - 1, sh - 1], 64, fill=(18, 18, 22), outline=(70, 72, 80), width=3)
    m = rounded_mask(scr_w, scr_h, 50)
    body.paste(screen.convert("RGB"), (14, 14), m)
    d.rounded_rectangle([sw / 2 - 62, 26, sw / 2 + 62, 58], 16, fill=(10, 10, 12))     # the island
    return body


def render_segment(job):
    """Render one segment to an mp4 (no audio). job: dict, see render()."""
    rnd = random.Random(job["seed"])
    shot = Image.open(job["shot"]).convert("RGB")
    others = [Image.open(p).convert("RGB") for p in job["others"]]
    lay = job["layout"]
    accent = tuple(job["accent"])
    n = int(round(job["frames"]))
    dur = n / FPS
    focus = job.get("focus")
    is_mobile = job["is_mobile"]
    bg = blurred_bg(shot if not is_mobile else (others[0] if others else shot), tint=accent,
                    dark=0.42 if lay == "spotlight" else 0.52)
    seed = rnd.uniform(0, 6)
    caps = None
    side = lay in ("split_left", "split_right", "phone")
    if job["words"]:
        if side:
            caps = Captions(job["words"], accent, job["brand"], size=66, max_w=640, align="left", backing=False,
                            max_lines=4)
        else:
            caps = Captions(job["words"], accent, job["brand"], size=58, max_w=1480, align="center")
    # card geometry
    if lay in ("center", "spotlight", "magnify"):
        cw, ch = 1400, 788
        cx, cy = (W - cw) // 2, 92
    elif lay == "browser":
        cw, ch = 1360, 765 - 54
        cx, cy = (W - cw) // 2, 86 + 54
    elif lay in ("tilt_left", "tilt_right"):
        cw, ch = 1360, 765
        cx, cy = (W - cw) // 2, 100
    elif lay == "split_left":
        cw, ch = 1120, 630
        cx, cy = 86, (H - ch) // 2 - 20
    elif lay == "split_right":
        cw, ch = 1120, 630
        cx, cy = W - 1120 - 86, (H - ch) // 2 - 20
    elif lay == "full_bleed":
        cw, ch = 1680, 945
        cx, cy = (W - cw) // 2, 40
    elif lay == "stack":
        cw, ch = 1280, 720
        cx, cy = (W - cw) // 2 + 60, 110
    elif lay == "duo":
        cw, ch = 1180, 664
        cx, cy = 110, 120
    elif lay == "scroll":
        cw, ch = 1120, 850
        cx, cy = (W - cw) // 2, 50
    else:                                                        # phone
        cw, ch = 0, 0
        cx, cy = 0, 0
    radius = 22
    mask = rounded_mask(cw, ch, radius) if cw else None
    shadow, sm = shadow_for(cw, ch, radius, glow=accent if lay in ("spotlight", "center", "full_bleed") else None) if cw else (None, 0)
    kind = "focus" if focus and lay not in ("scroll",) else ("scroll" if lay == "scroll" else rnd.choice(["push", "pan", "push"]))
    page = shot
    if lay == "scroll" and job.get("tall"):
        page = Image.open(job["tall"]).convert("RGB")
    bar = _browser_bar(cw, job["domain"], accent) if lay == "browser" else None
    # extras precomputed
    back_cards = []
    if lay == "stack":
        for k, o in enumerate(others[:2]):
            s = 0.9 - k * 0.07
            bw2, bh2 = int(cw * s), int(ch * s)
            im = o.resize((bw2, int(o.height * bw2 / o.width)), Image.BILINEAR).crop((0, 0, bw2, bh2))
            im = Image.blend(im, Image.new("RGB", im.size, (10, 12, 18)), 0.35 + 0.15 * k)
            back_cards.append((im, rounded_mask(bw2, bh2, radius), shadow_for(bw2, bh2, radius, blur=30)))
    duo_im = None
    if lay == "duo" and others:
        o = others[0]
        dw, dh = 560, 315
        duo_im = (o.resize((dw, int(o.height * dw / o.width)), Image.BILINEAR).crop((0, 0, dw, dh)),
                  rounded_mask(dw, dh, 18), shadow_for(dw, dh, 18, blur=28))
    label_font = _font("Inter-SemiBold.otf", 30)
    callout = (job.get("callout") or "").strip()
    co_font = _font("InterDisplay-ExtraBold.otf", 40)

    preview = job.get("preview")                    # a few stills instead of the video (for checking)
    proc = None if preview else subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-an", *X264, job["out"]], stdin=subprocess.PIPE)
    stills = []
    for f in (range(n) if not preview else [int(x * FPS) for x in preview]):
        t = f / FPS
        p = t / max(dur, 0.1)
        frame = bg_frame(bg, t + job["t0"], seed)
        if lay == "spotlight":                                   # a soft light behind the card
            light = Image.new("L", (W, H), 0)
            ImageDraw.Draw(light).ellipse([W / 2 - 900, 60 - 380, W / 2 + 900, 60 + 1100], fill=70)
            frame.paste((*accent, 255), (0, 0), light.filter(ImageFilter.GaussianBlur(160)))
        if lay == "phone":
            ph = _phone(shot, p * 0.9 + 0.05)
            float_y = 6 * math.sin(t * 1.1)
            sh_im, sm2 = shadow_for(ph.width, ph.height, 60, blur=40, glow=accent)
            px = 330
            py = (H - ph.height) // 2 - 50 + float_y
            frame.alpha_composite(sh_im, (int(px - sm2), int(py - sm2)))
            frame.alpha_composite(ph, (int(px), int(py)))
            if caps:
                caps.draw(frame, t + job.get("toff", 0.0), (int(px + ph.width + 150), 300))
        else:
            # the card's own motion: a gentle float, and a soft scale-in at the start
            intro_k = ease(t / 0.55) if (job["index"] > 0 or job.get("toff")) else 1.0
            fx = cx + (3 * math.sin(t * 0.9) if lay not in ("full_bleed",) else 0)
            fy = cy + 4 * math.sin(t * 0.7 + 1.0)
            aspect = cw / ch
            box = camera_box(page.width, page.height, focus if kind == "focus" else None, p, kind, aspect)
            card = view(page, box, (cw, ch))
            # back layers
            if lay == "stack":
                for k, (im, m, (sh, smk)) in reversed(list(enumerate(back_cards))):
                    ox = fx - 120 - k * 70 + 10 * math.sin(t * 0.5 + k)
                    oy = fy - 50 - k * 40
                    frame.alpha_composite(sh, (int(ox - smk), int(oy - smk)))
                    frame.paste(im, (int(ox), int(oy)), m)
            if lay == "duo" and duo_im:
                im, m, (sh, smk) = duo_im
                ox, oy = W - im.width - 110, 120 + 340 + 6 * math.sin(t * 0.8)
                frame.alpha_composite(sh, (int(ox - smk), int(oy - smk)))
                frame.paste(im, (int(ox), int(oy)), m)
            if lay in ("tilt_left", "tilt_right"):
                tilt = (0.09 if lay == "tilt_right" else -0.09) + 0.012 * math.sin(t * 0.6)
                rgba = card.convert("RGBA")
                rgba.putalpha(mask)
                warped = perspective(rgba, tilt)
                sh = Image.new("RGBA", (warped.width + 160, warped.height + 160), (0, 0, 0, 0))
                sh.paste((0, 0, 0, 160), (80, 100), warped.getchannel("A"))
                sh = sh.filter(ImageFilter.GaussianBlur(34))
                frame.alpha_composite(sh, (int(fx - 80), int(fy - 80)))
                frame.alpha_composite(warped, (int(fx), int(fy)))
            else:
                sc = 0.94 + 0.06 * intro_k
                if sc < 0.999:
                    cw2, ch2 = int(cw * sc), int(ch * sc)
                    card2 = card.resize((cw2, ch2), Image.BILINEAR)
                    m2 = mask.resize((cw2, ch2), Image.BILINEAR)
                    ox, oy = fx + (cw - cw2) / 2, fy + (ch - ch2) / 2
                    frame.alpha_composite(_alpha(shadow, intro_k), (int(ox - sm), int(oy - sm)))
                    if bar is not None:
                        frame.alpha_composite(bar.resize((cw2, int(bar.height * sc))), (int(ox), int(oy - bar.height * sc)))
                    frame.paste(card2, (int(ox), int(oy)), m2)
                else:
                    top = fy - (bar.height if bar is not None else 0)
                    frame.alpha_composite(shadow, (int(fx - sm), int(top - sm)))
                    if bar is not None:
                        bm = rounded_mask(cw, bar.height + 30, radius).crop((0, 0, cw, bar.height))
                        frame.paste(bar, (int(fx), int(top)), bm)
                        frame.paste(card, (int(fx), int(fy)), _bottom_round(mask))
                    else:
                        frame.paste(card, (int(fx), int(fy)), mask)
                # focus: a soft accent outline around the spot being talked about
                if kind == "focus" and focus and lay not in ("magnify",):
                    _focus_ring(frame, focus, box, (fx, fy, cw, ch), accent, p, dur)
                if lay == "magnify" and focus:
                    _magnifier(frame, page, focus, box, (fx, fy, cw, ch), accent, t)
            # segment label: a small chapter tag top-left
            if job.get("label") and lay != "full_bleed":
                _label(frame, job["label"], accent, t, dur, label_font)
            if callout and t > 1.0 and lay not in ("split_left", "split_right"):
                _callout(frame, callout, accent, t - 1.0, dur - 1.0, co_font, (fx, fy, cw, ch), lay)
            if caps:
                if side:
                    ax = cx + cw + 70 if lay == "split_left" else 86
                    caps.draw(frame, t + job.get("toff", 0.0), (ax, cy + 40))
                else:
                    caps.draw(frame, t + job.get("toff", 0.0), (W // 2, H - 52 if lay == "full_bleed" else H - 46))
        if job["index"] == 0 and not job.get("toff") and t < INTRO + 0.6:
            _intro(frame, job, t, accent)
        if preview:
            stills.append(frame.convert("RGB"))
            continue
        proc.stdin.write(frame.convert("RGB").tobytes())
    if preview:
        return stills
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError(f"ffmpeg failed on segment {job['index']}")
    return job["out"]


def _bottom_round(mask):
    """Mask for a card under a browser bar: square top corners, round bottom ones."""
    m = mask.copy()
    ImageDraw.Draw(m).rectangle([0, 0, m.width, 40], fill=255)
    return m


def _focus_ring(frame, focus, box, card, accent, p, dur):
    x0, y0, x1, y1 = box
    fx, fy, cw, ch = card
    sx, sy = cw / (x1 - x0), ch / (y1 - y0)
    rx0 = fx + (focus["x"] - x0) * sx - 14
    ry0 = fy + (focus["y"] - y0) * sy - 10
    rx1 = fx + (focus["x"] + focus["w"] - x0) * sx + 14
    ry1 = fy + (focus["y"] + focus["h"] - y0) * sy + 10
    rx0, ry0 = max(fx + 6, rx0), max(fy + 6, ry0)
    rx1, ry1 = min(fx + cw - 6, rx1), min(fy + ch - 6, ry1)
    if rx1 - rx0 < 20 or ry1 - ry0 < 12:
        return
    k = ease((p * dur - 0.9) / 0.5)
    if k <= 0:
        return
    pulse = 0.75 + 0.25 * math.sin(p * dur * 3.0)
    layer = Image.new("RGBA", (int(rx1 - rx0) + 40, int(ry1 - ry0) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([20, 20, layer.width - 21, layer.height - 21], 14, outline=(*accent, int(230 * k)), width=4)
    glow = layer.filter(ImageFilter.GaussianBlur(8))
    frame.alpha_composite(_alpha(glow, pulse * k), (int(rx0 - 20), int(ry0 - 20)))
    frame.alpha_composite(layer, (int(rx0 - 20), int(ry0 - 20)))


def _magnifier(frame, page, focus, box, card, accent, t):
    """A round lens showing the spot at 2.2x, floating beside it."""
    x0, y0, x1, y1 = box
    fx, fy, cw, ch = card
    sx = cw / (x1 - x0)
    k = ease((t - 0.8) / 0.5)
    if k <= 0:
        return
    R = int(190 * back(min(1, (t - 0.8) / 0.5)))
    if R < 10:
        return
    cxp = focus["x"] + focus["w"] / 2
    cyp = focus["y"] + focus["h"] / 2
    zoom = 2.2
    src_r = R / (sx * zoom)
    crop = page.crop((int(cxp - src_r), int(cyp - src_r), int(cxp + src_r), int(cyp + src_r))).resize((2 * R, 2 * R), Image.BICUBIC)
    m = Image.new("L", (2 * R, 2 * R), 0)
    ImageDraw.Draw(m).ellipse([0, 0, 2 * R - 1, 2 * R - 1], fill=255)
    spot_x = fx + (cxp - x0) * sx
    spot_y = fy + (cyp - y0) * sx
    lx = spot_x + (260 if spot_x < W / 2 else -260)
    ly = min(H - R - 160, max(R + 30, spot_y - 140))
    lx = min(W - R - 30, max(R + 30, lx))
    sh = Image.new("RGBA", (2 * R + 120, 2 * R + 120), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([60, 76, 60 + 2 * R, 76 + 2 * R], fill=(0, 0, 0, 170))
    frame.alpha_composite(sh.filter(ImageFilter.GaussianBlur(24)), (int(lx - R - 60), int(ly - R - 60)))
    d = ImageDraw.Draw(frame)
    d.line([(spot_x, spot_y), (lx, ly)], fill=(*accent, 200), width=3)
    frame.paste(crop, (int(lx - R), int(ly - R)), m)
    ring = Image.new("RGBA", (2 * R + 16, 2 * R + 16), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([4, 4, 2 * R + 11, 2 * R + 11], outline=(255, 255, 255, 235), width=7)
    ImageDraw.Draw(ring).ellipse([0, 0, 2 * R + 15, 2 * R + 15], outline=(*accent, 255), width=4)
    frame.alpha_composite(ring, (int(lx - R - 8), int(ly - R - 8)))
    d.ellipse([spot_x - 7, spot_y - 7, spot_x + 7, spot_y + 7], fill=accent)


def _label(frame, text, accent, t, dur, f):
    """Chapter tag: slides in at the start, leaves after a few seconds."""
    k_in = ease((t - 0.25) / 0.45)
    k_out = 1 - ease((t - 3.6) / 0.4)
    k = min(k_in, k_out)
    if k <= 0.01:
        return
    text = text.upper()
    tw = f.getlength(text)
    w, h = int(tw + 76), 62
    tag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tag)
    d.rounded_rectangle([0, 0, w - 1, h - 1], 27, fill=(12, 14, 20, 175), outline=(255, 255, 255, 40), width=1)
    d.ellipse([22, h / 2 - 6, 34, h / 2 + 6], fill=accent)
    d.text((46, h / 2), text, font=f, fill=(240, 242, 248), anchor="lm")
    frame.alpha_composite(_alpha(tag, k), (int(48 - (1 - k) * 30), 26))


def _callout(frame, text, accent, t, dur, f, card, lay):
    """The key fact: a glass card that pops in by the website's corner."""
    k = back(min(1.0, t / 0.45)) if t < 0.45 else 1.0
    out = 1 - ease((t - min(dur - 0.6, 5.5)) / 0.4)
    a = min(1.0, t / 0.25) * out
    if a <= 0.01:
        return
    tw = f.getlength(text)
    w, h = int(tw + 64), 84
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], 22, fill=(255, 255, 255, 238))
    d.rounded_rectangle([0, 0, 10, h - 1], 5, fill=accent)
    d.text((w / 2 + 4, h / 2), text, font=f, fill=(14, 16, 22), anchor="mm")
    sc = max(0.3, k)
    im2 = im.resize((max(1, int(w * sc)), max(1, int(h * sc))), Image.BILINEAR)
    fx, fy, cw, ch = card
    x = fx + cw - w * 0.75
    y = fy + ch - h * 0.4
    if lay in ("tilt_left",):
        x = fx + cw - w * 0.9
    x = min(W - w - 30, x)
    y = min(H - h - 150, y)
    sh = Image.new("RGBA", (w + 80, h + 80), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([40, 52, 40 + w, 52 + h], 22, fill=(0, 0, 0, 150))
    frame.alpha_composite(_alpha(sh.filter(ImageFilter.GaussianBlur(18)), a), (int(x - 40), int(y - 40)))
    frame.alpha_composite(_alpha(im2, a), (int(x + (w - im2.width) / 2), int(y + (h - im2.height) / 2)))


def _intro(frame, job, t, accent):
    """The title over the first seconds: logo, brand name, 'Honest review'; then it lifts away."""
    k_in = ease(t / 0.6)
    k_out = 1 - ease((t - (INTRO - 0.5)) / 0.5)
    k = min(k_in, k_out)
    if k <= 0.01:
        return
    veil = Image.new("RGBA", (W, H), (6, 8, 12, int(185 * k)))
    frame.alpha_composite(veil)
    brand = job["brand"]
    f = _font("InterDisplay-Black.otf", 150 if len(brand) < 12 else 110)
    lift = (1 - k_out) * -40 + (1 - k_in) * 30
    cy = H / 2 - 30 + lift
    logo = job.get("logo")
    if logo and Path(logo).exists():
        try:
            from .visuals import load_logo
            lg = load_logo(Path(logo))
            lg.thumbnail((150, 150))
            frame.alpha_composite(_alpha(lg, k), (int(W / 2 - lg.width / 2), int(cy - 200 - lg.height / 2)))
        except Exception:
            pass
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((W / 2, cy), brand, font=f, fill=(255, 255, 255, 255), anchor="mm")
    sub = job.get("kicker") or "HONEST REVIEW"
    sf = _font("Inter-SemiBold.otf", 34)
    spacing = 9
    sw = sum(sf.getlength(c) + spacing for c in sub) - spacing
    x = W / 2 - sw / 2
    for c in sub:
        ld.text((x, cy + 120), c, font=sf, fill=(*accent, 255), anchor="lm")
        x += sf.getlength(c) + spacing
    lw = 140 * ease((t - 0.3) / 0.6)
    ld.rounded_rectangle([W / 2 - lw, cy + 168, W / 2 + lw, cy + 173], 3, fill=(*accent, 255))
    frame.alpha_composite(_alpha(layer, k))


# ------------------------------------------------------------------ device scenes (owner's mock-ups)
MOCK = config.ASSETS_DIR / "mockups"


def _quad_coeffs(dst, src):
    """PIL PERSPECTIVE coefficients mapping output points dst[i] to input points src[i]."""
    A, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return tuple(np.linalg.solve(np.array(A, float), np.array(b, float)))


def _cover(img, aspect, top=False):
    """Crop img to the given width/height ratio (centre, or the top for tall pages)."""
    w, h = img.size
    if w / h > aspect:
        nw = int(h * aspect)
        return img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = int(w / aspect)
    y0 = 0 if top else (h - nh) // 2
    return img.crop((0, y0, w, y0 + nh))


def _onto_screen(base, content, name, top=False):
    """Put the content into the device's white screen: perspective-matched to the measured corners,
    clipped by the screen mask (the notch / Dynamic Island stay on top). Returns (image, content colour)."""
    import json as _json
    meta = _json.loads((MOCK / "mockups.json").read_text())[name]
    c = meta["corners"]
    sw = math.dist(c[0], c[1])
    sh = math.dist(c[1], c[2])
    src = _cover(content.convert("RGB"), sw / sh, top=top)
    k = 2.0 if src.width < sw else 1.0
    if k > 1:                                                   # small source: upscale first (sharper)
        src = src.resize((int(src.width * k), int(src.height * k)), Image.LANCZOS)
    rect = [(0, 0), (src.width, 0), (src.width, src.height), (0, src.height)]
    # the content reaches a few pixels past the screen's edge and the mask is grown to match, so it
    # meets the black bezel directly: no sliver of the white placeholder screen can show
    mx, my = sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4
    grow = 9.0
    cg = []
    for x, y in c:
        dx, dy = x - mx, y - my
        L = math.hypot(dx, dy) or 1.0
        cg.append((x + dx / L * grow * 1.4, y + dy / L * grow * 1.4))
    warped = src.transform(base.size, Image.PERSPECTIVE, _quad_coeffs(cg, rect), Image.BICUBIC)
    mask = Image.open(MOCK / f"{name}_screen.png").convert("L")
    mask = mask.point(lambda v: 255 if v > 30 else 0).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(1.2))
    out = base.copy()
    out.paste(warped, (0, 0), mask)
    small = src.resize((32, 18))
    avg = tuple(int(v) for v in np.asarray(small).reshape(-1, 3).mean(0))
    return out, (avg, c, src)


def _screen_light(desk, c, src):
    """Night scene: the screen lights the keyboard and the hinge in the colours on screen (a soft,
    blurred reflection of the content) instead of plain white."""
    W2, H2 = desk.size
    x0, x1 = min(p[0] for p in c), max(p[0] for p in c)
    yb = max(c[2][1], c[3][1])
    sh = yb - min(c[0][1], c[1][1])
    region_h = int(sh * 0.42)
    refl = src.transpose(Image.FLIP_TOP_BOTTOM).resize((int(x1 - x0 + sh * 0.5), region_h), Image.BILINEAR)
    refl = refl.filter(ImageFilter.GaussianBlur(region_h * 0.12))
    tint = np.asarray(refl).astype(np.float32) / 255
    lumv = tint.mean(-1, keepdims=True).mean() + 1e-3
    tint = 0.55 + 0.45 * tint / max(lumv, 0.35)                 # colour, about the same brightness
    fall = np.linspace(1.0, 0.0, region_h)[:, None, None] ** 1.6
    xx = np.linspace(-1, 1, refl.width)[None, :, None]
    fall = fall * np.clip(1.15 - xx ** 2, 0, 1)
    rgba = np.asarray(desk).astype(np.float32)
    ox = int(x0 - sh * 0.25)
    oy = int(yb)
    ys, ye = oy, min(H2, oy + region_h)
    xs, xe = max(0, ox), min(W2, ox + refl.width)
    patch = rgba[ys:ye, xs:xe, :3]
    t = tint[: ye - ys, xs - ox: xe - ox]
    f = fall[: ye - ys, xs - ox: xe - ox] * 0.85
    lit = patch.mean(-1, keepdims=True) > 70                    # only where the screen's light falls
    rgba[ys:ye, xs:xe, :3] = np.where(lit, patch * (1 - f + f * t), patch)
    return Image.fromarray(rgba.clip(0, 255).astype(np.uint8), "RGBA")


def _affine(img, scale, angle_deg, center, out_size, src_scale):
    """Zoom (and turn) img about `center` (in img pixels) into an out_size frame. src_scale: how many
    img pixels make one output pixel at scale 1."""
    a = math.radians(angle_deg)
    k = src_scale / scale
    cs, sn = math.cos(a) * k, math.sin(a) * k
    ow, oh = out_size
    cx, cy = center
    ox, oy = cx / src_scale, cy / src_scale                    # where the centre sits in the output
    # output (u, v) -> input (x, y)
    A, B = cs, -sn
    D, E = sn, cs
    C = cx - A * ox - B * oy
    F = cy - D * ox - E * oy
    return img.transform(out_size, Image.AFFINE, (A, B, C, D, E, F), Image.BICUBIC)


def render_scene(job):
    """The MacBook or iPhone mock-up scene for one segment (or a preview)."""
    scene = job["scene"]                                         # macbook_night / macbook_day / phone_day / phone_night
    n = int(round(job["frames"]))
    dur = n / FPS
    content = Image.open(job["shot"]).convert("RGB")
    accent = tuple(job["accent"])
    caps = Captions(job["words"], accent, job["brand"], size=58, max_w=1480, align="center") if job["words"] else None
    if scene.startswith("macbook"):
        wall = Image.open(MOCK / f"{scene}_wall.jpg").convert("RGB")
        desk = Image.open(MOCK / f"{scene}_desk.png").convert("RGBA")
        desk, (avg, c, src) = _onto_screen(desk, content, f"{scene}_desk")
        if "night" in scene:
            desk = _screen_light(desk, c, src)
        center = (sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4)
        layers = (wall, desk)
    else:
        base = Image.open(MOCK / f"{scene}.jpg").convert("RGB")
        img, (avg, c, src) = _onto_screen(base, content, scene, top=True)
        center = (sum(p[0] for p in c) / 4, sum(p[1] for p in c) / 4)
        layers = (img,)
    src_scale = layers[0].width / W
    preview = job.get("preview")
    proc = None if preview else subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-an", *X264, job["out"]], stdin=subprocess.PIPE)
    stills = []
    label_font = _font("Inter-SemiBold.otf", 30)
    for f in (range(n) if not preview else [int(x * FPS) for x in preview]):
        t = f / FPS
        p = ease_io(t / max(job.get("move", dur), 0.1))          # the move ends as the scene hands over
        if scene.startswith("macbook"):
            # a slow dolly-in: the desk (closer) grows faster than the wall, which softens with depth
            wall, desk = layers
            bz = 1.0 + 0.12 * p
            r = 7.5 * p
            if r > 0.8:
                small = _affine(wall, bz, 0, center, (W // 2, H // 2), src_scale * 2)
                frame = small.filter(ImageFilter.GaussianBlur(r / 2)).resize((W, H), Image.BILINEAR).convert("RGBA")
            else:
                frame = _affine(wall, bz, 0, center, (W, H), src_scale).convert("RGBA")
            frame.alpha_composite(_affine(desk, 1.0 + 0.24 * p, 0, center, (W, H), src_scale))
        else:
            # the phone: a super slow push-in with the slightest turn
            frame = _affine(layers[0], 1.0 + 0.08 * p, -1.4 * p, center, (W, H), src_scale).convert("RGBA")
        if job["index"] == 0:
            _brand_tag(frame, job, t, accent)
        elif job.get("label"):
            _label(frame, job["label"], accent, t, dur, label_font)
        if caps:
            caps.draw(frame, t, (W // 2, H - 46))
        if preview:
            stills.append(frame.convert("RGB"))
            continue
        proc.stdin.write(frame.convert("RGB").tobytes())
    if preview:
        return stills
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError(f"ffmpeg failed on the {scene} scene")
    return job["out"]


def _brand_tag(frame, job, t, accent):
    """Opening title for the device scene: a glass tag (logo, brand, kicker) top-left, no veil."""
    k = min(ease((t - 0.3) / 0.6), 1 - ease((t - 4.2) / 0.5))
    if k <= 0.01:
        return
    big = _font("InterDisplay-Black.otf", 64)
    small = _font("Inter-SemiBold.otf", 26)
    brand = job["brand"]
    kicker = job.get("kicker") or "HONEST REVIEW"
    lg = None
    if job.get("logo") and Path(job["logo"]).exists():
        try:
            from .visuals import load_logo
            lg = load_logo(Path(job["logo"]))
            lg.thumbnail((84, 84))
        except Exception:
            lg = None
    tw = max(big.getlength(brand), small.getlength(kicker) * 1.25)
    w = int(tw + 80 + (110 if lg else 0))
    h = 150
    tag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tag)
    d.rounded_rectangle([0, 0, w - 1, h - 1], 30, fill=(10, 12, 18, 190), outline=(255, 255, 255, 50), width=2)
    x = 40
    if lg:
        tag.alpha_composite(lg, (x, (h - lg.height) // 2))
        x += 110
    d.text((x, 60), brand, font=big, fill=(255, 255, 255), anchor="lm")
    sp = 5
    xx = x + 2
    for ch in kicker:
        d.text((xx, 112), ch, font=small, fill=accent, anchor="lm")
        xx += small.getlength(ch) + sp
    frame.alpha_composite(_alpha(tag, k), (int(56 - (1 - k) * 40), 48))


# ------------------------------------------------------------------ outro: the verdict
def outro_clip(job):
    shot = Image.open(job["shot"]).convert("RGB")
    accent = tuple(job["accent"])
    bg = blurred_bg(shot, dark=0.4, tint=accent)
    n = int(OUTRO * FPS)
    score = job.get("score")
    verdict = job.get("verdict") or ""
    brand = job["brand"]
    big = _font("InterDisplay-Black.otf", 92)
    mid = _font("InterDisplay-ExtraBold.otf", 50)
    small = _font("Inter-SemiBold.otf", 30)
    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-an", *X264, job["out"]], stdin=subprocess.PIPE)
    vcol = (60, 220, 130) if verdict.lower().startswith("worth it") and "some" not in verdict.lower() else \
        (255, 196, 60) if "some" in verdict.lower() else (255, 90, 90)
    for f in range(n):
        t = f / FPS
        frame = bg_frame(bg, t, 1.0)
        k = ease(t / 0.7)
        panel_w, panel_h = 1180, 560
        px, py = (W - panel_w) / 2, (H - panel_h) / 2 - 40 + (1 - k) * 40
        glass = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
        ImageDraw.Draw(glass).rounded_rectangle([0, 0, panel_w - 1, panel_h - 1], 36, fill=(14, 16, 24, int(200 * k)),
                                                outline=(255, 255, 255, int(40 * k)), width=2)
        sh, sm = shadow_for(panel_w, panel_h, 36, blur=40)
        frame.alpha_composite(_alpha(sh, k), (int(px - sm), int(py - sm)))
        frame.alpha_composite(glass, (int(px), int(py)))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((W / 2, py + 90), job.get("label") or "THE VERDICT", font=small, fill=(*accent, 255), anchor="mm")
        d.text((W / 2, py + 175), brand, font=big, fill=(255, 255, 255, 255), anchor="mm")
        # the score ring draws itself
        if isinstance(score, (int, float)):
            rk = ease((t - 0.5) / 1.2)
            r = 96
            cxr, cyr = W / 2 - 330, py + 380
            d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], outline=(255, 255, 255, 40), width=14)
            d.arc([cxr - r, cyr - r, cxr + r, cyr + r], -90, -90 + 360 * (score / 10) * rk, fill=(*vcol, 255), width=14)
            d.text((cxr, cyr), f"{score * rk:.1f}", font=mid, fill=(255, 255, 255, 255), anchor="mm")
            vx = W / 2 - 190
        else:
            vx = W / 2
        vk = ease((t - 1.1) / 0.5)
        d.text((vx if isinstance(score, (int, float)) else W / 2, py + 380 + (1 - vk) * 20), verdict,
               font=mid, fill=(*vcol, int(255 * vk)), anchor="lm" if isinstance(score, (int, float)) else "mm")
        frame.alpha_composite(_alpha(layer, k))
        proc.stdin.write(frame.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("ffmpeg failed on the outro")
    return job["out"]


# ------------------------------------------------------------------ planning
def choose_layouts(segs, seed, has_mobile, n_shots):
    """One layout per segment: never the same twice in a row, each used before any repeats,
    and only where it fits."""
    rnd = random.Random(seed + "-layouts")
    pool = LAYOUTS[:]
    rnd.shuffle(pool)
    out, prev = [], None
    for s in segs:
        fits = []
        for lay in pool + LAYOUTS:
            if lay == prev or lay in fits:
                continue
            if lay == "phone" and s["screenshot"] != "mobile.png":
                continue
            if s["screenshot"] == "mobile.png" and lay != "phone":
                continue
            if lay in ("magnify", "spotlight") and not s.get("focus_box"):
                continue
            if lay in ("stack", "duo") and n_shots < 3:
                continue
            if lay == "scroll" and not s["screenshot"].startswith("home_"):
                continue
            if lay == "browser" and s["screenshot"].startswith("story"):   # a user's post isn't the site: no URL bar
                continue
            fits.append(lay)
        lay = fits[0] if fits else "center"
        if lay in pool:
            pool.remove(lay)
        if not pool:
            pool = LAYOUTS[:]
            rnd.shuffle(pool)
        out.append(lay)
        prev = lay
    return out


def stitch_home(out_dir, shots, work):
    """The homepage screenshots (taken while scrolling) stacked into one tall page for the scroll layout."""
    homes = [s["file"] for s in shots if s["file"].startswith("home_")]
    if len(homes) < 2:
        return None
    ims = [Image.open(out_dir / h).convert("RGB") for h in homes[:4]]
    w = ims[0].width
    tall = Image.new("RGB", (w, sum(i.height for i in ims)))
    y = 0
    for i in ims:
        tall.paste(i, (0, y))
        y += i.height
    tall.thumbnail((1920, 1080 * 4))
    p = work / "home_tall.jpg"
    tall.save(p, quality=92)
    return p


# ------------------------------------------------------------------ the whole video
def render(data, info, out_dir: Path, theme: dict) -> Path:
    from .tts import duration, word_times
    from .video import _music_track, _sfx_track, _run
    work = out_dir / "render"
    work.mkdir(exist_ok=True)
    segs = data["segments"]
    accent = vivid(theme.get("accent") or (90, 170, 255))
    brand = data.get("brand") or info["domain"]
    shots = info["screenshots"]
    seed = theme.get("seed") or info["domain"]
    lays = choose_layouts(segs, seed, (out_dir / "mobile.png").exists(), len(shots))
    # the opening: the owner's MacBook scene, then the iPhone (day or night, picked per video)
    tod = "night" if random.Random(f"{seed}-tod").random() < 0.5 else "day"
    scenes = {}
    if (MOCK / "mockups.json").exists() and segs:
        scenes[0] = (f"macbook_{tod}", segs[0]["screenshot"] if segs[0]["screenshot"] != "mobile.png"
                     else (shots[0]["file"] if shots else segs[0]["screenshot"]))
        if len(segs) > 2 and (out_dir / "mobile.png").exists():
            scenes[1] = (f"phone_{tod}", "mobile.png")
    SCENE_LEN = {"macbook": 5.0, "phone": 4.5}                    # then the segment carries on in a layout
    tall = stitch_home(out_dir, shots, work)
    theme["music"] = "chords" if config.MUSIC in ("auto", "chords") else config.MUSIC
    theme.setdefault("sfx", "soft" if config.SFX else "off")
    shot_files = [out_dir / s["file"] for s in shots if s["file"] != "mobile.png"]

    jobs, t0 = [], 0.0
    pieces = []                                                 # (job, seconds on screen)
    for i, seg in enumerate(segs):
        d_i = round((seg["duration"] + PAD) * FPS) / FPS
        seg["clip_duration"] = d_i
        words = align_words(seg["text"], word_times(Path(seg["audio"]), seg["text"]))
        shot = out_dir / seg["screenshot"]
        others = [str(p) for p in shot_files if p != shot]
        rnd = random.Random(f"{seed}-{i}")
        rnd.shuffle(others)
        base = {"index": i, "shot": str(shot), "others": others[:2], "layout": lays[i], "accent": accent,
                "focus": seg.get("focus_box"), "words": words, "brand": brand,
                "domain": info["domain"], "label": seg.get("caption", ""), "callout": seg.get("callout", ""),
                "is_mobile": seg["screenshot"] == "mobile.png", "tall": str(tall) if tall else None,
                "kicker": "WHAT HAPPENED?" if data.get("kind") == "risk" else "HONEST REVIEW",
                "seed": f"{seed}-{i}", "t0": t0, "logo": str(out_dir / info["logo"]) if info.get("logo") else None}
        parts = []
        if i in scenes:
            sc, sc_shot = scenes[i]
            slen = SCENE_LEN[sc.split("_")[0]]
            slen = d_i if d_i < slen + 2.5 else slen               # short segment: the scene fills it
            parts.append(dict(base, scene=sc, shot=str(out_dir / sc_shot), move=slen, toff=0.0, d=slen,
                              layout=sc, out=str(work / f"clip_{i:02d}a.mp4")))
            if slen < d_i:
                parts.append(dict(base, toff=slen, d=d_i - slen, label="", out=str(work / f"clip_{i:02d}b.mp4")))
        else:
            parts.append(dict(base, toff=0.0, d=d_i, out=str(work / f"clip_{i:02d}.mp4")))
        for pj in parts:
            pj["frames"] = int(round((pj["d"] + T) * FPS))     # + the overlap with the next piece
            jobs.append(pj)
            pieces.append(pj)
        t0 += d_i
    outro_job = {"shot": str(shot_files[0] if shot_files else out_dir / segs[0]["screenshot"]), "accent": accent,
                 "brand": brand, "score": data.get("score") if data.get("kind") != "risk" else None,
                 "verdict": data.get("verdict") or ("Know the risks" if data.get("kind") == "risk" else ""),
                 "label": "THE TAKEAWAY" if data.get("kind") == "risk" else "THE VERDICT",
                 "out": str(work / "outro.mp4")}
    workers = max(1, min(len(jobs), (os.cpu_count() or 2)))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(render_scene if j.get("scene") else render_segment, j) for j in jobs] + \
            [ex.submit(outro_clip, outro_job)]
        for k, fu in enumerate(futs):
            fu.result()
            if k < len(jobs):
                print(f"   clip {k + 1}/{len(jobs)} (segment {jobs[k]['index'] + 1}, {jobs[k]['d']:.1f}s, "
                      f"{jobs[k].get('scene') or jobs[k]['layout']})")

    # ---- assemble: soft transitions, narration, quiet chords, a few gentle sound effects
    clips = [Path(j["out"]) for j in jobs] + [Path(outro_job["out"])]
    content = sum(s["clip_duration"] for s in segs)
    total_len = content + OUTRO
    args, fl, events = [], [], [(0.15, "whoosh")]
    for c in clips:
        args += ["-i", str(c)]
    for k in range(len(clips)):
        fl.append(f"[{k}:v]settb=AVTB,fps={FPS},format=yuv420p[c{k}]")
    acc, prev = pieces[0]["d"], "c0"
    for k in range(1, len(clips)):
        out = "vx" if k == len(clips) - 1 else f"x{k}"
        same_seg = k < len(pieces) and pieces[k]["index"] == pieces[k - 1]["index"]
        name = "fade" if (k == len(clips) - 1 or same_seg) else TRANSITIONS[(k - 1) % len(TRANSITIONS)]
        fl.append(f"[{prev}][c{k}]xfade=transition={name}:duration={T}:offset={acc:.3f}[{out}]")
        if not same_seg:
            events.append((acc, "whoosh"))
        acc += pieces[k]["d"] if k < len(pieces) else 0
        prev = out
    a0 = len(clips)
    for s in segs:
        args += ["-i", s["audio"]]
    for j, s in enumerate(segs):
        fl.append(f"[{a0 + j}:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{s['clip_duration']:.3f}[a{j}]")
    fl.append("".join(f"[a{j}]" for j in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1,"
              f"apad=whole_dur={total_len:.3f}[narr]")
    mixes = ["narr"]
    nxt = a0 + len(segs)
    music = _music_track(theme, total_len, work)
    if music is not None:
        loop = ["-stream_loop", "-1"] if music.suffix == ".mp3" else []
        args += [*loop, "-i", str(music)]
        fl.append("[narr]asplit=2[narr_m][narr_sc]")
        fl.append(f"[{nxt}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.24[mus];"
                  f"[mus][narr_sc]sidechaincompress=threshold=0.02:ratio=3:attack=40:release=700[duck]")
        mixes = ["narr_m", "duck"]
        nxt += 1
    sfx = _sfx_track(theme, events, total_len, work)
    if sfx is not None:
        args += ["-i", str(sfx)]
        fl.append(f"[{nxt}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.16[fx]")
        mixes.append("fx")
    fl.append("".join(f"[{m}]" for m in mixes) + f"amix=inputs={len(mixes)}:duration=first:normalize=0[pre]"
              if len(mixes) > 1 else "[narr]anull[pre]")
    fl.append("[pre]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[mix]")
    final = out_dir / "video.mp4"
    _run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex", ";".join(fl), "-map", "[vx]", "-map", "[mix]",
          "-t", f"{total_len:.3f}", *X264, "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
          "-movflags", "+faststart", str(final)])
    theme["layouts"] = [scenes[i][0] + "+" + lays[i] if i in scenes else lays[i] for i in range(len(segs))]
    print(f"   video ready: {duration(final):.0f}s · layouts {', '.join(theme['layouts'])} · music {theme['music']}")
    return final
