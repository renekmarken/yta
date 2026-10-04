"""Prepare the owner's MacBook / iPhone mock-up scenes for the review videos (run once).

  python tools/mockup_prep.py <uploads dir>

For each scene: a 4x Real-ESRGAN upscale (kept at 3840 px wide so the slow zoom stays sharp), and the
white screen measured exactly: its 4 corners (lines fitted to each edge and intersected, so rounded
corners, the notch or the Dynamic Island don't pull them in) and a soft mask of the screen itself
(the notch / island stay on top of the website). Writes assets/mockups/*.{jpg,png} + mockups.json.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ws_recut_characters as R  # noqa: E402  (the Real-ESRGAN upscaler)

OUT = ROOT / "assets" / "mockups"
SIZE = (3840, 2160)
FILES = {   # name: (file in the uploads folder, kind)
    "macbook_night_wall": ("83b54c76-image.png", "wall"),
    "macbook_night_desk": ("cb7430c1-image.png", "desk"),
    "macbook_day_wall": ("087747e8-image.png", "wall"),
    "macbook_day_desk": ("f38bef43-image.png", "desk"),
    "phone_day": ("33368154-image.png", "phone"),
    "phone_night": ("f3624d3b-image.png", "phone"),
}


def upscale(im, sess):
    rgb = R.upscale(sess, im.convert("RGB")).resize(SIZE, Image.LANCZOS)
    if im.mode == "RGBA":
        a = im.getchannel("A").resize(SIZE, Image.BICUBIC)
        rgb = rgb.convert("RGBA")
        rgb.putalpha(a)
    return rgb


def screen(im):
    """The white screen: soft mask + 4 corners (TL, TR, BR, BL) in pixels."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    lo = a.min(-1)
    white = (lo > 222).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    h, w = white.shape
    best = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA]
               - 4 * abs(stats[i, 0] + stats[i, 2] / 2 - w / 2))   # the big white thing near the middle
    m = (lab == best).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # soft edge: brightness ramp just around the region
    ring = cv2.dilate(m, np.ones((7, 7), np.uint8))
    soft = np.where(ring > 0, np.clip((lo - 150) / 70, 0, 1), 0) * 255
    soft = np.maximum(soft, m * 255).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float32)
    rect = cv2.boxPoints(cv2.minAreaRect(c))
    # order the rough rectangle TL, TR, BR, BL
    s, d = rect.sum(1), rect[:, 0] - rect[:, 1]
    rough = np.array([rect[np.argmin(s)], rect[np.argmax(d)], rect[np.argmax(s)], rect[np.argmin(d)]])
    lines = []
    for k in range(4):                            # each side: the contour points near it, middle 70%
        p, q = rough[k], rough[(k + 1) % 4]
        v = q - p
        L = np.linalg.norm(v)
        u = v / L
        nrm = np.array([-u[1], u[0]])
        t = (c - p) @ u / L
        dist = np.abs((c - p) @ nrm)
        sel = c[(t > 0.15) & (t < 0.85) & (dist < 0.06 * L + 12)]
        vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    corners = []
    for k in range(4):                            # corner k = side (k-1) x side k
        (p1, d1), (p2, d2) = lines[(k - 1) % 4], lines[k]
        A = np.array([d1, -d2]).T
        tt = np.linalg.solve(A, p2 - p1)
        corners.append((p1 + tt[0] * d1).tolist())
    return Image.fromarray(soft, "L"), corners


def main(src):
    src = Path(src)
    OUT.mkdir(parents=True, exist_ok=True)
    sess = R.esrgan()
    meta = {}
    for name, (f, kind) in FILES.items():
        im = Image.open(src / f)
        im = im.convert("RGBA") if kind == "desk" else im.convert("RGB")
        big = upscale(im, sess)
        if kind == "desk":
            big.save(OUT / f"{name}.png", optimize=True)
        else:
            big.save(OUT / f"{name}.jpg", quality=92)
        if kind in ("desk", "phone"):
            mask, corners = screen(big)
            mask.save(OUT / f"{name}_screen.png", optimize=True)
            meta[name] = {"corners": [[round(x, 1), round(y, 1)] for x, y in corners]}
            print(name, meta[name]["corners"])
        else:
            print(name)
    (OUT / "mockups.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/root/.claude/uploads/f1b30f34-9302-5b8a-8170-201b40e39121")
