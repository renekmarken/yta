"""After each discovery run: pick products that launched today / this week and start videos for them
right away (the discover workflow passes the URLs to "Make a batch of videos").

Limits (repository variables): AUTO_VIDEOS_PER_DAY (default 3, 0 = off) and AUTO_MIN_HOTNESS (default 6).
Each product is started once; data/auto_videos.json remembers what was started.

  python tools/auto_launch.py          -> prints the chosen URLs, writes urls=... to $GITHUB_OUTPUT
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import config                                       # noqa: E402
from studio.discover import is_fresh_launch, load_queue, priority  # noqa: E402
from studio.reviewed import Ledger                               # noqa: E402

STATE = config.DATA_DIR / "auto_videos.json"


def main():
    per_day = int(os.environ.get("AUTO_VIDEOS_PER_DAY") or 3)
    min_hot = float(os.environ.get("AUTO_MIN_HOTNESS") or 6)
    per_run = int(os.environ.get("AUTO_VIDEOS_PER_RUN") or 2)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    today = date.today().isoformat()
    if state.get("date") != today:
        state["date"], state["count"] = today, 0
    started = set(state.get("started", []))
    room = min(per_run, per_day - state["count"])
    chosen = []
    if room > 0:
        done = Ledger()
        cands = [(k, it) for k, it in load_queue()["items"].items()
                 if is_fresh_launch(it) and float(it.get("hotness", 0)) >= min_hot and k not in started
                 and not done.has(it.get("url", ""), it.get("name", ""))]
        cands.sort(key=lambda kv: priority(kv[1]), reverse=True)
        chosen = cands[:room]
    for k, it in chosen:
        print(f"🚀 starting a video now: {it['name']} ({it.get('launch')}, hot {it.get('hotness')}) {it['url']}")
    if not chosen:
        print(f"No new launch to make right now ({state['count']}/{per_day} automatic videos today).")
    state["count"] += len(chosen)
    state["started"] = (list(started) + [k for k, _ in chosen])[-300:]
    STATE.write_text(json.dumps(state, indent=1))
    urls = " ".join(it["url"] for _, it in chosen)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"urls={urls}\n")


if __name__ == "__main__":
    main()
