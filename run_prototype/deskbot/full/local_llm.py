"""
A local AI through Ollama (ollama.com): free, private, no internet. Used three ways:

    OllamaBrain   answers conversation in the robot's JSON reply format when Claude is off, missing or over its
                  daily cap (Brain.fallback_brains). No tools: tasks, ideas, routines, music and so on are still
                  handled by the local sentence rules, which run first.
    read_image    reads the text in a photo with a vision model (reader.py)
    summarise     short summaries / flashcards of read text (reader.py)

Where it runs: on the Pi itself (a 1-3B model; slow on a Pi 4: a reply takes ~5-20 s), or, much faster, on your
laptop on the same Wi-Fi: OLLAMA_URL=http://<laptop-ip>:11434 in secrets.env, and on the laptop start Ollama with
OLLAMA_HOST=0.0.0.0 so it listens on the network. Only private-network addresses are accepted (the local-only promise).

Models (settings, data/full.json): text "llama3.2:3b" (or "llama3.2:1b" / "qwen2.5:1.5b" on a Pi), vision
"qwen2.5vl:3b". Pull them once: `ollama pull llama3.2:3b` and `ollama pull qwen2.5vl:3b`.

API: POST /api/chat {"model", "messages", "stream": false, "format": <JSON schema>, "options": {...}}; images are
base64 strings in the message's "images" list. Structured output (format = schema) needs Ollama 0.5 or newer.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..assistant.commands import MOODS, SOUNDS, describe_actions

DEFAULT_URL = "http://127.0.0.1:11434"


class LocalLLMError(Exception):
    pass


def check_local_url(url):
    """Only loopback / private-network Ollama servers: a cloud URL here would break the local-only promise."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https"):
        raise LocalLLMError("OLLAMA_URL must start with http://")
    if host in ("localhost",) or host.endswith(".local"):
        return url.rstrip("/")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise LocalLLMError("OLLAMA_URL must be an IP address on your network (or localhost / name.local)") from exc
    if not (ip.is_private or ip.is_loopback or ip.is_link_local):
        raise LocalLLMError("OLLAMA_URL must be on your own network")
    return url.rstrip("/")


class Ollama:
    def __init__(self, settings=lambda: {}, url=None, timeout=60.0):
        self.settings = settings
        self.url = check_local_url(url or os.environ.get("OLLAMA_URL") or DEFAULT_URL)
        self.timeout = timeout
        self._models = None
        self._checked = 0.0
        self.last_error = None

    def _post(self, path, body, timeout=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            msg = exc.read().decode(errors="replace")[:200]
            raise LocalLLMError(f"Ollama error {exc.code}: {msg}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LocalLLMError(f"can't reach Ollama at {self.url} ({getattr(exc, 'reason', exc)})") from exc

    def models(self, max_age=30.0):
        """Installed model names (cached), or [] when Ollama isn't running."""
        if self._models is not None and time.monotonic() - self._checked < max_age:
            return self._models
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=2.0) as r:
                self._models = [m["name"] for m in json.loads(r.read()).get("models", [])]
            self.last_error = None
        except Exception as exc:
            self._models, self.last_error = [], f"{type(exc).__name__}: {exc}"[:150]
        self._checked = time.monotonic()
        return self._models

    def has(self, model):
        names = self.models()
        return model in names or f"{model}:latest" in names

    def chat(self, model, messages, schema=None, temperature=0.4, max_tokens=300, timeout=None):
        if not self.has(model):
            raise LocalLLMError(f"Ollama has no model {model!r}: run `ollama pull {model}`")
        body = {"model": model, "messages": messages, "stream": False, "keep_alive": "10m",
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if schema is not None:
            body["format"] = schema
        out = self._post("/api/chat", body, timeout)
        return out.get("message", {}).get("content", "")

    def read_image(self, jpeg, model=None, instruction="Transcribe all the text in this image exactly, keeping line breaks. "
                                                           "Output only the text."):
        model = model or self.settings().get("vision_model", "qwen2.5vl:3b")
        return self.chat(model, [{"role": "user", "content": instruction, "images": [base64.b64encode(jpeg).decode()]}],
                         temperature=0.0, max_tokens=1500,
                         timeout=float(self.settings().get("vision_timeout_s", 300))).strip()   # slow machines: first load is minutes

    def summarise(self, text, kind="summary", model=None):
        model = model or self.settings().get("text_model", "llama3.2:3b")
        ask = {"summary": "Summarise this in 2-4 short spoken sentences.",
               "flashcards": "Make up to 6 flashcards from this, one per line as 'Q: ... | A: ...'."}[kind]
        return self.chat(model, [{"role": "user", "content": f"{ask}\n\n{text[:6000]}"}], temperature=0.2, max_tokens=500,
                         timeout=180).strip()


REPLY_SCHEMA = {   # the robot's reply format without navigate's object fields (small models do better with less)
    "type": "object",
    "properties": {
        "speech": {"type": "string"},
        "mood": {"type": "string", "enum": MOODS},
        "sound": {"type": "string", "enum": list(SOUNDS)},
        "commands": {"type": "array", "items": {"type": "object", "properties": {
            "action": {"type": "string"}, "amount": {"type": "number"}}, "required": ["action", "amount"]}},
    },
    "required": ["speech", "mood", "sound", "commands"],
}

SYSTEM = """You are {name}, a small cheerful two-wheeled robot on a desk. You hear the user through speech-to-text.
Reply in JSON: "speech" (1-2 short spoken sentences, no emoji or lists), "mood" (one of {moods}),
"sound" (usually "none"), "commands" (robot actions, ONLY if the user asks you to move; otherwise []).
Actions you may use:
{actions}
You have no internet: if asked for live facts (weather, news), say you can't check right now.
{personality}"""


class OllamaBrain:
    name = "local"

    def __init__(self, ollama, settings, enabled=lambda: True):
        self.ollama = ollama
        self.settings = settings            # the assistant settings (personality, robot_name)
        self.enabled = enabled
        self.model = lambda: "llama3.2:3b"

    def available(self):
        return self.enabled() and self.ollama.has(self.model())

    def think(self, user_text, context, history, image_jpeg=None, tool_ctx=None):
        s = self.settings
        system = SYSTEM.format(name=s.get("robot_name", "Pip"), moods=", ".join(MOODS), actions=describe_actions(),
                               personality=s.get("personality", ""))
        msgs = [{"role": "system", "content": system}]
        for h in history[-4:]:
            msgs.append({"role": "user", "content": h["user"]})
            msgs.append({"role": "assistant", "content": json.dumps({"speech": h["speech"], "mood": h.get("mood", "neutral"),
                                                                     "sound": "none", "commands": h.get("commands", [])})})
        msgs.append({"role": "user", "content": f"Robot context:\n{context[:1500]}\n\nUser said: {user_text}"})
        raw = self.ollama.chat(self.model(), msgs, schema=REPLY_SCHEMA, max_tokens=250, timeout=45)   # slower = keyword rules
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"speech": raw.strip()[:300]}
        return {"speech": str(data.get("speech") or "Hmm, I'm not sure.")[:400], "mood": data.get("mood", "neutral"),
                "sound": data.get("sound", "none"), "commands": data.get("commands") or [], "tools": [],
                "usage": None}
