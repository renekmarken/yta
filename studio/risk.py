"""Risk Case videos: one real user's worst experience with a product, explained.

The point is awareness, not attacking the product: the video retells a real, public story (a Reddit
post, a Hacker News thread, a news report), explains what most likely happened and why, how to avoid
it and what to do if it happens to you, and makes clear it is one person's account.

Pipeline (all free, no login):
  gather()        search Reddit (RSS search), Hacker News (Algolia) and Google News for
                  "<brand> froze account", "<brand> closed my account", "<brand> lost money", ...
  pick_story()    Gemini picks the strongest *real* candidate by its number (it can't invent one)
                  and extracts the claim, the amount and the thumbnail words
  investigate()   reads the whole thread: the full post, the poster's own updates, the top replies,
                  and lists similar public reports, so the script tells the complete story
  story_cards()   2-4 clean "post" cards (the post's text, its continuation, an update or a reply)
                  used as screenshots in the video
  write_script()  narration in the same JSON shape as reviews, so voice/render/library are shared

data/risk_cases.json remembers every story (and product) already used, so nothing repeats.
"""
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from . import ai, config
from .categories import BY_ID
from .reviewed import name_id, site_id

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) site-review-studio/1.0 (research)"}
LEDGER = config.DATA_DIR / "risk_cases.json"
PROBLEMS = ["froze my account", "account frozen", "closed my account", "holding my money", "funds on hold",
            "won't refund", "lost my money", "scammed", "account banned", "locked out", "charged me",
            "hidden fees", "nightmare"]


class NoStory(Exception):
    """No usable real story was found for this product."""


# ------------------------------------------------------------------ memory
def _load():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text())
        except json.JSONDecodeError:
            pass
    return {"cases": []}


def used():
    """(story urls, product ids) never to use again: products that already had a Risk Case, and ones
    where no usable story was found (they can't make one, so they leave the Risk Case queue for good)."""
    d = _load()
    over = [c for c in d["cases"] if c.get("status") in ("done", "nostory")]
    return ({c.get("story_url") for c in d["cases"]},
            {c.get("site") for c in over} | {c.get("name") for c in over if c.get("name")})


def record(url, name, story_url, title, status):
    d = _load()
    d["cases"].append({"date": date.today().isoformat(), "site": site_id(url), "name": name_id(name),
                       "story_url": story_url, "title": title, "status": status})
    config.DATA_DIR.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(d, indent=1, ensure_ascii=False))


# ------------------------------------------------------------------ sources
STATUS = {}                                          # last answer per source, for the log


def _get(url, **kw):
    host = url.split("/")[2]
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=25, **kw)
        except requests.RequestException as e:
            STATUS[host] = type(e).__name__
            return None
        STATUS[host] = r.status_code
        if r.status_code == 429 and "reddit" in host and attempt < 2:
            wait = min(30, int(r.headers.get("retry-after", "0") or 0) or 8 * (attempt + 1))
            time.sleep(wait)                               # Reddit says "slow down": wait, then try again
            continue
        return r if r.status_code == 200 else None
    return None


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _paras(text):
    """HTML (or plain text) to clean paragraphs separated by blank lines."""
    text = re.sub(r"(?i)</p>|<br\s*/?>|</li>|</h\d>", "\n\n", text or "")
    text = re.sub(r"(?i)<li[^>]*>", "\n\n• ", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    paras = []
    for x in re.split(r"\n\s*\n", text):
        x = re.sub(r"\s+", " ", x).strip()
        if x.count(" • ") >= 2:                          # bullets typed inline: one per line
            paras += [b if i == 0 else "• " + b for i, b in enumerate(x.split(" • "))]
        else:
            paras.append(x)
    paras = [x for x in paras if x and x not in ("[deleted]", "[removed]") and not x.startswith("submitted by")]
    return "\n\n".join(paras)


def platform(story):
    """Where it was posted, said simply: "Reddit", "Hacker News", "Facebook", or the news outlet."""
    src = story.get("source") or ""
    if src == "News":
        return story.get("where") or "the news"
    return src or "an online forum"


ACCENT = {"Reddit": (255, 69, 0), "Hacker News": (255, 102, 0), "Facebook": (24, 119, 242),
          "Quora": (185, 43, 39), "Trustpilot": (0, 182, 122)}


def _reddit_json(query):
    """Reddit's JSON search (old.reddit answers some servers that the feed refuses)."""
    r = _get(f"https://old.reddit.com/search.json?q={quote(query)}&sort=relevance&t=all&limit=15")
    if not r:
        return []
    try:
        kids = r.json()["data"]["children"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for k in kids:
        x = k.get("data", {})
        if not x.get("permalink"):
            continue
        out.append({"source": "Reddit", "where": "r/" + x.get("subreddit", ""), "title": _clean(x.get("title")),
                    "text": _clean(x.get("selftext")), "url": "https://www.reddit.com" + x["permalink"],
                    "date": date.fromtimestamp(x.get("created_utc", 0)).isoformat() if x.get("created_utc") else "",
                    "points": x.get("score") or 0})
    return out


def _reddit(query):
    r = _get(f"https://www.reddit.com/search.rss?q={quote(query)}&sort=relevance&t=all&limit=15") or \
        _get(f"https://old.reddit.com/search.rss?q={quote(query)}&sort=relevance&t=all&limit=15")
    if not r:
        return _reddit_json(query)
    return _reddit_feed(r)


def _reddit_sub(brand, words):
    """Search inside the product's own subreddit (r/SophiaLearning, r/Instagram...): where most
    first-hand complaints are, and what the site-wide search often misses."""
    out = []
    for sub in dict.fromkeys([re.sub(r"[^A-Za-z0-9]", "", brand), re.sub(r"[^A-Za-z0-9]", "", brand.split()[0])]):
        if len(sub) < 3:
            continue
        for host in ("www", "old"):
            r = _get(f"https://{host}.reddit.com/r/{sub}/search.rss?q={quote(words)}&restrict_sr=on&sort=relevance&t=all&limit=25")
            if r:
                out += _reddit_feed(r)
                break
        time.sleep(1)
    return out


def _reddit_feed(r):
    out = []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for e in root.findall("a:entry", ns):
        link = e.find("a:link", ns)
        url = link.get("href") if link is not None else ""
        if "/comments/" not in url:
            continue                                  # subreddits and users, not posts
        cat = e.find("a:category", ns)
        out.append({"source": "Reddit", "where": (cat.get("label") if cat is not None else "") or "Reddit",
                    "title": _clean(e.findtext("a:title", "", ns)), "text": _clean(e.findtext("a:content", "", ns)),
                    "url": url, "date": (e.findtext("a:updated", "", ns) or "")[:10]})
    return out


def _hn(query):
    out = []
    for tags in ("story", "comment"):
        r = _get(f"https://hn.algolia.com/api/v1/search?query={quote(query)}&tags={tags}&hitsPerPage=15")
        if not r:
            continue
        for h in r.json().get("hits", []):
            text = _clean(h.get("story_text") or h.get("comment_text") or "")
            title = h.get("title") or h.get("story_title") or ""
            oid = h.get("objectID")
            out.append({"source": "Hacker News", "where": "Hacker News", "title": _clean(title), "text": text,
                        "url": f"https://news.ycombinator.com/item?id={oid}", "date": (h.get("created_at") or "")[:10],
                        "points": h.get("points") or 0, "link": h.get("url") or ""})
    return out


def _news(query):
    r = _get(f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en")
    if not r:
        return []
    out = []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []
    for it in root.findall(".//item")[:12]:
        src = it.find("source")
        d = it.findtext("pubDate") or ""
        try:
            d = parsedate_to_datetime(d).date().isoformat()
        except (TypeError, ValueError):
            d = ""
        out.append({"source": "News", "where": src.text if src is not None else "News",
                    "title": _clean(it.findtext("title")), "text": _clean(it.findtext("description")),
                    "url": it.findtext("link") or "", "date": d})
    return out


ISSUE_QUERIES = """List 8 short web search queries (3-7 words each) that real people would type, or that would
match the titles of first-hand Reddit / forum posts, about this problem with {brand}: "{issue}".
Every query must contain "{brand}". Vary the wording (e.g. "banned for no reason", "account disabled",
"suspended without warning"). Return ONLY a JSON list of strings."""


def issue_queries(brand, issue):
    """Search phrases for one specific issue the user asked for ("users getting banned for no reason")."""
    qs = []
    try:
        text, _ = ai.ask(ISSUE_QUERIES.format(brand=brand, issue=issue), json_mode=True, temperature=0.4)
        got = ai.parse_json(text)
        qs = [re.sub(r"\s+", " ", str(q)).strip() for q in (got if isinstance(got, list) else []) if str(q).strip()]
    except Exception as e:
        print(f"   ! search phrases from AI failed ({type(e).__name__}), using the issue as typed")
    word = brand.lower().split()[0]
    qs = [q if word in q.lower() else f"{brand} {q}" for q in qs]
    issue_words = re.sub(r"[^\w\s$]", " ", issue).split()
    base = [f"{brand} {issue}", f"{brand} {' '.join(issue_words[:4])}"]
    return list(dict.fromkeys(base + qs))[:9]


WEB_PROMPT = """Search the web for first-hand public posts where users of {brand} describe this problem:
"{issue}". Look on Reddit, forums, Trustpilot, BBB complaints, Quora, Facebook groups, app reviews and
news. Return ONLY a JSON list (up to 10) of the posts you actually found:
[{{"url": "the post's address", "title": "its title", "summary": "2-3 sentences of what the user says"}}]"""


def _web_posts(brand, issue):
    """Posts about the issue found by Gemini's Google search. Only ones that really open are kept
    (with their own text), so nothing made up can become a story."""
    try:
        text, sources = ai.ask(WEB_PROMPT.format(brand=brand, issue=issue), grounded=True, temperature=0.2)
        found = ai.parse_json(text)
    except Exception as e:
        print(f"   web search for posts unavailable ({type(e).__name__})")
        return []
    out = []
    for f in (found if isinstance(found, list) else [])[:10]:
        url = ai.resolve_url(str(f.get("url") or "")).split("#")[0]
        if not url.startswith("http"):
            continue
        host = re.sub(r"^www\.", "", url.split("/")[2])
        if "reddit.com" in host and "/comments/" in url:
            got, src = _reddit_thread(url), "Reddit"
        elif "ycombinator.com" in host:
            got, src = _hn_thread(url), "Hacker News"
        else:
            got = _article(url)
            src = next((n for k, n in (("trustpilot", "Trustpilot"), ("quora", "Quora"), ("facebook", "Facebook"),
                                       ("bbb.org", "BBB"), ("apple.com", "App Store"), ("play.google", "Google Play"))
                        if k in host), "News")
        if not got or len(got.get("text") or "") < 120:
            continue                                      # couldn't open it: not used
        out.append({"source": src, "where": host if src == "News" else src, "title": _clean(f.get("title")) or host,
                    "text": got["text"][:4000], "url": url, "date": "", "updates": got.get("updates", []),
                    "replies": got.get("replies", [])})
    print(f"   web search: {len(out)} post(s) opened")
    return out


def gather(brand, queries=8, issue=None):
    """Real public posts about bad experiences with `brand`, from several sources. With `issue`, the
    searches are about that one problem instead of the usual list."""
    words = brand.lower().split()[0]
    full = brand.lower()
    cands, seen = [], set()
    phrases = issue_queries(brand, issue) if issue else [f"{brand} {p}" for p in PROBLEMS[:queries]]
    for i, q in enumerate(phrases):
        for c in _reddit(q) + (_hn(q) if i < 4 else []) + (_news(q) if i < 3 else []):
            hay = (c["title"] + " " + c["text"]).lower()
            if c["url"] in seen or words not in hay:
                continue
            if issue and " " in full and full not in hay and full.replace(" ", "") not in hay:
                continue                                  # "Sophia Learning", not any post naming a Sophia
            if len(c["text"]) < 120 and not re.search(r"\$\s?\d", c["title"]):
                continue
            seen.add(c["url"])
            cands.append(c)
        time.sleep(2.0)                                 # be polite to the free endpoints (Reddit limits hard)
    if issue:                                           # asked for one issue: look harder for it
        words_issue = " ".join(re.sub(r"[^\w\s]", " ", issue).split()[:6])
        for c in _reddit_sub(brand, words_issue) + _web_posts(brand, issue):
            if c["url"] not in seen and len(c.get("text") or "") >= 80:
                seen.add(c["url"])
                cands.append(c)
    by = {}
    for c in cands:
        by[c["source"]] = by.get(c["source"], 0) + 1
    print(f"   stories found: {len(cands)} ({', '.join(f'{k} {v}' for k, v in by.items()) or 'none'}) · "
          f"answers: {', '.join(f'{h} {s}' for h, s in STATUS.items())}")
    return cands


PICK_PROMPT = """You help a YouTube channel that raises awareness of real risks with popular apps and
services, using real people's public stories (never to attack the product, always fair).

PRODUCT: {brand} ({url})
Below are real public posts about bad experiences with it, numbered. Pick the ONE best story for an
awareness video:
- a specific, first-hand (or clearly reported) experience with a concrete harm: money frozen/held/lost,
  account closed/banned, unexpected charges, data/security problem, support failure
- credible and detailed; NOT spam, ads, rants without facts, jokes, or the poster's own illegal activity
- prefer a clear amount or impact ("$70,000 frozen", "account closed after 6 years")
- the post must clearly be about {brand}
Skip these story urls, they were used before: {used}

Return ONLY JSON:
{{"index": number of the chosen post,
 "claim": "the core claim in a few words, as the poster tells it, e.g. 'froze $70,000 for no reason'",
 "amount": "the key amount or impact if any, e.g. '$70,000' or '6-year account' (empty if none)",
 "thumb_big": "2-3 punchy words for the thumbnail, e.g. '$70,000 GONE.' or 'ACCOUNT BANNED.'",
 "thumb_small": "2-3 words under it, e.g. 'WHAT HAPPENED?' or 'NO WARNING?'",
 "what_happened": "4-6 sentences, faithful to the post (no added facts), told as the poster's account",
 "excerpt": "one short sentence from the post (max 22 words), quoted exactly",
 "issue": "short label of the issue type, e.g. 'payout freeze / account review'"}}
If none is usable, return {{"index": -1}}.
{focus}
POSTS:
{posts}
"""


def pick_story(brand, url, cands, issue=None):
    used_urls, _ = used()
    cands = [c for c in cands if c["url"] not in used_urls]
    if not cands:
        raise NoStory(f"no public stories found for {brand}")
    word = brand.lower().split()[0]
    hurt = re.compile(r"froze|frozen|freez|closed|banned|suspend|hold|held|lost|stole|scam|refund|locked|charged|terminated", re.I)
    topic = {w for w in re.findall(r"[a-z]{4,}", (issue or "").lower())} - {"user", "users", "their", "with", "from", "about", "getting"}
    cands.sort(key=lambda c: -(3 * (word in c["title"].lower()) + 2 * bool(hurt.search(c["title"]))
                               + 2 * sum(t in (c["title"] + " " + c["text"][:400]).lower() for t in topic)
                               + bool(re.search(r"\$\s?\d", c["title"] + c["text"][:600])) + (len(c["text"]) > 400)))
    cands = cands[:30]
    posts = "\n\n".join(f"[{i}] ({c['where']}, {c['date']}) {c['title']}\n{c['text'][:900]}" for i, c in enumerate(cands))
    focus = (f"\nTHE VIEWER ASKED SPECIFICALLY FOR THIS ISSUE: \"{issue}\". Pick the post that is about this issue; "
             f"if none is exactly about it, pick one about a closely related problem with {brand} (the same kind of "
             f"harm, e.g. a different reason for the same suspension or rejection). Only if nothing is even related, "
             f"return {{\"index\": -1}}.\n") if issue else ""
    text, _ = ai.ask(PICK_PROMPT.format(brand=brand, url=url, posts=posts, focus=focus,
                                        used=", ".join(list(used_urls)[:20]) or "none"),
                     json_mode=True, temperature=0.3)
    pick = ai.parse_json(text)
    i = pick.get("index", -1) if isinstance(pick, dict) else -1
    if not isinstance(i, int) or not 0 <= i < len(cands):
        raise NoStory(f"no usable story for {brand}" + (f" about '{issue}'" if issue else "") + f" among {len(cands)} posts")
    story = {**cands[i], **{k: str(pick.get(k, "")).strip() for k in
                            ("claim", "amount", "thumb_big", "thumb_small", "what_happened", "excerpt", "issue")}}
    if story["excerpt"] and story["excerpt"].lower()[:30] not in (story["title"] + " " + story["text"]).lower():
        story["excerpt"] = ""                          # only real quotes
    print(f"   story: {platform(story)} ({story['where']}) — {story['title'][:80]} ({story['url']})")
    return story


# ------------------------------------------------------------------ the whole story
def _reddit_thread(url):
    """The full post, the poster's own later comments (updates) and the replies, from the thread feed."""
    base = url.split("?")[0].rstrip("/")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = []
    for i, u in enumerate((base, base.replace("://www.", "://old."), base)):
        if i == 2:
            time.sleep(6)                               # Reddit's rate limit: one more try after a pause
        r = _get(u + "/.rss?limit=100")
        try:
            entries = ET.fromstring(r.text).findall("a:entry", ns) if r else []
        except ET.ParseError:
            entries = []
        if entries:
            break
    if not entries:
        return None
    who = lambda e: (e.findtext("a:author/a:name", "", ns) or "").replace("/u/", "")
    op = who(entries[0])
    post = _paras(entries[0].findtext("a:content", "", ns))
    updates, replies = [], []
    for e in entries[1:]:
        text = _paras(e.findtext("a:content", "", ns))
        if len(text) < 40:
            continue
        (updates if op and who(e) == op else replies).append(text)
    return {"text": post, "updates": updates[:6], "replies": replies[:12]}


def _hn_thread(url):
    m = re.search(r"id=(\d+)", url)
    r = _get(f"https://hn.algolia.com/api/v1/items/{m.group(1)}") if m else None
    if not r:
        return None
    try:
        it = r.json()
    except ValueError:
        return None
    op = it.get("author")
    updates, replies = [], []

    def walk(node, depth):
        for k in node.get("children") or []:
            text = _paras(k.get("text") or "")
            if len(text) >= 40:
                (updates if k.get("author") == op else replies if depth < 2 else []).append(text)
            walk(k, depth + 1)
    walk(it, 0)
    return {"text": _paras(it.get("text") or ""), "updates": updates[:6], "replies": replies[:12]}


def _article(url):
    """The text of a news article (Google News links redirect to the outlet)."""
    r = _get(url, allow_redirects=True)
    if not r or "news.google." in r.url:
        return None
    paras = [_clean(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", r.text)]
    text = "\n\n".join(p for p in paras if len(p) > 60)
    return {"text": text[:6000], "updates": [], "replies": []} if len(text) > 300 else None


def investigate(story, others=()):
    """Read the whole story: the full post, the poster's updates, what others replied, and other
    public reports of the same kind of problem. Fills story["text"], ["updates"], ["replies"], ["similar"]."""
    src = story.get("source")
    try:
        found = (_reddit_thread(story["url"]) if src == "Reddit" else
                 _hn_thread(story["url"]) if src == "Hacker News" else _article(story["url"]))
    except Exception as e:                                # never lose the story over the extra reading
        print(f"   ! could not read the whole thread: {e}")
        found = None
    if found:
        if len(found["text"]) > len(story.get("text") or ""):
            story["text"] = found["text"]
        story["updates"], story["replies"] = found["updates"], found["replies"]
    else:
        story.setdefault("updates", [])
        story.setdefault("replies", [])
    story["similar"] = [f"{platform(c)}, {c.get('date') or 'undated'}: {c['title']}"
                        for c in others if c.get("url") != story["url"] and c.get("title")][:8]
    print(f"   whole story: post {len(story['text'])} chars, {len(story['updates'])} update(s) from the poster, "
          f"{len(story['replies'])} replies, {len(story['similar'])} similar reports")
    return story


# ------------------------------------------------------------------ the post as images
def _excerpt_of(story):
    """The quote for cards and thumbnails: the picked excerpt, else the start of the post."""
    q = (story.get("excerpt") or "").strip()
    if q:
        return q
    words = (story.get("text") or story.get("what_happened") or "").split()
    return " ".join(words[:30]) + ("…" if len(words) > 30 else "")


def story_cards(story, out_dir, brand):
    """The post as 2-4 readable cards (1920x1080 'screenshots'): the post with as much of its text as
    fits, the rest of it, then the poster's update or a top reply. Returns screenshot entries."""
    from PIL import Image, ImageDraw
    from .visuals import font, rounded, wrap
    W, H = 1920, 1080
    CW, MAX_H, PAD = 1560, 940, 64
    LINE, GAP, HEAD_H, FOOT_H = 50, 20, 172, 110          # body line, paragraph gap, header, footer room
    accent = ACCENT.get(story.get("source"), (40, 90, 220))
    where = platform(story)
    body_f, title_f = font("Medium", 36), font("Black", 54)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def lines_of(text):
        out = []
        for para in (text or "").split("\n\n"):
            if para.startswith("• ") and out and out[-1] == "" and len(out) > 1 and out[-2].startswith(("• ", "  ")):
                out.pop()                                   # list items sit close together
            out += [l if i == 0 or not para.startswith("• ") else "  " + l
                    for i, l in enumerate(wrap(probe, para, body_f, CW - PAD * 2 - 80))] + [""]
        return out[:-1]

    def height(lines):
        return sum(LINE if l else GAP for l in lines)

    def take(lines, room):
        """As many lines as fit in `room` pixels, ending at a paragraph break when one is close."""
        n, used = 0, 0
        while n < len(lines) and used + (LINE if lines[n] else GAP) <= room:
            used += LINE if lines[n] else GAP
            n += 1
        if n < len(lines):
            br = max((i for i in range(n) if not lines[i]), default=-1)
            if br >= n - 2:                         # end on a paragraph when that wastes at most 2 lines
                n = br
        return lines[:n], [l for l in lines[n:]]

    def card(header, sub, title, lines, more, name):
        tlines = wrap(probe, title, title_f, CW - PAD * 2)[:2] if title else []
        top = HEAD_H + (66 * len(tlines) + 22 if tlines else 0)
        ch = min(MAX_H, max(520, top + height(lines) + (50 if more else 0) + FOOT_H))
        im = Image.new("RGB", (W, H), (236, 239, 244))
        c = rounded((CW, ch), 34, (255, 255, 255, 255))
        d = ImageDraw.Draw(c)
        d.ellipse([PAD, 52, PAD + 80, 132], fill=accent)
        d.text((PAD + 40, 92), where[0].upper(), font=font("Black", 46), fill=(255, 255, 255), anchor="mm")
        d.text((PAD + 106, 56), header, font=font("Bold", 38), fill=(30, 32, 38))
        d.text((PAD + 106, 104), sub, font=font("Medium", 28), fill=(110, 116, 128))
        ox, oy = (W - CW) // 2, (H - ch) // 2
        boxes, y = [], HEAD_H
        for line in tlines:
            d.text((PAD, y), line, font=title_f, fill=(18, 20, 24))
            y += 66
        if tlines:
            boxes.append({"t": title[:80], "x": ox + PAD, "y": oy + HEAD_H, "w": CW - PAD * 2, "h": y - HEAD_H})
        y, para = top, []
        for line in lines + [""]:
            if line:
                d.text((PAD + 40, y), line, font=body_f, fill=(52, 56, 66))
                para.append((line, y))
            elif para:                     # one box per paragraph: the video can zoom into it
                boxes.append({"t": " ".join(t for t, _ in para)[:200], "x": ox + PAD + 40, "y": oy + para[0][1],
                              "w": CW - PAD * 2 - 40, "h": LINE * len(para)})
                para = []
            y += LINE if line else GAP
        y -= GAP
        if lines:
            d.rounded_rectangle([PAD, top + 4, PAD + 9, y - 10], 5, fill=accent)
        if more:
            d.text((PAD + 40, y + 8), "continued…", font=font("Bold", 30), fill=accent)
        d.text((PAD, ch - 56), f"Public post on {where} · shown for awareness, not verified",
               font=font("Medium", 24), fill=(140, 146, 158))
        im.paste(c, (ox, oy), c)
        im.save(out_dir / name)
        return {"file": name, "page": "the story", "visible_text": (title + " " + " ".join(lines))[:600], "boxes": boxes}

    def strip(lines):
        while lines and not lines[0]:
            lines = lines[1:]
        while lines and not lines[-1]:
            lines = lines[:-1]
        return lines

    date_s = story.get("date") or "public post"
    body = strip(lines_of(story.get("text") or story.get("what_happened") or ""))
    tl = len(wrap(probe, story["title"], title_f, CW - PAD * 2)[:2])
    first, rest = take(body, MAX_H - HEAD_H - 66 * tl - 22 - FOOT_H - 50)
    rest = strip(rest)
    shots = [card(f"Posted on {where}", f"by a {brand} user · {date_s}", story["title"], strip(first), bool(rest), "story.png")]
    while rest and len(shots) < 3:                       # the post's own words first: up to 3 cards
        part, rest = take(rest, MAX_H - HEAD_H - FOOT_H - 50)
        rest = strip(rest)
        shots.append(card(f"Posted on {where}", "the post, continued", "", strip(part), bool(rest),
                          f"story_{len(shots) + 1}.png"))
    extra = None
    if story.get("updates"):
        extra = ("Update from the poster", "later in the same thread", story["updates"][0])
    elif story.get("replies"):
        extra = (f"A reply on {where}", "another user in the thread", story["replies"][0])   # the top reply
    if extra:
        part, left = take(strip(lines_of(extra[2])), MAX_H - HEAD_H - FOOT_H - 50)
        shots.append(card(extra[0], extra[1], "", strip(part), bool(strip(left)), f"story_{len(shots) + 1}.png"))
    return shots


# ------------------------------------------------------------------ the script
SCRIPT_PROMPT = """You write for the YouTube channel "{channel}". This is a RISK CASE video: it raises
awareness of a real risk with a popular product through one real person's public story. It is not an
attack on the product: it is fair, factual and useful.

PRODUCT: {brand} — {url}
THE STORY (a public post on {where}, {date}, {story_url}):
Title: {title}
What the poster says happened: {what_happened}
The full post:
{text}

Later updates from the same poster in the thread (may say how it ended):
{updates}

Replies from other people in the thread (others with the same problem, explanations, advice):
{replies}

Other public reports of similar problems with {brand} (titles only):
{similar}

{focus}Write a 2-3 minute narration: {min_words}-{max_words} words in total (count them).
Structure, in this order:
1. Hook: the story in one or two gripping sentences, attributed simply to the platform: "A {brand}
   user posted on {where}..." Never name a subreddit, group, forum section or username.
2. The whole story, step by step, as the poster tells it: use the full post (quote a few short
   phrases), then what happened next if the poster posted updates (was it resolved? say so plainly),
   and what other people in the thread said (others with the same problem, or the likely explanation
   they gave). If there are similar public reports, say briefly that it is not the only report like
   it, without inventing numbers. Never state claims as proven facts: "they say", "according to the
   post". Do not add details that aren't in the material above.
3. Why this can happen: the most likely real reasons on {brand}'s side (e.g. risk reviews, payout
   holds, terms of service, verification, chargebacks), based on the WEBSITE TEXT and common, well-known
   industry practice. Be fair: say when the company has its side, or when we only have one side.
4. How to avoid it: 3-4 concrete, practical tips.
5. If it happens to you: concrete steps (document everything, official support channels and escalation,
   the company's dispute or appeal process, card dispute/chargeback where relevant, regulators or
   ombudsman such as the CFPB, BBB, state attorney general, small-claims court, a lawyer for large sums).
6. Fair close: this is one person's experience, many users never have this problem; ask viewers
   in the comments if it has happened to them.
Finance/legal topics: one short "not financial or legal advice" line.
Evergreen: never mention the current year or any year.
Style: calm, serious, documentary tone, short spoken sentences. No hype words like "insane".

VISUALS: 8-9 segments of 38-48 words EACH. Each segment shows ONE screenshot from the list below.
The story cards ({story_files}) show the post itself: use them in order for the hook and the
story part (the first {n_story} segments, each card at least once, the narration matching the text on
that card); the product's pages for the rest.
Optionally a "focus": exact short text from that screenshot's ON-SCREEN TEXT. A punchy caption (max 6
words) per segment. On about half the segments a "callout" sticker (max 4 words, e.g. "$70,000 on hold",
"Document everything", "File a CFPB complaint"). An "icon" per segment from: {icons}

SCREENSHOTS:
{shots}

Return ONLY JSON:
{{
  "brand": "{brand}",
  "category": "one of: {cat_ids}",
  "verdict": "Risk case",
  "score": 0,
  "segments": [{{"screenshot": "story.png", "focus": "", "caption": "...", "callout": "", "icon": "warning", "text": "..."}}],
  "youtube_title": "catchy title straight from the story, max 70 characters, the brand first, the claim in the poster's words, ending with a question, e.g. '{brand} FROZE $70,000 for 'No Reason' — What Now?' (at most two words in CAPS, no year)",
  "youtube_description": "150-250 words: what the video covers, that it is based on a public post on {where} (include its link: {story_url}), that it is one person's account we could not independently verify, and the practical takeaways. No hashtags.",
  "tags": ["15-25 real search phrases, e.g. '{brand} froze account', '{brand} holding funds', '{brand} account closed', 'is {brand} safe'"],
  "pinned_comment": "a short comment asking if this has happened to them, and what helped",
  "check_before_publishing": ["claims the human should double-check, including the source link"]
}}

WEBSITE TEXT (the product's own pages):
{home}
{subpages}
"""


def write_script(info, item, story, history):
    from .script import ICONS, _fix_segments, _shots_for_prompt, _validate, YEAR
    brand = story.get("brand") or item.get("name") or info.get("site_name") or info["domain"]
    stories = [x["file"] for x in info["screenshots"] if x["file"].startswith("story")] or ["story.png"]
    prompt = SCRIPT_PROMPT.format(
        channel=config.CHANNEL_NAME, brand=brand, url=info["url"], where=platform(story), date=story.get("date") or "",
        story_url=story["url"], title=story["title"], what_happened=story.get("what_happened", ""),
        text=story["text"][:5000], updates="\n---\n".join(u[:1200] for u in story.get("updates", [])[:4]) or "(none)",
        replies="\n---\n".join(r[:600] for r in story.get("replies", [])[:8]) or "(none)",
        similar="\n".join("- " + x for x in story.get("similar", [])) or "(none found)",
        story_files=", ".join(stories), n_story=max(2, len(stories)),
        focus=(f"FOCUS: the viewer asked for a video about this issue: \"{story['focus']}\". Keep the whole video on it:\n"
               f"why it happens, how to avoid it and what to do are all about this issue.\n\n") if story.get("focus") else "", min_words=320, max_words=390, icons=", ".join(ICONS), shots=_shots_for_prompt(info),
        cat_ids=", ".join(BY_ID), home=info.get("home_text", "")[:6000],
        subpages="\n".join(f"Sub-page {p['url']}: {p['text'][:2500]}" for p in info.get("pages", [])))
    best, best_gap, feedback = None, None, ""
    for attempt in range(4):
        text, _ = ai.ask(prompt + feedback, json_mode=True, temperature=0.7)
        data = ai.parse_json(text)
        problems = _validate(data, info)
        words = sum(len(s.get("text", "").split()) for s in data.get("segments", []))
        gap = abs(words - 355) + (1000 if any("missing" in p for p in problems) else 0)
        if best is None or gap < best_gap:
            best, best_gap = data, gap
        if not problems:
            break
        print(f"   script check: {'; '.join(problems)} — rewriting")
        feedback = "\n\nYOUR PREVIOUS ANSWER HAD PROBLEMS, FIX THEM: " + "; ".join(problems) + "\nReturn the complete JSON again."
    data = _fix_segments(best, info)
    data["kind"] = "risk"
    data["verdict"] = "Risk case"
    if data.get("category") not in BY_ID:
        data["category"] = item.get("category") or "saas"
    title = YEAR.sub("", data.get("youtube_title") or "").strip()
    if not title or brand.lower().split()[0] not in title.lower():
        title = f"{brand}: {story.get('claim') or 'A User’s Worst Experience'} — What Now?"
    data["youtube_title"] = re.sub(r"\s{2,}", " ", title)[:90]
    data["tags"] = [t for t in (YEAR.sub("", x).strip() for x in data.get("tags", [])) if t]
    desc = data.get("youtube_description", "")
    if story["url"] not in desc:
        desc += f"\n\nThe story: {story['url']} (one person's public account; not independently verified)."
    data["youtube_description"] = desc
    data["story"] = {k: story.get(k) for k in ("source", "where", "title", "url", "date", "claim", "amount",
                                                "thumb_big", "thumb_small", "issue", "excerpt")}
    data["story"]["platform"] = platform(story)
    data["story"]["text"] = (story.get("text") or "")[:1500]           # for the thumbnails' post card
    data["story"]["update"] = (story.get("updates") or [""])[0][:400]
    data["story"]["reply"] = (story.get("replies") or [""])[0][:400]
    data["thumbnail_subtitle"] = story.get("thumb_small") or "WHAT HAPPENED?"
    data["check_before_publishing"] = [f"Read the original post and check the video tells it fairly: {story['url']}"] + \
        list(data.get("check_before_publishing") or [])
    return data


RESOLVE_PROMPT = """What is the official website of this app / product / company: "{text}"?
Return ONLY JSON: {{"name": "its proper name, as people write it (e.g. 'Instagram', 'Cash App')",
 "url": "its official homepage, e.g. https://www.instagram.com"}}
If you don't know it, return {{"name": "{text}", "url": ""}}."""


def _reachable(url):
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
        return r.status_code < 500
    except requests.RequestException:
        return False


def resolve_product(text):
    """A typed product ("instagram", "cash app", "robinhood.com") -> (proper name, homepage)."""
    text = text.strip()
    if re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", text):      # it already is a web address
        url = text if "://" in text else "https://" + text
        host = re.sub(r"^www\.", "", url.split("/")[2])
        name = host.split(".")[0].replace("-", " ").title()
        try:                                              # "study.com" is called "Study.com", not "Study"
            got = ai.parse_json(ai.ask(RESOLVE_PROMPT.format(text=host), json_mode=True, temperature=0.1)[0])
            name = str(got.get("name") or "").strip() or name
        except Exception:
            pass
        return name, url
    name, url = text.title() if text.islower() else text, ""
    try:
        got = ai.parse_json(ai.ask(RESOLVE_PROMPT.format(text=text.replace('"', "'")), json_mode=True, temperature=0.1)[0])
        name = str(got.get("name") or name).strip() or name
        url = str(got.get("url") or "").strip()
    except Exception as e:
        print(f"   ! could not look up {text}'s website ({type(e).__name__})")
    if url and "://" not in url:
        url = "https://" + url
    if not url or not _reachable(url):                    # a sensible guess: name.com
        guess = "https://www." + re.sub(r"[^a-z0-9]", "", name.lower()) + ".com"
        url = guess if _reachable(guess) or not url else url
    return name, url


def find_story(brand, url, issue=None):
    cands = gather(brand, issue=issue)
    story = pick_story(brand, url, list(cands), issue)
    story["focus"] = issue or ""
    word = brand.lower().split()[0]
    return investigate(story, [c for c in cands if word in c["title"].lower()])


def candidates(history, n):
    """Products for Risk Cases: well-known ones first (past reviews and the queue's evergreen names,
    not brand-new launches: those rarely have public stories), never one that already had a Risk
    Case, and only products where a quick search finds real stories."""
    from .discover import load_queue
    _, done = used()
    pool = []
    for h in history:
        if h.get("kind") != "risk" and h.get("url"):
            pool.append((site_id(h["url"]), {"name": h.get("brand") or h["url"], "url": h["url"],
                                              "category": h.get("category")}, 2))
    for k, it in load_queue()["items"].items():
        if it.get("launch"):
            continue
        pool.append((k, {"name": it["name"], "url": it["url"], "category": it.get("category")},
                     1 if it.get("evergreen") else 0))
    pool.sort(key=lambda kv: -kv[2])
    out, seen = [], set()
    for k, it, _ in pool:
        sid = site_id(it["url"])
        if sid in seen or sid in done or name_id(it["name"]) in done:
            continue
        seen.add(sid)
        word = it["name"].lower().split()[0]
        hits = [c for c in gather(it["name"], queries=3) if word in c["title"].lower()]
        if len(hits) < 3:
            print(f"   {it['name']}: too few public stories ({len(hits)}), skipped")
            continue
        out.append((k, {**it, "kind": "risk"}))
        if len(out) >= n:
            break
    return out
