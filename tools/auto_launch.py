"""After each (hourly) discovery run: decide how many review videos to start right now, so the channel
gets up to UPLOADS_PER_DAY videos a day, each uploaded to YouTube as soon as it's done.

Repository variables: UPLOADS_PER_DAY (default 50, the volume in the YouTube API quota application;
0 = off) and AUTO_VIDEOS_PER_RUN (default 6: started per hourly run; about half the websites block
visitors and give no video, and those don't count). GitHub often skips scheduled runs for hours, so a
run that comes late starts more to catch up (6 per hour since the last start, at most 16). Today's
uploads are counted from data/history.json, plus the videos started in the last 90 minutes that
aren't booked yet. data/auto_videos.json remembers those starts.

  python tools/auto_launch.py          -> prints the decision, writes count=N to $GITHUB_OUTPUT
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import config                                       # noqa: E402

STATE = config.DATA_DIR / "auto_videos.json"
IN_FLIGHT = timedelta(minutes=90)               # a batch of 16 (4 at a time) takes about an hour
MAX_RUN = 16


def main():
    per_day = int(os.environ.get("UPLOADS_PER_DAY") or 50)
    per_run = int(os.environ.get("AUTO_VIDEOS_PER_RUN") or 6)
    now = datetime.now(timezone.utc)
    today = date.today().isoformat()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    history = json.loads(config.HISTORY_FILE.read_text()) if config.HISTORY_FILE.exists() else []

    uploaded = sum(1 for h in history if h.get("date") == today and h.get("youtube"))
    starts = [s for s in state.get("starts", []) if now - datetime.fromisoformat(s["at"]) < IN_FLIGHT]
    in_flight = sum(s["count"] for s in starts)
    last = state.get("last")
    hours = (now - datetime.fromisoformat(last)).total_seconds() / 3600 if last else 3
    catch_up = min(MAX_RUN, max(per_run, round(per_run * hours)))
    count = max(0, min(catch_up, per_day - uploaded - in_flight))
    print(f"{uploaded}/{per_day} uploaded today, {in_flight} still being made -> starting {count} now")

    if count:
        starts.append({"at": now.isoformat(timespec="seconds"), "count": count})
        last = now.isoformat(timespec="seconds")
    STATE.write_text(json.dumps({"starts": starts, "last": last}, indent=1))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"count={count}\n")


if __name__ == "__main__":
    main()
