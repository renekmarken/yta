"""Redraw the White Screen character in full quality with Gemini's image model (and add new poses).

The emotions cut out of the owner's sheet are small (about 220x256 px each). This asks Gemini's image
model to redraw each one at full resolution, same character, same pose and expression, on a flat
green screen; the green is keyed out and the result replaces the cut-out only if it looks right
(enough of the picture is the character, sensible shape). Anything that fails keeps the cut-out.

  python tools/ws_hd_assets.py characters      # redraw the 27 emotions
  python tools/ws_hd_assets.py new             # add the extra poses in NEW_POSES
  python tools/ws_hd_assets.py all

Needs GEMINI_API_KEY (an AI Studio key with image generation). Runs in the
"White Screen: improve assets" workflow, which commits the results.
"""
import base64
import io
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from studio import config  # noqa: E402

CHAR_DIR = config.ASSETS_DIR / "whitescreen" / "characters"
MODELS = ["gemini-2.5-flash-image", "gemini-2.5-flash-image-preview", "gemini-2.0-flash-preview-image-generation"]
AISTUDIO = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
VERTEX = "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"

REDRAW = ("Redraw this exact cartoon character in high quality at high resolution: the same young character with "
          "messy brown hair, a black face mask and a bright blue hoodie, the exact same pose, hands, expression and "
          "any small symbol next to them (heart, sweat drop, anger mark, stars...). Same glossy 3D cartoon style. "
          "Show the head and upper body, centred, filling the image, nothing cut off at the sides. "
          "Put it on a perfectly flat, pure green (#00FF00) background with no shadow, no floor, no gradient, "
          "no text. Do not add anything else.")
NEW_POSES = {
    "point_down": "pointing down with one finger at something below them, excited, eyes wide",
    "phone_shock": "holding a smartphone and staring at it in shock, mouth area hidden by the mask, eyes huge",
    "cover_eyes": "covering their eyes with both hands, peeking through the fingers",
    "pray": "hands pressed together pleading, big hopeful eyes",
    "point_viewer": "pointing straight at the viewer with a confident, mischievous look",
    "mind_blown": "both hands on the head, completely shocked, eyes wide",
}
POSE = ("Draw this exact same cartoon character (messy brown hair, black face mask, bright blue hoodie, same glossy "
        "3D cartoon style) {pose}. Head and upper body, centred, filling the image. Perfectly flat pure green "
        "(#00FF00) background, no shadow, no text, nothing else.")


def _image_call(prompt, ref: Image.Image):
    key = config.GEMINI_API_KEY
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set")
    buf = io.BytesIO()
    ref.convert("RGB").save(buf, "PNG")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/png",
                                                     "data": base64.b64encode(buf.getvalue()).decode()}}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
    errors = []
    for model in MODELS:
        for url, kw in ((AISTUDIO.format(m=model), {"headers": {"x-goog-api-key": key}}),
                        (VERTEX.format(m=model), {"params": {"key": key}})):
            for attempt in range(3):
                try:
                    r = requests.post(url, json=body, timeout=180, **kw)
                except requests.RequestException as e:
                    errors.append(str(e)[:120])
                    time.sleep(5)
                    continue
                if r.status_code == 429:
                    time.sleep(20 * (attempt + 1))
                    continue
                if r.status_code != 200:
                    errors.append(f"{model} {r.status_code}: {r.text[:160]}")
                    break
                for cand in r.json().get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
                        if data:
                            return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
                errors.append(f"{model}: no image in the answer")
                break
    raise RuntimeError(" | ".join(errors[-3:]))


def key_green(im: Image.Image):
    """Green screen -> transparent, with the green fringe removed from the edges."""
    a = np.asarray(im).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)                    # how much greener than the other channels
    alpha = np.clip(1 - (greenness - 40) / 80, 0, 1)    # >120 greener: background
    spill = np.clip(greenness, 0, None)
    g2 = np.where(spill > 0, g - spill * 0.85, g)       # de-spill the edge pixels
    out = np.dstack([r, g2, b, alpha * 255]).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    a8 = img.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    img.putalpha(a8)
    bb = a8.point(lambda v: 255 if v > 30 else 0).getbbox()
    return img.crop(bb) if bb else img


def looks_right(cut: Image.Image, ref: Image.Image):
    a = np.asarray(cut.getchannel("A")) > 128
    cover = a.mean()
    ratio = cut.width / max(1, cut.height)
    ref_ratio = ref.width / max(1, ref.height)
    return cut.height >= 600 and 0.35 < cover < 0.97 and abs(ratio - ref_ratio) < 0.45


def _save(cut, name):
    if cut.height > 1100:
        cut = cut.resize((int(cut.width * 1100 / cut.height), 1100), Image.LANCZOS)
    cut.save(CHAR_DIR / f"{name}.webp", quality=92, method=6)


def on_green(im):
    bg = Image.new("RGBA", (im.width + 80, im.height + 40), (0, 255, 0, 255))
    bg.alpha_composite(im, (40, 40))
    return bg


def redraw_characters():
    done = 0
    for p in sorted(CHAR_DIR.glob("*.webp")):
        ref = Image.open(p).convert("RGBA")
        if ref.height >= 900:                           # already redrawn
            continue
        try:
            got = key_green(_image_call(REDRAW, on_green(ref)))
            if looks_right(got, ref):
                _save(got, p.stem)
                done += 1
                print(f"  redrawn: {p.stem} ({got.width}x{got.height})")
            else:
                print(f"  ! {p.stem}: the redraw didn't look right, keeping the cut-out")
        except Exception as e:
            print(f"  ! {p.stem}: {str(e)[:200]}")
        time.sleep(4)
    print(f"{done} emotions redrawn")


def new_poses():
    ref = Image.open(CHAR_DIR / "stare.webp").convert("RGBA")
    for name, pose in NEW_POSES.items():
        if (CHAR_DIR / f"{name}.webp").exists():
            continue
        try:
            got = key_green(_image_call(POSE.format(pose=pose), on_green(ref)))
            if looks_right(got, ref):
                _save(got, name)
                print(f"  new pose: {name}")
            else:
                print(f"  ! {name}: didn't look right, skipped")
        except Exception as e:
            print(f"  ! {name}: {str(e)[:200]}")
        time.sleep(4)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("characters", "all"):
        redraw_characters()
    if what in ("new", "all"):
        new_poses()
