"""
What an object looks like, worked out on the robot: its main colour from the pixels inside its detection box.
Together with the detector's label this answers "what colour is the cup?" without sending a picture anywhere.
"""

from __future__ import annotations

import numpy as np

# upper hue limit (degrees) -> name
HUES = ((15, "red"), (40, "orange"), (70, "yellow"), (165, "green"), (195, "teal"), (255, "blue"), (290, "purple"),
        (340, "pink"), (360, "red"))


def dominant_colour(image, box):
    """Colour name for the central half of `box` (x1, y1, x2, y2) in a BGR image, or None."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy, bw, bh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2, (y2 - y1) / 2
    a, b = int(max(0, cx - bw / 2)), int(min(w, cx + bw / 2 + 1))
    c, d = int(max(0, cy - bh / 2)), int(min(h, cy + bh / 2 + 1))
    crop = image[c:d, a:b]
    if crop.size == 0:
        return None
    bgr = crop.reshape(-1, 3).astype(np.float32)
    blue, green, red = bgr[:, 0], bgr[:, 1], bgr[:, 2]
    value = bgr.max(axis=1)
    delta = value - bgr.min(axis=1)
    sat = np.where(value > 0, delta / np.maximum(value, 1), 0)
    colourful = (sat > 0.25) & (value > 50)
    if colourful.mean() < 0.3:
        v = float(np.median(value))
        return "black" if v < 60 else "white" if v > 185 else "grey"
    r, g, bl, dl, v = red[colourful], green[colourful], blue[colourful], np.maximum(delta[colourful], 1), value[colourful]
    hue = np.where(v == r, ((g - bl) / dl) % 6, np.where(v == g, (bl - r) / dl + 2, (r - g) / dl + 4)) * 60
    limits = np.array([u for u, _ in HUES])
    votes = np.bincount(np.searchsorted(limits, hue % 360), minlength=len(HUES))
    votes[0] += votes[-1]
    votes[-1] = 0
    name = HUES[int(votes.argmax())][1]
    return "brown" if name == "orange" and float(np.median(v)) < 150 else name
