"""
The "body" process: owns the I2C devices. Main thread = IMU loop, second thread = eyes.

A missing MPU-6050 or OLED never stops the robot: the process keeps running, publishes ok=0 for the IMU
(everything that uses it falls back to the camera/time-based behaviour) and mirrors the eyes to the dashboard.
"""

from __future__ import annotations

import threading
import time
import traceback

import numpy as np

from ..runtime import sched
from ..runtime.procs import _log, _parent_alive
from .animations import EMOTIONS
from .eyes import FacePlayer, draw_face, open_display
from .shared import fresh_imu
from .imu import ImuFilter, Mpu6050Source, SimImuSource, load_calibration


def face_loop(shared, cfg, sim):
    from luma.core.render import canvas
    from luma.core.sprite_system import framerate_regulator

    oc = cfg.companion.oled
    device, what = open_display(oc, sim, lambda m: _log(shared, "warn", m, proc="body"))
    _log(shared, "info", f"Eyes running ({what}, {oc.fps:g} fps)", proc="body")
    player = FacePlayer(oc)
    regulator = framerate_regulator(fps=oc.fps)
    seen, seq = None, 0
    player.invoke("neutral", time.monotonic())
    while not shared.stop.is_set():
        with regulator:
            now = time.monotonic()
            f = shared.face.read()
            if f["seq"] == f["seq"] and f["seq"] != seen:      # (NaN != NaN: nothing requested yet)
                seen = f["seq"]
                player.invoke(EMOTIONS[int(f["emotion"])], now)
            gx = 0.0 if f["gaze_x"] != f["gaze_x"] else f["gaze_x"]
            gy = 0.0 if f["gaze_y"] != f["gaze_y"] else f["gaze_y"]
            imu = fresh_imu(shared, now)
            pose, fx = player.pose(now, gx, gy, imu["roll"] if imu else 0.0, imu["pitch"] if imu else 0.0)
            with canvas(device) as draw:
                draw_face(draw, pose, fx, oc.width, oc.height, now)
            image = getattr(device, "image", None)
            if image is None:              # a real screen keeps no copy: draw the mirror separately
                from PIL import Image, ImageDraw
                image = Image.new("1", (oc.width, oc.height))
                draw_face(ImageDraw.Draw(image), pose, fx, oc.width, oc.height, now)
            grey = np.asarray(image.convert("L"), dtype=np.uint8)
            seq += 1
            shared.face_frame.write(seq, now, np.dstack((grey, grey, grey)))


def body_main(shared, cfg, sim):
    pblock = shared.procs["body"]
    info = sched.apply("body", cfg.runtime, pblock)
    cc = cfg.companion
    source = None
    try:
        threading.Thread(target=_guarded_face, args=(shared, cfg, sim), name="eyes", daemon=True).start()
        if cc.imu.enabled:
            try:
                source = SimImuSource(shared) if sim else Mpu6050Source(cc.imu)
            except Exception as exc:
                _log(shared, "warn", f"MPU-6050 not available ({exc}). Running without it: "
                                     "no gyro control, lift detection uses the IR sensors only.", proc="body")
        shared.imu.write(ok=0.0)
        pblock.write(ready=1)
        _log(shared, "info", f"Body process ready (core {info['core']}, {source.name if source else 'no IMU'})", proc="body")
        imu_loop(shared, cfg, source, pblock, sim)
    except Exception as exc:
        _log(shared, "error", f"Body process failed: {exc}", proc="body", trace=traceback.format_exc())
        pblock.write(ready=-1)
    finally:
        if source is not None:
            source.close()


def _guarded_face(shared, cfg, sim):
    try:
        face_loop(shared, cfg, sim)
    except Exception as exc:
        _log(shared, "warn", f"Eyes stopped: {exc}", proc="body", trace=traceback.format_exc())


def imu_loop(shared, cfg, source, pblock, sim=False):
    ic = cfg.companion.imu
    filt = ImuFilter(ic, sim=sim)
    loop = sched.LoopStats(pblock)
    period = 1.0 / ic.hz
    next_t = time.monotonic()
    zero_seen, reload_seen, failures = 0.0, 0.0, 0
    while not shared.stop.is_set():
        t0 = time.monotonic()
        ctl = shared.imu_ctl.read()
        if ctl["zero_seq"] != zero_seen:
            zero_seen = ctl["zero_seq"]
            filt.zero()
        if ctl["reload_seq"] != reload_seen:
            reload_seen = ctl["reload_seq"]
            filt.apply_calibration(load_calibration(sim))
        if source is not None:
            try:
                acc, gyr, temp = source.read(t0)
                m = shared.motor.read()
                motors_on = (m["left"] == m["left"]) and (m["left"] != 0 or m["right"] != 0)
                shared.imu.write(temp=temp, **filt.update(acc, gyr, t0, motors_on))
                failures = 0
            except OSError as exc:      # a loose wire: keep trying, consumers see ok=0
                failures += 1
                shared.imu.write(ok=0.0)
                if failures in (1, 100):
                    _log(shared, "warn", f"IMU read failed: {exc}", proc="body")
        loop.tick(time.monotonic() - t0)
        next_t += period if source is not None else 0.2
        delay = next_t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_t = time.monotonic()
        if not _parent_alive():
            break
