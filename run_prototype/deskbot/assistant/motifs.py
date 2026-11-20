"""
Short musical motifs, one per robot state, synthesised with numpy (no sound files, nothing downloaded).

All motifs share one small voice (a sine with a soft octave, plucked envelope) so they sound like the same
character. The meaning is carried by the shape of the melody:

    recognition     rising major arpeggio                "oh, I know that!"
    navigation      steady two-note walking figure       "on my way"
    arrival         resolving cadence up to the tonic    "made it"
    warning         falling minor second, repeated       tense, attention
    confusion       wandering notes ending unresolved    a musical question mark
    low_confidence  quiet, hesitant, slowly falling      "I'm not sure"
    picked_up       quick upward slide                   a startled "whoa"
    embarrassed     small descending sigh                "oops"

Sound effects (19 Nov 2026), the "sound" field of the AI's reply (commands.SOUNDS): tada, ding, pop, boing,
whoosh, giggle, rimshot, drumroll, sad_trombone, beep_boop, fanfare, notification, reminder, gasp, yawn.
They are made from the same pieces (plucked notes, pitch glides, filtered noise bursts) in _effect().
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .voice import write_wav

RATE = 22050
TEMPO_S = 0.11      # one beat

# (semitones above A4, beats); None = rest
MOTIFS = {
    "recognition": [(0, 1), (4, 1), (7, 1), (12, 2)],
    "navigation": [(0, 1), (7, 1), (0, 1), (7, 2)],
    "arrival": [(7, 1), (5, 1), (9, 1), (12, 3)],
    "warning": [(8, 1), (7, 2), (None, 1), (8, 1), (7, 2)],
    "confusion": [(5, 1), (3, 1), (6, 1), (4, 1), (8, 2)],
    "low_confidence": [(4, 2), (None, 1), (3, 2), (0, 3)],
    "picked_up": [(0, 0.5), (5, 0.5), (10, 0.5), (15, 2)],
    "embarrassed": [(7, 1), (6, 1), (4, 1), (3, 3)],
}
LEVEL = {"low_confidence": 0.6, "embarrassed": 0.7}


def _note(semitone, beats, tempo=TEMPO_S, harmonic=0.25):
    n = int(RATE * tempo * beats)
    if semitone is None:
        return np.zeros(n)
    t = np.arange(n) / RATE
    f = 440.0 * 2 ** (semitone / 12)
    tone = np.sin(2 * np.pi * f * t) + harmonic * np.sin(4 * np.pi * f * t)
    attack = np.minimum(1.0, t / 0.008)
    release = np.minimum(1.0, (t[-1] - t) / 0.02 + 1e-3)
    return tone * attack * release * np.exp(-2.5 * t / max(t[-1], 1e-3))


def _melody(notes, tempo=TEMPO_S, harmonic=0.25):
    return np.concatenate([_note(s, b, tempo, harmonic) for s, b in notes])


def _sweep(f0, f1, seconds, shape="exp", wobble=0.0, wobble_hz=0.0):
    """A sine whose pitch glides from f0 to f1 (Hz), optionally with vibrato."""
    t = np.arange(int(RATE * seconds)) / RATE
    k = t / seconds
    f = f0 * (f1 / f0) ** k if shape == "exp" else f0 + (f1 - f0) * k
    if wobble:
        f = f * (1 + wobble * np.sin(2 * np.pi * wobble_hz * t))
    phase = 2 * np.pi * np.cumsum(f) / RATE
    env = np.minimum(1.0, t / 0.01) * np.minimum(1.0, (t[-1] - t) / 0.04 + 1e-3)
    return np.sin(phase) * env


def _noise(seconds, rng, lowpass=0.0):
    x = rng.standard_normal(int(RATE * seconds))
    if lowpass:                                   # moving-average low-pass: 0 = white, 0.9 = dull (vectorised)
        k = max(2, int(round(1 / (1 - lowpass))))
        x = np.convolve(x, np.ones(k) / k, mode="same") * np.sqrt(k)
    return x


def _hit(seconds, rng, decay=30.0, lowpass=0.0, tone_hz=0.0):
    t = np.arange(int(RATE * seconds)) / RATE
    x = _noise(seconds, rng, lowpass)
    if tone_hz:
        x = 0.5 * x + np.sin(2 * np.pi * tone_hz * t) * 1.5
    return x * np.exp(-decay * t)


def _effect(name):
    """The sound effects of commands.SOUNDS (19 Nov 2026). Deterministic: a fixed noise seed."""
    rng = np.random.default_rng(7)
    if name == "tada":
        return _melody([(3, 1), (None, 0.4), (10, 1), (15, 4)], tempo=0.1)
    if name == "ding":
        t = np.arange(int(RATE * 0.6)) / RATE
        return (np.sin(2 * np.pi * 1568 * t) + 0.4 * np.sin(2 * np.pi * 3136 * t)) * np.exp(-6 * t)
    if name == "pop":
        return _sweep(900, 250, 0.07, "exp") * np.exp(-np.arange(int(RATE * 0.07)) / RATE * 30)
    if name == "boing":
        return _sweep(180, 520, 0.45, "lin", wobble=0.18, wobble_hz=14)
    if name == "whoosh":
        n = int(RATE * 0.5)
        env = np.sin(np.linspace(0, np.pi, n)) ** 2
        return _noise(0.5, rng, lowpass=0.8) * env * 2.5
    if name == "giggle":
        return np.concatenate([np.concatenate([_sweep(700 + 60 * i, 560 + 60 * i, 0.07), np.zeros(int(RATE * 0.03))])
                               for i in range(5)])
    if name == "rimshot":
        gap = np.zeros(int(RATE * 0.09))
        return np.concatenate([_hit(0.12, rng, 35, 0.3, 180), gap, _hit(0.12, rng, 35, 0.3, 180), gap,
                               _hit(0.5, rng, 7, 0.0) * 0.7])
    if name == "drumroll":
        hits = [_hit(0.045, rng, 70, 0.5, 200) * (0.5 + 0.5 * i / 17) for i in range(18)]
        return np.concatenate(hits + [_hit(0.35, rng, 9, 0.2, 150)])
    if name == "sad_trombone":
        notes = [(-5, 0.32), (-6, 0.32), (-7, 0.32), (-8, 0.9)]
        parts = []
        for i, (s, d) in enumerate(notes):
            f = 220 * 2 ** (s / 12)
            last = i == len(notes) - 1
            parts.append(_sweep(f, f * (0.97 if last else 1.0), d, wobble=0.02 if last else 0.0, wobble_hz=6))
        return np.concatenate(parts)
    if name == "beep_boop":
        return np.concatenate([_sweep(f, f, 0.08) for f in (880, 660, 990, 740)] * 1)
    if name == "fanfare":
        return _melody([(0, 1), (4, 1), (7, 1), (12, 2), (7, 1), (12, 5)], tempo=0.09, harmonic=0.6)
    if name == "notification":
        return _melody([(12, 1.2), (19, 3)], tempo=0.1)
    if name == "reminder":
        return _melody([(7, 1), (12, 1), (16, 3), (None, 2), (7, 1), (12, 1), (16, 3)], tempo=0.1)
    if name == "gasp":
        return _sweep(300, 900, 0.18) * 0.8
    if name == "yawn":
        return _sweep(520, 200, 0.9, wobble=0.03, wobble_hz=5)
    raise KeyError(name)


@lru_cache(maxsize=None)
def _synth_cached(name):
    return synth(name)


def synth(name):
    if name not in MOTIFS:
        x = _effect(name)
        return (x / max(np.abs(x).max(), 1e-6) * 0.85).astype(np.float32)
    out = []
    for semitone, beats in MOTIFS[name]:
        n = int(RATE * TEMPO_S * beats)
        if semitone is None:
            out.append(np.zeros(n))
            continue
        t = np.arange(n) / RATE
        f = 440.0 * 2 ** (semitone / 12)
        tone = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)
        attack = np.minimum(1.0, t / 0.008)
        release = np.minimum(1.0, (t[-1] - t) / 0.02 + 1e-3)
        out.append(tone * attack * release * np.exp(-2.5 * t / max(t[-1], 1e-3)))
    x = np.concatenate(out)
    return (x / np.abs(x).max() * LEVEL.get(name, 0.85)).astype(np.float32)


def motif_wav(name, volume=0.9):
    return write_wav(_synth_cached(name) * float(volume), RATE)
