"""
The outputs/ folder: everything worth keeping from a run, in one place.

    outputs/<date_time>_<mode>/
        session.json        what ran, when, with which settings
        telemetry.csv       sensors, pose, IMU, motors, emotion (5 Hz)
        events.jsonl        everything in the dashboard's event log
        conversation.jsonl  what was said to the assistant and what it answered
        figures/            maps, sensor / IMU / control plots, camera + eyes (PNG, JPEG)
        snapshots/          a camera picture the first time each object type is seen (then at most once a minute)
        calibration/        report.md, calibration.json, calibration.png
    outputs/benchmarks/, outputs/e2e/   copies of benchmark and end-to-end reports

Figures are saved every few minutes, before a map is thrown away, when the program stops, and whenever
"Save figures" is pressed on the dashboard. Matplotlib's object API is used (no pyplot), so saving from a
background thread is safe, and it is only imported when the first figure is drawn.
"""

from __future__ import annotations

import base64
import csv
import json
import math
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import OUTPUTS_DIR
from .imu import tilt_rad
from .shared import fresh_imu

# validated data-viz palette (fixed order) + neutral surfaces
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e4dd", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
ALLOWED_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".csv": "text/csv; charset=utf-8",
                  ".json": "application/json", ".jsonl": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8"}


def new_session_dir(mode, root=None):
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = Path(root or OUTPUTS_DIR) / f"{stamp}_{re.sub(r'[^a-z0-9-]+', '-', mode.lower())}"
    for sub in ("figures", "snapshots", "calibration"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    return folder


def _figure(w, h, nrows=1, ncols=1, **kw):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(w, h), dpi=150, facecolor=SURFACE, layout="constrained")
    FigureCanvasAgg(fig)
    return fig, fig.subplots(nrows, ncols, squeeze=False, **kw)


def style_axes(ax, title=None, xlabel=None, ylabel=None):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=7, length=0)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", fontsize=9, color=INK, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=7, color=INK_2)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=7, color=INK_2)


def legend(ax):
    ax.legend(loc="upper right", fontsize=7, frameon=False, labelcolor=INK_2, ncols=4)


# ---------------- map figures ----------------

def _layer(snapshot, name):
    n = snapshot["size"]
    return np.frombuffer(base64.b64decode(snapshot[name]), dtype=np.uint8).reshape(n, n) / 255.0


def _map_axes(ax, snap, title):
    half = snap["size"] * snap["resolution"] / 2
    style_axes(ax, title, "x (m)", "y (m)")
    ax.grid(False)
    ax.set_aspect("equal")
    trail = np.array(snap["trail"])
    if len(trail) > 1:
        ax.plot(trail[:, 0], trail[:, 1], color=SERIES[0], lw=1.2)
    p = snap["pose"]
    ax.annotate("", xy=(p["x"] + 0.14 * math.cos(p["theta"]), p["y"] + 0.14 * math.sin(p["theta"])), xytext=(p["x"], p["y"]),
                arrowprops={"arrowstyle": "-|>", "color": SERIES[0], "lw": 1.5})
    return (-half, half, -half, half)


def draw_geometric(ax, snap):
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("geo", ["#ffffff", GRID, INK])
    extent = _map_axes(ax, snap, "Geometric map (sonar + IR)")
    ax.imshow(_layer(snap, "geo"), origin="lower", extent=extent, cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
    n, res = snap["size"], snap["resolution"]
    if snap["edges"]:
        e = np.array(snap["edges"])
        ax.scatter((e % n + 0.5) * res + extent[0], (e // n + 0.5) * res + extent[2], s=4, color=SERIES[1], marker="s", label="desk edge")
        legend(ax)


def draw_semantic(ax, snap):
    extent = _map_axes(ax, snap, "Semantic map (recognised objects)")
    ax.imshow(np.full((2, 2), 0.0), extent=extent, cmap="gray_r", vmin=0, vmax=8, origin="lower")
    labels = sorted({o["label"] for o in snap["objects"]})
    for o in snap["objects"]:
        c = SERIES[labels.index(o["label"]) % len(SERIES)]
        ax.scatter([o["x"]], [o["y"]], s=34, color=c, edgecolors=SURFACE, linewidths=1.2, zorder=3)
        ax.annotate(o["label"], (o["x"], o["y"]), xytext=(5, 4), textcoords="offset points", fontsize=7, color=INK)
    if not labels:
        ax.text(0, 0, "No objects yet", ha="center", va="center", fontsize=8, color=INK_2)


def draw_heatmap(fig, ax, snap):
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("conf", [SERIES[0], "#d9d7cf", SERIES[7]])
    extent = _map_axes(ax, snap, "Confidence heatmap")
    im = ax.imshow(_layer(snap, "heat"), origin="lower", extent=extent, cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
    bar = fig.colorbar(im, ax=ax, shrink=0.8, ticks=[0, 0.5, 1])
    bar.ax.set_yticklabels(["empty", "unknown", "object"], fontsize=7, color=INK_2)
    bar.outline.set_visible(False)


# ---------------- recorder ----------------

TELEMETRY = ["time_s", "x", "y", "heading_deg", "front", "left", "right", "rear", "front_floor", "rear_floor", "wheel_left",
             "wheel_right", "roll_deg", "pitch_deg", "tilt_deg", "yaw_deg", "gyro_z", "accel_err", "lifted", "emotion", "persons"]


class OutputRecorder:
    def __init__(self, ctx, app, cfg, mode):
        self.robot, self.mapper, self.vision = ctx["robot"], ctx["mapper"], ctx["vision"]
        self.s, self.app, self.cfg = ctx["shared"], app, cfg
        self.folder = new_session_dir(mode)
        self.figures_dir = self.folder / "figures"
        self.rows = deque(maxlen=int(cfg.telemetry_hz * 600))      # last 10 minutes, for the plots
        self.started = time.monotonic()
        self.saving = False
        self.last_saved = None
        self.auto_figures = 0
        self.snapshots = 0
        self.last_snapshot = {}
        self.next_event = 0
        self.next_turn = 0
        self.next_figure = self.started + cfg.figure_every_s
        self._save_lock = threading.Lock()
        self._running = False
        self._csv_file = (self.folder / "telemetry.csv").open("w", newline="", encoding="utf-8", buffering=1)
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow(TELEMETRY)
        (self.folder / "session.json").write_text(json.dumps({
            "started": datetime.now().isoformat(timespec="seconds"), "mode": mode, "sim": ctx["sim"], "camera": ctx["camera"],
        }, indent=2), encoding="utf-8")

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="outputs", daemon=True).start()
        return self

    def _loop(self):
        period = 1.0 / self.cfg.telemetry_hz
        tick = 0
        while self._running:
            t0 = time.monotonic()
            try:
                self._sample(t0)
                tick += 1
                if tick % int(self.cfg.telemetry_hz) == 0:
                    self._write_logs()
                    self._snapshot_new_objects(t0)
                if t0 >= self.next_figure and self.auto_figures < self.cfg.max_auto_figures:
                    self.next_figure = t0 + self.cfg.figure_every_s
                    self.auto_figures += 1
                    self.save_all("automatic")
            except Exception as exc:     # saving must never disturb the robot
                print(f"[SAVE ] {exc}", flush=True)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    def _sample(self, now):
        r = self.robot.latest_reading()
        d = r.get("distances") or {}
        m = self.robot.motor_state()
        imu = fresh_imu(self.s, now)
        o = self.mapper.odom
        res = self.vision.latest() if self.vision else None
        persons = sum(1 for x in res.detections if x.label == "person") if res else 0
        deg = lambda v: None if imu is None else round(math.degrees(v), 2)   # noqa: E731
        row = [round(now - self.started, 2), round(o.x, 3), round(o.y, 3), round(math.degrees(o.theta), 1),
               *[None if d.get(k) is None else round(d[k], 3) for k in ("front", "left", "right", "rear")],
               r.get("front_floor"), r.get("back_floor"), m["left"], m["right"],
               deg(imu["roll"]) if imu else None, deg(imu["pitch"]) if imu else None,
               deg(tilt_rad(imu)) if imu else None, deg(imu["yaw"]) if imu else None,
               round(imu["gz"], 3) if imu else None, round(imu["accel_err"], 3) if imu else None,
               int(self.app.lift.lifted), self.app.emotion.emotion, persons]
        self.rows.append(row)
        self._csv.writerow(["" if v is None or v != v else v for v in row])

    def _append_jsonl(self, name, items):
        with (self.folder / name).open("a", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _write_logs(self):
        with self.robot._lock:
            events = [e for e in self.robot.events if e["id"] > self.next_event]
        if events:
            self.next_event = events[-1]["id"]
            self._append_jsonl("events.jsonl", events)
        turns = [t for t in self.app.assistant.status()["log"] if t["id"] > self.next_turn]
        if turns:
            self.next_turn = turns[-1]["id"]
            self._append_jsonl("conversation.jsonl", turns)

    def _snapshot_new_objects(self, now):
        if self.vision is None or self.snapshots >= self.cfg.max_detection_snapshots:
            return
        res = self.vision.latest()
        if res is None:
            return
        new = [d.label for d in res.detections
               if d.score >= 0.5 and now - self.last_snapshot.get(d.label, -1e9) >= self.cfg.detection_cooldown_s]
        if not new:
            return
        jpeg = self.vision.jpeg()
        if jpeg:
            for label in new:
                self.last_snapshot[label] = now
            self.snapshots += 1
            name = f"{datetime.now().strftime('%H-%M-%S')}_{re.sub(r'[^a-z0-9]+', '-', '_'.join(sorted(set(new))))[:60]}.jpg"
            (self.folder / "snapshots" / name).write_bytes(jpeg)

    # -- figures --

    def _series(self):
        rows = list(self.rows)
        if not rows:
            return None
        return {name: np.array([np.nan if r[i] is None or isinstance(r[i], str) else float(r[i]) for r in rows])
                for i, name in enumerate(TELEMETRY) if name != "emotion"}

    def _save(self, fig, stem, folder, saved):
        path = folder / f"{stem}.png"
        fig.savefig(path, facecolor=SURFACE)
        saved.append(path)

    def save_all(self, reason="manual", snap=None):
        """Draw and save every figure now. Returns the list of files. One save runs at a time.
        snap: a map snapshot taken earlier (to keep a map that is about to be cleared)."""
        with self._save_lock:
            self.saving = True
            try:
                stamp = datetime.now().strftime("%H-%M-%S")
                folder = self.figures_dir / f"{stamp}_{re.sub(r'[^a-z0-9]+', '-', reason.lower())}"
                folder.mkdir(parents=True, exist_ok=True)
                saved = self._draw_all(folder, snap)
                self.last_saved = {"t": time.time(), "reason": reason, "folder": self.relative(folder),
                                   "files": [self.relative(p) for p in saved]}
                self.robot.log("info", f"Saved {len(saved)} figures to {folder}")
                return saved
            finally:
                self.saving = False

    def save_async(self, reason="dashboard", snap=None):
        """Save in the background. With `snap` the save always runs (after any save in progress)."""
        if self.saving and snap is None:
            return False
        self.saving = True
        threading.Thread(target=self._save_guarded, args=(reason, snap), name="save-figures", daemon=True).start()
        return True

    def _save_guarded(self, reason, snap=None):
        try:
            self.save_all(reason, snap)
        except Exception as exc:
            self.saving = False
            self.app.alerts.warn("outputs", "I couldn't save the figures.", speak=False, detail=str(exc))

    def _draw_all(self, folder, snap=None):
        saved = []
        snap = snap or self.mapper.snapshot()
        for stem, draw in (("map_geometric", lambda f, a: draw_geometric(a, snap)),
                           ("map_semantic", lambda f, a: draw_semantic(a, snap)),
                           ("map_heatmap", lambda f, a: draw_heatmap(f, a, snap))):
            fig, axes = _figure(5, 4.6)
            draw(fig, axes[0][0])
            self._save(fig, stem, folder, saved)
        fig, axes = _figure(12, 4.2, 1, 3)
        draw_geometric(axes[0][0], snap)
        draw_semantic(axes[0][1], snap)
        draw_heatmap(fig, axes[0][2], snap)
        self._save(fig, "maps_overview", folder, saved)

        s = self._series()
        if s is not None and len(s["time_s"]) > 1:
            self._plot_sensors(s, folder, saved)
            self._plot_imu(s, folder, saved)
        self._plot_control(folder, saved)

        if self.vision is not None:
            jpeg = self.vision.jpeg()
            if jpeg:
                (folder / "camera.jpg").write_bytes(jpeg)
                saved.append(folder / "camera.jpg")
        png = self.app.face_png()
        if png:
            (folder / "eyes.png").write_bytes(png)
            saved.append(folder / "eyes.png")
        return saved

    def _plot_sensors(self, s, folder, saved):
        fig, axes = _figure(8, 3.2)
        ax = axes[0][0]
        style_axes(ax, "Ultrasonic distances", "time (s)", "distance (m)")
        for i, k in enumerate(("front", "left", "right", "rear")):
            ax.plot(s["time_s"], s[k], color=SERIES[i], lw=1.4, label=k)
        legend(ax)
        self._save(fig, "sensors", folder, saved)

    def _plot_imu(self, s, folder, saved):
        if not np.isfinite(s["yaw_deg"]).any():
            return
        fig, axes = _figure(8, 5.2, 3, 1, sharex=True)
        for ax, key, title, unit in ((axes[0][0], "tilt_deg", "Tilt", "deg"), (axes[1][0], "yaw_deg", "Heading (gyro)", "deg"),
                                     (axes[2][0], "gyro_z", "Turn rate", "rad/s")):
            style_axes(ax, title, None, unit)
            ax.plot(s["time_s"], s[key], color=SERIES[0], lw=1.4)
        axes[2][0].set_xlabel("time (s)", fontsize=7, color=INK_2)
        self._save(fig, "imu", folder, saved)

    def _plot_control(self, folder, saved):
        loops = {}
        for t, mode, sp, pv, _ in self.app.control_history():
            loops.setdefault(mode, []).append((t - self.started, sp, pv))
        if not loops:
            return
        fig, axes = _figure(8, 2.3 * len(loops), len(loops), 1)
        for ax, (mode, rows) in zip(axes[:, 0], sorted(loops.items())):
            a = np.array(rows)
            gaps = np.flatnonzero(np.diff(a[:, 0]) > 1.0) + 1      # separate moves stay separate lines
            a = np.insert(a, gaps, np.nan, axis=0)
            style_axes(ax, f"Control loop: {mode}", "time (s)", "rad/s" if mode == "turn rate" else "rad")
            ax.plot(a[:, 0], a[:, 1], color=SERIES[1], lw=1.4, label="target")
            ax.plot(a[:, 0], a[:, 2], color=SERIES[0], lw=1.4, label="measured")
            legend(ax)
        self._save(fig, "control_loops", folder, saved)

    # -- files --

    def relative(self, path):
        return Path(path).resolve().relative_to(OUTPUTS_DIR.resolve()).as_posix()

    def recent_files(self, limit=30):
        files = [p for p in self.folder.rglob("*") if p.is_file() and p.suffix in ALLOWED_SUFFIX]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"path": self.relative(p), "name": p.name, "kb": round(p.stat().st_size / 1024, 1)} for p in files[:limit]]

    def status(self):
        return {"folder": str(self.folder), "saving": self.saving, "last": self.last_saved, "files": self.recent_files()}

    def close(self):
        self._running = False
        try:
            self._write_logs()
            self.save_all("final")
        except Exception as exc:
            print(f"[SAVE ] final figures failed: {exc}", flush=True)
        finally:
            self._csv_file.close()


def resolve_download(rel):
    """A file inside outputs/ for the dashboard, or None. Blocks path traversal and other file types."""
    root = OUTPUTS_DIR.resolve()
    try:
        path = (root / rel).resolve()
        path.relative_to(root)
    except (ValueError, OSError):
        return None
    if path.suffix.lower() not in ALLOWED_SUFFIX or not path.is_file():
        return None
    return path
