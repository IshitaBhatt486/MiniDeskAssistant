"""
Interactive sensor tests (motors are never touched).

    python -m deskbot sensors            menu
    python -m deskbot sensors camera     straight to one test

Tests
    ultrasonic front/left/right/rear, front/rear IR   one sensor at a time, like hardware_test.py sensors
    all                                              every ultrasonic + IR in one live table
    camera                                           live camera image IN THE TERMINAL (works over SSH)
    detect                                           camera + YOLO26n (NCNN) + ByteTrack: boxes drawn into the
                                                     terminal image, detections, fps and latency listed

The camera tests work with the Pi camera, a webcam (--camera webcam) or the simulator (--camera sim).
Only the device being tested is opened, and it is closed again afterwards.
"""

from __future__ import annotations

import sys
import time

from .. import ROOT  # noqa: F401  (puts run_prototype + hardware_tests on sys.path)
from .. import ui
from ..config import AppConfig

MAX_DISTANCE = 2.0
INTERVAL = 0.2
FLOOR_VALUE = 0


def _sensor_table():
    import robot_config as cfg
    rows = [(f"{n} ultrasonic", "sonar", p) for n, p in cfg.SONARS.items()]
    rows += [("front IR", "ir", cfg.IR_FRONT), ("rear IR", "ir", cfg.IR_BACK)]
    return cfg, rows


def _pin_text(cfg, kind, pins):
    if kind == "sonar":
        t, e = pins["trigger"], pins["echo"]
        return f"TRIG GPIO {t} (pin {cfg.PHYSICAL_PIN[t]}), ECHO GPIO {e} (pin {cfg.PHYSICAL_PIN[e]})"
    return f"OUT GPIO {pins} (pin {cfg.PHYSICAL_PIN[pins]})"


def _fmt_cm(m):
    cm = m * 100
    return f">{MAX_DISTANCE * 100:.0f} cm (no echo)" if cm >= MAX_DISTANCE * 100 - 0.5 else f"{cm:6.1f} cm"


# ---------------- GPIO sensors ----------------

def stream_gpio(name):
    from gpiozero import DigitalInputDevice, DistanceSensor

    cfg, rows = _sensor_table()
    _, kind, pins = next(r for r in rows if r[0] == name)
    ui.out(f"\n[bold]{name}[/bold]: {_pin_text(cfg, kind, pins)}")
    ui.out("[dim]Press Enter to stop.[/dim]\n")
    if kind == "sonar":
        dev = DistanceSensor(echo=pins["echo"], trigger=pins["trigger"], max_distance=MAX_DISTANCE, queue_len=1)
        read = lambda: _fmt_cm(dev.distance)  # noqa: E731
    else:
        dev = DigitalInputDevice(pins)
        read = lambda: f"{dev.value}  {'floor' if dev.value == FLOOR_VALUE else 'EDGE / no floor'}"  # noqa: E731
    stop = ui.enter_to_stop()
    try:
        while not stop.is_set():
            print(f"{name}: {read()}", flush=True)
            stop.wait(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    ui.out("Stopped.")


def stream_all():
    """Every ultrasonic + IR in one live table. Sonars are triggered one at a time (gpiozero
    serialises them per pin), so there is less crosstalk than firing them together."""
    from gpiozero import DigitalInputDevice, DistanceSensor

    cfg, rows = _sensor_table()
    devs = []
    try:
        for name, kind, pins in rows:
            if kind == "sonar":
                devs.append((name, kind, DistanceSensor(echo=pins["echo"], trigger=pins["trigger"], max_distance=MAX_DISTANCE, queue_len=1)))
            else:
                devs.append((name, kind, DigitalInputDevice(pins)))
        stop = ui.enter_to_stop()

        def snapshot():
            out = []
            for name, kind, d in devs:
                if kind == "sonar":
                    out.append((name, _fmt_cm(d.distance)))
                else:
                    out.append((name, "floor" if d.value == FLOOR_VALUE else "EDGE"))
            return out

        if ui.RICH:
            from rich.live import Live
            from rich.table import Table

            def render():
                t = Table(title="All sensors (Enter to stop)", title_justify="left", border_style="dim")
                t.add_column("Sensor")
                t.add_column("Reading", justify="right")
                for n, v in snapshot():
                    t.add_row(n, f"[yellow]{v}[/yellow]" if "EDGE" in v else v)
                return t

            with Live(render(), console=ui.console, refresh_per_second=5) as live:
                while not stop.is_set():
                    live.update(render())
                    stop.wait(INTERVAL)
        else:
            while not stop.is_set():
                print(" | ".join(f"{n}: {v}" for n, v in snapshot()), flush=True)
                stop.wait(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        for _, _, d in devs:
            d.close()
    ui.out("Stopped.")


# ---------------- camera ----------------

def _open_source(camera, cfg):
    from ..vision.camera import open_camera

    hw = None
    if camera == "sim":
        from ..robot import FusionSimHardware
        hw = FusionSimHardware()
    return open_camera(camera, cfg.camera, hw)


def _terminal_loop(grab_text, width=0, ascii_mode=False):
    """Draw frames in place until Enter. grab_text() -> (bgr image, status line)."""
    from hardware_test import render  # hardware_tests/: the proven terminal renderer

    stop = ui.enter_to_stop()
    sys.stdout.write("\x1b[2J\x1b[?25l")
    frames = 0
    try:
        while not stop.is_set():
            img, status = grab_text()
            if img is False:  # no new result: don't redraw (a busy loop here steals the GIL from the detector)
                time.sleep(0.02)
                continue
            if img is None:  # nothing to draw yet: still show why (e.g. camera error)
                sys.stdout.write(f"\x1b[H\x1b[0m{status or 'Waiting for the first frame...'}  - Enter to stop\x1b[K\n")
                sys.stdout.flush()
                time.sleep(0.25)
                continue
            frame = render(img[:, :, ::-1], width, ascii_mode)  # BGR -> RGB
            frames += 1
            sys.stdout.write(f"\x1b[H{frame}\n\x1b[0m{status}  - Enter to stop\x1b[K\n\x1b[J")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")
        sys.stdout.flush()
    return frames


def camera_preview(camera="pi", width=0, ascii_mode=False):
    cfg = AppConfig()
    try:
        src = _open_source(camera, cfg)
    except Exception as exc:
        ui.fail(f"Could not open the camera: {exc}")
        return
    ui.ok(f"Camera opened: {getattr(src, 'model', camera)}  {cfg.camera.width}x{cfg.camera.height}")
    times = []

    def grab():
        t, img, _ = src.read()
        times.append(t)
        del times[:-20]
        fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0
        return img, f"Camera {fps:4.1f} fps"

    try:
        n = _terminal_loop(grab, width, ascii_mode)
    finally:
        src.close()
    ui.out(f"Stopped after {n} frames.")


def detect_live(camera="pi", width=0, ascii_mode=False):
    """Camera -> YOLO26n NCNN + ByteTrack, drawn into the terminal with live stats."""
    from ..vision.camera import FrameGrabber
    from ..vision.pipeline import VisionPipeline

    cfg = AppConfig()
    # detector before camera (see web/server.py build_vision)
    try:
        if camera == "sim":
            from ..vision.detector import SimDetector
            det = SimDetector()
        else:
            from ..vision.detector import make_detector
            from ..vision.model import resolve_model
            ui.out("Loading YOLO26n...")
            det = make_detector(cfg.vision, resolve_model(cfg.vision, log=ui.out))
    except Exception as exc:
        ui.fail(f"Could not load the detector: {exc}")
        return
    try:
        src = _open_source(camera, cfg)
    except Exception as exc:
        ui.fail(f"Could not open the camera: {exc}")
        return
    pipe =VisionPipeline(FrameGrabber(src).start(), det, cfg.camera, cfg.vision).start()

    shown = {"seq": None, "t": 0.0}

    def grab():
        res = pipe.latest()
        if res is not None and res.seq == shown["seq"]:
            return False, None
        if res is None and time.monotonic() - shown["t"] < 0.5:
            return False, None
        shown["t"] = time.monotonic()
        st = pipe.status()
        if res is None:
            return None, (f"Problem: {st['error']}" if st["error"] else "Warming up the detector...")
        shown["seq"] = res.seq
        import cv2
        import numpy as np
        data = pipe.jpeg()  # boxes drawn exactly like the dashboard stream
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else res.image
        names = ", ".join(f"{d['label']}{'#' + str(d['track_id']) if d['track_id'] is not None else ''}" for d in st["detections"]) or "nothing"
        return img, (f"{st['detect_fps']:4.1f} fps  infer {st['infer_ms'] or 0:5.1f} ms  "
                     f"frame->result {st['latency_ms'] or 0:5.1f} ms  |  {names}")

    try:
        _terminal_loop(grab, width, ascii_mode)
    finally:
        st = pipe.status()
        pipe.stop()
    ui.out(f"Detector {st['detector']}: {st['detect_fps']} fps, inference {st['infer_ms']} ms, "
           f"capture->result {st['latency_ms']} ms")


# ---------------- menu ----------------

def menu(camera="pi"):
    while True:
        try:
            cfg, rows = _sensor_table()
            options = [(f"{name:<18} {_pin_text(cfg, kind, pins)}", ("gpio", name)) for name, kind, pins in rows]
        except Exception:
            options = []
        options += [
            ("All ultrasonic + IR sensors at once (live table)", ("all", None)),
            (f"Camera preview in the terminal ({camera})", ("camera", None)),
            (f"Camera + object detection: YOLO26n + ByteTrack ({camera})", ("detect", None)),
            ("Back", None),
        ]
        choice = ui.choose("Which sensor do you want to test? (motors are never used)", options)
        if choice is None:
            return
        run_test(*choice, camera=camera)


def run_test(kind, name=None, camera="pi"):
    try:
        if kind == "gpio":
            stream_gpio(name)
        elif kind == "all":
            stream_all()
        elif kind == "camera":
            camera_preview(camera)
        elif kind == "detect":
            detect_live(camera)
    except ImportError as exc:
        ui.fail(f"{exc}. GPIO tests need the Pi (gpiozero); camera tests need picamera2 or --camera webcam/sim.")
    except Exception as exc:  # e.g. GPIO busy because the robot app is running
        ui.fail(f"Test failed: {exc}")
        if "busy" in str(exc).lower() or "in use" in str(exc).lower():
            ui.warn("Another robot program is using these pins/camera. Stop it first.")


def run_by_name(name, camera="pi"):
    """Non-interactive entry: name = front|left|right|rear|front-ir|rear-ir|all|camera|detect."""
    alias = {"front": "front ultrasonic", "left": "left ultrasonic", "right": "right ultrasonic",
             "rear": "rear ultrasonic", "front-ir": "front IR", "rear-ir": "rear IR"}
    if name in ("all", "camera", "detect"):
        return run_test(name, camera=camera)
    if name in alias:
        return run_test("gpio", alias[name], camera=camera)
    ui.fail(f"Unknown sensor {name!r}. Use one of: {', '.join(list(alias) + ['all', 'camera', 'detect'])}")
