"""White Screen videos, part 3: voice, word-by-word captions and the finished MP4.

  voice()    the whole script in one take (Microsoft Edge neural voice) with the exact time of every
             word; Piper is the offline backup (word times then estimated from the text)
  fit()      keeps the video between 35 and 45 seconds (never under 35): the voice is gently slowed
             down or sped up, and a short silent hold is added at the end if needed
  render()   1920x1080, plain white; each word pops in, centred, in big black Airone letters, exactly
             when it is spoken; a few icons pop up at key words (like, comment, deleted...) with a
             simple sound effect each; no music
"""
import asyncio
import math
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from . import config
from . import ws_assets as A
from .tts import duration

W, H, FPS = 1920, 1080, 30
MIN_S, MAX_S, TARGET_S = 35.0, 45.0, 40.0


# ------------------------------------------------------------------ voice with word times
async def _edge_words(text, path, voice, rate):
    import edge_tts
    words, audio = [], bytearray()
    com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    async for ch in com.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            start = ch["offset"] / 1e7
            words.append([start, start + ch["duration"] / 1e7, ch["text"]])
    Path(path).write_bytes(bytes(audio))
    return words


def _estimate_words(text, total):
    """Word times when the voice engine gives none: spread by length, short pauses at punctuation."""
    toks = text.split()
    weights = [len(re.sub(r"\W", "", t)) + 2 + (4 if re.search(r"[.!?…]$", t) else 2 if t.endswith(",") else 0)
               for t in toks]
    unit = total / max(1, sum(weights))
    out, t = [], 0.15
    for tok, wgt in zip(toks, weights):
        out.append([t, t + unit * (len(re.sub(r"\W", "", tok)) + 2) * 0.9, tok])
        t += unit * wgt
    return out


def voice(text, out_dir: Path):
    """(mp3 path, [[start, end, word], ...])."""
    path = out_dir / "voice.mp3"
    v = config.WS_VOICE or config.TTS_VOICE
    for attempt in range(3):
        try:
            words = asyncio.run(_edge_words(text, path, v, config.WS_RATE))
            if path.stat().st_size > 5000 and words:
                return path, words
        except Exception as e:
            print(f"   ! edge voice failed ({type(e).__name__}: {str(e)[:120]})")
    from .tts import piper_say
    print("   voice: Piper backup (word times estimated)")
    piper_say(text, path)
    return path, _estimate_words(text, duration(path))


def fit(path: Path, words, out_dir: Path):
    """Stretch the voice into 35-45 s. Returns (mp3, words, total video seconds)."""
    speech = duration(path)
    tail = 0.9                                            # last word stays on screen a moment
    total = speech + tail
    factor = 1.0
    if total < MIN_S:
        factor = max(0.86, (speech) / (MIN_S + 0.4 - tail))   # slow down a little (pitch kept)
    elif total > MAX_S:
        factor = min(1.18, speech / (MAX_S - 0.6 - tail))
    if abs(factor - 1) > 0.01:
        fixed = out_dir / "voice_fit.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-filter:a", f"atempo={factor:.4f}",
                        "-b:a", "192k", str(fixed)], check=True)
        print(f"   voice {speech:.1f}s -> x{factor:.2f} to fit 35-45 s")
        path, speech = fixed, duration(fixed)
        words = [[a / factor, b / factor, w] for a, b, w in words]
    total = max(MIN_S, speech + tail)
    return path, words, total


# ------------------------------------------------------------------ captions
def display_words(words):
    """Caption tokens: quotes and stray symbols dropped, upper case (Airone is all caps)."""
    out = []
    for a, b, w in words:
        t = re.sub(r"[“”\"«»]", "", w).strip()
        t = t.strip("—–-")
        if not re.search(r"[\w$%]", t):
            continue
        out.append((a, b, t.upper()))
    return out


def srt(words, path: Path, per=6):
    """Captions file for YouTube: short groups of words with exact times."""
    def ts(x):
        h, rem = divmod(x, 3600)
        m, sec = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{int((sec % 1) * 1000):03d}"
    lines, i, n = [], 0, 1
    while i < len(words):
        grp = words[i:i + per]
        cut = next((k + 1 for k, (_, _, w) in enumerate(grp) if re.search(r"[.!?…]$", w)), len(grp))
        grp = grp[:cut]
        lines.append(f"{n}\n{ts(grp[0][0])} --> {ts(grp[-1][1] + 0.05)}\n{' '.join(w for _, _, w in grp)}\n")
        i += len(grp)
        n += 1
    path.write_text("\n".join(lines))


# ------------------------------------------------------------------ cues: icons + sound effects
SFX_FOR = {"like": "pop", "likes": "pop", "liked": "pop", "comment": "bubble", "comments": "bubble",
           "subscribe": "click", "deleted": "glitch", "delete": "glitch", "deleting": "glitch",
           "private": "click", "gone": "whoosh", "disappear": "whoosh", "disappears": "whoosh",
           "hours": "ding", "tomorrow": "ding", "reveal": "sparkle", "pinned": "ding", "pin": "ding",
           "views": "coin", "view": "coin", "heart": "sparkle"}
ICON_FOR = {"like": "like", "likes": "like", "comment": "comment", "comments": "comment",
            "subscribe": "subscribe", "deleted": "trash", "delete": "trash", "deleting": "trash",
            "private": "lock", "hours": "hourglass", "tomorrow": "hourglass", "pinned": "pin", "pin": "pin",
            "views": "eye", "view": "eye", "heart": "heart"}


def plan_cues(words, script_cues, max_icons=5):
    """Pick the moments: the script's own cues first, then the key words; never two within 1.6 s."""
    plain = [re.sub(r"[^a-z0-9]", "", w.lower()) for _, _, w in words]
    picked, last = [], -9.0
    wanted = [(re.sub(r"[^a-z0-9]", "", str(c.get("word", "")).lower().split()[0] if str(c.get("word", "")).split() else ""),
               c.get("sfx"), c.get("icon")) for c in script_cues]
    used = set()
    for target, sfx, ic in wanted:
        for i, p in enumerate(plain):
            if p == target and i not in used and words[i][0] - last > 1.6:
                ic = ic if ic and ic != "none" else ICON_FOR.get(p)
                picked.append({"t": words[i][0], "i": i, "sfx": sfx if sfx and sfx != "none" else SFX_FOR.get(p, "pop"),
                               "icon": ic})
                used.add(i)
                last = words[i][0]
                break
    for i, p in enumerate(plain):                         # the asks themselves always get a sound
        if p in ("like", "comment") and i not in used and all(abs(words[i][0] - c["t"]) > 1.6 for c in picked):
            picked.append({"t": words[i][0], "i": i, "sfx": SFX_FOR[p], "icon": ICON_FOR[p]})
            used.add(i)
    picked.sort(key=lambda c: c["t"])
    shown = 0
    for c in picked:                                      # only a few icons: it's a white-screen video
        if c.get("icon") and shown < max_icons:
            shown += 1
        else:
            c["icon"] = None
    return picked


def sfx_track(cues, total, path: Path):
    from .music import SR
    from .sfx import MAKERS, _level
    rng = np.random.default_rng(7)
    n = int((total + 1) * SR)
    mix = np.zeros(n)
    for c in cues:
        name = c.get("sfx")
        if not name or name not in MAKERS:
            continue
        sig = _level(MAKERS[name](rng, 1.0), target_db=-22) * 0.8
        s = int(max(0, c["t"] - 0.02) * SR)
        e = min(n, s + len(sig))
        mix[s:e] += sig[: e - s]
    peak = np.abs(mix).max() or 1
    if peak > 0.9:
        mix *= 0.9 / peak
    pcm = (np.stack([mix, mix], axis=1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


# ------------------------------------------------------------------ the picture
def _pop(t, dur=0.14, over=1.1, start=0.8):
    """Scale for a pop-in: start -> over -> 1.0 in `dur` seconds (ease-out)."""
    if t >= dur:
        return 1.0
    half = dur * 0.55
    if t < half:
        x = t / half
        return start + (over - start) * (1 - (1 - x) ** 2)
    x = (t - half) / (dur - half)
    return over + (1 - over) * x


class Captions:
    def __init__(self, words):
        self.words = words
        self.cache = {}

    def image(self, text):
        if text not in self.cache:
            size = A.fit_size(text, W * 0.82, 230, start=210, floor=70)
            tw, th = A.text_size(text, size)
            im = Image.new("RGBA", (int(tw + 40), int(th + 80)), (255, 255, 255, 0))
            A.draw_text(im, (im.width / 2, im.height / 2), text, size, fill=(10, 10, 10))
            self.cache[text] = im.crop(im.getbbox())
        return self.cache[text]

    def at(self, t):
        """(index, word) on screen at time t, or (None, None)."""
        cur = None
        for i, (a, b, w) in enumerate(self.words):
            if a <= t:
                cur = i
            else:
                break
        if cur is None:
            return None, None
        a, b, w = self.words[cur]
        nxt = self.words[cur + 1][0] if cur + 1 < len(self.words) else b + 0.9
        if t > b + 0.45 and t < nxt:                       # a real pause: clear the screen
            return None, None
        return cur, w


def render(words, cues, voice_mp3: Path, total: float, out_mp4: Path, work: Path):
    """Write the finished video. words: [(start, end, TEXT)]; cues from plan_cues()."""
    caps = Captions(words)
    icons = {}
    for c in cues:
        if c.get("icon") and c["icon"] not in icons:
            icons[c["icon"]] = A.icon(c["icon"], 300 if c["icon"] != "subscribe" else 520)
    sfx = sfx_track(cues, total, work / "sfx.wav")
    frames = int(math.ceil(total * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(voice_mp3), "-i", str(sfx),
           "-filter_complex", "[1:a]apad[v];[v][2:a]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5[a]",
           "-map", "0:v", "-map", "[a]", "-t", f"{total:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "192k", str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    white = Image.new("RGB", (W, H), (255, 255, 255))
    for f in range(frames):
        t = f / FPS
        frame = white.copy()
        live = [c for c in cues if c.get("icon") and c["t"] <= t < c["t"] + 1.5]
        cap_y = H / 2 + (130 if live else 0)
        if live:
            c = live[-1]
            age = t - c["t"]
            ic = icons[c["icon"]]
            k = _pop(age, 0.22, 1.15, 0.2)
            if age > 1.3:                                  # quick shrink away
                k *= max(0.0, 1 - (age - 1.3) / 0.2)
            if k > 0.02:
                im = ic.resize((max(1, int(ic.width * k)), max(1, int(ic.height * k))), Image.BILINEAR)
                frame.paste(im, (int(W / 2 - im.width / 2), int(cap_y - 170 - im.height)), im)
        i, w = caps.at(t)
        if w:
            im = caps.image(w)
            k = _pop(t - words[i][0])
            if abs(k - 1) > 0.005:
                im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BILINEAR)
            frame.paste(im, (int(W / 2 - im.width / 2), int(cap_y - im.height / 2)), im)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the White Screen video")
    return out_mp4
