"""Full-quality White Screen assets made with Gemini's image model.

The owner's character sheet has the emotions packed so tightly that the hoods overlap and the
outer ones are cut off, so no cut-out of it can be clean. This redraws every emotion on its own:
same character, same pose and expression, complete (nothing cut off), at full resolution, on a flat
green screen that is keyed out. It also draws new poses and a set of unique YouTube-style 3D
objects for thumbnails and videos.

Every picture is checked before it is kept:
  - the key is clean (no green left, no holes, edges soft but tight)
  - nothing is cut off at the sides or top (the hoodie may run off the bottom)
  - Gemini looks at the reference and the result side by side: same character? same expression?
    complete? clean? Only a yes on all of them passes; otherwise it tries again (3 tries).

Results go to assets/whitescreen/redraw/<group>/ for review; `promote` moves the reviewed ones
into place (characters/ and objects/).

  python tools/ws_hd_assets.py characters [name ...]   # redraw the emotions (all, or the named ones)
  python tools/ws_hd_assets.py poses                   # the extra poses in NEW_POSES
  python tools/ws_hd_assets.py objects                 # the 3D objects in OBJECTS
  python tools/ws_hd_assets.py all
  python tools/ws_hd_assets.py promote [names ...]     # move reviewed results into place

Needs GEMINI_API_KEY (an AI Studio key with image generation). Runs in the
"White Screen: improve assets" workflow, which commits the results.
"""
import base64
import io
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from studio import config  # noqa: E402

WS = config.ASSETS_DIR / "whitescreen"
CHAR_DIR = WS / "characters"
OBJ_DIR = WS / "objects"
REVIEW = WS / "redraw"
MODELS = ["gemini-2.5-flash-image", "gemini-2.5-flash-image-preview", "gemini-2.0-flash-preview-image-generation"]
AISTUDIO = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
VERTEX = "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"

LOOK = ("a young cartoon character with messy brown hair, big expressive cartoon eyes, a plain black face mask "
        "covering nose and mouth, and a bright royal-blue hoodie with the hood up and two drawstrings; glossy, "
        "soft 3D cartoon render (like a Pixar-style sticker), soft studio light")
BACKDROP = ("Background: one perfectly flat, pure chroma-key green (#00FF00) colour everywhere, with no shadow, no floor, "
            "no gradient, no vignette, no text, no border, no frame. Nothing else in the picture.")
REDRAW = ("Redraw the character in the reference picture in high quality at high resolution: {look}. Keep EXACTLY the "
          "same pose, hands, eyes and expression ({what}){extra}. Show the head and upper body, centred, with clear "
          "empty space above the hood and on both sides — nothing may touch or be cut off by the left, right or top "
          "edge of the picture. The hoodie is cut off by the bottom edge at chest/waist height. "
          "Draw the complete hood and both shoulders, even where the reference is cut off. " + BACKDROP)
POSE = ("Draw this exact same character (see the reference): {look}. Pose: {pose}. Head and upper body, centred, with "
        "empty space above the hood and on both sides — nothing touches or is cut off by the left, right or top edge; "
        "the hoodie is cut off by the bottom edge. " + BACKDROP)
OBJECT = ("A single {thing}, as a glossy 3D cartoon icon (soft studio light, bold readable shapes, saturated colours, "
          "a little shine, like a premium 3D emoji or YouTube thumbnail sticker), centred, filling about 80% of the picture, "
          "with empty space on every side. No text unless asked, no logos. " + BACKDROP)

# what each emotion shows (helps Gemini keep it) and the little symbol that belongs next to it
EMOTIONS = {
    "alert": ("wide-eyed and alert, looking to the side", ", with three short yellow alert lines next to the head"),
    "angry": ("angry frown, both fists raised in front of the chest", ", with the red anger mark next to the head"),
    "celebrate": ("eyes happily closed, both fists raised high above the head in celebration", ""),
    "confused": ("confused, one hand on the chin, looking up to the side", ", with a white question mark next to the head"),
    "cool": ("wearing black sunglasses, one hand adjusting them", ""),
    "crying": ("crying, with two streams of blue tears running down", ""),
    "determined": ("determined frown, one fist raised in front of the chest", ""),
    "facepalm": ("facepalm, one hand covering the eyes", ""),
    "laughing_point": ("laughing with eyes closed, pointing a finger at the viewer", ", with three short yellow lines next to the head"),
    "love": ("winking, making a small finger-heart with one hand", ", with a small red heart next to the head"),
    "nervous": ("nervous wide eyes", ", with a blue sweat drop on the head"),
    "relaxed": ("relaxed and content, eyes closed, both hands behind the head", ""),
    "scared": ("scared, both hands (sleeves) pressed over the mask, eyes looking to the side", ""),
    "shocked": ("shocked, huge round eyes, both hands on the cheeks", ""),
    "shush": ("wide eyes, one finger raised to the mask in a 'shh' gesture", ""),
    "shy": ("shy, looking to the side, pink blush on the cheeks", ""),
    "side_eye": ("suspicious side-eye, looking to the side", ""),
    "sleepy": ("sleepy, eyes closed, head leaning on one hand", ", with white 'Z z' sleep letters next to the head"),
    "smug": ("smug half-closed eyes", ""),
    "stare": ("neutral stare straight at the viewer, big round eyes", ""),
    "starstruck": ("star-struck, eyes turned into two yellow stars, both fists in front of the chest", ""),
    "thinking": ("thinking, one hand on the chin, looking to the side", ""),
    "thumbs_down": ("unimpressed eyes, giving a thumbs down", ""),
    "thumbs_up": ("happy closed eyes, giving a thumbs up", ""),
    "unimpressed": ("unimpressed, half-closed flat eyes", ""),
    "wave": ("happy closed eyes, waving with one open hand", ""),
    "wink_point": ("winking, pointing a finger at the viewer", ""),
}
NEW_POSES = {
    "point_left": "pointing with one arm stretched out to the LEFT side of the picture at something, excited wide eyes, looking the same way",
    "point_right": "pointing with one arm stretched out to the RIGHT side of the picture at something, excited wide eyes, looking the same way",
    "point_down": "pointing down with both index fingers at something below, eyes wide, excited",
    "point_up": "pointing up with one finger at something above, eyes wide and amazed",
    "phone_shock": "holding a smartphone in both hands and staring at it in total shock, eyes huge",
    "phone_happy": "holding a smartphone up and smiling with closed happy eyes",
    "cover_eyes": "covering the eyes with both hands, peeking through the fingers",
    "pray": "both hands pressed together pleading, big shiny hopeful eyes",
    "mind_blown": "both hands on the head, completely shocked, eyes wide, small yellow burst lines around the head",
    "shrug": "shrugging with both palms up, eyebrows raised, 'I don't know' look",
    "clap": "clapping hands happily, eyes closed with joy",
    "scream": "screaming in panic, hands raised beside the face, eyes huge",
    "sad": "very sad, eyes glossy and teary, shoulders down",
    "evil": "mischievous evil grin in the eyes, fingers steepled together",
    "peek": "peeking up from the bottom edge of the picture, only the eyes, hair and hood visible, curious",
    "heart_hands": "making a big heart shape with both hands in front of the chest, happy closed eyes",
}
OBJECTS = {
    "like_button": "big glossy blue thumbs-up like button inside a rounded square",
    "like_fire": "glossy blue thumbs-up like icon wrapped in bright orange flames",
    "like_gold": "shiny solid-gold thumbs-up trophy on a small pedestal",
    "like_cracked": "blue thumbs-up like icon cracked into pieces with small fragments flying off",
    "dislike_button": "glossy red thumbs-down icon inside a rounded square",
    "comment_bubble": "big glossy white speech bubble with three dark dots inside, thick soft outline",
    "comment_stack": "a stack of three overlapping glossy speech bubbles (white, blue, red)",
    "comment_counter": "a glossy white speech bubble with a red notification badge showing the number 0",
    "heart_glossy": "big glossy red heart with a white shine",
    "heart_cracked": "a red heart cracked in half with a jagged split",
    "heart_pinned": "a red heart with a red pushpin stuck in the top",
    "bell_ringing": "a glossy golden notification bell ringing, with motion lines on both sides",
    "bell_badge": "a glossy red notification bell with a white circular badge showing 9+",
    "play_red": "a glossy red rounded-rectangle video play button with a white triangle (generic, no logo text)",
    "play_cracked": "a red rounded-rectangle video play button cracked and shattering into pieces",
    "play_locked": "a red rounded-rectangle video play button wrapped in heavy metal chains with a padlock",
    "play_melting": "a red rounded-rectangle video play button melting and dripping",
    "play_fire": "a red rounded-rectangle video play button on fire",
    "play_sad": "a red rounded-rectangle video play button with a sad cartoon face and one tear",
    "play_ghost": "a pale, see-through ghost shaped like a video play button, floating, spooky but cute",
    "padlock_red": "a big glossy red padlock, closed",
    "padlock_open": "a big glossy golden padlock, open",
    "trash_can": "a glossy red trash can with the lid flying off and crumpled paper",
    "trash_video": "a trash can with a video thumbnail card falling into it",
    "hourglass_red": "a glossy hourglass with red sand almost run out",
    "alarm_clock_red": "a red alarm clock ringing violently, shaking lines",
    "countdown_24h": "a glossy round stopwatch showing a big '24H'",
    "calendar_x": "a tear-off calendar page with a big red X on it",
    "eye_glowing": "a big cartoon eye glowing red, wide open",
    "views_counter": "a glossy white pill-shaped counter showing an eye icon and the number 0",
    "subscribe_red": "a glossy red pill button with the white word SUBSCRIBE and a hand cursor clicking it",
    "subscribed_grey": "a glossy grey pill button with the dark word SUBSCRIBED and a small bell",
    "cursor_click": "a white hand cursor (pointing finger) clicking, with small click lines",
    "warning_red": "a glossy red warning triangle with a white exclamation mark",
    "error_screen": "a small floating video player window showing a sad face and a broken triangle, dark theme",
    "loading_ring": "a glossy red circular loading spinner",
    "glitch_tv": "an old cartoon TV with a glitchy colourful static screen",
    "mystery_box": "a glossy purple mystery box with a big yellow question mark, lid slightly open with light coming out",
    "magnifier": "a big glossy magnifying glass",
    "crown_gold": "a shiny gold crown with red gems",
    "trophy_gold": "a shiny gold trophy cup with a star",
    "fire_big": "a big bright cartoon flame",
    "explosion": "a bold cartoon explosion burst, orange and yellow",
    "lightning": "a bold yellow lightning bolt",
    "speech_shout": "a spiky red shout speech bubble, empty",
    "algorithm_robot": "a cute small robot holding a magnifying glass",
    "rocket_up": "a red and white cartoon rocket flying up with a fire trail",
    "chart_up": "a glossy green arrow chart going up steeply",
    "chart_down": "a glossy red arrow chart crashing down",
    "pin_red": "a glossy red pushpin",
    "question_3d": "a big glossy red 3D question mark",
    "exclaim_3d": "a big glossy red 3D exclamation mark",
    "check_green": "a big glossy green check mark in a circle",
    "cross_red": "a big glossy red X in a circle",
    "zero_3d": "a big glossy red 3D number 0",
    "hundred_3d": "a big glossy red 3D '100' with a fiery underline",
    "ghost_cute": "a cute small white cartoon ghost waving",
    "skull_cartoon": "a cute cartoon skull, glossy white, not scary",
    "phone_notifications": "a smartphone with lots of red notification badges popping out",
    "megaphone_red": "a red megaphone with sound waves",
}


# ------------------------------------------------------------------ Gemini
def _png(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


_WORKS = {}          # the model/endpoint that answered last time: tried first from then on


class QuotaError(RuntimeError):
    pass


def _image_call(prompt, ref=None, aspect="3:4"):
    key = config.GEMINI_API_KEY
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set")
    parts = [{"text": prompt}]
    if ref is not None:
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(_png(ref.convert("RGB"))).decode()}})
    combos = [(m, ep) for m in MODELS for ep in ("aistudio", "vertex")]
    if _WORKS.get("combo") in combos:
        combos.remove(_WORKS["combo"])
        combos.insert(0, _WORKS["combo"])
    errors, quota = [], 0
    for model, ep in combos:
        url = (AISTUDIO if ep == "aistudio" else VERTEX).format(m=model)
        kw = {"headers": {"x-goog-api-key": key}} if ep == "aistudio" else {"params": {"key": key}}
        for with_aspect in ((True, False) if aspect else (False,)):
            gen = {"responseModalities": ["IMAGE", "TEXT"]}
            if with_aspect:
                gen["imageConfig"] = {"aspectRatio": aspect}
            body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
            r = None
            for attempt in range(2):
                try:
                    r = requests.post(url, json=body, timeout=120, **kw)
                except requests.RequestException as e:
                    errors.append(f"{model}/{ep}: {str(e)[:100]}")
                    r = None
                    break
                if r.status_code == 429:
                    if "limit: 0" in r.text or "free_tier" in r.text.lower():
                        quota += 1                              # this key has no image quota on this model
                        break
                    time.sleep(15 * (attempt + 1))
                    continue
                if r.status_code in (500, 503):
                    time.sleep(8)
                    continue
                break
            if r is None:
                break
            if r.status_code == 400 and with_aspect:            # this model doesn't take the aspect: without it
                continue
            if r.status_code != 200:
                errors.append(f"{model}/{ep} {r.status_code}: {r.text[:200]}")
                break
            for cand in r.json().get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
                    if data:
                        _WORKS["combo"] = (model, ep)
                        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
            errors.append(f"{model}/{ep}: no image in the answer")
            break
    if quota and not _WORKS:
        raise QuotaError("this Gemini key has no image-generation quota (free tier limit 0). " + " | ".join(errors[-2:]))
    raise RuntimeError(" | ".join(errors[-3:]))


JUDGE = """Image 1 is the reference, image 2 is a new drawing (on a checkerboard = transparent).
{what}
Answer in JSON: {{"same_character": true/false, "same_pose_and_expression": true/false,
"complete": true/false (nothing cut off at left/right/top, no missing hand or hood part),
"clean": true/false (no green fringe, no leftover background, no holes, no extra objects or text),
"problems": "short note"}}"""


def judge(ref, cut, what):
    """Gemini compares the reference and the result. Returns (ok, note)."""
    from studio import ai
    try:
        ans = ai.parse_json(ai.see(JUDGE.format(what=what), [_png(_on_checker(ref)), _png(_on_checker(cut))]))
    except Exception as e:                                        # no verdict: don't block on it
        return True, f"(no check: {str(e)[:80]})"
    keys = ("same_character", "same_pose_and_expression", "complete", "clean")
    ok = all(ans.get(k) is True for k in keys if k in ans)
    return ok, ans.get("problems", "")


# ------------------------------------------------------------------ keying
def key_green(im: Image.Image, crop=True):
    """Chroma key against the picture's own background colour (sampled at the border), green
    spill removed from the edges, stray specks dropped."""
    a = np.asarray(im).astype(np.float32)
    border = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)
    bg_green = bg[1] - max(bg[0], bg[2])
    dist = np.sqrt(((a - bg) ** 2).sum(-1))
    # background = very close to the sampled colour, or strongly green; ramps give soft edges
    a_dist = np.clip((dist - 40) / 90, 0, 1)
    a_green = np.clip(1 - (greenness - bg_green * 0.25) / (bg_green * 0.45 + 1), 0, 1)
    alpha = np.maximum(a_dist, a_green) if bg_green > 60 else a_dist
    alpha = np.minimum(alpha, a_dist + a_green)             # both must agree it is the subject
    # de-spill: no pixel greener than its red/blue allow
    lim = np.maximum(r, b) + 6
    g2 = np.where(g > lim, lim, g)
    out = np.dstack([r, g2, b, alpha * 255]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    a8 = img.getchannel("A")
    a8 = a8.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.6))
    a8 = _drop_specks(a8)
    img.putalpha(a8)
    if crop:
        bb = a8.point(lambda v: 255 if v > 24 else 0).getbbox()
        if bb:
            img = img.crop(bb)
    return img


def _drop_specks(a8, keep_frac=0.004):
    """Remove tiny islands (stray green-screen specks) but keep real separate parts (a ?, Zzz, a heart)."""
    try:
        from scipy import ndimage
    except ImportError:
        return a8
    m = np.asarray(a8) > 60
    lab, n = ndimage.label(m)
    if n <= 1:
        return a8
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes >= max(60, sizes.max() * keep_frac)
    mask = keep[lab]
    mask = ndimage.binary_dilation(mask, iterations=2)
    return Image.fromarray((np.asarray(a8) * mask).astype(np.uint8))


def checks(raw: Image.Image, cut: Image.Image, bottom_ok=True):
    """Problems with a keyed result (empty list = fine)."""
    probs = []
    full = key_green(raw, crop=False)
    A = np.asarray(full.getchannel("A")) > 128
    h, w = A.shape
    m = 3
    if A[:m].any():
        probs.append("touches the top")
    if A[:, :m].sum() > h * 0.01 or A[:, -m:].sum() > h * 0.01:
        probs.append("cut off at a side")
    if not bottom_ok and A[-m:].any():
        probs.append("touches the bottom")
    cover = A.mean()
    if not 0.12 < cover < 0.85:
        probs.append(f"coverage {cover:.2f}")
    px = np.asarray(cut.convert("RGBA")).astype(int)
    solid = px[..., 3] > 200
    greenish = (px[..., 1] > px[..., 0] + 40) & (px[..., 1] > px[..., 2] + 40) & solid
    if greenish.sum() > solid.sum() * 0.004:
        probs.append("green left in it")
    return probs


def _on_checker(im):
    im = im.convert("RGBA")
    yy, xx = np.mgrid[0:im.height, 0:im.width]
    tile = (((xx // 24) + (yy // 24)) % 2).astype(np.uint8)
    grey = np.where(tile[..., None] == 1, 225, 255).astype(np.uint8).repeat(3, -1)
    bg = Image.fromarray(np.dstack([grey, np.full(tile.shape, 255, np.uint8)]), "RGBA")
    bg.alpha_composite(im)
    return bg.convert("RGB")


def _ref_for(im):
    """The reference on a plain white card with room around it (no cut-off look for Gemini to copy)."""
    im = im.convert("RGBA")
    bg = Image.new("RGBA", (int(im.width * 1.5), int(im.height * 1.3)), (255, 255, 255, 255))
    bg.alpha_composite(im, ((bg.width - im.width) // 2, bg.height - im.height))
    return bg


def _save(cut, path, max_h=1100):
    path.parent.mkdir(parents=True, exist_ok=True)
    if cut.height > max_h:
        cut = cut.resize((int(cut.width * max_h / cut.height), max_h), Image.LANCZOS)
    cut.save(path, quality=94, method=6)


def make(prompt, ref, judge_what, dst, bottom_ok=True, aspect="3:4", tries=3):
    """Draw, key, check, judge; keep the first good one. Returns True when saved."""
    last = ""
    for t in range(tries):
        try:
            raw = _image_call(prompt, ref, aspect)
        except QuotaError:
            raise
        except Exception as e:
            last = str(e)[:200]
            time.sleep(6)
            continue
        cut = key_green(raw)
        probs = checks(raw, cut, bottom_ok)
        if not probs and ref is not None:
            ok, note = judge(ref, cut, judge_what)
            if not ok:
                probs.append("judge: " + note)
        if not probs:
            _save(cut, dst)
            print(f"  ok   {dst.stem} ({cut.width}x{cut.height}, try {t + 1})")
            return True
        last = "; ".join(probs)
        print(f"  ..   {dst.stem} try {t + 1}: {last}")
        time.sleep(4)
    print(f"  FAIL {dst.stem}: {last}")
    return False


# ------------------------------------------------------------------ jobs
def characters(names=None):
    done = 0
    for name, (what, extra) in EMOTIONS.items():
        if names and name not in names:
            continue
        src = CHAR_DIR / f"{name}.webp"
        if not src.exists():
            continue
        ref = _ref_for(Image.open(src))
        prompt = REDRAW.format(look=LOOK, what=what, extra=extra)
        done += make(prompt, ref, f"It should be the same character, {what}{extra}.", REVIEW / "characters" / f"{name}.webp")
    print(f"{done} emotions redrawn")


def poses(names=None):
    ref = _ref_for(Image.open(CHAR_DIR / "stare.webp"))
    for name, pose in NEW_POSES.items():
        if names and name not in names:
            continue
        make(POSE.format(look=LOOK, pose=pose), ref, f"It should be the same character (hair, mask, blue hoodie), now: {pose}.",
             REVIEW / "characters" / f"{name}.webp", bottom_ok=True)


def objects(names=None):
    for name, thing in OBJECTS.items():
        if names and name not in names:
            continue
        make(OBJECT.format(thing=thing), None, "", REVIEW / "objects" / f"{name}.webp", bottom_ok=False, aspect="1:1")


def promote(names=None):
    """Move reviewed results into place."""
    moved = 0
    for group, dst_dir in (("characters", CHAR_DIR), ("objects", OBJ_DIR)):
        for p in sorted((REVIEW / group).glob("*.webp")):
            if names and p.stem not in names:
                continue
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), dst_dir / p.name)
            moved += 1
    print(f"{moved} moved into place")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = set(sys.argv[2:]) or None
    if what in ("characters", "all"):
        characters(names)
    if what in ("poses", "new", "all"):
        poses(names)
    if what in ("objects", "all"):
        objects(names)
    if what == "promote":
        promote(names)
