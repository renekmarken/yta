"""Keep the video library's data (docs/videos/library.enc.json) up to date — encrypted.

The page is public on GitHub Pages, so its data is encrypted with the library password
(GitHub secret LIBRARY_PASSWORD): AES-256-GCM with a key from PBKDF2-SHA256 (600,000 rounds).
The browser decrypts it after you type the password; without it the file is unreadable.
The "Generate new videos" button's GitHub token (secret DISPATCH_TOKEN) travels inside the
encrypted data too, so only someone with the password can use it.

  python tools/video_index.py <entries.json>   # add newly released videos
  python tools/video_index.py                  # just re-encrypt (e.g. after changing the token)
"""
import base64
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DOCS = Path(__file__).resolve().parent.parent / "docs" / "videos"
ENC = DOCS / "library.enc.json"
PLAIN = DOCS / "videos.json"           # older, unencrypted format (migrated, then removed)
ITERATIONS = 600_000
b64 = lambda b: base64.b64encode(b).decode()


def _key(password, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def load(password):
    if ENC.exists():
        box = json.loads(ENC.read_text())
        salt = base64.b64decode(box["salt"])
        data = AESGCM(_key(password, salt)).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["data"]), None)
        return json.loads(data), salt
    videos = json.loads(PLAIN.read_text()) if PLAIN.exists() else []
    return {"videos": videos}, secrets.token_bytes(16)


def save(payload, password, salt):
    iv = secrets.token_bytes(12)
    data = AESGCM(_key(password, salt)).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode("utf-8"), None)
    DOCS.mkdir(parents=True, exist_ok=True)
    ENC.write_text(json.dumps({"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS,
                               "salt": b64(salt), "iv": b64(iv), "data": b64(data)}))
    if PLAIN.exists():
        PLAIN.unlink()


def main():
    password = os.environ.get("LIBRARY_PASSWORD", "")
    if not password:
        sys.exit("LIBRARY_PASSWORD is not set. Add it under Settings → Secrets and variables → Actions → "
                 "New repository secret (name LIBRARY_PASSWORD, value = your library password).")
    payload, salt = load(password)                 # keep the salt so 'remember me' keeps working
    videos = payload.get("videos", [])
    if len(sys.argv) > 1:
        new = json.loads(Path(sys.argv[1]).read_text())
        ids = {e["id"] for e in new}
        videos = new + [e for e in videos if e["id"] not in ids]
    payload["videos"] = videos
    token = os.environ.get("DISPATCH_TOKEN", "")
    payload["dispatch"] = {"repo": os.environ.get("GITHUB_REPOSITORY", "renekmarken/yta"),
                           "ref": os.environ.get("LIBRARY_REF") or os.environ.get("GITHUB_REF_NAME", ""),
                           "workflow": "batch.yml", "token": token} if token else None
    save(payload, password, salt)
    print(f"video library: {len(videos)} videos, generate button {'on' if token else 'off (no DISPATCH_TOKEN)'}")


if __name__ == "__main__":
    main()
