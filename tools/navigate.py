#!/usr/bin/env python3
"""
Go from one obstacle to another, choosing the path planner to suit the desk (18 Nov 2026).

    python tools/navigate.py --compare                       every planner on nine test desks, and which one is chosen
    python tools/navigate.py --from cup --to bottle          full simulated run: robot, sonars, camera, maps, safety rules
    python tools/navigate.py --to book                       from where the robot is now
    python tools/navigate.py --from cup --to bottle --url http://localhost:8000      ask a running robot (real or simulated)

The simulated run saves a picture and a JSON report in outputs/navigation/.
Normally you just ask the robot: "go from the cup to the bottle". Design: docs/navigation.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "run_prototype"     # the robot's code lives here
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parents[1] / "benchmarks")]

import deskbot  # noqa: E402,F401  (sys.path setup)


def compare():
    from deskbot.config import NavigationConfig
    from deskbot.navigation.planners import PLANNERS
    from desk_bench.scenes import NO_ROUTE_EXPECTED, SCENES, costmap_for, scene
    from deskbot.navigation.selector import SearchSpeed, plan_growing

    cfg = NavigationConfig()
    names = list(PLANNERS)
    speed = SearchSpeed(cfg.default_ms_per_1k)      # shared, as on the robot: it learns this machine's speed
    print(f"{'desk':<17}{'obstacles':>9}{'blocked':>9}  {'chosen':<15}" + "".join(f"{n:>16}" for n in names))
    print(" " * 52 + "".join(f"{'cm / ms':>16}" for _ in names))
    good = 0
    for name in SCENES:
        view, start, target, _ = scene(name, cfg)
        make = lambda margin: costmap_for(view, start, target, cfg, margin=margin)   # noqa: E731
        cells, astar_ms = [], "n/a"
        for planner in names:
            r = plan_growing(make, start, 0.0, target, speed if planner == "astar" else SearchSpeed(cfg.default_ms_per_1k), force=planner)
            cells.append(f"{r.length_m * 100:.0f} / {r.tried[0]['ms']:.0f}" if r.ok else "-")
            if planner == "astar" and r.tried:
                astar_ms = f"{r.tried[0]['ms']:.0f} ms ({r.tried[0]['expansions']} cells)"
        chosen = plan_growing(make, start, 0.0, target, speed)
        f = chosen.features
        correct = chosen.ok != (name in NO_ROUTE_EXPECTED)
        good += correct
        print(f"{name:<17}{f.n_obstacles:>9}{f.density:>9.0%}  {chosen.planner or '(no route)':<15}" + "".join(f"{c:>16}" for c in cells))
        print(f"    why: {'; '.join(chosen.decision.reasons)}")
        print(f"    A* time: predicted {f.predicted_ms:.0f} ms, measured {astar_ms}" + ("" if correct else "   <-- WRONG OUTCOME"))
    print(f"\n{good}/{len(SCENES)} desks had the expected outcome (a route, or a refusal on the walled-off desk).")
    return 0 if good == len(SCENES) else 1


def draw(path, hw, mapper, trail, plans, targets):
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        print(f"(no picture: {exc})")
        return None
    scale = 500
    pad = 50
    w, h = int(hw.DESK_W * scale) + 2 * pad, int(hw.DESK_H * scale) + 2 * pad
    px = lambda x, y: (pad + x * scale, h - pad - y * scale)   # noqa: E731
    ox, oy = trail[0]                                          # the map's origin is where the robot started
    img = Image.new("RGB", (w, h), (246, 246, 242))
    d = ImageDraw.Draw(img)
    d.rectangle([px(0, hw.DESK_H), px(hw.DESK_W, 0)], fill=(255, 255, 255), outline=(90, 90, 90), width=2)
    for ob in hw.OBSTACLES:
        if ob.get("user"):
            continue
        color = tuple(ob["color"])
        if ob["kind"] == "circle":
            (x0, y0), (x1, y1) = px(ob["x"] - ob["r"], ob["y"] + ob["r"]), px(ob["x"] + ob["r"], ob["y"] - ob["r"])
            d.ellipse([x0, y0, x1, y1], fill=color)
            where = px(ob["x"] + ob["r"], ob["y"] + ob["r"])
        else:
            d.rectangle([px(ob["x"], ob["y"] + ob["h"]), px(ob["x"] + ob["w"], ob["y"])], fill=color)
            where = px(ob["x"] + ob["w"], ob["y"] + ob["h"])
        d.text((where[0] + 3, where[1] - 12), ob["label"], fill=(30, 30, 30))
    for plan in plans:
        pts = [px(x + ox, y + oy) for x, y in plan.get("path") or []]
        if len(pts) > 1:
            d.line(pts, fill=(150, 190, 245), width=2)
    if len(trail) > 1:
        d.line([px(x, y) for x, y in trail], fill=(214, 60, 40), width=3)
    x, y = px(*trail[0])
    d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(30, 150, 70))
    x, y = px(*trail[-1])
    d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(214, 60, 40))
    used = " > ".join(p["planner"] for p in plans if p.get("planner"))
    d.text((pad, 12), f"{' to '.join(targets)}   planners: {used}", fill=(30, 30, 30))
    d.text((pad, h - 30), "green = start, red = driven path, blue = planned routes", fill=(90, 90, 90))
    img.save(path)
    return path


def body_gap(hw):
    """True distance between the robot's body and the nearest solid thing, in metres."""
    best = math.inf
    for ob in hw.OBSTACLES:
        if ob.get("flat") or ob.get("user"):
            continue
        if ob["kind"] == "circle":
            gap = math.hypot(hw.x - ob["x"], hw.y - ob["y"]) - ob["r"]
        else:
            dx = max(ob["x"] - hw.x, 0, hw.x - ob["x"] - ob["w"])
            dy = max(ob["y"] - hw.y, 0, hw.y - ob["y"] - ob["h"])
            gap = math.hypot(dx, dy)
        best = min(best, gap)
    return min(best, hw.DESK_H - hw.y) - hw.BODY_RADIUS


def simulate(args):
    from deskbot.config import AppConfig
    from deskbot.mapping.live import LiveFusionMapper
    from deskbot.navigation import Navigator
    from deskbot.robot import make_robot
    from deskbot.web.server import build_vision

    cfg = AppConfig()
    robot, hw = make_robot(sim=True)
    robot.busy = lambda: robot.state == "moving"     # the single-process robot has no busy()
    if args.start:
        with hw._lock:
            hw.x, hw.y = args.start
    if args.stop_distance:
        robot.update_settings(stop_distance=args.stop_distance)
    vision = build_vision("sim", True, hw, cfg, log=lambda m: None)
    mapper = LiveFusionMapper(robot, cfg, vision)
    mapper.start()
    spoken = []

    def say(text, kind="chatter"):
        spoken.append(text)
        print(f'  robot says: "{text}"')

    nav = Navigator(robot, mapper, cfg.navigation, say)
    trail, gaps, running = [(hw.x, hw.y)], [], [True]

    def watch():
        while running[0]:
            with hw._lock:
                hw._step()
                if math.hypot(hw.x - trail[-1][0], hw.y - trail[-1][1]) > 0.005:
                    trail.append((hw.x, hw.y))
                gaps.append(body_gap(hw))
            time.sleep(0.03)

    threading.Thread(target=watch, daemon=True).start()
    try:
        time.sleep(1.5)
        if not args.no_scan:
            print("Looking around first, so the map has something in it...")
            nav.scan()
        print("On the map:", nav.known_obstacles())
        t0 = time.monotonic()
        why = nav.go(args.to, args.frm or "")
        elapsed = time.monotonic() - t0
    finally:
        running[0] = False
        robot.stop()
        mapper.stop()
        vision.stop()
        hw.close()

    status = nav.status()
    plans = nav.history
    print(f"\nResult: {'arrived' if why is None else why}  ({elapsed:.1f} s, {len(plans)} plan(s))")
    for i, p in enumerate(plans, 1):
        f = p["features"] or {}
        print(f"  plan {i} to {p['target']}: {p['planner'] or 'none'}, {p['length_m'] * 100:.0f} cm, {p['plan_ms']:.0f} ms, "
              f"{f.get('n_obstacles')} obstacles, {(f.get('density') or 0):.0%} blocked")
        for reason in p["reasons"]:
            print(f"      {reason}")
    print(f"  closest the robot's body came to anything solid: {min(gaps) * 100:.1f} cm")
    print(f"  safety stops: {robot.stats['safety_stops']} {robot.stop_counts}")

    folder = ROOT / "outputs" / "navigation" / datetime.now().strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    targets = [n for n in (args.frm, args.to) if n]
    picture = draw(folder / "route.png", hw, mapper, trail, plans, targets)
    report = {"from": args.frm, "to": args.to, "result": why or "arrived", "seconds": round(elapsed, 1),
              "min_body_gap_m": round(min(gaps), 4), "safety_stops": robot.stats["safety_stops"],
              "stop_counts": robot.stop_counts, "plans": plans, "spoken": spoken,
              "final_pose": {"x": round(hw.x, 3), "y": round(hw.y, 3), "theta": round(hw.theta, 3)},
              "status": {k: v for k, v in status.items() if k != "plans"}}
    (folder / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"  saved {picture or folder}")
    return 0 if why is None else 1


def ask_robot(args):
    body = json.dumps({"commands": [{"action": "navigate", "amount": 0, "from_object": args.frm or "", "to_object": args.to}],
                       "source": "navigate.py"}).encode()
    base = args.url.rstrip("/")
    req = urllib.request.Request(base + "/api/assistant/commands", body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            print("Accepted:", json.loads(r.read())["accepted"])
        while True:
            time.sleep(1)
            with urllib.request.urlopen(base + "/api/assistant", timeout=5) as r:
                state = json.loads(r.read())
            nav = state["navigation"]
            print(f"  {nav.get('phase')}: target {nav.get('target')}, planner {nav.get('planner')}, replans {nav.get('replans')}")
            if state["executor"]["current"] is None and nav.get("phase") in ("done", "stopped", "failed"):
                print("Result:", nav.get("result"))
                return 0 if nav.get("phase") == "done" else 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"Could not reach the robot at {base}: {exc}")
        return 1


def main():
    p = argparse.ArgumentParser(description="Go from one obstacle to another with adaptive path planning.")
    p.add_argument("--from", dest="frm", default="", help="visit this first (cup, book, 'obstacle 1', 'nearest obstacle')")
    p.add_argument("--to", help="destination")
    p.add_argument("--compare", action="store_true", help="compare the planners on test desks (no robot needed)")
    p.add_argument("--url", help="send the request to a running robot, e.g. http://localhost:8000")
    p.add_argument("--no-scan", action="store_true", help="simulation: don't look around before starting")
    p.add_argument("--start", nargs=2, type=float, metavar=("X", "Y"), help="simulation: start here on the 1.2 x 0.7 m desk")
    p.add_argument("--stop-distance", type=float, help="simulation: sonar stop distance in metres (default 0.20)")
    args = p.parse_args()
    if args.compare:
        return compare()
    if not args.to:
        p.error("--to is required (or use --compare)")
    return ask_robot(args) if args.url else simulate(args)


if __name__ == "__main__":
    sys.exit(main())
