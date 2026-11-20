"""
"Remember this idea": a notebook of ideas you say out loud.

    "remember this idea: a robot that waters plants"   -> saved straight away
    "remember this idea"  ...  "a robot that waters plants"   -> the robot asks "What's the idea?" and saves the
                                                               next thing you say (within 60 s)
    "what were my ideas?" / "read my last idea" / "forget the plant idea"

Storage: data/ideas.json (ideas_sim.json in simulation), atomic writes, at most 500 ideas. Each idea:
{"id", "text", "created", "source"}. With the AI, Claude gets save_idea / list_ideas / delete_idea tools; without
it, local_intent() understands the sentences above. The dashboard lists, searches, deletes and exports them
(Markdown download).
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

MAX_IDEAS = 500
MAX_TEXT = 600
CAPTURE_S = 60.0

_SAVE = re.compile(r"^(?:hey |ok |okay )?(?:please |can you |could you )*(?:remember|save|note(?: down)?|write down|jot down|keep)"
                   r"(?: (?:this|that|an?|my|the))? (?:new )?idea(?:s)?(?:\s*(?:that|:|,|-|is|for))?\s*(.*)$")
_SAVE2 = re.compile(r"^(?:idea|new idea)\s*[:,-]\s*(.+)$")
_LIST = re.compile(r"\b(?:what (?:were|are) my ideas|list my ideas|read (?:me )?my ideas|my ideas|any ideas saved)\b")
_LAST = re.compile(r"\b(?:what was|read|tell me) my (?:last|latest|newest) idea\b")
_DEL = re.compile(r"^(?:please )?(?:forget|delete|remove) (?:the |my )?(.+?) idea$|^(?:forget|delete|remove) (?:the |my )?idea (?:about )?(.+)$")


class IdeaStore:
    def __init__(self, path: Path, clock=datetime.now):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self.ideas = []
        self.next_id = 1
        self.capturing_until = 0.0       # "remember this idea" with nothing after it: save the next sentence
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.ideas = [i for i in data.get("ideas", []) if isinstance(i, dict) and "text" in i]
                self.next_id = max([int(data.get("next_id", 1))] + [i["id"] + 1 for i in self.ideas])
            except (OSError, ValueError, TypeError, KeyError):
                self.path.replace(self.path.with_suffix(".corrupt.json"))

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"next_id": self.next_id, "ideas": self.ideas}, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def add(self, text, source="voice"):
        text = " ".join(str(text).split()).strip(" .,:;-")[:MAX_TEXT]
        if len(text) < 2:
            raise ValueError("What's the idea?")
        with self._lock:
            idea = {"id": self.next_id, "text": text[0].upper() + text[1:], "created": self.clock().isoformat(timespec="seconds"),
                    "source": source}
            self.next_id += 1
            self.ideas.append(idea)
            del self.ideas[:-MAX_IDEAS]
            self._save()
        self.capturing_until = 0.0
        return dict(idea)

    def remove(self, ref):
        with self._lock:
            idea = self.find(ref)
            self.ideas.remove(idea)
            self._save()
            return dict(idea)

    def find(self, ref):
        ref = str(ref).strip()
        if re.fullmatch(r"#?\d+", ref):
            hit = next((i for i in self.ideas if i["id"] == int(ref.lstrip("#"))), None)
            if hit:
                return hit
            raise LookupError(f"there's no idea number {ref}")
        words = set(re.findall(r"\w+", ref.lower())) - {"the", "a", "an", "my", "idea", "about"}

        def hits(text):      # "plant" matches "plants", "water" matches "watering"
            tw = set(re.findall(r"\w+", text.lower()))
            return sum(1 for w in words if any(t == w or (min(len(t), len(w)) >= 4 and (t.startswith(w) or w.startswith(t))) for t in tw))
        scored = sorted(((hits(i["text"]), i) for i in self.ideas), key=lambda x: -x[0])
        if not scored or scored[0][0] == 0:
            raise LookupError(f"I couldn't find an idea about {ref!r}")
        if len(scored) > 1 and scored[1][0] == scored[0][0]:
            raise LookupError("that matches more than one idea: " + " / ".join(i["text"][:40] for _, i in scored[:2]))
        return scored[0][1]

    def search(self, query="", limit=20):
        with self._lock:
            ideas = list(reversed(self.ideas))
        q = query.lower().strip()
        return [dict(i) for i in ideas if not q or q in i["text"].lower()][:limit]

    def context_lines(self):
        if not self.ideas:
            return []
        last = self.ideas[-1]
        return [f"Ideas notebook: {len(self.ideas)} saved; newest: \"{last['text'][:120]}\"."]

    def markdown(self):
        lines = ["# Ideas", ""]
        for i in reversed(self.ideas):
            lines.append(f"- **{i['created'][:16].replace('T', ' ')}** {i['text']}")
        return "\n".join(lines) + "\n"

    def status(self):
        return {"count": len(self.ideas), "ideas": self.search(limit=50), "capturing": time.monotonic() < self.capturing_until}


PROMPT = """Ideas notebook: when the user says "remember this idea", "note this idea", "save an idea" or similar, call
save_idea with the idea in their words (tidied, nothing invented). If they say it with no idea attached, ask
"What's the idea?" and save their next answer. Answer "what were my ideas" with list_ideas."""

TOOL_SPECS = [
    {"name": "save_idea", "description": "Save an idea the user wants to remember.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string", "description": "The idea, in the user's words."}},
                      "required": ["text"], "additionalProperties": False}},
    {"name": "list_ideas", "description": "The user's saved ideas, newest first, optionally filtered by words.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Words to search for, or \"\"."}},
                      "required": ["query"], "additionalProperties": False}},
    {"name": "delete_idea", "description": "Delete one saved idea.",
     "input_schema": {"type": "object", "properties": {"idea": {"type": "string", "description": "Number (#3) or a few words of it."}},
                      "required": ["idea"], "additionalProperties": False}},
]


def tool_handlers(store):
    def run(fn):
        def go(args):
            try:
                return json.dumps(fn(args)), False
            except (LookupError, ValueError) as exc:
                return f"Error: {exc}", True
        return go
    return {"save_idea": run(lambda a: {"saved": store.add(a.get("text", ""), source="ai"), "total": len(store.ideas)}),
            "list_ideas": run(lambda a: {"ideas": store.search(a.get("query", ""), 15), "total": len(store.ideas)}),
            "delete_idea": run(lambda a: {"deleted": store.remove(a.get("idea", ""))})}


def local_intent(text, store):
    t = re.sub(r"[.!?]+$", "", " ".join(text.lower().split()))
    reply = lambda speech, mood="happy", sound="none": {  # noqa: E731
        "speech": speech, "mood": mood, "sound": sound, "commands": [], "tools": [], "backend": "local"}
    if time.monotonic() < store.capturing_until and t:
        store.add(text, source="voice")
        return reply("Saved your idea.", "excited", "ding")
    m = _SAVE.match(t) or _SAVE2.match(t)
    if m:
        body = (m.group(1) or "").strip()
        if len(body) < 3:
            store.capturing_until = time.monotonic() + CAPTURE_S
            return reply("Ooh, an idea! What is it?", "curious")
        original = re.search(r"(?i)idea\s*(?:that|:|,|-|is|for)?\s*(.+)$", text)
        store.add(original.group(1) if original else body, source="voice")
        return reply(f"Saved! That's idea number {len(store.ideas)}.", "excited", "ding")
    if _LAST.search(t):
        if not store.ideas:
            return reply("You haven't saved any ideas yet.", "neutral")
        return reply(f"Your latest idea: {store.ideas[-1]['text']}", "curious")
    if _LIST.search(t):
        ideas = store.search(limit=3)
        if not ideas:
            return reply("You haven't saved any ideas yet. Say 'remember this idea' any time.", "neutral")
        more = f" You have {len(store.ideas)} in total; the rest are on the dashboard." if len(store.ideas) > 3 else ""
        return reply("Your newest ideas: " + "; ".join(i["text"] for i in ideas) + "." + more, "curious")
    m = _DEL.match(t)
    if m and store.ideas:
        try:
            idea = store.remove(m.group(1) or m.group(2))
        except LookupError as exc:
            return reply(f"Hmm, {exc}.", "confused")
        return reply(f"Okay, I forgot the idea: {idea['text'][:80]}.", "neutral")
    return None
