"""
deskbot command line.

    python -m deskbot                      interactive menu (arrow keys + Enter)
    python -m deskbot run [--sim] [--lan] [--camera pi|webcam|sim|none|<index>|<video>] [--port 8000]
    python -m deskbot sensors [front|left|right|rear|front-ir|rear-ir|all|camera|detect] [--camera ...]
    python -m deskbot model export|bench|info
    python -m deskbot doctor
    python -m deskbot bench download|images|video|system|all [options]
    python -m deskbot test
    python -m deskbot pins

The scripts in scripts/ are one-word wrappers around these.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys

from . import ROOT, __version__, ui
from .config import AppConfig


# ---------------- actions ----------------

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outgoing interface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def cmd_run(sim=False, lan=False, host=None, port=8000, camera=None, single_process=False):
    if single_process:
        from .web.server import run_app          # everything in one process (threads), the 15 Nov design
    else:
        from .runtime.app import run_runtime as run_app   # 4 processes, one per core (default)

    host = host or ("0.0.0.0" if lan else "127.0.0.1")
    camera = camera or ("sim" if sim else "pi")
    ui.header("Starting the desk robot" + (" (simulation)" if sim else ""),
              f"robot + 4 sonars + IR + camera ({camera}) + fusion maps + dashboard"
              + (" · single process" if single_process else " · 4 processes: motor / sensors / camera / nav"))
    ui.out(f"Open [bold]http://localhost:{port}[/bold]" + (f"  or  [bold]http://{lan_ip()}:{port}[/bold] from another device" if host == "0.0.0.0" and lan_ip() else ""))
    if host == "0.0.0.0":
        ui.warn("Listening on the network with no login: anyone on this Wi-Fi can drive the robot.")
    ui.out("[dim]Ctrl+C stops the motors and quits.[/dim]\n")
    try:
        run_app(sim=sim, host=host, port=port, camera=camera)
    except OSError as exc:
        ui.fail(f"Could not start: {exc}")
        if "address" in str(exc).lower() or getattr(exc, "errno", None) in (98, 10048):
            ui.warn(f"Port {port} is in use - is the app already running? Try --port {port + 1}.")
        return 1
    except Exception as exc:
        ui.fail(f"Could not start: {exc}")
        if not sim:
            ui.warn("Not on the Pi (or GPIO busy)? Use the simulation: scripts/sim.sh  or  python -m deskbot run --sim")
        return 1
    return 0


def cmd_assistant(sim=False, lan=False, host=None, port=8000, camera=None, https_port=8443):
    """The 17 Nov assistant runtime: 4 processes + voice assistant + presence + remote (deskbot/assistant/)."""
    from .assistant.app import run_assistant

    host = host or ("0.0.0.0" if lan else "127.0.0.1")
    camera = camera or ("sim" if sim else "pi")
    ui.header("Starting the desk robot assistant" + (" (simulation)" if sim else ""),
              f"voice + AI + chipmunk speaker + Bluetooth presence + lift detection + camera ({camera}) + maps")
    ip = lan_ip()
    ui.out(f"Dashboard  [bold]http://localhost:{port}[/bold]" + (f"   ·   remote  [bold]http://{ip}:{port}/remote[/bold]" if host == "0.0.0.0" and ip else ""))
    if https_port and host == "0.0.0.0" and ip:
        ui.out(f"Microphone (phones/laptops) needs HTTPS: [bold]https://{ip}:{https_port}/remote[/bold]  (accept the certificate warning once)")
    if host == "0.0.0.0":
        ui.warn("Listening on the network with no login: anyone on this Wi-Fi (or the robot's hotspot) can drive it.")
    ui.out("[dim]Ctrl+C stops the motors and quits.[/dim]\n")
    try:
        run_assistant(sim=sim, host=host, port=port, camera=camera, https_port=https_port)
    except OSError as exc:
        ui.fail(f"Could not start: {exc}")
        if "address" in str(exc).lower() or getattr(exc, "errno", None) in (98, 10048):
            ui.warn(f"Port {port} is in use - is the app already running (maybe the systemd service)? "
                    f"Try --port {port + 1}, or: sudo systemctl stop deskbot")
        return 1
    except Exception as exc:
        ui.fail(f"Could not start: {exc}")
        if not sim:
            ui.warn("Not on the Pi (or GPIO busy)? Use the simulation: scripts/assistant.sh --sim")
        return 1
    return 0


def cmd_model(action):
    from .vision import model

    cfg = AppConfig()
    if action == "export":
        try:
            model.export_model(cfg.vision, log=ui.out)
        except Exception as exc:
            ui.fail(f"Export failed: {exc}")
            if "Application Control" in str(exc):
                ui.warn("Windows Smart App Control blocked the PNNX converter. Export on the Pi instead; "
                        "on this PC the app falls back to the PyTorch weights.")
            return 1
        return 0
    if action == "bench":
        ui.out(f"Benchmarking detect + track at imgsz {cfg.vision.imgsz} on a {cfg.camera.width}x{cfg.camera.height} frame...")
        r = model.benchmark(cfg.vision, cfg.camera, log=ui.out)
        ui.table("YOLO26n + ByteTrack", ["Model", "Threads", "Mean", "p50", "p95", "FPS"],
                 [(r["model"].split("models")[-1].strip("/\\"), r["threads"] or "default", f"{r['mean_ms']} ms",
                   f"{r['p50_ms']} ms", f"{r['p95_ms']} ms", r["fps"])])
        ui.out(f"Detected on the sample photo: {', '.join(r['detections']) or 'nothing'}")
        return 0
    m = model.find_model(cfg.vision)
    ui.table("Model", ["Item", "Value"], [
        ("Model", cfg.vision.model_name), ("Input size", cfg.vision.imgsz),
        ("NCNN export", m or "not exported yet (python -m deskbot model export)"),
        ("Tracker", "ByteTrack (deskbot/vision/bytetrack.yaml)"), ("Threads", cfg.vision.threads),
        ("Cost", "free - runs entirely on the device"),
    ])
    return 0


def cmd_bench(action="all", images=300, clips=2, limit=None, conditions=None, every="1,3,5",
              video=None, label=None, threads=1, max_frames=300):
    sys.path.insert(0, str(ROOT.parent / "benchmarks"))
    try:
        from desk_bench import datasets, lighting, run
    except ImportError:
        ui.fail("Benchmarks aren't part of run_prototype. Run them from the full repository (benchmarks/).")
        return 2

    conds = [c.strip() for c in conditions.split(",")] if conditions else None
    for c in conds or []:
        if c not in lighting.CONDITIONS:
            ui.fail(f"Unknown condition {c!r}. Choose from: {', '.join(lighting.CONDITIONS)}")
            return 2
    everies = tuple(int(x) for x in every.split(","))
    ui.header("Benchmark", "detection under lighting (COCO) · tracking on video (Objectron) · runtime latency")
    results = {}
    try:
        if action in ("download", "all"):
            if not (datasets.coco_subset_path().exists() and len(datasets.load_coco()["images"]) >= min(images, 1)) or action == "download":
                datasets.download_coco(images, log=ui.out)
            if video is None and (action == "download" or not datasets.local_clips()):
                datasets.download_objectron(clips, log=ui.out)
            if action == "download":
                ui.ok("Benchmark data ready in benchmarks/data/")
                return 0
        if action in ("system", "all"):
            ui.out("[bold]System[/bold]: multi-process runtime on the simulated robot")
            results["system"] = run.bench_system(log=ui.out)
        if action in ("images", "all"):
            ui.out("[bold]Images[/bold]: YOLO26n on COCO desk objects under each lighting condition")
            results["images"] = run.bench_images(conds, limit, threads, log=ui.out)
        if action in ("video", "all"):
            ui.out("[bold]Video[/bold]: tracking with detection every " + ", ".join(map(str, everies)) + " frames")
            clips_list = [(video, label)] if video else None
            if video and not label:
                ui.fail("--video needs --label (the COCO name of the object in it, e.g. cup)")
                return 2
            results["video"] = run.bench_video(clips_list, everies, conds if action == "video" and conds else None,
                                               threads, max_frames, log=ui.out)
    except FileNotFoundError as exc:
        ui.fail(str(exc))
        return 1
    except Exception as exc:
        ui.fail(f"Benchmark failed: {exc}")
        return 1
    if results:
        folder = run.write_report(results, log=ui.out)
        ui.ok(f"Done. Open {folder / 'report.md'}")
    return 0


def cmd_test(verbose=False):
    ui.header("Unit tests", "tests/ - run anywhere, no hardware needed")
    if not (ROOT.parent / "tests").is_dir():
        ui.fail("The unit tests aren't part of run_prototype. Run them from the full repository.")
        return 2
    args = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."] + (["-v"] if verbose else [])
    return subprocess.call(args, cwd=ROOT.parent)


def cmd_pins():
    import robot_config as cfg
    ui.table("Wiring (robot_config.py)", ["Signal", "GPIO", "Physical pin"],
             [(label, pin, cfg.PHYSICAL_PIN[pin]) for label, pin in cfg.all_pins()])
    c = AppConfig().camera
    ui.table("Camera (deskbot/config.py)", ["Setting", "Value"], [
        ("Capture", f"{c.width}x{c.height} @ {c.fps} fps"), ("Field of view", f"{c.hfov_deg}° x {c.vfov_deg}°"),
        ("Mount", f"{c.x * 100:.0f} cm ahead, {c.height_m * 100:.0f} cm high, tilted {c.pitch_deg}° down"),
    ])
    return 0


# ---------------- interactive menu ----------------

def _ask_camera(default):
    return ui.choose("Which camera?", [
        ("Raspberry Pi camera", "pi"), ("USB webcam", "webcam"),
        ("Simulated camera (sees the simulated desk)", "sim"), ("No camera (maps from sonar + IR only)", "none"),
    ], default=default)


def menu():
    ui.header(f"Desk Assistant Robot  v{__version__}", "↑/↓ to move, Enter to choose, Ctrl+C to go back")
    while True:
        choice = ui.choose("What do you want to do?", [
            ("🗣  Start the assistant (voice + AI + remote + presence)", "assistant"),
            ("🗣  Assistant in simulation (no hardware needed)", "assistant-sim"),
            ("▶  Start the robot (dashboard + maps + vision)", "run"),
            ("▶  Start in simulation (no hardware needed)", "sim"),
            ("🔧 Test sensors (ultrasonic, IR, camera, detection)", "sensors"),
            ("👁  Vision model: export / benchmark / info", "model"),
            ("🩺 System check", "doctor"),
            ("📊 Benchmark (lighting, tracking, latency)", "bench"),
            ("✅ Run unit tests", "test"),
            ("📌 Show wiring + camera config", "pins"),
            ("Quit", "quit"),
        ])
        if choice in (None, "quit"):
            ui.out("Bye.")
            return 0
        if choice in ("assistant", "assistant-sim"):
            sim = choice == "assistant-sim"
            camera = _ask_camera("sim" if sim else "pi")
            if camera is None:
                continue
            lan = ui.confirm("Open the dashboard + remote to other devices (phone/laptop)?", default=True)
            cmd_assistant(sim=sim, lan=lan, camera=camera)
            ui.pause()
        elif choice in ("run", "sim"):
            sim = choice == "sim"
            camera = _ask_camera("sim" if sim else "pi")
            if camera is None:
                continue
            lan = ui.confirm("Open the dashboard to other devices on this network (phone/laptop)?", default=False)
            port = ui.ask("Port", 8000)
            if port is None:
                continue
            cmd_run(sim=sim, lan=lan, port=int(port) if str(port).isdigit() else 8000, camera=camera)
            ui.pause()
        elif choice == "sensors":
            from .checks import sensors
            camera = _ask_camera("pi")
            if camera and camera != "none":
                sensors.menu(camera)
        elif choice == "model":
            action = ui.choose("Model", [("Info", "info"), ("Export to NCNN (once, ~1 min)", "export"),
                                         ("Benchmark detect + track latency", "bench"), ("Back", None)])
            if action:
                cmd_model(action)
                ui.pause()
        elif choice == "bench":
            action = ui.choose("Benchmark", [
                ("Everything (downloads data the first time, ~420 MB)", "all"),
                ("Download the datasets only", "download"),
                ("Detection under lighting conditions (COCO)", "images"),
                ("Tracking on video, detect every 1/3/5 frames (Objectron)", "video"),
                ("Runtime latency (processes, commands, sensors)", "system"),
                ("Back", None)])
            if action:
                cmd_bench(action)
                ui.pause()
        elif choice == "doctor":
            from .checks import doctor
            doctor.run()
            ui.pause()
        elif choice == "test":
            cmd_test()
            ui.pause()
        elif choice == "pins":
            cmd_pins()
            ui.pause()


# ---------------- argparse ----------------

def build_parser():
    p = argparse.ArgumentParser(prog="deskbot", description="Desk assistant robot: run the app, test sensors, manage the vision model.")
    p.add_argument("--version", action="version", version=f"deskbot {__version__}")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="start robot + maps + vision + dashboard")
    r.add_argument("--sim", action="store_true", help="simulated robot and desk (no hardware)")
    r.add_argument("--lan", action="store_true", help="listen on all interfaces (other devices can open the dashboard)")
    r.add_argument("--host", help="bind address (overrides --lan)")
    r.add_argument("--port", type=int, default=8000)
    r.add_argument("--camera", help="pi | webcam | sim | none | <webcam index> | <video file>  (default: pi, or sim with --sim)")
    r.add_argument("--single-process", action="store_true", help="the older one-process app (threads, no core pinning)")

    a = sub.add_parser("assistant", help="robot + voice assistant + AI + remote control + Bluetooth presence")
    a.add_argument("--sim", action="store_true", help="simulated robot, desk, camera and phone (no hardware)")
    a.add_argument("--lan", action="store_true", help="listen on all interfaces (phones/laptops on the Wi-Fi or hotspot)")
    a.add_argument("--host", help="bind address (overrides --lan)")
    a.add_argument("--port", type=int, default=8000)
    a.add_argument("--https-port", type=int, default=8443, help="HTTPS port for browser microphones (0 = off)")
    a.add_argument("--camera", help="pi | webcam | sim | none | <webcam index> | <video file>")

    s = sub.add_parser("sensors", help="interactive sensor tests (no motors)")
    s.add_argument("name", nargs="?", help="front|left|right|rear|front-ir|rear-ir|all|camera|detect (omit for the menu)")
    s.add_argument("--camera", default="pi", help="camera for camera/detect tests: pi | webcam | sim | <index> | <file>")

    m = sub.add_parser("model", help="YOLO26n NCNN model")
    m.add_argument("action", nargs="?", default="info", choices=["info", "export", "bench"])

    sub.add_parser("doctor", help="check installation, camera, model, pins")
    b = sub.add_parser("bench", help="benchmark detection (lighting), tracking (video) and runtime latency")
    b.add_argument("action", nargs="?", default="all", choices=["all", "download", "images", "video", "system"])
    b.add_argument("--images", type=int, default=300, help="COCO images to download (default 300)")
    b.add_argument("--clips", type=int, default=2, help="Objectron clips per class to download (default 2)")
    b.add_argument("--limit", type=int, help="use only the first N downloaded images")
    b.add_argument("--conditions", help="comma-separated lighting conditions (default: all for images, 4 for video)")
    b.add_argument("--every", default="1,3,5", help="detect every N frames, comma-separated (default 1,3,5)")
    b.add_argument("--video", help="your own video instead of Objectron (needs --label)")
    b.add_argument("--label", help="COCO name of the object in --video, e.g. cup")
    b.add_argument("--threads", type=int, default=1, help="NCNN threads (the runtime gives the camera 1 core)")
    b.add_argument("--max-frames", type=int, default=300, help="frames per clip (default 300 = 10 s)")
    t = sub.add_parser("test", help="run the unit tests")
    t.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("pins", help="print wiring and camera mounting")
    sub.add_parser("menu", help="interactive menu (default)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd in (None, "menu"):
        return menu()
    if args.cmd == "run":
        return cmd_run(sim=args.sim, lan=args.lan, host=args.host, port=args.port, camera=args.camera,
                       single_process=args.single_process)
    if args.cmd == "assistant":
        return cmd_assistant(sim=args.sim, lan=args.lan, host=args.host, port=args.port, camera=args.camera,
                             https_port=args.https_port)
    if args.cmd == "sensors":
        from .checks import sensors
        if args.name:
            sensors.run_by_name(args.name, args.camera)
        else:
            sensors.menu(args.camera)
        return 0
    if args.cmd == "model":
        return cmd_model(args.action)
    if args.cmd == "doctor":
        from .checks import doctor
        return 0 if doctor.run() else 1
    if args.cmd == "test":
        return cmd_test(args.verbose)
    if args.cmd == "bench":
        return cmd_bench(args.action, args.images, args.clips, args.limit, args.conditions, args.every,
                         args.video, args.label, args.threads, args.max_frames)
    if args.cmd == "pins":
        return cmd_pins()
    return 0
