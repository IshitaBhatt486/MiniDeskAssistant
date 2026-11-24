"""
The brain: (what the user said + what the camera sees + robot state + personality) -> reply JSON.

    ClaudeBrain   Claude (default claude-haiku-5-5, effort "low" for voice-assistant latency) over plain HTTPS
                  (claude_http.py, 20 Nov 2026; was the `anthropic` SDK, same calls). Tool use (free web APIs in tools.py) in a manual loop of at
                  most MAX_TOOL_ROUNDS rounds; the final answer is forced into commands.RESPONSE_SCHEMA
                  with structured outputs (output_config.format), so it always parses.
                  Server-side refusal fallback ("fallbacks": "default") is used on models that support it;
                  Haiku doesn't, so a refusal there simply gets a polite spoken answer.
                  One camera frame (320x240 JPEG, ~10 kB, a few hundred tokens) is attached per conversation
                  turn, only if settings.send_image is on AND the request needs eyes (needs_image), unless
                  settings.vision_on_demand is off. The detections always go along as text.
                  Plain robot commands never reach it (local_command, settings.local_commands).
                  Prompt caching: the system prompt + tool list are stable and cached (top-level
                  cache_control); everything that changes per request is in the user message.
    OfflineBrain  keyword rules. Used when there's no ANTHROPIC_API_KEY, the SDK can't load, or the
                  API call fails, so voice commands like "turn left", "stop", "what's the weather"
                  keep working without the AI.

think() never raises: an API failure is reported to alerts (spoken) and the offline brain answers.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections import deque

from .commands import ACTIONS, MOODS, RESPONSE_SCHEMA, SOUNDS, describe_actions, describe_sounds, normalise
from .tools import TOOL_SPECS, run_tool

MAX_TOOL_ROUNDS = 4
HISTORY_TURNS = 6          # earlier exchanges sent as context (text only)

SYSTEM_TEMPLATE = """You are the voice and brain of a small two-wheeled robot that lives on a desk.
You hear the user through speech-to-text (expect transcription mistakes; guess the intended words).
You see through a small forward-facing camera mounted on the robot; detections are given as text and,
when available, the camera frame is attached (boxes drawn by an on-board detector).

Your reply is spoken by a tiny speaker in a high-pitched chipmunk voice, so:
- "speech": 1-3 short, natural sentences. No emoji, markdown, lists or URLs. Say numbers the way people say them.
- If you use a tool, give the answer in plain words (for example "It's 24 degrees and sunny in Delhi").

You can move. Put actions in "commands" (in order) ONLY when the user asks for movement or an action,
or when it clearly fits (for example a little "dance" when the user is excited). Otherwise use [].
Never invent actions; the full list:
{actions}
Safety rules on the robot stop it at desk edges and obstacles by themselves; you don't need to check.
To travel to or between things on the desk, use one "navigate" command: "go from the cup to the bottle" is
from_object "cup", to_object "bottle"; "go to the book" is from_object "", to_object "book". It plans its own
route, so never replace it with move and turn commands. For every other action leave both fields empty.
Directions are from the robot's point of view. The user is usually in front of the robot.
"mood" sets the face on the dashboard.
"sound" is a sound effect played just before your speech. Most replies use "none"; pick one only when it adds fun
or meaning (a rimshot after a pun, a whoosh with a spin, ta-da when something is finished). The full list:
{sounds}
{extra}
Personality (stay in character, but always be helpful and kind):
{personality}"""


def system_prompt(personality, extra=""):
    """extra: more instructions from add-ons (buddy/: tasks, notifications), stable so the prompt stays cached."""
    return SYSTEM_TEMPLATE.format(actions=describe_actions(), sounds=describe_sounds(),
                                  extra=(extra.strip() + "\n") if extra.strip() else "", personality=personality.strip())


class BrainResult(dict):
    """{"speech", "mood", "sound", "commands", "backend", "ms", "tools", "error", "usage"}"""


# ---------------- Claude ----------------

class ClaudeBrain:
    name = "claude"

    def __init__(self, settings):
        self.settings = settings
        self._client = None
        self.load_error = None
        self.extra_tools = {}          # name -> (spec, fn(args) -> (text, is_error)); see Brain.add_tool
        self.extra_prompt = ""
        from . import claude_http  # standard library only: always loads (no SDK, no compiled DLL)

        self._anthropic = claude_http

    def available(self):
        return self._anthropic is not None and bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def why_unavailable(self):
        if self._anthropic is None:
            return self.load_error or "Claude client missing"
        return "no ANTHROPIC_API_KEY in secrets.env"

    def client(self):
        if self._client is None:
            # 1 retry: a voice reply that takes 3 attempts is too late anyway; the offline brain answers instead
            self._client = self._anthropic.Anthropic(max_retries=1, timeout=40.0)
        return self._client

    def think(self, user_text, context, history, image_jpeg=None, tool_ctx=None):
        a = self._anthropic
        s = self.settings
        content = []
        if image_jpeg:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.standard_b64encode(image_jpeg).decode()}})
        content.append({"type": "text", "text": f"<robot_context>\n{context}\n</robot_context>\n\nUser said: {user_text}"})

        messages = []
        for h in history:
            messages.append({"role": "user", "content": h["user"]})
            messages.append({"role": "assistant", "content": json.dumps(
                {"speech": h["speech"], "mood": h.get("mood", "neutral"), "sound": h.get("sound", "none"),
                 "commands": h.get("commands", [])})})
        messages.append({"role": "user", "content": content})

        used_tools, usage = [], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "model": s.get("model", "claude-haiku-5-5")}
        for _ in range(MAX_TOOL_ROUNDS + 1):
            model = s.get("model", "claude-haiku-5-5")
            fallback = {} if "haiku" in model else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            resp = self.client().beta.messages.create(
                model=model,
                max_tokens=4000,
                **fallback,
                cache_control={"type": "ephemeral"},
                system=system_prompt(s.get("personality", ""), self.extra_prompt),
                tools=TOOL_SPECS + [spec for spec, _ in self.extra_tools.values()],
                output_config={"effort": s.get("effort", "low"),
                               "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
                messages=messages,
            )
            u = resp.usage
            usage["input"] += u.input_tokens or 0
            usage["output"] += u.output_tokens or 0
            usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0

            if resp.stop_reason == "refusal":
                return {"speech": "Sorry, I can't help with that one.", "mood": "confused", "sound": "none", "commands": [],
                        "tools": used_tools, "usage": usage}
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    if block.name in self.extra_tools:
                        text, is_err = self.extra_tools[block.name][1](block.input or {})
                    else:
                        text, is_err = run_tool(block.name, block.input or {}, tool_ctx or {})
                    used_tools.append({"name": block.name, "input": block.input, "error": is_err})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": text,
                                    **({"is_error": True} if is_err else {})})
                messages.append({"role": "user", "content": results})   # all results in ONE message
                continue
            if resp.stop_reason == "max_tokens":
                raise RuntimeError("reply was cut off (max_tokens)")
            text = next((b.text for b in resp.content if b.type == "text"), "")
            data = json.loads(text)
            return {"speech": data.get("speech", ""), "mood": data.get("mood", "neutral"), "sound": data.get("sound", "none"),
                    "commands": data.get("commands", []), "tools": used_tools, "usage": usage}
        raise RuntimeError("too many tool rounds")

    def classify_error(self, exc):
        """Short, speakable reason for an API failure."""
        a = self._anthropic
        if a is None:
            return "my AI library is missing"
        if isinstance(exc, a.AuthenticationError):
            return "my AI key was rejected"
        if isinstance(exc, a.PermissionDeniedError):
            return "my AI key isn't allowed to use that model"
        if isinstance(exc, a.NotFoundError):
            return "the AI model name is wrong"
        if isinstance(exc, a.RateLimitError):
            return "the AI is rate limiting me"
        if isinstance(exc, a.APIStatusError):
            return "the AI service had an error" if exc.status_code >= 500 else f"the AI rejected my request ({exc.status_code})"
        if isinstance(exc, a.APIConnectionError):
            return "I can't reach the internet"
        return "my AI brain had a problem"


# ---------------- offline ----------------

NUM_WORDS = {"once": 1, "twice": 2, "thrice": 3, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "half": 0.5, "a": 1, "an": 1,
             "ninety": 90, "forty five": 45, "forty-five": 45, "thirty": 30, "sixty": 60, "hundred eighty": 180}


NOT_PLACES = {"left", "right", "front", "back", "the left", "the right", "the front", "the back", "forward", "backward",
              "sleep", "bed", "me", "you", "us"}
LOCAL_START = re.compile(r"^(?:(?:hey|ok|okay)\s+)?(?:(?:please|can you|could you)\s+)*"
                         r"(?:stop|halt|freeze|turn|rotate|spin|dance|go|drive|move|head|travel|navigate|roll|return|come|"
                         r"reverse|back up|look around|follow me|face me|look at me|wake up|good night|good morning|"
                         r"find my phone|forget the map|reset the map|this is home|mark|set home|speed up|slow down)\b")
# OfflineBrain (no AI): movement words only count at the start of a command, never inside a question
OFFLINE_START = re.compile(LOCAL_START.pattern[:-3] + r"|do\s+(?:a\s+)?(?:little\s+)?(?:dance|spin)|keep looking at me|"
                           r"keep facing me|forward|backwards?|faster|slower|let'?s)\b")
OFFLINE_QUESTION = re.compile(r"\?|\b(?:what|why|how|who|when|where|which|whose|is it|are you|do you|does it)\b")
NEEDS_THOUGHT = re.compile(r"\?|\b(what|why|how|who|when|where|tell|joke|weather|and|but|because|if)\b")
NEEDS_EYES = re.compile(r"\b(look(s|ing)? like|see|seeing|show|colou?r|read|describe|holding|wearing|in front of you|"
                        r"what is this|what's this|what is that|what's that|how many|camera|picture|photo)\b")


def local_vision_answer(text, items):
    """Answer simple "what do you see" questions from the on-board detector. items: [{"label", "colour", "area"}]."""
    if not items:
        return None
    t = re.sub(r"[?.!,]+", " ", text.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    biggest = max(items, key=lambda i: i["area"])
    named = lambda i: f"{i['colour']} {i['label']}" if i.get("colour") else i["label"]   # noqa: E731
    answer = None
    m = re.search(r"\bwhat colou?r\b(?: is| are|'s)? ?(?:the |my |this |that )?(.*)$", t)
    if m:
        wanted = m.group(1).replace("it", "").strip()
        wanted = SIMPLE_NAMES.get(wanted, wanted)
        hit = biggest if not wanted else next((i for i in items if wanted in i["label"] or i["label"] in wanted), None)
        if hit is None or not hit.get("colour"):
            return None
        answer = f"The {hit['label']} looks {hit['colour']}."
    elif re.fullmatch(r"(?:what (?:do|can) you see|what's in front of you|what is in front of you)(?: right now| now)?", t):
        names = list(dict.fromkeys(named(i) for i in items))
        answer = "I can see " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]) + "."
    elif re.fullmatch(r"what(?: is|'s) (?:this|that)", t):
        answer = f"That looks like a {named(biggest)}."
    return None if answer is None else {"speech": answer, "mood": "curious", "sound": "none", "commands": [], "tools": []}


SIMPLE_NAMES = {"mug": "cup", "phone": "cell phone", "mobile": "cell phone", "notebook": "book", "water bottle": "bottle"}


def needs_image(text):
    """Does answering this need the actual picture? The detector's list always goes along as text."""
    return bool(NEEDS_EYES.search(text.lower()))


def local_command(text):
    """A reply for a plain robot command, or None if it needs the AI. Deliberately strict: anything that
    might be a question or a longer thought goes to the AI, so its answers don't get worse."""
    t = re.sub(r"[.,!]+", " ", text.lower()).strip()
    if len(t.split()) > 10 or NEEDS_THOUGHT.search(t) or not LOCAL_START.match(t):
        return None
    out = OfflineBrain().think(t, "", [])
    return out if out.get("commands") else None
TRAVEL = r"\b(?:go|drive|head|move|travel|navigate|roll|get)\b(?: over| across)?"


def _place(text):
    text = re.sub(r"[.?!,]+", " ", text)
    return re.sub(r"\s+(?:please|now|then)\s*$", "", " ".join(text.split()) + " ").strip()


def parse_navigation(text):
    """(from, to) for "go from the cup to the bottle" / "go to the cup", else None."""
    if re.search(r"\b(?:go|drive|head|return|get)\b(?: back)? home\b", text):
        return "", "home"
    m = re.search(TRAVEL + r" from (.+?) to (.+)$", text) or re.search(r"^\s*from (.+?) to (.+)$", text)
    if m:
        return _place(m.group(1)), _place(m.group(2))
    m = re.search(TRAVEL + r" (?:to|towards?) (.+)$", text)
    if m and _place(m.group(1)) not in NOT_PLACES:
        return "", _place(m.group(1))
    return None


def _number(text, default):
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    for w, v in NUM_WORDS.items():
        if re.search(rf"\b{w}\b", text):
            return v
    return default


class OfflineBrain:
    """Small keyword matcher so basic voice control works with no AI at all."""
    name = "offline"

    def think(self, user_text, context, history, image_jpeg=None, tool_ctx=None):
        t = " " + user_text.lower().strip() + " "
        name = (tool_ctx or {}).get("robot_name", "Pip")
        cmd = lambda a, amt=0: {"action": a, "amount": amt}   # noqa: E731
        reply = lambda speech, mood="happy", commands=(), sound="none": {  # noqa: E731
            "speech": speech, "mood": mood, "sound": sound, "commands": list(commands), "tools": []}

        if re.search(r"\b(stop|halt|freeze|wait)\b", t):
            return reply("Stopping.", "neutral", [cmd("stop")])
        if re.search(r"find (my )?phone|where('s| is) my phone", t):
            return reply("Looking for your phone.", "curious", [cmd("find_phone")])
        if re.search(r"\b(go to sleep|good ?night|sleep)\b", t):
            return reply("Good night.", "sleepy", [cmd("sleep")], "yawn")
        if re.search(r"\b(wake up|good morning)\b", t):
            return reply("I'm awake!", "excited", [cmd("wake")], "ding")
        if re.search(r"\b(reset|forget|new) (the )?map\b", t):
            return reply("Starting a fresh map.", "neutral", [cmd("reset_map")])
        if re.search(r"\b(this is|here is|mark|set|save)\b.{0,16}\bhome\b", t):
            return reply("This is home.", "happy", [cmd("set_home")])
        # 24 Nov 2026: movement only for sentences that START with a command and are not questions. These rules
        # matched words anywhere, so with no AI key "that's right" turned right, "I'll be back" reversed and
        # "what's ahead?" drove forward (the same bug was found and fixed in legacy/simplified_code.py).
        bare = re.sub(rf"^(?:(?:hey|hi|ok|okay)\s+)?(?:{re.escape(name.lower())}\b)?[\s,]*", "", t.strip())
        bare = re.sub(r"^(?:(?:please|can|could|would|will)\s+(?:you\s+|we\s+)?)+", "", bare)   # polite openers
        if OFFLINE_START.match(bare) and not OFFLINE_QUESTION.search(t):
            route = parse_navigation(t.strip())
            if route:
                start, goal = route
                say = f"Going from {start} to {goal}." if start else f"Going to {goal}."
                return reply(say, "curious", [{"action": "navigate", "amount": 0, "from_object": start, "to_object": goal}])
            if "spin" in t:
                return reply("Wheee!", "excited", [cmd("spin", _number(t, 1))], "whoosh")
            if "dance" in t:
                return reply("Dance time!", "excited", [cmd("dance")])
            if "look around" in t:
                return reply("Having a look around.", "curious", [cmd("look_around")])
            if re.search(r"\b(follow me|keep looking at me)\b", t):
                return reply("I'll keep my eyes on you.", "happy", [cmd("follow_user_on")])
            if re.search(r"\b(look at me|face me|turn to me)\b", t):
                return reply("Hi there!", "happy", [cmd("face_user")])
            if re.search(r"\b(turn|rotate)\b.*\bleft\b|\bleft\b", t):
                return reply("Turning left.", "neutral", [cmd("turn_left", _number(t, 90))])
            if re.search(r"\b(turn|rotate)\b.*\bright\b|\bright\b", t):
                return reply("Turning right.", "neutral", [cmd("turn_right", _number(t, 90))])
            if re.search(r"\b(back|backward|backwards|reverse)\b", t):
                return reply("Backing up.", "neutral", [cmd("move_backward", _number(t, 1))])
            if re.search(r"\b(forward|ahead|come here|come closer)\b", t):
                return reply("Coming!", "happy", [cmd("move_forward", _number(t, 1))])
            if re.search(r"\b(faster|speed up)\b", t):
                return reply("Speeding up.", "excited", [cmd("set_speed", 80)])
            if re.search(r"\b(slower|slow down)\b", t):
                return reply("Slowing down.", "neutral", [cmd("set_speed", 35)])

        if "weather" in t or "temperature" in t:
            m = re.search(r"\bin ([a-z .'-]+?)(?:\?| today| tomorrow| now|$| \b)", t.strip())
            text, err = run_tool("get_weather", {"location": m.group(1).strip() if m else ""}, tool_ctx or {})
            if err:
                return reply(f"I couldn't get the weather. {text.removeprefix('Error: ')}.", "sad")
            w = json.loads(text)
            n = w["now"]
            return reply(f"In {w['place'].split(',')[0]} it's {round(n['temperature_c'])} degrees with {n['conditions']}.", "happy")
        if re.search(r"\bwhat time\b|\bthe time\b|\bwhat day\b|\bdate\b", t):
            tm = json.loads(run_tool("get_time", {}, {})[0])
            return reply(f"It's {tm['local_time']} on {tm['date']}.", "neutral")
        if "joke" in t:
            text, err = run_tool("tell_joke", {}, {})
            if err:
                return reply("I tried to think of a joke, but my internet is down. That's the joke.", "sad")
            j = json.loads(text)
            return reply(f"{j['setup']} {j['punchline']}", "excited", sound="giggle")
        if re.search(r"what (do|can) you see|what's in front", t):
            seen = (tool_ctx or {}).get("seen_labels") or []
            return reply(f"I can see {', '.join(seen)}." if seen else "I don't see anything I recognise.", "curious")
        m = re.search(r"(?:who|what) (?:is|was|are) (.+?)\??\s*$", t.strip())
        if m:
            text, err = run_tool("wikipedia_summary", {"topic": m.group(1)}, {})
            if not err:
                summary = json.loads(text)["summary"]
                return reply(" ".join(re.split(r"(?<=[.!?]) ", summary)[:2]), "curious")
        if re.search(r"\b(hi|hello|hey)\b", t):
            return reply(f"Hello! I'm {name}.", "happy", sound="beep_boop")
        return reply("I'm in simple mode without my AI brain, so I only understand short commands like "
                     "turn left, come here, stop, spin, or what's the weather.", "confused")


# ---------------- facade ----------------

class Brain:
    def __init__(self, settings, alerts):
        self.settings = settings
        self.alerts = alerts
        self.claude = ClaudeBrain(settings)
        self.offline = OfflineBrain()
        self.history = deque(maxlen=HISTORY_TURNS)
        self.last = None
        self.local_handlers = []     # fn(text, tool_ctx) -> reply dict or None: tried before the offline rules
        self.pre_handlers = []       # fn(text, tool_ctx) -> reply or None, tried FIRST (full/: routines, smart home, games)
        self.fallback_brains = []    # objects with .name, .available(), .think(...): tried after the local skills
        self.primary_brains = []     # (20 Nov 2026, pro/: Groq) same interface, tried BEFORE Claude; Claude becomes
                                     # their fallback. A brain without .sees = True is skipped for a turn that carries
                                     # a camera image while Claude is available (Claude can look at it)
        self.not_local = []          # compiled regexes: sentences that must NOT be taken as a plain robot command
                                     # ("stop the music" is not "stop"; hub/core.py adds music / focus words)
        if not self.claude.available():
            alerts.warn("ai", "No AI brain connected, so I'm in simple mode. Add an Anthropic API key to fix that.",
                        detail=self.claude.why_unavailable())

    def _try(self, handler, user_text, tool_ctx):
        try:
            out = handler(user_text, tool_ctx or {})
        except Exception as exc:
            self.alerts.warn("ai", "A local skill failed.", speak=False, detail=f"{type(exc).__name__}: {exc}"[:300])
            return None
        if out is not None:
            out.setdefault("tools", [])
        return out

    def add_tool(self, spec, fn):
        """An extra Claude tool from an add-on (buddy/tasks.py). fn(args) -> (result text, is_error)."""
        self.claude.extra_tools[spec["name"]] = (dict(spec, strict=True), fn)

    def add_prompt(self, text):
        self.claude.extra_prompt = (self.claude.extra_prompt + "\n" + text.strip()).strip()

    def backend(self):
        for pb in self.primary_brains:
            if pb.available():
                return pb.name
        return "claude" if self.claude.available() else "offline"

    def order(self):
        """Names of the cloud/local brains in the order they're tried right now (dashboard: APIs in use)."""
        names = [pb.name for pb in self.primary_brains if pb.available()]
        names += ["claude"] if self.claude.available() else []
        # OllamaBrain.available() probes the network (too slow for a status poll): use its switch and the result of
        # the last probe instead (None = never probed yet)
        for fb in self.fallback_brains:
            if hasattr(fb, "enabled"):
                cached = getattr(getattr(fb, "ollama", None), "_models", None)
                ok = fb.enabled() and (cached is None or bool(cached))
            else:
                ok = fb.available()
            if ok:
                names.append(fb.name)
        return names + ["offline"]

    def status(self):
        backend = self.backend()
        primary = next((pb for pb in self.primary_brains if pb.name == backend), None)
        model = primary.model() if primary is not None and callable(getattr(primary, "model", None)) else \
            self.settings.get("model") if backend == "claude" else None
        return {"backend": backend, "model": model, "order": self.order(),
                "effort": self.settings.get("effort"),
                "why_offline": None if backend != "offline" else self.claude.why_unavailable(),
                "last": self.last}

    def think(self, user_text, context, image_jpeg=None, tool_ctx=None):
        t0 = time.perf_counter()
        out, error = None, None
        for handler in self.pre_handlers:          # routines, smart-home devices, games: before anything else
            out = self._try(handler, user_text, tool_ctx)
            if out is not None:
                out.setdefault("backend", "local")
                break
        if out is None and self.settings.get("local_commands", True) and not any(rx.search(user_text.lower()) for rx in self.not_local):
            out = local_vision_answer(user_text, (tool_ctx or {}).get("seen_items")) or local_command(user_text)
            if out is not None:
                out["backend"] = "local"
        if out is None:
            for pb in self.primary_brains:
                if not pb.available() or (image_jpeg is not None and not getattr(pb, "sees", False) and self.claude.available()):
                    continue
                try:
                    out = pb.think(user_text, context, list(self.history), image_jpeg if getattr(pb, "sees", False) else None, tool_ctx)
                    out["backend"] = pb.name
                    self.alerts.resolve(f"ai-{pb.name}", f"{pb.name.title()} is answering again.", speak=False)
                    break
                except Exception as exc:
                    reason = pb.classify_error(exc) if hasattr(pb, "classify_error") else "it failed"
                    nxt = "Claude" if self.claude.available() else "simple mode"
                    self.alerts.warn(f"ai-{pb.name}", f"{pb.name.title()} isn't answering ({reason}), using {nxt}.", speak=False,
                                     detail=f"{type(exc).__name__}: {exc}"[:300])
                    error = reason
                    out = None
        if out is None and self.claude.available():
            try:
                out = self.claude.think(user_text, context, list(self.history), image_jpeg, tool_ctx)
                out["backend"] = "claude"
                error = None                      # a primary brain may have failed first; Claude covered for it
                self.alerts.resolve("ai", "My AI brain is back.")
            except Exception as exc:
                error = self.claude.classify_error(exc)
                self.alerts.warn("ai", f"Switching to simple mode: {error}.", detail=f"{type(exc).__name__}: {exc}"[:300])
        if out is None:
            for handler in self.local_handlers:
                out = self._try(handler, user_text, tool_ctx)
                if out is not None:
                    break
        if out is None:
            for fb in self.fallback_brains:        # e.g. a local LLM (full/local_llm.py) before the keyword rules
                if not fb.available():
                    continue
                try:
                    out = fb.think(user_text, context, list(self.history), image_jpeg, tool_ctx)
                    out["backend"] = fb.name
                    break
                except Exception as exc:
                    self.alerts.warn("ai", f"The {fb.name} brain failed.", speak=False, detail=f"{type(exc).__name__}: {exc}"[:300])
                    out = None
        if out is None:
            out = self.offline.think(user_text, context, list(self.history), None, tool_ctx)
        if "backend" not in out:
            out["backend"] = "offline"
        if out.get("mood") not in MOODS:
            out["mood"] = "neutral"
        if out.get("sound") not in SOUNDS:
            out["sound"] = "none"
        out["commands"], problems = normalise(out.get("commands", []))
        out["problems"] = problems
        out["error"] = error
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        self.history.append({"user": user_text, "speech": out["speech"], "mood": out["mood"], "sound": out["sound"],
                             "commands": out["commands"]})
        self.last = {k: out.get(k) for k in ("backend", "ms", "error", "usage")}
        return out


__all__ = ["Brain", "ClaudeBrain", "OfflineBrain", "system_prompt", "ACTIONS"]
