"""
The single entry point of the project: `python main.py`.

    python main.py                         menu of everything
    python main.py start [--sim] [--lan]   the whole robot
    python main.py buddy [--sim] [--lan]   the whole robot + task list, reminders, celebrations, phone notifications
    python main.py hub [--sim] [--lan]     buddy + ideas, focus mode, Google Calendar, Spotify, accounts, cost meter
    python main.py full [--sim] [--lan]    every feature: wake word, routines, smart home, reader, guard, Telegram, ...
    python main.py pro [--sim] [--lan]     full + configurable dashboard, touch pads, more IMU, Groq brain, voice studio
    python main.py help [topic]            every feature and voice command (no robot needed)
    python main.py calibrate [--sim]       the complete calibration
    python main.py health [--sim] [--motors]   test every sensor and part, report health
    python main.py imu | face | gestures | outputs | check
    python main.py run | assistant | sensors | model | doctor | bench | test | pins     (deskbot commands)
    python main.py shell | e2e | test-sensors | test-camera | ...                       (every other tool)

Anything after a tool's name is passed to that tool: python main.py shell --sim
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import ROOT, cli as base, ui
from .animations import ANIMATIONS, EMOTIONS
from .config import OUTPUTS_DIR, load_config

PY_TOOLS = {
    "shell": ("../tools/robot_shell.py", "interactive shell: forward 30cm, find cup, map, home"),
    "navigate": ("../tools/navigate.py", "go from one obstacle to another; compare the path planners"),
    "benchmarks": ("../benchmarks/benchmarks.py", "open-source benchmarks: planners, odometry, tracking, detection, speech"),
    "calibrate-encoders": ("calibrate_encoders.py", "measure the wheel encoders (on the Pi)"),
    "e2e": ("../tools/test_e2e.py", "run every feature end to end"),
    "test-sensors": ("hardware_tests/test_sensors.py", "stream any sensor"),
    "test-ultrasonic": ("hardware_tests/test_ultrasonic.py", "stream one ultrasonic sensor"),
    "test-camera": ("hardware_tests/test_camera.py", "camera in the terminal"),
    "test-mic": ("hardware_tests/test_microphone.py", "microphone level and recording"),
    "drive-basic": ("../legacy/3Nov-latest.py", "the original terminal drive menu"),
    "drive-multisonar": ("../legacy/13Nov-multisonar.py", "terminal drive menu, four sonars"),
    "dashboard-basic": ("dashboard/server.py", "the first web dashboard"),
    "dashboard-mapping": ("../legacy/server_mapping.py", "dashboard + occupancy map"),
    "dashboard-multisonar": ("../legacy/server_multisonar.py", "dashboard + four sonars"),
    "wiring": ("robot_config.py", "check the pin table for conflicts"),
}
SH_TOOLS = {
    "setup": ("setup.sh", "install everything (once)"),
    "deploy": ("deploy.sh", "copy the project to the Pi"),
    "service": ("install-service.sh", "start on boot (systemd)"),
    "hotspot": ("hotspot.sh", "make the Pi its own Wi-Fi network"),
    "realtime": ("enable-realtime.sh", "allow real-time priority"),
}
DESKBOT_COMMANDS = {"run", "assistant", "sensors", "model", "doctor", "bench", "test", "pins"}
CHECKED_LIBRARIES = [("numpy", "numpy"), ("Pillow", "PIL"), ("matplotlib", "matplotlib"), ("scipy", "scipy"), ("simple-pid", "simple_pid"),
                     ("ahrs", "ahrs"), ("pytweening", "pytweening"), ("luma.core", "luma.core"), ("luma.oled", "luma.oled.device"),
                     ("smbus2", "smbus2"), ("Adafruit MPU-6050", "adafruit_mpu6050"), ("MediaPipe", "mediapipe.tasks.python.vision")]


def run_tool(name, args):
    if name in PY_TOOLS:
        script = (ROOT / PY_TOOLS[name][0]).resolve()
        if not script.exists():
            ui.fail(f"{name} isn't part of run_prototype. It is in the full repository: {PY_TOOLS[name][0].replace('../', '')}")
            return 1
        cmd = [sys.executable, str(script), *args]
    else:
        bash = shutil.which("bash")
        if not bash:
            ui.fail("This tool needs bash (Git Bash on Windows).")
            return 1
        cmd = [bash, str(ROOT / "scripts" / SH_TOOLS[name][0]), *args]
    try:
        code = subprocess.call(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        code = 130
    if name == "e2e":
        archive("e2e_results", "e2e")
    return code


def archive(source, target):
    """Copy new reports from a tool's own results folder into outputs/."""
    src = ROOT / source
    if not src.is_dir():
        return
    for item in src.iterdir():
        dest = OUTPUTS_DIR / target / item.name
        if item.is_dir() and not dest.exists():
            shutil.copytree(item, dest)
            ui.ok(f"Copied to {dest}")


def cmd_help(topic=""):
    """Every feature, its voice commands and the terminal commands (full/features.py CATALOG)."""
    from ..full.features import help_text
    try:
        sys.stdout.reconfigure(errors="replace")     # Windows consoles: never crash on "·" or curly quotes
    except (AttributeError, ValueError):
        pass
    print(help_text(topic))
    return 0


def cmd_start(sim=False, lan=False, host=None, port=8000, camera=None, https_port=8443, buddy=False, hub=False, full=False,
              pro=False):
    """buddy=True (19 Nov 2026): the buddy runtime (buddy/app.py) instead of the companion one."""
    from .app import run_companion

    host = host or ("0.0.0.0" if lan else "127.0.0.1")
    camera = camera or ("sim" if sim else "pi")
    full = full or pro      # pro (20 Nov 2026) is the full robot plus more
    ui.header(("Starting the pro desk robot" if pro else "Starting the full desk robot" if full else "Starting the desk hub" if hub else "Starting the desk buddy" if buddy else "Starting the desk robot")
              + (" (simulation)" if sim else ""),
              "assistant + maps + camera + MPU-6050 + PID self-correction + OLED eyes + gestures + saved outputs"
              + (" + tasks + reminders + phone notifications" if buddy or hub else "")
              + (" + ideas + focus mode + Google Calendar + Spotify + cost meter" if hub or full else "")
              + (" + wake word + routines + smart home + reader + guard + Telegram (python main.py help)" if full else "")
              + (" + touch pads + knock/bump/shake/tip + Groq brain + voice studio + custom dashboard" if pro else ""))
    ip = base.lan_ip()
    ui.out(f"Dashboard  [bold]http://localhost:{port}[/bold]" + (f"   ·   [bold]http://{ip}:{port}[/bold]" if host == "0.0.0.0" and ip else ""))
    if host == "0.0.0.0":
        ui.warn("Listening on the network with no login: anyone on this Wi-Fi can drive the robot.")
    ui.out("[dim]Ctrl+C stops the motors, saves the final figures and quits.[/dim]\n")
    try:
        if pro:
            from ..pro.app import run_pro
            run_pro(sim=sim, host=host, port=port, camera=camera, https_port=https_port)
        elif full:
            from ..full.app import run_full
            run_full(sim=sim, host=host, port=port, camera=camera, https_port=https_port)
        elif hub:
            from ..hub.app import run_hub
            run_hub(sim=sim, host=host, port=port, camera=camera, https_port=https_port)
        elif buddy:
            from ..buddy.app import run_buddy
            run_buddy(sim=sim, host=host, port=port, camera=camera, https_port=https_port)
        else:
            run_companion(sim=sim, host=host, port=port, camera=camera, https_port=https_port)
    except Exception as exc:
        ui.fail(f"Could not start: {exc}")
        if "address" in str(exc).lower() or getattr(exc, "errno", None) in (98, 10048):
            ui.warn(f"Port {port} is in use. Is the robot already running? Try --port {port + 1}, or: sudo systemctl stop deskbot")
        elif not sim:
            ui.warn("Not on the Pi (or GPIO busy)? Try: python main.py start --sim")
        return 1
    return 0


def _ask_number(question):
    if not ui.interactive():
        return None
    answer = ui.ask(question + " (Enter = skip)", "")
    try:
        return float(answer) if answer else None
    except ValueError:
        return None


def cmd_calibrate(sim=False, camera=None, yes=False):
    from .app import Rig
    from .calibration import Calibration

    camera = camera or ("sim" if sim else "pi")
    ui.header("Complete calibration", "IMU, sonars, edge sensors, camera, turning, motor dead zone, driving, verification")
    ui.warn("The robot will spin and drive short distances. Leave about 30 cm of clear desk all round.")
    if not sim:
        ui.out("[dim]A box 30-100 cm in front of and behind the robot lets the sonars measure its speed automatically.[/dim]")
    if not yes and not ui.confirm("Start?", default=True):
        return 0
    rig = None
    try:
        rig = Rig(sim=sim, camera=camera)
        cal = Calibration(rig.robot, rig.shared, rig.cfg, sim, log=ui.out, ask=_ask_number, has_camera=camera != "none")
        results = cal.run()
    except KeyboardInterrupt:
        ui.warn("Stopped.")
        return 130
    except Exception as exc:
        ui.fail(f"Calibration could not run: {exc}")
        return 1
    finally:
        if rig is not None:
            rig.close()
    ui.table("Calibration", ["Step", "Result", "Details"], [(r["title"], r["status"].upper(), r["message"]) for r in results])
    ui.ok(f"Report: {cal.folder / 'report.md'}")
    return 1 if any(r["status"] == "fail" for r in results) else 0


def cmd_imu(sim=False, seconds=0.0):
    import math

    from .app import Rig
    from .imu import tilt_rad
    from .shared import fresh_imu

    ui.header("MPU-6050 live", "Ctrl+C or Enter stops")
    rig = None
    try:
        rig = Rig(sim=sim, camera="none")
        done = ui.enter_to_stop() if ui.interactive() else None
        end = time.monotonic() + seconds if seconds else None
        while not (done and done.is_set()) and not (end and time.monotonic() > end):
            v = fresh_imu(rig.shared, time.monotonic())
            line = "no data: check the wiring and `i2cdetect -y 1`" if v is None else (
                f"roll {math.degrees(v['roll']):6.1f}°  pitch {math.degrees(v['pitch']):6.1f}°  tilt {math.degrees(tilt_rad(v)):5.1f}°  "
                f"heading {math.degrees(v['yaw']):7.1f}°  turn {v['gz']:5.2f} rad/s  {'still' if v['still'] else 'moving'}")
            print("\r" + line.ljust(90), end="", flush=True)
            time.sleep(0.1)
        print()
    except KeyboardInterrupt:
        print()
    except Exception as exc:
        ui.fail(str(exc))
        return 1
    finally:
        if rig is not None:
            rig.close()
    return 0


def render_preview(folder):
    """Every animation as a contact sheet and one GIF per emotion."""
    from PIL import Image, ImageDraw

    from .config import OledConfig
    from .eyes import FacePlayer, draw_face

    cfg = OledConfig()
    w, h, scale = cfg.width, cfg.height, 2
    folder.mkdir(parents=True, exist_ok=True)

    def frame(emotion, anim, t_ms):
        p = FacePlayer(cfg)
        p.emotion, p.name, p.frames, p.started = emotion, anim[0], anim[1], 0.0
        p.next_blink = p.next_replay = 1e9
        im = Image.new("1", (w, h))
        pose, fx = p.pose(t_ms / 1000)
        draw_face(ImageDraw.Draw(im), pose, fx, w, h, t_ms / 1000)
        return im.convert("L").resize((w * scale, h * scale), Image.NEAREST)

    sheet = Image.new("L", (5 * (w * scale + 6) + 6, len(EMOTIONS) * (h * scale + 6) + 6), 70)
    for row, emotion in enumerate(EMOTIONS):
        gif = []
        for col, anim in enumerate(ANIMATIONS[emotion]):
            key = anim[1][len(anim[1]) // 2].ms + 1
            sheet.paste(frame(emotion, anim, key), (6 + col * (w * scale + 6), 6 + row * (h * scale + 6)))
            gif += [frame(emotion, anim, t) for t in range(0, anim[1][-1].ms + 200, 66)]
        gif[0].save(folder / f"{emotion}.gif", save_all=True, append_images=gif[1:], duration=66, loop=0)
    sheet.save(folder / "all_animations.png")
    return folder


def cmd_face(preview=False, emotion=None, sim=False):
    from luma.core.render import canvas
    from luma.core.sprite_system import framerate_regulator

    from .eyes import FacePlayer, draw_face, open_display

    if preview:
        ui.ok(f"Saved to {render_preview(OUTPUTS_DIR / 'eyes_preview')}")
        return 0
    cfg = load_config().companion.oled
    device, what = open_display(cfg, sim, ui.warn)
    ui.header("OLED eyes", f"{what} · each animation in turn · Ctrl+C stops")
    player = FacePlayer(cfg)
    regulator = framerate_regulator(fps=cfg.fps)
    try:
        for name in ([emotion] if emotion else EMOTIONS):
            for _ in range(5):
                player.invoke(name, time.monotonic())
                ui.out(f"{name}: {player.name}")
                end = time.monotonic() + max(2.5, player.frames[-1].ms / 1000 + 1)
                while time.monotonic() < end:
                    with regulator:
                        now = time.monotonic()
                        pose, fx = player.pose(now)
                        with canvas(device) as draw:
                            draw_face(draw, pose, fx, cfg.width, cfg.height, now)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_gestures(args):
    from .gestures import CONTROLLABLE, GESTURES_FILE, clean_mapping, load_mapping, save_mapping, valid_actions

    m = load_mapping()
    if args.action == "set":
        if args.gesture not in CONTROLLABLE or args.target not in valid_actions():
            ui.fail(f"Gestures: {', '.join(CONTROLLABLE)}\nActions: {', '.join(valid_actions())}")
            return 2
        m[args.gesture]["action"] = args.target
        if args.amount is not None:
            m[args.gesture]["amount"] = args.amount
        if args.hold is not None:
            m[args.gesture]["hold_s"] = args.hold
        m = save_mapping(m)
    elif args.action in ("enable", "disable"):
        if args.gesture not in CONTROLLABLE:
            ui.fail(f"Gestures: {', '.join(CONTROLLABLE)}")
            return 2
        m[args.gesture]["enabled"] = args.action == "enable"
        m = save_mapping(m)
    elif args.action == "reset":
        m = save_mapping(clean_mapping({}))
    ui.table(f"Gestures ({GESTURES_FILE})", ["Gesture", "Action", "Amount", "Hold", "Cooldown", "On"],
             [(k, v["action"], f"{v['amount']:g}", f"{v['hold_s']:g} s", f"{v['cooldown_s']:g} s", "yes" if v["enabled"] else "no") for k, v in m.items()])
    return 0


def cmd_outputs():
    sessions = sorted((p for p in OUTPUTS_DIR.glob("*") if p.is_dir()), reverse=True) if OUTPUTS_DIR.exists() else []
    ui.out(f"Outputs folder: [bold]{OUTPUTS_DIR}[/bold]")
    rows = [(p.name, sum(1 for f in p.rglob("*") if f.is_file())) for p in sessions[:25]]
    ui.table("Newest first", ["Session", "Files"], rows)
    return 0


def cmd_health(sim=None, camera=None, motors=None, unit_tests=True, sound=False):
    from .health_check import is_pi, run_health

    sim = (not is_pi()) if sim is None else sim
    if motors is None:
        motors = sim or (ui.interactive() and ui.confirm("Also test the motors? The robot will move a little.", default=False))
    return 0 if run_health(sim=sim, camera=camera, motors=motors, unit_tests=unit_tests, sound=sound).healthy else 1


def _offer_health():
    """The first question when main.py opens its menu."""
    from .health_check import is_pi

    where = "this robot" if is_pi() else "the simulated robot (no Pi detected)"
    if ui.choose("Run all tests and report the robot's health first?",
                 [(f"Yes, test {where}", "yes"), ("No, go to the menu", "no")], default="no") == "yes":
        cmd_health()
        ui.pause()


def cmd_check():
    ui.header("Companion check", "libraries, I2C devices and saved settings")
    rows, ok = [], True
    for label, module in CHECKED_LIBRARIES:
        try:
            importlib.import_module(module)
            rows.append((label, "ok"))
        except Exception as exc:
            ok = False
            rows.append((label, str(exc)[:70]))
    ui.table("Libraries", ["Library", "Status"], rows)
    if Path("/dev/i2c-1").exists():
        from smbus2 import SMBus
        cfg = load_config().companion
        devices = []
        with SMBus(1) as bus:
            for name, addr in (("MPU-6050", cfg.imu.address), ("OLED", cfg.oled.address)):
                try:
                    bus.read_byte(addr)
                    devices.append((name, f"{addr:#x}", "found"))
                except OSError:
                    ok = False
                    devices.append((name, f"{addr:#x}", "NOT FOUND"))
        ui.table("I2C bus 1", ["Device", "Address", "Status"], devices)
    else:
        ui.warn("No I2C bus here (normal off the Pi). On the Pi: sudo raspi-config nonint do_i2c 0")
    return 0 if ok else 1


# ---------------- menu ----------------

def _start_menu(sim, buddy=False, hub=False, full=False, pro=False):
    camera = base._ask_camera("sim" if sim else "pi")
    if camera is None:
        return
    lan = ui.confirm("Open the dashboard to other devices (phone/laptop)?", default=not sim or buddy or hub or full)
    cmd_start(sim=sim, lan=lan, camera=camera, buddy=buddy, hub=hub, full=full, pro=pro)
    ui.pause()


def _tools_menu():
    options = [(f"{k}  ({v[1]})", k) for k, v in {**PY_TOOLS, **SH_TOOLS}.items()] + [("Back", None)]
    name = ui.choose("Which tool?", options)
    if name:
        run_tool(name, [])
        ui.pause()


def menu():
    ui.header("Desk Assistant Robot", "↑/↓ to move, Enter to choose, Ctrl+C to go back")
    if ui.interactive():
        _offer_health()
    while True:
        c = ui.choose("What do you want to do?", [
            ("🩺 Run all tests and report health", "health"),
            ("▶  Start the robot (everything)", "start"), ("▶  Start in simulation (no hardware)", "sim"),
            ("🎉 Start the desk buddy (+ tasks, reminders, phone notifications)", "buddy"),
            ("🎉 Desk buddy in simulation", "buddy-sim"),
            ("🌟 Start the PRO robot (full + touch, Groq, voice studio, custom dashboard)", "pro"),
            ("🌟 Pro robot in simulation", "pro-sim"),
            ("⭐ Start the FULL robot (every feature)", "full"), ("⭐ Full robot in simulation", "full-sim"),
            ("❓ Every feature and command (help)", "help"),
            ("🧠 Start the desk hub (+ ideas, focus mode, Google, Spotify, costs)", "hub"),
            ("🧠 Desk hub in simulation", "hub-sim"),
            ("🎯 Calibrate everything", "calibrate"), ("🎯 Calibrate in simulation", "calibrate-sim"),
            ("👀 Test the OLED eyes", "face"), ("🖼  Save a preview of all eye animations", "preview"),
            ("🧭 Live MPU-6050 readout", "imu"), ("✋ Show gesture settings", "gestures"),
            ("📁 Show saved outputs", "outputs"), ("🔧 Test sensors", "sensors"), ("👁  Vision model", "model"),
            ("🩺 System check", "doctor"), ("📊 Benchmark", "bench"), ("✅ Unit tests", "test"), ("📌 Wiring", "pins"),
            ("🧰 Other tools (shell, older scripts, setup, deploy)", "tools"), ("Quit", "quit")])
        if c in (None, "quit"):
            ui.out("Bye.")
            return 0
        if c in ("start", "sim"):
            _start_menu(c == "sim")
            continue
        if c in ("buddy", "buddy-sim"):
            _start_menu(c == "buddy-sim", buddy=True)
            continue
        if c in ("pro", "pro-sim"):
            _start_menu(c == "pro-sim", pro=True)
            continue
        if c in ("full", "full-sim"):
            _start_menu(c == "full-sim", full=True)
            continue
        if c == "help":
            cmd_help()
            ui.pause()
            continue
        if c in ("hub", "hub-sim"):
            _start_menu(c == "hub-sim", hub=True)
            continue
        if c == "tools":
            _tools_menu()
            continue
        if c == "health":
            cmd_health()
            ui.pause()
            continue
        if c in ("calibrate", "calibrate-sim"):
            cmd_calibrate(sim=c == "calibrate-sim")
        elif c == "face":
            cmd_face()
        elif c == "preview":
            cmd_face(preview=True)
        elif c == "imu":
            cmd_imu()
        elif c == "gestures":
            cmd_gestures(argparse.Namespace(action="list"))
        elif c == "outputs":
            cmd_outputs()
        elif c == "doctor":
            base.main(["doctor"])
            cmd_check()
        elif c == "bench":
            action = ui.choose("Benchmark", [("Everything (downloads ~420 MB once)", "all"), ("Detection under lighting", "images"),
                                             ("Tracking on video", "video"), ("Runtime latency", "system"), ("Back", None)])
            if action:
                base.main(["bench", action])
                archive("../benchmarks/results", "benchmarks")
        elif c == "model":
            action = ui.choose("Model", [("Info", "info"), ("Export to NCNN", "export"), ("Benchmark", "bench"), ("Back", None)])
            if action:
                base.main(["model", action])
        elif c == "sensors":
            camera = base._ask_camera("pi")
            if camera and camera != "none":
                base.main(["sensors", "--camera", camera])
        else:
            base.main([c])
        ui.pause()


# ---------------- arguments ----------------

def build_parser():
    p = argparse.ArgumentParser(prog="main.py", description="Desk assistant robot: everything from one command.",
                                epilog="Also: " + ", ".join(sorted(DESKBOT_COMMANDS)) + " (deskbot commands); "
                                       + ", ".join([*PY_TOOLS, *SH_TOOLS]) + " (tools; extra arguments are passed on).")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("start", help="the whole robot")
    s.add_argument("--sim", action="store_true", help="simulated robot, desk, camera and phone")
    s.add_argument("--lan", action="store_true", help="reachable from other devices")
    s.add_argument("--host")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--https-port", type=int, default=8443, help="HTTPS for browser microphones (0 = off)")
    s.add_argument("--camera", help="pi | webcam | sim | none | <index> | <video>")
    b = sub.add_parser("buddy", help="the whole robot + task list, reminders, celebrations, phone notifications")
    b.add_argument("--sim", action="store_true", help="simulated robot, desk, camera and phone")
    b.add_argument("--lan", action="store_true", help="reachable from other devices (needed for the phone)")
    b.add_argument("--host")
    b.add_argument("--port", type=int, default=8000)
    b.add_argument("--https-port", type=int, default=8443, help="HTTPS for browser microphones (0 = off)")
    b.add_argument("--camera", help="pi | webcam | sim | none | <index> | <video>")
    fl = sub.add_parser("full", help="every feature: wake word, routines, smart home, reader, guard, Telegram, games, ...")
    fl.add_argument("--sim", action="store_true", help="simulated robot, desk, camera and phone")
    fl.add_argument("--lan", action="store_true", help="reachable from other devices")
    fl.add_argument("--host")
    fl.add_argument("--port", type=int, default=8000)
    fl.add_argument("--https-port", type=int, default=8443, help="HTTPS for browser microphones (0 = off)")
    fl.add_argument("--camera", help="pi | webcam | sim | none | <index> | <video>")
    pr = sub.add_parser("pro", help="full + configurable dashboard, touch pads, more IMU, Groq brain, voice studio")
    pr.add_argument("--sim", action="store_true", help="simulated robot, desk, camera and phone")
    pr.add_argument("--lan", action="store_true", help="reachable from other devices")
    pr.add_argument("--host")
    pr.add_argument("--port", type=int, default=8000)
    pr.add_argument("--https-port", type=int, default=8443, help="HTTPS for browser microphones (0 = off)")
    pr.add_argument("--camera", help="pi | webcam | sim | none | <index> | <video>")
    hp = sub.add_parser("help", help="every feature, its voice commands and the terminal commands")
    hp.add_argument("topic", nargs="?", default="", help="a feature or group, e.g. talking, guard, cli")
    hb = sub.add_parser("hub", help="buddy + ideas, focus mode, Google Calendar, Spotify, connected accounts, cost meter")
    hb.add_argument("--sim", action="store_true", help="simulated robot, desk, camera and phone")
    hb.add_argument("--lan", action="store_true", help="reachable from other devices")
    hb.add_argument("--host")
    hb.add_argument("--port", type=int, default=8000)
    hb.add_argument("--https-port", type=int, default=8443, help="HTTPS for browser microphones (0 = off)")
    hb.add_argument("--camera", help="pi | webcam | sim | none | <index> | <video>")
    c = sub.add_parser("calibrate", help="the complete calibration")
    c.add_argument("--sim", action="store_true")
    c.add_argument("--camera", help="pi | webcam | sim | none")
    c.add_argument("--yes", action="store_true", help="don't ask before moving")
    i = sub.add_parser("imu", help="live MPU-6050 readout")
    i.add_argument("--sim", action="store_true")
    i.add_argument("--seconds", type=float, default=0)
    f = sub.add_parser("face", help="OLED eyes: play every animation, or --preview to save them as images")
    f.add_argument("--preview", action="store_true")
    f.add_argument("--emotion", choices=EMOTIONS)
    f.add_argument("--sim", action="store_true", help="no screen needed")
    g = sub.add_parser("gestures", help="show or change the gesture map")
    g.add_argument("action", nargs="?", default="list", choices=["list", "set", "enable", "disable", "reset"])
    g.add_argument("gesture", nargs="?")
    g.add_argument("target", nargs="?", help="action name (for set)")
    g.add_argument("--amount", type=float)
    g.add_argument("--hold", type=float)
    h = sub.add_parser("health", help="test all sensors and parts, run the unit tests, report health")
    h.add_argument("--sim", action="store_true", default=None, help="test the simulated robot (default when not on a Pi)")
    h.add_argument("--camera", help="pi | webcam | sim | none")
    h.add_argument("--motors", action="store_true", default=None, help="include short motor moves without asking")
    h.add_argument("--no-motors", dest="motors", action="store_false")
    h.add_argument("--no-unit-tests", action="store_true")
    h.add_argument("--sound", action="store_true", help="also play a test phrase on the speaker")
    sub.add_parser("outputs", help="list saved sessions")
    sub.add_parser("check", help="check the companion libraries and I2C devices")
    sub.add_parser("menu", help="interactive menu (default)")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PY_TOOLS or argv and argv[0] in SH_TOOLS:
        return run_tool(argv[0], argv[1:])
    if argv and argv[0] in DESKBOT_COMMANDS:
        code = base.main(argv)
        if argv[0] == "bench":
            archive("../benchmarks/results", "benchmarks")
        if argv[0] == "doctor":
            code = cmd_check() or code
        return code
    args = build_parser().parse_args(argv)
    if args.cmd in (None, "menu"):
        return menu()
    if args.cmd == "pro":
        return cmd_start(args.sim, args.lan, args.host, args.port, args.camera, args.https_port, pro=True)
    if args.cmd == "full":
        return cmd_start(args.sim, args.lan, args.host, args.port, args.camera, args.https_port, full=True)
    if args.cmd == "help":
        return cmd_help(args.topic)
    if args.cmd == "hub":
        return cmd_start(args.sim, args.lan, args.host, args.port, args.camera, args.https_port, hub=True)
    if args.cmd == "buddy":
        return cmd_start(args.sim, args.lan, args.host, args.port, args.camera, args.https_port, buddy=True)
    if args.cmd == "start":
        return cmd_start(args.sim, args.lan, args.host, args.port, args.camera, args.https_port)
    if args.cmd == "calibrate":
        return cmd_calibrate(args.sim, args.camera, args.yes)
    if args.cmd == "imu":
        return cmd_imu(args.sim, args.seconds)
    if args.cmd == "face":
        return cmd_face(args.preview, args.emotion, args.sim)
    if args.cmd == "gestures":
        return cmd_gestures(args)
    if args.cmd == "outputs":
        return cmd_outputs()
    if args.cmd == "health":
        return cmd_health(args.sim, args.camera, args.motors, not args.no_unit_tests, args.sound)
    return cmd_check()
