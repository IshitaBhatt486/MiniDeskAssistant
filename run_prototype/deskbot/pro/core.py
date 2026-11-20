"""
The pro robot (20 Nov 2026): reactions to touch and motion, personality profiles by voice, Groq first.

Reactions (face = OLED/dashboard emotion via full.react; speech is rate-limited by touch.cooldown_s; movement only
when touch.move is on, the robot isn't lifted and isn't already moving):

    touch (any pad down)   happy face at once; wakes a sleeping robot
    pat                    giggle + a short thank-you + a little "nudge" wiggle
    hold                   blushing face + a contented sigh
    pats (3 quick ones)    celebrating face + "yay" + a small "celebrate" move
    stroke                 happy face + "ooh, that's nice"
    knock                  curious face, "who's there?"
    double_knock           wakes up, turns to face you
    bump (while driving)   STOP, annoyed face, "oof"
    shake                  dizzy (confused) face, "whoa"
    tipped                 STOP, scared face, a warning on the dashboard, asks for help
    righted                warning cleared, "phew"
    drop                   scared face + gasp

Voice: "switch to the pirate profile" / "use the calm butler personality" / "which profile are you using?" are
answered before the AI (Brain.pre_handlers), so they work offline too.
"""

from __future__ import annotations

import random
import re
import threading
import time

PHRASES = {
    "pat": ["Hehe, that tickles!", "Aww, thank you!", "Headpat accepted!", "Ooh, I like that.", "You're the best!",
            "Beep boop, happy robot!"],
    "hold": ["Mmm, that's nice.", "Aww, you're making me blush.", "I could get used to this."],
    "pats": ["Yay! So many headpats!", "Best day ever!", "Wheee, more pats!"],
    "stroke": ["Ooh, that feels lovely.", "Ahh, a proper head stroke!"],
    "knock": ["Hm? Who's there?", "Knock knock? Who's there?"],
    "double_knock": ["I'm awake! What's up?", "Yes? I'm here!"],
    "bump": ["Oof! I bumped into something.", "Ouch, sorry, didn't see that."],
    "shake": ["Whoa, whoa! I'm dizzy!", "Earthquake! Oh wait, it's you."],
    "tipped": ["Help! I've fallen over.", "Uh oh, I tipped over. Could you stand me up?"],
    "righted": ["Phew, thank you!", "Back on my wheels. Thanks!"],
}
TOUCH_FACE = {"touch": ("happy", 2.5), "pat": ("happy", 3.0), "hold": ("embarrassed", 4.0), "pats": ("celebrating", 4.0),
              "stroke": ("happy", 4.0)}
MOTION_FACE = {"knock": ("curious", 3.0), "double_knock": ("excited", 3.0), "bump": ("annoyed", 3.0), "shake": ("confused", 4.0),
               "tipped": ("scared", 8.0), "righted": ("happy", 3.0), "drop": ("scared", 3.0)}

PROFILE_SWITCH = re.compile(r"\b(?:switch|change|swap|use|be|become|go)\b.*?\b(?:to |the |a |into )*(.+?)\s+"
                            r"(?:profile|personality|voice|mode)\b", re.I)
PROFILE_ASK = re.compile(r"\b(?:which|what)\b.*\b(?:profile|personality)\b.*\b(?:using|on|are you)\b", re.I)


class Pro:
    def __init__(self, ctx, app, comp, full, settings, groq, profiles, touch, motion, apis):
        self.ctx, self.app, self.comp, self.full = ctx, app, comp, full
        self.settings, self.groq, self.profiles, self.touch, self.motion, self.apis = settings, groq, profiles, touch, motion, apis
        self._spoke = {}
        self._lock = threading.Lock()

    # -- helpers --

    def lifted(self):
        try:
            return bool(self.app.lift.status().get("lifted"))
        except Exception:
            return False

    def moving(self):
        try:
            return bool(self.app.executor.status().get("current"))
        except Exception:
            return False

    def _say_once(self, key, cooldown, phrases):
        now = time.monotonic()
        with self._lock:
            if now - self._spoke.get(key, -1e9) < cooldown:
                return False
            self._spoke[key] = now
        self.full.say(random.choice(phrases))
        return True

    def _wake(self, why):
        p = self.app.presence
        if p is not None and not p.awake:
            p.set_awake(True, reason=why, announce=False)

    def _move(self, action, source):
        self.app.executor.run([{"action": action, "amount": 0}], source=source)

    # -- touch --

    def on_touch(self, kind, pad, info):
        cfg = self.settings.section("touch")
        face = TOUCH_FACE.get(kind)
        if face:
            self.full.react(face[0], face[1], f"touch {kind}")
        if kind == "touch":
            self._wake("headpat")
            return
        cooldown = float(cfg.get("cooldown_s", 2.0))
        if cfg.get("speak", True) and kind in PHRASES:
            if self._say_once("touch", cooldown if kind == "pat" else 0.5, PHRASES[kind]):
                self.full.chime({"pat": "giggle", "hold": "yawn", "pats": "tada", "stroke": "giggle"}.get(kind, "pop"))
        if cfg.get("move", True) and not self.lifted() and not self.moving():
            if kind == "pats":
                self._move("celebrate", "headpats")
            elif kind in ("pat", "stroke") and self._ready("touch-move", cooldown * 2):
                self._move("nudge", "headpat")       # at most one wiggle per 2 cool-downs: every pat would be too much

    def _ready(self, key, cooldown):
        now = time.monotonic()
        with self._lock:
            if now - self._spoke.get(key, -1e9) < cooldown:
                return False
            self._spoke[key] = now
            return True

    # -- motion --

    def on_motion(self, kind, info):
        cfg = self.settings.section("motion")
        face = MOTION_FACE.get(kind)
        if face:
            self.full.react(face[0], face[1], f"motion {kind}")
        if kind in ("bump", "tipped"):
            self._move("stop", f"motion {kind}")
        if kind == "tipped":
            self.app.alerts.warn("tipped", "I've tipped over. Please stand me up.", speak=False,
                                 detail=f"tilt {info.get('deg')} degrees")
        elif kind == "righted":
            self.app.alerts.resolve("tipped", "Back on my wheels.", speak=False)
        elif kind == "double_knock":
            self._wake("knock")
            if not self.lifted():
                self._move("face_user", "knock")
        if kind == "drop":
            self.full.chime("gasp")
        elif cfg.get("speak", True) and kind in PHRASES:
            self._say_once(f"motion-{kind}", 4.0, PHRASES[kind])

    # -- profiles by voice --

    def pre_handler(self, text, tool_ctx):
        t = text.strip()
        if PROFILE_ASK.search(t):
            name = self.profiles.active or "a custom one"
            return {"speech": f"I'm using the {name} profile.", "mood": "neutral", "sound": "none", "commands": []}
        m = PROFILE_SWITCH.search(t)
        if not m:
            return None
        wanted = re.sub(r"^(?:(?:to|the|a|an|my|into|your)\s+)+", "", m.group(1).strip(), flags=re.I)
        key = self.profiles.find(wanted)
        if key is None:
            return None            # not a profile name: let the AI handle "use a deeper voice" and so on
        self.profiles.apply(key)
        return {"speech": f"Switched to {key}.", "mood": "happy", "sound": "tada", "commands": []}

    def context_lines(self):
        t = self.touch.status()["today"]
        lines = [f"Headpats today: {t['pats']}"]
        if self.motion.det.tipped:
            lines.append("The robot is lying on its side (tipped over).")
        return lines

    def status(self):
        return {"settings": self.settings.all(), "touch": self.touch.status(), "motion": self.motion.status(),
                "groq": self.groq.status(), "profiles": self.profiles.status(),
                "voice": {k: self.app.settings.get(k) for k in ("voice_style", "voice_gender", "voice_name", "voice_pitch",
                                                                  "voice_speed", "chipmunk_factor", "volume")}}
