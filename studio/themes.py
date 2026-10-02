"""Per-video design system: every video gets its own combination of layout, colours, fonts,
backgrounds, browser frame, caption style and animation, callout stickers, transitions, intro,
highlight, music mood, sound-effect pack and thumbnail layout, while staying recognisably the same
channel. Choices avoid repeating the last videos' looks."""
import random

from . import config
from .music import MOODS
from .sfx import PACKS
from .thumbnail import LAYOUTS as THUMBS, PALETTES as THUMB_PALETTES
from .visuals import available_head_fonts, lum, mix, shift_hue, text_safe

LAYOUTS = ["tilt", "tilt", "tilt", "full", "side", "stage", "spotlight"]   # tilt = the signature look
FRAMES = ["mac_dark", "mac_light", "floating", "minimal"]
CAPTIONS = ["bar", "pill", "tag", "underline", "glass"]
BACKGROUNDS = ["gradient", "mesh", "spotlight", "aurora", "blurshot", "blurshot"]   # clean, modern looks
MODES = ["dark", "dark", "brand", "brand", "light"]
TRANSITIONS = [["fade"], ["smoothleft", "smoothright"], ["fadeblack"], ["slideleft", "slideright"],
               ["circleopen", "fade"], ["wipeleft", "wiperight"], ["zoomin", "fade"], ["dissolve"],
               ["hblur", "fade"], ["smoothup", "smoothdown"], ["radial", "fade"],
               ["slideup", "slidedown"], ["coverleft", "revealright"], ["vertopen", "horzopen"],
               ["squeezeh", "fade"], ["cut"]]
CAPTION_ANIMS = ["slide_up", "slide_left", "drop", "fade_up", "slide_right"]
CALLOUTS = ["card", "pill", "glass"]
# music moods that suit each category best (any mood can still appear)
MOOD_BIAS = {"credit-cards": ["lofi", "acoustic", "upbeat"], "insurance": ["acoustic", "ambient", "lofi"],
             "banking-apps": ["upbeat", "lofi", "acoustic"], "investing": ["ambient", "tech", "lofi"],
             "real-estate": ["acoustic", "lofi", "ambient"], "legal": ["ambient", "acoustic", "lofi"],
             "saas": ["upbeat", "tech", "lofi"], "ai-tools": ["tech", "ambient", "upbeat"],
             "business-tools": ["upbeat", "acoustic", "tech"], "marketing": ["upbeat", "tech", "lofi"],
             "vpn-security": ["tech", "ambient", "lofi"], "hosting": ["tech", "upbeat", "lofi"],
             "freelancing": ["lofi", "upbeat", "acoustic"]}
INTROS = ["logo_pop", "headline", "split"]
HIGHLIGHTS = ["box", "underline", "spotlight"]
OUTROS = ["center", "ring"]
ALT_ACCENTS = [(255, 212, 0), (0, 214, 170), (255, 94, 58), (122, 92, 255), (0, 170, 255),
               (255, 70, 140), (140, 230, 60), (255, 150, 30)]

GEOMETRY = {   # where the website sits in the frame, per layout
    "full": {"cx": 180, "cy": 92, "cw": 1560, "ch": 877},
    "side": {"cx": 600, "cy": 210, "cw": 1216, "ch": 684},
    "stage": {"cx": 240, "cy": 250, "cw": 1440, "ch": 810},
    "cinema": {"cx": 0, "cy": 0, "cw": 1920, "ch": 1080},
    "spotlight": {"cx": 274, "cy": 118, "cw": 1372, "ch": 772},
    "tilt": {"cx": 430, "cy": 236, "cw": 1260, "ch": 708},
}


def _avoid(rnd, options, recent_values):
    fresh = [o for o in options if o not in recent_values]
    return rnd.choice(fresh or options)


def _mood(rnd, category, recent):
    forced = (config.MUSIC or "auto").lower()
    if forced in MOODS or forced == "off":
        return forced
    pool = MOOD_BIAS.get(category, MOODS) * 2 + MOODS          # biased, but every mood possible
    fresh = [m for m in pool if m not in recent]
    return rnd.choice(fresh or pool)


def pick_theme(seed, brand, history, has_mobile, category=None):
    rnd = random.Random(seed)
    recent = [h.get("theme", {}) for h in history[-3:]]
    rv = lambda k: [r.get(k) for r in recent]

    mode = _avoid(rnd, MODES, rv("mode")[-1:])
    if brand and rnd.random() < 0.7:
        accent = brand
    else:
        accent = _avoid(rnd, ALT_ACCENTS, [tuple(a) for a in rv("accent") if a])
    accent = tuple(accent)
    accent2 = shift_hue(accent, rnd.choice([-50, 40, 150]), sat=0.75, val=0.95)
    light = mode == "light"

    if mode == "dark":
        bg1 = rnd.choice([(11, 13, 18), (14, 14, 16), (10, 14, 24), (17, 13, 20)])
        bg2 = mix(bg1, accent, 0.2)
        text, muted, panel, chrome_text = (255, 255, 255), (165, 170, 184), (32, 35, 43), (225, 228, 235)
    elif mode == "brand":
        bg1 = shift_hue(accent, 0, sat=0.8, val=0.24)
        bg2 = shift_hue(accent, rnd.choice([-25, 25]), sat=0.85, val=0.1)
        text, muted = (255, 255, 255), mix((255, 255, 255), bg1, 0.35)
        panel, chrome_text = mix(bg1, (0, 0, 0), 0.45), (230, 232, 238)
    else:
        bg1 = rnd.choice([(247, 246, 242), (244, 246, 250), (250, 247, 240)])
        bg2 = mix((232, 235, 242), accent, 0.14)
        text, muted, panel, chrome_text = (16, 18, 24), (92, 98, 110), (228, 231, 237), (40, 44, 52)

    layout = _avoid(rnd, LAYOUTS, rv("layout"))
    frames = ["mac_light", "floating", "minimal"] if light else FRAMES
    thumbs = THUMBS if has_mobile else [t for t in THUMBS if t != "phone"]
    all_fonts = available_head_fonts()
    fonts = [f for f in all_fonts if f in ("inter", "interdisplay", "poppins")] or all_fonts  # clean in video
    theme = {
        "seed": seed, "mode": mode, "light": light, "layout": layout,
        "frame": _avoid(rnd, frames, rv("frame")),
        "caption": _avoid(rnd, CAPTIONS, rv("caption")[-1:]),
        "bg": _avoid(rnd, BACKGROUNDS, rv("bg")[-1:]),
        "bg_angle": rnd.choice([90, 115, 65, 150]),
        "blob_alpha": rnd.randint(55, 95),
        "head_font": _avoid(rnd, fonts, rv("head_font")[-1:]) if fonts else "inter",
        "accent": accent, "accent2": accent2, "accent_text": text_safe(accent, light),
        "bg1": bg1, "bg2": bg2, "text": text, "muted": muted, "panel": panel,
        "chrome_text": chrome_text,
        "transitions": _avoid(rnd, TRANSITIONS, rv("transitions")),
        "intro": _avoid(rnd, INTROS, rv("intro")[-1:]),
        "highlight": _avoid(rnd, HIGHLIGHTS, rv("highlight")[-1:]),
        "progress": rnd.random() < 0.6,
        "outro": rnd.choice(OUTROS),
        "thumb": _avoid(rnd, thumbs, [h.get("theme", {}).get("thumb") for h in history[-5:]]),
        "thumb_palette": _avoid(rnd, list(THUMB_PALETTES),
                                [h.get("theme", {}).get("thumb_palette") for h in history[-4:]]),
        "thumb_accent": _avoid(rnd, [(255, 212, 0), (255, 230, 0), (0, 230, 160), (255, 90, 60),
                                     (0, 200, 255), accent if lum(accent) > 120 else (255, 212, 0)],
                               [tuple(a) for a in rv("thumb_accent") if a]),
        "thumb_tilt": rnd.choice([-6, -4, 4, 6]),
        "radius": rnd.choice([20, 24, 28]),
        "tilt": rnd.choice([-3.4, -2.6, 2.6, 3.4]),
        "thumb_font": _avoid(rnd, all_fonts, [h.get("theme", {}).get("thumb_font") for h in history[-2:]])
                      if all_fonts else "inter",
        "cap_anim": _avoid(rnd, CAPTION_ANIMS, rv("cap_anim")[-1:]),
        "callout": _avoid(rnd, CALLOUTS, rv("callout")[-1:]),
        "music": _mood(rnd, category, rv("music")[-2:]),
        "sfx": _avoid(rnd, PACKS, rv("sfx")[-1:]) if config.SFX else "off",
    }
    theme.update(GEOMETRY[layout])
    # Every video mixes the tilted 3D card with a browser window that shows the address bar and URL,
    # clip by clip; "mix" is the second layout, "mix_frame" the browser frame used for it.
    mix_rnd = random.Random(seed + "mix")
    theme["mix"] = mix_rnd.choice(["full", "stage", "spotlight", "side"]) if layout == "tilt" else "tilt"
    theme["mix_frame"] = theme["frame"] if theme["frame"] in ("mac_dark", "mac_light") else \
        ("mac_light" if light else "mac_dark")
    return theme


def normalize(theme):
    """JSON turns tuples into lists; Pillow wants tuples."""
    return {k: tuple(v) if isinstance(v, list) and v and isinstance(v[0], int) else v
            for k, v in theme.items()}
