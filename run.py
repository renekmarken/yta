"""Site Review Studio — trending products -> research -> script -> voice -> video -> thumbnail -> YouTube kit.

  python discover.py                  # find hot/new products, update data/queue.json + data/QUEUE.md
  python run.py                       # make the next VIDEOS_PER_RUN videos from the queue
  python run.py --url https://x.com   # review one specific site now
  python run.py --rerender output/x-com   # rebuild after editing script.json or adding your own voice
  python run.py --restyle output/x-com    # same content, new random design
  python run.py --upload output/x-com     # upload one finished video (UPLOAD_MODE=api)
"""
import argparse
import json
import re
import shutil
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from studio import config
from studio.categories import BY_ID
from studio.discover import discover, key_for, load_queue, pick_next, remove_from_queue
from studio.notify import notify
from studio.reviewed import Ledger, record as record_review, site_id
# The video libraries (Pillow, numpy, Playwright, ...) are imported inside the functions that make
# videos, so planning and booking batches only need requests + beautifulsoup4.


def slug(url):
    u = urlparse(url)
    s = (u.netloc.replace("www.", "") + u.path).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]


def load_history():
    if config.HISTORY_FILE.exists():
        return json.loads(config.HISTORY_FILE.read_text())
    return []


def save_history(h):
    config.DATA_DIR.mkdir(exist_ok=True)
    config.HISTORY_FILE.write_text(json.dumps(h[-300:], indent=1, ensure_ascii=False))


def _append(path, line):
    config.DATA_DIR.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(line + "\n")


def _tags(tags):
    """YouTube allows ~500 characters of tags in total."""
    out, n = [], 0
    for t in dict.fromkeys(t.strip() for t in tags if t and t.strip()):
        cost = len(t) + (2 if " " in t else 0) + 1
        if n + cost > 480:
            break
        out.append(t)
        n += cost
    return out


def video_filename(title):
    """911video - <YouTube title>.mp4 (Studio uses the file name as the starting title)."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title or "").strip().rstrip(".")
    return "911video - " + (re.sub(r"\s+", " ", name)[:90].strip() or "video") + ".mp4"


def full_description(data, info):
    from studio.video import chapters
    brand_tag = re.sub(r"[^A-Za-z0-9]", "", data.get("brand", ""))
    cat_tag = {"credit-cards": "CreditCards", "insurance": "Insurance", "banking-apps": "Banking",
               "investing": "Investing", "real-estate": "RealEstate", "legal": "LegalTech",
               "saas": "SaaS", "ai-tools": "AITools", "business-tools": "SmallBusiness",
               "marketing": "Marketing", "vpn-security": "Cybersecurity", "hosting": "WebHosting",
               "freelancing": "Freelancing"}.get(data.get("category"), "Review")
    parts = [data["youtube_description"].strip()]
    chap = chapters(data["segments"])
    if chap:
        parts.append("Chapters:\n" + chap)
    parts.append(f"Website reviewed: {info['url']}")
    if data.get("sources"):
        parts.append("Sources:\n" + "\n".join(f"- {s['title'] or s['url']}: {s['url']}"
                                             for s in data["sources"][:6]))
    parts.append("This review is based on what the website and public sources show on the day of "
                 "recording. Always check current terms, fees and licensing yourself. "
                 "Not financial, legal or investment advice. Not sponsored.")
    parts.append(" ".join(f"#{t}" for t in [brand_tag, f"{brand_tag}Review", cat_tag] if t))
    return "\n\n".join(parts)[:4900]


def write_kit(out, data, info, description, theme, video_file="video.mp4"):
    meta = {"title": data["youtube_title"], "video_file": video_file, "description": description,
            "tags": _tags(data["tags"]),
            "verdict": data.get("verdict"), "score": data.get("score"),
            "category": data.get("category"), "pinned_comment": data.get("pinned_comment", ""),
            "check_before_publishing": data.get("check_before_publishing", [])}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    checks = "\n".join(f"- [ ] {c}" for c in meta["check_before_publishing"]) or "- [ ] (none flagged)"
    script = "\n\n".join(f"**[{s['caption']}]** {s['text']}" for s in data["segments"])
    research = data.get("research_notes") or "(no web research this time)"
    (out / "UPLOAD_KIT.md").write_text(f"""# {data.get('brand')} — upload kit ({date.today()})

Verdict: **{data.get('verdict')}** ({data.get('score')}/10) · {BY_ID.get(data.get('category'), {}).get('name', '')}
Source: {info['url']} · Format: {data.get('format')} · Look: {theme['layout']}/{theme['mode']}/{theme['thumb']} · Music: {theme.get('music')}

## Before you publish (2 minutes)
- [ ] Watch the video once
- [ ] Add one line of your own opinion (description or pinned comment)
{checks}

## Title
{meta['title']}

## Description
{description}

## Tags (paste into the Tags box)
{', '.join(meta['tags'])}

## Pinned comment
{meta['pinned_comment']}

## Files
- {video_file} — upload this (named after the title, so Studio pre-fills it)
- 911video-thumbnail-1/2/3.jpg — three thumbnail options (pick one; 1 matches the title)
- captions.srt — Subtitles → Upload file → With timing
- "Altered or synthetic content" question: **No** (the narrator is an obvious AI voice, not a real person)

## Research notes used
{research}

## Script
{script}
""")


def produce(item, history, out=None, mode="new"):
    """mode: new | rerender (same look) | restyle (new look)."""
    from studio.crawl import crawl
    from studio.script import write_script
    from studio.themes import normalize, pick_theme
    from studio.thumbnail import make_thumbnails, choose_thumbnail
    from studio.tts import fit_length, narrate, write_srt
    from studio.video import render
    from studio.visuals import brand_color, load_logo
    if mode == "new":
        url = item["url"]
        out = config.OUTPUT_DIR / slug(url)
        if out.exists():
            shutil.rmtree(out)
        cat = BY_ID.get(item.get("category"))
        print(f"1/6 crawling {url}")
        info = crawl(url, out, cat["subpage_words"] if cat else None)
        print(f"2/6 research + script ({len(info['screenshots'])} screenshots, logo={bool(info.get('logo'))})")
        data = write_script(info, item, history)
    else:
        info = json.loads((out / "site.json").read_text())
        data = json.loads((out / "script.json").read_text())

    data["category_name"] = BY_ID.get(data.get("category"), {}).get("name", "")
    if mode == "rerender" and data.get("theme"):
        theme = normalize(data["theme"])
    else:
        logo = load_logo(out / info["logo"]) if info.get("logo") else None
        bc = brand_color(logo, out / info["screenshots"][0]["file"])
        seed = f"{info['domain']}-{datetime.now(timezone.utc).isoformat()}"
        theme = pick_theme(seed, bc, history, (out / "mobile.png").exists(), data.get("category"))
    data["theme"] = theme

    print("3/6 voice-over")
    narrate(data["segments"], out)
    if mode == "new":            # keep your own recordings (rerender) untouched
        from studio.video import OUTRO, PAD
        fit_length(data["segments"], OUTRO + PAD * len(data["segments"]))
    print(f"4/6 rendering video ({theme['layout']} layout, {theme['mode']} {theme['bg']}, {theme['head_font']})")
    shutil.rmtree(out / "render", ignore_errors=True)
    video = render(data, info, out, theme)
    make_thumbnails(data, info, out, theme)
    print(f"5/6 thumbnails ({', '.join(theme['thumbs'])})")
    srt = write_srt(data["segments"], out / "captions.srt")
    print("6/6 metadata")
    (out / "script.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    description = full_description(data, info)
    named = out / video_filename(data.get("youtube_title"))
    for old in out.glob("*.mp4"):                      # earlier renders of this review
        if old != video:
            old.unlink()
    video = video.rename(named)
    write_kit(out, data, info, description, theme, named.name)
    shutil.rmtree(out / "render", ignore_errors=True)

    youtube_url = None
    if config.UPLOAD_MODE == "api":
        from studio.upload import upload
        meta = json.loads((out / "metadata.json").read_text())
        try:                     # a failed upload must not throw away a finished video
            thumb = choose_thumbnail(out)
            print(f"   thumbnail: {thumb.name}")
            vid = upload(video, thumb, meta["title"], description, meta["tags"], srt)
            (out / "youtube_id.txt").write_text(vid)
            youtube_url = f"https://youtu.be/{vid}"
            print(f"   uploaded: {youtube_url}")
        except Exception as e:
            print(f"   ! YouTube upload failed, upload this one by hand: {str(e)[:300]}")

    opener = data["segments"][0]["text"].split(".")[0][:120]
    return out, data, {"date": date.today().isoformat(), "url": info["url"], "brand": data.get("brand"),
                       "category": data.get("category"), "title": data.get("youtube_title"),
                       "youtube": youtube_url,
                       "format": data.get("format"), "opener": opener, "title_style": data.get("title_style"),
                       "theme": {k: theme[k] for k in ("mode", "layout", "frame", "caption", "bg",
                                                       "head_font", "accent", "transitions", "intro",
                                                       "highlight", "thumb", "thumb_accent",
                                                       "cap_anim", "callout", "music", "sfx", "thumb_palette", "thumbs")
                                 if k in theme}}


def _label(data, item, youtube):
    return (data.get("youtube_title") or item["name"]) + (f" → {youtube}" if youtube
                                                          else " (not uploaded)" if config.UPLOAD_MODE == "api" else "")


def apply_result(res, history):
    """Book one finished (or failed) video into the queue, history and the never-again record."""
    item, key = res["item"], res["key"]
    if res["status"] == "done":
        history.append(res["record"])
        save_history(history)
        _append(config.DONE_FILE, item["url"])
        record_review(item["url"], item.get("name", ""), res.get("brand", ""), "done")
    else:
        _append(config.FAILED_FILE, item["url"])
        record_review(item["url"], item.get("name", ""), "", "failed")
    remove_from_queue(key)


def make_one(key, item, history):
    """Produce one video. Returns a result dict (also used by batch runs)."""
    print(f"\n=== {item['name']} ({item.get('category') or 'auto'}) — {item['url']}")
    try:
        out, data, record = produce(item, history)
        print(f"✓ done -> {out}")
        return {"status": "done", "key": key, "item": item, "record": record, "brand": data.get("brand", ""),
                "label": _label(data, item, record.get("youtube")), "folder": out.name}
    except Exception as e:
        traceback.print_exc()
        reason = "blocked/empty site" if type(e).__name__ == "BlockedSite" else type(e).__name__
        print(f"✗ {item['url']} skipped ({reason}); next time the queue moves on")
        return {"status": "failed", "key": key, "item": item, "reason": reason}


def plan(n, history):
    q, picks = pick_next(n, history)
    if len(q["items"]) < n * 2:
        print("Queue is running low — discovering new products first.")
        discover()
        q, picks = pick_next(n, history)
    done = Ledger()
    return [(k, it) for k, it in picks if not done.has(it["url"], it.get("name"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--rerender", type=Path)
    ap.add_argument("--restyle", type=Path)
    ap.add_argument("--upload", type=Path)
    ap.add_argument("-n", type=int, default=config.VIDEOS_PER_RUN)
    ap.add_argument("--force", action="store_true", help="review --url even if it was reviewed before")
    # batch mode (used by the "Make a batch of videos" workflow)
    ap.add_argument("--plan", type=int, help="pick this many products and write them to --plan-out")
    ap.add_argument("--plan-out", type=Path, default=Path("plan.json"))
    ap.add_argument("--plan-url", default="", help="also review this website (outside the queue)")
    ap.add_argument("--item", help="make exactly this planned item (JSON) and write result.json, no bookkeeping")
    ap.add_argument("--apply-results", type=Path, help="book all result.json files found in this folder")
    a = ap.parse_args()
    history = load_history()

    if a.upload:
        from studio.upload import upload
        from studio.thumbnail import choose_thumbnail
        meta = json.loads((a.upload / "metadata.json").read_text())
        thumb = choose_thumbnail(a.upload)
        print(f"thumbnail: {thumb.name if thumb else 'none'}")
        vid = upload(a.upload / meta.get("video_file", "video.mp4"), thumb, meta["title"],
                     meta["description"], meta["tags"], a.upload / "captions.srt")
        print(f"https://youtu.be/{vid}")
        return
    if a.rerender or a.restyle:
        produce(None, history, out=a.rerender or a.restyle, mode="rerender" if a.rerender else "restyle")
        return

    if a.plan is not None:
        picks = plan(a.plan, history) if a.plan > 0 else []
        q = load_queue()
        for custom in reversed(re.split(r"[\s,]+", a.plan_url.strip())):    # one or more websites
            if not custom:
                continue
            custom = custom if "://" in custom else "https://" + custom
            hit = next(((k, it) for k, it in q["items"].items() if site_id(it.get("url", "")) == site_id(custom)), None)
            item = (hit[0], {**hit[1]}) if hit else \
                (key_for(custom), {"name": urlparse(custom).netloc.removeprefix("www."), "url": custom,
                                   "category": None, "custom": True})       # typed in: made even if reviewed
            picks = [item] + [(k, it) for k, it in picks if k != item[0]]
        a.plan_out.write_text(json.dumps([{"n": i + 1, "key": k, **it} for i, (k, it) in enumerate(picks)]))
        print(f"Planned {len(picks)} video(s):")
        for i, (k, it) in enumerate(picks, 1):
            print(f"  {i}. {it['name']} ({it.get('category')}) — {it['url']}")
        return
    if a.item:
        it = json.loads(a.item)
        key = it.pop("key", None) or key_for(it["url"])
        it.pop("n", None)
        if not it.get("custom") and Ledger().has(it["url"], it.get("name")):   # a typed-in site is made anyway
            print(f"{it['name']} was already reviewed — skipping.")
            return
        res = make_one(key, it, history)
        folder = config.OUTPUT_DIR / res.get("folder", "failed-" + key.replace("/", "_"))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "result.json").write_text(json.dumps(res, ensure_ascii=False))
        # a blocked site is normal (it is recorded and skipped from now on) - don't turn the batch red
        sys.exit(0 if res["status"] == "done" or res.get("reason") == "blocked/empty site" else 1)
    if a.apply_results:
        results = [json.loads(p.read_text()) for p in sorted(a.apply_results.rglob("result.json"))]
        for res in results:
            apply_result(res, history)
        made = [r["label"] for r in results if r["status"] == "done"]
        failed = [r["item"]["name"] for r in results if r["status"] != "done"]
        print(f"Booked {len(made)} video(s), {len(failed)} failed.")
        if made:
            notify(f"Batch ready: {len(made)} video(s)" + (f", {len(failed)} failed" if failed else ""),
                   "\n".join(f"• {t}" for t in made))
        return

    if a.url:
        if Ledger().has(a.url) and not a.force:
            print(f"{a.url} was already reviewed — not making it again. (Add --force to override.)")
            return
        picks = [(key_for(a.url), {"name": urlparse(a.url).netloc, "url": a.url, "category": None})]
    else:
        picks = plan(a.n, history)
    if not picks:
        print("Nothing to review: queue is empty and discovery found nothing. Add URLs to sites.txt.")
        return

    made, failed = [], 0
    for key, item in picks:
        res = make_one(key, item, history)
        apply_result(res, history)
        if res["status"] == "done":
            made.append(res["label"])
        else:
            failed += 1
    if made:
        notify(f"{len(made)} review video(s) ready", "\n".join(f"• {t}" for t in made))
    sys.exit(1 if failed and not made else 0)


if __name__ == "__main__":
    main()
