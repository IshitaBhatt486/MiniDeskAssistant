"""
The planners. All of them solve the same Problem and only ever produce drivable routes
(Costmap.edge_ok / dirmask), so the selector can swap them freely.

    direct          one straight segment. No search at all.
    visibility      shortest any-angle route through the corners of the obstacles (corners are thinned, so
                    near-shortest). Very fast with few obstacles; work grows with the square of the corners.
    theta_star      grid search whose parents may be any visible ancestor: few turns, near-shortest.
    astar           8-connected grid search on the soft cost field: stays away from obstacles and
                    unobserved floor, and it searches every reachable cell, so it finds narrow gaps.
    weighted_astar  A* with an inflated heuristic: expands far fewer cells, route at most w x optimal.
    rrt_connect     two random trees growing toward each other: its work depends little on map size,
                    so it suits long routes across open space when a grid search would be too slow.

No external dependencies: this has to run on the Pi and on a laptop that blocks unsigned DLLs.
"""

from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field

import numpy as np

from .costmap import NEIGHBOURS, Costmap, Target, edt


class Timeout(Exception):
    pass


@dataclass
class Problem:
    cm: Costmap
    start: tuple                # true robot position
    entry: tuple                # where planning starts (= start unless it had to step out of a tight spot)
    entry_idx: int
    target: Target
    goal_list: list             # flat grid indices, every goal cell
    goals: list                 # world points: a spread-out sample, nearest first
    goal_flags: list            # per grid cell: is it a goal?
    h: list                     # per grid cell: straight-line metres to the nearest goal
    rng: random.Random = field(default_factory=random.Random)
    expansions: int = 0


def build_problem(cm: Costmap, start, target: Target):
    """A Problem, or (None, why) when there is nowhere to stop or nowhere to start from."""
    entry = cm.nearest_free(start[0], start[1])
    if entry is None:
        return None, "the robot is boxed in where it stands"
    mask = cm.goal_mask(target)
    if not mask.any():
        return None, "there is no room to stop near it"
    flat = [int(i) for i in mask.ravel().nonzero()[0]]
    # goal samples spread all round the ring (farthest-point sampling), starting from the nearest one:
    # the best stopping place is often on the far side, once obstacles are taken into account
    rows, cols = np.nonzero(mask)
    xy = np.column_stack((cm.X[cols], cm.Y[rows]))
    gap = np.hypot(xy[:, 0] - entry[0], xy[:, 1] - entry[1])
    chosen = [int(np.argmin(gap))]
    gap = np.hypot(xy[:, 0] - xy[chosen[0], 0], xy[:, 1] - xy[chosen[0], 1])
    while len(chosen) < cm.cfg.max_goals and gap.max() >= 2 * cm.res:
        chosen.append(int(np.argmax(gap)))
        gap = np.minimum(gap, np.hypot(xy[:, 0] - xy[chosen[-1], 0], xy[:, 1] - xy[chosen[-1], 1]))
    goals = sorted(((float(xy[i, 0]), float(xy[i, 1])) for i in chosen), key=lambda q: math.dist(q, entry))
    h = (edt(mask) * cm.res).ravel().tolist()
    return Problem(cm, tuple(start), tuple(entry), cm.index(*entry), target, flat, goals, mask.ravel().tolist(), h,
                   random.Random(cm.cfg.seed)), None


def _check(deadline, counter):
    if counter & 255 == 0 and time.perf_counter() > deadline:
        raise Timeout()


def _walk(parent, node):
    out = []
    while node != -1:
        out.append(node)
        node = parent[node]
    out.reverse()
    return out


# ---------------- search on the grid ----------------

def _grid_search(p: Problem, deadline, weight=1.0, soft=True):
    cm, nc, nr = p.cm, p.cm.nc, p.cm.nr
    free, dirs, cost, h, is_goal = cm.free_list, cm.dir_list, cm.cost_list, p.h, p.goal_flags
    res = cm.res
    s = p.entry_idx
    g = {s: 0.0}
    parent = {s: -1}
    heap = [(weight * h[s], s)]
    closed = set()
    while heap:
        _, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        p.expansions += 1
        _check(deadline, p.expansions)
        if is_goal[u]:
            return [cm.centre(i) for i in _walk(parent, u)]
        r, c = divmod(u, nc)
        gu = g[u]
        for k, (dr, dc, length) in enumerate(NEIGHBOURS):
            nrow, ncol = r + dr, c + dc
            if not (0 <= nrow < nr and 0 <= ncol < nc):
                continue
            v = nrow * nc + ncol
            if v in closed or not free[v] or (dirs[v] >> k) & 1:
                continue
            if dr and dc and not (free[r * nc + ncol] and free[nrow * nc + c]):
                continue                  # no cutting corners
            step = length * res
            if soft:
                step *= (cost[u] + cost[v]) / 2
            alt = gu + step
            if alt < g.get(v, math.inf):
                g[v], parent[v] = alt, u
                heapq.heappush(heap, (alt + weight * h[v], v))
    return None


def astar(p, deadline):
    return _grid_search(p, deadline)


def weighted_astar(p, deadline):
    return _grid_search(p, deadline, weight=p.cm.cfg.weighted_astar_w)


def theta_star(p: Problem, deadline):
    cm, nc, nr = p.cm, p.cm.nc, p.cm.nr
    free, dirs, h, is_goal = cm.free_list, cm.dir_list, p.h, p.goal_flags
    res = cm.res
    s = p.entry_idx
    g = {s: 0.0}
    parent = {s: -1}
    heap = [(h[s], s)]
    closed = set()
    while heap:
        _, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        p.expansions += 1
        _check(deadline, p.expansions)
        if is_goal[u]:
            return [cm.centre(i) for i in _walk(parent, u)]
        r, c = divmod(u, nc)
        up = parent[u]
        up_xy = cm.centre(up) if up != -1 else None
        for k, (dr, dc, length) in enumerate(NEIGHBOURS):
            nrow, ncol = r + dr, c + dc
            if not (0 <= nrow < nr and 0 <= ncol < nc):
                continue
            v = nrow * nc + ncol
            if v in closed or not free[v]:
                continue
            best, via = math.inf, -1
            if up_xy is not None:             # try to skip u and come straight from its parent
                vxy = cm.centre(v)
                if cm.edge_ok(*up_xy, *vxy):
                    best, via = g[up] + math.dist(up_xy, vxy), up
            if via == -1:
                if (dirs[v] >> k) & 1 or (dr and dc and not (free[r * nc + ncol] and free[nrow * nc + c])):
                    continue
                best, via = g[u] + length * res, u
            if best < g.get(v, math.inf):
                g[v], parent[v] = best, via
                heapq.heappush(heap, (best + h[v], v))
    return None


# ---------------- continuous planners ----------------

def near_goals(p: Problem):
    """Goal samples about as close as the nearest one. A clear line to the FAR side of the target is not
    a good route: it only means the near side is blocked, and a real planner should look at that."""
    limit = 1.25 * math.dist(p.entry, p.goals[0]) + 0.05
    return [q for q in p.goals if math.dist(p.entry, q) <= limit]


def direct(p: Problem, deadline):
    cm = p.cm
    for q in near_goals(p):
        p.expansions += 1
        if cm.edge_ok(*p.entry, *q):
            return [p.entry, q]
    return None


def visibility(p: Problem, deadline):
    """A* over {start, obstacle corners, goal samples}; an edge is only tested when it could help."""
    cm = p.cm
    nodes = [p.entry] + [cm.centre(i) for i in cm.corners()]
    first_goal = len(nodes)
    nodes += p.goals
    n = len(nodes)
    g = [math.inf] * n
    parent = [-1] * n
    g[0] = 0.0
    h = []
    for x, y in nodes:
        i = cm.index(x, y)
        h.append(p.h[i] if i is not None else 0.0)
    heap = [(h[0], 0)]
    done = [False] * n
    while heap:
        _, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        p.expansions += 1
        if u >= first_goal:
            return [nodes[i] for i in _walk(parent, u)]
        ux, uy = nodes[u]
        for v in range(1, n):
            if done[v]:
                continue
            _check(deadline, v)
            alt = g[u] + math.dist(nodes[u], nodes[v])
            if alt < g[v] and cm.edge_ok(ux, uy, *nodes[v]):
                g[v], parent[v] = alt, u
                heapq.heappush(heap, (alt + h[v], v))
    return None


def rrt_connect(p: Problem, deadline):
    cm, rng = p.cm, p.rng
    step = cm.cfg.rrt_step_m
    free_cells = [i for i, f in enumerate(cm.free_list) if f]
    if not free_cells:
        return None
    a = {"pts": [p.entry], "par": [-1], "forward": True}     # grows away from the robot
    b = {"pts": list(p.goals), "par": [-1] * len(p.goals), "forward": False}   # grows back from the goals

    def ok(tree, frm, to):
        return cm.edge_ok(*frm, *to) if tree["forward"] else cm.edge_ok(*to, *frm)

    def extend(tree, q):
        pts = tree["pts"]
        i = min(range(len(pts)), key=lambda k: (pts[k][0] - q[0]) ** 2 + (pts[k][1] - q[1]) ** 2)
        near = pts[i]
        d = math.dist(near, q)
        if d < 1e-9:
            return i, True
        new = q if d <= step else (near[0] + (q[0] - near[0]) * step / d, near[1] + (q[1] - near[1]) * step / d)
        if not ok(tree, near, new):
            return None, False
        pts.append(new)
        tree["par"].append(i)
        return len(pts) - 1, d <= step

    while True:
        p.expansions += 1
        _check(deadline, p.expansions)
        if rng.random() < cm.cfg.rrt_goal_bias:
            q = rng.choice(b["pts"] if a["forward"] else a["pts"])
        else:
            q = cm.centre(rng.choice(free_cells))
        i, _ = extend(a, q)
        if i is not None:
            target = a["pts"][i]
            while True:                      # the other tree goes as far toward it as it can
                j, reached = extend(b, target)
                if j is None or reached:
                    break
                _check(deadline, len(b["pts"]))
            if j is not None and reached:
                ia, ib = (i, j) if a["forward"] else (j, i)
                fwd, back = (a, b) if a["forward"] else (b, a)
                head = [fwd["pts"][k] for k in _walk(fwd["par"], ia)]
                tail = [back["pts"][k] for k in reversed(_walk(back["par"], ib))]
                return head + tail[1:]
        a, b = b, a


PLANNERS = {"direct": direct, "visibility": visibility, "theta_star": theta_star, "astar": astar,
            "weighted_astar": weighted_astar, "rrt_connect": rrt_connect}
COST_AWARE = {"astar", "weighted_astar"}     # their shortcuts must not undo the safer route


# ---------------- finishing a route ----------------

def _collinear(path):
    out = list(path[:1])
    for i in range(1, len(path) - 1):
        ax, ay = out[-1]
        bx, by = path[i]
        cx, cy = path[i + 1]
        if abs((bx - ax) * (cy - by) - (by - ay) * (cx - bx)) > 1e-9:
            out.append(path[i])
    return out + list(path[-1:])


def shortcut(cm: Costmap, path, keep_cost=False):
    """Greedy string pulling: from each waypoint, jump to the furthest one that can be driven directly.
    keep_cost: a jump must not cost more than the piece it replaces (it may not hug an obstacle)."""
    path = _collinear(path)
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1:
            a, b = path[i], path[j]
            if cm.edge_ok(*a, *b):
                if not keep_cost:
                    break
                old = sum(cm.segment_cost(*path[k], *path[k + 1]) for k in range(i, j))
                if cm.segment_cost(*a, *b) <= old * 1.02:
                    break
            j -= 1
        out.append(path[j])
        i = j
    return out


def route_ok(cm: Costmap, path):
    return all(cm.edge_ok(*path[i], *path[i + 1]) for i in range(len(path) - 1))


def route_length(path):
    return sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))


def route_turning(path, heading=None):
    """Total turning in radians, including the first turn from `heading`."""
    total, last = 0.0, heading
    for i in range(len(path) - 1):
        (ax, ay), (bx, by) = path[i], path[i + 1]
        if math.hypot(bx - ax, by - ay) < 1e-9:
            continue
        a = math.atan2(by - ay, bx - ax)
        if last is not None:
            total += abs((a - last + math.pi) % (2 * math.pi) - math.pi)
        last = a
    return total
