"""Risk Case videos: one real user's worst experience with a product, explained.

The point is awareness, not attacking the product: the video retells a real, public story (a Reddit
post, a Hacker News thread, a news report), explains what most likely happened and why, how to avoid
it and what to do if it happens to you, and makes clear it is one person's account.

Pipeline (all free, no login):
  gather()        search Reddit (RSS search), Hacker News (Algolia) and Google News for
                  "<brand> froze account", "<brand> closed my account", "<brand> lost money", ...
  pick_story()    Gemini picks the strongest *real* candidate by its number (it can't invent one)
                  and extracts the claim, the amount and the thumbnail words
  story_card()    a clean "post" card (source, title, short excerpt) used as a screenshot in the video
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
    """(story urls, product ids) already turned into a Risk Case."""
    d = _load()
    return ({c.get("story_url") for c in d["cases"]},
            {c.get("site") for c in d["cases"] if c.get("status") == "done"} |
            {c.get("name") for c in d["cases"] if c.get("status") == "done" and c.get("name")})


def record(url, name, story_url, title, status):
    d = _load()
    d["cases"].append({"date": date.today().isoformat(), "site": site_id(url), "name": name_id(name),
                       "story_url": story_url, "title": title, "status": status})
    config.DATA_DIR.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(d, indent=1, ensure_ascii=False))


# ------------------------------------------------------------------ sources
def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
        return r if r.status_code == 200 else None
    except requests.RequestException:
        return None


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _reddit(query):
    r = _get(f"https://www.reddit.com/search.rss?q={quote(query)}&sort=relevance&t=all&limit=15")
    if not r:
        return []
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


def gather(brand):
    """Real public posts about bad experiences with `brand`, from several sources."""
    words = brand.lower().split()[0]
    cands, seen = [], set()
    for i, p in enumerate(PROBLEMS[:8]):
        q = f'{brand} {p}'
        for c in _reddit(q) + (_hn(q) if i < 4 else []) + (_news(q) if i < 3 else []):
            hay = (c["title"] + " " + c["text"]).lower()
            if c["url"] in seen or words not in hay:
                continue
            if len(c["text"]) < 120 and not re.search(r"\$\s?\d", c["title"]):
                continue
            seen.add(c["url"])
            cands.append(c)
        time.sleep(1.2)                                 # be polite to the free endpoints
    print(f"   stories found: {len(cands)} ({', '.join(sorted({c['source'] for c in cands})) or 'none'})")
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

POSTS:
{posts}
"""


def pick_story(brand, url, cands):
    used_urls, _ = used()
    cands = [c for c in cands if c["url"] not in used_urls]
    if not cands:
        raise NoStory(f"no public stories found for {brand}")
    word = brand.lower().split()[0]
    hurt = re.compile(r"froze|frozen|freez|closed|banned|suspend|hold|held|lost|stole|scam|refund|locked|charged|terminated", re.I)
    cands.sort(key=lambda c: -(3 * (word in c["title"].lower()) + 2 * bool(hurt.search(c["title"]))
                               + bool(re.search(r"\$\s?\d", c["title"] + c["text"][:600])) + (len(c["text"]) > 400)))
    cands = cands[:30]
    posts = "\n\n".join(f"[{i}] ({c['where']}, {c['date']}) {c['title']}\n{c['text'][:900]}" for i, c in enumerate(cands))
    text, _ = ai.ask(PICK_PROMPT.format(brand=brand, url=url, posts=posts, used=", ".join(list(used_urls)[:20]) or "none"),
                     json_mode=True, temperature=0.3)
    pick = ai.parse_json(text)
    i = pick.get("index", -1) if isinstance(pick, dict) else -1
    if not isinstance(i, int) or not 0 <= i < len(cands):
        raise NoStory(f"no usable story for {brand} among {len(cands)} posts")
    story = {**cands[i], **{k: str(pick.get(k, "")).strip() for k in
                            ("claim", "amount", "thumb_big", "thumb_small", "what_happened", "excerpt", "issue")}}
    if story["excerpt"] and story["excerpt"].lower()[:30] not in (story["title"] + " " + story["text"]).lower():
        story["excerpt"] = ""                          # only real quotes
    print(f"   story: {story['where']} — {story['title'][:80]} ({story['url']})")
    return story


# ------------------------------------------------------------------ the post as an image
def story_card(story, out_dir, brand):
    """A clean, readable card of the post (source, title, short excerpt) as a 1920x1080 'screenshot'."""
    from PIL import Image, ImageDraw
    from .visuals import font, rounded, wrap
    W, H = 1920, 1080
    im = Image.new("RGB", (W, H), (236, 239, 244))
    card = rounded((1500, 820), 34, (255, 255, 255, 255))
    d = ImageDraw.Draw(card)
    accent = {"Reddit": (255, 69, 0), "Hacker News": (255, 102, 0)}.get(story["source"], (40, 90, 220))
    d.ellipse([60, 56, 140, 136], fill=accent)
    d.text((100, 96), story["source"][0], font=font("Black", 46), fill=(255, 255, 255), anchor="mm")
    d.text((166, 62), story["where"] or story["source"], font=font("Bold", 38), fill=(30, 32, 38))
    d.text((166, 110), f"{story['source']} · {story.get('date') or 'public post'}", font=font("Medium", 28),
           fill=(110, 116, 128))
    tf = font("Black", 62)
    y = 190
    for line in wrap(d, story["title"], tf, 1380)[:3]:
        d.text((60, y), line, font=tf, fill=(18, 20, 24))
        y += 78
    excerpt = story.get("excerpt") or (story.get("what_happened") or "")[:220]
    if excerpt:
        y += 24
        bf = font("Medium", 40)
        lines = wrap(d, ("“" + excerpt + "”") if story.get("excerpt") else excerpt, bf, 1300)[:4]
        d.rounded_rectangle([60, y, 70, y + 56 * len(lines) - 8], 5, fill=accent)
        for line in lines:
            d.text((100, y), line, font=bf, fill=(52, 56, 66))
            y += 56
    d.text((60, 740), story["url"][:90], font=font("Medium", 26), fill=(120, 126, 138))
    im.paste(card, ((W - card.width) // 2, (H - card.height) // 2), card)
    p = out_dir / "story.png"
    im.save(p)
    boxes = [{"t": story["title"][:80], "x": 210, "y": 320, "w": 1380, "h": 240}]
    if story.get("amount"):
        boxes.append({"t": story["amount"], "x": 210, "y": 320, "w": 700, "h": 90})
    return {"file": "story.png", "page": "the story", "visible_text": story["title"], "boxes": boxes}


# ------------------------------------------------------------------ the script
SCRIPT_PROMPT = """You write for the YouTube channel "{channel}". This is a RISK CASE video: it raises
awareness of a real risk with a popular product through one real person's public story. It is not an
attack on the product: it is fair, factual and useful.

PRODUCT: {brand} — {url}
THE STORY (from {where}, {date}, {story_url}):
Title: {title}
What the poster says happened: {what_happened}
Post text (excerpt): {text}

Write a 2-3 minute narration: {min_words}-{max_words} words in total (count them).
Structure, in this order:
1. Hook: the story in one or two gripping sentences, clearly attributed ("One {brand} user on {where} says...").
2. What happened, step by step, as the poster tells it. Never state their claims as proven facts:
   "they say", "according to the post". Do not add details that aren't in the post.
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

VISUALS: 8-9 segments of 38-48 words EACH. Each segment shows ONE screenshot from the list below
(the story card "story.png" for the hook and the story part; the product's pages for the rest).
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
  "youtube_description": "150-250 words: what the video covers, that it is based on a public post (name the source and include its link: {story_url}), that it is one person's account we could not independently verify, and the practical takeaways. No hashtags.",
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
    prompt = SCRIPT_PROMPT.format(
        channel=config.CHANNEL_NAME, brand=brand, url=info["url"], where=story["where"], date=story.get("date") or "",
        story_url=story["url"], title=story["title"], what_happened=story.get("what_happened", ""),
        text=story["text"][:3000], min_words=320, max_words=390, icons=", ".join(ICONS), shots=_shots_for_prompt(info),
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
                                                "thumb_big", "thumb_small", "issue")}
    data["thumbnail_subtitle"] = story.get("thumb_small") or "WHAT HAPPENED?"
    data["check_before_publishing"] = [f"Read the original post and check the video tells it fairly: {story['url']}"] + \
        list(data.get("check_before_publishing") or [])
    return data


def find_story(brand, url):
    cands = gather(brand)
    return pick_story(brand, url, cands)


def candidates(history, n):
    """Products for Risk Cases: popular ones from the review queue and past reviews (big names have the
    most public stories), never one that already had a Risk Case."""
    from .discover import load_queue, priority
    _, done = used()
    pool, seen = [], set()
    q = load_queue()
    for k, it in sorted(q["items"].items(), key=lambda kv: -priority(kv[1])):
        pool.append((k, {"name": it["name"], "url": it["url"], "category": it.get("category"),
                         "pop": float(it.get("hotness", 5)) + (3 if it.get("evergreen") else 0)}))
    for h in history:
        if h.get("kind") != "risk" and h.get("url"):
            pool.append((site_id(h["url"]), {"name": h.get("brand") or h["url"], "url": h["url"],
                                              "category": h.get("category"), "pop": 9}))
    out = []
    for k, it in sorted(pool, key=lambda kv: -kv[1]["pop"]):
        sid = site_id(it["url"])
        if sid in seen or sid in done or name_id(it["name"]) in done:
            continue
        seen.add(sid)
        out.append((k, {**{x: it[x] for x in ("name", "url", "category")}, "kind": "risk"}))
        if len(out) >= n:
            break
    return out
