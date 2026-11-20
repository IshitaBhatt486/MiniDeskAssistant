"""
Smart home: switch lights, plugs and fans on your own Wi-Fi. No cloud: the robot talks to the devices directly.

Devices: data/smart_home.json (the dashboard's Smart home card adds and removes them):
    [{"name": "desk lamp", "aliases": ["lamp"], "type": "homeassistant", "entity_id": "light.desk_lamp"},
     {"name": "fan", "type": "shelly", "host": "192.168.1.50"},             Shelly Gen2+ (RPC Switch.Set)
     {"name": "heater", "type": "shelly1", "host": "192.168.1.51"},         Shelly Gen1 (/relay/0)
     {"name": "strip", "type": "tasmota", "host": "192.168.1.52"}]          Tasmota (/cm?cmnd=Power On, Dimmer 50)

    Home Assistant: HA_URL (e.g. http://homeassistant.local:8123) and HA_TOKEN (Profile -> Security -> Long-lived
    access tokens) in secrets.env. Services: light/switch/fan .turn_on/.turn_off/.toggle; brightness_pct for "set".
    GET /api/states lists your lights, switches and fans so you can pick (the dashboard's "Find devices").

Voice: "turn on the desk lamp", "switch the fan off", "lamp off", "set the lamp to 30 percent", "dim the lamp",
"is the fan on?". These are matched BEFORE the robot's own commands (Brain.pre_handlers), but only when a known
device name is in the sentence, so "turn left" still turns the robot. The AI gets a smart_home tool too.

Safety: only private-network addresses (and *.local names) are accepted for devices and HA_URL; the HA token is
never shown or logged; 4 s timeouts.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TYPES = ("homeassistant", "shelly", "shelly1", "tasmota")
TIMEOUT = 4.0


class SmartHomeError(Exception):
    pass


def check_lan(url_or_host):
    host = urllib.parse.urlsplit(url_or_host if "//" in url_or_host else f"http://{url_or_host}").hostname or ""
    if host.endswith(".local") or host == "localhost":
        return host
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise SmartHomeError(f"{host!r}: use an IP address on your network or a name.local") from exc
    if not (ip.is_private or ip.is_loopback):
        raise SmartHomeError(f"{host} is not on your local network")
    return host


def _http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={**({"Content-Type": "application/json"} if body is not None else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip().startswith((b"{", b"[")) else {}
    except urllib.error.HTTPError as exc:
        raise SmartHomeError(f"the device answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SmartHomeError(f"can't reach it ({getattr(exc, 'reason', exc)})") from exc


class SmartHome:
    def __init__(self, path: Path, http=_http):
        self.path = Path(path)
        self.http = http
        self.devices = []
        self.last = None
        self.load()

    # -- devices --

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            self.devices = [self.validate(d) for d in data]
        except (OSError, ValueError, SmartHomeError):
            self.devices = []
        return self

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.devices, indent=2), encoding="utf-8")

    def validate(self, d):
        if not isinstance(d, dict):
            raise SmartHomeError("a device must be an object")
        name = " ".join(str(d.get("name", "")).lower().split())[:40]
        typ = d.get("type")
        if not name or typ not in TYPES:
            raise SmartHomeError(f"a device needs a name and a type ({', '.join(TYPES)})")
        out = {"name": name, "type": typ, "aliases": [" ".join(str(a).lower().split())[:40] for a in d.get("aliases", []) if str(a).strip()][:5]}
        if typ == "homeassistant":
            eid = str(d.get("entity_id", "")).strip()
            if not re.fullmatch(r"(light|switch|fan|input_boolean)\.[a-z0-9_]+", eid):
                raise SmartHomeError("entity_id must look like light.desk_lamp (light, switch, fan or input_boolean)")
            out["entity_id"] = eid
        else:
            out["host"] = check_lan(str(d.get("host", "")).strip())
        return out

    def add(self, d):
        dev = self.validate(d)
        self.devices = [x for x in self.devices if x["name"] != dev["name"]] + [dev]
        self.save()
        return dev

    def remove(self, name):
        before = len(self.devices)
        self.devices = [x for x in self.devices if x["name"] != name]
        if len(self.devices) == before:
            raise LookupError(f"no device called {name!r}")
        self.save()

    def find(self, text):
        t = " " + " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split()) + " "
        best = None
        for d in self.devices:
            for n in [d["name"], *d["aliases"]]:
                if f" {n} " in t and (best is None or len(n) > best[1]):
                    best = (d, len(n))
        return best[0] if best else None

    # -- Home Assistant --

    def _ha(self):
        url, token = os.environ.get("HA_URL", "").rstrip("/"), os.environ.get("HA_TOKEN", "")
        if not url or not token:
            raise SmartHomeError("Home Assistant isn't set up: add HA_URL and HA_TOKEN to secrets.env")
        check_lan(url)
        return url, {"Authorization": f"Bearer {token}"}

    def discover(self):
        url, h = self._ha()
        states = self.http("GET", f"{url}/api/states", headers=h)
        return [{"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"]), "state": s.get("state")}
                for s in states if s.get("entity_id", "").split(".")[0] in ("light", "switch", "fan", "input_boolean")]

    # -- control --

    def control(self, device, action, value=None):
        """action: on | off | toggle | set (value 0-100) | status. Returns {"device", "state"}."""
        d = device if isinstance(device, dict) else self.find(f" {device} ")
        if d is None:
            raise SmartHomeError(f"I don't know a device called {device!r}")
        if action not in ("on", "off", "toggle", "set", "status"):
            raise SmartHomeError("action must be on, off, toggle, set or status")
        typ = d["type"]
        state = action
        if typ == "homeassistant":
            url, h = self._ha()
            domain = d["entity_id"].split(".")[0]
            if action == "status":
                state = self.http("GET", f"{url}/api/states/{d['entity_id']}", headers=h).get("state")
            else:
                service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle", "set": "turn_on"}[action]
                body = {"entity_id": d["entity_id"]}
                if action == "set" and domain == "light":
                    body["brightness_pct"] = max(1, min(100, int(value or 50)))
                self.http("POST", f"{url}/api/services/{domain if domain != 'input_boolean' else 'input_boolean'}/{service}", body, headers=h)
        elif typ == "shelly":
            base = f"http://{d['host']}/rpc"
            if action == "status":
                state = "on" if self.http("GET", f"{base}/Switch.GetStatus?id=0").get("output") else "off"
            elif action == "toggle":
                self.http("GET", f"{base}/Switch.Toggle?id=0")
            else:
                self.http("GET", f"{base}/Switch.Set?id=0&on={'false' if action == 'off' else 'true'}")
        elif typ == "shelly1":
            base = f"http://{d['host']}/relay/0"
            if action == "status":
                state = "on" if self.http("GET", base).get("ison") else "off"
            else:
                self.http("GET", f"{base}?turn={'toggle' if action == 'toggle' else 'off' if action == 'off' else 'on'}")
        else:   # tasmota
            def cmd(c):
                return self.http("GET", f"http://{d['host']}/cm?cmnd={urllib.parse.quote(c)}")
            if action == "status":
                state = str(cmd("Power").get("POWER", "?")).lower()
            elif action == "set":
                cmd(f"Dimmer {max(1, min(100, int(value or 50)))}")
            else:
                cmd(f"Power {'Toggle' if action == 'toggle' else 'Off' if action == 'off' else 'On'}")
        self.last = {"device": d["name"], "action": action, "value": value, "state": state}
        return self.last

    def voice(self, text):
        """(device, action, value) if the sentence controls a known device, else None."""
        d = self.find(text)
        if d is None:
            return None
        t = text.lower()
        m = re.search(r"\b(?:set|dim|brighten|put)\b.*?\b(\d{1,3})\s*(?:%|percent)?", t)
        if m:
            return d, "set", int(m.group(1))
        if re.search(r"\bdim\b", t):
            return d, "set", 30
        if re.search(r"\bis\b.*\b(on|off)\b\??$|\bstatus\b", t):
            return d, "status", None
        if re.search(r"\btoggle\b", t):
            return d, "toggle", None
        if re.search(r"\b(off|out)\b", t):
            return d, "off", None
        if re.search(r"\bon\b", t):
            return d, "on", None
        return None

    def status(self):
        return {"devices": self.devices, "last": self.last,
                "home_assistant": bool(os.environ.get("HA_URL") and os.environ.get("HA_TOKEN")), "types": list(TYPES)}


PROMPT = """Smart home: the devices are listed in robot_context. "Turn on the lamp" and similar are handled before you
see them; if one reaches you, call smart_home (action on | off | toggle | set with value 0-100 | status)."""

TOOL_SPECS = [{"name": "smart_home", "description": "Switch or dim a smart-home device, or read its state.",
               "input_schema": {"type": "object", "properties": {
                   "device": {"type": "string"}, "action": {"type": "string", "enum": ["on", "off", "toggle", "set", "status"]},
                   "value": {"type": "integer", "description": "Brightness 0-100 for set; otherwise 0."}},
                   "required": ["device", "action", "value"], "additionalProperties": False}}]
