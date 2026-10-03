"""Re-cut the White Screen character's emotions from the owner's sheet, cleanly and in high quality.

The sheet (assets/whitescreen/source/character_sheet.webp) packs 27 emotions in a 7x4 grid on a blue
background, with the hoods almost touching. Cutting along the grid chops hoods and arms flat and
leaves bits of the neighbours. Here every character is cut along its own outline instead:

  1 a window around the character, 3 cells wide (its neighbours included, so nothing is chopped)
  2 4x upscale with Real-ESRGAN (realesr-general-x4v3, ONNX, CPU)
  3 BiRefNet segmentation of the window (rembg), the mask scaled to the 4x picture
  4 the touching neighbours are split off along the narrowest point (watershed from each face);
    loose bits (a "?", Zzz, anger mark, heart...) go to the character they are next to
  5 a hoodie side cut straight by a neighbour is rebuilt from the mirrored other side
  6 a straight, clean cut at the bottom of the hoodie; soft 1-2 px edge; checks that nothing touches
    the window's sides or top (= cut off)

  python tools/ws_recut_characters.py [name ...]
Needs: rembg (birefnet-general-lite), onnxruntime, scikit-image, scipy. Writes assets/whitescreen/characters/.
"""
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageChops, ImageFilter
from scipy import ndimage
from skimage.segmentation import watershed

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "assets" / "whitescreen" / "source" / "character_sheet.webp"
OUT = ROOT / "assets" / "whitescreen" / "characters"
ESRGAN = Path.home() / ".models" / "realesr-general-x4v3.onnx"
ESRGAN_URL = "https://huggingface.co/Samo629/real-esrgan-onnx/resolve/main/realesr-general-x4v3.onnx"
COLS, ROWS = 7, 4
GRID = [
    ["smug", "thumbs_up", "shocked", "wink_point", "confused", "angry", "starstruck"],
    ["facepalm", "sleepy", "shy", "nervous", "thinking", "laughing_point", "crying"],
    ["shush", "cool", "wave", "unimpressed", "alert", "love", "scared"],
    ["stare", "side_eye", "determined", "celebrate", "relaxed", "thumbs_down", None],
]
SCALE = 4
REACH_UP = {"celebrate": 0.3, "nervous": -0.07}
# leftover background the segmenter took for hoodie: polygons (fractions of the finished cut) to erase
ERASE = {"nervous": [[(0, 0), (0.29, 0), (0.24, 0.06), (0.18, 0.15), (0.1, 0.165), (0, 0.2)]]}
# zones (fractions of the character's box) where background-coloured pixels are erased
ERASE_BG = {"nervous": [[(0, 0), (0.3, 0), (0.2, 0.2), (0.12, 0.42), (0, 0.42)]]}   # how far (in rows) a pose reaches above its own row


def esrgan():
    if not ESRGAN.exists():
        import urllib.request
        ESRGAN.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(ESRGAN_URL, ESRGAN)
    return ort.InferenceSession(str(ESRGAN), providers=["CPUExecutionProvider"])


def upscale(sess, im, tile=160, pad=12):
    """4x, in overlapping tiles (keeps memory small)."""
    a = np.asarray(im.convert("RGB")).astype(np.float32) / 255
    h, w, _ = a.shape
    out = np.zeros((h * SCALE, w * SCALE, 3), np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
            t = a[y0:y1, x0:x1].transpose(2, 0, 1)[None]
            r = sess.run(None, {"input": t})[0][0].transpose(1, 2, 0)
            oy, ox = (y - y0) * SCALE, (x - x0) * SCALE
            th, tw = min(tile, h - y) * SCALE, min(tile, w - x) * SCALE
            out[y * SCALE:y * SCALE + th, x * SCALE:x * SCALE + tw] = r[oy:oy + th, ox:ox + tw]
    return Image.fromarray((out.clip(0, 1) * 255 + 0.5).astype(np.uint8))


def segment(session, im):
    from rembg import remove
    cut = remove(im, session=session, post_process_mask=False)
    return np.asarray(cut.getchannel("A")).astype(np.float32) / 255


def cut_one(sheet, r, c, up_sess, seg_sess, name=""):
    W, H = sheet.size
    cw, ch = W / COLS, H / ROWS
    # the window: the cell plus most of each neighbour (so nothing of this character is outside it)
    wx0, wx1 = int(max(0, (c - 0.75) * cw)), int(min(W, (c + 1.75) * cw))
    wy0, wy1 = int(max(0, (r - 0.45) * ch)), int(min(H, (r + 1.12) * ch))
    win = sheet.crop((wx0, wy0, wx1, wy1)).convert("RGB")
    big = upscale(up_sess, win)
    # BiRefNet reads the original picture (on the upscaled one it mistakes the smoothed blue background
    # for the hoodie); its mask is scaled to the 4x picture and its edge sharpened again
    small = segment(seg_sess, win.resize((win.width * 2, win.height * 2), Image.LANCZOS))
    alpha = np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize(big.size, Image.BICUBIC)) / 255.0
    alpha = np.clip((alpha - 0.5) * 2.4 + 0.5, 0, 1)
    mask = alpha > 0.5
    # markers: a face for every character that reaches into the window
    markers = np.zeros(mask.shape, np.int32)
    k, own = 1, None
    for rr in range(max(0, r - 1), min(ROWS, r + 2)):
        for cc in range(max(0, c - 1), min(COLS, c + 2)):
            fx = ((cc + 0.5) * cw - wx0) * SCALE
            fy = ((rr + 0.48) * ch - wy0) * SCALE
            fyb = ((rr + 0.97) * ch - wy0) * SCALE               # the bottom of that character's row
            if 0 <= fx < mask.shape[1] and fyb > 0 and fy < mask.shape[0]:
                # a strip from the face down to the bottom of its row: the body stays with its own face
                y0, y1 = int(max(0, fy - 40)), int(min(mask.shape[0], fyb))
                x0, x1 = int(max(0, fx - 30)), int(min(mask.shape[1], fx + 30))
                markers[y0:y1, x0:x1] = k
                # the body (lower part of the row) anchored wide: neighbours' bodies split halfway
                by0 = int(max(0, fy + 0.22 * ch * SCALE))
                bx0, bx1 = int(max(0, fx - 0.3 * cw * SCALE)), int(min(mask.shape[1], fx + 0.3 * cw * SCALE))
                if by0 < y1:
                    markers[by0:y1, bx0:bx1] = np.where(mask[by0:y1, bx0:bx1], k, markers[by0:y1, bx0:bx1])
                if rr == r and cc == c:
                    own = k
                k += 1
    dist = ndimage.distance_transform_edt(mask)
    labels = watershed(-dist, markers, mask=mask)
    # loose bits (no face reached them): to the nearest face
    lab, n = ndimage.label(mask & (labels == 0))
    if n:
        pts = {i: np.argwhere(markers == i).mean(0) for i in range(1, k)}
        # own cell (in window pixels): a loose bit only belongs to this character if it sits in it
        ox0, ox1 = ((c - 0.1) * cw - wx0) * SCALE, ((c + 1.1) * cw - wx0) * SCALE
        oy0, oy1 = ((r - 0.3) * ch - wy0) * SCALE, ((r + 1) * ch - wy0) * SCALE
        for i, sl in enumerate(ndimage.find_objects(lab), 1):
            cy = (sl[0].start + sl[0].stop) / 2
            cx = (sl[1].start + sl[1].stop) / 2
            best = min(pts, key=lambda j: (pts[j][0] - cy) ** 2 + (pts[j][1] - cx) ** 2)
            if best == own and not (ox0 <= cx <= ox1 and oy0 <= cy <= oy1):
                best = -1                                       # someone else's (their face is outside the window)
            labels[lab == i] = best
    region = labels == own
    # keep only the main body + bits close to it (drops specks of the neighbours)
    lab, n = ndimage.label(region)
    if n > 1:
        sizes = ndimage.sum(region, lab, range(1, n + 1))
        main = 1 + int(np.argmax(sizes))
        near = ndimage.binary_dilation(lab == main, iterations=60)
        sl = ndimage.find_objects(lab)
        ox0, ox1 = ((c - 0.1) * cw - wx0) * SCALE, ((c + 1.1) * cw - wx0) * SCALE
        oy0 = ((r - 0.3) * ch - wy0) * SCALE
        keep = [i for i in range(1, n + 1) if i == main or (
            sizes[i - 1] > 400 and (near & (lab == i)).any()
            and ox0 <= (sl[i - 1][1].start + sl[i - 1][1].stop) / 2 <= ox1
            and (sl[i - 1][0].start + sl[i - 1][0].stop) / 2 >= oy0)]
        region = np.isin(lab, keep)
    # nothing above the character's own row (that's the row above's hands and hems), except where
    # the pose really reaches up (celebrate's fists)
    top = int(((r - REACH_UP.get(name, 0.03)) * ch - wy0) * SCALE)
    if top > 0:
        region[:top] = False
    # drop anything joined on by a thin neck (a neighbour's fingertip, a chunk of background)
    opened = ndimage.binary_opening(region, structure=np.ones((3, 3)), iterations=10)
    lab, n = ndimage.label(opened)
    if n:
        sizes = ndimage.sum(opened, lab, range(1, n + 1))
        body = lab == 1 + int(np.argmax(sizes))
        attached = ndimage.binary_propagation(body, mask=region)
        keep_body = region & ndimage.binary_dilation(body, iterations=12)
        region = keep_body | (region & ~attached)              # separate props (?, Zzz, heart) stay
    soft = ndimage.binary_dilation(region, iterations=3)
    a = (alpha * soft).clip(0, 1)
    # leftover background in a marked zone: pixels of the sheet's background colour there are erased
    if ERASE_BG.get(name):
        from PIL import ImageDraw
        rgb = np.asarray(big).astype(np.float32)
        out_px = alpha < 0.05
        bgcol = np.median(rgb[out_px], axis=0)
        bb0 = Image.fromarray((a * 255).astype(np.uint8)).point(lambda v: 255 if v > 20 else 0).getbbox()
        zone = Image.new("L", big.size, 0)
        bw, bh = bb0[2] - bb0[0], bb0[3] - bb0[1]
        for poly in ERASE_BG[name]:
            ImageDraw.Draw(zone).polygon([(bb0[0] + x * bw, bb0[1] + y * bh) for x, y in poly], fill=255)
        R_, G_, B_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        dull_blue = (B_ < 205) & (B_ > R_ + 50) & (B_ > G_ + 40)   # the steel-blue backdrop, not the bright hood
        hit = (np.asarray(zone) > 0) & (dull_blue | (np.sqrt(((rgb - bgcol) ** 2).sum(-1)) < 30))
        hit = ndimage.binary_dilation(ndimage.binary_opening(hit, iterations=1), iterations=1)
        a[hit] = 0

    # the hoodie's bottom: a straight cut where the character's own row ends
    bottom = int(((r + 1) * ch - wy0) * SCALE) - 6
    a[bottom:] = 0
    rgba = np.dstack([np.asarray(big), (a * 255).astype(np.uint8)])
    img = Image.fromarray(rgba, "RGBA")
    A = img.getchannel("A").filter(ImageFilter.GaussianBlur(0.7))
    img.putalpha(A)
    bb = A.point(lambda v: 255 if v > 20 else 0).getbbox()
    problems = []
    if bb[0] <= 2 and wx0 > 0:
        problems.append("touches left")
    if bb[2] >= img.width - 2 and wx1 < W:
        problems.append("touches right")
    if bb[1] <= 2 and wy0 > 0:
        problems.append("touches top")
    img = img.crop(bb)
    if ERASE.get(name):
        from PIL import ImageDraw
        hole = Image.new("L", img.size, 255)
        for poly in ERASE[name]:
            ImageDraw.Draw(hole).polygon([(x * img.width, y * img.height) for x, y in poly], fill=0)
        img.putalpha(ImageChops.multiply(img.getchannel("A"), hole.filter(ImageFilter.GaussianBlur(1))))
        img = img.crop(img.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox())
    img = symmetrize(img)
    # specks: tiny islands left over from the sheet
    A2 = np.asarray(img.getchannel("A")) > 40
    lab, n = ndimage.label(A2)
    if n > 1:
        sizes = ndimage.sum(A2, lab, range(1, n + 1))
        drop = np.isin(lab, [i + 1 for i, z in enumerate(sizes) if z < max(1500, sizes.max() * 0.004)])
        arr = np.asarray(img).copy()
        arr[..., 3][ndimage.binary_dilation(drop, iterations=2)] = 0
        img = Image.fromarray(arr, "RGBA")
        img = img.crop(img.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox())
    if img.height > 1100:
        img = img.resize((int(img.width * 1100 / img.height), 1100), Image.LANCZOS)
    return img, problems


def symmetrize(img, from_y=0.3):
    """Where the hoodie was cut straight by a neighbour on the sheet, rebuild it from the other
    side: the hoodie is close to symmetric around the face. Only hoodie-blue pixels are copied
    (no hands or props get mirrored), only below from_y, and only outside the current outline."""
    a = np.asarray(img).astype(np.float32)
    al = a[..., 3]
    h, w = al.shape
    dark = (a[..., :3].max(-1) < 45) & (al > 200)                  # the black mask: the face's centre
    dark[int(h * 0.75):] = False
    if dark.sum() < 200:
        return img
    axis = np.argwhere(dark)[:, 1].mean()
    pad = int(max(0, 2 * axis - (w - 1), (w - 1) - 2 * axis)) + 4    # room for the mirrored side
    canvas = np.zeros((h, w + 2 * pad, 4), np.float32)
    canvas[:, pad:pad + w] = a
    ax = axis + pad
    xs = np.arange(canvas.shape[1])
    src = np.clip(np.round(2 * ax - xs).astype(int), 0, canvas.shape[1] - 1)
    mir = canvas[:, src]
    r, g, b = mir[..., 0], mir[..., 1], mir[..., 2]
    hoodie = (b > 150) & (b > r + 80) & (b > g + 40) & (mir[..., 3] > 128)
    fill = hoodie & (canvas[..., 3] < 30)
    fill[: int(h * from_y)] = False
    # only fill next to a straight cut: rows where this side is clearly shorter than the other
    lab, n = ndimage.label(fill)
    if n:
        sizes = ndimage.sum(fill, lab, range(1, n + 1))
        body = ndimage.binary_dilation(canvas[..., 3] > 128, iterations=2)
        touching = set(np.unique(lab[body & (lab > 0)]))
        # a rebuilt piece must hang on the body along a long edge (a cut), not touch it at a corner
        good = []
        for i, z in enumerate(sizes, 1):
            if z > 900 and i in touching and ((lab == i) & body).sum() > 0.25 * h:
                good.append(i)
        fill = np.isin(lab, good)
    if not fill.any():
        return img
    soft = ndimage.gaussian_filter(fill.astype(np.float32), 1.0)
    out = canvas.copy()
    for ch in range(3):
        out[..., ch] = np.where(fill, mir[..., ch], canvas[..., ch])
    out[..., 3] = np.maximum(canvas[..., 3], np.where(fill | (soft > 0.5), np.minimum(mir[..., 3], 255), 0))
    res = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA")
    return res.crop(res.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox())


def main(names=None):
    from rembg import new_session
    sheet = Image.open(SHEET).convert("RGB")
    up = esrgan()
    seg = new_session("birefnet-general-lite")
    OUT.mkdir(parents=True, exist_ok=True)
    for r, row in enumerate(GRID):
        for c, name in enumerate(row):
            if not name or (names and name not in names):
                continue
            img, probs = cut_one(sheet, r, c, up, seg, name)
            img.save(OUT / f"{name}.webp", quality=94, method=6)
            print(f"  {name:15s} {img.width}x{img.height}  {'; '.join(probs) or 'ok'}", flush=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
