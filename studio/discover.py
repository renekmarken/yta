"""Trend discovery: find new / hot products in the money categories and keep a ranked queue.

Free, keyless sources:
  * Launch radar: Product Hunt, "Launch HN" (YC startups), TechCrunch startups and Google News
    "launches/unveils" searches from the last 1-2 days - products launched today or this week
  * Google News RSS (per-category launch/funding/news searches, last 7 days)
  * Google Trends "trending now" RSS (US)
  * Product Hunt feed (new launches: AI tools, SaaS, marketing, business tools)
  * Hacker News "Show HN" posts with traction
  * Apple App Store top-free charts (Finance, Business, Productivity) + who is climbing
  * Gemini with Google Search (what's launching / in the news right now)
Then Gemini acts as editor: picks the reviewable products, finds the official website,
assigns a category, a 0-10 hotness and when it launched. Priority = hotness (decays with age) +
category value + a big boost for products launched today / this week, so new launches go first
(and discover runs can start a video for them right away, see tools/auto_launch.py).
"""
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import requests

from . import ai, config
from .categories import BY_ID, CATEGORIES, describe_for_ai, weight
from .reviewed import Ledger, site_id

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0 Safari/537.36"}
NOW = lambda: datetime.now(timezone.utc)

# Never queue these: too generic, not a product site, or not reviewable.
BLOCKED_DOMAINS = {"google.com", "youtube.com", "facebook.com", "twitter.com", "x.com", "reddit.com",
                   "wikipedia.org", "apple.com", "apps.apple.com", "play.google.com", "amazon.com",
                   "linkedin.com", "github.com", "medium.com", "news.ycombinator.com",
                   "producthunt.com", "techcrunch.com", "forbes.com", "cnbc.com", "bloomberg.com",
                   "reuters.com", "businessinsider.com", "nerdwallet.com", "bankrate.com",
                   "investopedia.com", "irs.gov", "usa.gov", "instagram.com", "tiktok.com"}


# ---------------------------------------------------------------- helpers
def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
        if r.status_code == 200:
            return r
        print(f"   source {urlparse(url).netloc}: HTTP {r.status_code}")
    except requests.RequestException as e:
        print(f"   source {urlparse(url).netloc}: {type(e).__name__}")
    return None


def _age_days(ts):
    try:
        dt = datetime.fromisoformat(ts)
        return max(0.0, (NOW() - dt).total_seconds() / 86400)
    except Exception:
        return 0.0


def _when(ts):
    """Signal date -> datetime (RSS, Atom or ISO), or None."""
    if not ts:
        return None
    try:
        dt = parsedate_to_datetime(ts)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago(ts):
    dt = _when(ts)
    if not dt:
        return ""
    h = (NOW() - dt).total_seconds() / 3600
    return "today" if h < 24 else (f"{int(h // 24)}d ago")


def key_for(url):
    u = urlparse(url if "://" in url else "https://" + url)
    host = u.netloc.lower().removeprefix("www.")
    path = u.path.rstrip("/")
    return host + (path if path and path != "/" else "")


def _domain(url):
    return urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")


def _rss_items(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = root.findall(".//item")
    if not items:                                    # Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out = []
        for e in root.findall(".//a:entry", ns):
            link = e.find("a:link", ns)
            out.append({"title": (e.findtext("a:title", "", ns) or "").strip(),
                        "link": link.get("href") if link is not None else "",
                        "date": e.findtext("a:published", "", ns) or e.findtext("a:updated", "", ns),
                        "detail": re.sub("<[^>]+>", " ", e.findtext("a:content", "", ns) or "")[:200]})
        return out
    out = []
    for it in items:
        out.append({"title": (it.findtext("title") or "").strip(), "link": it.findtext("link") or "",
                    "date": it.findtext("pubDate") or "",
                    "detail": re.sub("<[^>]+>", " ", it.findtext("description") or "")[:200],
                    "_el": it})
    return out


# ---------------------------------------------------------------- sources
def src_google_news():
    out = []
    for cat in CATEGORIES:
        for q in cat["news_queries"]:
            r = _get(f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=en-US&gl=US&ceid=US:en")
            if not r:
                continue
            for it in _rss_items(r.text)[:10]:
                out.append({"source": "Google News", "title": it["title"], "detail": "",
                            "cat_hint": cat["id"], "date": it["date"]})
            time.sleep(0.4)
    return out


def src_google_trends():
    r = _get("https://trends.google.com/trending/rss?geo=US")
    if not r:
        return []
    out = []
    for it in _rss_items(r.text):
        el = it.get("_el")
        traffic, news = "", []
        if el is not None:
            for child in el:
                tag = child.tag.split("}")[-1]
                if tag == "approx_traffic":
                    traffic = child.text or ""
                if tag == "news_item":
                    for c in child:
                        if c.tag.split("}")[-1] == "news_item_title":
                            news.append(c.text or "")
        out.append({"source": "Google Trends", "title": it["title"],
                    "detail": f"searches {traffic}; " + " / ".join(news[:2]), "cat_hint": None,
                    "date": it["date"]})
    return out


def src_product_hunt():
    r = _get("https://www.producthunt.com/feed")
    if not r:
        return []
    return [{"source": "Product Hunt (launch)", "title": it["title"], "detail": it["detail"][:160],
             "cat_hint": None, "date": it["date"]} for it in _rss_items(r.text)[:50]]


def src_hacker_news():
    since = int(time.time()) - 4 * 86400
    r = _get(f"https://hn.algolia.com/api/v1/search?tags=show_hn&numericFilters=created_at_i>{since},points>40&hitsPerPage=40")
    if not r:
        return []
    out = []
    for h in r.json().get("hits", []):
        out.append({"source": "Hacker News", "title": h.get("title", ""),
                    "detail": f"{h.get('points', 0)} points; {h.get('url') or ''}", "cat_hint": None,
                    "date": h.get("created_at", "")})
    return out


def src_app_store():
    snap_file = config.DATA_DIR / "appstore_snapshot.json"
    old = json.loads(snap_file.read_text()) if snap_file.exists() else {}
    new, out = {}, []
    genres = sorted({c["appstore_genre"] for c in CATEGORIES if c["appstore_genre"]})
    for g in genres:
        r = _get(f"https://itunes.apple.com/us/rss/topfreeapplications/limit=100/genre={g}/json")
        if not r:
            continue
        entries = r.json().get("feed", {}).get("entry", [])
        names = [e["im:name"]["label"] for e in entries]
        new[str(g)] = names
        prev = old.get(str(g), [])
        hint = next((c["id"] for c in CATEGORIES if c["appstore_genre"] == g), None)
        for rank, e in enumerate(entries, 1):
            name = e["im:name"]["label"]
            was = prev.index(name) + 1 if name in prev else None
            climbing = (was is None and prev and rank <= 60) or (was and was - rank >= 15)
            if climbing or (not prev and rank <= 15):
                move = "new on chart" if was is None else f"up from #{was}"
                out.append({"source": "App Store", "title": f"{name} ({e['im:artist']['label']})",
                            "detail": f"#{rank} top free in {e['category']['attributes']['label']}"
                                      + (f", {move}" if prev else ""),
                            "cat_hint": hint, "date": ""})
    if new:
        snap_file.write_text(json.dumps(new))
    return out


LAUNCH_QUERIES = ["launches app", "officially launches platform", "unveils new app", "launches new service",
                  "startup launches", "now available new app", "debuts new platform", "launches AI tool"]


def src_launch_news():
    """Google News: things that launched in the last ~day."""
    out = []
    for q in LAUNCH_QUERIES:
        r = _get(f"https://news.google.com/rss/search?q={quote(q)}+when:1d&hl=en-US&gl=US&ceid=US:en")
        if not r:
            continue
        for it in _rss_items(r.text)[:15]:
            out.append({"source": "Launch news", "title": it["title"], "detail": "", "cat_hint": None,
                        "date": it["date"]})
        time.sleep(0.4)
    return out


def src_launch_hn():
    """'Launch HN' posts: YC startups launching their product."""
    r = _get("https://hnrss.org/launches?count=30")
    if not r:
        return []
    return [{"source": "Launch HN", "title": it["title"], "detail": it["detail"][:160], "cat_hint": None,
             "date": it["date"]} for it in _rss_items(r.text) if (_when(it["date"]) and
                                                                  (NOW() - _when(it["date"])).days <= 7)]


def src_techcrunch():
    r = _get("https://techcrunch.com/category/startups/feed/")
    if not r:
        return []
    return [{"source": "TechCrunch", "title": it["title"], "detail": it["detail"][:160], "cat_hint": None,
             "date": it["date"]} for it in _rss_items(r.text)[:25]]


def src_gemini_search():
    prompt = f"""Use Google Search. Today is {NOW():%B %d, %Y}.
List up to 25 specific products, apps or online services that US consumers or businesses can sign
up for on a website, and that LAUNCHED TODAY or THIS WEEK (first priority), or are growing fast or
in the news during the last 14 days, in these categories:
{describe_for_ai()}
Skip big generic platforms (Google, Amazon, Apple, Meta) unless it is a specific new product with
its own website. Return ONLY a JSON array: [{{"name": "...", "url": "official website",
"category": "category id", "launched": "today | this_week | older",
"why": "max 15 words, what happened"}}]"""
    try:
        text, _ = ai.ask(prompt, grounded=True, temperature=0.4)
        items = ai.parse_json(text)
        return [{"source": "Gemini web search", "title": f"{i.get('name')} — {i.get('url', '')}",
                 "detail": f"launched {i.get('launched', '?')}; " + i.get("why", ""),
                 "cat_hint": i.get("category"), "date": ""}
                for i in items if isinstance(i, dict)]
    except Exception as e:
        print(f"   Gemini web search skipped: {str(e)[:200]}")
        return []


SOURCES = [src_gemini_search, src_product_hunt, src_launch_hn, src_launch_news, src_techcrunch,
           src_google_news, src_hacker_news, src_app_store, src_google_trends]


# ---------------------------------------------------------------- queue storage
def load_queue():
    if config.QUEUE_FILE.exists():
        return json.loads(config.QUEUE_FILE.read_text())
    return {"items": {}, "updated": None}


def save_queue(q):
    config.DATA_DIR.mkdir(exist_ok=True)
    q["updated"] = NOW().isoformat(timespec="seconds")
    config.QUEUE_FILE.write_text(json.dumps(q, indent=1, ensure_ascii=False))
    write_queue_md(q)


def _queued_site(q, url):
    """Queue key of an item for the same website, if one is already waiting."""
    sid = site_id(url)
    for k, it in q["items"].items():
        if site_id(it.get("url", "")) == sid:
            return k
    return None


def priority(item):
    if item.get("pinned"):
        return 100.0
    h = float(item.get("hotness", 5))
    fresh_bonus = 0.0
    if not item.get("evergreen"):
        age = _age_days(item.get("added", ""))
        h *= 0.5 ** (age / 4)                                  # hot news halves every 4 days
        fresh_bonus = 2.0 if age < 5 else 0.0                  # new/hot products go first
    return round(0.65 * h + 0.35 * weight(item.get("category")) * 10 + fresh_bonus + launch_boost(item), 2)


def launch_boost(item):
    """Launched today: +8, this week: +5 (fading over a few days) - new launches jump the queue."""
    kind = item.get("launch")
    if kind not in ("today", "this_week"):
        return 0.0
    return (8.0 if kind == "today" else 5.0) * 0.5 ** (_age_days(item.get("launch_seen", "")) / 3)


def is_fresh_launch(item, days=7):
    return item.get("launch") in ("today", "this_week") and _age_days(item.get("launch_seen", "")) <= days


def write_queue_md(q):
    rows = sorted(q["items"].values(), key=priority, reverse=True)[:40]
    lines = [f"# Review queue", f"Updated {q['updated']} UTC · {len(q['items'])} products waiting\n",
             "| # | Priority | Category | Product | Why | Found via |", "|---|---|---|---|---|---|"]
    for n, it in enumerate(rows, 1):
        cat = BY_ID.get(it.get("category"), {})
        kind = "📌 pinned" if it.get("pinned") else ("🚀 new launch · " if is_fresh_launch(it) else
                                                     ("🔥 " if not it.get("evergreen") else "🌲 "))
        lines.append(f"| {n} | {priority(it):.1f} | {cat.get('emoji', '')} {cat.get('name', it.get('category', '?'))} "
                     f"| [{it['name']}]({it['url']}) | {kind}{it.get('why', '')} | {', '.join(it.get('sources', []))} |")
    config.QUEUE_MD.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- AI editor
EDITOR_PROMPT = """You are the editor of a YouTube channel that reviews US websites/apps and asks
"is it worth using?". Below are raw signals from news, trend charts and launch sites.

Pick up to {max_new} distinct products/services that:
- a US consumer or business can sign up for or buy on a public website
- fit one of these categories:
{cats}
- have NEVER been reviewed on the channel. ALREADY REVIEWED (never suggest these again, under any
  name, URL or sub-page): {reviewed}
- are not already waiting in the queue: {queued}
- are not news sites, review sites, government sites, gambling, adult, meme coins or obvious scams
- would make people search "<name> review" or "is <name> worth it"

TOP PRIORITY: products that LAUNCHED TODAY or THIS WEEK (Product Hunt launches, "Launch HN", "X launches
/ unveils / debuts ..." news). Today is {today}; each signal shows how long ago it appeared. List those
first. Only call something a launch if the signal says it is new / launched / now available, not just
news about an old product.

For each give the official website URL (homepage or the product's own page), the category id,
"hotness" 0-10 (how much fresh attention it has right now: launch, viral, big news, chart climb),
"launched": "today" (last ~24h), "this_week" (last 7 days) or "older", and "why" (max 15 words).
Prefer items with several signals.

Return ONLY JSON: {{"items": [{{"name": "...", "url": "https://...", "category": "...",
"hotness": 7, "launched": "today", "why": "..."}}]}}

SIGNALS:
{signals}
"""

EVERGREEN_PROMPT = """List well-known, frequently searched US websites/apps that people look up
reviews for, in these categories: {cats}.
{per_cat} per category. Choose ones with high "<brand> review" search interest, mix big names and
popular challengers. NEVER include anything already reviewed on the channel: {reviewed}.
Also skip ones already waiting in the queue: {queued}.
Return ONLY JSON: {{"items": [{{"name": "...", "url": "official https URL", "category": "category id",
"search_interest": 0-10, "why": "max 12 words"}}]}}"""


def _verify(url):
    """Make sure the site exists. 403/429 means 'exists but blocks scripts' — still fine."""
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True, stream=True)
        r.close()
        return r.status_code < 400 or r.status_code in (403, 429)
    except requests.RequestException:
        return False


def _add(q, raw, evergreen, sources, skip):
    url = (raw.get("url") or "").strip()
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/") if url else ""
    if not url or raw.get("category") not in BY_ID:
        return False
    if skip.has(url, raw.get("name")) or _domain(url) in BLOCKED_DOMAINS:
        return False                                           # reviewed before: never again
    k = _queued_site(q, url) or key_for(url)
    if k in q["items"]:
        it = q["items"][k]                                     # seen again: refresh heat
        it["hotness"] = max(float(it.get("hotness", 0)), float(raw.get("hotness", 0)))
        it["added"] = NOW().isoformat(timespec="seconds") if not evergreen else it["added"]
        it["sources"] = sorted(set(it.get("sources", [])) | set(sources))[:4]
        _mark_launch(it, raw)
        return False
    if not _verify(url):
        print(f"   ✗ unreachable: {url}")
        return False
    q["items"][k] = {"name": raw.get("name", k)[:60], "url": url, "category": raw["category"],
                     "hotness": float(raw.get("hotness", raw.get("search_interest", 5)) or 5)
                                * (0.6 if evergreen else 1.0),
                     "evergreen": evergreen, "why": (raw.get("why") or "")[:120],
                     "sources": sources[:4], "added": NOW().isoformat(timespec="seconds")}
    _mark_launch(q["items"][k], raw)
    return True


def _mark_launch(it, raw):
    kind = raw.get("launched")
    if kind in ("today", "this_week") and not (it.get("launch") == "today" and kind == "this_week"):
        if it.get("launch") != kind:
            it["launch"], it["launch_seen"] = kind, NOW().isoformat(timespec="seconds")


def discover():
    config.DATA_DIR.mkdir(exist_ok=True)
    q = load_queue()
    skip = Ledger()
    print("Collecting trend signals...")
    signals = []
    for src in SOURCES:
        try:
            got = src()
        except Exception as e:                       # one broken source never stops discovery
            print(f"   {src.__name__}: failed ({str(e)[:120]})")
            got = []
        print(f"   {src.__name__.removeprefix('src_')}: {len(got)}")
        signals += got
    # de-duplicate titles, keep it compact for the AI
    seen_t, compact = set(), []
    for s in signals:
        t = re.sub(r"\s+", " ", s["title"]).strip()
        if t.lower() in seen_t or not t:
            continue
        seen_t.add(t.lower())
        hint = f" [{s['cat_hint']}]" if s.get("cat_hint") else ""
        when = _ago(s.get("date", ""))
        compact.append(f"- ({s['source']}{', ' + when if when else ''}){hint} {t} | {s.get('detail', '')}".strip(" |"))
    compact = compact[:220]

    reviewed = skip.for_prompt()
    queued = ", ".join(sorted({it.get("name", k) for k, it in q["items"].items()}))[:4000] or "none"
    added = 0
    if compact:
        try:
            text, _ = ai.ask(EDITOR_PROMPT.format(max_new=config.DISCOVERY_MAX_NEW, cats=describe_for_ai(),
                                                  reviewed=reviewed, queued=queued,
                                                  today=f"{NOW():%A %B %d, %Y}",
                                                  signals="\n".join(compact)),
                             json_mode=True, temperature=0.3)
            picks = ai.parse_json(text)
            picks = picks.get("items", []) if isinstance(picks, dict) else picks
            src_by_name = {}
            for s in signals:
                for p in picks:
                    if p.get("name") and p["name"].lower() in s["title"].lower():
                        src_by_name.setdefault(p["name"], set()).add(s["source"])
            for p in picks:
                if _add(q, p, False, sorted(src_by_name.get(p.get("name"), {"trend scan"})), skip):
                    added += 1
                    tag = "🚀" if p.get("launched") in ("today", "this_week") else "🔥"
                    print(f"   {tag} {p['name']} ({p['category']}, hot {p.get('hotness')}, launched {p.get('launched')})")
        except Exception as e:
            print(f"   editor step failed: {str(e)[:300]}")

    # Keep an evergreen backlog in every category so production never runs dry.
    counts = {c["id"]: 0 for c in CATEGORIES}
    for it in q["items"].values():
        if it.get("category") in counts:
            counts[it["category"]] += 1
    low = [c for c, n in counts.items() if n < config.QUEUE_MIN_EVERGREEN]
    if low:
        try:
            names = ", ".join(f"{c} ({BY_ID[c]['name']})" for c in low)
            text, _ = ai.ask(EVERGREEN_PROMPT.format(cats=names, per_cat=config.QUEUE_MIN_EVERGREEN + 2,
                                                     reviewed=reviewed, queued=queued),
                             json_mode=True, temperature=0.5)
            items = ai.parse_json(text)
            items = items.get("items", []) if isinstance(items, dict) else items
            for p in items:
                p.setdefault("hotness", p.get("search_interest", 5))
                if _add(q, p, True, ["evergreen"], skip):
                    added += 1
                    print(f"   🌲 {p['name']} ({p['category']})")
        except Exception as e:
            print(f"   evergreen refill failed: {str(e)[:300]}")

    # Drop stale hot items nobody got to.
    for k in [k for k, it in q["items"].items()
              if not it.get("evergreen") and not it.get("pinned") and _age_days(it["added"]) > 21]:
        del q["items"][k]
    save_queue(q)
    print(f"Queue: {len(q['items'])} items ({added} new). See data/QUEUE.md")
    return q


# ---------------------------------------------------------------- picking the next videos
def sync_pinned(q):
    """sites.txt entries jump the queue (unless that product was already reviewed)."""
    skip = Ledger()
    if not config.SITES_FILE.exists():
        return
    for line in config.SITES_FILE.read_text().splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        if skip.has(url):
            print(f"   sites.txt: {url} was already reviewed — skipping")
            continue
        k = _queued_site(q, url) or key_for(url)
        it = q["items"].setdefault(k, {"name": _domain(url), "url": url, "category": None,
                                       "hotness": 5, "evergreen": True, "why": "added by you",
                                       "sources": ["sites.txt"],
                                       "added": NOW().isoformat(timespec="seconds")})
        it["pinned"] = True


def pick_next(n, history):
    q = load_queue()
    sync_pinned(q)
    done = Ledger()
    stale = [k for k, it in q["items"].items() if done.has(it.get("url", ""), it.get("name", ""))]
    for k in stale:                                   # reviewed since it was queued: drop it
        print(f"   queue: dropping {q['items'][k].get('name', k)} (already reviewed)")
        del q["items"][k]
    if stale:
        save_queue(q)
    recent = [h.get("category") for h in history[-2:]]
    ranked = sorted(q["items"].items(), key=lambda kv: priority(kv[1]), reverse=True)
    picked, cats = [], list(recent)
    pool = list(ranked)
    while pool and len(picked) < n:
        # small penalty for repeating a category back-to-back keeps the channel varied
        best = max(pool, key=lambda kv: priority(kv[1]) - (2.0 if kv[1].get("category") in cats[-2:] else 0))
        pool.remove(best)
        picked.append(best)
        cats.append(best[1].get("category"))
    return q, picked


def remove_from_queue(key):
    q = load_queue()
    q["items"].pop(key, None)
    save_queue(q)
