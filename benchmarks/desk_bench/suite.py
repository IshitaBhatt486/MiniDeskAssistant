"""The open-source benchmark suite behind benchmarks.py. Each function returns a JSON-friendly dict."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

import numpy as np

from deskbot import ROOT

from . import BENCH_HOME
from deskbot.config import AppConfig, NavigationConfig

DATA = BENCH_HOME / "data"
PYTHONROBOTICS_REPO = "https://github.com/AtsushiSakai/PythonRobotics"
LIBRISPEECH_URL = "https://www.openslr.org/resources/12/dev-clean.tar.gz"


# ---------------- pyperf ----------------

PERF_SETUP = f"""
import sys; sys.path[:0] = [{str(ROOT)!r}, {str(BENCH_HOME)!r}]
import numpy as np, deskbot
from deskbot.config import NavigationConfig, VisionConfig
from desk_bench.scenes import scene, costmap_for
from deskbot.navigation.selector import plan_route, SearchSpeed
from deskbot.runtime.sensor_filter import SensorConditioner
from deskbot.vision.adaptive import AdaptiveInterval
from deskbot.vision.describe import dominant_colour
cfg = NavigationConfig(); v, s, t, _ = scene("many obstacles", cfg); cm = costmap_for(v, s, t, cfg, margin=1.0)
f = SensorConditioner(); d = dict(front=.5, left=.5, right=.5, rear=.5)
a = AdaptiveInterval(VisionConfig()); img = np.zeros((240, 320, 3), np.uint8)
"""
PERF_CASES = {
    "costmap_build_ms": "costmap_for(v, s, t, cfg, margin=1.0)",
    "plan_astar_ms": "plan_route(cm, s, 0.0, t, SearchSpeed(40.0), force='astar')",
    "plan_theta_star_ms": "plan_route(cm, s, 0.0, t, SearchSpeed(40.0), force='theta_star')",
    "plan_visibility_ms": "plan_route(cm, s, 0.0, t, SearchSpeed(40.0), force='visibility')",
    "sensor_filter_ms": "f.update(d, True, True)",
    "adaptive_vision_check_ms": "a.should_detect(img, 1, 0)",
    "colour_of_box_ms": "dominant_colour(img, (20, 20, 120, 120))",
}


def perf():
    import pyperf

    out = {}
    with tempfile.TemporaryDirectory() as d:
        for name, stmt in PERF_CASES.items():
            path = os.path.join(d, name + ".json")
            subprocess.run([sys.executable, "-m", "pyperf", "timeit", "--fast", "--quiet", "--output", path,
                            "--setup", PERF_SETUP, stmt], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
            b = pyperf.Benchmark.load(path)
            out[name] = {"mean": round(b.mean() * 1000, 4), "stdev": round(b.stdev() * 1000, 4) if b.get_nvalue() > 1 else 0.0}
    return out


# ---------------- PythonRobotics baseline ----------------

def _load_astar():
    head = subprocess.run(["git", "ls-remote", PYTHONROBOTICS_REPO, "HEAD"], capture_output=True, text=True, check=True, timeout=30)
    sha = head.stdout.split()[0]
    path = DATA / "pythonrobotics" / sha / "a_star.py"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/AtsushiSakai/PythonRobotics/{sha}/PathPlanning/AStar/a_star.py"
        urllib.request.urlretrieve(url, path)
    os.environ.setdefault("MPLBACKEND", "Agg")
    spec = importlib.util.spec_from_file_location("pythonrobotics_a_star", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.show_animation = False
    return mod, sha


def planners():
    from deskbot.navigation.planners import build_problem
    from desk_bench.scenes import NO_ROUTE_EXPECTED, SCENES, costmap_for, scene
    from deskbot.navigation.selector import SearchSpeed, plan_growing

    astar, sha = _load_astar()
    cfg = NavigationConfig()
    rows = {}
    for name in SCENES:
        if name in NO_ROUTE_EXPECTED or name == "long open route":
            continue
        view, start, target, _ = scene(name, cfg)
        make = lambda m: costmap_for(view, start, target, cfg, margin=m)   # noqa: E731
        ours = plan_growing(make, start, 0.0, target, SearchSpeed(cfg.default_ms_per_1k))
        if not ours.ok:
            rows[name] = {"ours": "no route"}
            continue
        cm = ours.cm
        goal = ours.path[-1]
        step = max(1, int(round(0.05 / cm.res)))
        rr, cc = np.nonzero(cm.solid[::step, ::step])
        # the baseline rounds its map bounds to whole metres, so shift everything onto a whole-metre frame
        dx, dy = 1.0 - float(cm.X[0]), 1.0 - float(cm.Y[0])
        ox = (cm.X[::step][cc] + dx).tolist()
        oy = (cm.Y[::step][rr] + dy).tolist()
        x1, y1 = math.ceil(float(cm.X[-1]) + dx) + 1, math.ceil(float(cm.Y[-1]) + dy) + 1
        for x in np.arange(1.0, x1 + 0.01, 0.05):
            ox += [float(x), float(x)]
            oy += [1.0, float(y1)]
        for y in np.arange(1.0, y1 + 0.01, 0.05):
            ox += [1.0, float(x1)]
            oy += [float(y), float(y)]
        t0 = time.perf_counter()
        rx, ry = astar.AStarPlanner(ox, oy, 0.05, cfg.robot_radius + cfg.clearance_margin).planning(
            start[0] + dx, start[1] + dy, goal[0] + dx, goal[1] + dy)
        ms = (time.perf_counter() - t0) * 1000
        found = len(rx) > 1
        length = sum(math.dist((rx[i], ry[i]), (rx[i + 1], ry[i + 1])) for i in range(len(rx) - 1))
        rows[name] = {"ours_planner": ours.planner, "ours_cm": round(ours.length_m * 100, 1), "ours_ms": round(ours.plan_ms, 1),
                      "pythonrobotics_astar_cm": round(length * 100, 1) if found else None, "pythonrobotics_ms": round(ms, 1),
                      "note": "ours also obeys the sonar stop rule; the baseline only avoids collisions"}
    return {"pythonrobotics_commit": sha, "same_goal": True, "desks": rows}


# ---------------- evo ----------------

def _trajectory(rows):
    from evo.core.trajectory import PoseTrajectory3D

    a = np.asarray(rows, float)
    xyz = np.column_stack((a[:, 1], a[:, 2], np.zeros(len(a))))
    th = a[:, 3]
    quat = np.column_stack((np.cos(th / 2), np.zeros(len(a)), np.zeros(len(a)), np.sin(th / 2)))
    return PoseTrajectory3D(positions_xyz=xyz, orientations_quat_wxyz=quat, timestamps=a[:, 0])


def _simulated_drive(wheel_error=0.05):
    """A square driven in the simulator. The real wheels run 5% slower than odometry assumes."""
    from deskbot.mapping.live import LiveFusionMapper
    from deskbot.robot import make_robot

    cfg = AppConfig()
    robot, hw = make_robot(sim=True)
    robot.busy = lambda: robot.state == "moving"
    hw.MAX_WHEEL_SPEED *= 1 - wheel_error
    hw.OBSTACLES = []
    robot.stop_distance = 0.05
    mapper = LiveFusionMapper(robot, cfg, None)
    mapper.start()
    truth, odom = [], []
    x0, y0 = hw.x, hw.y
    t0 = time.monotonic()
    try:
        turn = (math.pi / 2) / (2 * robot.speed * 0.25 / 0.12)
        for _ in range(4):
            for direction, seconds in (("forward", 1.4), ("left", turn)):
                robot.move(direction, seconds)
                end = time.monotonic() + seconds + 0.2
                while time.monotonic() < end:
                    now = time.monotonic() - t0
                    with hw._lock:
                        hw._step()
                        truth.append((now, hw.x - x0, hw.y - y0, hw.theta))
                    with mapper._lock:
                        o = mapper.odom
                        odom.append((now, o.x, o.y, o.theta))
                    time.sleep(0.05)
    finally:
        robot.stop()
        mapper.stop()
        hw.close()
    return truth, odom


def odometry(reference=None, estimate=None):
    from evo.core import metrics, sync
    from evo.tools import file_interface

    if reference and estimate:
        ref, est = file_interface.read_tum_trajectory_file(reference), file_interface.read_tum_trajectory_file(estimate)
        source = "TUM files"
    else:
        truth, odom = _simulated_drive()
        ref, est = _trajectory(truth), _trajectory(odom)
        source = "simulator, square path, wheels 5% slower than the odometry assumes"
    ref, est = sync.associate_trajectories(ref, est, max_diff=0.05)
    out = {"source": source, "poses": ref.num_poses}
    ape = metrics.APE(metrics.PoseRelation.translation_part)
    ape.process_data((ref, est))
    out["ate_rmse_cm"] = round(ape.get_statistic(metrics.StatisticsType.rmse) * 100, 2)
    out["ate_max_cm"] = round(ape.get_statistic(metrics.StatisticsType.max) * 100, 2)
    rpe = metrics.RPE(metrics.PoseRelation.translation_part, delta=10, delta_unit=metrics.Unit.frames, all_pairs=False)
    rpe.process_data((ref, est))
    out["rpe_rmse_cm_per_10_poses"] = round(rpe.get_statistic(metrics.StatisticsType.rmse) * 100, 2)
    return out


# ---------------- TrackEval ----------------

def _trackeval_scores(gt_frames, tracker_frames):
    """gt_frames, tracker_frames: per frame, {id: (x1, y1, x2, y2)}."""
    np.float = float       # TrackEval still uses these aliases, which NumPy removed
    np.int = int
    import trackeval
    from trackeval.metrics import CLEAR, HOTA, Identity

    def ids(frames):
        return {k: i for i, k in enumerate(sorted({t for f in frames for t in f}))}

    gi, ti = ids(gt_frames), ids(tracker_frames)
    data = {"num_timesteps": len(gt_frames), "num_gt_ids": len(gi), "num_tracker_ids": len(ti),
            "num_gt_dets": sum(map(len, gt_frames)), "num_tracker_dets": sum(map(len, tracker_frames)),
            "gt_ids": [], "tracker_ids": [], "similarity_scores": []}
    for g, t in zip(gt_frames, tracker_frames):
        gk, tk = list(g), list(t)
        sim = np.zeros((len(gk), len(tk)))
        for i, a in enumerate(gk):
            for j, b in enumerate(tk):
                x = max(0, min(g[a][2], t[b][2]) - max(g[a][0], t[b][0]))
                y = max(0, min(g[a][3], t[b][3]) - max(g[a][1], t[b][1]))
                inter = x * y
                union = (g[a][2] - g[a][0]) * (g[a][3] - g[a][1]) + (t[b][2] - t[b][0]) * (t[b][3] - t[b][1]) - inter
                sim[i, j] = inter / union if union > 0 else 0.0
        data["gt_ids"].append(np.array([gi[k] for k in gk], int))
        data["tracker_ids"].append(np.array([ti[k] for k in tk], int))
        data["similarity_scores"].append(sim)
    conf = {"PRINT_CONFIG": False, "THRESHOLD": 0.5}
    hota = HOTA(conf).eval_sequence(data)
    clear = CLEAR(conf).eval_sequence(data)
    identity = Identity(conf).eval_sequence(data)
    return {"HOTA": round(float(np.mean(hota["HOTA"])), 4), "MOTA": round(float(clear["MOTA"]), 4),
            "IDF1": round(float(identity["IDF1"]), 4), "id_switches": int(clear["IDSW"])}


def _read_mot(path, frames):
    out = [{} for _ in range(frames)]
    for row in np.loadtxt(path, delimiter=",", ndmin=2):
        f, tid, x, y, w, h = row[:6]
        if 1 <= f <= frames:
            out[int(f) - 1][int(tid)] = (x, y, x + w, y + h)
    return out


def _tracking_run(adaptive, frames=240):
    from deskbot.config import CameraConfig, VisionConfig
    from deskbot.robot import FusionSimHardware
    from deskbot.vision.adaptive import AdaptiveInterval
    from deskbot.vision.camera import Frame, SimCamera
    from deskbot.vision.detector import SimDetector
    from deskbot.vision.flow import FlowTracker

    hw = FusionSimHardware()
    ccfg, vcfg = CameraConfig(), VisionConfig()
    cam = SimCamera(ccfg, hw)
    cam._period = 0.0
    det, flow = SimDetector(miss_rate=0.05, seed=1), FlowTracker(vcfg.flow_points)
    ai = AdaptiveInterval(vcfg)
    gt, res, last, runs = [], [], -10 ** 9, 0
    hw.x, hw.y, hw.theta = 0.45, 0.2, 0.0
    for k in range(frames):
        turning = 60 <= k < 110 or 170 <= k < 190            # still, turn, still, turn
        moving = turning
        if turning:
            hw.theta += 0.035 * (1 if k < 120 else -1)
        t, img, boxes = cam.read()
        frame = Frame(k, t, img, boxes)
        since = k - last
        go = ai.should_detect(img, since, len(flow.tracks), moving, turning) if adaptive else since >= vcfg.detect_every or not flow.tracks
        if go:
            dets = det(frame)
            flow.reset(img, dets)
            last, runs = k, runs + 1
            if adaptive:
                ai.detected(img, len(dets), moving, turning)
        else:
            dets = flow.update(img)
        gt.append({b["id"]: tuple(b["box"]) for b in boxes})
        res.append({d.track_id: tuple(d.box) for d in dets if d.track_id is not None})
    hw.close()
    return gt, res, runs


def tracking(gt=None, results=None):
    if gt and results:
        n = int(np.loadtxt(gt, delimiter=",", ndmin=2)[:, 0].max())
        return {"source": "MOT files", **_trackeval_scores(_read_mot(gt, n), _read_mot(results, n))}
    out = {"source": "simulated camera, robot still then turning, 240 frames"}
    for name, adaptive in (("fixed_every_3", False), ("adaptive", True)):
        g, r, runs = _tracking_run(adaptive)
        out[name] = {"detector_runs": runs, **_trackeval_scores(g, r)}
    return out


# ---------------- pycocotools ----------------

def detection(limit=30):
    import cv2
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    from deskbot.vision.coco import NAMES
    from . import datasets
    from .run import _detector, _robot_view

    cfg = AppConfig()
    if not datasets.coco_subset_path().exists():
        datasets.download_coco(limit)
    data = datasets.load_coco()
    images = data["images"][:limit]
    det = _detector(cfg, 2, print)
    wanted = set(data["classes"])
    gt = {"images": [], "annotations": [], "categories": [{"id": i, "name": n} for i, n in enumerate(NAMES)]}
    preds = []
    for im in images:
        gt["images"].append({"id": im["id"], "width": im["w"], "height": im["h"]})
        for b in im["boxes"]:
            if NAMES[b[0]] in wanted:
                w, h = b[3] - b[1], b[4] - b[2]
                gt["annotations"].append({"id": len(gt["annotations"]) + 1, "image_id": im["id"], "category_id": b[0],
                                          "bbox": [b[1], b[2], w, h], "area": w * h, "iscrowd": b[5]})
        img, s = _robot_view(cv2.imread(str(datasets.coco_image(im))), cfg.camera.width)
        for d in det.predict(img, conf=0.01):
            if d.label in wanted:
                x1, y1, x2, y2 = (v / s for v in d.box)
                preds.append({"image_id": im["id"], "category_id": NAMES.index(d.label),
                              "bbox": [x1, y1, x2 - x1, y2 - y1], "score": float(d.score)})
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gt.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(gt, f)
        coco = COCO(path)
    ev = COCOeval(coco, coco.loadRes(preds), "bbox")
    ev.params.imgIds = [im["id"] for im in images]
    ev.params.catIds = sorted({a["category_id"] for a in gt["annotations"]})
    ev.evaluate(), ev.accumulate(), ev.summarize()
    return {"images": len(images), "image_width": cfg.camera.width, "mAP50_95": round(float(ev.stats[0]), 4),
            "mAP50": round(float(ev.stats[1]), 4), "AR100": round(float(ev.stats[8]), 4)}


# ---------------- jiwer ----------------

def speech(limit=20, model_name="tiny.en"):
    import jiwer
    from faster_whisper import WhisperModel

    root = DATA / "librispeech"
    audio = root / "LibriSpeech" / "dev-clean"
    if not audio.exists():
        root.mkdir(parents=True, exist_ok=True)
        archive = root / "dev-clean.tar.gz"
        print("Downloading LibriSpeech dev-clean (about 340 MB, CC BY 4.0)...", flush=True)
        urllib.request.urlretrieve(LIBRISPEECH_URL, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
        archive.unlink()
    clips = []
    for listing in sorted(audio.rglob("*.trans.txt")):
        for line in listing.read_text(encoding="utf-8").splitlines():
            key, text = line.split(" ", 1)
            clips.append((listing.parent / f"{key}.flac", text))
    clips = clips[:: max(1, len(clips) // limit)][:limit]
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=2)
    clean = jiwer.Compose([jiwer.ToLowerCase(), jiwer.RemovePunctuation(), jiwer.RemoveMultipleSpaces(), jiwer.Strip()])
    refs, hyps, seconds, spoken = [], [], 0.0, 0.0
    for path, text in clips:
        t0 = time.perf_counter()
        segments, info = model.transcribe(str(path), beam_size=1, vad_filter=True)
        hyp = " ".join(s.text.strip() for s in segments)
        seconds += time.perf_counter() - t0
        spoken += info.duration
        refs.append(clean(text))
        hyps.append(clean(hyp) or "empty")
    return {"clips": len(clips), "model": model_name, "wer": round(jiwer.wer(refs, hyps), 4),
            "seconds_per_audio_second": round(seconds / spoken, 3)}
