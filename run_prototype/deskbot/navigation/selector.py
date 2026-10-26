"""
Adaptive path planning: measure the problem, then choose the planner that suits it.

Measured for every plan (Features):

    n_obstacles      separate solid things in the planning window
    density          share of the window the robot's centre cannot occupy
    line_clear       can the robot simply drive straight to a stopping place?
    n_on_route       obstacles the straight line would run into
    tight_on_route   gaps on the way that are barely wider than the robot
    unknown_frac     share of the straight corridor nobody has observed
    object_sigma     how uncertain the camera objects' positions are
    distance_m, free_cells, vertices     size of the search
    predicted_ms     expected search time, from the speed MEASURED on this machine

Rules, first match wins:

    1. line clear over floor it has observed        -> direct
    2. grid search predicted over the time budget   -> rrt_connect if the space is open, else weighted_astar
    3. the map can't be trusted on this route       -> astar (its cost field avoids unobserved floor)
    4. tight gap, dense clutter or many obstacles   -> astar (searches every reachable cell)
    5. any-angle search fits the budget             -> theta_star (shortest routes on the test desks, few turns)
    6. few obstacles and few corners                -> visibility (much cheaper, somewhat longer routes)
    7. anything else                                -> astar

The remaining planners follow as fallbacks, so one planner failing or timing out doesn't end the trip.
Every decision records its reasons, which are logged and shown in the status.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import numpy as np

from .costmap import Costmap, Target, edt, label
from .planners import (COST_AWARE, PLANNERS, Problem, Timeout, build_problem, near_goals, route_length, route_ok,
                       route_turning, shortcut)

FALLBACK_ORDER = ["theta_star", "astar", "weighted_astar", "rrt_connect"]
THETA_COST = 12.0    # Theta* does a line-of-sight test per neighbour: measured at about this many times A*'s time


class SearchSpeed:
    """How long a grid expansion really takes here (exponential average). The Pi is several times slower
    than a laptop, and the nav process shares its core with the mapper and web server."""

    def __init__(self, ms_per_1k):
        self.ms_per_1k = ms_per_1k

    def update(self, ms, expansions):
        if expansions >= 100:
            self.ms_per_1k += 0.3 * (ms / expansions * 1000 - self.ms_per_1k)


@dataclass
class Features:
    n_obstacles: int
    density: float
    line_clear: bool
    n_on_route: int
    tight_on_route: int
    unknown_frac: float
    object_sigma: float
    distance_m: float
    free_cells: int
    vertices: int
    resolution_m: float
    predicted_ms: float


@dataclass
class Decision:
    planner: str
    order: list
    reasons: list


@dataclass
class Route:
    ok: bool
    why: str = ""
    planner: str = ""
    path: list = None
    length_m: float = 0.0
    turning_deg: float = 0.0
    drive_s: float = 0.0
    plan_ms: float = 0.0
    expansions: int = 0
    tried: list = None
    features: Features = None
    decision: Decision = None
    cm: Costmap = None              # the grid this route was planned on

    def summary(self):
        return {"ok": self.ok, "why": self.why, "planner": self.planner,
                "length_m": round(self.length_m, 3), "turning_deg": round(self.turning_deg, 1),
                "drive_s": round(self.drive_s, 1), "plan_ms": round(self.plan_ms, 1), "expansions": self.expansions,
                "tried": self.tried or [], "reasons": self.decision.reasons if self.decision else [],
                "features": asdict(self.features) if self.features else None,
                "path": [[round(x, 3), round(y, 3)] for x, y in (self.path or [])]}


def _corridor(cm: Costmap, a, b, half_width):
    gx, gy = np.meshgrid(cm.X, cm.Y)
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy or 1e-9
    t = np.clip(((gx - a[0]) * dx + (gy - a[1]) * dy) / ll, 0.0, 1.0)
    return np.hypot(gx - (a[0] + t * dx), gy - (a[1] + t * dy)) <= half_width


def measure(p: Problem, speed: SearchSpeed) -> Features:
    cm, cfg = p.cm, p.cm.cfg
    goal = p.goals[0]
    distance = math.dist(p.entry, goal)
    free_cells = int((~cm.lethal).sum())
    density = float(cm.lethal.mean())
    labels, n_obstacles = cm.obstacle_clusters()
    target_cells = cm.target_mask(p.target)

    # what the straight line runs into
    corridor = _corridor(cm, p.entry, goal, cm.inflate)
    on_route = {int(v) for v in np.unique(labels[corridor]) if v}

    # A gap is tight if the robot still fits (the obstacles stay apart at its own width) but they join up
    # once a little slack is added. Gaps it can't fit through at all don't count: they are just walls.
    tight = 0
    others = cm.solid & ~(edt(target_cells) * cm.res <= cm.res * 3)   # the robot stops well short of the target
    if others.any():
        solid_dist = edt(others) * cm.res
        body, _ = label(solid_dist < cm.inflate)
        joined, count = label(solid_dist < cm.inflate + cfg.tight_gap_slack_m)
        wide_corridor = _corridor(cm, p.entry, goal, cm.inflate + 2 * cfg.tight_gap_slack_m)
        for blob in range(1, count + 1):
            inside = joined == blob
            if (inside & wide_corridor).any() and len({int(v) for v in np.unique(body[inside]) if v}) >= 2:
                tight += 1

    narrow = _corridor(cm, p.entry, goal, 0.12) & ~cm.lethal
    unknown = float(cm.unknown[narrow].mean()) if narrow.any() else 0.0
    sigmas = [o.sigma for o in cm.objects]
    vertices = len(cm.corners())
    line_clear = any(cm.edge_ok(*p.entry, *q) for q in near_goals(p))
    # A* explores a band around the straight line. The band widens with clutter, with obstacles on the line,
    # and with unobserved floor (its extra cost is invisible to the heuristic). Fitted on the test desks.
    spread = 0.06 + 1.5 * density + (0.15 if len(on_route) > 1 else 0.0) + 0.8 * unknown
    predicted = min(free_cells, (distance / cm.res) ** 2 * spread) * speed.ms_per_1k / 1000
    return Features(n_obstacles, round(density, 3), line_clear, len(on_route), tight, round(unknown, 3),
                    round(float(np.mean(sigmas)) if sigmas else 0.0, 3), round(distance, 3), free_cells, vertices,
                    cm.res, round(predicted, 1))


def choose(f: Features, cfg) -> Decision:
    def pick(name, *why):
        order = [name] + [n for n in FALLBACK_ORDER if n != name]
        return Decision(name, order, list(why))

    if f.line_clear and f.unknown_frac < cfg.uncertain_unknown:
        return pick("direct", "a straight line to the target is clear")
    budget = cfg.time_budget_ms
    if f.predicted_ms > budget:
        why = f"a full grid search would take about {f.predicted_ms:.0f} ms, over the {budget:.0f} ms budget"
        if f.density <= cfg.sparse_density:
            return pick("rrt_connect", why, f"the space is open ({f.density:.0%} blocked), so sampling is efficient")
        return pick("weighted_astar", why, f"{f.density:.0%} of the space is blocked, so it trades path length for speed")
    if f.unknown_frac >= cfg.uncertain_unknown:
        return pick("astar", f"{f.unknown_frac:.0%} of the way has not been observed, so it prefers known floor")
    if f.object_sigma >= cfg.uncertain_sigma_m:
        return pick("astar", f"object positions are uncertain (about {f.object_sigma * 100:.0f} cm), so it keeps extra clearance")
    if f.tight_on_route:
        return pick("astar", f"{f.tight_on_route} tight gap(s) on the way need a complete search")
    if f.density >= cfg.cluttered_density:
        return pick("astar", f"the desk is cluttered ({f.density:.0%} blocked)")
    if f.n_obstacles >= cfg.many_obstacles:
        return pick("astar", f"{f.n_obstacles} obstacles is too many for a corner graph")
    theta_ms = f.predicted_ms * THETA_COST
    if theta_ms <= budget:
        return pick("theta_star", f"{f.n_obstacles} obstacle(s) and time to spare: any-angle search gives the shortest route")
    if f.n_obstacles <= cfg.few_obstacles and f.vertices <= cfg.max_visibility_vertices:
        return pick("visibility", f"any-angle search would take about {theta_ms:.0f} ms, but with only {f.n_obstacles} "
                                  f"obstacle(s) and {f.vertices} corners a corner graph is cheap")
    return pick("astar", f"{f.n_obstacles} obstacles and any-angle search would not fit the time budget")


def run_planner(name, p: Problem, limit_ms):
    """(path or None, status, ms). The path is shortened and re-validated before it is trusted."""
    t0 = time.perf_counter()
    p.expansions = 0
    try:
        raw = PLANNERS[name](p, t0 + limit_ms / 1000)
    except Timeout:
        return None, "timed out", (time.perf_counter() - t0) * 1000
    if raw is None:
        return None, "no route", (time.perf_counter() - t0) * 1000
    path = shortcut(p.cm, raw, keep_cost=name in COST_AWARE) if len(raw) > 2 else raw
    ms = (time.perf_counter() - t0) * 1000
    if not route_ok(p.cm, path):
        return None, "invalid route", ms
    return path, "ok", ms


def plan_route(cm: Costmap, start, heading, target: Target, speed: SearchSpeed | None = None, force=None,
               wheel_speed=0.125, turn_rate=2.08) -> Route:
    """Measure, choose, plan (with fallbacks). `force` runs one named planner (for comparisons)."""
    cfg = cm.cfg
    speed = speed or SearchSpeed(cfg.default_ms_per_1k)
    p, why = build_problem(cm, start, target)
    if p is None:
        return Route(False, why)
    t0 = time.perf_counter()
    features = measure(p, speed)
    decision = Decision(force, [force], ["forced"]) if force else choose(features, cfg)
    tried = []
    for name in decision.order:
        # each planner may overrun its prediction a little; A*, the complete search, gets the long leash
        limit = cfg.hard_limit_ms if name == "astar" or force else cfg.time_budget_ms * 2
        path, status, ms = run_planner(name, p, limit)
        tried.append({"planner": name, "status": status, "ms": round(ms, 1), "expansions": p.expansions})
        if name in ("astar", "weighted_astar", "theta_star"):
            speed.update(ms / (THETA_COST if name == "theta_star" else 1.0), p.expansions)
        if path is None:
            continue
        if p.entry != p.start:
            path = [p.start] + path     # step out of the tight spot first
        length, turning = route_length(path), route_turning(path, heading)
        return Route(True, "", name, path, length, math.degrees(turning), length / wheel_speed + turning / turn_rate,
                     (time.perf_counter() - t0) * 1000, p.expansions, tried, features, decision, cm)
    return Route(False, "no clear route", tried=tried, features=features, decision=decision,
                 plan_ms=(time.perf_counter() - t0) * 1000, cm=cm)


def plan_growing(make_costmap, start, heading, target, speed=None, force=None, wheel_speed=0.125, turn_rate=2.08):
    """Plan on a small window first (fast, fine grid); if that finds nothing, the way round may simply lie
    outside it, so widen the window, finally to the whole map. make_costmap(margin) -> Costmap."""
    route, size = None, None
    for margin in (None, 1.0, 100.0):
        cm = make_costmap(margin)
        if (cm.nr, cm.nc, cm.res) == size:
            continue
        size = (cm.nr, cm.nc, cm.res)
        route = plan_route(cm, start, heading, target, speed, force, wheel_speed, turn_rate)
        if route.ok:
            break
    return route
