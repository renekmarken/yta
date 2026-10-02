"""Step 2: research the product, then write a review script + YouTube metadata with Gemini."""
import json
import random
import re

from . import ai, config
from .categories import BY_ID, describe_for_ai

# Different review formats so videos don't all sound the same.
FORMATS = {
    "first_look": "A guided first look: follow the journey of a new visitor through the site, "
                  "reacting to what you see, then judge it.",
    "pros_cons": "Three real strengths, three real concerns, then a verdict.",
    "fine_print": "A fine-print check: compare the big marketing claims with what the detailed pages, "
                  "fees and terms actually say.",
    "who_for": "Who it's for and who should skip it: build the review around 2-3 types of users.",
    "five_questions": "Answer the 5 questions a careful buyer would ask before signing up.",
    "red_flags": "A trust check: look for green flags and red flags (licensing, transparency, "
                 "pricing clarity, support, reviews), then score it.",
}

HOOKS = ["a pointed question", "a surprising specific detail from the site",
         "a bold claim from the site that you then test", "a short 'here's the catch' teaser",
         "who should stop watching (and who should keep watching)"]

RESEARCH_PROMPT = """Use Google Search. Research "{name}" ({url}) for an honest consumer review, today {today}.
Find, with sources: what it is, who runs it (company, partner bank/carrier/licences if relevant),
current pricing or fees, notable recent news (launch, funding, outages, lawsuits, regulatory action),
what real users praise and complain about (Trustpilot, App Store, BBB, Reddit ratings if available),
and its 2-3 main competitors. Be factual, short bullet points, say 'unknown' when you cannot verify.
Max 250 words."""

SCRIPT_PROMPT = """You write for the YouTube channel "{channel}": honest reviews of US websites and
apps that answer one question: is it worth using?

PRODUCT: {name} — {url}
CATEGORY: {category}
FORMAT FOR THIS VIDEO: {fmt}
OPEN WITH: {hook}
A GOOD REVIEW IN THIS CATEGORY CHECKS: {checklist}

Write a 2-3 minute narration: {min_words}-{max_words} words in total.

Honesty rules (very important):
- Facts must come from the WEBSITE TEXT or the RESEARCH NOTES below. Never invent numbers, ratings
  or features. If something important is not shown, say so and tell viewers what to check.
- When you use a research note, attribute it naturally ("users on Trustpilot mostly complain about...",
  "according to recent reports..."). Treat the website's own claims as claims.
- Do not pretend to have personally used the product. You are walking through what it offers,
  how clear it is, and what to watch out for.
- Balanced: real strengths, real weaknesses or missing info, who it suits, who should look elsewhere.
- Finance/insurance/legal/investing: one short "not financial/legal advice" line near the end.

Style: spoken, confident, specific, short sentences, natural contractions. No "welcome back",
no "in today's video", no "smash that like button", no "let's dive in", no "game-changer".
Do not start with any of these openings used on recent videos: {recent_openers}
End with the verdict and one specific question for the comments.

VISUALS: split the narration into 7-10 segments. Each segment shows ONE screenshot from the list
(most relevant; may repeat but not back-to-back). Optionally pick a "focus" for the segment:
an exact short text from that screenshot's ON-SCREEN TEXT list that the camera should zoom to and
highlight (e.g. a price, rate, headline, button). Use focus on about half the segments, only when it
matches what you are saying. Give each segment a punchy on-screen caption (max 6 words).

SCREENSHOTS:
{shots}

Return ONLY JSON:
{{
  "brand": "brand name as written on the site",
  "category": "one of: {cat_ids}",
  "verdict": "Worth it | Worth it for some | Not worth it",
  "score": 7.5,
  "segments": [{{"screenshot": "home_0.png", "focus": "exact on-screen text or empty", "caption": "...", "text": "..."}}],
  "youtube_title": "max 70 chars: brand + 'Review' or 'Worth It?' + 2026 + a curiosity hook; no ALL CAPS words except 1",
  "youtube_description": "150-250 words, natural keyword-rich summary of what the review covers; no timestamps, no hashtags",
  "tags": ["15-25 real search phrases, e.g. '<brand> review', 'is <brand> legit', '<brand> vs <competitor>', '<category> 2026'"],
  "thumbnail_subtitle": "2-4 word hook for the thumbnail, e.g. 'Hidden fees?', 'Legit or hype?'",
  "pinned_comment": "a short first comment that invites discussion",
  "check_before_publishing": ["specific claims or numbers the human reviewer should double-check"]
}}

RESEARCH NOTES (web, may be incomplete):
{research}

WEBSITE TEXT:
Title: {title}
Meta description: {meta}
Homepage: {home}
{subpages}
"""


def research(name, url):
    if not config.USE_WEB_RESEARCH:
        return "", []
    from datetime import date
    try:
        text, sources = ai.ask(RESEARCH_PROMPT.format(name=name, url=url, today=date.today()),
                               grounded=True, temperature=0.2)
        clean = []
        for s in sources[:8]:
            real = ai.resolve_url(s["url"])
            if "grounding-api-redirect" not in real:
                clean.append({"title": s["title"], "url": real})
        return text.strip(), clean
    except Exception as e:
        print(f"   research skipped: {str(e)[:200]}")
        return "", []


def _shots_for_prompt(info):
    lines = []
    for s in info["screenshots"]:
        texts = [b["t"] for b in s.get("boxes", [])][:25]
        lines.append(f"- {s['file']} ({s['page']}): {s.get('visible_text', '')[:220]}\n"
                     f"  ON-SCREEN TEXT: {json.dumps(texts, ensure_ascii=False)}")
    return "\n".join(lines)


def _validate(data, info):
    problems = []
    words = sum(len(s.get("text", "").split()) for s in data.get("segments", []))
    if not 300 <= words <= 520:
        problems.append(f"narration is {words} words; it must be 330-450 words")
    if not 6 <= len(data.get("segments", [])) <= 12:
        problems.append("use 7-10 segments")
    for k in ("youtube_title", "youtube_description", "tags", "verdict"):
        if not data.get(k):
            problems.append(f"missing {k}")
    if len(data.get("youtube_title", "")) > 100:
        problems.append("title too long")
    return problems


def _fix_segments(data, info):
    files = [s["file"] for s in info["screenshots"]]
    boxes = {s["file"]: s.get("boxes", []) for s in info["screenshots"]}
    prev = None
    for i, seg in enumerate(data["segments"]):
        if seg.get("screenshot") not in files:
            seg["screenshot"] = files[i % len(files)]
        if seg["screenshot"] == prev and len(files) > 1:         # avoid the same image twice in a row
            alt = [f for f in files if f != prev and f != "mobile.png"]
            if alt:
                seg["screenshot"] = alt[i % len(alt)]
                seg["focus"] = ""
        prev = seg["screenshot"]
        # keep focus only if that text really is on that screenshot
        f = (seg.get("focus") or "").strip().lower()
        match = None
        if f:
            for b in boxes.get(seg["screenshot"], []):
                if f == b["t"].lower() or (len(f) > 3 and f in b["t"].lower()):
                    match = b
                    break
        seg["focus_box"] = match
        seg["caption"] = " ".join(seg.get("caption", "").split()[:7])
    return data


def write_script(info: dict, item: dict, history: list) -> dict:
    name = item.get("name") or info.get("site_name") or info["domain"]
    notes, sources = research(name, info["url"])
    cat = BY_ID.get(item.get("category"))
    rnd = random.Random(info["domain"] + str(len(history)))
    recent_formats = [h.get("format") for h in history[-3:]]
    fmt_key = rnd.choice([k for k in FORMATS if k not in recent_formats] or list(FORMATS))
    recent_openers = [h.get("opener", "") for h in history[-8:] if h.get("opener")]

    prompt = SCRIPT_PROMPT.format(
        channel=config.CHANNEL_NAME, name=name, url=info["url"],
        category=cat["name"] if cat else "decide from the site (pick the closest id)",
        fmt=FORMATS[fmt_key], hook=rnd.choice(HOOKS),
        checklist="; ".join(cat["checklist"]) if cat else "pricing, trust signals, who it is for",
        min_words=340, max_words=440,
        recent_openers=json.dumps(recent_openers, ensure_ascii=False) if recent_openers else "none yet",
        shots=_shots_for_prompt(info), cat_ids=", ".join(BY_ID),
        research=notes or "none available",
        title=info.get("title", ""), meta=info.get("meta_description", ""),
        home=info.get("home_text", "")[:9000],
        subpages="\n".join(f"Sub-page {p['url']}: {p['text'][:3500]}" for p in info.get("pages", [])))

    data, feedback = None, ""
    for attempt in range(2):
        text, _ = ai.ask(prompt + feedback, json_mode=True, temperature=0.8)
        data = ai.parse_json(text)
        problems = _validate(data, info)
        if not problems:
            break
        print(f"   script check: {'; '.join(problems)} — rewriting")
        feedback = "\n\nYOUR PREVIOUS ANSWER HAD PROBLEMS, FIX THEM: " + "; ".join(problems)

    data = _fix_segments(data, info)
    if data.get("category") not in BY_ID:
        data["category"] = item.get("category") or "saas"
    data["format"] = fmt_key
    data["research_notes"] = notes
    data["sources"] = sources
    return data
