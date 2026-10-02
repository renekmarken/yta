"""The private video library: encrypted list + encrypted files.

Everything is encrypted with a key made from the library password (GitHub secret LIBRARY_PASSWORD,
PBKDF2-SHA256, 600,000 rounds -> AES-256-GCM):
  * docs/videos/library.enc.json  - the list (titles, descriptions, tags, file references, ...)
  * vault/v/<id>/<kind>.bin        - the files (video, 3 thumbnails, captions, upload kit), kept on the
                                     repo's "vault" branch and read by the page through
                                     raw.githubusercontent.com, then decrypted in the browser.
Without the password both are unreadable.

  python tools/library.py add <folder with review folders> <run tag>
  python tools/library.py refresh                       # re-encrypt the list (new token / settings)
  python tools/library.py migrate                       # move older, unencrypted release files in
  python tools/library.py get <id> <out dir>            # decrypt one video (for the YouTube upload)
  python tools/library.py set-youtube <id> <url>
  python tools/library.py mark-uploaded "Robinhood, Zoho"   # file them under "Already uploaded"
"""
import base64
import json
import os
import re
import secrets
import sys
import urllib.request
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "videos"
ENC = DOCS / "library.enc.json"
PLAIN = DOCS / "videos.json"
VAULT = Path(os.environ.get("VAULT_DIR", ROOT / "vault"))
ITERATIONS = 600_000
KINDS = {"video": ("video/mp4", ".mp4"), "thumbnail": ("image/jpeg", ".jpg"),
         "captions": ("text/plain", ".srt"), "kit": ("text/markdown", ".md"),
         "script": ("application/json", ".json"),             # kept so thumbnails can be remade later
         "site": ("application/zip", ".zip")}                 # screenshots + logo, same reason
b64 = lambda b: base64.b64encode(b).decode()
MAGIC, CHUNK = b"YTVC1", 4 * 1024 * 1024          # chunked encryption for videos (phones decrypt piece by piece)
_aad = lambda i, n: i.to_bytes(4, "big") + n.to_bytes(4, "big")


def _password():
    pw = os.environ.get("LIBRARY_PASSWORD", "")
    if not pw:
        sys.exit("LIBRARY_PASSWORD is not set. Add it under Settings -> Secrets and variables -> Actions -> "
                 "New repository secret (name LIBRARY_PASSWORD, value = your library password).")
    return pw


def _key(password, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())


class Library:
    def __init__(self):
        self.password = _password()
        if ENC.exists():
            box = json.loads(ENC.read_text())
            self.salt = base64.b64decode(box["salt"])
            self.key = _key(self.password, self.salt)
            self.payload = json.loads(AESGCM(self.key).decrypt(base64.b64decode(box["iv"]),
                                                                base64.b64decode(box["data"]), None))
        else:
            self.salt = secrets.token_bytes(16)
            self.key = _key(self.password, self.salt)
            self.payload = {"videos": json.loads(PLAIN.read_text()) if PLAIN.exists() else []}
        self.videos = self.payload.setdefault("videos", [])

    # ---- files
    def seal(self, data: bytes, chunked=False) -> bytes:
        """iv||ciphertext, or for big files (videos) the chunked format the page can decrypt piece by
        piece on a phone: MAGIC, chunk size, then iv||ciphertext per 4 MB chunk. Each chunk's
        associated data is its index and the chunk count, so pieces can't be reordered or dropped."""
        if not chunked:
            iv = secrets.token_bytes(12)
            return iv + AESGCM(self.key).encrypt(iv, data, None)
        n = max(1, -(-len(data) // CHUNK))
        out = [MAGIC, CHUNK.to_bytes(4, "big")]
        for i in range(n):
            iv = secrets.token_bytes(12)
            out += [iv, AESGCM(self.key).encrypt(iv, data[i * CHUNK:(i + 1) * CHUNK], _aad(i, n))]
        return b"".join(out)

    def unseal(self, blob: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            return AESGCM(self.key).decrypt(blob[:12], blob[12:], None)
        size = int.from_bytes(blob[len(MAGIC):len(MAGIC) + 4], "big")
        step = 12 + size + 16
        body = blob[len(MAGIC) + 4:]
        n = max(1, -(-len(body) // step))
        return b"".join(AESGCM(self.key).decrypt(body[i * step:i * step + 12], body[i * step + 12:(i + 1) * step],
                                                 _aad(i, n)) for i in range(n))

    def store(self, vid, kind, data, filename, part=""):
        rel = f"v/{vid}/{kind}{part}.bin"
        dst = VAULT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self.seal(data, chunked=(kind == "video")))
        return {"path": rel, "name": filename, "type": KINDS[kind][0], "size": len(data)}

    def fetch(self, ref):
        """Bytes of a stored file (vault path, or an old plain URL)."""
        if isinstance(ref, str):                                    # old format: plain release URL
            with urllib.request.urlopen(ref, timeout=120) as r:
                return r.read()
        return self.unseal((VAULT / ref["path"]).read_bytes())

    # ---- list
    def check_files(self):
        """Entries whose encrypted files are not in the vault lose their file links (and say so), so
        the page never offers downloads that don't exist. Only runs when the vault was pulled."""
        if not (VAULT / ".git").exists():
            return
        for e in self.videos:
            files, lost = e.get("files") or {}, False
            for kind, ref in list(files.items()):
                refs = ref if isinstance(ref, list) else [ref]
                if any(isinstance(r, dict) and not (VAULT / r["path"]).exists() for r in refs):
                    del files[kind]
                    lost = True
            if lost:
                e["missing"] = True
                print(f"  ! files missing for {e.get('title')}")

    def save(self):
        self.check_files()
        token = os.environ.get("DISPATCH_TOKEN", "")
        self.payload["dispatch"] = {
            "repo": os.environ.get("GITHUB_REPOSITORY", "renekmarken/yta"),
            "ref": os.environ.get("LIBRARY_REF") or os.environ.get("GITHUB_REF_NAME", ""),
            "token": token} if token else None
        self.payload["vault"] = {"base": os.environ.get("VAULT_BASE") or (
            f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', 'renekmarken/yta')}/vault/")}
        iv = secrets.token_bytes(12)
        data = AESGCM(self.key).encrypt(iv, json.dumps(self.payload, ensure_ascii=False).encode(), None)
        DOCS.mkdir(parents=True, exist_ok=True)
        ENC.write_text(json.dumps({"v": 2, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64(self.salt),
                                   "iv": b64(iv), "data": b64(data)}))
        if PLAIN.exists():
            PLAIN.unlink()
        print(f"video library: {len(self.videos)} videos · generate/upload buttons "
              f"{'on' if token else 'off (no DISPATCH_TOKEN)'}")


def _filename(title, ext):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title or "").strip().rstrip(".")
    return "911video - " + (re.sub(r"\s+", " ", name)[:90].strip() or "video") + ext


def cmd_add(src, tag):
    lib = Library()
    added = []
    for meta_path in sorted(Path(src).rglob("metadata.json")):
        folder = meta_path.parent
        meta = json.loads(meta_path.read_text())
        mp4s = sorted(folder.glob("*.mp4"))
        if not mp4s:
            continue
        site = re.sub(r"[^a-z0-9-]+", "-", folder.name.lower()).strip("-") or "video"
        vid = f"{tag}-{site}"
        script = {}
        if (folder / "script.json").exists():
            try:
                script = json.loads((folder / "script.json").read_text())
            except json.JSONDecodeError:
                pass
        title = meta.get("title", "")
        files = {"video": lib.store(vid, "video", mp4s[0].read_bytes(), _filename(title, ".mp4"))}
        site_files = [p for p in folder.iterdir() if p.suffix == ".png" and not p.name.startswith(("hl_", "cap_"))
                      or p.name in ("site.json", "logo.svg")]
        if (folder / "site.json").exists():
            import io
            import zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
                for p in site_files:
                    z.write(p, p.name)
            files["site"] = lib.store(vid, "site", buf.getvalue(), f"{site} - screenshots.zip")
        thumbs = sorted(folder.glob("*thumbnail*.jpg"))         # 3 variations (older videos: 1)
        if thumbs:
            files["thumbnails"] = [lib.store(vid, "thumbnail", t.read_bytes(), f"911video - {site} - thumbnail {i}.jpg",
                                             f"-{i}") for i, t in enumerate(thumbs, 1)]
            files["thumbnail"] = files["thumbnails"][0]
        for kind, fname, label in (("captions", "captions.srt", "captions"), ("kit", "UPLOAD_KIT.md", "upload kit"),
                                   ("script", "script.json", "script")):
            if (folder / fname).exists():
                files[kind] = lib.store(vid, kind, (folder / fname).read_bytes(),
                                        f"911video - {site} - {label}{KINDS[kind][1]}")
        entry = {"id": vid, "date": date.today().isoformat(), "site": folder.name, "brand": script.get("brand", ""),
                 "title": title, "description": meta.get("description", ""), "tags": meta.get("tags", []),
                 "pinned_comment": meta.get("pinned_comment", ""), "verdict": meta.get("verdict", ""),
                 "score": meta.get("score", ""), "category": meta.get("category", ""),
                 "checks": meta.get("check_before_publishing", []), "files": files}
        yt = folder / "youtube_id.txt"
        if yt.exists():
            entry["youtube"] = f"https://youtu.be/{yt.read_text().strip()}"
        added.append(entry)
    ids = {e["id"] for e in added}
    sites = {e["site"] for e in added}                   # a remade video replaces one whose files were lost
    lib.videos[:] = added + [e for e in lib.videos if e["id"] not in ids
                             and not (e.get("missing") and e.get("site") in sites)]
    keep = int(os.environ.get("LIBRARY_KEEP", "150"))      # keep files of the newest N videos
    for e in lib.videos[keep:]:
        if e.get("files"):
            import shutil
            shutil.rmtree(VAULT / "v" / e["id"], ignore_errors=True)
            e["files"], e["expired"] = {}, True
    lib.save()
    with open(os.environ.get("LIBRARY_ADDED_FILE", "added.txt"), "a") as f:   # for the phone notification
        f.writelines(f"• {e['title']}\n" for e in added)
    print(f"added {len(added)} video(s)")


def cmd_refresh():
    Library().save()


def cmd_migrate():
    """Re-home videos whose files are plain release URLs into the encrypted vault, and re-encrypt
    single-piece video files in the chunked format phones can handle."""
    lib = Library()
    moved = 0
    for e in lib.videos:
        ref = (e.get("files") or {}).get("video")
        p = VAULT / ref["path"] if isinstance(ref, dict) else None
        if p and p.exists() and not p.read_bytes()[:len(MAGIC)] == MAGIC:
            p.write_bytes(lib.seal(lib.unseal(p.read_bytes()), chunked=True))
            print(f"  re-encrypted for phones: {e['title']}")
    for e in lib.videos:
        files = e.get("files", {})
        if not any(isinstance(v, str) for k, v in files.items() if k in KINDS):
            continue
        new = {}
        for kind, ref in files.items():
            if kind not in KINDS:                    # e.g. the list of thumbnail variations
                new[kind] = ref
                continue
            data = lib.fetch(ref)
            name = _filename(e.get("title"), ".mp4") if kind == "video" else \
                f"911video - {e.get('site', 'video')} - {kind}{KINDS[kind][1]}"
            new[kind] = lib.store(e["id"], kind, data, name) if isinstance(ref, str) else ref
        e["files"] = new
        moved += 1
        print(f"  encrypted {e['title']}")
    lib.save()
    print(f"migrated {moved} video(s)")


def cmd_get(vid, out):
    lib = Library()
    e = next((x for x in lib.videos if x["id"] == vid), None)
    if not e:
        sys.exit(f"no video with id {vid}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = e.get("files", {})
    names = {"video": "911video.mp4", "captions": "captions.srt", "kit": "UPLOAD_KIT.md"}
    for kind, ref in files.items():
        if kind in names:
            (out / names[kind]).write_bytes(lib.fetch(ref))
    for i, ref in enumerate(files.get("thumbnails") or ([files["thumbnail"]] if files.get("thumbnail") else []), 1):
        (out / f"911video-thumbnail-{i}.jpg").write_bytes(lib.fetch(ref))
    (out / "metadata.json").write_text(json.dumps({"title": e["title"], "description": e["description"],
                                                   "tags": e["tags"], "video_file": "911video.mp4"}, ensure_ascii=False))
    print(f"decrypted {e['title']}")


def cmd_mark_uploaded(names):
    """Mark videos as uploaded (matched by brand, site or title), so the page files them away."""
    lib = Library()
    wanted = [n.strip().lower() for n in names.split(",") if n.strip()]
    for e in lib.videos:
        text = f"{e.get('brand', '')} {e.get('site', '')} {e.get('title', '')}".lower()
        if any(w in text for w in wanted):
            e["uploaded"] = True
            print(f"  marked uploaded: {e.get('title')}")
    lib.save()


def cmd_remove_lost(names):
    """Remove library entries whose files were lost (matched by brand, site or title)."""
    import shutil
    lib = Library()
    wanted = [n.strip().lower() for n in names.split(",") if n.strip()]
    keep = []
    for e in lib.videos:
        text = f"{e.get('brand', '')} {e.get('site', '')} {e.get('title', '')}".lower()
        if e.get("missing") and any(w in text for w in wanted):
            shutil.rmtree(VAULT / "v" / e["id"], ignore_errors=True)
            print(f"  removed: {e.get('title')}")
        else:
            keep.append(e)
    lib.videos[:] = keep
    lib.save()


def cmd_set_youtube(vid, url):
    lib = Library()
    for e in lib.videos:
        if e["id"] == vid:
            e["youtube"] = url
    lib.save()


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"add": cmd_add, "refresh": cmd_refresh, "migrate": cmd_migrate, "get": cmd_get,
     "set-youtube": cmd_set_youtube, "mark-uploaded": cmd_mark_uploaded,
     "remove-lost": cmd_remove_lost}[cmd](*args)
