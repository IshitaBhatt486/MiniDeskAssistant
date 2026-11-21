"""
The benchmarks. Results go to benchmarks/results/<date-time>/ as report.md + results.json.

    images   YOLO26n accuracy + speed on the COCO desk subset under every lighting condition:
             mAP50, mAP50-95, precision / recall at the robot's threshold, per-class AP50,
             inference p50 / p95, and the drop relative to normal light
    video    tracking on Objectron clips (or your own video) for detect_every = 1, 3, 5 under a few
             lighting conditions: found %, ID switches, distinct IDs, longest run, jitter, agreement
             with detecting every frame, CPU ms per frame and whether it keeps up with 30 fps
    system   the multi-process runtime (simulated hardware): command -> motor latency, age of the
             sensor sample at each safety check, preemption, shared-memory read cost, loop rates
"""

from __future__ import annotations

import dataclasses
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from deskbot import ROOT

from . import BENCH_HOME
from deskbot.config import AppConfig
from . import datasets, lighting, metrics

RESULTS = BENCH_HOME / "results"


def _pct(v, q):
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(q * len(s)))]


def _detector(cfg, threads, log):
    from deskbot.vision.detector import make_detector
    from deskbot.vision.model import resolve_model

    vcfg = dataclasses.replace(cfg.vision, threads=threads)
    return make_detector(vcfg, resolve_model(vcfg, log))


def _robot_view(img, width):
    """Resize to the robot camera's width (the detector sees what the robot would see)."""
    import cv2

    h, w = img.shape[:2]
    s = width / w
    return cv2.resize(img, (width, int(round(h * s))), interpolation=cv2.INTER_AREA), s


# ---------------- images ----------------

def bench_images(conditions=None, limit=None, threads=1, op_conf=0.35, log=print, cfg=None):
    import cv2

    cfg = cfg or AppConfig()
    conditions = conditions or lighting.DEFAULT_IMAGE_CONDITIONS
    data = datasets.load_coco()
    images = data["images"][:limit] if limit else data["images"]
    classes = data["classes"]
    det = _detector(cfg, threads, log)
    warm = cv2.imread(str(datasets.coco_image(images[0])))
    det.predict(_robot_view(warm, cfg.camera.width)[0], conf=0.01)
    det._set_threads()
    det.predict(_robot_view(warm, cfg.camera.width)[0], conf=0.01)

    from deskbot.vision.coco import name

    loaded = []
    for im in images:
        img, s = _robot_view(cv2.imread(str(datasets.coco_image(im))), cfg.camera.width)
        gts = [(name(b[0]), [v * s for v in b[1:5]]) for b in im["boxes"] if not b[5] and name(b[0]) in classes]
        loaded.append((im["id"], img, gts))

    out = {"dataset": data["source"], "images": len(loaded), "classes": classes, "imgsz": cfg.vision.imgsz,
           "threads": threads, "model": det.model_path, "op_conf": op_conf, "conditions": {}}
    for cond in conditions:
        preds, gts, times = [], [], []
        for img_id, img, gt in loaded:
            x = lighting.apply(cond, img, seed=img_id)
            t0 = time.perf_counter()
            dets = det.predict(x, conf=0.01)
            times.append((time.perf_counter() - t0) * 1000)
            preds.append([(d.label, d.score, d.box) for d in dets if d.label in classes])
            gts.append(gt)
        m = metrics.evaluate(preds, gts, classes, op_conf)
        m.update({"infer_p50_ms": _pct(times, 0.5), "infer_p95_ms": _pct(times, 0.95),
                  "description": lighting.CONDITIONS[cond][0]})
        out["conditions"][cond] = m
        log(f"  {cond:<13} mAP50 {_f(m['map50'])}  mAP50-95 {_f(m['map'])}  P {_f(m['precision'])}  "
            f"R {_f(m['recall'])}  {m['infer_p50_ms']:.0f} ms")
    base = out["conditions"].get("normal", {}).get("map50")
    for m in out["conditions"].values():
        m["map50_vs_normal"] = (m["map50"] / base) if base and m["map50"] is not None else None
    return out


# ---------------- video ----------------

def run_clip(frames, det_factory, every, flow_points=12):
    """Run the camera process's detect-every-N loop over frames (offline, every frame processed).
    Returns (per-frame detections, detect ms list, flow ms list)."""
    from deskbot.vision.camera import Frame
    from deskbot.vision.flow import FlowTracker

    det = det_factory()
    flow = FlowTracker(flow_points)
    out, dms, fms = [], [], []
    last = -10 ** 9
    for i, img in enumerate(frames):
        if i - last >= every or not flow.tracks:
            t0 = time.perf_counter()
            d = det(Frame(i + 1, 0.0, img))
            dms.append((time.perf_counter() - t0) * 1000)
            flow.reset(img, d)
            last = i
        else:
            t0 = time.perf_counter()
            d = flow.update(img)
            fms.append((time.perf_counter() - t0) * 1000)
        out.append(d)
    return out, dms, fms


def bench_video(clips=None, everies=(1, 3, 5), conditions=None, threads=1, max_frames=300, log=print, cfg=None):
    cfg = cfg or AppConfig()
    conditions = conditions or lighting.DEFAULT_VIDEO_CONDITIONS
    clips = clips or datasets.local_clips()
    if not clips:
        raise FileNotFoundError("No clips: run `python -m deskbot bench download` (Objectron) or pass --video FILE --label NAME")
    det = _detector(cfg, threads, log)

    def factory():
        det.reset()
        return det

    out = {"clips": [], "everies": list(everies), "threads": threads, "fps_target": cfg.camera.fps, "conditions": conditions}
    frame_budget = 1000.0 / cfg.camera.fps
    for path, label in clips:
        frames = datasets.read_frames(path, max_frames)
        if not frames:
            continue
        det.warmup(frames[0])
        clip = {"clip": Path(path).name, "label": label, "frames": len(frames), "runs": []}
        for cond in conditions:
            # lit frames are generated on the fly (not stored): keeps memory to one clip, not one per condition
            def seq(cond=cond):
                return (lighting.apply(cond, f, seed=i) for i, f in enumerate(frames))
            ref = None
            for every in sorted(everies):
                dets, dms, fms = run_clip(seq(), factory, every, cfg.vision.flow_points)
                if every == 1:
                    ref = dets
                m = metrics.tracking_metrics(dets, label, ref if every != 1 else None)
                total = sum(dms) + sum(fms)
                m.update({"condition": cond, "every": every, "detect_ms": statistics.mean(dms) if dms else None,
                          "flow_ms": statistics.mean(fms) if fms else None,
                          "cpu_ms_per_frame": total / len(frames),
                          "keeps_up_30fps": total / len(frames) <= frame_budget})
                clip["runs"].append(m)
                log(f"  {clip['clip'][:28]:<28} {cond:<9} every {every}: found {_f(m['found'])}  "
                    f"IDs {m['ids']}  switches {m['id_switches']}  {m['cpu_ms_per_frame']:.1f} ms/frame"
                    + (f"  agreement {_f(m.get('agreement'))}" if every != 1 else ""))
        out["clips"].append(clip)
    # summary per (condition, every)
    summary = {}
    for clip in out["clips"]:
        for r in clip["runs"]:
            summary.setdefault((r["condition"], r["every"]), []).append(r)
    out["summary"] = [
        {"condition": c, "every": e,
         **{k: _mean([r[k] for r in rs]) for k in ("found", "id_switches", "ids", "longest", "jitter", "agreement", "cpu_ms_per_frame")}}
        for (c, e), rs in sorted(summary.items(), key=lambda kv: (conditions.index(kv[0][0]), kv[0][1]))
    ]
    return out


# ---------------- system ----------------

def bench_system(n_commands=300, log=print, cfg=None):
    """Start the motor + sensor processes on the simulated robot and measure the control path."""
    from deskbot.runtime.app import start_children, stop_children, wait_ready
    from deskbot.runtime.proxy import RobotProxy, proc_table
    from deskbot.runtime.shared import Shared
    from deskbot.robot import RUNTIME_SIM_OBJECTS
    from deskbot.runtime.hardware import SimMirrorHardware

    cfg = cfg or AppConfig()
    shared = Shared(cfg.camera.width, cfg.camera.height, sim=True)
    shared.sim.publish_objects(RUNTIME_SIM_OBJECTS)
    procs = start_children(shared, cfg, True, "none")
    robot = RobotProxy(shared, cfg.runtime, SimMirrorHardware(shared.sim))
    try:
        if not all(wait_ready(shared, procs, ["motor", "sensors"]).values()):
            raise RuntimeError("motor/sensor process did not start")
        time.sleep(1.5)
        rng = np.random.default_rng(1)
        log(f"  sending {n_commands} commands (turn left / turn right / stop, random 5-60 ms apart; newest must win)...")
        for i in range(n_commands):
            if i % 3 == 0:
                robot.move("left", 0.2, source="auto")
            elif i % 3 == 1:
                robot.move("right", 0.2, source="auto")     # replaces the left turn while it runs
            else:
                robot.stop(source="auto")
            time.sleep(float(rng.uniform(0.005, 0.06)))
        robot.stop(source="auto")
        time.sleep(1.2)   # let the loop stats publish
        m = shared.motor.read()
        # shared-memory read cost
        t0 = time.perf_counter()
        for _ in range(20000):
            shared.sensors.read_array()
        shm_us = (time.perf_counter() - t0) / 20000 * 1e6
        # pipe round trip for comparison (what a Queue-based design pays per message)
        from deskbot.runtime.shared import CTX
        q = CTX.Queue()
        t0 = time.perf_counter()
        for _ in range(2000):
            q.put({"level": "x", "msg": "y"})
            q.get()
        queue_us = (time.perf_counter() - t0) / 2000 * 1e6
        return {
            "commands": n_commands,
            "cmd_latency_ms": {"p50": m["cmd_latency_p50"], "p95": m["cmd_latency_p95"], "max": m["cmd_latency_max"]},
            "sensor_age_at_check_ms": {"p50": m["sensor_age_p50"], "p95": m["sensor_age_p95"], "max": m["sensor_age_max"]},
            "preempted_moves": int(m["preempted"]),
            "moves": int(m["moves"]),
            "shm_read_us": shm_us,
            "queue_roundtrip_us": queue_us,
            "processes": proc_table(shared),
        }
    finally:
        robot.close()
        stop_children(shared, procs)


# ---------------- report ----------------

def _f(v, pct=False):
    if v is None:
        return "—"
    return f"{v * 100:.0f}%" if pct else f"{v:.3f}"


def _mean(v):
    v = [x for x in v if x is not None]
    return float(np.mean(v)) if v else None


def write_report(results, log=print):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = RESULTS / stamp
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    lines = [f"# Benchmark {stamp}", ""]
    if "system" in results:
        s = results["system"]
        lines += ["## System (multi-process runtime, simulated hardware)", "",
                  "| Metric | p50 | p95 | max |", "| --- | --- | --- | --- |",
                  f"| Command → motor process (ms) | {_n(s['cmd_latency_ms']['p50'])} | {_n(s['cmd_latency_ms']['p95'])} | {_n(s['cmd_latency_ms']['max'])} |",
                  f"| Sensor sample age at safety check (ms) | {_n(s['sensor_age_at_check_ms']['p50'])} | {_n(s['sensor_age_at_check_ms']['p95'])} | {_n(s['sensor_age_at_check_ms']['max'])} |",
                  "", f"- Moves preempted by a newer command: {s['preempted_moves']} of {s['moves']}",
                  f"- Shared-memory read: {s['shm_read_us']:.1f} µs  ·  multiprocessing.Queue round trip: {s['queue_roundtrip_us']:.0f} µs", "",
                  "| Process | Core | Priority | Loop Hz |", "| --- | --- | --- | --- |"]
        for p in s["processes"]:
            prio = p["policy"].upper() + f" {p['priority']}" if p["policy"] != "other" else ("default (not Linux)" if p["nice"] is None else f"nice {p['nice']}")
            lines.append(f"| {p['role']} | {p['core'] if p['core'] is not None else 'any'} | {prio} | {_n(p['loop_hz'])} |")
        lines.append("")
    if "images" in results:
        r = results["images"]
        lines += [f"## Detection under lighting conditions ({r['images']} COCO val2017 images, robot view {AppConfig().camera.width} px, imgsz {r['imgsz']}, {r['threads']} thread)", "",
                  f"Model: `{Path(r['model']).name}` · P/R at score ≥ {r['op_conf']} · classes: {', '.join(r['classes'])}", "",
                  "| Condition | mAP50 | mAP50-95 | vs normal | Precision | Recall | Inference p50 / p95 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for name, m in r["conditions"].items():
            lines.append(f"| {name} ({m['description']}) | {_f(m['map50'])} | {_f(m['map'])} | {_f(m['map50_vs_normal'], True)} | "
                         f"{_f(m['precision'], True)} | {_f(m['recall'], True)} | {_n(m['infer_p50_ms'])} / {_n(m['infer_p95_ms'])} ms |")
        normal = r["conditions"].get("normal")
        if normal:
            lines += ["", "Per class, normal light (AP50, number of boxes):", "",
                      "| Class | AP50 | Boxes |", "| --- | --- | --- |"]
            for c, v in sorted(normal["per_class"].items(), key=lambda kv: -kv[1]["n_gt"]):
                lines.append(f"| {c} | {_f(v['ap50'])} | {v['n_gt']} |")
        lines.append("")
    if "video" in results:
        v = results["video"]
        lines += [f"## Tracking on video ({len(v['clips'])} clips, detect every N frames + optical flow, {v['threads']} thread)", "",
                  "| Condition | Every | Found | ID switches | IDs | Longest run | Jitter | Agreement with every-frame | CPU ms/frame |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s in v["summary"]:
            lines.append(f"| {s['condition']} | {s['every']} | {_f(s['found'], True)} | {_n(s['id_switches'])} | {_n(s['ids'])} | "
                         f"{_f(s['longest'], True)} | {_f(s['jitter'])} | {_f(s['agreement'], True) if s['every'] != 1 else 'ref'} | {_n(s['cpu_ms_per_frame'])} |")
        lines.append("")
    lines += ["Metric definitions: docs/benchmark.md", ""]
    (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")
    log(f"Report: {folder / 'report.md'}")
    return folder


def _n(v):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"{v:.2f}" if isinstance(v, float) and v < 10 else f"{v:.0f}" if isinstance(v, float) else str(v))
