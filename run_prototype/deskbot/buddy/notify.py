"""
Phone notifications: receive them, decide which are important, and queue those to be read aloud.

How they arrive: the phone posts each notification to the robot over Wi-Fi (POST /api/notify, JSON, with a
token). On Android an automation app (MacroDroid, Tasker, Automate) does it with a "notification received"
trigger and an "HTTP request" action; setup in docs/buddy.md. The body is flexible, so most apps' variable
names work:

    {"token": "...", "app": "WhatsApp", "title": "Mom", "text": "Call me when you're free",
     "category": "msg", "priority": 1, "package": "com.whatsapp"}
    aliases: app_name / application -> app; sender / from -> title; message / body / content -> text

Deciding "important" (triage):
    1. sensitive: one-time codes, passwords, PINs, verification links -> BLOCKED. Never spoken, never sent to
       the AI, text not kept (the dashboard shows only the app).
    2. rules give a score (see score()):
           +4 a VIP name (settings) in the sender or text      +3 urgent words ("urgent", "call me", "missed call")
           +3 calls, alarms, reminders, calendar events         +3 an app on your "always" list, or one of your keywords
           +2 a message from a messaging app                     +1 e-mail, work chat, high Android priority
           -3 promotions, social likes, "is live", downloads, battery, system noise, low priority
           -10 an app on your muted list
       score >= 3 -> important;  score <= 0 -> skipped;  1-2 -> "maybe"
    3. a "maybe" goes to the AI (Claude, structured output: important yes/no + a short spoken line), if
       the AI is on in the settings and available. Without the AI a maybe with score 2 (a plain message from a
       person) counts as important, score 1 doesn't.

Repeats (the same app + title + text within 10 minutes, e.g. a notification being updated) are ignored.
Everything is kept in memory only (last 60), never written to disk.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
from collections import deque

MAX_FIELD = 400
DEDUPE_S = 600

SENSITIVE = re.compile(r"\b(?:otp|one[- ]time (?:password|code|pin)|verification (?:code|link)|security code|passcode|"
                       r"password|login code|sign[- ]in code|2fa|two[- ]factor|auth(?:entication)? code|cvv|pin(?: code)?)\b"
                       r"|\b\d{4,8}\b (?:is|as) (?:your|the)\b|\bcode[: ]+\d{4,8}\b", re.I)
URGENT = re.compile(r"\b(?:urgent|urgently|asap|emergency|important|call me|call back|missed call|deadline|right now|"
                    r"immediately|help|are you (?:ok|okay|there)|where are you|pick up|running late|on my way|"
                    r"cancel+ed|reschedul\w*|due (?:today|tomorrow|soon))\b", re.I)
NOISE = re.compile(r"\b(?:\d+ ?% off|sale|offer|deals?|discount|promo\w*|coupon|cashback|limited time|subscribe|"
                   r"new followers?|followed you|liked your|likes your|reacted to|is live|went live|live now|trending|"
                   r"recommended|you might like|suggested|backup|backing up|downloading|downloaded|uploading|syncing|"
                   r"charging|fully charged|battery|update available|updated|screenshot|usb|wi-?fi|bluetooth|"
                   r"tap to|weekly summary|digest|newsletter|unsubscribe|reward|points|streak)\b", re.I)

CATEGORY = {"call": 3, "alarm": 3, "reminder": 3, "event": 3, "msg": 2, "message": 2, "email": 1,
            "promo": -3, "social": -3, "recommendation": -3, "status": -3, "progress": -3, "transport": -3,
            "service": -3, "sys": -3, "system": -3}
# substrings of the app name or Android package -> (points, kind)
APPS = [
    (("dialer", "phone", "incallui", "telecom", "call"), 3, "call"),
    (("calendar",), 3, "calendar"), (("clock", "alarm", "deskclock"), 3, "alarm"),
    (("whatsapp", "signal", "telegram", "messages", "mms", "sms", "messenger", "imessage", "viber", "line"), 2, "message"),
    (("gmail", "outlook", "mail"), 1, "email"),
    (("slack", "teams", "discord", "classroom", "zoom", "meet"), 1, "work"),
    (("instagram", "facebook", "twitter", "x.android", "youtube", "snapchat", "tiktok", "reddit", "linkedin",
      "amazon", "flipkart", "swiggy", "zomato", "myntra", "netflix", "spotify", "game", "store", "play"), -2, "noise"),
]
IMPORTANT, MAYBE_LOW, MAYBE_HIGH = 3, 1, 2


def _field(payload, *names):
    for n in names:
        v = payload.get(n)
        if v not in (None, ""):
            return " ".join(str(v).split())[:MAX_FIELD]
    return ""


def normalise_payload(payload):
    """The phone's JSON -> {"app", "package", "title", "text", "category", "priority"}."""
    if not isinstance(payload, dict):
        raise ValueError("the notification must be a JSON object")
    n = {"app": _field(payload, "app", "app_name", "application", "appName", "package"),
         "package": _field(payload, "package", "pkg", "packageName"),
         "title": _field(payload, "title", "sender", "from", "name"),
         "text": _field(payload, "text", "message", "body", "content", "bigtext", "big_text"),
         "category": _field(payload, "category", "cat").lower(),
         "priority": 0}
    try:
        p = payload.get("priority", 0)
        words = {"max": 2, "urgent": 2, "high": 1, "default": 0, "normal": 0, "low": -1, "min": -2}
        n["priority"] = words[str(p).lower()] if str(p).lower() in words else max(-2, min(2, int(float(p))))
    except (TypeError, ValueError):
        n["priority"] = 0
    if not (n["title"] or n["text"]):
        raise ValueError("the notification needs a title or text")
    n["app"] = n["app"] or "your phone"
    return n


def app_kind(n):
    hay = f"{n['app']} {n['package']}".lower()
    for keys, points, kind in APPS:
        if any(k in hay for k in keys):
            return points, kind
    return 0, "other"


def score(n, prefs):
    """(score, reasons, kind). prefs: the buddy settings' "notify" dict."""
    if SENSITIVE.search(f"{n['title']} {n['text']}"):
        return None, ["contains a code or password"], "sensitive"
    hay_app = f"{n['app']} {n['package']}".lower()
    text = f"{n['title']} {n['text']}"
    reasons, s = [], 0
    if any(m.strip() and m.strip().lower() in hay_app for m in prefs.get("muted_apps", [])):
        return -10, ["muted app"], "muted"
    points, kind = app_kind(n)
    if points:
        s += points
        reasons.append(f"{kind} app {points:+d}")
    cat = CATEGORY.get(n["category"])
    if cat:
        s += cat
        reasons.append(f"category {n['category']} {cat:+d}")
    if any(a.strip() and a.strip().lower() in hay_app for a in prefs.get("important_apps", [])):
        s += 3
        reasons.append("always-app +3")
    low = text.lower()
    vip = next((v for v in prefs.get("vip", []) if v.strip() and re.search(rf"\b{re.escape(v.strip().lower())}\b", low)), None)
    if vip:
        s += 4
        reasons.append(f"VIP {vip} +4")
    if URGENT.search(text):
        s += 3
        reasons.append("urgent words +3")
    kw = next((k for k in prefs.get("keywords", []) if k.strip() and k.strip().lower() in low), None)
    if kw:
        s += 3
        reasons.append(f"keyword {kw} +3")
    if NOISE.search(text):
        s -= 3
        reasons.append("promo/noise -3")
    if n["priority"] >= 1:
        s += 1
        reasons.append("high priority +1")
    elif n["priority"] < 0:
        s -= 2
        reasons.append("low priority -2")
    return s, reasons, kind


def spoken(n, kind, read_text=True):
    """The default spoken line (the AI writes its own for the ones it judges)."""
    who, app, text = n["title"], n["app"], n["text"]
    if kind == "call" or "missed call" in f"{who} {text}".lower():
        caller = re.sub(r"(?i)missed call( from)?", "", who).strip(" :") or re.sub(r"(?i)missed call( from)?", "", text).strip(" :")
        return f"Missed call from {caller or 'someone'}."
    if kind in ("calendar", "alarm"):
        return f"{app}: {who}{'. ' + text if text and read_text else ''}."
    if not read_text:
        return f"New {app} notification from {who or app}."
    body = text if len(text) <= 160 else text[:157].rsplit(" ", 1)[0] + "..."
    if who and body:
        return f"{who} on {app}: {body}"
    return f"{app}: {who or body}"


# ---------------- the AI's opinion ----------------

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "important": {"type": "boolean"},
        "reason": {"type": "string", "description": "Why, in a few words."},
        "speech": {"type": "string", "description": "What the robot says if important: one short sentence naming the "
                                                    "sender and the gist, no emoji. Empty if not important."},
    },
    "required": ["important", "reason", "speech"],
    "additionalProperties": False,
}
TRIAGE_SYSTEM = """You filter phone notifications for a desk robot that reads only the IMPORTANT ones aloud to its owner,
who is working at their desk. Interrupting is costly: say important only for things a person would want to hear
right now, e.g. a real person messaging them directly about something that matters, time-sensitive plans, family,
deliveries arriving now, security alerts, work or study deadlines. Not important: marketing, social media activity,
group chatter, newsletters, app updates, routine status. The owner's preferences: {prefs}"""


def make_ai_triage(brain, settings, on_usage=None):
    """fn(notification) -> {"important", "reason", "speech"} using the assistant's Claude client, or None.
    on_usage(usage dict): token counts of each call (hub/costs.py counts them)."""
    claude = brain.claude

    def triage(n, prefs):
        if not claude.available():
            raise RuntimeError("AI not available")
        p = {k: prefs.get(k) for k in ("vip", "keywords", "important_apps")}
        # same call shape as assistant/brain.py (structured output via output_config.format)
        resp = claude.client().beta.messages.create(
            model=settings.get("model", "claude-haiku-5-5"), max_tokens=300,
            system=TRIAGE_SYSTEM.format(prefs=json.dumps(p)),
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
            messages=[{"role": "user", "content": json.dumps({k: n[k] for k in ("app", "title", "text", "category")})}])
        if on_usage is not None and getattr(resp, "usage", None) is not None:
            u = resp.usage
            on_usage({"input": u.input_tokens or 0, "output": u.output_tokens or 0,
                      "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                      "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                      "model": settings.get("model", "claude-haiku-5-5")})
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return json.loads(text)
    triage.available = claude.available
    return triage


# ---------------- the inbox ----------------

class NotificationCenter:
    """receive() -> triage on a worker thread -> important ones wait in `outbox` for buddy/core.py to say."""

    def __init__(self, prefs, ai_triage=None, clock=time.time, log=print):
        self.prefs = prefs                  # fn() -> the buddy settings' "notify" dict
        self.ai_triage = ai_triage          # fn(n, prefs) -> dict, or None
        self.clock = clock
        self.log = log
        self.history = deque(maxlen=60)
        self.outbox = []                    # important entries not said yet (oldest first)
        self._recent = {}                   # dedupe key -> time
        self._lock = threading.Lock()
        self._q = queue.Queue(maxsize=50)
        self._id = 0
        self._running = False
        self.received = 0

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="notify", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def receive(self, payload, source="phone", sync=False):
        n = normalise_payload(payload)
        now = self.clock()
        key = hashlib.sha1(f"{n['app']}|{n['title']}|{n['text']}".encode()).hexdigest()
        with self._lock:
            self.received += 1
            self._id += 1
            entry = {"id": self._id, "t": now, "source": source, "app": n["app"], "title": n["title"], "text": n["text"],
                     "status": "triaging", "score": None, "reasons": [], "decided_by": None, "speech": None}
            self._recent = {k: t for k, t in self._recent.items() if now - t < DEDUPE_S}
            if key in self._recent:
                entry["status"] = "duplicate"
                self.history.append(entry)
                return dict(entry)
            self._recent[key] = now
            self.history.append(entry)
        if sync:
            self._triage(entry, n)
        else:
            try:
                self._q.put_nowait((entry, n))
            except queue.Full:
                entry["status"], entry["reasons"] = "dropped", ["too many at once"]
        return dict(entry)

    def _loop(self):
        while self._running:
            try:
                entry, n = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._triage(entry, n)
            except Exception as exc:
                entry["status"], entry["reasons"] = "error", [f"{type(exc).__name__}: {exc}"[:120]]

    def _triage(self, entry, n):
        prefs = self.prefs()
        s, reasons, kind = score(n, prefs)
        entry["reasons"], entry["kind"] = reasons, kind
        if s is None:
            entry.update(status="blocked", decided_by="rules", title="(hidden)", text="")   # never kept, never said
            return
        entry["score"] = s
        if s >= IMPORTANT:
            important, by, line = True, "rules", spoken(n, kind, prefs.get("read_text", True))
        elif s < MAYBE_LOW:
            important, by, line = False, "rules", None
        else:
            important, by, line = s >= MAYBE_HIGH, "rules (no AI)", None
            if self.ai_triage and prefs.get("use_ai", True):
                try:
                    verdict = self.ai_triage(n, prefs)
                    important, by = bool(verdict.get("important")), "ai"
                    entry["reasons"] = reasons + [f"AI: {verdict.get('reason', '')}"[:120]]
                    line = (verdict.get("speech") or "").strip() or None
                except Exception as exc:
                    entry["reasons"] = reasons + [f"AI unavailable ({type(exc).__name__})"]
            if important and not line:
                line = spoken(n, kind, prefs.get("read_text", True))
            if important and not prefs.get("read_text", True):
                line = spoken(n, kind, False)
        entry["decided_by"] = by
        if not important:
            entry["status"] = "skipped"
            return
        entry["speech"] = line
        with self._lock:
            entry["status"] = "waiting"
            self.outbox.append(entry)

    # -- for the speaker side (buddy/core.py) --

    def expire(self, max_age_s):
        now = self.clock()
        with self._lock:
            for e in [e for e in self.outbox if now - e["t"] > max_age_s]:
                e["status"] = "expired"
                self.outbox.remove(e)

    def take(self, n=None):
        """Remove and return the waiting entries (all, or the oldest n)."""
        with self._lock:
            out = self.outbox[: n or len(self.outbox)]
            del self.outbox[: len(out)]
            return out

    def recent_lines(self, max_age_s=3600, limit=3):
        """For the AI's context: the newest important ones, so 'what did Mom say?' works."""
        now = self.clock()
        items = [e for e in list(self.history) if e["status"] in ("spoken", "waiting") and now - e["t"] < max_age_s][-limit:]
        if not items:
            return []
        return ["Recent important phone notifications: " + "; ".join(
            f"{round((now - e['t']) / 60)} min ago, {e['app']}, from {e['title'] or '?'}: {e['text'][:160]}" for e in items) + "."]

    def status(self):
        with self._lock:
            hist = [dict(e) for e in reversed(self.history)]
            waiting = len(self.outbox)
        return {"history": hist[:30], "waiting": waiting, "received": self.received,
                "ai": bool(self.ai_triage) and getattr(self.ai_triage, "available", lambda: True)()
                      and self.prefs().get("use_ai", True)}
