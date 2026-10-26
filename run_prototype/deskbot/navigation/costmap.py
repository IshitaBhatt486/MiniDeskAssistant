"""
The planning grid: what the maps know, restated as "where can this robot actually drive?".

Three layers come from the live maps (read once under the mapper's lock, then planned on without it):

    solid     sonar-occupied cells, camera objects (as discs), anything learned during this trip
    edges     where the IR sensors saw the desk end
    unknown   floor that neither the sonars nor the camera have looked at

From them:

    lethal    closer to something solid than the robot's radius + margin: the centre may not go here
    cone      solid cells widened by the sonar beam: what the FRONT SONAR would hear
    dirmask   per cell and per grid direction: would arriving here heading that way put something
              inside the motor process's stop distance?

The last one matters most. The motor process stops any forward move when the front sonar reads
<= stop_distance (20 cm), so a route that merely avoids collisions can still be undrivable: it may
point the robot at a wall and plan to turn 10 cm before it. Every planner therefore uses `edge_ok`
(or dirmask, its grid form): the segment must be clear AND the sonar's view past its end must be clear.

Coordinates are the map's (metres, origin at the robot's start pose). Grid index = r * nc + c.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from multisonar import SONARS  # dashboard/ (on sys.path via deskbot/__init__)

from ..config import NavigationConfig, object_radius

SONAR_X = SONARS["front"]["x"]
SQRT2 = math.sqrt(2.0)
# (dr, dc, length in cells); the index is the bit used in dirmask
NEIGHBOURS = [(0, 1, 1.0), (1, 0, 1.0), (0, -1, 1.0), (-1, 0, 1.0),
              (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2)]


# ---------------- array helpers ----------------

def edt(mask):
    """Exact Euclidean distance (in cells) from every cell to the nearest True cell.

    Two passes: distance along each column, then the minimum over horizontal offsets dx of
    column_distance(c + dx)^2 + dx^2. Each offset is one numpy operation, and the loop stops as soon as
    dx^2 cannot improve anything, so this stays fast without needing scipy on the Pi."""
    rows, cols = mask.shape
    big = float(rows + cols + 1)
    if not mask.any():
        return np.full(mask.shape, big)
    down = np.empty(mask.shape)
    cur = np.full(cols, big)
    for r in range(rows):
        cur = np.where(mask[r], 0.0, cur + 1.0)
        down[r] = cur
    cur = np.full(cols, big)
    for r in range(rows - 1, -1, -1):
        cur = np.where(mask[r], 0.0, cur + 1.0)
        down[r] = np.minimum(down[r], cur)
    column = np.minimum(down, big) ** 2
    best = column.copy()
    for dx in range(1, cols):
        add = float(dx * dx)
        if add >= best.max():
            break
        best[:, dx:] = np.minimum(best[:, dx:], column[:, :-dx] + add)
        best[:, :-dx] = np.minimum(best[:, :-dx], column[:, dx:] + add)
    return np.sqrt(best)


def shift(a, dr, dc):
    """out[r, c] = a[r + dr, c + dc], False outside the array."""
    out = np.zeros_like(a)
    h, w = a.shape
    out[max(-dr, 0):h + min(-dr, 0), max(-dc, 0):w + min(-dc, 0)] = \
        a[max(dr, 0):h + min(dr, 0), max(dc, 0):w + min(dc, 0)]
    return out


def label(mask):
    """8-connected components: (label array with 0 = background, count)."""
    labels = np.zeros(mask.shape, np.int32)
    h, w = mask.shape
    count = 0
    for r0, c0 in zip(*np.nonzero(mask)):
        if labels[r0, c0]:
            continue
        count += 1
        labels[r0, c0] = count
        stack = [(int(r0), int(c0))]
        while stack:
            r, c = stack.pop()
            for dr, dc, _ in NEIGHBOURS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and mask[nr, nc] and not labels[nr, nc]:
                    labels[nr, nc] = count
                    stack.append((nr, nc))
    return labels, count


# ---------------- a consistent copy of the maps ----------------

@dataclass
class MapObject:
    id: int
    label: str
    x: float
    y: float
    radius: float
    sigma: float
    existence: float


@dataclass
class MapView:
    res: float
    n: int
    L: np.ndarray                  # geometric log-odds, [row, col], row 0 at the bottom
    edge: np.ndarray
    known: np.ndarray
    objects: list
    pose: tuple
    epoch: int = 0


def take_view(mapper):
    """Copy what planning needs. Holds the mapper's lock only for the copy."""
    with mapper._lock:
        now = time.monotonic()
        g = mapper.geo
        known = g.seen.copy()
        cam_t = getattr(mapper, "cam_T", None)
        if cam_t is not None:
            known |= (now - cam_t) < mapper.mcfg.camera_seen_s
        objects = [MapObject(lm.id, lm.label, lm.x, lm.y, object_radius(lm.label),
                             math.sqrt(mapper.sem.variance(lm, now)), mapper.sem.existence(lm, now))
                   for lm in mapper.sem.objects.values()]
        return MapView(g.res, g.n, g.logodds(now), g.edge.copy(), known, objects,
                       (mapper.odom.x, mapper.odom.y, mapper.odom.theta), mapper.epoch)


@dataclass
class Blocker:
    """Something a safety stop taught us during this trip (kept until the trip ends)."""
    x: float
    y: float
    radius: float
    edge: bool = False


@dataclass
class Target:
    """A named place to go: a camera object (disc) or an unlabelled sonar obstacle (cells)."""
    name: str
    x: float
    y: float
    radius: float = 0.0
    object_id: int | None = None
    label: str | None = None
    cells: np.ndarray | None = None    # world points [[x, y], ...] of an unlabelled obstacle
    exact: bool = False                # a place to stand on (home, search spot), not a thing to stop in front of
    extra: dict = field(default_factory=dict)

    def surface_distance(self, x, y):
        if self.cells is not None and len(self.cells):
            return float(np.hypot(self.cells[:, 0] - x, self.cells[:, 1] - y).min())
        return math.hypot(self.x - x, self.y - y) - self.radius

    def nearest_point(self, x, y):
        if self.cells is not None and len(self.cells):
            i = int(np.argmin(np.hypot(self.cells[:, 0] - x, self.cells[:, 1] - y)))
            return float(self.cells[i, 0]), float(self.cells[i, 1])
        return self.x, self.y


# ---------------- the grid ----------------

class Costmap:
    def __init__(self, view: MapView, cfg: NavigationConfig, stop_distance, focus, blockers=(), margin=None, zones=None):
        """focus: world points the window must contain (start, targets, route).
        margin: how far the window extends past them (default cfg.window_margin_m).
        zones: NavMemory.layers(): no-go polygons, places to avoid, known-good corridors."""
        self.zones = zones or {}
        self.view, self.cfg = view, cfg
        self.stop_distance = stop_distance
        half = view.n * view.res / 2
        xs = [p[0] for p in focus]
        ys = [p[1] for p in focus]
        self.margin = m = cfg.window_margin_m if margin is None else margin
        x0, x1 = max(-half, min(xs) - m), min(half, max(xs) + m)
        y0, y1 = max(-half, min(ys) - m), min(half, max(ys) + m)
        self.res = res = cfg.fine_res if max(x1 - x0, y1 - y0) <= cfg.fine_max_window_m else cfg.coarse_res
        self.x0, self.y0 = x0, y0
        self.nc = max(2, int(math.ceil((x1 - x0) / res)))
        self.nr = max(2, int(math.ceil((y1 - y0) / res)))
        self.X = x0 + (np.arange(self.nc) + 0.5) * res
        self.Y = y0 + (np.arange(self.nr) + 0.5) * res

        # distances the motor safety rule imposes
        self.inflate = cfg.robot_radius + cfg.clearance_margin
        self.lookahead = SONAR_X + stop_distance + cfg.brake_margin
        self.cone_pad = max(res, math.tan(math.radians(7.5)) * stop_distance)
        self.standoff = self.lookahead + self.cone_pad + res  # from the target's surface to the robot centre

        self._rasterise(blockers)
        self._derive()

    # -- building --

    def _native(self, a, fill=False):
        """Sample a map-sized array at this grid's cell centres."""
        v = self.view
        ic = np.floor(self.X / v.res).astype(int) + v.n // 2
        ir = np.floor(self.Y / v.res).astype(int) + v.n // 2
        ok_c, ok_r = (ic >= 0) & (ic < v.n), (ir >= 0) & (ir < v.n)
        out = a[np.ix_(np.clip(ir, 0, v.n - 1), np.clip(ic, 0, v.n - 1))]
        if not (ok_c.all() and ok_r.all()):
            out = out.copy()
            out[~ok_r, :] = fill
            out[:, ~ok_c] = fill
        return out

    def disc(self, x, y, radius):
        gx, gy = np.meshgrid(self.X, self.Y)
        return (gx - x) ** 2 + (gy - y) ** 2 <= radius ** 2

    def object_radius(self, ob: MapObject):
        return ob.radius + min(self.cfg.object_sigma_max, self.cfg.object_sigma_k * ob.sigma)

    def _rasterise(self, blockers):
        cfg, v = self.cfg, self.view
        solid = self._native(v.L > cfg.occupied_logodds)
        edges = self._native(v.edge)
        self.unknown = ~self._native(v.known)
        self.objects = [o for o in v.objects if o.existence >= cfg.object_min_logodds]
        for ob in self.objects:
            solid |= self.disc(ob.x, ob.y, self.object_radius(ob))
        for b in blockers:
            if b.edge:
                edges |= self.disc(b.x, b.y, b.radius)
            else:
                solid |= self.disc(b.x, b.y, b.radius)
        gx, gy = np.meshgrid(self.X, self.Y)
        self.nogo = np.zeros(solid.shape, bool)
        for pts in self.zones.get("nogo", ()):
            self.nogo |= self.polygon(gx, gy, pts)
        edges |= self.nogo                    # hard for planning, but the sonar can't hear a drawn zone
        self.solid, self.edges = solid, edges

    @staticmethod
    def polygon(gx, gy, pts):
        """Even-odd point-in-polygon test for every cell."""
        inside = np.zeros(gx.shape, bool)
        for i, (x1, y1) in enumerate(pts):
            x0, y0 = pts[i - 1]
            if y0 == y1:
                continue
            crosses = (y0 > gy) != (y1 > gy)
            inside ^= crosses & (gx < (x1 - x0) * (gy - y0) / (y1 - y0) + x0)
        return inside

    def _derive(self):
        res, cfg = self.res, self.cfg
        hard = self.solid | self.edges
        self.dist = edt(hard) * res
        self.lethal = self.dist < self.inflate
        self.cone = (edt(self.solid) * res) <= self.cone_pad
        prox = np.clip((self.inflate + cfg.proximity_range_m - self.dist) / cfg.proximity_range_m, 0.0, 1.0)
        self.cost = 1.0 + cfg.proximity_cost * prox ** 2 + cfg.unknown_cost * self.unknown
        for x, y in self.zones.get("avoid", ()):
            self.cost[self.disc(x, y, 0.08)] += 2.0
        corridor = self.zones.get("corridor", ())
        if len(corridor):                     # costs must stay >= 1, so other floor costs more instead
            known = np.zeros(self.cost.shape, bool)
            for x, y in corridor:
                cell = self.cell(x, y)
                if cell is not None:
                    known[cell] = True
            if known.any():
                self.cost[edt(known) * res > 0.05] += 0.3

        mask = np.zeros(self.lethal.shape, np.uint8)
        for k, (dr, dc, length) in enumerate(NEIGHBOURS):
            steps = max(1, int(math.ceil(self.lookahead / (res * length))))
            hit = np.zeros_like(self.cone)
            cur = self.cone
            for _ in range(steps):
                cur = shift(cur, dr, dc)
                hit |= cur
            mask[hit] |= 1 << k
        self.dirmask = mask
        # plain lists: indexing them is several times faster than numpy in the search loops
        self.free_list = (~self.lethal).ravel().tolist()
        self.cone_list = self.cone.ravel().tolist()
        self.cost_list = self.cost.ravel().tolist()
        self.dir_list = mask.ravel().tolist()

    # -- coordinates --

    def cell(self, x, y):
        c = int(math.floor((x - self.x0) / self.res))
        r = int(math.floor((y - self.y0) / self.res))
        return (r, c) if 0 <= r < self.nr and 0 <= c < self.nc else None

    def index(self, x, y):
        cell = self.cell(x, y)
        return None if cell is None else cell[0] * self.nc + cell[1]

    def centre(self, idx):
        r, c = divmod(idx, self.nc)
        return float(self.X[c]), float(self.Y[r])

    # -- what may be driven --

    def is_free(self, x, y):
        i = self.index(x, y)
        return i is not None and self.free_list[i]

    def segment_free(self, ax, ay, bx, by):
        d = math.hypot(bx - ax, by - ay)
        n = int(d / (self.res * 0.5)) + 1
        for i in range(n + 1):
            f = i / n
            k = self.index(ax + (bx - ax) * f, ay + (by - ay) * f)
            if k is None or not self.free_list[k]:
                return False
        return True

    def body_clear(self, ax, ay, bx, by):
        """Looser than segment_free: only the robot's body has to fit, without the planning margin."""
        d = math.hypot(bx - ax, by - ay)
        n = int(d / (self.res * 0.5)) + 1
        for i in range(n + 1):
            f = i / n
            cell = self.cell(ax + (bx - ax) * f, ay + (by - ay) * f)
            if cell is not None and self.dist[cell] < self.cfg.robot_radius:
                return False
        return True

    def sonar_clear_after(self, ax, ay, bx, by):
        """Driving a->b: would the front sonar hear something inside the stop distance?"""
        d = math.hypot(bx - ax, by - ay)
        if d < 1e-9:
            return True
        ux, uy = (bx - ax) / d, (by - ay) / d
        n = int(self.lookahead / (self.res * 0.5)) + 1
        for i in range(1, n + 1):
            s = self.lookahead * i / n
            k = self.index(bx + ux * s, by + uy * s)
            if k is not None and self.cone_list[k]:
                return False
        return True

    def edge_ok(self, ax, ay, bx, by):
        return self.segment_free(ax, ay, bx, by) and self.sonar_clear_after(ax, ay, bx, by)

    def segment_cost(self, ax, ay, bx, by):
        d = math.hypot(bx - ax, by - ay)
        n = int(d / self.res) + 1
        total = 0.0
        for i in range(n + 1):
            f = i / n
            k = self.index(ax + (bx - ax) * f, ay + (by - ay) * f)
            total += self.cost_list[k] if k is not None else 10.0
        return total / (n + 1) * d

    def nearest_free(self, x, y, within=0.2):
        """The closest drivable cell centre (for a start pose that drifted too close to something)."""
        if self.is_free(x, y):
            return x, y
        gx, gy = np.meshgrid(self.X, self.Y)
        d = np.hypot(gx - x, gy - y)
        d[self.lethal] = np.inf
        i = int(np.argmin(d))
        return self.centre(i) if d.ravel()[i] <= within else None

    # -- targets --

    def target_mask(self, t: Target):
        if t.cells is not None and len(t.cells):
            mask = np.zeros(self.lethal.shape, bool)
            for x, y in t.cells:
                cell = self.cell(float(x), float(y))
                if cell is not None:
                    mask[cell] = True
            return mask
        return self.disc(t.x, t.y, max(t.radius, self.res))

    def stop_ring(self, t: Target):
        return 0.0 if t.exact else self.standoff

    def goal_mask(self, t: Target):
        """Free cells on the ring where the robot can stop, facing the target, sonar limit respected."""
        if t.exact:
            return self.disc(t.x, t.y, max(self.cfg.arrive_slack_m * 0.9, 1.5 * self.res)) & ~self.lethal
        d = edt(self.target_mask(t)) * self.res
        band = max(self.cfg.goal_band_m, 1.5 * self.res)
        return (d >= self.standoff) & (d <= self.standoff + band) & ~self.lethal

    # -- description for the selector --

    def obstacle_clusters(self):
        """(labels, count) of separate solid things in the window (touching cells merged)."""
        near = (edt(self.solid) * self.res) <= self.res * 1.5 if self.solid.any() else self.solid
        return label(near)

    def corners(self):
        """Convex corners of the lethal region, thinned: the vertices of the visibility graph."""
        free = ~self.lethal
        found = np.zeros_like(free)
        for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            found |= free & shift(self.lethal, dr, dc) & shift(free, dr, 0) & shift(free, 0, dc)
        keep, taken = [], np.zeros_like(free)
        rad = 1
        for r, c in zip(*np.nonzero(found)):
            if taken[r, c]:
                continue
            keep.append(int(r) * self.nc + int(c))
            taken[max(0, r - rad):r + rad + 1, max(0, c - rad):c + rad + 1] = True
        return keep
