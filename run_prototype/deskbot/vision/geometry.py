"""
Pinhole camera model for a camera tilted down over a flat desk.

Frames
    robot:  x forward, y left, z up (metres), origin = robot centre on the desk surface
    camera: pixel (u right, v down), optical axis tilted down by `pitch`

A pixel ray is intersected with the desk plane (z = 0). For an object standing on the desk,
the bottom-centre of its bounding box touches the desk, so that pixel gives the object's
position: bearing from the ray direction, range from where it meets the plane.
"""

from __future__ import annotations

import math

from ..config import CameraConfig


class CameraModel:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.fx, self.fy = cfg.fx, cfg.fy
        self.cx, self.cy = cfg.width / 2, cfg.height / 2
        p = math.radians(cfg.pitch_deg)
        self.sp, self.cp = math.sin(p), math.cos(p)

    # -- pixel -> robot frame --

    def bearing(self, u):
        """Horizontal angle (rad, CCW positive = left) of pixel column u, ignoring pitch."""
        return math.atan2(-(u - self.cx), self.fx)

    def ground_point(self, u, v):
        """Robot-frame (x, y) where pixel (u, v) meets the desk, or None if it looks above the horizon."""
        a = (u - self.cx) / self.fx
        b = (v - self.cy) / self.fy
        # ray = forward_axis + a * right_axis + b * down_axis, in the robot frame
        dx = self.cp - b * self.sp
        dy = -a
        dz = -self.sp - b * self.cp
        if dz >= -1e-3:  # parallel to or above the horizon
            return None
        t = self.cfg.height_m / -dz
        return self.cfg.x + dx * t, self.cfg.y + dy * t

    # -- robot frame -> pixel (used by the simulator and the visibility test) --

    def project(self, x, y, z):
        """Pixel (u, v) of a robot-frame point, or None if it is behind the camera."""
        px, py, pz = x - self.cfg.x, y - self.cfg.y, z - self.cfg.height_m
        zc = px * self.cp - pz * self.sp
        if zc <= 1e-3:
            return None
        xc = -py
        yc = -px * self.sp - pz * self.cp
        return self.cx + self.fx * xc / zc, self.cy + self.fy * yc / zc

    def in_view(self, x, y, margin_px=4):
        """True if the desk point (x, y) is inside the image."""
        uv = self.project(x, y, 0.0)
        if uv is None:
            return False
        u, v = uv
        return margin_px <= u <= self.cfg.width - margin_px and margin_px <= v <= self.cfg.height - margin_px

    def half_hfov(self):
        return math.radians(self.cfg.hfov_deg) / 2
