"""
Geometric layer: a log-odds occupancy grid whose evidence fades with time.

Each cell stores its log-odds L and the time T it was last updated. The value actually used is

    L_eff(now) = L * exp(-ln2 * (now - T) / half_life)

so evidence halves every `half_life` seconds without a new observation and drifts back to 0
(p = 0.5, "unknown"). Decay is computed lazily, only when a cell is read or written. Nothing
loops over the whole grid on a timer, so an idle map costs nothing. When a cell is updated, its
current decayed value is folded in first and then the new evidence is added (standard additive
log-odds Bayes update), and T is set to now.

Coordinates: metres, origin = robot start pose, x right / y up on the map, grid centred on the origin.
Arrays are indexed [row, col] with row 0 at the bottom (y = -size/2 * res).
"""

from __future__ import annotations

import math

import numpy as np

from ..config import MappingConfig

LN2 = math.log(2.0)


class DecayGrid:
    def __init__(self, cfg: MappingConfig):
        self.cfg = cfg
        self.n = cfg.size
        self.res = cfg.resolution
        self.L = np.zeros((self.n, self.n), np.float32)
        self.T = np.zeros((self.n, self.n), np.float64)
        self.edge = np.zeros((self.n, self.n), bool)       # IR saw a drop here (desk edges don't move)
        self.seen = np.zeros((self.n, self.n), bool)       # ever observed
        self.k = LN2 / cfg.geo_half_life_s
        self.updates = 0

    # -- coordinates --

    def cells(self, xs, ys):
        """World points -> flat cell indices (points outside the grid are dropped)."""
        xs, ys = np.asarray(xs, float), np.asarray(ys, float)
        c = np.floor(xs / self.res).astype(np.int64) + self.n // 2
        r = np.floor(ys / self.res).astype(np.int64) + self.n // 2
        ok = (c >= 0) & (c < self.n) & (r >= 0) & (r < self.n)
        return r[ok] * self.n + c[ok]

    def cell_centres(self):
        """(X, Y) arrays of every cell centre, metres (computed once, then cached: read-only)."""
        if getattr(self, "_centres", None) is None:
            idx = (np.arange(self.n) - self.n // 2 + 0.5) * self.res
            X, Y = np.meshgrid(idx, idx)  # X varies along columns, Y along rows
            X.flags.writeable = Y.flags.writeable = False
            self._centres = (X, Y)
        return self._centres

    # -- updates --

    def add(self, flat_idx, delta, now):
        if len(flat_idx) == 0:
            return
        L, T = self.L.ravel(), self.T.ravel()
        cur = L[flat_idx] * np.exp(-self.k * (now - T[flat_idx]))
        L[flat_idx] = np.clip(cur + delta, self.cfg.l_min, self.cfg.l_max)
        T[flat_idx] = now
        self.seen.ravel()[flat_idx] = True

    def disc(self, x, y, radius):
        """Flat indices of the cells whose centre is within `radius` of (x, y)."""
        steps = int(math.ceil(radius / self.res))
        offs = np.arange(-steps, steps + 1) * self.res
        gx, gy = np.meshgrid(offs, offs)
        keep = gx ** 2 + gy ** 2 <= radius ** 2
        return np.unique(self.cells(x + gx[keep], y + gy[keep]))

    def sonar(self, ox, oy, heading, distance, now, free_delta=None):
        """One ultrasonic reading: a cone of rays, free along each ray and occupied at the hit.

        Cells are collected over all rays first and every cell is updated ONCE per reading
        (a cell crossed by three rays near the sensor is not counted as three observations),
        and cells at the hit arc are never also marked free.
        free_delta overrides the free evidence (a reading with NO echo uses a much weaker value:
        the pulse may have bounced away off an angled or shiny surface)."""
        cfg = self.cfg
        hit = distance < cfg.sonar_max_useful
        rng = min(distance, cfg.sonar_max_useful)
        half = math.radians(cfg.sonar_cone_half_deg)
        angles = heading + np.linspace(-half, half, cfg.sonar_rays) if cfg.sonar_rays > 1 else np.array([heading])
        n = max(2, int(math.ceil(rng / (self.res * 0.5))) + 1)
        t = np.linspace(0.0, rng, n)
        xs = ox + np.outer(np.cos(angles), t)
        ys = oy + np.outer(np.sin(angles), t)
        if hit:
            free = np.unique(self.cells(xs[:, :-1].ravel(), ys[:, :-1].ravel()))
            occ = np.unique(self.cells(xs[:, -1], ys[:, -1]))
            free = np.setdiff1d(free, occ, assume_unique=True)
            self.add(occ, cfg.l_occ, now)
        else:
            free = np.unique(self.cells(xs.ravel(), ys.ravel()))
        self.add(free, cfg.l_free if free_delta is None else free_delta, now)
        self.updates += 1

    def floor(self, x, y, now, radius=0.0):
        idx = self.disc(x, y, radius) if radius > 0 else self.cells([x], [y])
        self.add(idx, self.cfg.l_floor, now)

    def mark_edge(self, x, y):
        idx = self.cells([x], [y])
        self.edge.ravel()[idx] = True
        self.seen.ravel()[idx] = True

    # -- reading --

    def logodds(self, now):
        return self.L * np.exp(-self.k * (now - self.T)).astype(np.float32)

    def age(self, now):
        """Seconds since each cell was last observed (inf if never)."""
        a = now - self.T
        a[~self.seen] = np.inf
        return a
