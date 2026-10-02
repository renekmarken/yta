"""Synthesised sound effects (whoosh, pop, tick, riser, impact, ding), mixed into one track.

Three packs give videos a different feel: "soft" (gentle, rounded), "crisp" (bright, clicky) and
"punchy" (more low end and louder hits). Effects stay well under the narration.
"""
import math
import random
import wave
from pathlib import Path

import numpy as np

from .music import SR, lowpass

PACKS = ["soft", "crisp", "punchy"]


def _t(n):
    return np.arange(n) / SR



def whoosh(rng, pack, dur=0.55):
    n = int(dur * SR)
    t = _t(n)
    x = rng.standard_normal(n)
    # sweep a band of noise up then down (simulated by mixing two filtered versions)
    lo = lowpass(x, 900)
    hi = x - lowpass(x, 2500)
    shape = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    pos = np.clip(t / dur, 0, 1)
    sig = (lo * (1 - pos) + hi * pos * (0.6 if pack == "soft" else 1.0)) * shape
    return sig * (0.35 if pack != "punchy" else 0.45)


def pop(rng, pack):
    n = int(0.09 * SR)
    t = _t(n)
    f = (900 if pack == "crisp" else 600) * np.exp(-t / 0.03) + 250
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.025) * (0.5 if pack == "soft" else 0.65)


def tick(rng, pack):
    n = int(0.05 * SR)
    t = _t(n)
    f = 2400 if pack == "crisp" else 1600
    return (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.01 * t)) * np.exp(-t / 0.008) * 0.35


def blip(rng, pack):
    """Two quick rising notes, for stickers/callouts."""
    out = np.zeros(int(0.18 * SR))
    for k, (f, at) in enumerate(((880, 0), (1320, 0.06))):
        n = int(0.11 * SR)
        t = _t(n)
        s = int(at * SR)
        tone = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
        out[s:s + n] += tone * np.exp(-t / 0.04) * 0.28
    return out if pack != "soft" else lowpass(out, 3000)


def riser(rng, pack, dur=1.1):
    n = int(dur * SR)
    t = _t(n)
    f = 200 * (6 ** (t / dur))
    ph = 2 * np.pi * np.cumsum(f) / SR
    noise = rng.standard_normal(n)
    noise = noise - lowpass(noise, 1500)
    env = (t / dur) ** 2
    return (0.35 * np.sin(ph) + 0.25 * noise) * env * (0.4 if pack == "soft" else 0.55)


def impact(rng, pack):
    n = int(1.2 * SR)
    t = _t(n)
    f = 38 + 90 * np.exp(-t / 0.06)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / (0.5 if pack == "punchy" else 0.3))
    noise = lowpass(rng.standard_normal(n), 3000) * np.exp(-t / 0.08) * 0.4
    return (body + noise) * (0.85 if pack == "punchy" else 0.6)


def ding(rng, pack):
    n = int(1.6 * SR)
    t = _t(n)
    base = rng.choice([1046.5, 1174.7, 1318.5])
    parts = [(1, 1), (2.0, 0.4), (2.76, 0.25), (5.4, 0.1)]
    sig = sum(a * np.sin(2 * np.pi * base * k * t) * np.exp(-t * (1.5 + k)) for k, a in parts)
    return sig * 0.3


MAKERS = {"whoosh": whoosh, "pop": pop, "tick": tick, "blip": blip, "riser": riser,
          "impact": impact, "ding": ding}
LEVEL = {"whoosh": 0.8, "pop": 0.7, "tick": 0.6, "blip": 0.7, "riser": 0.7, "impact": 0.8, "ding": 0.8}


def build_track(events, total_seconds, pack, seed, path: Path) -> Path:
    """events: list of (time_seconds, effect_name). Writes a stereo WAV of total_seconds."""
    rng = np.random.default_rng(random.Random(f"{seed}-sfx").randint(0, 10 ** 9))
    n = int((total_seconds + 1) * SR)
    L, R = np.zeros(n), np.zeros(n)
    cache = {}
    for i, (at, name) in enumerate(sorted(events)):
        if name not in MAKERS:
            continue
        if name not in cache or name == "whoosh":          # vary whooshes a little each time
            cache[name] = MAKERS[name](rng, pack)
        sig = cache[name] * LEVEL[name]
        s = max(0, int(at * SR))
        e = min(n, s + len(sig))
        if e <= s:
            continue
        pan = 0.25 * math.sin(i * 1.7) if name in ("whoosh", "pop", "blip") else 0
        L[s:e] += sig[: e - s] * (1 - pan)
        R[s:e] += sig[: e - s] * (1 + pan)
    peak = max(np.abs(L).max(), np.abs(R).max(), 1e-6)
    if peak > 0.95:
        L, R = L * 0.95 / peak, R * 0.95 / peak
    pcm = (np.stack([L, R], axis=1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path
