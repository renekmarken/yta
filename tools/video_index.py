"""Add released videos to the video library page's data (docs/videos/videos.json), newest first.

  python tools/video_index.py <entries.json>
"""
import json
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "docs" / "videos" / "videos.json"
new = json.loads(Path(sys.argv[1]).read_text())
INDEX.parent.mkdir(parents=True, exist_ok=True)
old = json.loads(INDEX.read_text()) if INDEX.exists() else []
ids = {e["id"] for e in new}
INDEX.write_text(json.dumps(new + [e for e in old if e["id"] not in ids], ensure_ascii=False, indent=1))
print(f"video library: {len(new)} added, {len(new) + len(old)} total")
