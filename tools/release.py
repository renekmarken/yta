"""Gather finished videos into one folder + release notes, for an easy-download GitHub Release.

  python tools/release.py <folder with review folders> <out dir>

Every review folder with a metadata.json contributes its .mp4 (named after the title) plus
"<site> - thumbnail.jpg", "<site> - captions.srt" and "<site> - UPLOAD_KIT.md".
Prints the number of videos found (0 = nothing to release).
"""
import json
import shutil
import sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
rows = []
for meta_path in sorted(src.rglob("metadata.json")):
    folder = meta_path.parent
    meta = json.loads(meta_path.read_text())
    videos = sorted(folder.glob("*.mp4"))
    if not videos:
        continue
    site = folder.name
    shutil.copy2(videos[0], out / videos[0].name)
    for extra in ("thumbnail.jpg", "captions.srt", "UPLOAD_KIT.md"):
        if (folder / extra).exists():
            shutil.copy2(folder / extra, out / f"{site} - {extra}")
    rows.append(f"- **{meta.get('title', site)}** — verdict: {meta.get('verdict', '?')} "
                f"({meta.get('score', '?')}/10)")
notes = ["Tap a file below to download it.", "",
         "**Videos:**", *rows, "",
         "For each video there is also a thumbnail, a captions file and an UPLOAD_KIT "
         "(title, description, tags, things to double-check)."]
(out.parent / "release_notes.md").write_text("\n".join(notes))
print(len(rows))
