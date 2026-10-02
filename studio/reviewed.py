"""The permanent record of every product the channel has reviewed (or tried to), so nothing is
ever reviewed twice — by the queue, by Gemini's suggestions, sites.txt or a manual URL.

A product counts as already done when its website (same domain, any page or subdomain) or its
name matches an earlier review. data/reviewed.json is never trimmed.
"""
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from . import config

LEDGER = config.DATA_DIR / "reviewed.json"

# Hosts that carry many unrelated products: here the first path part identifies the product.
PLATFORM_HOSTS = {"apps.apple.com", "play.google.com", "chromewebstore.google.com",
                  "chrome.google.com", "microsoft.com", "apps.microsoft.com", "github.com",
                  "producthunt.com", "medium.com", "substack.com", "notion.site", "vercel.app",
                  "netlify.app", "herokuapp.com", "webflow.io", "framer.website", "wixsite.com"}
_TWO_PART_TLDS = {"co.uk", "com.au", "co.nz", "co.jp", "com.br", "co.in", "com.mx", "co.za"}
_NAME_NOISE = re.compile(r"\b(app|apps|inc|llc|ltd|corp|co|company|the|official|online|hq|us|usa)\b")


def _host(url):
    u = urlparse(url if "://" in url else "https://" + url)
    path = u.path
    app_id = parse_qs(u.query).get("id")          # Google Play: the app is in ?id=
    if app_id:
        path = path.rstrip("/") + "/" + app_id[0]
    return u.netloc.lower().split("@")[-1].split(":")[0].removeprefix("www."), path


def site_id(url):
    """'https://app.robinhood.com/us/en' -> 'robinhood.com'; app-store links keep their path."""
    host, path = _host(url or "")
    if not host:
        return ""
    for p in PLATFORM_HOSTS:
        if host == p or host.endswith("." + p):
            part = [x for x in path.split("/") if x][:5]
            return host + ("/" + "/".join(part) if part else "")
    labels = host.split(".")
    keep = 3 if ".".join(labels[-2:]) in _TWO_PART_TLDS else 2
    return ".".join(labels[-keep:])


def name_id(name):
    """'Robinhood App, Inc.' -> 'robinhood'. Empty for names too short to be safe to match."""
    n = (name or "").lower()
    n = re.sub(r"\.(com|io|ai|app|co|net|org)\b", " ", n)
    n = _NAME_NOISE.sub(" ", n)
    n = re.sub(r"[^a-z0-9]+", "", n)
    return n if len(n) >= 3 else ""


def _load():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text())
        except json.JSONDecodeError:
            pass
    return []


def _save(rows):
    config.DATA_DIR.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(rows, indent=1, ensure_ascii=False))


def backfill():
    """Fold done.txt, failed.txt and history.json into the ledger (safe to run every time)."""
    rows = _load()
    have = {(r.get("site"), r.get("status")) for r in rows}
    extra = []
    names = {}
    if config.HISTORY_FILE.exists():
        try:
            for h in json.loads(config.HISTORY_FILE.read_text()):
                names[site_id(h.get("url", ""))] = h.get("brand") or ""
        except json.JSONDecodeError:
            pass
    for f, status in ((config.DONE_FILE, "done"), (config.FAILED_FILE, "failed")):
        if f.exists():
            for url in f.read_text().split():
                sid = site_id(url)
                if sid and (sid, status) not in have:
                    extra.append({"site": sid, "name": names.get(sid, ""), "url": url, "status": status,
                                  "date": ""})
                    have.add((sid, status))
    if extra:
        _save(rows + extra)
    return rows + extra


class Ledger:
    def __init__(self):
        self.rows = backfill()
        self.sites = {r["site"] for r in self.rows if r.get("site")}
        self.names = {name_id(n) for r in self.rows for n in (r.get("name"), r.get("alt"))} - {""}

    def has(self, url="", name=""):
        sid = site_id(url) if url else ""
        nid = name_id(name)
        return bool((sid and sid in self.sites) or (nid and nid in self.names))

    def for_prompt(self, limit_chars=12000):
        """Every reviewed product, newest first, for Gemini's 'never suggest' list."""
        seen, parts = set(), []
        for r in reversed(self.rows):
            label = f"{r['name']} ({r['site']})" if r.get("name") else r["site"]
            if r["site"] in seen:
                continue
            seen.add(r["site"])
            parts.append(label)
        text = ", ".join(parts)
        return text[:limit_chars] if text else "none yet"


def record(url, name="", brand="", status="done"):
    """Add a product to the permanent record (status: done | failed)."""
    rows = backfill()
    rows.append({"site": site_id(url), "name": brand or name or "", "alt": name if brand and name != brand else "",
                 "url": url, "status": status, "date": date.today().isoformat()})
    _save(rows)
