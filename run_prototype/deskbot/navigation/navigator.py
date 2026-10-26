"""
Carrying out "go from the cup to the bottle".

    1. Find the named things on the map. If one is missing, look around once and try again.
    2. For each leg (robot -> first obstacle -> second obstacle):
         build the planning grid from the current maps, let the selector pick a planner, plan
         turn + short forward hops along the route, re-checking the pose and the map after every hop
         replan if the route stops being drivable, the target moves, or a safety rule stops the robot
    3. Stop on the ring around the target, facing it, just outside the sonar stop distance.

It only moves through robot.move(), so the motor process keeps applying every safety rule. Planning happens
while the robot stands still. Runs on the executor's worker thread and honours its cancel signal.
"""

from __future__ import annotations

import math
import re
import time

import numpy as np

from ..config import NavigationConfig
from ..runtime import behaviour as motion
from ..runtime.shared import STATES
from .costmap import SONAR_X, Blocker, Costmap, MapObject, Target, label, take_view
from .memory import NavMemory
from .planners import route_ok
from .selector import SearchSpeed, plan_growing

SYNONYMS = {
    "mug": "cup", "glass": "cup", "coffee": "cup", "coffee cup": "cup", "tea cup": "cup", "teacup": "cup",
    "water bottle": "bottle", "flask": "bottle", "phone": "cell phone", "mobile": "cell phone",
    "mobile phone": "cell phone", "cellphone": "cell phone", "smartphone": "cell phone", "notebook": "book",
    "computer": "laptop", "plant": "potted plant", "monitor": "tv", "screen": "tv", "television": "tv",
    "user": "person", "owner": "person", "teddy": "teddy bear",
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
IR_OFFSET = 0.07
HOME_NAMES = {"home", "home base", "base", "dock", "charger", "your home", "parking spot"}


def clean_name(text):
    t = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    t = re.sub(r"\b(the|a|an|my|that|this|please|one over there|over there)\b", " ", t)
    return " ".join(t.split())


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def unlabelled_obstacles(view, cfg):
    """Sonar obstacles no camera object explains, nearest first: [{"name", "x", "y", "cells"}]."""
    solid = view.L > cfg.occupied_logodds
    if not solid.any():
        return []
    idx = (np.arange(view.n) - view.n // 2 + 0.5) * view.res
    gx, gy = np.meshgrid(idx, idx)
    for ob in view.objects:
        if ob.existence >= cfg.object_min_logodds:
            solid &= np.hypot(gx - ob.x, gy - ob.y) > ob.radius + 2 * view.res
    labels, count = label(solid)
    x, y, _ = view.pose
    out = []
    for k in range(1, count + 1):
        mask = labels == k
        cells = np.column_stack((gx[mask], gy[mask]))
        out.append({"x": float(cells[:, 0].mean()), "y": float(cells[:, 1].mean()), "cells": cells,
                    "d": float(np.hypot(cells[:, 0] - x, cells[:, 1] - y).min())})
    out.sort(key=lambda o: o["d"])
    for i, o in enumerate(out, 1):
        o["name"] = f"obstacle {i}"
    return out


def _object_target(ob: MapObject):
    return Target(ob.label, ob.x, ob.y, ob.radius, ob.id, ob.label)


def _cluster_target(c):
    return Target(c["name"], c["x"], c["y"], cells=c["cells"])


def find_target(view, cfg, name, near=None, exclude=None):
    """The thing called `name`, or None. With several matches: the one nearest to `near`."""
    want = clean_name(name)
    if not want:
        return None
    x, y = near or view.pose[:2]
    objects = [o for o in view.objects if o.existence >= cfg.object_min_logodds]
    if exclude is not None:
        objects = [o for o in objects if o.id != exclude.object_id]
    clusters = unlabelled_obstacles(view, cfg)
    if exclude is not None:
        clusters = [c for c in clusters if math.hypot(c["x"] - exclude.x, c["y"] - exclude.y) > 0.1]

    m = re.fullmatch(r"(nearest|closest|farthest|furthest)( obstacle| object| thing)?", want) \
        or re.fullmatch(r"(?:obstacle|object|thing) (nearest|closest|farthest|furthest)", want)
    if m:
        options = [(math.hypot(o.x - x, o.y - y) - o.radius, _object_target(o)) for o in objects]
        options += [(float(np.hypot(c["cells"][:, 0] - x, c["cells"][:, 1] - y).min()), _cluster_target(c)) for c in clusters]
        if not options:
            return None
        pick = max if m.group(1) in ("farthest", "furthest") else min
        return pick(options, key=lambda o: o[0])[1]

    m = re.fullmatch(r"obstacle (\d+|" + "|".join(NUMBER_WORDS) + ")", want)
    if m:
        n = NUMBER_WORDS.get(m.group(1)) or int(m.group(1))
        return next((_cluster_target(c) for c in clusters if c["name"] == f"obstacle {n}"), None)
    if want == "obstacle":
        return _cluster_target(clusters[0]) if clusters else None

    wanted = {want, SYNONYMS.get(want, want)}
    if want.endswith("s"):
        wanted |= {want[:-1], SYNONYMS.get(want[:-1], want[:-1])}
    hits = [o for o in objects if o.label in wanted]
    return _object_target(min(hits, key=lambda o: math.hypot(o.x - x, o.y - y))) if hits else None


class Navigator:
    def __init__(self, robot, mapper, cfg: NavigationConfig | None = None, say=None, behaviour=None, memory=None):
        self.robot, self.mapper = robot, mapper
        self.cfg = cfg or NavigationConfig()
        self._say = say
        self.behaviour = behaviour
        self.speed = SearchSpeed(self.cfg.default_ms_per_1k)
        self.memory = memory or NavMemory()
        self.listeners = []            # fn(event): recognised, navigating, arrived, not_found, low_confidence, failed
        self.hop = self.cfg.hop_m
        self.state = {"phase": "idle"}
        self.history = []              # one entry per plan of the current trip
        self.blockers = []
        self.epoch = 0
        self._warned_low = False
        self._scanned = False
        self._deadline = math.inf

    # -- small helpers (the first three are replaced in tests) --

    def view(self):
        return take_view(self.mapper)

    def pose(self):
        with self.mapper._lock:
            o = self.mapper.odom
            return o.x, o.y, o.theta

    def _wait_for_map(self):
        """Let the mapper integrate the end of the last move, so the pose is current."""
        before = self.mapper.updates
        end = time.monotonic() + self.cfg.map_settle_s
        while self.mapper.updates < before + 2 and time.monotonic() < end:
            time.sleep(0.01)

    def emit(self, event):
        for fn in self.listeners:
            try:
                fn(event)
            except Exception as exc:
                self.log("warn", f"Navigation listener failed: {exc}")

    def say(self, text, kind="chatter"):
        if self._say:
            try:
                self._say(text, kind)
            except Exception as exc:
                self.log("warn", f"Could not speak: {exc}")

    def log(self, level, msg):
        self.robot.log(level, f"[nav] {msg}")

    def _linear_speed(self):
        return max(1e-3, self.robot.speed * motion.WHEEL_SPEED_AT_FULL)

    def _turn_rate(self):
        return max(1e-3, motion.turn_rate(self.robot.speed))

    def status(self):
        return {**self.state, "plans": self.history[-6:]}

    def known_obstacles(self):
        """Names the user can ask for right now (for the AI's context and the status)."""
        v = self.view()
        names = sorted({o.label for o in v.objects if o.existence >= self.cfg.object_min_logodds})
        extra = [{"name": c["name"], "distance_m": round(c["d"], 2)} for c in unlabelled_obstacles(v, self.cfg)[:6]]
        return {"objects": names, "unlabelled": extra}

    # -- motion primitives --

    def _command(self, direction, seconds, cancelled):
        """None when the move finished, else "cancelled" / "blocked" / a problem."""
        seconds = max(0.03, min(seconds, 10.0))
        self.robot.move(direction, round(seconds, 3))
        time.sleep(self.cfg.command_settle_s)
        end = time.monotonic() + seconds + 3.0
        while time.monotonic() < end:
            if cancelled():
                self.robot.stop()
                return "cancelled"
            state = self.robot.snapshot()["state"]
            if state == "blocked":
                return "blocked"
            if state == "error":
                return "the motors reported an error"
            if state != "moving":
                self._wait_for_map()
                return None
            time.sleep(0.04)
        self.robot.stop()
        return "the move timed out"

    def _turn(self, angle, cancelled):
        return self._command("left" if angle > 0 else "right", abs(angle) / self._turn_rate(), cancelled)

    def _forward(self, metres, cancelled):
        return self._command("forward", metres / self._linear_speed(), cancelled)

    def _blocked_kind(self, direction):
        """Which safety rule stopped us, from the sensors (the log text can arrive later)."""
        r = self.robot.latest_reading()
        d = r.get("distances") or {}
        limit = self.robot.stop_distance + 0.02
        if direction == "backward":
            return "rear"
        if direction != "forward":
            return "turn_edge" if r.get("front_floor") is False or r.get("back_floor") is False else "side"
        if r.get("front_floor") is False:
            return "front_edge"
        front = d.get("front", r.get("distance"))
        return "front_obstacle" if front is not None and front <= limit else "sensors"

    def _remember_stop(self, kind):
        """Put what stopped us into this trip's map, so the next plan avoids it."""
        x, y, th = self.pose()
        c, s = math.cos(th), math.sin(th)
        if kind == "front_obstacle":
            r = self.robot.latest_reading()
            d = (r.get("distances") or {}).get("front", r.get("distance")) or self.robot.stop_distance
            reach = SONAR_X + d
            self.blockers.append(Blocker(x + reach * c, y + reach * s, 0.03))
            self.memory.add_avoid(x + reach * c, y + reach * s)
        elif kind == "front_edge":
            ex, ey = x + IR_OFFSET * c, y + IR_OFFSET * s
            for t in np.arange(-0.15, 0.151, 0.05):      # the desk edge is a line across our path
                self.blockers.append(Blocker(ex - s * t, ey + c * t, 0.03, edge=True))
            self.memory.add_avoid(ex, ey)

    def _recover(self, kind, cancelled):
        """After a safety stop: remember why and make room, so the robot can turn again."""
        self._remember_stop(kind)
        if kind in ("front_edge", "side", "turn_edge"):
            r = self.robot.latest_reading()
            direction = "forward" if r.get("back_floor") is False and r.get("front_floor") is not False else "backward"
            why = self._command(direction, self.cfg.backoff_m / self._linear_speed(), cancelled)
            if why == "cancelled":
                return why
        return None

    # -- planning --

    def _costmap(self, view, pose, target, margin=None, route=()):
        focus = [pose[:2], (target.x, target.y), *route]
        return Costmap(view, self.cfg, self.robot.stop_distance, focus, self.blockers, margin, self.memory.layers())

    def _plan(self, target):
        view = self.view()
        pose = view.pose
        fresh = self._refresh(view, target)
        cm = self._costmap(view, pose, fresh)
        if fresh.surface_distance(*pose[:2]) <= cm.stop_ring(fresh) + self.cfg.arrive_slack_m:
            return view, cm, fresh, None
        route = plan_growing(lambda margin: self._costmap(view, pose, fresh, margin), pose[:2], pose[2], fresh, self.speed,
                             wheel_speed=self._linear_speed(), turn_rate=self._turn_rate())
        cm = route.cm or cm
        info = route.summary()
        info["target"] = fresh.name
        info["confidence"] = self._confidence(view, fresh, route)
        self.history.append(info)
        self.state = {**self.state, "planner": route.planner, "reasons": info["reasons"], "path": info["path"],
                      "features": info["features"], "route_m": info["length_m"], "confidence": info["confidence"]}
        low = route.ok and info["confidence"] < self.cfg.low_confidence
        self.hop = self.cfg.hop_m / 2 if low else self.cfg.hop_m
        if low and not self._warned_low:
            self._warned_low = True
            self.emit("low_confidence")
            self.say("I'm not very sure about this route, so I'll take it carefully.")
        if route.ok:
            f = route.features
            self.log("info", f"to {fresh.name}: {route.planner} ({f.n_obstacles} obstacles, {f.density:.0%} blocked, "
                             f"{route.length_m * 100:.0f} cm, planned in {route.plan_ms:.0f} ms): {'; '.join(route.decision.reasons)}")
        else:
            self.log("warn", f"to {fresh.name}: no route ({route.why})")
        return view, cm, fresh, route

    def _confidence(self, view, target, route):
        """0-1: is the target really there, is its position known, has the way been observed?"""
        seen, sigma = 0.85, 0.02
        if target.exact:
            seen = 1.0
        for o in view.objects:
            if o.id == target.object_id:
                seen, sigma = 1 / (1 + math.exp(-o.existence)), o.sigma
        unknown = route.features.unknown_frac if route.features else 0.5
        return round(seen * (1 - 0.6 * unknown) / (1 + sigma / 0.1), 3)

    def _refresh(self, view, target):
        """The same target as the map sees it now (objects drift as better sightings arrive)."""
        if target.object_id is not None:
            for o in view.objects:
                if o.id == target.object_id:
                    return _object_target(o)
            same = [o for o in view.objects if o.label == target.label
                    and o.existence >= self.cfg.object_min_logodds and math.hypot(o.x - target.x, o.y - target.y) < 0.2]
            return _object_target(same[0]) if same else target
        if target.cells is not None:
            options = unlabelled_obstacles(view, self.cfg)
            near = [c for c in options if math.hypot(c["x"] - target.x, c["y"] - target.y) < 0.15]
            if near:
                best = min(near, key=lambda c: math.hypot(c["x"] - target.x, c["y"] - target.y))
                return Target(target.name, best["x"], best["y"], cells=best["cells"])
        return target

    # -- following a route --

    def _still_good(self, route, index, target):
        """Re-check the rest of the route on a fresh copy of the map. "" = fine, else why not."""
        view = self.view()
        if view.epoch != self.epoch:
            return "the map was reset"
        pose = view.pose
        now = self._refresh(view, target)
        if math.hypot(now.x - target.x, now.y - target.y) > self.cfg.target_moved_m:
            return "target moved"
        cm = self._costmap(view, pose, now, route.cm.margin, route.path[index:])
        ahead = route.path[index]
        # the robot is never exactly on the line, so its own next piece only has to keep the body clear;
        # the pieces after that were planned from exact points and must still pass the full check
        if not cm.body_clear(*pose[:2], *ahead) or not cm.sonar_clear_after(*pose[:2], *ahead):
            return "the way ahead changed"
        return "" if route_ok(cm, route.path[index:]) else "the way ahead changed"

    def _off_route(self, pose, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ll = dx * dx + dy * dy
        if ll < 1e-9:
            return False
        t = max(0.0, min(1.0, ((pose[0] - a[0]) * dx + (pose[1] - a[1]) * dy) / ll))
        return math.hypot(pose[0] - (a[0] + t * dx), pose[1] - (a[1] + t * dy)) > self.cfg.max_deviation_m

    def _follow(self, route, target, standoff, cancelled):
        """"arrived" | "replan" | ("stop", why)."""
        cfg = self.cfg
        if cfg.smooth_driving and hasattr(self.robot, "drive") and hasattr(self.robot, "motor_state"):
            return self._follow_smooth(route, target, standoff, cancelled)
        tol = math.radians(cfg.heading_tol_deg)
        stuck = 0
        for index in range(1, len(route.path)):
            wp = route.path[index]
            last = index == len(route.path) - 1
            for _ in range(60):
                if cancelled():
                    self.robot.stop()
                    return "stop", "cancelled"
                if time.monotonic() > self._deadline:
                    return "stop", "it was taking too long"
                x, y, th = self.pose()
                if last and target.surface_distance(x, y) <= standoff + cfg.arrive_slack_m:
                    return "arrived"
                dist = math.hypot(wp[0] - x, wp[1] - y)
                if dist <= cfg.waypoint_tol_m:
                    break
                if self._off_route((x, y), route.path[index - 1], wp) and index > 1:
                    return "replan"
                err = wrap(math.atan2(wp[1] - y, wp[0] - x) - th)
                direction = "forward"
                if abs(err) > tol:
                    direction = "left" if err > 0 else "right"
                    why = self._turn(err, cancelled)
                else:
                    why = self._forward(min(self.hop, dist), cancelled)
                if why == "blocked":
                    kind = self._blocked_kind(direction)
                    if kind == "front_obstacle" and last and \
                            target.surface_distance(*self.pose()[:2]) <= standoff + 2 * cfg.arrive_slack_m:
                        return "arrived"          # what stopped us is the thing we came to
                    self.log("info", f"safety stop ({kind}), finding another way")
                    if self._recover(kind, cancelled) == "cancelled":
                        return "stop", "cancelled"
                    return "replan"
                if why:
                    return "stop", why
                nx, ny, nth = self.pose()
                moved = math.hypot(nx - x, ny - y) + abs(wrap(nth - th))
                stuck = stuck + 1 if moved < 0.005 else 0
                if stuck >= 4:
                    return "stop", "I don't seem to be moving"
                if direction == "forward":
                    self.memory.visit(nx, ny)
                    problem = self._still_good(route, index, target)
                    if problem == "the map was reset":
                        return "stop", problem
                    if problem:
                        self.log("info", f"{problem}: replanning")
                        return "replan"
            else:
                return "replan"
        x, y, _ = self.pose()
        return "arrived" if target.surface_distance(x, y) <= standoff + 2 * cfg.arrive_slack_m else "replan"

    def _wheels_for(self, err, dist, last, front):
        """Wheel commands (left, right) that curve toward the waypoint and ease off near obstacles."""
        cfg = self.cfg
        speed = self.robot.speed
        v = 0.0 if abs(err) > math.radians(cfg.spin_above_deg) else speed * max(0.0, math.cos(err)) ** 2
        if last:
            v *= min(1.0, 0.4 + dist / 0.25)
        margin = None if front is None else front - self.robot.stop_distance
        if margin is not None:
            v *= max(0.35, min(1.0, margin / 0.2))
        if self.hop < cfg.hop_m:
            v *= 0.6                                  # low confidence: go gently
        per_rad = motion.TRACK_WIDTH / (2 * motion.WHEEL_SPEED_AT_FULL)
        w = max(-speed, min(speed, cfg.heading_gain * err * per_rad))
        if v == 0.0:
            w = math.copysign(max(abs(w), 0.6 * speed), err)
        return v, w, margin

    def _steer_clear(self, w, margin, last):
        """Something is close ahead: bend toward the side with more room instead of waiting to be stopped."""
        cfg = self.cfg
        if margin is None or last or margin >= cfg.avoid_zone_m:
            return w
        d = self.robot.latest_reading().get("distances") or {}
        side = 1.0 if (d.get("left") or 0.0) >= (d.get("right") or 0.0) else -1.0
        return w + side * self.robot.speed * 0.6 * (1 - max(0.0, margin) / cfg.avoid_zone_m)

    def _state(self):
        m = self.robot.motor_state()
        return None if m["state"] != m["state"] else STATES[int(m["state"])]

    def _follow_smooth(self, route, target, standoff, cancelled):
        """Continuous curves with ramped wheel commands. The motor process still applies every safety rule, and
        stops the wheels by itself if these commands stop arriving."""
        cfg = self.cfg
        path = route.path
        index, left, right = 1, 0.0, 0.0
        tick, sent, last_check, last_visit = 0.05, 0, time.monotonic(), time.monotonic()
        anchor, anchor_t = self.pose(), time.monotonic()

        def brake():
            self.robot.drive(0.0, 0.0, 0.1)

        while True:
            now = time.monotonic()
            if cancelled():
                self.robot.stop()
                return "stop", "cancelled"
            if now > self._deadline:
                brake()
                return "stop", "it was taking too long"
            x, y, th = self.pose()
            is_last = index == len(path) - 1
            if is_last and target.surface_distance(x, y) <= standoff + cfg.arrive_slack_m:
                brake()
                return "arrived"
            wp = path[index]
            dist = math.hypot(wp[0] - x, wp[1] - y)
            if dist <= (cfg.waypoint_tol_m if is_last else cfg.corner_radius_m):
                if is_last:
                    brake()
                    return "arrived" if target.surface_distance(x, y) <= standoff + 2 * cfg.arrive_slack_m else "replan"
                index += 1
                continue
            if index > 1 and self._off_route((x, y), path[index - 1], wp):
                brake()
                return "replan"
            err = wrap(math.atan2(wp[1] - y, wp[0] - x) - th)
            r = self.robot.latest_reading()
            front = (r.get("distances") or {}).get("front", r.get("distance"))
            v, w, margin = self._wheels_for(err, dist, is_last, front)
            w = self._steer_clear(w, margin, is_last)
            direction = ("left" if w > 0 else "right") if abs(w) >= abs(v) else "forward"
            step = cfg.wheel_step
            left += max(-step, min(step, (v - w) - left))
            right += max(-step, min(step, (v + w) - right))
            self.robot.drive(round(left, 3), round(right, 3), 0.25)
            sent += 1
            time.sleep(tick)
            if sent > 3 and self._state() == "blocked":
                kind = self._blocked_kind(direction)
                if kind == "front_obstacle" and is_last and \
                        target.surface_distance(*self.pose()[:2]) <= standoff + 2 * cfg.arrive_slack_m:
                    return "arrived"
                self.log("info", f"safety stop ({kind}), finding another way")
                if self._recover(kind, cancelled) == "cancelled":
                    return "stop", "cancelled"
                return "replan"
            now = time.monotonic()
            if now - last_visit > 0.2:
                last_visit = now
                self.memory.visit(x, y)
            if now - last_check > 0.4:
                last_check = now
                problem = self._still_good(route, index, target)
                if problem:
                    brake()
                    self.log("info", f"{problem}: replanning")
                    return ("stop", problem) if problem == "the map was reset" else "replan"
            nx, ny, nth = self.pose()
            if math.hypot(nx - anchor[0], ny - anchor[1]) + abs(wrap(nth - anchor[2])) > 0.02:
                anchor, anchor_t = (nx, ny, nth), now
            elif now - anchor_t > 3.0:
                brake()
                return "stop", "I don't seem to be moving"

    def _face(self, target, cancelled):
        x, y, th = self.pose()
        if target.exact:
            if "heading" not in target.extra:
                return
            err = wrap(target.extra["heading"] - th)
        else:
            px, py = target.nearest_point(x, y)
            err = wrap(math.atan2(py - y, px - x) - th)
        if abs(err) > math.radians(self.cfg.heading_tol_deg):
            self._turn(err, cancelled)           # a blocked last turn doesn't undo the arrival

    def _leg(self, target, cancelled):
        """Drive to one target. None when there, else the reason."""
        for attempt in range(self.cfg.max_replans + 1):
            self.state = {**self.state, "phase": "planning", "target": target.name, "replans": attempt}
            view, cm, fresh, route = self._plan(target)
            target = fresh
            if view.epoch != self.epoch:
                return "the map was reset", target
            if route is None:
                self._face(target, cancelled)
                return None, target
            if not route.ok:
                return f"no route: {route.why}", target
            self.state = {**self.state, "phase": "driving"}
            result = self._follow(route, target, cm.stop_ring(target), cancelled)
            if result == "arrived":
                self._face(target, cancelled)
                return None, target
            if result != "replan":
                return result[1], target
        return "too many detours", target

    # -- looking for things --

    def scan(self, cancelled=lambda: False):
        """Turn once on the spot in steps, pausing so the camera gets sharp frames."""
        self.state = {**self.state, "phase": "looking around"}
        step = 2 * math.pi / self.cfg.scan_steps
        for _ in range(self.cfg.scan_steps):
            why = self._turn(step, cancelled)
            if why:
                return why
            time.sleep(self.cfg.scan_pause_s)
        return None

    def _search_spot(self, view, visited):
        """A reachable nearby place that shows the most unobserved floor and is new to this search."""
        x, y, _ = view.pose
        step = self.cfg.search_step_m
        cm = Costmap(view, self.cfg, self.robot.stop_distance, [(x, y)], self.blockers, 0.8, self.memory.layers())
        best, best_score = None, -math.inf
        for k in range(12):
            a = 2 * math.pi * k / 12
            px, py = x + step * math.cos(a), y + step * math.sin(a)
            if not cm.is_free(px, py) or any(math.hypot(px - vx, py - vy) < step * 0.7 for vx, vy in visited):
                continue
            near = cm.disc(px, py, 0.3)
            score = float(cm.unknown[near].mean()) if near.any() else 0.0
            score += 0.1 * min(math.hypot(px - vx, py - vy) for vx, vy in visited)
            if score > best_score:
                best, best_score = (px, py), score
        return best

    def _explore(self, name, near, exclude, cancelled):
        """Look around here, then from a few other places. The target, or None."""
        spoken = clean_name(name)
        self.say(f"I don't see the {spoken} yet, so I'll look around.")
        if self.scan(cancelled) == "cancelled":
            return None
        target = find_target(self.view(), self.cfg, name, near, exclude)
        visited = [tuple(self.pose()[:2])]
        for _ in range(self.cfg.search_spots):
            if target is not None or cancelled():
                break
            spot = self._search_spot(self.view(), visited)
            if spot is None:
                break
            visited.append(spot)
            self.state = {**self.state, "phase": "searching", "target": spoken}
            why, _ = self._leg(Target("search spot", spot[0], spot[1], exact=True), cancelled)
            if why == "cancelled" or cancelled():
                return None
            if self.scan(cancelled) == "cancelled":
                return None
            target = find_target(self.view(), self.cfg, name, near, exclude)
        return target

    def _locate(self, name, near, exclude, cancelled):
        target = find_target(self.view(), self.cfg, name, near, exclude)
        if target is None and not self._scanned:
            self._scanned = True
            target = self._explore(name, near, exclude, cancelled)
        return target

    def home_target(self):
        m = self.memory
        if m.home is None or not m.aligned:
            return None
        return Target("home", m.home[0], m.home[1], exact=True, extra={"heading": m.home[2]})

    def mark_home(self):
        """The robot is standing on its home spot."""
        self.memory.sync(self.view().epoch)
        moved = self.memory.mark_home(self.pose())
        self.say("Got it, this is home. My saved places line up again." if moved else "Got it, this is home.")
        self.emit("arrived")
        return None

    # -- the whole trip --

    def go(self, to, frm="", cancelled=lambda: False):
        """Drive to `frm` (if given), then to `to`. Returns None on success, else why it stopped."""
        names = [n for n in (frm, to) if clean_name(n)]
        if not names:
            return "no destination given"
        if len(names) == 2 and clean_name(frm) == clean_name(to):
            first = find_target(self.view(), self.cfg, frm)
            if first is None or find_target(self.view(), self.cfg, to, exclude=first) is None:
                names = names[1:]                # "from the cup to the cup" with only one cup
        was_on = self.behaviour.enabled if self.behaviour is not None else False
        if self.behaviour is not None:
            self.behaviour.set_enabled(False)    # don't fight the face-the-user turns
        self.history, self.blockers, self._scanned, self._warned_low = [], [], False, False
        self.hop = self.cfg.hop_m
        self.epoch = self.view().epoch
        self.memory.sync(self.epoch)
        if not self.memory.aligned:
            self.log("warn", "Saved zones and home are switched off until the map is lined up again")
        self._deadline = time.monotonic() + self.cfg.mission_timeout_s
        self.state = {"phase": "starting", "from": clean_name(frm), "to": clean_name(to), "started": time.time()}
        try:
            why = self._trip(names, cancelled)
        except Exception as exc:
            self.robot.stop()
            self.state = {**self.state, "phase": "failed", "result": str(exc)}
            self.say("Something went wrong while I was finding my way.", "alert")
            raise
        finally:
            if self.behaviour is not None and was_on:
                self.behaviour.set_enabled(True)
        self.memory.save()
        self.state = {**self.state, "phase": "done" if why is None else "stopped", "result": why or "arrived"}
        if why not in (None, "cancelled") and not why.startswith("can't find"):
            self.emit("failed")
        return why

    def _trip(self, names, cancelled):
        previous = None
        for i, name in enumerate(names):
            spoken = clean_name(name)
            x, y, _ = self.pose()
            if spoken in HOME_NAMES:
                target = self.home_target()
                if target is None:
                    self.emit("failed")
                    self.say("I don't know where home is on this map. Put me there and say, this is home.", "alert")
                    return "home is not set"
            else:
                target = self._locate(name, (x, y), previous, cancelled)
            if cancelled():
                return "cancelled"
            if target is None:
                self.emit("not_found")
                self.say(f"I cannot seem to find the {spoken}.", "alert")
                return f"can't find {spoken}"
            self.emit("recognised")
            self.state = {**self.state, "leg": i + 1, "legs": len(names)}
            self.emit("navigating")
            why, target = self._leg(target, cancelled)
            if why == "cancelled":
                return why
            if why:
                self.say(f"I couldn't get to the {target.name}. {self._speakable(why)}", "alert")
                return why
            previous = target
            self.emit("arrived")
            self.say(f"I reached the {target.name}." if i == len(names) - 1 else f"I'm at the {target.name}. On to the next one.")
            if i < len(names) - 1:
                time.sleep(self.cfg.leg_pause_s)
        return None

    @staticmethod
    def _speakable(why):
        return {"too many detours": "I kept running into things."}.get(why, why[0].upper() + why[1:] + ".")
