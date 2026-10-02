"""Draw fresh thumbnails for videos already in the library (the video itself is not touched).

Visits the product's website again (new screenshots and logo), then makes 3 new thumbnail options
with the current design and replaces the old ones in the encrypted library. Uses the video's saved
script when the library has it (videos added from now on), otherwise its title, verdict and score.

  python tools/remake_thumbs.py "Moshly, Betterment"      (brand, site or title words; "all" = every video)
"""
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import library                                                    # noqa: E402
from studio.categories import BY_ID                               # noqa: E402
from studio.crawl import crawl                                    # noqa: E402
from studio.themes import normalize, pick_theme                   # noqa: E402
from studio.thumbnail import make_thumbnails                      # noqa: E402
from studio.visuals import brand_color, load_logo                 # noqa: E402

STYLE_WORDS = [("scam", "scam"), ("catch", "catch"), ("legit", "legit"), ("hype", "legit"), ("expect", "expect"),
               ("fees", "fees"), ("before", "before"), ("don't", "dont"), ("truth", "truth"), ("honest", "honest"),
               ("any good", "good"), ("actually good", "good"), ("actually worth", "actually"), ("worth", "worth")]


def title_style(title):
    t = (title or "").lower()
    return next((style for word, style in STYLE_WORDS if word in t), "worth")


def main(names):
    lib = library.Library()
    wanted = [n.strip().lower() for n in names.split(",") if n.strip()]
    done = 0
    for e in lib.videos:
        text = f"{e.get('brand', '')} {e.get('site', '')} {e.get('title', '')}".lower()
        files = e.get("files") or {}
        if not ("all" in wanted or any(w in text for w in wanted)) or e.get("missing") or "video" not in files:
            continue
        kit = lib.fetch(files["kit"]).decode("utf-8", "replace") if "kit" in files else ""
        m = re.search(r"^Source: (\S+)", kit, re.M)
        if not m:
            print(f"  ! {e['title']}: no website address saved, skipped")
            continue
        url = m.group(1)
        data = json.loads(lib.fetch(files["script"])) if "script" in files else {}
        data = {**data, "brand": data.get("brand") or e.get("brand") or e.get("site"),
                "verdict": data.get("verdict") or e.get("verdict"), "score": data.get("score") or e.get("score"),
                "title_style": data.get("title_style") or title_style(e.get("title")),
                "segments": data.get("segments") or []}
        out = Path(tempfile.mkdtemp()) / e["id"]
        try:
            if "site" in files:                          # screenshots saved with the video: no visit needed
                import io
                import zipfile
                out.mkdir(parents=True)
                zipfile.ZipFile(io.BytesIO(lib.fetch(files["site"]))).extractall(out)
                info = json.loads((out / "site.json").read_text())
                print(f"  {e['title']}: using the saved screenshots")
            else:
                print(f"  {e['title']}: visiting {url}")
                cat = BY_ID.get(e.get("category"))
                info = crawl(url, out, cat["subpage_words"] if cat else None)
        except Exception as ex:                          # e.g. the site shows a bot check right now
            print(f"  ! {e['title']}: skipped ({type(ex).__name__}: {str(ex)[:120]})")
            continue
        logo = load_logo(out / info["logo"]) if info.get("logo") else None
        theme = normalize(pick_theme(f"{info['domain']}-{datetime.now(timezone.utc).isoformat()}",
                                     brand_color(logo, out / info["screenshots"][0]["file"]), [],
                                     (out / "mobile.png").exists(), e.get("category")))
        if e.get("kind") == "risk" and data.get("story"):
            from studio.thumbnail import make_risk_thumbnails
            paths = make_risk_thumbnails(data, info, out, theme)
        else:
            paths = make_thumbnails(data, info, out, theme)
        files["thumbnails"] = [lib.store(e["id"], "thumbnail", p.read_bytes(),
                                         f"911video - {e.get('site', 'video')} - thumbnail {i}.jpg", f"-{i}")
                               for i, p in enumerate(paths, 1)]
        files["thumbnail"] = files["thumbnails"][0]
        print(f"    new thumbnails: {', '.join(theme['thumbs'])} (logo: {'yes' if logo else 'name only'})")
        done += 1
    lib.save()
    print(f"remade thumbnails for {done} video(s)")
    if not done:
        sys.exit("no matching video with files found")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
