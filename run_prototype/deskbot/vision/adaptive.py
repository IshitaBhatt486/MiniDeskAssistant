"""
When should the (expensive) detector run? Optical flow carries the boxes between detections, which costs about
1-2 ms, so the detector only needs to run when something may have changed.

Sooner: the robot is turning or driving, the picture differs from the last detected frame, or a track was lost.
These act at once, so a new object is not left waiting for the long interval.
Later: while the robot is still and the picture stays the same, the interval grows one frame per detection, up to
detect_max_tracking while objects are being tracked and detect_max_idle when nothing is in view.

The comparison uses every 8th pixel of each row and column (about 1200 values at 320x240).
"""

from __future__ import annotations

import numpy as np


class AdaptiveInterval:
    def __init__(self, vcfg):
        self.fast = max(1, vcfg.detect_min)
        self.normal = max(self.fast, vcfg.detect_every)
        self.max_tracking = vcfg.detect_max_tracking
        self.max_idle = vcfg.detect_max_idle
        self.threshold = vcfg.detect_change
        self.every = self.normal
        self.calm = 0
        self.reference = None
        self.tracks = 0
        self.change = 0.0

    @staticmethod
    def _small(image):
        return image[::8, ::8].mean(axis=2).astype(np.float32)

    def should_detect(self, image, frames_since, n_tracks, moving=False, turning=False):
        small = self._small(image)
        self.change = float(np.abs(small - self.reference).mean()) if self.reference is not None else 255.0
        lost = n_tracks < self.tracks
        self.tracks = n_tracks
        cap = self.fast if turning else self.fast + 1 if moving else None
        if cap is not None:
            self.calm, self.every = 0, min(self.every, cap)
        return frames_since >= self.every or lost or self.change > self.threshold

    def detected(self, image, n_detections, moving=False, turning=False):
        """Call after each detection, with how many objects it found."""
        changed = self.reference is None or self.change > self.threshold
        self.reference = self._small(image)
        self.tracks = n_detections
        self.calm = 0 if changed or moving or turning else self.calm + 1
        limit = self.max_tracking if n_detections else self.max_idle
        base = self.fast if turning else self.fast + 1 if moving else self.normal
        self.every = min(limit, base + self.calm)
        return self.every
