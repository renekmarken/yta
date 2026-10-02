"""Gather finished videos for a GitHub Release and the video library page.

  python tools/release.py <folder with review folders> <out dir> <release download base URL> <tag>

For every review folder with a metadata.json it copies, with download-safe names:
  <site>.mp4, <site>-thumbnail.jpg, <site>-captions.srt, <site>-upload-kit.md
and writes <out dir>/../release_notes.md and <out dir>/../entries.json (for tools/video_index.py).
Prints the number of videos found (0 = nothing to release).
"""
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

src, out, base, tag = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].rstrip("/"), sys.argv[4]
out.mkdir(parents=True, exist_ok=True)
rows, entries = [], []
for meta_path in sorted(src.rglob("metadata.json")):
    folder = meta_path.parent
    meta = json.loads(meta_path.read_text())
    videos = sorted(folder.glob("*.mp4"))
    if not videos:
        continue
    site = re.sub(r"[^a-z0-9-]+", "-", folder.name.lower()).strip("-") or "video"
    files = {"video": (videos[0], f"{site}.mp4"), "thumbnail": (folder / "thumbnail.jpg", f"{site}-thumbnail.jpg"),
             "captions": (folder / "captions.srt", f"{site}-captions.srt"),
             "kit": (folder / "UPLOAD_KIT.md", f"{site}-upload-kit.md")}
    urls = {}
    for kind, (path, name) in files.items():
        if path.exists():
            shutil.copy2(path, out / name)
            urls[kind] = f"{base}/{tag}/{name}"
    script = {}
    if (folder / "script.json").exists():
        try:
            script = json.loads((folder / "script.json").read_text())
        except json.JSONDecodeError:
            pass
    entries.append({
        "id": f"{tag}-{site}", "date": date.today().isoformat(), "site": folder.name,
        "brand": script.get("brand", ""), "title": meta.get("title", ""), "description": meta.get("description", ""),
        "tags": meta.get("tags", []), "pinned_comment": meta.get("pinned_comment", ""),
        "verdict": meta.get("verdict", ""), "score": meta.get("score", ""), "category": meta.get("category", ""),
        "checks": meta.get("check_before_publishing", []), "files": urls,
    })
    rows.append(f"- **{meta.get('title', site)}** — verdict: {meta.get('verdict', '?')} ({meta.get('score', '?')}/10)")
notes = ["Easiest: open the video library at https://renekmarken.github.io/yta/videos/ "
         "(downloads + copy buttons for title, description and tags).", "",
         "**Videos:**", *rows]
(out.parent / "release_notes.md").write_text("\n".join(notes))
(out.parent / "entries.json").write_text(json.dumps(entries, ensure_ascii=False, indent=1))
print(len(entries))
