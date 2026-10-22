"""
Shared memory between the four processes: lock-free, zero-copy, no pickling on the hot path.

Everything that is read often (sensor sample, motor state, wheel log, newest camera frame, newest
detections) lives in `multiprocessing.RawArray`s viewed as numpy arrays. A RawArray has no lock and
no pickling: a read is a memcpy of a few hundred bytes (~1-3 us), not a pipe round trip (~50-100 us
for a multiprocessing.Queue). RawArrays are handed to the child processes when they are created.

Consistency: a **sequence lock** (seqlock). Every block has exactly ONE writer process.
    writer:  seq += 1 (odd = writing) -> write the values -> seq += 1 (even = stable)
    reader:  s1 = seq; copy values; s2 = seq; retry if s1 is odd or s1 != s2
Readers never block the writer, and the writer never waits for readers, so a slow web request
can't delay the motor process. (CPython executes many atomic operations between these steps, which
act as memory barriers in practice; the writer side is a single process.)

Blocks
    SeqBlock     named float64 fields (sensor sample, motor status, settings, commands)
    Ring         fixed-size ring of float64 rows (wheel-command log, detection results)
    FrameRing    3 slots of H x W x 3 uint8 images (camera -> dashboard)
"""

from __future__ import annotations

import math
import multiprocessing as mp

import numpy as np

NAN = float("nan")


class SeqBlock:
    """A seqlock-protected record of named float64 fields. One writer, any number of readers."""

    def __init__(self, fields, raw=None):
        self.fields = list(fields)
        self.index = {name: i + 1 for i, name in enumerate(self.fields)}   # [0] is the sequence
        fresh = raw is None
        self.raw = raw if raw is not None else mp.RawArray("d", len(self.fields) + 1)
        self.a = np.frombuffer(self.raw, dtype=np.float64)
        if fresh:
            self.a[1:] = NAN          # "no value yet" (seq stays 0)

    # RawArrays can only be pickled while a child process is being created; rebuild the view after.
    def __getstate__(self):
        return {"fields": self.fields, "raw": self.raw}

    def __setstate__(self, state):
        self.__init__(state["fields"], state["raw"])

    # -- writer --

    def write(self, **values):
        a, idx = self.a, self.index
        a[0] += 1
        for k, v in values.items():
            a[idx[k]] = NAN if v is None else v
        a[0] += 1

    def write_array(self, values, start=0):
        a = self.a
        a[0] += 1
        a[1 + start:1 + start + len(values)] = values
        a[0] += 1

    # -- reader --

    def read_array(self):
        a = self.a
        for _ in range(1000):
            s1 = a[0]
            if s1 % 2:
                continue
            v = a[1:].copy()
            if a[0] == s1:
                return v
        return a[1:].copy()  # writer stuck mid-write (crashed); return what is there

    def read(self):
        """dict of field -> float (NaN for 'no value')."""
        return dict(zip(self.fields, self.read_array().tolist()))

    @property
    def version(self):
        return int(self.a[0]) // 2


def opt(v):
    """NaN -> None (fields that have no value yet)."""
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


class Ring:
    """Ring of `slots` float64 rows of `width` values. One writer. Readers get rows in write order."""

    def __init__(self, slots, width, block=None):
        self.slots, self.width = slots, width
        # layout: [count, row0..., row1..., ...]
        if block is None:
            block = SeqBlock(["count"] + [f"v{i}" for i in range(slots * width)])
            block.a[1] = 0
        self.block = block

    def __getstate__(self):
        return {"slots": self.slots, "width": self.width, "block": self.block}

    def __setstate__(self, s):
        self.__init__(s["slots"], s["width"], s["block"])

    def append(self, row):
        a = self.block.a
        count = int(a[1])
        i = count % self.slots
        a[0] += 1
        a[2 + i * self.width:2 + (i + 1) * self.width] = row
        a[1] = count + 1
        a[0] += 1

    def rows(self):
        """All stored rows, oldest first, as an (n, width) array."""
        v = self.block.read_array()
        count = int(v[0])
        data = v[1:].reshape(self.slots, self.width)
        n = min(count, self.slots)
        if n == 0:
            return data[:0]
        start = count % self.slots if count > self.slots else 0
        order = [(start + k) % self.slots for k in range(n)]
        return data[order]

    @property
    def count(self):
        return int(self.block.a[1])


class FrameRing:
    """Newest camera frames (3 slots, so the writer never overwrites the frame a reader is copying)."""

    def __init__(self, height, width, slots=3, raw=None, meta=None):
        self.h, self.w, self.slots = height, width, slots
        self.size = height * width * 3
        self.raw = raw if raw is not None else mp.RawArray("B", self.size * slots)
        self.images = np.frombuffer(self.raw, dtype=np.uint8).reshape(slots, height, width, 3)
        # meta: latest seq, then (seq, t) per slot
        self.meta = meta or SeqBlock(["latest"] + [f"{k}{i}" for i in range(slots) for k in ("seq", "t")])

    def __getstate__(self):
        return {"h": self.h, "w": self.w, "slots": self.slots, "raw": self.raw, "meta": self.meta}

    def __setstate__(self, s):
        self.__init__(s["h"], s["w"], s["slots"], s["raw"], s["meta"])

    def write(self, seq, t, image):
        i = seq % self.slots
        self.meta.write(**{f"seq{i}": -1})              # slot is being written
        h, w = min(self.h, image.shape[0]), min(self.w, image.shape[1])
        self.images[i, :h, :w] = image[:h, :w]
        self.meta.write(**{"latest": seq, f"seq{i}": seq, f"t{i}": t})

    def read(self, seq=None):
        """(seq, t, image copy) of frame `seq` if still stored, else the newest. None if no frame yet."""
        for _ in range(5):
            m = self.meta.read()
            latest = m["latest"]
            if seq is None and math.isnan(latest):
                return None
            want = int(latest) if seq is None else seq
            if want <= 0:
                return None
            i = want % self.slots
            if m[f"seq{i}"] != want:
                if seq is None:
                    continue
                return self.read(None)
            img = self.images[i].copy()
            if self.meta.read()[f"seq{i}"] == want:   # not overwritten while copying
                return want, m[f"t{i}"], img
        return None
