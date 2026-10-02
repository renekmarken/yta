"""The product's real logo, checked, so a thumbnail never shows a blank block or a random icon.

  candidates   the site's own logos (header image, inline SVG, touch icon, favicon...) found by the
               crawler, plus the brand's icon from public icon services (Google, DuckDuckGo,
               icon.horse) and, when it answers, Wikidata's official logo
  check()      throws out what can't be a logo: empty or see-through images, plain blocks of one
               colour (the "blank white block"), and tiny icons
  choose()     Gemini looks at the survivors and picks the one that really is this brand's logo
               (not a menu icon, an app-store badge, a partner's logo or a photo); without Gemini
               the site's own header logo wins. If nothing passes, there is no logo and the
               thumbnails show the brand name as a wordmark instead.
"""
import base64
import io
import shutil
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageStat

from . import ai

UA = {"User-Agent": "site-review-studio/1.0 (https://github.com/renekmarken/yta; logo lookup) python-requests"}


# ------------------------------------------------------------------ is it a picture at all?
def check(path):
    """None when the image can be a logo, else the reason it can't."""
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return "unreadable"
    a = im.getchannel("A")
    box = a.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not box:
        return "empty"
    im = im.crop(box)
    if max(im.size) < 40:
        return "too small"
    a = im.getchannel("A")
    solid = a.point(lambda v: 255 if v > 40 else 0)
    cover = ImageStat.Stat(solid).mean[0] / 255
    if cover < 0.03:
        return "almost empty"
    # a plain block: (nearly) one colour wherever it's visible
    rgb = im.convert("RGB")
    sd = ImageStat.Stat(rgb, mask=solid).stddev
    edges = cover < 0.97                                 # transparent parts make a shape
    if max(sd) < 6 and not edges:
        return "blank block"
    if max(sd) < 6 and edges:
        # a single-colour shape is fine (a white wordmark), unless it's just a filled rectangle
        inner = solid.crop((solid.width // 10, solid.height // 10, solid.width * 9 // 10, solid.height * 9 // 10))
        if ImageStat.Stat(inner).mean[0] / 255 > 0.97:
            return "blank block"
    return None


def placeholder(im):
    """Icon services answer unknown sites with a generated letter: a grey letter on a flat light-grey
    square. That is not the brand's logo."""
    rgb = im.convert("RGB")
    small = rgb.resize((48, 48))
    hsv = small.convert("HSV")
    if ImageStat.Stat(hsv).mean[1] > 12:                 # has real colour: not the grey placeholder
        return False
    corner = small.getpixel((2, 2))
    return 190 <= sum(corner) / 3 <= 245 and max(corner) - min(corner) < 8


def has_name_shape(path):
    """Rough guess without AI: a wide image is a wordmark (has the name), a squarish one an icon."""
    im = Image.open(path)
    return im.width / max(1, im.height) > 1.8


# ------------------------------------------------------------------ outside sources
def _get(url, timeout=15):
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        return r if r.status_code == 200 and len(r.content) > 300 else None
    except requests.RequestException:
        return None


def _wikidata(brand, domain):
    """The official logo file from Wikidata, for the item whose website is this domain."""
    r = _get(f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quote(brand)}"
             f"&language=en&format=json&limit=7")
    try:
        ids = [x["id"] for x in r.json().get("search", [])] if r else []
    except ValueError:
        return None
    if not ids:
        return None
    r = _get(f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={'|'.join(ids)}&props=claims&format=json")
    try:
        ents = r.json()["entities"] if r else {}
    except (ValueError, KeyError):
        return None
    root = domain.lower().replace("www.", "")
    for q in ids:
        claims = ents.get(q, {}).get("claims", {})
        sites = [str(c["mainsnak"].get("datavalue", {}).get("value", "")).lower() for c in claims.get("P856", [])]
        logos = [c["mainsnak"].get("datavalue", {}).get("value") for c in claims.get("P154", [])]
        if logos and any(root in s for s in sites):
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(logos[0])}?width=800"
    return None


def outside_candidates(brand, domain, out_dir: Path):
    """Download the brand's logo/icon from public sources. Returns local files (any format)."""
    root = domain.lower().replace("www.", "")
    urls = []
    try:
        w = _wikidata(brand, root)
        if w:
            urls.append(("wikidata", w))
    except Exception:
        pass
    urls += [("google", f"https://www.google.com/s2/favicons?domain={root}&sz=256"),
             ("iconhorse", f"https://icon.horse/icon/{root}"),
             ("duckduckgo", f"https://icons.duckduckgo.com/ip3/{root}.ico")]
    files = []
    for name, u in urls:
        r = _get(u)
        if not r:
            continue
        ctype = r.headers.get("content-type", "")
        if "html" in ctype:
            continue
        ext = ".svg" if "svg" in ctype else ".img"
        if ext == ".img":
            try:
                im = Image.open(io.BytesIO(r.content))
                if max(im.size) < 64 or placeholder(im):  # blurry 16px favicon / generated letter
                    continue
            except Exception:
                continue
        p = out_dir / f"logo_src_{name}{ext}"
        p.write_bytes(r.content)
        files.append(p)
    return files


# ------------------------------------------------------------------ to PNG, and the pick
def render(srcs, out_dir: Path):
    """Every source (svg/ico/webp/png...) as a trimmed transparent PNG, via one Chromium."""
    from playwright.sync_api import sync_playwright
    outs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 700})
        for i, src in enumerate(srcs):
            data = src.read_bytes()
            head = data[:400].lower()
            mime = ("image/svg+xml" if b"<svg" in head or src.suffix == ".svg" else
                    "image/x-icon" if data[:4] == b"\x00\x00\x01\x00" else "image/png")
            uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
            pg.set_content("<html><body style='margin:0;background:transparent'>"
                           f"<img id=l src='{uri}' style='max-width:1200px;max-height:500px;"
                           "min-height:240px;object-fit:contain'></body></html>")
            pg.wait_for_timeout(300)
            out = out_dir / f"logo_cand_{i}.png"
            try:
                pg.locator("#l").screenshot(path=str(out), omit_background=True, timeout=5000)
                im = Image.open(out).convert("RGBA")
                bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
                if not bbox:
                    continue
                im = im.crop(bbox)
                if im.width < 24 or im.height < 12:
                    continue
                im.save(out)
                outs.append((out, src))
            except Exception:
                continue
        b.close()
    return outs


PICK_PROMPT = """These images are candidate logos collected for the product "{brand}" (website {domain}),
to be shown big in the corner of a YouTube thumbnail. Each is shown on a grey background.
Which ONE is this product's own, real logo? Prefer the full logo with the name (wordmark) when it is
crisp; otherwise the brand's own icon/app icon.
NOT acceptable: empty or blank images, plain shapes or blocks, generic icons (menu, arrow, cart,
user, search, globe, flag, lock), another company's logo (App Store, Google Play, payment cards,
banks, press, partners, awards, cookie/privacy badges), photos, banners and screenshots, a logo
of a different brand, or something unreadably blurry.
Return ONLY JSON: {{"index": the image number (1-{n}), or 0 if none is acceptable,
 "has_name": true if the chosen image shows the brand's name in letters, "reason": "a few words"}}"""


def _preview(path):
    """The candidate on mid-grey, so white and black logos are both visible to the AI."""
    im = Image.open(path).convert("RGBA")
    im.thumbnail((480, 240), Image.LANCZOS)
    bg = Image.new("RGBA", (im.width + 40, im.height + 40), (128, 128, 128, 255))
    bg.alpha_composite(im, (20, 20))
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def choose(cands, brand, domain, out_dir: Path):
    """cands: rendered PNGs, best guess first. Writes logo.png and returns (name, has_name), or
    (None, False) when no candidate is a proper logo."""
    ok = []
    for p in cands:
        why = check(p)
        if why:
            print(f"   logo candidate {p.name}: {why}, rejected")
        else:
            ok.append(p)
    if not ok:
        return None, False
    ok = ok[:8]
    pick, has_name = ok[0], None
    try:
        ans = ai.parse_json(ai.see(PICK_PROMPT.format(brand=brand, domain=domain, n=len(ok)),
                                   [_preview(p) for p in ok]))
        i = int(ans.get("index", 0))
        if not 1 <= i <= len(ok):
            print(f"   logo: none of {len(ok)} candidates is {brand}'s logo ({ans.get('reason', '')}); "
                  "using the name instead")
            return None, False
        pick, has_name = ok[i - 1], bool(ans.get("has_name"))
        print(f"   logo: candidate {i} of {len(ok)} ({ans.get('reason', '')})")
    except Exception as e:                               # no AI: the site's own logo comes first
        print(f"   logo: AI check unavailable ({type(e).__name__}), using the first good candidate")
    if has_name is None:
        has_name = has_name_shape(pick)
    shutil.copyfile(pick, out_dir / "logo.png")
    return "logo.png", has_name


def cleanup(out_dir: Path):
    for p in list(out_dir.glob("logo_cand_*")) + list(out_dir.glob("logo_src_*")):
        p.unlink(missing_ok=True)


def find(site_srcs, brand, domain, out_dir: Path):
    """The whole job: site candidates + outside ones -> checked -> picked -> logo.png."""
    srcs = list(site_srcs) + outside_candidates(brand, domain, out_dir)
    try:
        rendered = [out for out, _ in render(srcs, out_dir)]
        name, has_name = choose(rendered, brand, domain, out_dir)
    finally:
        cleanup(out_dir)
    return name, has_name


def ensure(info, out_dir: Path, brand):
    """For thumbnails made later (remakes): re-check the saved logo and replace it when it is not
    a proper logo. Updates info["logo"] / info["logo_has_name"]."""
    cur = out_dir / info["logo"] if info.get("logo") else None
    srcs = []
    if cur and cur.exists():
        keep = cur.with_name("logo_src_saved.png")
        shutil.copyfile(cur, keep)
        srcs.append(keep)
    name, has_name = find(srcs, brand, info["domain"], out_dir)
    info["logo"], info["logo_has_name"] = name, has_name
    return info
