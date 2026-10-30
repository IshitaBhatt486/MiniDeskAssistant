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
"""

from __future__ import annotations

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


def synth(name):
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
    return write_wav(synth(name) * float(volume), RATE)
