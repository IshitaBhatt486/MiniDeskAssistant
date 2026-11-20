"""
The eyes on the OLED.

    FacePlayer   chooses one of the emotion's 5 hardcoded animations at random, eases between its keyframes
                 (pytweening), adds random blinks and follows the user's position
    draw_face    draws one pose with Pillow
    open_display the real screen (luma.oled) or an in-memory one (luma.core dummy) with the same interface

The screen faces the person, so eyes moving toward the user means moving away from the side of the camera
image the user is on (OledConfig.mirror_gaze).
"""

from __future__ import annotations

import math
import random

import pytweening
from PIL import ImageFont

from .animations import ANIMATIONS, BASE, BLINKS, DEFAULT_POSE, EMOTIONS


def open_display(cfg, simulated=False, log=print):
    """(luma device, description). Falls back to an in-memory display, so the dashboard mirror still works."""
    from luma.core.device import dummy

    if not simulated and cfg.enabled:
        try:
            from luma.core.interface.serial import i2c
            from luma.oled import device as oled

            serial = i2c(port=cfg.port, address=cfg.address)
            driver = {"ssd1306": oled.ssd1306, "sh1106": oled.sh1106}[cfg.driver]
            return driver(serial, width=cfg.width, height=cfg.height, rotate=cfg.rotate), f"{cfg.driver} at {cfg.address:#x}"
        except Exception as exc:
            log(f"OLED not available ({exc}); showing the eyes on the dashboard only")
    return dummy(width=cfg.width, height=cfg.height, mode="1"), "dashboard only"


def _lerp(a, b, f):
    return a + (b - a) * f


class FacePlayer:
    def __init__(self, cfg, rng=None):
        self.cfg = cfg
        self.rng = rng or random.Random()
        self.emotion = "neutral"
        self.name = ""
        self.frames = []
        self.started = 0.0
        self.last_choice = {}
        self.gx = self.gy = 0.0
        self.blink = None
        self.blink_t = 0.0
        self.next_blink = None
        self.next_replay = None
        self.plays = 0
        self.tx = self.ty = self.tvx = self.tvy = 0.0     # eye slide from tilting, with a little slosh
        self.woozy = 0.0

    def invoke(self, emotion, now):
        """Show this emotion: pick one of its animations at random (not the same one twice running).
        Being picked up always starts with the gasp."""
        emotion = emotion if emotion in ANIMATIONS else "neutral"
        options = ANIMATIONS[emotion]
        previous = self.last_choice.get(emotion)
        choice = self.rng.choice([a for a in options if a[0] != previous])
        if emotion == "scared" and self.emotion != "scared":
            choice = next(a for a in options if a[0] == "gasp")
        self.last_choice[emotion] = choice[0]
        self.emotion, self.name, self.frames = emotion, choice[0], choice[1]
        self.started = now
        self.plays += 1
        self.next_replay = now + self.rng.uniform(self.cfg.replay_min_s, self.cfg.replay_max_s)

    def _full(self, keyframe):
        return {**DEFAULT_POSE, **BASE[self.emotion], **keyframe.pose}

    def _animated(self, now):
        frames = self.frames
        if not frames:
            return dict(DEFAULT_POSE), None
        t = (now - self.started) * 1000
        if t >= frames[-1].ms:
            return self._full(frames[-1]), frames[-1].fx
        for a, b in zip(frames, frames[1:]):
            if t < b.ms:
                span = max(1, b.ms - a.ms)
                f = getattr(pytweening, b.ease)(max(0.0, min(1.0, (t - a.ms) / span)))
                pa, pb = self._full(a), self._full(b)
                return {k: _lerp(pa[k], pb[k], f) for k in pa}, a.fx
        return self._full(frames[-1]), None

    def _blink_open(self, now):
        cfg = self.cfg
        if self.next_blink is None:
            self.next_blink = now + self.rng.uniform(cfg.blink_min_s, cfg.blink_max_s)
        if self.blink is None and now >= self.next_blink:
            self.blink, self.blink_t = self.rng.choice(BLINKS), now
        if self.blink is None:
            return 1.0
        t = (now - self.blink_t) * 1000
        for (t0, v0), (t1, v1) in zip(self.blink, self.blink[1:]):
            if t < t1:
                return _lerp(v0, v1, (t - t0) / max(1, t1 - t0))
        self.blink = None
        self.next_blink = now + self.rng.uniform(cfg.blink_min_s, cfg.blink_max_s)
        return 1.0

    def _apply_tilt(self, p, now, roll, pitch):
        """Eyes slide downhill like something loose in a bowl; a big tilt makes the robot woozy."""
        c = self.cfg
        full = math.radians(c.tilt_full_deg)
        goal_x = max(-1.0, min(1.0, roll / full)) * c.tilt_x_px * c.tilt_sign_x
        goal_y = max(-1.0, min(1.0, pitch / full)) * c.tilt_y_px * c.tilt_sign_y
        self.tvx = 0.72 * self.tvx + 0.2 * (goal_x - self.tx)      # under-damped spring: a small overshoot
        self.tvy = 0.72 * self.tvy + 0.2 * (goal_y - self.ty)
        self.tx += self.tvx
        self.ty += self.tvy
        tilt = math.degrees(math.hypot(roll, pitch))
        goal = max(0.0, min(1.0, (tilt - c.woozy_start_deg) / (c.woozy_full_deg - c.woozy_start_deg)))
        self.woozy += (goal - self.woozy) * (0.25 if goal > self.woozy else 0.08)      # recovers slowly
        w = self.woozy
        p["dx"] += self.tx + w * 5.0 * math.sin(now * 3.1)
        p["dy"] += self.ty + w * 3.0 * math.sin(now * 4.3 + 1.0)
        p["left"] *= 1 - w * (0.2 + 0.2 * math.sin(now * 1.7))
        p["right"] *= 1 - w * (0.2 - 0.2 * math.sin(now * 1.7))
        p["lid"] += w * 6.0
        p["lid_out"] += w * 3.0
        return w

    def pose(self, now, gaze_x=0.0, gaze_y=0.0, roll=0.0, pitch=0.0):
        """(pose, fx) for this moment. gaze_x/y: -1..1 in camera-image coordinates; 0 = straight ahead.
        roll, pitch: the body's tilt in radians."""
        cfg = self.cfg
        if self.next_replay is not None and now >= self.next_replay:
            self.invoke(self.emotion, now)
        target_x = (-gaze_x if cfg.mirror_gaze else gaze_x) * cfg.gaze_x_px
        self.gx += (target_x - self.gx) * cfg.gaze_smooth
        self.gy += (gaze_y * cfg.gaze_y_px - self.gy) * cfg.gaze_smooth
        p, fx = self._animated(now)
        p["dx"] += self.gx * p["look"]
        p["dy"] += self.gy * p["look"]
        p["open"] *= self._blink_open(now)
        if self._apply_tilt(p, now, roll, pitch) > 0.4:
            fx = fx or "dizzy"
        return p, fx


_font = None


def _text(draw, xy, s):
    global _font
    _font = _font or ImageFont.load_default()
    draw.text(xy, s, fill="white", font=_font)


def _drop(d, x, y, r=3):
    d.polygon([(x, y - 2 * r), (x - r, y), (x + r, y)], fill="white")
    d.ellipse((x - r, y - r, x + r, y + r), fill="white")


def _draw_fx(d, fx, w, now):
    phase = int(now * 4)
    if fx == "z":
        for i in range(3):
            if phase % 4 >= i:
                _text(d, (w - 26 + i * 8, 16 - i * 6), "z")
    elif fx in ("?", "!"):
        _text(d, (w - 12, 3 + phase % 2), fx)
    elif fx == "heart":
        for x, y in ((6, 8), (w - 14, 8)):
            y -= phase % 2
            d.ellipse((x, y, x + 4, y + 4), fill="white")
            d.ellipse((x + 4, y, x + 8, y + 4), fill="white")
            d.polygon([(x, y + 3), (x + 8, y + 3), (x + 4, y + 9)], fill="white")
    elif fx == "tear":
        _drop(d, 27, 52 + (phase % 3) * 3, 2)
    elif fx == "sweat":
        _drop(d, w - 7, 10 + (phase % 3) * 3, 2)
    elif fx == "spark":
        for x, y in ((6, 8), (w - 8, 10), (w // 2, 5)):
            r = 2 + phase % 2
            d.line((x - r, y, x + r, y), fill="white")
            d.line((x, y - r, x, y + r), fill="white")
    elif fx == "confetti":
        # 14 pieces falling and drifting; position from the piece's index and the clock, so no state is kept
        for i in range(14):
            x = (i * 37 + 9 + int(4 * math.sin(now * 3 + i))) % w
            y = int((now * 26 + i * 23) % 70) - 4
            if i % 3 == 0:
                d.rectangle((x, y, x + 2, y + 1), fill="white")
            elif i % 3 == 1:
                d.point((x, y), fill="white")
                d.point((x + 1, y + 1), fill="white")
            else:
                d.line((x, y, x + 1, y + 2), fill="white")
    elif fx == "dizzy":
        x = w // 2 + (-5, 0, 5, 0)[phase % 4]
        y = 7 + (0, -3, 0, 3)[phase % 4]
        d.ellipse((x - 2, y - 2, x + 2, y + 2), outline="white")


def _eye(d, cx, cy, p, height, inner_on_right):
    w, r = p["w"], p["r"]
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - height / 2, cy + height / 2
    if height < 4:
        d.rounded_rectangle((x0, cy - 1, x1, cy + 1), radius=1, fill="white")
        return
    d.rounded_rectangle((x0, y0, x1, y1), radius=min(r, height / 2, w / 2), fill="white")
    inner, outer = p["lid"] + p["lid_in"], p["lid"] + p["lid_out"]
    left_drop, right_drop = (outer, inner) if inner_on_right else (inner, outer)
    if left_drop > 0.5 or right_drop > 0.5:
        d.polygon([(x0 - 2, y0 - 2), (x1 + 2, y0 - 2), (x1 + 2, y0 + right_drop), (x0 - 2, y0 + left_drop)], fill="black")
    if p["cheek"] > 0.5:
        top = y1 - p["cheek"]
        d.ellipse((x0 - 8, top, x1 + 8, top + height), fill="black")


def draw_face(d, pose, fx=None, width=128, height=64, now=0.0):
    p = pose
    gap = 33 + p["spread"]
    cx, cy = width / 2 + p["dx"], height / 2 + p["dy"]
    base = p["h"] * p["open"]
    _eye(d, cx - gap, cy, p, base * p["left"], True)
    _eye(d, cx + gap, cy, p, base * p["right"], False)
    if fx:
        _draw_fx(d, fx, width, now)


__all__ = ["EMOTIONS", "FacePlayer", "draw_face", "open_display"]
