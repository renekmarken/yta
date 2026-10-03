"""White Screen videos, part 1: what to make and what to say.

A White Screen video is 35-45 seconds of a voice talking straight to the viewer over a plain white
16:9 screen, the words appearing one by one in big black letters. The whole point is likes and
comments: "This video is going private very soon... comment I WAS HERE".

  TITLES        the queue of proven formats ([Private Video], This Video Has 0 Comments, Face Reveal...),
                weighted so the error-style ones ([Private Video], [Deleted Video]...) come up more often;
                a title can come back, with a fresh script (different goal, comment word and twist)
  write()       Gemini writes the script in the channel's own style (assets/whitescreen/examples.md),
                knowing today's date so every "I'll bring it back in ..." makes sense
"""
import json
import random
import re
from datetime import datetime, timedelta, timezone

from . import ai, config

EXAMPLES = config.ASSETS_DIR / "whitescreen" / "examples.md"
TITLES_FILE = config.DATA_DIR / "whitescreen_titles.json"

# kind: error (the [Private Video] family, shown with a sad YouTube face), count, deadline, goal,
# reveal, dare, pin, only. weight: how often it comes up.
DEFAULT_TITLES = [
    ("[Private Video]", "error", 4), ("[Deleted Video]", "error", 4), ("[Removed Video]", "error", 3),
    ("[Unlisted Video]", "error", 3), ("[Glitched Video]", "error", 2), ("[Cursed Video]", "error", 2),
    ("[Locked Video]", "error", 2), ("[No Access]", "error", 2), ("[Secret Video]", "error", 2),
    ("[Deleted Content]", "error", 2), ("<Private Video>", "error", 2), ("{{Glitched Video}}", "error", 1),
    ("[Hidden Video]", "error", 2), ("[Video Unavailable]", "error", 2),
    ("This Video Has 0 Comments", "count", 2), ("This Video Has 0 Likes", "count", 2),
    ("This Video Has 0 Likes And 0 Comments", "count", 2), ("This Video Has 1 Comment", "count", 1),
    ("This Video Has 1 View", "count", 1), ("This Video Has 5 Comments", "count", 1),
    ("This Video Will Self Destruct In 24 Hours...", "deadline", 2), ("This Video Will Be Deleted Tomorrow", "deadline", 2),
    ("This Video Disappears In 1 Hour", "deadline", 2), ("I'm Deleting This in 2 Days...", "deadline", 2),
    ("Watch This Before It's Gone...", "deadline", 1),
    ("This Video Won't Get 1,000 Comments", "goal", 1), ("Can This Video Get 10 Million Views?", "goal", 1),
    ("Only 67 People Can Comment", "goal", 1), ("Let's Balance The Likes & Comments", "goal", 1),
    ("This Video Won't Get 1 Million Views", "goal", 1),
    ("Face Reveal...", "reveal", 2), ("Face Reveal Final Chance...", "reveal", 1), ("My REAL Age Reveal", "reveal", 1),
    ("Don't Pause This Video", "dare", 1), ("Don't Watch This Video Twice", "dare", 1),
    ("Don't Be The 1st Person To Comment", "dare", 1), ("this video is upside down", "dare", 1),
    ("First Comment Gets Pinned", "pin", 1), ("The WEIRDEST Comment Gets Pinned...", "pin", 1),
    ("I Will Heart Every Comment", "pin", 1),
    ("Only YOU can comment on this video", "only", 1), ("Only You Can Watch This Video", "only", 1),
    ("Only Verified YouTubers Can Comment", "only", 1), ("SECRET VIDEO", "only", 1),
]


def load_titles():
    if TITLES_FILE.exists():
        try:
            return json.loads(TITLES_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return [{"title": t, "kind": k, "weight": w} for t, k, w in DEFAULT_TITLES]


def save_titles(rows):
    config.DATA_DIR.mkdir(exist_ok=True)
    TITLES_FILE.write_text(json.dumps(rows, indent=1, ensure_ascii=False))


def kind_of(title):
    t = title.lower()
    if re.match(r"^[\[<{(]", title.strip()):
        return "error"
    for k, words in (("count", ("has 0", "has 1", "has 5", " 0 ", "1 view")),
                     ("deadline", ("delete", "destruct", "disappear", "gone", "hour", "tomorrow", "days")),
                     ("reveal", ("reveal",)), ("pin", ("pinned", "heart every")),
                     ("goal", ("million", "comments", "balance", "people can", "1,000")),
                     ("dare", ("don't", "dont", "upside")), ("only", ("only",))):
        if any(w in t for w in words):
            return k
    return "goal"


def pick(n, history, seed=None):
    """n titles for the next videos: weighted by kind, not one made in the last few videos."""
    rows = load_titles()
    rnd = random.Random(seed or datetime.now(timezone.utc).isoformat())
    made = [h.get("title_base") or h.get("title") for h in history if h.get("kind") == "whitescreen"]
    recent = set(made[-10:])
    picks = []
    pool = list(rows)
    while pool and len(picks) < n:
        weights = [r["weight"] * (0.15 if r["title"] in recent else 1.0) for r in pool]
        r = rnd.choices(pool, weights=weights)[0]
        pool.remove(r)
        picks.append({"title": r["title"], "kind": r.get("kind") or kind_of(r["title"]),
                      "done_before": made.count(r["title"])})
    return picks


# ------------------------------------------------------------------ the script
PROMPT = """You write short videos for the YouTube channel "{channel}" ({subs}). Each video is 35-45
seconds: one voice talking straight to the viewer over a plain white screen while the words appear.
The only goal of every video: make people LIKE the video and COMMENT (a specific word or answer).

TODAY IS {today}. Any time you mention must make sense from today: "tomorrow", "in 24 hours",
"in 2 days", "this weekend", "{next_month}" or "{month_after}" - never a month that is already past or
oddly far away (in October, "I'll bring it back in November", not "in July"). Never say a year.

FOLLOW THE CHANNEL'S OWN STYLE (these are its real videos - same format, wording and rhythm):
{examples}

NOW WRITE THIS VIDEO:
Title: {title}
{extra}

Rules:
- {min_words}-{max_words} spoken words in total (count them; that is 38-43 seconds of voice). 10-15 short lines, one or two short
  sentences per line, spoken like a real person talks: always contract (I'm, don't, let's, you're,
  it's; never "let us" or "do not"), "..." for pauses. First line = the hook, said
  in the first two seconds (no "hey guys", no intro).
- Ask for the like AND one specific comment ("comment "I WAS HERE"") at least twice, the last line
  being the strongest call to action. Give a reason to do it NOW (it's disappearing, a goal, a record,
  being early, a future-self message...). Goals are believable numbers.
- Simple words a 12-year-old gets. No hashtags, no emojis, no "smash that like button".
- Be honest: never promise money, prizes or gifts, never pretend to be another creator, never claim
  YouTube itself will do something. Playful mystery is fine ("I'll do something random").
- If this title was made before, write a clearly different version: a different goal number, a
  different comment word and a different twist.

Return ONLY JSON:
{{"title": "the title (keep it as given unless a small variation is clearly better)",
 "lines": ["line 1", "line 2", "..."],
 "comment_word": "the exact thing to comment, e.g. I WAS HERE",
 "description": "3-4 short paragraphs like the examples: restate the hook, the goal and the call to like and comment (no keywords here)",
 "tags": ["25-30 search tags like the examples' keywords"],
 "pinned_comment": "a short pinned comment from the channel that invites replies",
 "thumbnail": {{
   "phrase": "1-3 BIG words for the thumbnail, the most important words of the title, e.g. DELETING SOON / 0 LIKES / FACE REVEAL (empty for error-style titles)",
   "small": "optional 2-5 small words, e.g. 'This video is private.' for error titles, else empty",
   "emotion": "the character's emotion, one of: {emotions}",
   "icon": "one icon that fits, one of: {icons}",
   "ui": "a YouTube-interface mock that fits, one of: {uis}"}},
 "cues": [{{"word": "a word in the script", "sfx": "one of: {sfx}", "icon": "one of the icons or empty"}}]
}}
"cues": 3-6 key moments (e.g. the word "like" -> sfx pop + icon like; "comment" -> bubble + comment;
"deleted" -> glitch + trash; "private" -> click + lock; a deadline -> ding + hourglass). The word
must appear in the lines exactly."""

# the character's emotions = the pictures in assets/whitescreen/characters (new poses join automatically)
EMOTIONS = sorted(p.stem for p in (config.ASSETS_DIR / "whitescreen" / "characters").glob("*.webp")) or ["shocked"]
ICONS = ["like", "dislike", "comment", "bell", "subscribe", "lock", "trash", "hourglass", "pin", "heart",
         "eye", "question", "warning", "fire", "crown", "sad_face", "dead_face", "glitch_face", "cracked_face",
         "crying_face", "angry_face", "happy_face", "dots_face", "none"]
UIS = ["comments_zero", "likes_zero", "likes_and_comments_zero", "pinned_comment", "delete_video",
       "delete_channel", "private_player", "video_unavailable", "view_count", "none"]
SFX = ["pop", "click", "bubble", "ding", "glitch", "whoosh", "coin", "tap", "sparkle", "thud", "none"]


def _today():
    now = datetime.now(timezone.utc)
    nm = (now.replace(day=1) + timedelta(days=32)).strftime("%B")
    ma = (now.replace(day=1) + timedelta(days=63)).strftime("%B")
    return now.strftime("%A, %B %-d"), nm, ma


def words(lines):
    return sum(len(re.findall(r"[\w’']+", l)) for l in lines)


def write(title, instructions="", history=(), done_before=0, min_words=125, max_words=145):
    """The script for one video (dict, see PROMPT). instructions: the viewer's own topic/notes."""
    today, nm, ma = _today()
    extra = ""
    if not title:
        extra += ("No title given: choose one yourself, in the style of the channel's titles (short, curious, "
                  "often a [Bracketed Video] or 'This Video Has 0 ...' format), that fits the instructions.\n")
    if instructions:
        extra += f"The channel owner's instructions for this video: {instructions}\n"
    if done_before:
        old = [h for h in history if h.get("kind") == "whitescreen" and (h.get("title_base") or h.get("title")) == title]
        if old:
            extra += ("This title was made before. Earlier version's first lines: "
                      + " / ".join(old[-1].get("hook", [])[:3]) + f" (comment word: {old[-1].get('comment_word', '')}). "
                      "Write a clearly different version.\n")
    prompt = PROMPT.format(channel=config.CHANNEL_NAME, subs="a big channel with a loyal audience",
                           today=today, next_month=nm, month_after=ma,
                           examples=EXAMPLES.read_text()[:9000], title=title or "(choose it)", extra=extra,
                           min_words=min_words, max_words=max_words,
                           emotions=", ".join(EMOTIONS), icons=", ".join(ICONS), uis=", ".join(UIS),
                           sfx=", ".join(SFX))
    best, feedback = None, ""
    for attempt in range(3):
        text, _ = ai.ask(prompt + feedback, json_mode=True, temperature=0.9)
        data = ai.parse_json(text)
        lines = [re.sub(r"\s+", " ", str(l)).strip() for l in data.get("lines", []) if str(l).strip()]
        data["lines"] = lines
        n = words(lines)
        problems = []
        if n < min_words:
            problems.append(f"only {n} words, write {min_words}-{max_words}")
        if n > max_words + 12:
            problems.append(f"{n} words is too long, write {min_words}-{max_words}")
        if not any("like" in l.lower() for l in lines) or not any("comment" in l.lower() for l in lines):
            problems.append("ask for the like and the comment")
        if best is None or abs(n - (min_words + max_words) / 2) < abs(words(best["lines"]) - (min_words + max_words) / 2):
            best = data
        if not problems:
            break
        print(f"   script check: {'; '.join(problems)} - rewriting")
        feedback = "\n\nYOUR LAST ANSWER HAD PROBLEMS, FIX THEM: " + "; ".join(problems) + "\nReturn the complete JSON again."
    data = best
    data["title"] = (data.get("title") or title or "SECRET VIDEO").strip()[:100]
    data["title_base"] = title or data["title"]
    data["kind"] = "whitescreen"
    data["format"] = kind_of(data["title_base"])
    th = data.get("thumbnail") or {}
    th["emotion"] = th.get("emotion") if th.get("emotion") in EMOTIONS else "shocked"
    th["icon"] = th.get("icon") if th.get("icon") in ICONS else "none"
    th["ui"] = th.get("ui") if th.get("ui") in UIS else "none"
    data["thumbnail"] = th
    data["cues"] = [c for c in data.get("cues", []) if isinstance(c, dict) and c.get("word")][:7]
    data["tags"] = [t for t in data.get("tags", []) if isinstance(t, str) and t.strip()][:30]
    data["text"] = " ".join(data["lines"])
    return data
