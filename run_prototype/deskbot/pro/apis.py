"""
Accounts and APIs (20 Nov 2026), for the dashboard's "Accounts" and "APIs in use" cards. View only: keys are
changed by editing secrets.env on the robot (and restarting), never over HTTP.

Masking: a key is shown as its type prefix (up to the first "_" or "-", max 4 characters, e.g. "gsk_") plus
"..." plus its last 4 characters, so you can tell WHICH key is loaded without revealing it. PINs, passwords and
encryption keys only ever show "set" / "not set". Nothing longer leaves the robot.

"In use" means: the service is configured AND switched on AND is what the robot would call right now (for the
brain and speech-to-text that is the first one in the fallback order). Web tools (weather, Wikipedia, jokes,
currency) are counted from each conversation turn's tool calls.
"""

from __future__ import annotations

import os
import time
import urllib.parse

SECRETS = [   # (env, service, used for, kind: key | secret | url | id)
    ("GROQ_API_KEY", "Groq", "AI brain (first choice) and Whisper speech-to-text", "key"),
    ("ANTHROPIC_API_KEY", "Anthropic Claude", "AI brain (fallback after Groq), reading, notification triage", "key"),
    ("OPENAI_API_KEY", "OpenAI", "Whisper speech-to-text (paid, off unless allowed)", "key"),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot", "messages to and from your phone", "key"),
    ("HA_URL", "Home Assistant", "smart-home server address", "url"),
    ("HA_TOKEN", "Home Assistant", "smart-home access token", "key"),
    ("GOOGLE_CLIENT_ID", "Google", "Calendar sign-in (OAuth client)", "id"),
    ("GOOGLE_CLIENT_SECRET", "Google", "Calendar sign-in (OAuth secret)", "secret"),
    ("SPOTIFY_CLIENT_ID", "Spotify", "music control sign-in (OAuth client)", "id"),
    ("OLLAMA_URL", "Ollama (local AI)", "address of the local AI server", "url"),
    ("ADMIN_PIN", "Robot", "PIN for protected dashboard actions", "secret"),
    ("ACCOUNTS_KEY", "Robot", "encryption key for saved account tokens", "secret"),
    ("NOTIFY_TOKEN", "Robot", "token phones use to post notifications", "secret"),
]
TOOL_APIS = {"get_weather": "Open-Meteo (weather)", "wikipedia_summary": "Wikipedia", "tell_joke": "Official Joke API",
             "convert_currency": "open.er-api.com (currency)"}


def mask(value, kind):
    if not value:
        return None
    if kind == "secret":
        return "set"
    if kind == "url":
        p = urllib.parse.urlsplit(value)
        return f"{p.scheme}://{p.hostname or ''}{':' + str(p.port) if p.port else ''}"
    if len(value) < 12:
        return "set"
    prefix = ""
    for sep in ("_", "-"):
        i = value.find(sep)
        if 0 < i <= 4:
            prefix = value[:i + 1]
            break
    return f"{prefix}…{value[-4:]}"


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


class ApiInventory:
    def __init__(self, app, hub=None, full=None, groq=None, env=os.environ):
        self.app, self.hub, self.full, self.groq, self.env = app, hub, full, groq, env
        self.tool_uses = {}        # api name -> {"count", "last"}
        self.brain_uses = {}       # backend -> {"count", "last"}

    def on_turn(self, entry):
        """Assistant turn listener: count which brain answered and which web APIs its tools called."""
        now = time.time()
        b = entry.get("backend")
        if b:
            row = self.brain_uses.setdefault(b, {"count": 0, "last": None})
            row["count"] += 1
            row["last"] = now
        for t in entry.get("tools") or []:
            name = TOOL_APIS.get(t.get("name"))
            if name:
                row = self.tool_uses.setdefault(name, {"count": 0, "last": None})
                row["count"] += 1
                row["last"] = now

    # -- accounts (view only) --

    def accounts(self):
        keys = []
        for env, service, used_for, kind in SECRETS:
            v = self.env.get(env, "")
            keys.append({"env": env, "service": service, "used_for": used_for, "set": bool(v), "shown": mask(v, kind)})
        linked = []
        if self.hub is not None:
            for name, r in (_safe(self.hub.accounts.status, {}) or {}).items():
                linked.append({"provider": r.get("title", name), "configured": r.get("configured"), "connected": r.get("connected"),
                               "account": r.get("account"), "scopes": r.get("scopes") or [], "last_used": r.get("last_used"),
                               "error": r.get("error")})
        if self.full is not None:
            t = _safe(self.full.telegram.status, {}) or {}
            linked.append({"provider": "Telegram", "configured": t.get("configured"), "connected": bool(t.get("paired")),
                           "account": f"@{t['bot']} · {t.get('paired', 0)} chat(s)" if t.get("bot") else None, "scopes": [],
                           "last_used": None, "error": t.get("error")})
        return {"keys": keys, "linked": linked, "secrets_file": "secrets.env (on the robot)",
                "how_to_change": "Edit secrets.env on the robot, then restart it. Keys are never changed from the dashboard."}

    # -- what is being used right now --

    def in_use(self):
        a = self.app
        rows = []
        brain = _safe(a.brain.status, {}) or {}
        order = brain.get("order") or []
        for i, name in enumerate(order):
            title = {"groq": "Groq chat", "claude": "Anthropic Claude", "local": "Ollama (local AI)", "offline": "Offline rules"}.get(name, name)
            model = (self.groq.model() if name == "groq" and self.groq else
                     a.settings.get("model") if name == "claude" else None)
            u = self.brain_uses.get(name, {})
            rows.append({"group": "AI brain", "name": title, "state": "active" if i == 0 else "fallback",
                         "detail": " · ".join(x for x in (model, f"#{i + 1} in order") if x),
                         "count": u.get("count", 0), "last": u.get("last")})
        stt = _safe(a.stt.status, {}) or {}
        for i, name in enumerate(stt.get("available") or []):
            title = {"local": "faster-whisper (on the robot)", "groq": "Groq Whisper", "openai": "OpenAI Whisper",
                     "windows": "Windows speech (laptop)"}.get(name, name)
            last = stt.get("last") or {}
            rows.append({"group": "Speech to text", "name": title, "state": "active" if i == 0 else "fallback",
                         "detail": f"last: {last.get('ms')} ms" if last.get("backend") == name else "",
                         "count": None, "last": None})
        if not stt.get("available"):
            rows.append({"group": "Speech to text", "name": "none available", "state": "off",
                         "detail": "add GROQ_API_KEY or install faster-whisper", "count": None, "last": None})
        sp = _safe(a.speaker.status, {}) or {}
        rows.append({"group": "Voice", "name": f"{sp.get('engine') or 'no'} text-to-speech", "state": "active" if sp.get("engine") else "off",
                     "detail": " · ".join(x for x in (a.settings.get("voice_name") or "default voice", sp.get("player")) if x),
                     "count": sp.get("spoken"), "last": None})
        if self.full is not None:
            w = _safe(self.full.wake.status, {}) or {}
            rows.append({"group": "Wake word", "name": w.get("backend") or "Vosk / Whisper", "state": "active" if w.get("enabled") else "off",
                         "detail": f"\"{w.get('phrase', '')}\"", "count": w.get("count"), "last": None})
            ol = self.full.ollama
            rows.append({"group": "Local AI", "name": "Ollama", "state": "active" if ol._models else ("off" if ol.last_error else "standby"),
                         "detail": ol.url if not ol.last_error else "not reachable", "count": None, "last": None})
            t = _safe(self.full.telegram.status, {}) or {}
            rows.append({"group": "Messaging", "name": "Telegram Bot API", "state": "active" if t.get("paired") else
                         ("standby" if t.get("configured") else "off"), "detail": f"{t.get('sent', 0)} sent · {t.get('received', 0)} received",
                         "count": None, "last": None})
            sh = _safe(self.full.smarthome.status, {}) or {}
            rows.append({"group": "Smart home", "name": "Home Assistant" if sh.get("home_assistant") else "Shelly / Tasmota (local)",
                         "state": "active" if sh.get("devices") else "off", "detail": f"{len(sh.get('devices') or [])} device(s)",
                         "count": None, "last": None})
        if self.hub is not None:
            for name, r in (_safe(self.hub.accounts.status, {}) or {}).items():
                rows.append({"group": "Accounts", "name": r.get("title", name) + " API",
                             "state": "active" if r.get("connected") else ("standby" if r.get("configured") else "off"),
                             "detail": r.get("account") or ("not connected" if r.get("configured") else "no client id"),
                             "count": None, "last": r.get("last_used")})
        for name in TOOL_APIS.values():
            u = self.tool_uses.get(name, {})
            rows.append({"group": "Web tools (free, no key)", "name": name, "state": "active" if u else "standby",
                         "detail": "called by the AI when needed", "count": u.get("count", 0), "last": u.get("last")})
        return {"rows": rows, "brain": brain.get("backend"), "t": time.time()}
