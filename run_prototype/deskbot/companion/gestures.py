"""
Configurable hand-gesture control.

    gesture process   MediaPipe GestureRecognizer on the newest camera frame, a few times a second, on the
                      navigation core at the lowest priority. Only runs while YOLO sees a person.
    GestureController (navigation process) a gesture must be held for its hold time, then its action runs once
                      through the same Executor as voice commands, so every safety rule applies.

The mapping lives in data/gestures.json and can be edited on the dashboard or with `main.py gestures`:

    {"Thumb_Up": {"action": "dance", "amount": 0, "hold_s": 0.6, "enabled": true}, ...}

Gestures MediaPipe knows: Closed_Fist, Open_Palm, Pointing_Up, Thumb_Down, Thumb_Up, Victory, ILoveYou.
Actions: every robot command in assistant/commands.py, plus `save_figures` and `none`.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import urllib.request

from .. import MODELS_DIR
from ..assistant.commands import ACTIONS
from ..runtime import sched
from ..runtime.procs import _log, _parent_alive
from .config import GESTURES_FILE
from .shared import GESTURE_BACKENDS, GESTURES, nav_bump

MODEL_PATH = MODELS_DIR / "gesture_recognizer.task"
EXTRA_ACTIONS = ("none", "save_figures")
CONTROLLABLE = GESTURES[1:]

DEFAULT_MAP = {
    "Open_Palm":   {"action": "stop", "amount": 0, "hold_s": 0.2, "cooldown_s": 1.0, "enabled": True},
    "Closed_Fist": {"action": "follow_user_off", "amount": 0, "hold_s": 0.8, "cooldown_s": 3.0, "enabled": True},
    "Thumb_Up":    {"action": "dance", "amount": 0, "hold_s": 0.8, "cooldown_s": 5.0, "enabled": True},
    "Thumb_Down":  {"action": "sleep", "amount": 0, "hold_s": 1.2, "cooldown_s": 5.0, "enabled": True},
    "Victory":     {"action": "spin", "amount": 1, "hold_s": 0.8, "cooldown_s": 5.0, "enabled": True},
    "Pointing_Up": {"action": "look_around", "amount": 0, "hold_s": 0.8, "cooldown_s": 10.0, "enabled": True},
    "ILoveYou":    {"action": "follow_user_on", "amount": 0, "hold_s": 0.8, "cooldown_s": 3.0, "enabled": True},
}


def valid_actions():
    return list(EXTRA_ACTIONS) + [a for a in ACTIONS if a != "navigate"]   # navigate needs named objects


def clean_mapping(raw):
    """Validated mapping for all gestures: unknown names are rejected, numbers are clamped."""
    if not isinstance(raw, dict):
        raise ValueError("the gesture map must be an object")
    unknown = set(raw) - set(CONTROLLABLE)
    if unknown:
        raise ValueError(f"unknown gesture: {', '.join(sorted(unknown))}")
    out = {}
    for name in CONTROLLABLE:
        item = {**DEFAULT_MAP[name], **(raw.get(name) or {})}
        if item["action"] not in valid_actions():
            raise ValueError(f"{name}: unknown action {item['action']!r}")
        out[name] = {"action": item["action"], "amount": max(0.0, float(item["amount"])),
                     "hold_s": max(0.1, min(5.0, float(item["hold_s"]))),
                     "cooldown_s": max(0.0, min(60.0, float(item["cooldown_s"]))), "enabled": bool(item["enabled"])}
    return out


def load_mapping(path=None, warn=print):
    try:
        return clean_mapping(json.loads((path or GESTURES_FILE).read_text(encoding="utf-8")))
    except OSError:
        return clean_mapping({})
    except ValueError as exc:
        warn(f"Ignoring gestures.json: {exc}")
        return clean_mapping({})


def save_mapping(mapping, path=None):
    path = path or GESTURES_FILE
    clean = clean_mapping(mapping)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    tmp.replace(path)
    return clean


# ---------------- recogniser ----------------

def ensure_model(cfg, log=print):
    if not MODEL_PATH.exists():
        log("Downloading the MediaPipe gesture model (8 MB, once)...")
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = MODEL_PATH.with_suffix(".part")
        urllib.request.urlretrieve(cfg.model_url, tmp)
        tmp.replace(MODEL_PATH)
    return MODEL_PATH


class MediaPipeRecognizer:
    def __init__(self, cfg, log=print):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self.mp = mp
        options = vision.GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model(cfg, log))),
            running_mode=vision.RunningMode.VIDEO, num_hands=1,
            min_hand_detection_confidence=0.5, min_tracking_confidence=0.5)
        self.rec = vision.GestureRecognizer.create_from_options(options)
        self.last_ms = 0

    def __call__(self, bgr, t):
        rgb = bgr[:, :, ::-1].copy()
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        ms = max(self.last_ms + 1, int(t * 1000))   # VIDEO mode needs strictly increasing timestamps
        self.last_ms = ms
        result = self.rec.recognize_for_video(image, ms)
        if not result.gestures:
            return "None", 0.0
        top = result.gestures[0][0]
        return top.category_name or "None", float(top.score)

    def close(self):
        self.rec.close()


def gesture_main(shared, cfg, camera, sim):
    pblock = shared.procs["gesture"]
    info = sched.apply("gesture", cfg.runtime, pblock)
    gc = cfg.companion.gesture
    recognizer, backend = None, "simulated"
    try:
        if camera != "sim":
            try:
                recognizer = MediaPipeRecognizer(gc, lambda m: _log(shared, "info", m, proc="gesture"))
                backend = "mediapipe"
            except Exception as exc:
                backend = "off"
                _log(shared, "warn", f"Gesture control is off: {exc}", proc="gesture")
        shared.gesture.write(backend=GESTURE_BACKENDS.index(backend), seq=0)
        pblock.write(ready=1)
        _log(shared, "info", f"Gesture process ready ({backend}, core {info['core']})", proc="gesture")
        loop = sched.LoopStats(pblock)
        seq, last_frame, sim_seen, shown = 0, None, 0.0, ("None", 0.0)
        while not shared.stop.is_set() and _parent_alive():
            t0 = time.monotonic()
            ctl = shared.gesture_ctl.read()
            name, score = "None", 0.0
            if backend == "simulated":
                if ctl["sim_seq"] != sim_seen:        # a dashboard button "holds up" the gesture for 1.5 s
                    sim_seen = ctl["sim_seq"]
                    shown = (GESTURES[int(ctl["sim_gesture"])], t0 + 1.5)
                if t0 < shown[1]:
                    name, score = shown[0], 0.95
            elif backend == "mediapipe" and (ctl["person"] == 1.0 or not gc.only_with_person):
                frame = shared.frames.read()
                if frame is not None and frame[0] != last_frame:
                    last_frame = frame[0]
                    name, score = recognizer(frame[2], frame[1])
            seq += 1
            shared.gesture.write(t=time.monotonic(), seq=seq, gesture=GESTURES.index(name) if name in GESTURES else 0, score=score)
            loop.tick(time.monotonic() - t0)
            time.sleep(max(0.0, 1.0 / gc.hz - (time.monotonic() - t0)))
    except Exception as exc:
        _log(shared, "error", f"Gesture process failed: {exc}", proc="gesture", trace=traceback.format_exc())
        pblock.write(ready=-1)
    finally:
        if recognizer is not None:
            recognizer.close()


# ---------------- gesture -> action ----------------

class GestureController:
    def __init__(self, shared, cfg, app, on_action=None, mapping=None):
        self.s, self.cfg, self.app = shared, cfg, app
        self.mapping = mapping if mapping is not None else load_mapping()
        self.on_action = on_action
        self.enabled = cfg.enabled
        self.paused = False
        self.current = "None"
        self.since = 0.0
        self.fired = False
        self.last_fire = {}
        self.last = None
        self.score = 0.0
        self.count = 0
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="gestures", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self.step(time.monotonic())
            except Exception as exc:
                print(f"[GEST ] {exc}", flush=True)
            time.sleep(0.05)

    def set_mapping(self, raw):
        self.mapping = save_mapping(raw)
        return self.mapping

    def step(self, now):
        g = self.s.gesture.read()
        fresh = g["t"] == g["t"] and now - g["t"] < 1.0
        name = GESTURES[int(g["gesture"])] if fresh and g["score"] >= self.cfg.min_score else "None"
        self.score = g["score"] if fresh else 0.0
        if name != self.current:
            self.current, self.since, self.fired = name, now, False
        if name == "None" or self.fired or not self.enabled or self.paused:
            return
        rule = self.mapping[name]
        if not rule["enabled"] or rule["action"] == "none" or now - self.since < rule["hold_s"]:
            return
        if now - self.last_fire.get(name, -1e9) < rule["cooldown_s"]:
            return
        self.fired = True
        self.last_fire[name] = now
        self.fire(name, rule)

    def fire(self, name, rule):
        a = self.app
        if a.lift.lifted:
            return
        asleep = a.presence is not None and not a.presence.awake
        if asleep and rule["action"] not in ("wake", "stop"):      # any gesture wakes a sleeping robot instead
            a.presence.set_awake(True, reason="gesture")
            self._note(name, "wake")
            return
        self.count += 1
        self._note(name, rule["action"])
        if rule["action"] == "save_figures":
            a.outputs.save_all("gesture")
        elif rule["action"] == "stop":
            a.executor.cancel()
            a.robot.stop()
        else:
            a.executor.run([{"action": rule["action"], "amount": rule["amount"]}], source=f"gesture {name}")

    def _note(self, name, action):
        self.last = {"gesture": name, "action": action, "t": time.time()}
        self.app.robot.log("info", f"Gesture {name.replace('_', ' ')}: {action.replace('_', ' ')}")
        if self.on_action:
            self.on_action(name, action)

    def simulate(self, name):
        if name not in CONTROLLABLE:
            raise ValueError(f"unknown gesture {name!r}")
        nav_bump(self.s.gesture_ctl, "sim_seq", sim_gesture=GESTURES.index(name))

    def status(self):
        g = self.s.gesture.read()
        backend = GESTURE_BACKENDS[int(g["backend"])] if g["backend"] == g["backend"] else "starting"
        return {"enabled": self.enabled, "backend": backend, "current": self.current,
                "score": round(self.score, 2), "last": self.last, "count": self.count,
                "mapping": self.mapping, "gestures": list(CONTROLLABLE), "actions": valid_actions()}
