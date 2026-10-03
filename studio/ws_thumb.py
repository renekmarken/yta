"""White Screen videos, part 4: three 16:9 thumbnails per video, in the channel's own look.

Modelled on the channel's thumbnails: dark, high-contrast, almost no text (1-3 big words picked by
the script writer), the masked blue-hoodie character big on one half when there is one, and
YouTube's own visual language (the sad red YouTube face for [Private Video]-style titles, the
"0 Comments" panel, the like bar, "Delete your channel?").

Styles:
  error      the big sad/locked/glitched YouTube face on black, small "This video is private." line
  ui         a YouTube-interface mock-up, the key number ringed in red with an arrow
  character  the character on one half, 1-3 huge words (white + red, black outline) on the other
  headline   a huge phrase across the top ("24 HOURS LEFT..."), the character below
  icon       one big symbol (trash, hourglass, lock...) and the phrase
  white      white background, big black words with a red strike or arrow ("1,000,000 VIEWS")
"""
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import config
from . import ws_assets as A

TW, TH = 1280, 720
RED, WHITE, INK = (255, 28, 36), (255, 255, 255), (8, 8, 8)

STYLES_FOR = {   # format of the title -> styles that suit it, best first
    "error": ["error", "error_glow", "ui", "character"],
    "count": ["ui", "character", "white", "headline"],
    "deadline": ["headline", "character", "icon", "ui"],
    "goal": ["white", "character", "headline", "icon"],
    "reveal": ["character", "headline", "icon"],
    "dare": ["character", "headline", "icon", "white"],
    "pin": ["ui", "character", "headline"],
    "only": ["character", "headline", "icon", "ui"],
}
UI_FOR = {"error": ["private_player", "video_unavailable"], "count": ["comments_zero", "likes_zero", "likes_and_comments_zero", "view_count"],
          "deadline": ["delete_video"], "pin": ["pinned_comment"], "goal": ["comments_zero", "view_count"],
          "only": ["comments_zero"], "dare": ["comments_zero"], "reveal": ["likes_zero"]}


# ------------------------------------------------------------------ backgrounds
SCHEMES = {   # base, glow, ray colour -- the channel's look is black: every scheme is black with a faint glow
    "black": ((2, 2, 3), (34, 34, 40), (120, 120, 132)),
    "red": ((2, 2, 2), (34, 4, 6), (150, 40, 40)),          # error videos: black with a faint red glow
}
SCHEME_FOR = {"error": ["red", "black"]}


def _dark(glow=(60, 60, 64), center=(0.5, 0.45), base=(6, 6, 8)):
    bg = Image.new("RGB", (TW, TH), base)
    g = Image.radial_gradient("L").resize((int(TW * 1.6), int(TH * 1.9)))
    cx, cy = int(TW * center[0]), int(TH * center[1])
    layer = Image.new("RGB", (TW, TH), glow)
    mask = Image.new("L", (TW, TH), 0)
    inv = g.point(lambda v: 255 - v)
    mask.paste(inv, (cx - g.width // 2, cy - g.height // 2))
    return Image.composite(layer, bg, mask).convert("RGBA")


def _glow(canvas, box, color, blur=60, alpha=170):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([int(v) for v in box], 40, fill=(*color, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _backdrop(scheme, focus=(0.5, 0.5), rays=True):
    """A filled background: deep colour, a strong glow behind the subject, soft sunburst rays, vignette."""
    base, glow, ray = SCHEMES.get(scheme, SCHEMES["black"])
    bg = _dark(glow, focus, base)
    fx, fy = TW * focus[0], TH * focus[1]
    if rays:
        layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        n, R = 18, TW * 1.5
        for i in range(n):
            a0 = 2 * math.pi * i / n
            a1 = a0 + math.pi / n
            d.polygon([(fx, fy), (fx + R * math.cos(a0), fy + R * math.sin(a0)),
                       (fx + R * math.cos(a1), fy + R * math.sin(a1))], fill=(*ray, 26))
        fade = Image.radial_gradient("L").resize((int(TW * 2.2), int(TW * 2.2)))
        m = Image.new("L", (TW, TH), 0)
        m.paste(fade.point(lambda v: max(0, 255 - v * 2)), (int(fx - fade.width / 2), int(fy - fade.height / 2)))
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), m.point(lambda v: min(255, v * 3))))
        bg.alpha_composite(layer)
    # vignette: the corners darker, so the subject pops
    vig = Image.radial_gradient("L").resize((int(TW * 1.25), int(TH * 1.45)))
    v = Image.new("L", (TW, TH), 255)
    v.paste(vig, ((TW - vig.width) // 2, (TH - vig.height) // 2))
    dark = Image.new("RGBA", (TW, TH), (0, 0, 0, 255))
    dark.putalpha(v.point(lambda x: int(max(0, x - 120) * 1.1)))
    bg.alpha_composite(dark)
    return bg


def _white_backdrop(focus=(0.5, 0.5)):
    bg = Image.new("RGBA", (TW, TH), (255, 255, 255, 255))
    layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fx, fy, n, R = TW * focus[0], TH * focus[1], 22, TW * 1.5
    for i in range(n):
        a0 = 2 * math.pi * i / n
        d.polygon([(fx, fy), (fx + R * math.cos(a0), fy + R * math.sin(a0)),
                   (fx + R * math.cos(a0 + math.pi / n), fy + R * math.sin(a0 + math.pi / n))], fill=(0, 0, 0, 10))
    bg.alpha_composite(layer)
    return bg
# ------------------------------------------------------------------ type
def _anton(size):
    return ImageFont.truetype(str(config.ASSETS_DIR / "fonts" / "Anton-Regular.ttf"), int(size))


def _fit_anton(text, max_w, max_h, start=330):
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    size = start
    while size > 30:
        f = _anton(size)
        bb = d.textbbox((0, 0), text, font=f, stroke_width=max(4, size // 18))
        if bb[2] - bb[0] <= max_w and bb[3] - bb[1] <= max_h:
            return f
        size -= 4
    return _anton(size)


def _words(canvas, lines, box, colors, font="anton", align="center"):
    """Big words inside box (x0, y0, x1, y1): one line per entry, each as big as it fits; black
    outline + soft shadow. colors: one per line."""
    x0, y0, x1, y1 = box
    n = len(lines)
    lh = (y1 - y0) / n
    d = ImageDraw.Draw(canvas)
    out = []
    for i, (line, col) in enumerate(zip(lines, colors)):
        cy = y0 + lh * (i + 0.5)
        if font == "airone":
            size = A.fit_size(line, x1 - x0, lh * 0.86, start=260, floor=30)
            w, h = A.text_size(line, size)
            cx = (x0 + x1) / 2 if align == "center" else x0 + w / 2
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            A.draw_text(sh, (cx + 6, cy + 10), line, size, fill=(0, 0, 0, 170))
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
            A.draw_text(canvas, (cx, cy), line, size, fill=col, stroke=max(5, size // 16), stroke_fill=INK)
            out.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        else:
            f = _fit_anton(line, x1 - x0, lh * 0.95)
            stroke = max(5, f.size // 16)
            anchor = "mm" if align == "center" else "lm"
            cx = (x0 + x1) / 2 if align == "center" else x0
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((cx + 6, cy + 10), line, font=f, fill=(0, 0, 0, 170), anchor=anchor,
                                    stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
            d.text((cx, cy), line, font=f, fill=col, anchor=anchor, stroke_width=stroke, stroke_fill=INK)
            out.append(d.textbbox((cx, cy), line, font=f, anchor=anchor, stroke_width=stroke))
    return out


def phrase_lines(phrase, max_lines=2):
    words = phrase.upper().split()
    if len(words) <= 1 or len(phrase) <= 9:
        return [phrase.upper()]
    if len(words) == 2:
        return words
    cut = max(1, min(len(words) - 1, round(len(words) / 2)))
    return [" ".join(words[:cut]), " ".join(words[cut:])][:max_lines]


def _paste(canvas, im, xy, shadow=True):
    if shadow:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        a = im.getchannel("A").point(lambda v: v * 0.7)
        blk = Image.new("RGBA", im.size, (0, 0, 0, 255))
        blk.putalpha(a)
        sh.alpha_composite(blk, (int(xy[0] + 10), int(xy[1] + 16)))
        canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    canvas.alpha_composite(im, (int(xy[0]), int(xy[1])))


def _character(canvas, emotion, side, height=None, glow=(40, 110, 255), max_w=0.5, rim=True):
    """The character big on one half, standing on the bottom edge. Returns its box."""
    ch = A.character(emotion)
    h = height or int(TH * 1.0)
    ch = ch.resize((int(ch.width * h / ch.height), h), Image.LANCZOS)
    if ch.width > TW * max_w:
        k = TW * max_w / ch.width
        ch = ch.resize((int(ch.width * k), int(ch.height * k)), Image.LANCZOS)
    x = TW - ch.width + 10 if side == "right" else -10
    y = TH - ch.height + 4
    _glow(canvas, (x + 40, y + 40, x + ch.width - 40, TH), glow, 80, 150)
    if rim:                                                     # a thin light rim: the character pops off the background
        a = ch.getchannel("A").filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
        rim_im = Image.new("RGBA", ch.size, (255, 255, 255, 0))
        rim_im.putalpha(a.point(lambda v: int(v * 0.85)))
        canvas.alpha_composite(rim_im, (int(x), int(y)))
    _paste(canvas, ch, (x, y))
    return x, y, x + ch.width, TH


def _pose(prefer, fallback):
    """A pose picture if the character has it (point_left...), else the given emotion."""
    have = set(A.characters())
    for p in prefer:
        if p in have:
            return p
    return fallback


def _icon_name(th, fmt):
    ic = th.get("icon")
    if ic and ic != "none":
        return ic
    return {"deadline": "hourglass", "reveal": "eye", "goal": "trophy", "count": "comment", "pin": "pin",
            "error": "lock", "dare": "fire", "only": "crown"}.get(fmt, "question")


def _tilted(im, rnd, spread=9):
    return im.rotate(rnd.uniform(-spread, spread), Image.BICUBIC, expand=True)


SPOTS = {   # where the key thing is on each UI card (fractions of the card), for the ring and the arrow
    "comments_zero": (0.02, 0.04, 0.48, 0.24), "likes_zero": (0.02, 0.66, 0.36, 0.95),
    "likes_and_comments_zero": (0.02, 0.48, 0.36, 0.69), "delete_channel": (0.52, 0.72, 0.9, 0.93),
    "private_player": (0.33, 0.23, 0.67, 0.58), "video_unavailable": (0.4, 0.36, 0.93, 0.52),
    "view_count": (0.28, 0.18, 0.78, 0.78), "delete_video": (0.04, 0.2, 0.2, 0.8),
}


# ------------------------------------------------------------------ the styles
def render(style, data, variant=0):
    """One thumbnail (RGB 1280x720) in `style` for the script `data` (see ws_script.write).
    Every style fills the frame: a coloured, textured background, the character big on one half,
    1-3 huge words, one big 3D picture. No small print."""
    th = data.get("thumbnail") or {}
    title = data.get("title_base") or data.get("title", "")
    phrase = (th.get("phrase") or "").strip() or re.sub(r"[\[\]<>{}()]", "", title).upper()[:22]
    phrase = " ".join(phrase.split()[:3])
    emotion = th.get("emotion") or "shocked"
    fmt = data.get("format") or "goal"
    rnd = random.Random(f"{title}-{style}-{variant}")
    side = "left" if variant % 2 else "right"
    other = "right" if side == "left" else "left"
    scheme = SCHEME_FOR.get(fmt, ["black"])[variant % len(SCHEME_FOR.get(fmt, ["black"]))]
    icon = _icon_name(th, fmt)

    if style in ("error", "error_glow"):
        faces = A.drawn_faces(title)
        if style == "error_glow":                               # the sad face alone, huge, centre stage
            bg = _backdrop("red", (0.5, 0.48))
            face = A.yt_face_drawn(faces[variant % len(faces)], int(TW * 0.62))
            if face.height > TH * 0.86:
                face = face.resize((int(face.width * TH * 0.86 / face.height), int(TH * 0.86)), Image.LANCZOS)
            _glow(bg, ((TW - face.width) // 2, (TH - face.height) // 2, (TW + face.width) // 2,
                       (TH + face.height) // 2), (255, 20, 30), 90, 85)
            _paste(bg, face, ((TW - face.width) // 2, (TH - face.height) // 2))
            return bg.convert("RGB")
        bg = _backdrop("black" if variant % 2 else "red", (0.3 if side == "right" else 0.7, 0.5))
        box = _character(bg, emotion if emotion in ("sad", "crying", "shocked", "scared", "nervous") else
                         _pose(["sad", "phone_shock"], "shocked"), side, max_w=0.46)
        free_w = (box[0] if side == "right" else TW - box[2]) - 50
        face = A.yt_face_drawn(faces[variant % len(faces)], int(min(TW * 0.5, free_w)))
        if face.height > TH * 0.8:
            face = face.resize((int(face.width * TH * 0.8 / face.height), int(TH * 0.8)), Image.LANCZOS)
        free0, free1 = (0, box[0]) if side == "right" else (box[2], TW)
        fx = (free0 + free1 - face.width) / 2
        _glow(bg, (fx, (TH - face.height) / 2, fx + face.width, (TH + face.height) / 2), (255, 20, 30), 90, 75)
        _paste(bg, face, (fx, (TH - face.height) / 2))
        return bg.convert("RGB")

    if style == "ui":
        name = th.get("ui") if th.get("ui") in A.UI_NAMES else rnd.choice(UI_FOR.get(fmt, ["comments_zero"]))
        count = "0"
        m = re.search(r"(\d[\d,]*)", title)
        if m and fmt in ("count", "goal"):
            count = m.group(1)
        pinned = ""
        if name == "pinned_comment":                             # the pinned comment is the word viewers are asked to type
            word = re.sub(r'["“”]', "", str(data.get("comment_word") or "")).strip()
            pinned = word.upper() if 0 < len(word) <= 16 else "FIRST!"
        bg = _backdrop(scheme, (0.68 if side == "right" else 0.32, 0.5))
        # the character on one side (pointing at the card if that pose exists), the card big on the other
        pose = _pose(["point_left"] if side == "right" else ["point_right"], emotion)
        box = _character(bg, pose, side, max_w=0.42)
        free0, free1 = (24, box[0] + 20) if side == "right" else (box[2] - 20, TW - 24)
        card_w = int(min(free1 - free0, TW * (0.66 if name not in ("delete_video", "view_count") else 0.6)))
        card = A.ui(name, card_w, title=title if name in ("likes_zero", "likes_and_comments_zero") else pinned,
                    count=count, note=_error_note(title))
        if card.height > TH * 0.8:
            k = TH * 0.8 / card.height
            card = card.resize((int(card.width * k), int(card.height * k)), Image.LANCZOS)
        cx = int(max(24, min(TW - card.width - 24, (free0 + free1 - card.width) / 2)))
        if name == "pinned_comment":
            spot = (0.135, 0.665, min(0.9, 0.2 + 0.052 * len(pinned)), 0.79)
        else:
            spot = SPOTS.get(name)
        # the open space goes on the side of the card nearest the ringed spot: the arrow starts there
        # and only crosses the bit of card between its edge and the ring, never the words
        room_above = bool(spot) and (spot[1] + spot[3]) / 2 < 0.5
        room = TH - card.height - 48
        cy = TH - card.height - 24 if room_above else 24
        rx0, rx1 = (cx, cx + card.width * 0.55) if side == "right" else (cx + card.width * 0.45, cx + card.width)
        if room > 200:                                           # the big 3D picture fills the open space
            pic = _tilted(A.picture(icon, int(min(room - 20, 300))), rnd, 7)
            py = (24 + (cy - pic.height) / 2) if room_above else (cy + card.height + (TH - cy - card.height - pic.height) / 2)
            _paste(bg, pic, ((rx0 + rx1) / 2 - pic.width / 2, py))
        _paste(bg, card, (cx, cy))
        if spot:
            x0, y0 = cx + spot[0] * card.width, cy + spot[1] * card.height
            x1, y1 = cx + spot[2] * card.width, cy + spot[3] * card.height
            r = A.sheet_ring(x1 - x0, y1 - y0, seed=variant)
            rl, rt = int((x0 + x1 - r.width) / 2), int((y0 + y1 - r.height) / 2)
            bg.alpha_composite(r, (rl, rt))
            mx = (x0 + x1) / 2
            toward = 1 if side == "right" else -1                # the arrow leans toward the character's side
            tx = mx + toward * (x1 - x0) * 0.22
            if room_above:
                ty, sy = rt + 6, max(28, min(cy - 30, rt - 150))
            else:
                ty, sy = rt + r.height - 6, min(TH - 28, max(cy + card.height + 30, rt + r.height + 150))
            sx = min(TW - 40, max(40, tx + toward * 190))
            A.point_arrow(bg, (sx, sy), (tx, ty), seed=variant, style="bold" if variant % 2 else "clean", max_thick=120)
        return bg.convert("RGB")

    if style == "character":
        bg = _backdrop(scheme, (0.3 if side == "left" else 0.7, 0.55))
        box = _character(bg, emotion, side, max_w=0.5)
        tx0, tx1 = (36, box[0] + 10) if side == "right" else (box[2] - 10, TW - 36)
        lines = phrase_lines(phrase, 3)
        if len(lines) == 1 and len(lines[0]) > 6 and " " in lines[0]:      # two big lines beat one small one
            lines = lines[0].split(" ", 1)
        colors = [WHITE] * len(lines)
        colors[-1] = RED if scheme not in ("red",) else (255, 222, 0)
        font = "airone" if variant % 3 == 1 else "anton"
        pic = _tilted(A.picture(icon, 280), rnd)
        bbs = _words(bg, lines, (tx0, 30, tx1, TH - pic.height + 10), colors, font)
        top = max(b[3] for b in bbs)
        px = (tx0 + tx1) / 2 - pic.width / 2 + rnd.uniform(-60, 60)
        _paste(bg, pic, (px, min(TH - pic.height + 10, top - 10)), shadow=True)
        return bg.convert("RGB")

    if style == "headline":
        bg = _backdrop(scheme, (0.5, 0.25))
        lines = [phrase.upper()]
        if _fit_anton(lines[0], TW - 60, 300).size < 170:            # too long for one big line
            lines = phrase_lines(phrase)
        csid = "right" if variant % 2 == 0 else "left"
        _character(bg, emotion, csid, height=int(TH * 0.86), max_w=0.46)
        bbs = _words(bg, lines, (30, 10, TW - 30, 300 if len(lines) == 1 else 360),
                     [RED if scheme != "red" else (255, 222, 0)] + [WHITE] * (len(lines) - 1), "anton")
        pic = _tilted(A.picture(icon, 330), rnd)
        top = max(b[3] for b in bbs) + 10
        x = TW * (0.27 if csid == "right" else 0.73) - pic.width / 2
        _paste(bg, pic, (x, top + max(0, (TH - top - pic.height) / 2)))
        return bg.convert("RGB")

    if style == "icon":
        bg = _backdrop(scheme, (0.7 if side == "right" else 0.3, 0.5))
        pic = _tilted(A.picture(icon, 500), rnd, 6)
        if pic.width > TW * 0.42:
            pic = pic.resize((int(TW * 0.42), int(pic.height * TW * 0.42 / pic.width)), Image.LANCZOS)
        x = TW - pic.width - 40 if side == "right" else 40
        _glow(bg, (x + 40, (TH - pic.height) / 2 + 40, x + pic.width - 40, (TH + pic.height) / 2 - 40),
              (60, 60, 70), 70, 140)
        _paste(bg, pic, (x, (TH - pic.height) // 2))
        tx0, tx1 = (36, x + 20) if side == "right" else (x + pic.width - 20, TW - 36)
        lines = phrase_lines(phrase, 3)
        if len(lines) == 1 and len(lines[0]) > 6 and " " in lines[0]:      # two big lines beat one small one
            lines = lines[0].split(" ", 1)
        _words(bg, lines, (tx0, 40, tx1, TH - 40), [WHITE] * (len(lines) - 1) + [RED if scheme != "red" else (255, 222, 0)], "anton")
        return bg.convert("RGB")

    if style == "white":
        bg = _backdrop("black", (0.75 if side == "right" else 0.25, 0.5))
        box = _character(bg, emotion, side, max_w=0.42)
        tx0, tx1 = (40, box[0] - 20) if side == "right" else (box[2] + 20, TW - 40)
        lines = phrase_lines(phrase, 3)
        d = ImageDraw.Draw(bg)
        n = len(lines)
        bbs = []
        for i, line in enumerate(lines):
            f = _fit_anton(line, tx1 - tx0, (TH - 120) / n * 0.95)
            cy = 60 + (TH - 120) / n * (i + 0.5)
            cxm = (tx0 + tx1) / 2
            d.text((cxm, cy), line, font=f, fill=WHITE, anchor="mm", stroke_width=max(5, f.size // 18), stroke_fill=INK)
            bbs.append(d.textbbox((cxm, cy), line, font=f, anchor="mm", stroke_width=max(5, f.size // 18)))
        x0, y0, x1, y1 = bbs[0]
        if re.search(r"\d", lines[0]) and rnd.random() < 0.6:   # a number gets the red cross-out
            w = max(16, int((y1 - y0) * 0.1))
            d.line([(x0 - 16, y1 - 8), (x1 + 16, y0 + 8)], fill=RED, width=w)
            d.line([(x0 - 16, y0 + 8), (x1 + 16, y1 - 8)], fill=RED, width=w)
        else:                                                    # an arrow from the character's side at the words
            lx0, ly0, lx1, ly1 = bbs[-1]
            tx = lx1 + 8 if side == "right" else lx0 - 8
            ty = (ly0 + ly1) / 2
            sx = tx + 250 if side == "right" else tx - 250
            sy = ty + 200 if ty < TH * 0.6 else ty - 200
            start = (min(TW - 30, max(30, sx)), min(TH - 30, max(30, sy)))
            A.point_arrow(bg, start, (tx, ty), seed=variant, style="bold" if variant % 2 else "brush", max_thick=120)
        return bg.convert("RGB")

    raise ValueError(style)



def _error_note(title):
    t = title.lower()
    for key, note in (("delet", "This video has been deleted."), ("remov", "This video has been removed."),
                      ("unlist", "This video is unlisted."), ("lock", "This video is locked."),
                      ("access", "You don't have access to this video."), ("glitch", "Something went wrong."),
                      ("curse", "This video is cursed."), ("hidden", "This video is hidden."),
                      ("secret", "This video is secret.")):
        if key in t:
            return note
    return ""


def make(data, out_dir: Path, count=3):
    """Three different thumbnails for the video. Returns the paths."""
    fmt = data.get("format") or "goal"
    styles = list(STYLES_FOR.get(fmt, STYLES_FOR["goal"]))
    rnd = random.Random(data.get("title", "") + data.get("text", "")[:40])
    first, rest = styles[0], styles[1:]
    rnd.shuffle(rest)
    pick = [first] + rest
    while len(pick) < count:
        pick.append(rnd.choice(["character", "headline", "icon"]))
    for old in out_dir.glob("*thumbnail*.jpg"):
        old.unlink()
    paths = []
    for i, st in enumerate(pick[:count], 1):
        im = render(st, data, variant=i - 1)
        p = out_dir / f"911video-thumbnail-{i}.jpg"
        im.save(p, quality=92)
        paths.append(p)
    data["thumbs"] = pick[:count]
    return paths
