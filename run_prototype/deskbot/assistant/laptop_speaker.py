"""
The laptop as the robot's speaker (21 Nov 2026), until a real speaker + amplifier is wired to the Pi.

Everything the robot would play (replies, alerts, chatter, chimes) becomes a numbered WAV clip in a short
queue here. Any browser with the dashboard open (or /speaker) asks for new clips and plays them in order:

    GET /api/speaker/clips?after=<id>&wait=20&listener=<tab id>
        -> {"clips": [{"id", "kind", "text", "duration"}], "latest", "interrupt", "output", "listeners"}
           Long poll: answers at once when there are newer clips, otherwise after up to `wait` seconds.
           after=-1 returns no clips, only "latest" (a page that just opened doesn't replay old speech).
    GET /api/speaker/clip/<id>.wav      the clip itself
    GET /speaker                        a page that only does this (leave it open in a laptop tab)

Where sound goes is the assistant setting `speaker_output`: laptop (default for now) | robot | both.
The environment variable DESKBOT_SPEAKER (same values) overrides it, e.g. once the speaker is wired.

Docs: docs/laptop-speaker.md
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

OUTPUTS = ("laptop", "robot", "both")
KEEP_CLIPS = 24                   # newest clips kept (~1-2 minutes of speech); older ones are dropped
LISTENER_TIMEOUT_S = 45.0         # a tab that hasn't asked for this long is gone (a long poll is 20 s)
MAX_WAIT_S = 25.0


def output_from_env():
    value = os.environ.get("DESKBOT_SPEAKER", "").strip().lower()
    return value if value in OUTPUTS else None


def wav_duration(wav: bytes) -> float:
    """Seconds of audio in a PCM WAV (header fields), 0 if it can't be read."""
    try:
        import io
        import wave
        with wave.open(io.BytesIO(wav)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


class LaptopSpeaker:
    def __init__(self, keep=KEEP_CLIPS):
        self._clips = deque(maxlen=keep)      # (id, kind, text, wav, duration)
        self._cond = threading.Condition()
        self._next_id = 1
        self.interrupts = 0                   # bumped by interrupt(): browsers stop what they're playing
        self._listeners = {}                  # tab id -> last time it asked
        self.pushed = 0

    # -- robot side --

    def push(self, wav: bytes, kind="reply", text=""):
        duration = wav_duration(wav)
        with self._cond:
            cid = self._next_id
            self._next_id += 1
            self._clips.append((cid, kind, text[:200], wav, duration))
            self.pushed += 1
            self._cond.notify_all()
        return cid, duration

    def interrupt(self):
        with self._cond:
            self.interrupts += 1
            self._clips.clear()               # queued clips must not start after "stop"
            self._cond.notify_all()

    def listeners(self):
        now = time.monotonic()
        with self._cond:
            for tab in [t for t, seen in self._listeners.items() if now - seen > LISTENER_TIMEOUT_S]:
                del self._listeners[tab]
            return len(self._listeners)

    # -- browser side --

    def latest(self):
        return self._next_id - 1

    def wait_clips(self, after: int, wait: float = 20.0, listener: str = "", interrupt_seen: int = -1):
        """Clips newer than `after`; blocks up to `wait` s for one (or for an interrupt the tab hasn't seen)."""
        wait = max(0.0, min(float(wait), MAX_WAIT_S))
        deadline = time.monotonic() + wait
        with self._cond:
            if listener:
                self._listeners[listener[:40]] = time.monotonic()
            if after >= 0:
                while (not any(c[0] > after for c in self._clips)
                       and not (0 <= interrupt_seen < self.interrupts)):
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    self._cond.wait(left)
            clips = [] if after < 0 else [{"id": c[0], "kind": c[1], "text": c[2], "duration": round(c[4], 2)}
                                          for c in self._clips if c[0] > after]
            if listener:
                self._listeners[listener[:40]] = time.monotonic()
            return {"clips": clips, "latest": self._next_id - 1, "interrupt": self.interrupts}

    def clip(self, cid: int):
        with self._cond:
            for c in self._clips:
                if c[0] == cid:
                    return c[3]
        return None

    def status(self):
        return {"listeners": self.listeners(), "pushed": self.pushed, "latest": self.latest()}
