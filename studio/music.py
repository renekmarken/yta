"""Original background music, composed and synthesised for each video (no samples, no licences).

Five moods, each with its own tempo range, chord progressions, instruments and drum feel. The key,
tempo, progression, voicings and arrangement are drawn from the video's seed, so no two videos get
the same track. Output: a 44.1 kHz stereo WAV a little longer than the video.
"""
import math
import random
import wave
from pathlib import Path

import numpy as np

SR = 44100
MOODS = ["lofi", "upbeat", "ambient", "tech", "acoustic", "chords"]

MAJOR = {"I": (0, "maj"), "ii": (2, "min"), "iii": (4, "min"), "IV": (5, "maj"), "V": (7, "maj"),
         "vi": (9, "min")}
MINOR = {"i": (0, "min"), "III": (3, "maj"), "iv": (5, "min"), "v": (7, "min"), "VI": (8, "maj"),
         "VII": (10, "maj")}
PROGRESSIONS = {
    "lofi": [("major", "ii V I vi"), ("major", "IV iii ii I"), ("minor", "i iv VII III"),
             ("major", "I vi ii V"), ("minor", "i VI III VII")],
    "upbeat": [("major", "I V vi IV"), ("major", "vi IV I V"), ("major", "I IV vi V"),
               ("major", "IV I V vi")],
    "ambient": [("major", "I iii IV I"), ("minor", "i VI III VII"), ("major", "IV I V vi"),
                ("minor", "i iv VI v")],
    "tech": [("minor", "i VI III VII"), ("minor", "i VII VI VII"), ("minor", "i iv VI v"),
             ("minor", "VI VII i i")],
    "acoustic": [("major", "I V vi IV"), ("major", "I IV I V"), ("major", "vi IV I V"),
                 ("major", "I iii IV V")],
    "chords": [("major", "I vi IV V"), ("major", "IV I vi V"), ("major", "I iii vi IV"),
               ("major", "vi IV I V"), ("minor", "i VI III VII"), ("major", "I IV vi IV")],
}
TEMPO = {"lofi": (72, 86), "upbeat": (108, 122), "ambient": (62, 74), "tech": (116, 126),
         "acoustic": (92, 104), "chords": (60, 70)}
SEVENTHS = {"lofi": True, "upbeat": False, "ambient": True, "tech": False, "acoustic": False, "chords": True}


# ------------------------------------------------------------------ basic synthesis
def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _t(n):
    return np.arange(n) / SR


def _env(n, attack, release, decay=None):
    """Attack/release envelope, optionally with an exponential decay (seconds)."""
    e = np.ones(n)
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    a, r = min(a, n), min(r, n)
    e[:a] = np.linspace(0, 1, a)
    e[n - r:] *= np.linspace(1, 0, r)
    if decay:
        e *= np.exp(-_t(n) / decay)
    return e


def additive(freq, dur, partials, decay, attack=0.004, release=0.05, bright_decay=1.0):
    """Sum of harmonics; higher harmonics fade faster (natural plucked/struck sound)."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for k, amp in partials:
        f = freq * k
        if f > SR / 2.3:
            break
        d = decay / (1 + (k - 1) * bright_decay) if decay else None
        out += amp * np.sin(2 * np.pi * f * t) * (np.exp(-t / d) if d else 1)
    return out * _env(n, attack, release)


def epiano(freq, dur):
    n = int(dur * SR)
    t = _t(n)
    mod = 1.6 * np.exp(-t / 0.25) * np.sin(2 * np.pi * freq * t)            # bell-like FM attack
    tone = np.sin(2 * np.pi * freq * t + mod) + 0.25 * np.sin(2 * np.pi * 2 * freq * t)
    trem = 1 + 0.12 * np.sin(2 * np.pi * 4.5 * t)
    return tone * trem * _env(n, 0.006, 0.12, decay=1.6)


def pluck(freq, dur, bright=1.0):
    parts = [(k, 1 / k ** 1.1) for k in range(1, 14)]
    return additive(freq, dur, parts, decay=0.9, bright_decay=0.6 / bright)


def guitar(freq, dur):
    parts = [(k, (1 / k) * (0.6 if k % 2 == 0 else 1)) for k in range(1, 16)]
    return additive(freq, dur, parts, decay=1.4, bright_decay=0.45, attack=0.002)


def bell(freq, dur):
    parts = [(1, 1), (2.01, 0.35), (3.0, 0.2), (4.2, 0.12)]
    n = int(dur * SR)
    t = _t(n)
    out = sum(a * np.sin(2 * np.pi * freq * k * t) * np.exp(-t * (1.2 + k)) for k, a in parts)
    return out * _env(n, 0.003, 0.2)


def soft_piano(freq, dur):
    """A felt-damped piano note: warm, quiet attack, long soft decay (no bright 'ping')."""
    parts = [(1, 1.0), (2, 0.42), (3, 0.18), (4, 0.09), (5, 0.05), (6, 0.03)]
    return additive(freq, dur, parts, decay=3.2, attack=0.025, release=0.6, bright_decay=1.4)


def pad(freq, dur, rnd):
    """Detuned band-limited saws with a slow swell."""
    n = int(dur * SR)
    t = _t(n)
    out = np.zeros(n)
    for detune in (-0.12, 0.0, 0.11):
        f = freq * 2 ** (detune / 12)
        ph = rnd.random() * 6.28
        for k in range(1, 10):
            if f * k > 9000:
                break
            out += np.sin(2 * np.pi * f * k * t + ph * k) / k
    return out / 3 * _env(n, min(0.9, dur * 0.4), min(0.9, dur * 0.4))


def square(freq, dur, decay=0.18):
    parts = [(k, 1 / k) for k in (1, 3, 5, 7, 9)]
    return additive(freq, dur, parts, decay=decay, bright_decay=0.3, attack=0.002, release=0.02)


def bass(freq, dur, kind="sine"):
    n = int(dur * SR)
    t = _t(n)
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t)
    if kind == "pluck":
        tone += 0.15 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-t / 0.08)
        return tone * _env(n, 0.004, 0.06, decay=0.45)
    return tone * _env(n, 0.01, 0.08)


# ------------------------------------------------------------------ drums (one-shots, cached)
class Kit:
    def __init__(self, rnd, soft=False):
        nr = np.random.default_rng(rnd.randint(0, 10 ** 9))
        self.kick = self._kick(soft)
        self.snare = self._snare(nr, soft)
        self.clap = self._clap(nr)
        self.hat = self._hat(nr, 0.035)
        self.open_hat = self._hat(nr, 0.16)
        self.shaker = self._shaker(nr)
        self.rim = self._rim()

    @staticmethod
    def _kick(soft):
        n = int(0.45 * SR)
        t = _t(n)
        f = 45 + (110 if not soft else 75) * np.exp(-t / 0.045)
        ph = 2 * np.pi * np.cumsum(f) / SR
        k = np.sin(ph) * np.exp(-t / (0.32 if not soft else 0.22))
        k[:60] += np.linspace(0.6, 0, 60) * (0 if soft else 1)                 # click
        return k * 0.95

    @staticmethod
    def _hp(x, width=6):
        return x - np.convolve(x, np.ones(width) / width, mode="same")

    def _snare(self, nr, soft):
        n = int(0.25 * SR)
        t = _t(n)
        noise = self._hp(nr.standard_normal(n), 4) * np.exp(-t / (0.09 if soft else 0.12))
        tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.05)
        return (0.55 * noise + 0.5 * tone) * (0.5 if soft else 0.75)

    def _clap(self, nr):
        n = int(0.3 * SR)
        t = _t(n)
        out = np.zeros(n)
        for off in (0, 0.011, 0.022):
            s = int(off * SR)
            burst = self._hp(nr.standard_normal(n - s), 3) * np.exp(-_t(n - s) / (0.012 if off < 0.02 else 0.14))
            out[s:] += burst
        return out * 0.4 * np.exp(-t / 0.2)

    def _hat(self, nr, decay):
        n = int((decay * 4) * SR)
        return self._hp(nr.standard_normal(n), 2) * np.exp(-_t(n) / decay) * 0.22

    def _shaker(self, nr):
        n = int(0.09 * SR)
        e = np.sin(np.linspace(0, np.pi, n)) ** 2
        return self._hp(nr.standard_normal(n), 2) * e * 0.12

    @staticmethod
    def _rim():
        n = int(0.08 * SR)
        t = _t(n)
        return (np.sin(2 * np.pi * 820 * t) + 0.5 * np.sin(2 * np.pi * 1640 * t)) * np.exp(-t / 0.012) * 0.35


# ------------------------------------------------------------------ mixing helpers
class Track:
    def __init__(self, n):
        self.l = np.zeros(n)
        self.r = np.zeros(n)

    def add(self, sig, at, gain=1.0, pan=0.0):
        s = int(at * SR)
        if s >= len(self.l) or s < 0:
            return
        e = min(len(self.l), s + len(sig))
        seg = sig[: e - s] * gain
        self.l[s:e] += seg * math.cos((pan + 1) * math.pi / 4) * 1.41
        self.r[s:e] += seg * math.sin((pan + 1) * math.pi / 4) * 1.41


def lowpass(x, cutoff, order=2):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / np.sqrt(1 + (f / cutoff) ** (2 * order))
    return np.fft.irfft(spec, len(x))


def reverb(l, r, size=1.0, mix_amt=0.25):
    """Cheap diffuse reverb: decaying multi-tap echoes, different per channel, then darkened."""
    out = []
    for ch, delays in ((l, (1031, 1327, 1601, 1871, 2269, 2593)),
                       (r, (1129, 1423, 1709, 1999, 2381, 2711))):
        wet = np.zeros_like(ch)
        for d in delays:
            d = int(d * size * 2.2)
            g = 0.62
            for k in range(1, 9):
                s = d * k
                if s >= len(ch):
                    break
                wet[s:] += ch[:-s] * (g ** k) / len(delays)
        out.append(ch + lowpass(wet, 5000) * mix_amt * 3)
    return out


# ------------------------------------------------------------------ composition
def _chord(key, roman, scale, seventh, octave=4):
    table = MAJOR if scale == "major" else MINOR
    off, quality = table[roman]
    third = 4 if quality == "maj" else 3
    notes = [0, third, 7] + ([11 if quality == "maj" else 10] if seventh else [])
    root = 12 * (octave + 1) + key + off
    while root > 12 * (octave + 1) + 7:          # keep voicings in a comfortable range
        root -= 12
    return root, [root + n for n in notes]


def compose(mood, seconds, seed, path: Path) -> Path:
    rnd = random.Random(f"{seed}-music-{mood}")
    bpm = rnd.uniform(*TEMPO[mood])
    beat = 60 / bpm
    bar = 4 * beat
    key = rnd.randint(0, 11)
    scale, prog = rnd.choice(PROGRESSIONS[mood])
    prog = prog.split()
    seventh = SEVENTHS[mood] or rnd.random() < 0.3
    swing = 0.12 if mood == "lofi" else 0.0
    n = int((seconds + 2) * SR)
    kit = Kit(rnd, soft=mood in ("lofi", "ambient", "acoustic"))

    tr = {k: Track(n) for k in ("keys", "bass", "drums", "lead", "pad")}
    nbars = int(seconds / bar) + 2
    # arrangement: intro (no drums) · main · breakdown every 8th/9th bar · outro
    lead_on = rnd.random() < 0.7
    for b in range(nbars):
        t0 = b * bar
        roman = prog[b % len(prog)]
        root, chord = _chord(key, roman, scale, seventh)
        bass_note = root - 12 if root - 12 >= 36 else root
        intro = b < 2
        breakdown = (b % 16) in (12, 13) and b > 4
        outro = t0 > seconds - 2 * bar
        drums = not intro and not breakdown and not outro

        def sw(i, step=0.5):          # swung position of the i-th subdivision in the bar
            pos = i * step * beat
            return t0 + pos + (swing * beat if (i % 2 == 1 and step == 0.5) else 0)

        if mood == "lofi":
            for j, m in enumerate(chord):
                tr["keys"].add(epiano(hz(m), bar * 1.05), t0 + j * 0.018, 0.16, pan=-0.2 + j * 0.13)
            if rnd.random() < 0.5:
                for j, m in enumerate(chord[1:]):
                    tr["keys"].add(epiano(hz(m), beat * 1.5), t0 + 2.5 * beat + j * 0.015, 0.09)
            tr["bass"].add(bass(hz(bass_note), beat * 1.6, "pluck"), t0, 0.42)
            tr["bass"].add(bass(hz(bass_note + (7 if rnd.random() < 0.5 else 0)), beat * 0.9, "pluck"),
                           t0 + 2.5 * beat, 0.32)
            if drums:
                tr["drums"].add(kit.kick, t0, 0.7)
                tr["drums"].add(kit.kick, t0 + 2.5 * beat + swing * beat, 0.5)
                for s in (1, 3):
                    tr["drums"].add(kit.snare, t0 + s * beat, 0.45)
                for i in range(8):
                    tr["drums"].add(kit.hat, sw(i), 0.5 if i % 2 == 0 else 0.3, pan=0.25)
        elif mood == "upbeat":
            rhythm = rnd.choice([[0, 1.5, 2, 3.5], [0, 0.75, 1.5, 2.5, 3], [0, 1, 1.5, 2.5, 3.5]])
            for p in rhythm:
                for j, m in enumerate(chord):
                    tr["keys"].add(pluck(hz(m + 12), beat * 0.9), t0 + p * beat, 0.11, pan=-0.3 + j * 0.3)
            for i in range(8):
                tr["bass"].add(bass(hz(bass_note), beat * 0.45, "pluck"), t0 + i * beat / 2,
                               0.34 if i % 2 == 0 else 0.26)
            if drums:
                for s in range(4):
                    tr["drums"].add(kit.kick, t0 + s * beat, 0.75)
                    tr["drums"].add(kit.open_hat, t0 + (s + 0.5) * beat, 0.4, pan=0.2)
                for s in (1, 3):
                    tr["drums"].add(kit.clap, t0 + s * beat, 0.6)
            if lead_on and not intro and b % 4 in (1, 3):
                for i in range(4):
                    m = rnd.choice(chord) + 24
                    tr["lead"].add(bell(hz(m), beat), t0 + (i * 0.5 + 2) * beat, 0.08, pan=0.35)
        elif mood == "ambient":
            if b % 2 == 0:
                for j, m in enumerate(chord):
                    tr["pad"].add(pad(hz(m), bar * 2.2, rnd), t0, 0.09, pan=-0.4 + j * 0.27)
                tr["bass"].add(bass(hz(bass_note - 12 if bass_note >= 48 else bass_note), bar * 2.1), t0, 0.3)
            arp = chord + [chord[0] + 12]
            for i in range(8):
                if rnd.random() < 0.75:
                    m = arp[(i * rnd.choice([1, 2])) % len(arp)] + 12
                    tr["lead"].add(bell(hz(m), beat * 2), t0 + i * beat / 2, 0.07,
                                   pan=rnd.uniform(-0.5, 0.5))
            if drums and b % 2 == 0:
                tr["drums"].add(kit.kick, t0, 0.35)
        elif mood == "tech":
            pump = np.ones(int(bar * SR) + 1)
            for s in range(4):                                  # sidechain "pump" on the pad
                a = int(s * beat * SR)
                k = int(beat * 0.6 * SR)
                pump[a:a + k] = np.minimum(pump[a:a + k], 0.25 + 0.75 * np.linspace(0, 1, k) ** 1.5)
            chord_sig = sum(pad(hz(m), bar, rnd) for m in chord) / len(chord)
            tr["pad"].add(chord_sig * pump[:len(chord_sig)], t0, 0.28)
            arp = chord + [chord[1] + 12, chord[0] + 12]
            pattern = rnd.choice([[0, 1, 2, 3], [0, 2, 1, 3], [0, 1, 2, 4, 3, 2]])
            for i in range(16):
                m = arp[pattern[i % len(pattern)] % len(arp)] + 12
                tr["lead"].add(square(hz(m), beat / 4 * 0.9), t0 + i * beat / 4, 0.07,
                               pan=0.3 if i % 2 else -0.3)
            for i in range(8):
                tr["bass"].add(bass(hz(bass_note), beat * 0.4, "pluck"), t0 + i * beat / 2 + beat / 4, 0.3)
            if drums:
                for s in range(4):
                    tr["drums"].add(kit.kick, t0 + s * beat, 0.8)
                for s in (1, 3):
                    tr["drums"].add(kit.clap, t0 + s * beat, 0.5)
                for i in range(16):
                    tr["drums"].add(kit.hat, t0 + i * beat / 4, 0.32 if i % 4 == 2 else 0.16, pan=0.3)
        elif mood == "chords":                                  # quiet background chords: nothing else
            if b % 2 == 0:                                      # each chord rings for two bars
                low = chord[0] - 12
                voicing = [low] + chord[1:] + [chord[0] + 12]
                for j, m in enumerate(voicing):                 # gently rolled, low to high
                    tr["keys"].add(soft_piano(hz(m), bar * 2.1), t0 + j * 0.045, 0.13 if j else 0.16,
                                   pan=-0.25 + j * 0.12)
                for j, m in enumerate(chord):
                    tr["pad"].add(pad(hz(m), bar * 2.15, rnd), t0, 0.035, pan=-0.3 + j * 0.2)
            elif rnd.random() < 0.6:                            # a soft re-touch of the top notes
                for j, m in enumerate(chord[1:]):
                    tr["keys"].add(soft_piano(hz(m + 12), bar * 1.1), t0 + 2 * beat + j * 0.06, 0.05,
                                   pan=0.15 + j * 0.1)
        else:  # acoustic
            pick_pat = rnd.choice([[0, 2, 1, 2, 3, 2, 1, 2], [0, 1, 2, 3, 2, 1, 2, 3], [0, 2, 3, 2, 1, 2, 3, 2]])
            notes = [chord[0] - 12] + chord
            for i, p in enumerate(pick_pat):
                m = notes[p % len(notes)]
                tr["keys"].add(guitar(hz(m), beat * 2), t0 + i * beat / 2 + rnd.uniform(0, 0.01), 0.17,
                               pan=-0.25 + p * 0.15)
            tr["bass"].add(bass(hz(bass_note), beat * 1.8), t0, 0.32)
            tr["bass"].add(bass(hz(bass_note + 7), beat * 1.8), t0 + 2 * beat, 0.26)
            if drums:
                tr["drums"].add(kit.kick, t0, 0.55)
                tr["drums"].add(kit.kick, t0 + 2 * beat, 0.45)
                for s in (1, 3):
                    tr["drums"].add(kit.rim, t0 + s * beat, 0.5)
                for i in range(16):
                    tr["drums"].add(kit.shaker, t0 + i * beat / 4, 0.55 if i % 2 == 0 else 0.35, pan=0.35)

    # ---- mix
    L, R = np.zeros(n), np.zeros(n)
    wet_send = {"keys": 0.6, "pad": 1.0, "lead": 0.8, "bass": 0.05, "drums": 0.12}
    sendL, sendR = np.zeros(n), np.zeros(n)
    for k, t in tr.items():
        L += t.l
        R += t.r
        sendL += t.l * wet_send[k]
        sendR += t.r * wet_send[k]
    wl, wr = reverb(sendL, sendR, size=1.4 if mood in ("ambient", "chords") else 1.0,
                    mix_amt=0.4 if mood == "chords" else 0.35 if mood in ("ambient", "lofi") else 0.18)
    L, R = L + (wl - sendL), R + (wr - sendR)
    if mood == "chords":                                 # soft and far away: no highs to fight the voice
        L, R = lowpass(L, 3200), lowpass(R, 3200)
    if mood == "lofi":                                   # warm, dusty
        L, R = lowpass(L, 5200), lowpass(R, 5200)
        nr = np.random.default_rng(rnd.randint(0, 10 ** 9))
        hiss = lowpass(nr.standard_normal(n), 4000) * 0.004
        crackle = (nr.random(n) > 0.99985) * nr.uniform(-0.25, 0.25, n)
        L, R = L + hiss + crackle, R + hiss + crackle
    # fade in/out, gentle saturation, normalise
    fi, fo = int(1.5 * SR), int(3.0 * SR)
    for ch in (L, R):
        ch[:fi] *= np.linspace(0, 1, fi)
        ch[n - fo:] *= np.linspace(1, 0, fo)
    # same loudness for every mood: aim for -15 dBFS RMS, soft-limit the peaks
    rms = math.sqrt((np.mean(L ** 2) + np.mean(R ** 2)) / 2) or 1e-6
    peak = max(np.abs(L).max(), np.abs(R).max(), 1e-6)
    gain = min(10 ** (-15 / 20) / rms, 1.8 / peak)
    L, R = np.tanh(L * gain), np.tanh(R * gain)
    pcm = (np.stack([L, R], axis=1) * 0.92 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path
