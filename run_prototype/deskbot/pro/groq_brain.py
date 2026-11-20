"""
Groq as the robot's primary AI brain (20 Nov 2026); Claude is its fallback (Brain.primary_brains).

Groq's API is OpenAI-compatible: POST https://api.groq.com/openai/v1/chat/completions with "Authorization: Bearer
$GROQ_API_KEY" (the same key that already powers Whisper speech-to-text). Standard library only (urllib).

Model: data/pro.json groq.model, default "openai/gpt-oss-120b": a Groq *production* model with tool use and JSON
mode ($0.15 / $0.60 per million input / output tokens; free-tier keys without a card can't be charged).
"openai/gpt-oss-20b" is faster and cheaper; "llama-3.3-70b-versatile" also works. The gpt-oss models are reasoning
models, so "reasoning_effort": "low" keeps voice replies quick.

A turn:
  1. system prompt = the same one Claude gets (brain.system_prompt: actions, sounds, personality, add-on
     instructions) + "answer with ONE JSON object" + the reply schema
  2. up to MAX_TOOL_ROUNDS rounds with the same tools as Claude (weather, time, Wikipedia, jokes, currency,
     robot status, plus add-on tools such as tasks), converted to OpenAI function format; every tool call is
     answered with a "tool" message
  3. the final message is parsed as JSON (a ```json fence or text around the object is tolerated). If it isn't
     valid, ONE repair call with response_format json_object turns it into the schema
No camera image: none of Groq's production models takes images, so Brain skips Groq for a turn that carries a
frame while Claude is available (the on-board detections always go along as text).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from ..assistant.brain import HISTORY_TURNS, MAX_TOOL_ROUNDS, system_prompt
from ..assistant.commands import RESPONSE_SCHEMA
from ..assistant.tools import TOOL_SPECS, run_tool

URL = "https://api.groq.com/openai/v1"
JSON_RULES = """
Answer with exactly ONE JSON object and nothing else (no markdown fence, no text before or after), matching this
JSON schema:
{schema}"""


class GroqError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def to_openai_tools(specs):
    return [{"type": "function", "function": {"name": s["name"], "description": s.get("description", ""),
                                              "parameters": s.get("input_schema") or {"type": "object", "properties": {}}}}
            for s in specs]


def extract_json(text):
    """The JSON object in a model's reply, tolerating a ``` fence or chatter around it. None if there is none."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class GroqClient:
    def __init__(self, key_env="GROQ_API_KEY", timeout=25.0):
        self.key_env, self.timeout = key_env, timeout
        self.models_cache, self.models_t, self.last_error, self.last_ok = None, 0.0, None, None

    def key(self):
        return os.environ.get(self.key_env, "")

    def _req(self, method, path, body=None, timeout=None):
        req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.key()}", "Content-Type": "application/json",
                                              "User-Agent": "deskbot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                out = json.loads(r.read())
            self.last_ok, self.last_error = time.time(), None
            return out
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            try:
                detail = json.loads(detail)["error"]["message"][:300]
            except (ValueError, KeyError, TypeError):
                pass
            self.last_error = f"HTTP {exc.code}: {detail}"
            raise GroqError(self.last_error, exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = f"can't reach Groq ({getattr(exc, 'reason', exc)})"
            raise GroqError(self.last_error) from exc

    def chat(self, body, timeout=None):
        return self._req("POST", "/chat/completions", body, timeout)

    def models(self, max_age=600.0):
        """Model ids this key can use (cached 10 min); [] on failure."""
        if self.models_cache is not None and time.time() - self.models_t < max_age:
            return self.models_cache
        try:
            data = self._req("GET", "/models", timeout=8)
            self.models_cache = sorted(m["id"] for m in data.get("data", []) if m.get("active", True))
        except GroqError:
            self.models_cache = self.models_cache or []
        self.models_t = time.time()
        return self.models_cache


class GroqBrain:
    name = "groq"
    sees = False           # no image input on Groq's production models

    def __init__(self, settings, section, claude=None, client=None, enabled=lambda: True):
        """settings: the assistant Settings (personality); section(): data/pro.json "groq"; claude: the ClaudeBrain,
        whose add-on tools and prompt (tasks, notifications, ...) are reused; enabled(): feature switches."""
        self.settings, self.section, self.claude, self.enabled = settings, section, claude, enabled
        self.client = client or GroqClient()
        self.last = None

    def model(self):
        return self.section().get("model") or "openai/gpt-oss-120b"

    def available(self):
        return bool(self.client.key()) and bool(self.section().get("enabled", True)) and self.enabled()

    def why_unavailable(self):
        if not self.client.key():
            return "no GROQ_API_KEY in secrets.env"
        if not self.section().get("enabled", True):
            return "switched off (Groq card)"
        return "the AI brain is switched off or local-only mode is on"

    def _tools(self):
        extra = list(self.claude.extra_tools.values()) if self.claude is not None else []
        specs = TOOL_SPECS + [spec for spec, _ in extra]
        return to_openai_tools([{k: v for k, v in s.items() if k != "strict"} for s in specs])

    def _run_tool(self, name, args, tool_ctx):
        if self.claude is not None and name in self.claude.extra_tools:
            return self.claude.extra_tools[name][1](args)
        return run_tool(name, args, tool_ctx)

    def _body(self, messages, **extra):
        body = {"model": self.model(), "messages": messages, "temperature": 0.6, "max_completion_tokens": 1200, **extra}
        if self.model().startswith("openai/gpt-oss"):
            body["reasoning_effort"] = self.section().get("reasoning_effort", "low")
        return body

    def think(self, user_text, context, history, image_jpeg=None, tool_ctx=None):
        s = self.settings
        extra = self.claude.extra_prompt if self.claude is not None else ""
        system = system_prompt(s.get("personality", ""), extra) + JSON_RULES.format(schema=json.dumps(RESPONSE_SCHEMA))
        messages = [{"role": "system", "content": system}]
        for h in history[-HISTORY_TURNS:]:
            messages.append({"role": "user", "content": h["user"]})
            messages.append({"role": "assistant", "content": json.dumps(
                {"speech": h["speech"], "mood": h.get("mood", "neutral"), "sound": h.get("sound", "none"),
                 "commands": h.get("commands", [])})})
        messages.append({"role": "user", "content": f"<robot_context>\n{context}\n</robot_context>\n\nUser said: {user_text}"})
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "model": self.model()}
        used_tools = []
        tools = self._tools()
        t0 = time.perf_counter()
        for _ in range(MAX_TOOL_ROUNDS + 1):
            resp = self.client.chat(self._body(messages, tools=tools, tool_choice="auto"))
            u = resp.get("usage") or {}
            usage["input"] += u.get("prompt_tokens", 0) or 0
            usage["output"] += u.get("completion_tokens", 0) or 0
            msg = resp["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if calls:
                messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    text, is_err = self._run_tool(fn.get("name", ""), args if isinstance(args, dict) else {}, tool_ctx or {})
                    used_tools.append({"name": fn.get("name"), "input": args, "error": is_err})
                    messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": text})
                continue
            data = extract_json(msg.get("content"))
            if data is None:          # one repair round in JSON mode
                messages.append({"role": "assistant", "content": msg.get("content") or ""})
                messages.append({"role": "user", "content": "Rewrite your last answer as the single JSON object described "
                                                            "in the system prompt, and nothing else."})
                resp = self.client.chat(self._body(messages, response_format={"type": "json_object"}))
                u = resp.get("usage") or {}
                usage["input"] += u.get("prompt_tokens", 0) or 0
                usage["output"] += u.get("completion_tokens", 0) or 0
                data = extract_json(resp["choices"][0]["message"].get("content")) or {
                    "speech": (msg.get("content") or "Hmm, I'm not sure.").strip()[:300]}
            self.last = {"model": self.model(), "ms": round((time.perf_counter() - t0) * 1000), "tools": len(used_tools)}
            return {"speech": str(data.get("speech") or "Hmm, I'm not sure.")[:400], "mood": data.get("mood", "neutral"),
                    "sound": data.get("sound", "none"), "commands": data.get("commands") or [], "tools": used_tools,
                    "usage": usage}
        raise GroqError("too many tool rounds")

    def classify_error(self, exc):
        status = getattr(exc, "status", None)
        if status == 401:
            return "its key was rejected"
        if status == 404:
            return "the model name is wrong"
        if status == 429:
            return "it is rate limiting me"
        if status and status >= 500:
            return "the service had an error"
        if status:
            return f"it rejected my request ({status})"
        return "I can't reach it"

    def status(self):
        return {"available": self.available(), "why": None if self.available() else self.why_unavailable(),
                "model": self.model(), "last": self.last, "last_error": self.client.last_error,
                "last_ok": self.client.last_ok}
