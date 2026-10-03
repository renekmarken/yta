"""White Screen videos: one 35-45 s video from a title (or the owner's own topic/instructions).

  1 script      ws_script.write(): Gemini, in the channel's own style, today's date in mind
  2 voice       ws_video.voice(): one take, the time of every word; too short or too long -> one rewrite
  3 video       ws_video.render(): white 16:9, the words popping in one by one, a few icons and sounds
  4 thumbnails  ws_thumb.make(): 3 options in the channel's thumbnail styles
  5 kit         title, description, tags, pinned comment, captions.srt -> the library like every video
"""
import json
import re
from datetime import date

from . import config
from . import ws_script as S


def _filename(title):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title or "").strip().rstrip(".")
    return "911video - " + (re.sub(r"\s+", " ", name)[:90].strip() or "video") + ".mp4"


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:50] or "video"


def produce(item, history, out=None):
    """Make the video for a planned item {name/title, instructions?}. Returns (folder, data, record)."""
    from . import ws_thumb as T
    from . import ws_video as V
    title = (item.get("title") or "").strip()
    instructions = (item.get("instructions") or "").strip()
    out = out or (config.OUTPUT_DIR / f"whitescreen-{_slug(title or instructions)}")
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("*.mp4")) + list(out.glob("*.jpg")):
        old.unlink()

    print(f"1/5 script: {title or '(own topic) ' + instructions[:80]}")
    min_w, max_w = 125, 145
    for attempt in range(3):
        data = S.write(title, instructions, history, item.get("done_before", 0), min_w, max_w)
        print(f"   {data['title']} — {S.words(data['lines'])} words, comment: {data.get('comment_word')}")
        print("2/5 voice")
        mp3, words = V.voice(data["text"], out)
        speech = V.duration(mp3)
        if 31.5 <= speech <= 47.0 or attempt == 2:
            break
        # too far from 35-45 s to fix by speed alone: write it again, shorter or longer
        delta = int(round((40 - speech) * 3.3))
        min_w, max_w = max(80, min_w + delta), max(95, max_w + delta)
        print(f"   voice is {speech:.1f}s — rewriting for {min_w}-{max_w} words")
    mp3, words, total = V.fit(mp3, words, out)
    dw = V.display_words(words)
    cues = V.plan_cues(dw, data.get("cues", []))
    V.srt(dw, out / "captions.srt")
    print(f"3/5 video ({total:.1f}s, {len(dw)} words, {sum(1 for c in cues if c.get('icon'))} icons, "
          f"{sum(1 for c in cues if c.get('sfx'))} sounds)")
    video = V.render(dw, cues, mp3, total, out / _filename(data["title"]), out)
    print("4/5 thumbnails")
    T.make(data, out)
    print(f"   styles: {', '.join(data.get('thumbs', []))}")

    print("5/5 upload kit")
    for f in ("voice.mp3", "voice_fit.mp3", "sfx.wav"):
        (out / f).unlink(missing_ok=True)
    data["seconds"] = round(total, 1)
    data["cues_used"] = [{"t": round(c["t"], 2), "word": dw[c["i"]][2], "sfx": c.get("sfx"), "icon": c.get("icon")} for c in cues]
    (out / "script.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tags = data.get("tags", [])
    meta = {"title": data["title"], "video_file": video.name, "description": data.get("description", ""),
            "tags": _cap_tags(tags), "verdict": "", "score": "", "category": "", "kind": "whitescreen",
            "pinned_comment": data.get("pinned_comment", ""), "story": None,
            "check_before_publishing": ["Watch it once: the words should match the voice",
                                        "Any date or deadline in it still makes sense today"]}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    script = "\n\n".join(data["lines"])
    (out / "UPLOAD_KIT.md").write_text(f"""# {data['title']} — White Screen ({date.today()})

{total:.0f} seconds · comment word: {data.get('comment_word', '')} · thumbnails: {', '.join(data.get('thumbs', []))}

## Title
{data['title']}

## Description
{meta['description']}

## Tags
{', '.join(meta['tags'])}

## Pinned comment
{meta['pinned_comment']}

## Files
- {video.name} — upload this
- 911video-thumbnail-1/2/3.jpg — three thumbnail options
- captions.srt — Subtitles → Upload file → With timing

## Script
{script}
""")
    record = {"date": date.today().isoformat(), "url": item.get("url") or f"whitescreen:{_slug(data['title'])}",
              "brand": "", "kind": "whitescreen", "title": data["title"], "title_base": data.get("title_base"),
              "format": data.get("format"), "comment_word": data.get("comment_word"), "hook": data["lines"][:3],
              "theme": {"thumbs": data.get("thumbs", [])}, "youtube": None}
    return out, data, record


def _cap_tags(tags):
    out, n = [], 0
    for t in dict.fromkeys(t.strip() for t in tags if t and t.strip()):
        cost = len(t) + (2 if " " in t else 0) + 1
        if n + cost > 480:
            break
        out.append(t)
        n += cost
    return out
