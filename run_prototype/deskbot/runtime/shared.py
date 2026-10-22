"""
The shared-memory layout of one running robot (created by the supervisor, passed to every process).

    who writes      block            read by
    ----------      -----            -------
    nav (main)      command          motor      newest command wins (single slot, sequence-numbered)
    nav (main)      settings         motor      speed, stop distances
    nav (main)      vision_ctl       camera     reset tracks, detect_every
    sensors         sensors          motor, nav 4 sonars + 2 IR, 50 Hz
    motor           motor            nav        state, stats, latency figures
    motor           wheel_log        nav        (t, left, right) on every wheel-command change -> odometry
    camera          frames           nav        newest 3 frames (dashboard video)
    camera          latest           nav        newest result for every frame (detected or optical-flow)
    camera          detections       nav        the last 8 results that came from a real detection -> map
    each process    procs[role]      nav        pid, core, policy, priority, loop rate, CPU time
    sim (motor)     sim              all        simulated pose + objects (simulation only)

Events: `wake` (set by the nav process on a new command and by the sensor process on every sample,
so the motor process reacts at once instead of on its next timer tick) and `stop` (shutdown).
"""

from __future__ import annotations

import json
import multiprocessing as mp

from .shm import FrameRing, Ring, SeqBlock, opt

CTX = mp.get_context("spawn")   # same behaviour on the Pi and on Windows; no fork-with-threads surprises

# commands
NONE, MOVE, STOP, DRIVE = 0, 1, 2, 3   # DRIVE = direct wheel values from a closed-loop controller (short deadman)
DIRECTIONS = ("forward", "backward", "left", "right")
SOURCES = ("user", "auto")

# motor states
STATES = ("idle", "moving", "blocked", "error")

# t = time.monotonic() (the clock the mapper and camera use); tp = time.perf_counter() for latency
# figures only (both are system-wide clocks; on Windows + Python < 3.13 monotonic ticks in 15.6 ms steps)
SENSOR_FIELDS = ["t", "tp", "front", "left", "right", "rear", "front_floor", "back_floor", "read_ms",
                 "enc_left", "enc_right", "faults"]
COMMAND_FIELDS = ["t", "tp", "kind", "direction", "duration", "source", "left", "right"]
SETTINGS_FIELDS = ["speed", "stop_distance", "side_stop_distance"]
STOP_KINDS = ["front_edge", "rear_edge", "turn_edge", "obstacle", "rear_obstacle", "side_obstacle", "stale_sensors"]
MOTOR_FIELDS = (["t", "state", "direction", "duration", "move_end", "source", "cmd_seq", "left", "right",
                 "moves", "completed", "safety_stops", "user_stops", "preempted", "auto_moves",
                 "cmd_latency_p50", "cmd_latency_p95", "cmd_latency_max",
                 "sensor_age_p50", "sensor_age_p95", "sensor_age_max", "loops", "drive"]
                + [f"stop_{k}" for k in STOP_KINDS])
PROC_FIELDS = ["pid", "core", "policy", "priority", "nice", "loop_hz", "loop_max_ms", "cpu_s", "t", "ready"]
POLICIES = ("other", "fifo", "rr")
VISION_CTL_FIELDS = ["reset", "detect_every"]
VISION_STATS_FIELDS = ["every", "change"]

MAX_DETS = 32
DET_HEADER = ["seq", "t_capture", "t_done", "infer_ms", "n", "detected", "camera_fps", "detect_fps", "flow_ms", "error"]
DET_ROW = ["cls", "score", "x1", "y1", "x2", "y2", "track"]
DET_WIDTH = len(DET_HEADER) + MAX_DETS * len(DET_ROW)

ROLES = ("motor", "sensors", "camera", "nav")

SIM_OBJECTS_BYTES = 8192


class WakeSignal:
    """Wakes the motor process. A one-slot semaphore instead of multiprocessing.Event: Event.set() waits for
    every sleeper to acknowledge, so a crashed motor process would freeze everyone who sends a command."""

    def __init__(self):
        self._slot = CTX.BoundedSemaphore(1)
        self._slot.acquire()

    def set(self):
        try:
            self._slot.release()
        except ValueError:     # already signalled
            pass

    def wait(self, timeout=None):
        return self._slot.acquire(True, timeout)

    def clear(self):
        self._slot.acquire(False)


class Shared:
    def __init__(self, width=320, height=240, sim=False):
        self.command = SeqBlock(COMMAND_FIELDS)
        self.settings = SeqBlock(SETTINGS_FIELDS)
        self.sensors = SeqBlock(SENSOR_FIELDS)
        self.motor = SeqBlock(MOTOR_FIELDS)
        self.wheel_log = Ring(64, 3)
        self.frames = FrameRing(height, width)
        self.latest = Ring(4, DET_WIDTH)
        self.detections = Ring(8, DET_WIDTH)
        self.vision_ctl = SeqBlock(VISION_CTL_FIELDS)
        self.vision_stats = SeqBlock(VISION_STATS_FIELDS)
        self.procs = {r: SeqBlock(PROC_FIELDS) for r in ROLES}
        self.wake = WakeSignal()
        self.stop = CTX.Event()
        self.log = CTX.Queue(maxsize=500)   # human-readable events only (not a hot path)
        self.sim = SimBlock() if sim else None


class SimBlock:
    """Simulated world shared by all processes: the motor process integrates the physics (it owns the
    wheels) and publishes the pose; everyone else mirrors it. Objects change rarely (shuffle/reset), so
    they travel as versioned JSON."""

    def __init__(self):
        self.pose = SeqBlock(["x", "y", "theta", "wheel_left", "wheel_right"])                 # written by the motor process only
        self.ctl = SeqBlock(["objects_version", "reset", "stuck"])          # written by the nav process only
        self.objects_raw = CTX.RawArray("B", SIM_OBJECTS_BYTES)
        self.objects_len = CTX.RawValue("i", 0)

    def publish_objects(self, objects):
        data = json.dumps(objects).encode()
        if len(data) > SIM_OBJECTS_BYTES:
            raise ValueError("too many simulated objects")
        self.objects_raw[:len(data)] = data
        self.objects_len.value = len(data)
        v = self.ctl.read()
        self.ctl.write(objects_version=(opt(v["objects_version"]) or 0) + 1)

    def request_reset(self, objects):
        self.publish_objects(objects)
        v = self.ctl.read()
        self.ctl.write(reset=(opt(v["reset"]) or 0) + 1)

    def objects(self):
        n = self.objects_len.value
        try:
            return json.loads(bytes(self.objects_raw[:n])) if n else None
        except ValueError:      # read while being rewritten; the next version check retries
            return None
