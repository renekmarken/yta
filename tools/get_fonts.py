"""Download extra open-licence headline fonts (Google Fonts, OFL) for more thumbnail/video variety.
Runs automatically in the cloud workflow; run it once locally too if you like."""
from pathlib import Path

import requests

DEST = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONTS = {
    "Anton-Regular.ttf": "ofl/anton/Anton-Regular.ttf",
    "BebasNeue-Regular.ttf": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "ArchivoBlack-Regular.ttf": "ofl/archivoblack/ArchivoBlack-Regular.ttf",
}

for name, path in FONTS.items():
    out = DEST / name
    if out.exists():
        continue
    try:
        r = requests.get(f"https://github.com/google/fonts/raw/main/{path}", timeout=60)
        r.raise_for_status()
        out.write_bytes(r.content)
        print(f"downloaded {name}")
    except Exception as e:
        print(f"skipped {name}: {e}")
