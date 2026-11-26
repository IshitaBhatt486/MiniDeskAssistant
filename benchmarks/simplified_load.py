"""Load benchmark for legacy/simplified_code.py, in simulation (24 Nov 2026, docs/simplified-code.md#performance-24-nov-2026).

    python benchmarks/simplified_load.py [folder with simplified_code.py] [seconds]

Runs the whole robot (control loop, IMU, OLED drawing, simulated detector, object map, assistant, task reminders,
the real HTTP server) with two simulated dashboard tabs polling like the page does, while the robot drives.
Prints one JSON line: control-loop rate and tick times, status() time, request latencies, CPU.
Compare two versions by running it on both folders; absolute numbers depend on the machine."""
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

FOLDER = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else str(Path(__file__).resolve().parent.parent / "legacy")
sys.path.insert(0, FOLDER)
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 30
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
import simplified_code as sc  # noqa: E402


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else float("nan")


class TimedEvent:
    """Stands in for the control loop's stop Event: records when each tick ends (it calls wait once per tick)."""
    def __init__(self, ev):
        self.ev, self.ticks, self.woke, self.work = ev, [], None, []

    def is_set(self):
        return self.ev.is_set()

    def set(self):
        self.ev.set()

    def wait(self, t=None):
        now = time.perf_counter()
        if self.woke is not None:
            self.work.append((now - self.woke) * 1000)      # the tick's own work, without the sleep
        r = self.ev.wait(t)
        self.woke = time.perf_counter()
        return r


tmp = tempfile.mkdtemp()
hw = sc.SimHardware(True)
robot = sc.Robot(hw, check_edges=True)
te = TimedEvent(robot._stop)
_read = hw.read
def timed_read(pose):
    te.ticks.append(time.perf_counter())
    return _read(pose)
hw.read = timed_read
robot.detector = sc.SimDetector(robot)
robot.tasks = sc.TaskList(Path(tmp) / "tasks.json")
for i in range(15):
    robot.tasks.add(f"task number {i} by friday")
rem = sc.Reminders(robot, robot.tasks)
robot.assistant = sc.Assistant(robot)
camera = sc.Camera(enabled=False)
port = 8097
server = sc.start_dashboard(robot, camera, "127.0.0.1", port)
robot.oled = sc.Oled(robot, port, enabled=True)
time.sleep(2.0)                                   # IMU bias

# measure status() directly, from its own thread (like the OLED + dashboard do)
status_ms = []
stop = threading.Event()


def status_probe():
    while not stop.is_set():
        t0 = time.perf_counter()
        robot.status()
        status_ms.append((time.perf_counter() - t0) * 1000)
        stop.wait(0.05)


lat = {"/api/state": [], "/api/map": [], "/oled.png": []}


def browser(path, every):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            r.read()
            if r.will_close:
                conn.close()
            lat[path].append((time.perf_counter() - t0) * 1000)
        except Exception:
            conn.close()
            lat[path].append(5000.0)
        stop.wait(every)


def driver():                                     # keep it busy: turns and short drives
    cmds = ["turn 30", "forward 10cm", "turn -45", "back 5cm", "spin"]
    i = 0
    while not stop.is_set():
        robot.execute(cmds[i % len(cmds)], source="assistant")
        i += 1
        stop.wait(1.5)


threads = [threading.Thread(target=status_probe)]
for _ in range(2):                                # two dashboard tabs
    threads += [threading.Thread(target=browser, args=("/api/state", 0.3)),
                threading.Thread(target=browser, args=("/api/map", 0.7)),
                threading.Thread(target=browser, args=("/oled.png", 0.25))]
threads.append(threading.Thread(target=driver))
te.ticks.clear()
te.work.clear()
cpu0, wall0 = time.process_time(), time.perf_counter()
for t in threads:
    t.start()
time.sleep(SECONDS)
stop.set()
for t in threads:
    t.join(timeout=6)
cpu, wall = time.process_time() - cpu0, time.perf_counter() - wall0
ticks = te.ticks
iv = [(b - a) * 1000 for a, b in zip(ticks, ticks[1:])]
period = 1000 / sc.LOOP_HZ
res = {
    "loop_hz_target": sc.LOOP_HZ,
    "loop_hz_real": round(len(iv) / wall, 1),
    "tick_ms_p50": round(pct(iv, 50), 2), "tick_ms_p99": round(pct(iv, 99), 2), "tick_ms_max": round(max(iv), 1),
    "late_ticks_pct": round(100 * sum(x > 1.5 * period for x in iv) / max(1, len(iv)), 2),
    "status_ms_p50": round(pct(status_ms, 50), 3), "status_ms_p99": round(pct(status_ms, 99), 3),
    **{f"{k}_ms_p50": round(pct(v, 50), 2) for k, v in lat.items()},
    **{f"{k}_ms_p99": round(pct(v, 99), 2) for k, v in lat.items()},
    "requests": sum(len(v) for v in lat.values()),
    "errors": sum(x >= 5000 for v in lat.values() for x in v),
    "cpu_pct_of_one_core": round(100 * cpu / wall, 1),
}
print("RESULT " + json.dumps(res))
robot.oled.close()
rem.close()
robot.detector.close()
server.shutdown()
robot.close()
