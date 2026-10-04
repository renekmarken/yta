"""Step 2: research the product, then write a review script + YouTube metadata with Gemini."""
import json
import random
import re

from . import ai, config
from .categories import BY_ID, describe_for_ai
from .icons import ICONS

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

# Title formats (rotated so the channel doesn't repeat itself). {b} = brand.
TITLE_STYLES = {
    "scam": "{b}: Is It a Scam?",
    "expect": "{b}: What to Actually Expect (EXPLAINED)",
    "worth": "{b}: Worth Using It?",
    "legit": "{b}: Legit or Overhyped?",
    "before": "{b}: Watch This Before You Sign Up",
    "catch": "{b}: What's the Catch?",
    "truth": "{b} Review: The Honest Truth",
    "fees": "{b}: The Fees Nobody Mentions",
    "dont": "Don't Use {b} Until You Watch This",
    "actually": "Is {b} Actually Worth It?",
    "good": "{b}: Is It Actually Good?",
    "honest": "{b} Honest Review: Pros, Cons & Verdict",
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

Write a 2-3 minute narration: {min_words}-{max_words} words in total (count them; this is a hard limit).

Honesty rules (very important):
- Facts must come from the WEBSITE TEXT or the RESEARCH NOTES below. Never invent numbers, ratings
  or features. If something important is not shown, say so and tell viewers what to check.
- When you use a research note, attribute it naturally ("users on Trustpilot mostly complain about...",
  "according to recent reports..."). Treat the website's own claims as claims.
- Do not pretend to have personally used the product. You are walking through what it offers,
  how clear it is, and what to watch out for.
- Balanced: real strengths, real weaknesses or missing info, who it suits, who should look elsewhere.
- Finance/insurance/legal/investing: one short "not financial/legal advice" line near the end.

Evergreen: never mention the current year or any year, and avoid "right now"/"this year" phrasing,
so the video stays useful for years. (Facts that change, like prices, are fine: say "at the time of recording".)
Style - sound like a real, friendly person talking to a friend, not a narrator reading an article:
- Very simple words a 12-year-old gets. Short sentences. Contractions always (it's, you'll, don't).
  Explain any jargon in plain words the moment you use it ("APY, so basically the interest you earn").
- Natural spoken glue, used now and then (not in every sentence): "Okay, now...", "So...",
  "Alright,", "Honestly,", "Here's the thing:", "kinda", "pretty", "a bit", "Now, this part's
  interesting." Vary them; never the same one twice in a row.
- A little light humour: 2-3 small, kind jokes or wry asides in the whole script (e.g. "which is
  a lot of words for 'we keep some of it'", "my wallet flinched a bit there"). Never mock the
  viewer or real people, never jokes about money troubles, health or anything sensitive.
- React like a human: short honest reactions ("Okay, that's actually nice.", "Hmm, not great.").
- Talk to the viewer as "you". Calls to action, natural and short: early on, a light "stick
  around, the fine print's coming"; mid-video one friendly "if this is helping, a like really
  helps the channel"; at the end, the verdict, then one specific question for the comments.
- Flow: it must feel like ONE conversation, not a list of separate clips. Every segment's first
  sentence picks up where the last one ended, with a real link, not a reset: "Which brings us to
  the price.", "But here's the flip side.", "And that's actually where it gets better.", "Okay, so
  that's the good stuff. Now the stuff they don't put on the billboard." Never start two segments
  the same way. Each segment ends on a little pull forward (a question, a "but...", a tease).
- Pros and cons, whatever the format: somewhere in the middle, clearly walk through the real pros
  (2-3, each with a specific detail from the site or research) and the real cons (2-3, same), said
  naturally ("Okay, the good stuff first." ... "Now, the not-so-good stuff."), then weigh them
  against each other before the verdict ("So is the good enough to make up for the annoying bits?").
- The verdict ties back to the opening hook, so the video closes the loop it opened.
- No "welcome back", no "in today's video", no "smash that like button", no "let's dive in",
  no "game-changer", no stage directions, no emojis, no [laughs] or other sound cues.
Do not start with any of these openings used on recent videos: {recent_openers}

VISUALS: split the narration into 8-9 segments of 38-48 words EACH (2-4 full sentences per
segment; short one-line segments make the video too short). Each segment shows ONE screenshot from the list
(most relevant; may repeat but not back-to-back). Optionally pick a "focus" for the segment:
an exact short text from that screenshot's ON-SCREEN TEXT list that the camera should zoom to and
highlight (e.g. a price, rate, headline, button). Use focus on about half the segments, only when it
matches what you are saying. Give each segment a punchy on-screen caption (max 6 words).
On about half the segments add a "callout": the ONE key fact said in that segment as a tiny sticker,
max 4 words, ideally with a number (e.g. "$0 monthly fee", "4.30% APY", "No phone support",
"Free 30-day trial"). Only use facts from the sources below; leave it empty otherwise.
Give every segment an "icon" that matches what it is about, chosen from: {icons}

SCREENSHOTS:
{shots}

Return ONLY JSON:
{{
  "brand": "brand name as written on the site",
  "category": "one of: {cat_ids}",
  "verdict": "Worth it | Worth it for some | Not worth it",
  "score": 7.5,
  "segments": [{{"screenshot": "home_0.png", "focus": "exact on-screen text or empty", "caption": "...", "callout": "short fact or empty", "icon": "payments", "text": "..."}}],
  "youtube_title": "{title_rule}",
  "youtube_description": "150-250 words, natural keyword-rich summary of what the review covers; no timestamps, no hashtags",
  "tags": ["15-25 real search phrases, e.g. '<brand> review', 'is <brand> legit', 'is <brand> a scam', '<brand> vs <competitor>', 'best <category>' — never a year"],
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


YEAR = re.compile(r"\b(19|20)\d{2}\b")


def clean_title(title, brand, style_key):
    """Short, evergreen title: no years, tidy punctuation; falls back to the plain style."""
    t = YEAR.sub("", title or "")
    t = re.sub(r"\(\s*\)|\[\s*\]", "", t)
    t = re.sub(r"\s+([:?!,.])", r"\1", re.sub(r"\s{2,}", " ", t))
    t = re.sub(r"(^[\s:|–-]+|[\s:|–-]+$)", "", t).strip()
    t = re.sub(r":\s*:", ":", t)
    if not t or len(t) > 70 or (brand and brand.lower().split()[0] not in t.lower()):
        t = TITLE_STYLES.get(style_key, "{b}: Worth Using It?").format(b=brand or "This App")
    return t


def _validate(data, info):
    problems = []
    words = sum(len(s.get("text", "").split()) for s in data.get("segments", []))
    if not 290 <= words <= 410:       # ~2-3 minute video at the voice's speed
        problems.append(f"narration is {words} words; it must be 320-390 words")
    if not 6 <= len(data.get("segments", [])) <= 12:
        problems.append("use 7-10 segments")
    for k in ("youtube_title", "youtube_description", "tags", "verdict"):
        if not data.get(k):
            problems.append(f"missing {k}")
    title = data.get("youtube_title", "")
    if len(YEAR.sub("", title)) > 75:                 # years are removed afterwards anyway
        problems.append(f"title is {len(title)} characters; keep it under 60")
    return problems


STIFF = [r"\blet us\b", r"\bwe tested\b", r"\bwe will\b", r"\bwe looked\b", r"\bin conclusion\b",
         r"\bfurthermore\b", r"\bmoreover\b", r"\bboldly claims\b", r"\bnext-generation\b"]
UNCONTRACTED = r"\b(it is|do not|does not|you are|you will|that is|there is|is not|are not|can not|cannot|we are|i am|they are|you would|it will)\b"
CONTRACTED = r"\b\w+'(s|t|re|ll|ve|d|m)\b"
MARKERS = ["okay", "so,", "so ", "honestly", "here's the thing", "kinda", "pretty", "alright", "now,",
           "a bit", "which brings", "but here's", "flip side"]
CONNECT = ("but", "and", "so", "okay", "now", "which", "that", "alright", "here", "honestly", "plus",
           "still", "speaking", "on the", "the good", "the not", "then", "next", "oh", "right")


def tone_problems(data):
    """Does the narration sound like a friendly person and flow? Returns the problems (empty = fine)."""
    segs = [str(x.get("text", "")) for x in data.get("segments", [])]
    text = " ".join(segs).replace("’", "'")
    low = text.lower()
    out = []
    stiff = [re.search(p, low).group(0) for p in STIFF if re.search(p, low)]
    if stiff:
        out.append("it sounds stiff, never say: " + ", ".join(sorted(set(stiff))))
    unc, con = len(re.findall(UNCONTRACTED, low)), len(re.findall(CONTRACTED, low))
    if unc > 2 or con < 8:
        out.append(f"use natural contractions everywhere (it's, don't, you're, that's): found {con} contractions "
                   f"and {unc} un-contracted forms")
    if sum(low.count(m) for m in MARKERS) < 5:
        out.append('talk like a friendly person: use natural glue like "Okay, now...", "So...", "Honestly,", '
                   '"Here\'s the thing:", "kinda", "pretty" (varied, at least 5 in total)')
    if not (re.search(r"good stuff|the good|pros?\b|what i like|what's good", low)
            and re.search(r"not-so-good|not so good|cons?\b|downside|the bad|annoying|catch", low)):
        out.append('walk through the pros AND the cons clearly ("Okay, the good stuff first." ... '
                   '"Now, the not-so-good stuff.")')
    starts = [re.sub(r"[^a-z' ]", "", sg.lower()).strip() for sg in segs[1:]]
    linked = sum(1 for st in starts if st.startswith(CONNECT))
    if starts and linked < len(starts) * 0.5:
        out.append("the segments don't flow: start most segments with a link to the one before "
                   '("But here\'s the flip side.", "Which brings us to the price.", "Okay, so...")')
    firsts = [st.split()[0] if st else "" for st in starts]
    if any(firsts[i] and firsts[i] == firsts[i + 1] for i in range(len(firsts) - 1)):
        out.append("two segments in a row start with the same word; vary them")
    if "like" not in low or "comment" not in low:
        out.append("add the friendly calls to action (a like mid-video, a comment question at the end)")
    return out


POLISH_PROMPT = """Rewrite ONLY the narration of these review segments so it sounds like a real, friendly
person talking to a friend, and flows as one conversation. Keep every fact, number and claim exactly;
add nothing new. Keep the same number of segments and roughly the same words per segment (38-48).
- Very simple words, short sentences, contractions everywhere (it's, don't, you're).
- Natural glue, varied: "Okay, now...", "So...", "Honestly,", "Here's the thing:", "kinda", "pretty".
- Each segment starts by picking up where the last ended ("But here's the flip side.", "Which
  brings us to the price."), no two segments start with the same word.
- Clear pros ("Okay, the good stuff first.") and cons ("Now, the not-so-good stuff."), then a weigh-up.
- 2-3 small, kind jokes or wry asides. A friendly like-ask mid-video; the verdict and one specific
  comment question at the end. No "let us", no "we tested", no stage directions or [sound cues].
These problems were found: {problems}
Return ONLY JSON: {{"texts": ["segment 1 narration", "segment 2 narration", ...]}}

SEGMENTS:
{segments}"""


def polish(data, problems):
    """One extra pass that only rewrites the narration's tone and flow (facts stay)."""
    segs = data.get("segments", [])
    try:
        text, _ = ai.ask(POLISH_PROMPT.format(problems="; ".join(problems),
                                              segments=json.dumps([x.get("text", "") for x in segs], ensure_ascii=False)),
                         json_mode=True, temperature=0.7)
        texts = ai.parse_json(text).get("texts", [])
    except Exception as e:
        print(f"   ! tone polish failed: {str(e)[:120]}")
        return data
    if len(texts) != len(segs):
        return data
    new = sum(len(str(t).split()) for t in texts)
    if not 290 <= new <= 420:
        return data
    for sg, t in zip(segs, texts):
        sg["text"] = re.sub(r"\s+", " ", str(t)).strip()
    return data


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
        callout = " ".join(str(seg.get("callout") or "").split()[:5])
        seg["callout"] = callout if 2 <= len(callout) <= 34 else ""
        icon = str(seg.get("icon") or "").strip().lower().replace(" ", "_")
        seg["icon"] = icon if icon in ICONS else ""
    return data


def write_script(info: dict, item: dict, history: list) -> dict:
    name = item.get("name") or info.get("site_name") or info["domain"]
    notes, sources = research(name, info["url"])
    cat = BY_ID.get(item.get("category"))
    rnd = random.Random(info["domain"] + str(len(history)))
    recent_formats = [h.get("format") for h in history[-3:]]
    fmt_key = rnd.choice([k for k in FORMATS if k not in recent_formats] or list(FORMATS))
    recent_openers = [h.get("opener", "") for h in history[-8:] if h.get("opener")]
    recent_styles = [h.get("title_style") for h in history[-8:]]
    style_key = rnd.choice([k for k in TITLE_STYLES if k not in recent_styles] or list(TITLE_STYLES))
    style = TITLE_STYLES[style_key].format(b="<brand>")
    title_rule = (f"SHORT, max 60 characters, no year. Use this format: '{style}'. You may swap the generic part "
                  f"for ONE concrete detail from the facts if it makes it more specific and clickable (e.g. "
                  f"'<brand>: $0 Fees, But What's the Catch?'). Title Case, at most one word in CAPS.")

    prompt = SCRIPT_PROMPT.format(
        channel=config.CHANNEL_NAME, name=name, url=info["url"],
        category=cat["name"] if cat else "decide from the site (pick the closest id)",
        fmt=FORMATS[fmt_key], hook=rnd.choice(HOOKS),
        checklist="; ".join(cat["checklist"]) if cat else "pricing, trust signals, who it is for",
        min_words=320, max_words=390,
        recent_openers=json.dumps(recent_openers, ensure_ascii=False) if recent_openers else "none yet",
        shots=_shots_for_prompt(info), cat_ids=", ".join(BY_ID), icons=", ".join(ICONS),
        title_rule=title_rule,
        research=notes or "none available",
        title=info.get("title", ""), meta=info.get("meta_description", ""),
        home=info.get("home_text", "")[:9000],
        subpages="\n".join(f"Sub-page {p['url']}: {p['text'][:3500]}" for p in info.get("pages", [])))

    data, feedback = None, ""
    best, best_gap = None, None
    for attempt in range(4):
        text, _ = ai.ask(prompt + feedback, json_mode=True, temperature=0.8)
        data = ai.parse_json(text)
        problems = _validate(data, info)
        tone = tone_problems(data)
        problems += tone
        words = sum(len(s.get("text", "").split()) for s in data.get("segments", []))
        gap = abs(words - 355) + (1000 if any("missing" in p for p in problems) else 0) + 40 * len(tone)
        if best is None or gap < best_gap:
            best, best_gap = data, gap
        if not problems:
            break
        print(f"   script check: {'; '.join(problems)} — rewriting")
        hint = ""
        if words < 320:
            hint = (f" Your narration has {words} words; it needs {320 - words}-{390 - words} MORE. Keep the same "
                    f"segments but add 1-2 specific sentences to each (what the page shows, a number, who it suits, "
                    f"a caveat), so every segment has 38-48 words.")
        elif words > 390:
            hint = f" Your narration has {words} words; cut {words - 390}-{words - 320} words, keep every fact."
        feedback = ("\n\nYOUR PREVIOUS ANSWER HAD PROBLEMS, FIX THEM: " + "; ".join(problems) + hint +
                    "\nReturn the complete JSON again.")
    data = best
    tone = tone_problems(data)
    if tone:                                                # still stiff: one pass just for tone and flow
        print(f"   tone check: {'; '.join(tone)} — polishing the narration")
        data = polish(data, tone)
        left = tone_problems(data)
        print("   tone: " + ("ok" if not left else "; ".join(left)))

    data = _fix_segments(data, info)
    if data.get("category") not in BY_ID:
        data["category"] = item.get("category") or "saas"
    data["format"] = fmt_key
    data["title_style"] = style_key
    data["youtube_title"] = clean_title(data.get("youtube_title"), data.get("brand") or name, style_key)
    data["tags"] = [t for t in (YEAR.sub("", x).strip() for x in data.get("tags", [])) if t]
    desc = re.sub(r"\s*\b(in|for|of|as of|during)\s+(19|20)\d{2}\b", "", data.get("youtube_description", ""), flags=re.I)
    data["youtube_description"] = re.sub(r"\s*\(?\b(19|20)\d{2}\b\)?", "", desc).replace("  ", " ").strip()
    data["research_notes"] = notes
    data["sources"] = sources
    return data
