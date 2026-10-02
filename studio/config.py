"""Settings, read from environment variables (GitHub secrets/variables) or a local .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.split(" #", 1)[0]
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


# --- AI ---
GEMINI_API_KEY = env("GEMINI_API_KEY")
# Tried in order; if none exist any more, the newest available Flash model is picked automatically.
GEMINI_MODELS = [m.strip() for m in env(
    "GEMINI_MODELS", "gemini-flash-latest,gemini-2.5-flash,gemini-flash-lite-latest,gemini-2.5-flash-lite"
).split(",") if m.strip()]
USE_WEB_RESEARCH = env("USE_WEB_RESEARCH", "1") == "1"   # Gemini + Google Search grounding
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")

# --- Voice ---
TTS_VOICE = env("TTS_VOICE", "en-US-AndrewMultilingualNeural")
TTS_RATE = env("TTS_RATE", "+5%")
PIPER_VOICE = env("PIPER_VOICE", "en_US-ryan-high")   # offline backup voice

# --- Production ---
VIDEOS_PER_RUN = int(env("VIDEOS_PER_RUN", "1"))
CHANNEL_NAME = env("CHANNEL_NAME", "Worth Using It?")
VIDEO_W, VIDEO_H, FPS = 1920, 1080, 30
FAST_RENDER = env("FAST_RENDER", "0") == "1"           # lower quality, for quick tests

# --- Discovery ---
DISCOVERY_MAX_NEW = int(env("DISCOVERY_MAX_NEW", "25"))  # new products added per discovery run
QUEUE_MIN_EVERGREEN = int(env("QUEUE_MIN_EVERGREEN", "3"))  # evergreen picks kept per category

# --- YouTube upload ---
UPLOAD_MODE = env("UPLOAD_MODE", "manual")             # manual | api (api only after the API audit)
YT_PRIVACY = env("YT_PRIVACY", "private")                # private | unlisted | public
# Upload as private and let YouTube publish it automatically this many hours later (a review window).
YT_PUBLISH_DELAY_HOURS = float(env("YT_PUBLISH_DELAY_HOURS", "0"))
YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")
YT_CATEGORY_ID = env("YT_CATEGORY_ID", "28")

# --- Phone notifications (free, no account): install the ntfy app and subscribe to your topic ---
NTFY_TOPIC = env("NTFY_TOPIC")

SITES_FILE = ROOT / "sites.txt"
DATA_DIR = ROOT / "data"
DONE_FILE = DATA_DIR / "done.txt"
FAILED_FILE = DATA_DIR / "failed.txt"
QUEUE_FILE = DATA_DIR / "queue.json"
QUEUE_MD = DATA_DIR / "QUEUE.md"
HISTORY_FILE = DATA_DIR / "history.json"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
CACHE_DIR = ROOT / ".cache"
