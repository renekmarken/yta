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
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
    ImageDraw.Draw(layer).rounded_rectangle(box, 40, fill=(*color, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


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


def _character(canvas, emotion, side, height=None, glow=(40, 110, 255)):
    ch = A.character(emotion)
    h = height or int(TH * 0.98)
    ch = ch.resize((int(ch.width * h / ch.height), h), Image.LANCZOS)
    if ch.width > TW * 0.56:
        ch = ch.resize((int(TW * 0.56), int(ch.height * TW * 0.56 / ch.width)), Image.LANCZOS)
    x = TW - ch.width + 20 if side == "right" else -20
    y = TH - ch.height + 6
    _glow(canvas, (x + 60, y + 60, x + ch.width - 60, TH), glow, 90, 120)
    _paste(canvas, ch, (x, y))
    return x, y, x + ch.width, TH


# ------------------------------------------------------------------ the styles
def render(style, data, variant=0):
    """One thumbnail (RGB 1280x720) in `style` for the script `data` (see ws_script.write)."""
    th = data.get("thumbnail") or {}
    title = data.get("title_base") or data.get("title", "")
    phrase = (th.get("phrase") or "").strip() or re.sub(r"[\[\]<>{}()]", "", title).upper()[:22]
    small = (th.get("small") or "").strip()
    emotion = th.get("emotion") or "shocked"
    fmt = data.get("format") or "goal"
    rnd = random.Random(f"{title}-{style}-{variant}")
    side = "left" if variant % 2 else "right"

    if style in ("error", "error_glow"):
        bg = _dark((44, 44, 48) if style == "error" else (110, 0, 8))
        faces = A.drawn_faces(title)
        fw = int(TW * (0.46 if style == "error" else 0.42))
        face = A.yt_face_drawn(faces[variant % len(faces)], fw)
        fw = face.width
        if style == "error_glow":
            _glow(bg, ((TW - fw) // 2, 120, (TW + fw) // 2, 120 + face.height), (255, 20, 30), 80, 140)
        y = (TH - face.height) // 2 - (40 if small else 0)
        _paste(bg, face, ((TW - fw) // 2, y))
        if small:
            d = ImageDraw.Draw(bg)
            f = A.font("Roboto-Medium.ttf", 44)
            d.text((TW / 2, y + face.height + 56), small, font=f, fill=(235, 235, 235), anchor="mm")
        return bg.convert("RGB")

    if style == "ui":
        bg = _dark((52, 52, 58))
        name = th.get("ui") if th.get("ui") in A.UI_NAMES else rnd.choice(UI_FOR.get(fmt, ["comments_zero"]))
        count = "0"
        m = re.search(r"(\d[\d,]*)", title)
        if m and fmt in ("count", "goal"):
            count = m.group(1)
        pinned = ""
        if name == "pinned_comment":                             # the pinned comment is the word viewers are asked to type
            word = re.sub(r'["“”]', "", str(data.get("comment_word") or "")).strip()
            pinned = word.upper() if 0 < len(word) <= 16 else "FIRST!"
        card = A.ui(name, int(TW * (0.8 if name not in ("delete_video", "view_count") else 0.66)),
                    title=title if name in ("likes_zero", "likes_and_comments_zero") else pinned, count=count,
                    note=small or _error_note(title))
        cx, cy = (TW - card.width) // 2, (TH - card.height) // 2
        _paste(bg, card, (cx, cy))
        # ring the key spot, arrow pointing at it
        spot = {"comments_zero": (0.02, 0.04, 0.48, 0.24), "likes_zero": (0.02, 0.66, 0.36, 0.95),
                "likes_and_comments_zero": (0.02, 0.48, 0.36, 0.69),
                "pinned_comment": (0.135, 0.665, min(0.9, 0.2 + 0.052 * len(pinned)), 0.79),
                "view_count": None, "delete_video": None, "delete_channel": (0.52, 0.72, 0.9, 0.93),
                "private_player": (0.3, 0.7, 0.7, 0.9), "video_unavailable": (0.36, 0.36, 0.95, 0.62)}.get(name)
        if spot:
            x0, y0 = cx + spot[0] * card.width, cy + spot[1] * card.height
            x1, y1 = cx + spot[2] * card.width, cy + spot[3] * card.height
            pad = 16 if name == "pinned_comment" else 30                # tight there: lines above and below
            r = A.ring(x1 - x0 + pad, y1 - y0 + pad, seed=variant)
            bg.alpha_composite(r, (int(x0 - pad / 2 - (r.width - (x1 - x0 + pad)) / 2),
                                   int(y0 - pad / 2 - (r.height - (y1 - y0 + pad)) / 2)))
            # the arrow comes from the free side and points down at the ring
            base = A.arrow(210, curve=0.32)
            mid_y = (y0 + y1) / 2
            if x1 + base.width * 0.9 < TW - 10:                      # from the right, pointing left-down
                ar = base.transpose(Image.FLIP_LEFT_RIGHT).rotate(28, Image.BICUBIC, expand=True)
                ax, ay = int(x1 - 14), int(mid_y - ar.height - 6)
            else:                                                    # from the left, pointing right-down
                ar = base.rotate(-28, Image.BICUBIC, expand=True)
                ax, ay = int(x0 - ar.width + 14), int(mid_y - ar.height - 6)
            if ay < 6:                                               # no room above: come from below
                ar = ar.transpose(Image.FLIP_TOP_BOTTOM)
                ay = int(mid_y + 6)
            bg.alpha_composite(ar, (max(4, min(TW - ar.width - 4, ax)), max(4, ay)))
        return bg.convert("RGB")

    if style == "character":
        bg = _dark((30, 30, 36), center=(0.3 if side == "right" else 0.7, 0.5))
        box = _character(bg, emotion, side)
        tx0, tx1 = (40, box[0] - 10) if side == "right" else (box[2] + 10, TW - 40)
        lines = phrase_lines(phrase)
        colors = [WHITE] * len(lines)
        colors[-1] = RED
        font = "airone" if variant % 3 == 1 else "anton"
        ic = th.get("icon")
        has_icon = ic and ic != "none"
        bbs = _words(bg, lines, (tx0, 70, tx1, TH - 200 if has_icon else TH - 60), colors, font)
        if has_icon:
            im = A.icon(ic, 140)
            x = (tx0 + tx1) / 2 - im.width / 2
            _paste(bg, im, (x, max(max(b[3] for b in bbs) + 12, TH - 190)), shadow=False)
        return bg.convert("RGB")

    if style == "headline":
        bg = _dark((70, 8, 12) if fmt in ("deadline", "dare") else (30, 30, 40), center=(0.5, 0.15))
        lines = [phrase.upper()]
        if _fit_anton(lines[0], TW - 80, 280).size < 160:            # too long for one big line
            lines = phrase_lines(phrase)
        # the character big on one half (behind the words), the icon on the other
        _character(bg, emotion, "right" if variant % 2 == 0 else "left", height=int(TH * 0.8))
        bbs = _words(bg, lines, (40, 18, TW - 40, 300), [RED] + [WHITE] * (len(lines) - 1), "anton")
        ic = th.get("icon")
        if ic and ic != "none":
            im = A.icon(ic, 230)
            x = (TW * 0.25 if variant % 2 == 0 else TW * 0.75) - im.width / 2
            top = max(b[3] for b in bbs) + 30
            _paste(bg, im, (x, top + max(0, (TH - top - im.height) // 2 - 10)), shadow=False)
        return bg.convert("RGB")

    if style == "icon":
        bg = _dark((90, 0, 6), center=(0.7 if side == "right" else 0.3, 0.5))
        ic = th.get("icon") if th.get("icon") not in (None, "none") else {"deadline": "hourglass", "reveal": "eye",
                                                                          "goal": "fire"}.get(fmt, "question")
        im = A.icon(ic, 460)
        x = TW - im.width - 60 if side == "right" else 60
        _paste(bg, im, (x, (TH - im.height) // 2), shadow=False)
        tx0, tx1 = (50, x - 30) if side == "right" else (x + im.width + 30, TW - 50)
        lines = phrase_lines(phrase)
        _words(bg, lines, (tx0, 110, tx1, TH - 110), [WHITE] * (len(lines) - 1) + [RED], "anton")
        return bg.convert("RGB")

    if style == "white":
        bg = Image.new("RGBA", (TW, TH), (255, 255, 255, 255))
        lines = phrase_lines(phrase)
        d = ImageDraw.Draw(bg)
        bbs = []
        n = len(lines)
        for i, line in enumerate(lines):
            f = _fit_anton(line, TW - 160, (TH - 140) / n * 0.92)
            cy = 70 + (TH - 140) / n * (i + 0.5)
            d.text((TW / 2, cy), line, font=f, fill=INK, anchor="mm")
            bbs.append(d.textbbox((TW / 2, cy), line, font=f, anchor="mm"))
        x0, y0, x1, y1 = bbs[0]
        if fmt in ("goal", "count") and rnd.random() < 0.7:     # the red cross-out
            w = max(14, int((y1 - y0) * 0.09))
            d.line([(x0 - 20, y1 - 10), (x1 + 20, y0 + 10)], fill=RED, width=w)
            d.line([(x0 - 20, y0 + 10), (x1 + 20, y1 - 10)], fill=RED, width=w)
        else:
            ar = A.arrow(260, curve=0.25).rotate(20, Image.BICUBIC, expand=True)
            bg.alpha_composite(ar, (int(max(10, x0 - ar.width + 30)), int(max(10, y0 - ar.height * 0.6))))
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
