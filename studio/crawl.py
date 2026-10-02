"""Step 1: visit a website, collect text, screenshots (with on-screen text boxes) and the logo."""
import base64
import io
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

DEFAULT_WORDS = ["pricing", "plans", "fees", "rates", "features", "how-it-works", "about",
                 "security", "faq", "products", "compare"]

COOKIE_BUTTONS = ["Accept all", "Accept All", "Accept all cookies", "Accept", "I agree", "Agree",
                  "Allow all", "Got it", "OK", "Close", "No thanks", "Dismiss"]

# Hide cookie banners, chat bubbles and sticky promo bars so screenshots stay clean.
CLEAN_CSS = """
#onetrust-banner-sdk, #onetrust-consent-sdk, .onetrust-pc-dark-filter, #CybotCookiebotDialog,
#truste-consent-track, .truste_box_overlay, [id*="cookie-banner" i], [class*="cookie-banner" i],
[id*="cookieConsent" i], [class*="cookie-consent" i], [aria-label*="cookie" i][role="dialog"],
#intercom-container, .intercom-lightweight-app, #hubspot-messages-iframe-container,
iframe[title*="chat" i], #launcher, .drift-frame-controller, #drift-widget, .zEWidget-launcher,
#credential_picker_container, [class*="smartbanner" i] { display: none !important; }
"""

BLOCK_SIGNS = ["access denied", "just a moment", "attention required", "verify you are human",
               "are you a robot", "enable javascript and cookies", "request unsuccessful",
               "pardon our interruption", "403 forbidden", "captcha"]

# Collect short, meaningful on-screen texts with their boxes (used for smart zoom + highlight).
BOXES_JS = """
() => {
  const out = [], seen = new Set(), H = innerHeight, W = innerWidth;
  const sel = 'h1,h2,h3,h4,strong,b,button,a,[class*="price" i],[class*="rate" i],[class*="apy" i],' +
              '[class*="amount" i],[class*="badge" i],li,p,span';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 10 || r.bottom < 40 || r.top > H - 40 || r.right < 0 || r.left > W) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.opacity === '0') continue;
    let t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 70 || seen.has(t)) continue;
    const big = parseFloat(st.fontSize) >= 22, num = /[$%€£]|\\d/.test(t);
    const tag = el.tagName.toLowerCase();
    if (!(big || num || /^h[1-4]$/.test(tag) || tag === 'button' || tag === 'strong')) continue;
    seen.add(t);
    out.push({t, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width),
              h: Math.round(r.height), s: Math.round(parseFloat(st.fontSize))});
    if (out.length >= 45) break;
  }
  return out;
}
"""

VISIBLE_TEXT_JS = """
() => {
  const H = innerHeight, parts = [];
  for (const el of document.querySelectorAll('h1,h2,h3,p,li')) {
    const r = el.getBoundingClientRect();
    if (r.top >= 0 && r.top < H && r.height > 0) {
      const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t && t.length < 300) parts.push(t);
    }
    if (parts.join(' ').length > 400) break;
  }
  return parts.join(' | ').slice(0, 400);
}
"""


class BlockedSite(Exception):
    pass


def _dismiss_popups(page):
    try:
        page.add_style_tag(content=CLEAN_CSS)
    except Exception:
        pass
    for label in COOKIE_BUTTONS:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(600)
                break
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _clean_text(html, limit=12000):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()[:limit]


def _check_blocked(title, text):
    low = (title + " " + text[:1500]).lower()
    if len(text) < 350 or any(s in low for s in BLOCK_SIGNS) and len(text) < 3000:
        raise BlockedSite(f"site blocked automated visit or has no content ({title!r})")


def _is_useful(path: Path, prev: Path | None):
    """Drop near-blank screenshots and near-duplicates of the previous one."""
    im = Image.open(path).convert("L").resize((192, 108))
    if ImageStat.Stat(im).stddev[0] < 7:
        return False
    if prev is not None and prev.exists():
        p = Image.open(prev).convert("L").resize((192, 108))
        diff = ImageStat.Stat(ImageChops.difference(im, p)).mean[0]
        if diff < 3:
            return False
    return True


def _shot(page, out_dir, name, label, shots):
    f = out_dir / name
    page.screenshot(path=str(f))
    prev = out_dir / shots[-1]["file"] if shots else None
    if not _is_useful(f, prev):
        f.unlink(missing_ok=True)
        return
    try:
        boxes = page.evaluate(BOXES_JS)
        visible = page.evaluate(VISIBLE_TEXT_JS)
    except Exception:
        boxes, visible = [], ""
    shots.append({"file": name, "page": label, "visible_text": visible, "boxes": boxes})


def _find_logo(page, base_url):
    js = """
    () => {
      const out = [];
      const abs = u => { try { return new URL(u, location.href).href } catch(e) { return null } };
      // App Store / Google Play: the app's own icon (square, near the top), not the store's logo
      if (/(^|\.)apps\.apple\.com$|(^|\.)play\.google\.com$/.test(location.hostname)) {
        [...document.images].forEach(img => {
          const r = img.getBoundingClientRect(), src = img.currentSrc || img.src;
          if (r.top < 900 && r.width >= 56 && Math.abs(r.width - r.height) < 8 && /mzstatic|googleusercontent/.test(src))
            out.push(abs(src));
        });
      }
      // never: cookie / privacy-choice banners, footers, badges and partner logos
      const skipBox = '[id*="onetrust" i],[class*="onetrust" i],[id*="cookie" i],[class*="cookie" i],[id*="consent" i],' +
                      '[class*="consent" i],[class*="privacy" i],[id*="privacy" i],footer,[role="dialog"]';
      const skipHint = /privacy|ccpa|opt-?out|consent|cookie|choices|fdic|sipc|finra|bbb|badge|app-?store|google-?play|partner|press|award|trustpilot|as-seen|featured/;
      const brandWord = location.hostname.replace(/^www\./, '').split('.')[0].toLowerCase();
      const imgs = [];
      document.querySelectorAll('img').forEach(img => {
        const hint = (img.alt + ' ' + img.className + ' ' + img.id + ' ' + img.src).toLowerCase();
        if (!hint.includes('logo') || img.naturalWidth < 40 || skipHint.test(hint) || img.closest(skipBox)) return;
        const top = img.closest('header, nav, a[href="/"]') ? 0 : 1;
        imgs.push([hint.includes(brandWord) ? 0 : 1, top, abs(img.currentSrc || img.src)]);
      });
      imgs.sort((a, b) => a[0] - b[0] || a[1] - b[1]).forEach(x => out.push(x[2]));
      document.querySelectorAll('header svg, [class*="logo" i] svg, a[href="/"] svg').forEach(svg => {
        const r = svg.getBoundingClientRect();
        if (r.width >= 60 && r.top < 200 && !svg.closest(skipBox)) {
          const c = svg.cloneNode(true);
          c.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
          if (!c.getAttribute('width')) c.setAttribute('width', Math.round(r.width));
          if (!c.getAttribute('height')) c.setAttribute('height', Math.round(r.height));
          const fill = getComputedStyle(svg).color;
          out.push('inline-svg:' + c.outerHTML.replace(/currentColor/g, fill));
        }
      });
      document.querySelectorAll('link[rel*="apple-touch-icon"]').forEach(l => out.push(abs(l.href)));
      document.querySelectorAll('link[rel*="icon"]').forEach(l => out.push(abs(l.href)));
      // the share image is usually a banner or photo, not the logo: last resort only
      const og = document.querySelector('meta[property="og:image"]');
      if (og) out.push('og:' + abs(og.content));
      return out.filter(Boolean);
    }"""
    try:
        cands = page.evaluate(js)
    except Exception:
        cands = []
    cands.append(urljoin(base_url, "/favicon.ico"))
    return list(dict.fromkeys(cands))


def _clean_svg(text):
    """Inline SVGs copied from a page can carry attributes that are invalid on their own (e.g. a
    stray '"=""'), which makes the image fail to render; drop anything that isn't a valid name."""
    def tag(m):
        attrs = re.findall(r'\s([A-Za-z_:][-\w:.]*)\s*=\s*("[^"]*"|\'[^\']*\')', m.group(2))
        return "<" + m.group(1) + "".join(f" {k}={v}" for k, v in attrs) + m.group(3) + ">"
    return re.sub(r"<(svg)\b([^>]*?)(/?)>", tag, text, count=1)


def _download_logo(cands, out_dir: Path, start=0):
    """Download the first usable candidate from position `start`. Returns (path, next position)."""
    for i in range(start, min(len(cands), 10)):
        c = cands[i]
        try:
            if c.startswith("inline-svg:"):
                p = out_dir / "logo.svg"
                p.write_text(_clean_svg(c[len("inline-svg:"):]))
                return p, i + 1
            if c.startswith("data:"):
                continue
            share = c.startswith("og:")
            c = c[3:] if share else c
            r = requests.get(c, headers={"User-Agent": UA}, timeout=15)
            if r.status_code != 200 or len(r.content) < 300:
                continue
            ctype = r.headers.get("content-type", "")
            ext = ".svg" if "svg" in ctype or c.lower().endswith(".svg") else ".img"
            if ext == ".img":
                try:                       # tiny favicons look blurry when enlarged; photos aren't logos
                    im = Image.open(io.BytesIO(r.content))
                    if max(im.size) < 64 or (share and im.width / max(1, im.height) > 1.3):
                        continue
                except Exception:
                    pass
            p = out_dir / f"logo{ext}"
            p.write_bytes(r.content)
            return p, i + 1
        except Exception:
            continue
    return None, len(cands)


def _logo_to_png(src: Path, out_dir: Path):
    """Render any logo format (svg/ico/webp/png) to a trimmed transparent PNG via Chromium."""
    data = src.read_bytes()
    head = data[:400].lower()
    mime = ("image/svg+xml" if b"<svg" in head or src.suffix == ".svg" else
            "image/x-icon" if data[:4] == b"\x00\x00\x01\x00" else "image/png")
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    html = (f"<html><body style='margin:0;background:transparent'>"
            f"<img id=l src='{uri}' style='max-width:1200px;max-height:500px;"
            f"min-height:240px;object-fit:contain'></body></html>")
    out = out_dir / "logo.png"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 700})
            pg.set_content(html)
            pg.wait_for_timeout(400)
            pg.locator("#l").screenshot(path=str(out), omit_background=True)
            b.close()
        im = Image.open(out).convert("RGBA")
        bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if not bbox:
            return None
        im = im.crop(bbox)
        if im.width < 24 or im.height < 12:
            return None
        im.save(out)
        return out.name
    except Exception as e:
        print(f"   ! logo render failed: {e}")
        return None


def _subpage_links(page, base_url, words, max_links=3):
    host = urlparse(base_url).netloc
    links = page.evaluate("() => Array.from(document.querySelectorAll('a[href]'))"
                          ".map(a => [a.href, (a.innerText||'').trim().toLowerCase()])")
    picked = []
    for word in words:
        for href, txt in links:
            u = urlparse(href)
            clean = href.split("#")[0].split("?")[0]
            if u.netloc != host or clean in picked or u.path in ("", "/"):
                continue
            if word in u.path.lower() or word.replace("-", " ") in txt:
                picked.append(clean)
                break
        if len(picked) >= max_links:
            break
    return picked


def crawl(url: str, out_dir: Path, subpage_words=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    words = list(dict.fromkeys((subpage_words or []) + DEFAULT_WORDS))
    shots = []
    info = {"url": url, "domain": urlparse(url).netloc.replace("www.", "")}

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=UA,
                                  locale="en-US", timezone_id="America/New_York")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        _dismiss_popups(page)

        info["final_url"] = page.url
        info["title"] = page.title()
        info["meta_description"] = page.evaluate(
            "() => (document.querySelector('meta[name=description]')||{}).content || ''")
        info["site_name"] = page.evaluate(
            "() => (document.querySelector('meta[property=\"og:site_name\"]')||{}).content || ''")
        info["home_text"] = _clean_text(page.content())
        _check_blocked(info["title"], info["home_text"])

        height = page.evaluate("() => document.body.scrollHeight")
        for i, frac in enumerate((0, 0.16, 0.32, 0.5, 0.68)):
            y = int(height * frac)
            if i and y > height - 700:
                break
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(1100)
            _shot(page, out_dir, f"home_{i}.png", "homepage", shots)

        logo_cands = _find_logo(page, page.url)
        subpages = _subpage_links(page, page.url, words)

        info["pages"] = []
        for j, sub in enumerate(subpages):
            try:
                page.goto(sub, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2200)
                _dismiss_popups(page)
                label = urlparse(sub).path
                _shot(page, out_dir, f"sub_{j}_0.png", label, shots)
                h = page.evaluate("() => document.body.scrollHeight")
                if h > 1900:                                   # pricing tables are often lower
                    page.evaluate("window.scrollTo(0, 850)")
                    page.wait_for_timeout(900)
                    _shot(page, out_dir, f"sub_{j}_1.png", label, shots)
                info["pages"].append({"url": sub, "text": _clean_text(page.content(), 5000)})
            except Exception as e:
                print(f"   ! subpage failed {sub}: {str(e)[:120]}")

        try:
            m = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                    is_mobile=True, has_touch=True, user_agent=UA)
            mp = m.new_page()
            mp.goto(url, wait_until="domcontentloaded", timeout=30000)
            mp.wait_for_timeout(2800)
            _dismiss_popups(mp)
            mp.screenshot(path=str(out_dir / "mobile.png"))
            if _is_useful(out_dir / "mobile.png", None):
                shots.append({"file": "mobile.png", "page": "mobile", "visible_text": "", "boxes": []})
        except Exception:
            pass
        browser.close()

    if not shots:
        raise BlockedSite("no usable screenshots")
    info["logo"], pos = None, 0
    while not info["logo"] and pos < min(len(logo_cands), 10):     # next candidate if one won't render
        logo, pos = _download_logo(logo_cands, out_dir, pos)
        info["logo"] = _logo_to_png(logo, out_dir) if logo else None
    info["screenshots"] = shots
    (out_dir / "site.json").write_text(json.dumps(info, indent=2))
    return info
