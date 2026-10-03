"""Cut the owner's arrows and UI sheets (assets/whitescreen/source) into single transparent assets.

arrows_sheet: every arrow with its tail and tip (so it can be turned to point exactly at a spot),
the hand-drawn rings, the burst marks, the underline swooshes and the X.
ui_sheet: subscribe buttons, bells, like/dislike, comment/share buttons, the play buttons, LIVE.

  python tools/ws_cut_sheets.py
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "whitescreen" / "source"
OUT = ROOT / "assets" / "whitescreen"

# name: (box x0, y0, x1, y1 on the sheet, tail x, y, tip x, y)
ARROWS = {
    "block": ((15, 8, 295, 172), (25, 125), (282, 82)),
    "swoop_white": ((295, 8, 532, 190), (305, 180), (526, 22)),
    "hook_up": ((465, 5, 680, 188), (470, 178), (669, 10)),
    "bold_straight": ((688, 15, 978, 187), (695, 100), (973, 97)),
    "brush_up": ((965, 20, 1232, 188), (975, 180), (1223, 60)),
    "bold_swoop": ((1225, 5, 1528, 202), (1232, 195), (1521, 60)),
    "curl_down": ((12, 175, 228, 352), (20, 252), (190, 344)),
    "bold_curl_down": ((215, 190, 407, 354), (220, 205), (365, 350)),
    "elbow": ((422, 195, 602, 347), (435, 335), (599, 245)),
    "hook_up2": ((595, 170, 802, 347), (600, 330), (745, 175)),
    "brush_right": ((775, 200, 1050, 337), (780, 330), (1044, 248)),
    "curl_down2": ((1055, 188, 1247, 352), (1060, 225), (1228, 346)),
    "arc_down": ((1250, 198, 1527, 324), (1255, 295), (1517, 305)),
    "wavy": ((10, 365, 237, 452), (20, 400), (231, 405)),
    "arc": ((222, 350, 462, 464), (228, 455), (456, 385)),
    "loop": ((440, 340, 680, 467), (445, 445), (673, 365)),
    "dashed_arc": ((680, 340, 897, 460), (688, 445), (893, 393)),
    "bold_up": ((888, 350, 1102, 480), (893, 470), (1097, 383)),
    "arc2": ((1112, 350, 1332, 464), (1118, 455), (1326, 395)),
    "zigzag": ((1330, 335, 1527, 472), (1335, 465), (1506, 345)),
    "dashed": ((10, 488, 250, 587), (15, 575), (244, 535)),
    "brush_arc": ((228, 478, 497, 617), (232, 610), (491, 512)),
    "bold_down": ((498, 478, 697, 627), (505, 490), (669, 616)),
    "curve_down": ((668, 470, 857, 622), (673, 490), (821, 613)),
    "loop2": ((858, 478, 1074, 614), (865, 540), (1066, 545)),
    "brush_right2": ((1078, 478, 1327, 610), (1083, 595), (1321, 530)),
    "bold_block": ((1330, 478, 1527, 614), (1338, 545), (1521, 540)),
    "brush_long": ((490, 895, 747, 1017), (495, 1005), (741, 915)),
}
MARKS = {   # rings, bursts, underlines, X
    "ring_oval": (12, 618, 256, 762), "ring_scribble": (258, 618, 453, 772), "ring_thick": (458, 615, 643, 784),
    "ring_round": (648, 615, 809, 784), "ring_dashed": (815, 615, 976, 784), "ring_double": (980, 615, 1169, 784),
    "ring_double2": (1172, 615, 1356, 784), "ring_brush": (1358, 615, 1527, 784),
    "burst_big": (8, 775, 244, 946), "burst_mid": (250, 795, 419, 906), "burst_drops": (415, 805, 623, 931),
    "burst_small": (690, 785, 901, 901), "underline": (168, 905, 461, 1004), "underline_long": (780, 875, 1096, 996),
    "cross": (1050, 800, 1262, 1013), "ring_arrow": (1260, 800, 1531, 1002),
}


def cut(im, box, alpha, clip=False):
    """The parts whose centre lies in box (neighbours that reach in are left out). clip: also cut
    at the box edge (for pieces that touch their neighbour on the sheet)."""
    x0, y0, x1, y1 = box
    solid = alpha > 20
    lab, n = ndimage.label(solid)
    centres = ndimage.center_of_mass(solid, lab, range(1, n + 1))
    inbox = np.zeros_like(solid)
    inbox[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = True
    sizes = ndimage.sum(solid, lab, range(1, n + 1))
    inside = ndimage.sum(solid & inbox, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    for i, (cy, cx) in enumerate(centres, 1):
        keep[i] = (x0 <= cx <= x1 and y0 <= cy <= y1) or (clip and inside[i - 1] > sizes[i - 1] * 0.3)
    mask = ndimage.binary_dilation(keep[lab], iterations=1)
    if clip:
        mask &= inbox
    arr = np.asarray(im).copy()
    arr[..., 3] = (arr[..., 3] * mask).astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")
    bb = out.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    return out.crop(bb), bb


def snap(img, tail, tip, r=40):
    """Move the marked tail/tip onto the arrow's very ends: the opaque pixel near the mark that lies
    furthest out along the arrow's direction."""
    a = np.asarray(img)[..., 3] > 100
    ys, xs = np.nonzero(a)
    pts = np.stack([xs, ys], 1).astype(float)
    t, h = np.array(tail, float), np.array(tip, float)
    d = (h - t) / max(1e-6, np.linalg.norm(h - t))
    out = []
    for mark, sign in ((t, -1), (h, 1)):
        near = pts[np.linalg.norm(pts - mark, axis=1) < r]
        if len(near) == 0:
            out.append([float(mark[0]), float(mark[1])])
            continue
        best = near[np.argmax((near @ d) * sign)]
        out.append([float(best[0]), float(best[1])])
    return out


def arrows():
    im = Image.open(SRC / "arrows_sheet.webp").convert("RGBA")
    a = np.asarray(im)[..., 3]
    d = OUT / "arrows"
    d.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, (box, tail, tip) in ARROWS.items():
        c, bb = cut(im, box, a)
        c.save(d / f"{name}.webp", lossless=True)
        tl, tp = snap(c, (tail[0] - bb[0], tail[1] - bb[1]), (tip[0] - bb[0], tip[1] - bb[1]))
        meta[name] = {"tail": tl, "tip": tp,
                      "size": list(c.size), "outlined": name.startswith("bold")}
    for name, box in MARKS.items():
        c, _ = cut(im, box, a)
        c.save(d / f"{name}.webp", lossless=True)
    (d / "arrows.json").write_text(json.dumps(meta, indent=1))
    print(f"{len(ARROWS)} arrows, {len(MARKS)} marks")


UI = {
    "subscribe_red_cursor": (30, 45, 495, 200),
    "subscribed_grey": (1012, 52, 1510, 160), "subscribe_black_hand": (25, 190, 470, 330),
    "subscribed_grey_ring": (1012, 205, 1510, 318),
    "bell_white": (25, 355, 145, 495), "bell_red_ring": (168, 350, 318, 495), "bell_blue_ring": (343, 350, 493, 497),
    "bell_black": (522, 355, 642, 497), "bell_white_1": (668, 355, 795, 497), "bell_white_9": (820, 355, 962, 497),
    "bell_red_1": (988, 345, 1130, 497), "bell_blue_9": (1160, 345, 1305, 497), "bell_gold_ring": (1350, 345, 1505, 497),
    "like_white": (25, 525, 160, 660), "like_blue": (172, 520, 315, 662), "like_circle": (333, 515, 482, 662),
    "dislike_white": (505, 525, 630, 660), "dislike_red": (650, 525, 785, 660), "dislike_circle": (805, 525, 945, 660),
    "like_25k": (993, 507, 1228, 590), "like_1_2m": (1252, 507, 1505, 590), "dislike_1_3k": (998, 603, 1228, 688),
    "like_100k": (1252, 600, 1505, 690), "comment_white": (28, 685, 318, 785), "comment_black": (343, 685, 648, 785),
    "share_red": (680, 685, 980, 785), "share_white": (1012, 700, 1125, 815), "share_red_circle": (1140, 700, 1262, 815),
    "share_black": (1278, 700, 1400, 815), "dots": (1440, 710, 1475, 808), "play_big": (25, 805, 262, 970),
    "play_red_circle": (282, 805, 440, 970), "play_black_circle": (457, 805, 622, 970), "live": (640, 830, 862, 940),
    "progress_bar": (888, 838, 1512, 868), "ctl_play": (892, 893, 942, 950), "ctl_pause": (965, 893, 1012, 950),
    "ctl_volume": (1035, 890, 1095, 950), "ctl_slider": (1112, 898, 1285, 940), "ctl_settings": (1298, 893, 1355, 950),
    "ctl_theater": (1375, 895, 1440, 948), "ctl_fullscreen": (1455, 893, 1508, 950),
}


def ui():
    im = Image.open(SRC / "ui_sheet.webp").convert("RGBA")
    a = np.asarray(im)[..., 3]
    d = OUT / "ui"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.webp"):
        old.unlink()
    for name, box in UI.items():
        c, _ = cut(im, box, a, clip=True)
        c.save(d / f"{name}.webp", lossless=True)
    print(f"{len(UI)} UI pieces")


if __name__ == "__main__":
    arrows()
    ui()
