"""
Pin a process to its core and give it its Linux scheduling priority.

    motor    core 0   SCHED_FIFO 50   (fallback: nice -10, then nice 0)
    sensors  core 1   SCHED_FIFO 40   (fallback: nice -5,  then nice 0)
    camera   core 2   nice 5          (never real-time: it is CPU-bound and would starve its core)
    nav      core 3   nice 10

Why this cannot starve anything
    * Only the two processes that SLEEP between short bursts are real-time. The motor process wakes
      on a command or a sensor sample, checks safety (~0.1 ms) and sleeps again; the sensor process
      reads at 50 Hz and sleeps. Together they use a few % of their cores.
    * The kernel's RT throttling stays on (/proc/sys/kernel/sched_rt_runtime_us = 950000 of 1000000):
      even a runaway real-time loop leaves 5 % of every second to normal tasks (ssh, the kernel's own
      threads), so the Pi can always be reached and stopped.
    * Each process is pinned to its own core, so the camera's 100 % load stays on core 2 and can't
      delay the motor process; the other system processes are free to run on any core.
    * nice values (not real-time) for camera and nav: CFS gives every runnable task a share in
      proportion to its weight, so a nice-10 task still runs, just less when there's contention.

Permissions: real-time and negative nice need CAP_SYS_NICE or an RLIMIT_RTPRIO / RLIMIT_NICE allowance.
`scripts/enable-realtime.sh` adds `rtprio 60` and `nice -10` for your user in
/etc/security/limits.d/deskbot.conf (takes effect at next login). Without it everything still runs;
the motor and sensor processes just use normal priority on their own cores.

On Windows/macOS (development) pinning and priorities are skipped and reported as such.
"""

from __future__ import annotations

import os

from .shared import POLICIES


def apply(role, rcfg, block=None):
    """Pin + prioritise the CALLING process. Returns a dict describing what was actually applied.
    Call it before starting threads: new threads inherit the affinity and the policy."""
    info = {"role": role, "pid": os.getpid(), "core": None, "policy": "other", "priority": 0,
            "nice": None, "notes": []}
    core = rcfg.cores.get(role)
    ncpu = os.cpu_count() or 1

    if hasattr(os, "sched_setaffinity") and core is not None:
        try:
            wanted = list(core) if isinstance(core, (list, tuple, set)) else [core]   # e.g. camera: (2, 3)
            cpus = sorted({c % ncpu for c in wanted})
            os.sched_setaffinity(0, cpus)
            info["core"] = cpus[0] if len(cpus) == 1 else cpus
            if max(wanted) >= ncpu:
                info["notes"].append(f"only {ncpu} CPUs, cores {wanted} -> {cpus}")
        except OSError as exc:
            info["notes"].append(f"affinity: {exc}")
    else:
        info["notes"].append("no CPU pinning on this OS")

    rt = rcfg.rt_priority.get(role)
    if rt and hasattr(os, "sched_setscheduler"):
        try:
            os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(rt))
            info["policy"], info["priority"] = "fifo", rt
        except (PermissionError, OSError):
            info["notes"].append("SCHED_FIFO not permitted (run scripts/enable-realtime.sh)")

    if info["policy"] == "other" and hasattr(os, "setpriority"):
        want = rcfg.nice.get(role, 0)
        for value in (want, 0) if want < 0 else (want,):
            try:
                os.setpriority(os.PRIO_PROCESS, 0, value)
                break
            except (PermissionError, OSError):
                if value < 0:
                    info["notes"].append(f"nice {value} not permitted, using 0")
    if hasattr(os, "getpriority"):
        info["nice"] = os.getpriority(os.PRIO_PROCESS, 0)
    elif os.name == "nt":
        info["notes"].append("no priorities on Windows (development only)")

    if block is not None:
        first = info["core"][0] if isinstance(info["core"], list) else info["core"]
        block.write(pid=info["pid"], core=-1 if first is None else first,
                    policy=POLICIES.index(info["policy"]), priority=info["priority"],
                    nice=info["nice"], ready=0)
    return info


def rt_throttle():
    """(runtime_us, period_us) of the kernel's real-time throttling, or None (not Linux)."""
    try:
        with open("/proc/sys/kernel/sched_rt_runtime_us") as f:
            runtime = int(f.read())
        with open("/proc/sys/kernel/sched_rt_period_us") as f:
            period = int(f.read())
        return runtime, period
    except OSError:
        return None


class LoopStats:
    """Loop rate + worst iteration time, published to the process's status block about once a second."""

    def __init__(self, block):
        import time

        self.block = block
        self.time = time
        self.n = 0
        self.t0 = time.monotonic()
        self.max_ms = 0.0

    def tick(self, busy_s):
        self.n += 1
        self.max_ms = max(self.max_ms, busy_s * 1000)
        now = self.time.monotonic()
        if now - self.t0 >= 1.0:
            self.block.write(loop_hz=self.n / (now - self.t0), loop_max_ms=self.max_ms,
                             cpu_s=self.time.process_time(), t=now, ready=1)
            self.n, self.t0, self.max_ms = 0, now, 0.0
