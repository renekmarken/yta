"""Check that the YouTube secrets work: prints the channel they upload to. Uploads nothing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import config  # noqa: E402

missing = [n for n in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not getattr(config, n)]
if missing:
    sys.exit(f"Missing secrets: {', '.join(missing)}")

from studio.upload import _client  # noqa: E402

items = _client().channels().list(part="snippet", mine=True).execute().get("items", [])
if not items:
    sys.exit("Signed in, but this Google account has no YouTube channel.")
print(f"OK: videos will upload to \"{items[0]['snippet']['title']}\" (https://youtube.com/channel/{items[0]['id']})")
print(f"UPLOAD_MODE is '{config.UPLOAD_MODE}'" + ("" if config.UPLOAD_MODE == "api"
      else " - set the repository variable UPLOAD_MODE to 'api' to turn on automatic uploads"))
