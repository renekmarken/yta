"""Synthesised sound effects, mixed into one track and kept well under the narration.

The video asks for *roles* (a transition, a caption appearing, a sticker popping in, the camera
landing on a number, the build-up and hit before the verdict, the verdict chime). Each video gets
one of 8 packs, and each pack plays its own sound for each role, drawn from 18 effects:

    whoosh, swish, air, swoosh_down, reverse   (movement)
    pop, click, tap, bubble, type               (text and UI)
    blip, coin, glitch, sparkle                 (stickers)
    marimba, pluck_note, chime, ding            (tonal accents)
    riser, shimmer_riser                        (build-ups)
    impact, thud, boom, zap                     (hits)
"""
import math
import random
import wave
from pathlib import Path

import numpy as np

from .music import SR, lowpass

ROLES = ["transition", "caption", "callout", "focus", "riser", "hit", "ding"]
# role -> effect for each pack (None = silent for that role)
PACK_MAP = {
    "soft":    {"transition": "air", "caption": "tap", "callout": "bubble", "focus": "click",
                "riser": "reverse", "hit": "thud", "ding": "chime"},
    "crisp":   {"transition": "whoosh", "caption": "click", "callout": "blip", "focus": "click",
                "riser": "riser", "hit": "impact", "ding": "ding"},
    "punchy":  {"transition": "whoosh", "caption": "pop", "callout": "blip", "focus": "tap",
                "riser": "riser", "hit": "boom", "ding": "ding"},
    "airy":    {"transition": "air", "caption": "bubble", "callout": "sparkle", "focus": "tap",
                "riser": "shimmer_riser", "hit": "thud", "ding": "chime"},
    "digital": {"transition": "swish", "caption": "type", "callout": "glitch", "focus": "click",
                "riser": "riser", "hit": "zap", "ding": "coin"},
    "warm":    {"transition": "air", "caption": "marimba", "callout": "pluck_note", "focus": "tap",
                "riser": "reverse", "hit": "thud", "ding": "marimba"},
    "minimal": {"transition": "swish", "caption": "tap", "callout": "click", "focus": None,
                "riser": None, "hit": "thud", "ding": "ding"},
    "playful": {"transition": "swoosh_down", "caption": "bubble", "callout": "coin", "focus": "pop",
                "riser": "shimmer_riser", "hit": "impact", "ding": "sparkle"},
}
PACKS = list(PACK_MAP)
# older event names used by the renderer -> roles
ALIASES = {"whoosh": "transition", "pop": "caption", "blip": "callout", "tick": "focus",
           "riser": "riser", "impact": "hit", "ding": "ding"}


def _t(n):
    return np.arange(n) / SR


def _sweep(f0, f1, dur, curve=1.0):
    n = int(dur * SR)
    x = np.linspace(0, 1, n) ** curve
    f = f0 * (f1 / f0) ** x
    return 2 * np.pi * np.cumsum(f) / SR


def _env(n, attack=0.002, decay=0.1):
    t = _t(n)
    e = np.exp(-t / decay)
    a = max(1, int(attack * SR))
    e[:a] *= np.linspace(0, 1, a)
    return e


def _hp(x, cutoff):
    return x - lowpass(x, cutoff)


# ------------------------------------------------------------------ movement
def whoosh(rng, k, dur=0.5):
    n = int(dur * SR)
    t = _t(n)
    x = rng.standard_normal(n)
    pos = np.clip(t / dur, 0, 1)
    sig = (lowpass(x, 900) * (1 - pos) + _hp(x, 2500) * pos) * np.sin(np.pi * pos) ** 2
    return sig * 0.32


def swish(rng, k, dur=0.28):
    n = int(dur * SR)
    pos = np.linspace(0, 1, n)
    sig = _hp(rng.standard_normal(n), 3500) * np.sin(np.pi * pos) ** 3
    return sig * 0.28


def air(rng, k, dur=0.7):
    n = int(dur * SR)
    pos = np.linspace(0, 1, n)
    sig = lowpass(_hp(rng.standard_normal(n), 300), 2200) * np.sin(np.pi * pos) ** 2
    return sig * 0.38


def swoosh_down(rng, k, dur=0.45):
    n = int(dur * SR)
    pos = np.linspace(0, 1, n)
    x = rng.standard_normal(n)
    sig = (_hp(x, 3000) * (1 - pos) + lowpass(x, 800) * pos) * np.sin(np.pi * pos) ** 2
    return sig * 0.3


def reverse(rng, k, dur=1.0):
    n = int(dur * SR)
    pos = np.linspace(0, 1, n)
    sig = _hp(rng.standard_normal(n), 2000) * pos ** 3
    return sig * 0.35


# ------------------------------------------------------------------ text / UI
def pop(rng, k):
    n = int(0.09 * SR)
    return np.sin(_sweep(700 * k, 260, 0.09, 0.4)) * _env(n, decay=0.025) * 0.55


def click(rng, k):
    n = int(0.03 * SR)
    sig = _hp(rng.standard_normal(n), 2000) * _env(n, 0.0005, 0.004)
    return sig * 0.5 + np.sin(2 * np.pi * 2200 * k * _t(n)) * _env(n, 0.0005, 0.006) * 0.2


def tap(rng, k):
    n = int(0.08 * SR)
    t = _t(n)
    tone = np.sin(2 * np.pi * 820 * k * t) + 0.4 * np.sin(2 * np.pi * 2140 * k * t)
    return (tone * _env(n, 0.001, 0.018) + _hp(rng.standard_normal(n), 3000) * _env(n, 0.0005, 0.004) * 0.3) * 0.4


def bubble(rng, k):
    n = int(0.11 * SR)
    return np.sin(_sweep(280 * k, 950 * k, 0.11, 0.6)) * np.sin(np.linspace(0, np.pi, n)) * 0.45


def type_(rng, k):
    out = np.zeros(int(0.32 * SR))
    for i in range(5):
        c = click(rng, k * rng.uniform(0.85, 1.15)) * rng.uniform(0.6, 1.0)
        s = int((i * 0.055 + rng.uniform(0, 0.015)) * SR)
        out[s:s + len(c)] += c[: len(out) - s]
    return out * 0.8


# ------------------------------------------------------------------ stickers / tonal
def blip(rng, k):
    out = np.zeros(int(0.18 * SR))
    for f, at in ((880 * k, 0), (1320 * k, 0.06)):
        n = int(0.11 * SR)
        t = _t(n)
        s = int(at * SR)
        out[s:s + n] += (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)) * np.exp(-t / 0.04) * 0.26
    return out


def coin(rng, k):
    out = np.zeros(int(0.32 * SR))
    for f, at, d in ((988 * k, 0, 0.07), (1319 * k, 0.07, 0.25)):
        n = int(d * SR)
        t = _t(n)
        sq = sum(np.sin(2 * np.pi * f * h * t) / h for h in (1, 3, 5))
        s = int(at * SR)
        out[s:s + n] += sq * np.exp(-t / (d * 0.6)) * 0.18
    return lowpass(out, 6000)


def glitch(rng, k):
    out = np.zeros(int(0.2 * SR))
    for i in range(4):
        n = int(rng.uniform(0.015, 0.035) * SR)
        burst = np.sign(np.sin(2 * np.pi * rng.uniform(300, 1600) * _t(n))) * 0.5 + rng.standard_normal(n) * 0.3
        s = int(i * 0.045 * SR)
        out[s:s + n] += burst[: len(out) - s] * 0.22
    return lowpass(out, 7000)


def sparkle(rng, k):
    out = np.zeros(int(0.6 * SR))
    for i in range(6):
        f = rng.choice([2093, 2349, 2637, 3136, 3520]) * k
        n = int(0.25 * SR)
        t = _t(n)
        s = int(i * 0.06 * SR)
        out[s:s + n] += np.sin(2 * np.pi * f * t) * np.exp(-t / 0.06) * 0.12 * rng.uniform(0.6, 1)
    return out


def marimba(rng, k):
    n = int(0.5 * SR)
    t = _t(n)
    f = 523.25 * k
    return (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.02)) * np.exp(-t / 0.15) * 0.4


def pluck_note(rng, k):
    n = int(0.6 * SR)
    t = _t(n)
    f = 659.25 * k
    sig = sum(np.sin(2 * np.pi * f * h * t) / h * np.exp(-t * (4 + h * 3)) for h in range(1, 8))
    return sig * 0.35


def chime(rng, k):
    out = np.zeros(int(1.6 * SR))
    for i, f in enumerate((784 * k, 988 * k, 1175 * k)):
        n = int(1.3 * SR)
        t = _t(n)
        s = int(i * 0.09 * SR)
        out[s:s + n] += (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.76 * t)) * np.exp(-t * 2.5) * 0.16
    return out


def ding(rng, k):
    n = int(1.6 * SR)
    t = _t(n)
    base = 1046.5 * k
    parts = [(1, 1), (2.0, 0.4), (2.76, 0.25), (5.4, 0.1)]
    return sum(a * np.sin(2 * np.pi * base * m * t) * np.exp(-t * (1.5 + m)) for m, a in parts) * 0.28


# ------------------------------------------------------------------ build-ups and hits
def riser(rng, k, dur=1.1):
    n = int(dur * SR)
    t = _t(n)
    noise = _hp(rng.standard_normal(n), 1500)
    return (0.35 * np.sin(_sweep(200, 1200, dur)) + 0.25 * noise) * (t / dur) ** 2 * 0.5


def shimmer_riser(rng, k, dur=1.1):
    n = int(dur * SR)
    t = _t(n)
    sig = sum(np.sin(_sweep(400 * m * k, 1600 * m * k, dur)) / m for m in (1, 1.5, 2))
    return sig * (t / dur) ** 2.5 * 0.22


def impact(rng, k):
    n = int(1.1 * SR)
    t = _t(n)
    body = np.sin(_sweep(130, 38, 1.1, 0.25)) * np.exp(-t / 0.3)
    return (body + lowpass(rng.standard_normal(n), 3000) * np.exp(-t / 0.08) * 0.4) * 0.6


def thud(rng, k):
    n = int(0.5 * SR)
    t = _t(n)
    return np.sin(_sweep(110, 45, 0.5, 0.3)) * np.exp(-t / 0.12) * 0.6


def boom(rng, k):
    n = int(1.8 * SR)
    t = _t(n)
    body = np.sin(_sweep(90, 30, 1.8, 0.2)) * np.exp(-t / 0.6)
    return (body + lowpass(rng.standard_normal(n), 900) * np.exp(-t / 0.25) * 0.5) * 0.7


def zap(rng, k):
    n = int(0.25 * SR)
    t = _t(n)
    sq = np.sign(np.sin(_sweep(1800, 120, 0.25, 0.5)))
    return lowpass(sq, 5000) * np.exp(-t / 0.08) * 0.3


MAKERS = {"whoosh": whoosh, "swish": swish, "air": air, "swoosh_down": swoosh_down, "reverse": reverse,
          "pop": pop, "click": click, "tap": tap, "bubble": bubble, "type": type_,
          "blip": blip, "coin": coin, "glitch": glitch, "sparkle": sparkle,
          "marimba": marimba, "pluck_note": pluck_note, "chime": chime, "ding": ding,
          "riser": riser, "shimmer_riser": shimmer_riser,
          "impact": impact, "thud": thud, "boom": boom, "zap": zap}
ROLE_GAIN = {"transition": 0.7, "caption": 0.75, "callout": 0.8, "focus": 0.55, "riser": 0.75,
             "hit": 0.9, "ding": 0.8}


def _level(sig, target_db=-20.0, peak=0.8):
    """Same loudness for every effect: RMS over the audible part, peaks kept below 0.8."""
    loud = np.abs(sig) > np.abs(sig).max() * 0.05
    rms = math.sqrt(float(np.mean(sig[loud] ** 2))) if loud.any() else 0.0
    if rms <= 0:
        return sig
    g = min(10 ** (target_db / 20) / rms, peak / (np.abs(sig).max() or 1))
    return sig * g


VARY = {"whoosh", "swish", "air", "swoosh_down", "type", "glitch", "sparkle"}   # re-roll each time


def build_track(events, total_seconds, pack, seed, path: Path) -> Path:
    """events: list of (time_seconds, role or old event name). Writes a stereo WAV."""
    rnd = random.Random(f"{seed}-sfx")
    rng = np.random.default_rng(rnd.randint(0, 10 ** 9))
    k = 2 ** (rnd.choice([-2, 0, 0, 2, 3, 5]) / 12)          # each video tuned a little differently
    mapping = PACK_MAP.get(pack, PACK_MAP["crisp"])
    n = int((total_seconds + 1) * SR)
    L, R = np.zeros(n), np.zeros(n)
    cache = {}
    for i, (at, name) in enumerate(sorted(events)):
        role = ALIASES.get(name, name)
        effect = mapping.get(role)
        if not effect:
            continue
        if effect not in cache or effect in VARY:
            cache[effect] = _level(MAKERS[effect](rng, k))
        sig = cache[effect] * ROLE_GAIN.get(role, 0.7)
        s = max(0, int(at * SR))
        e = min(n, s + len(sig))
        if e <= s:
            continue
        pan = 0.25 * math.sin(i * 1.7) if effect not in ("impact", "thud", "boom", "riser") else 0
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
