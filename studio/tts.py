"""Step 3: voice-over. Microsoft Edge neural voices (free) with an offline Piper backup.

Tip: record your own voice as voice/seg_00.mp3, seg_01.mp3 ... in a video's folder and rerender;
your recordings are used instead of the AI voice.
"""
import asyncio
import re
import subprocess
import wave
from pathlib import Path

import requests

from . import config

_engine = {"name": None}


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def speakable(text):
    """Small fixes so TTS reads finance text naturally."""
    t = text.replace("&", " and ").replace("%", " percent").replace("w/", "with ")
    t = re.sub(r"\bAPY\b", "A.P.Y.", t)
    t = re.sub(r"\bAPR\b", "A.P.R.", t)
    t = re.sub(r"\bvs\b\.?", "versus", t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ Edge (primary)
async def _edge(text, path):
    import edge_tts
    await edge_tts.Communicate(text, config.TTS_VOICE, rate=config.TTS_RATE).save(str(path))


def edge_say(text, path):
    asyncio.run(_edge(text, path))
    if not path.exists() or path.stat().st_size < 2000:
        raise RuntimeError("edge-tts returned no audio")


# ------------------------------------------------------------------ Piper (offline backup)
def _piper_model():
    d = config.CACHE_DIR / "piper"
    d.mkdir(parents=True, exist_ok=True)
    name = config.PIPER_VOICE                          # e.g. en_US-ryan-high
    lang, speaker, quality = name.split("-")
    base = (f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{lang.split('_')[0]}/{lang}/{speaker}/{quality}/{name}")
    for ext in (".onnx", ".onnx.json"):
        f = d / (name + ext)
        if not f.exists():
            r = requests.get(base + ext, timeout=300)
            r.raise_for_status()
            f.write_bytes(r.content)
    return d / (name + ".onnx")


def piper_say(text, path):
    from piper import PiperVoice
    voice = PiperVoice.load(str(_piper_model()))
    wav = path.with_suffix(".wav")
    with wave.open(str(wav), "wb") as wf:
        if hasattr(voice, "synthesize_wav"):           # piper-tts >= 1.3
            voice.synthesize_wav(text, wf)
        else:                                          # piper-tts 1.2
            voice.synthesize(text, wf)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", "loudnorm=I=-16",
                    "-b:a", "160k", str(path)], check=True)
    wav.unlink(missing_ok=True)


ENGINES = [("edge", edge_say), ("piper", piper_say)]


def say(text, path):
    errors = []
    order = sorted(ENGINES, key=lambda e: e[0] != _engine["name"]) if _engine["name"] else ENGINES
    for name, fn in order:
        for attempt in range(2 if name == "edge" else 1):
            try:
                fn(text, path)
                if _engine["name"] != name:
                    print(f"   voice engine: {name}")
                _engine["name"] = name
                return name
            except Exception as e:
                errors.append(f"{name}: {str(e)[:160]}")
    raise RuntimeError("All voice engines failed: " + " | ".join(errors))


def narrate(segments: list, out_dir: Path) -> list:
    vdir = out_dir / "voice"
    vdir.mkdir(exist_ok=True)
    for i, seg in enumerate(segments):
        path = vdir / f"seg_{i:02d}.mp3"
        if not path.exists():
            say(speakable(seg["text"]), path)
        seg["audio"] = str(path)
        seg["duration"] = duration(path)
    return segments


def fit_length(segments: list, extra: float, min_s=125.0, max_s=175.0) -> float:
    """Keep the finished video between 2 and 3 minutes: if the narration came out too long or
    too short, gently speed it up or slow it down (atempo keeps the pitch). Returns total seconds."""
    speech = sum(s["duration"] for s in segments)
    total = speech + extra
    if min_s <= total <= max_s:
        return total
    target = (max_s - 8 if total > max_s else min_s + 8) - extra
    factor = max(0.9, min(1.25, speech / max(target, 1)))
    print(f"   video would be {total:.0f}s; adjusting voice speed x{factor:.2f} to fit 2-3 minutes")
    for seg in segments:
        src = Path(seg["audio"])
        tmp = src.with_name(src.stem + "_fit.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter:a", f"atempo={factor:.4f}",
                        "-b:a", "160k", str(tmp)], check=True)
        tmp.replace(src)
        seg["duration"] = duration(src)
    total = sum(s["duration"] for s in segments) + extra
    if not min_s - 5 <= total <= max_s + 5:
        print(f"   ! video is {total:.0f}s, outside 2-3 minutes (script length was off)")
    return total


# ------------------------------------------------------------------ captions
def _ts(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{int((sec % 1) * 1000):03d}"


def write_srt(segments, path: Path):
    """Sentence-level subtitles, timed by each segment's real audio length."""
    lines, n, t0 = [], 1, 0.0
    for seg in segments:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", seg["text"].strip()) if s]
        chunks = []
        for s in sentences:                             # keep cues short (max ~12 words)
            w = s.split()
            for k in range(0, len(w), 12):
                chunks.append(" ".join(w[k:k + 12]))
        total = sum(len(c) for c in chunks) or 1
        t = t0
        for c in chunks:
            d = seg["duration"] * len(c) / total
            lines.append(f"{n}\n{_ts(t)} --> {_ts(t + d - 0.05)}\n{c}\n")
            n += 1
            t += d
        t0 += seg["clip_duration"]
    path.write_text("\n".join(lines))
    return path
