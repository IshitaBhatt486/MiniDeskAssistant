"""
What the robot spends: Claude tokens per day, an estimate in dollars and rupees, and a daily cap.

Claude is the ONLY paid API the robot calls. Everything else is free (see SERVICES), and the one paid
fallback that existed (OpenAI speech-to-text) is blocked unless "allow_paid_apis" is switched on.

Prices (USD per million tokens, Anthropic API list prices, Nov 2026). Cache reads and writes are estimated as
0.1x and 1.25x the input price (Anthropic's usual multipliers for the 5-minute cache):

    model               input    output
    claude-haiku-5-5     0.10     0.50     (prompts up to 100K tokens; the robot's are ~4K)
    claude-sonnet-5-5    2.00    10.00
    claude-opus-5-5      4.00    20.00
    anything else        4.00    20.00     (unknown: assume the expensive end)

These are an ESTIMATE from the token counts each response reports. The real bill is in the Anthropic Console
(console.anthropic.com -> Billing / Usage), and a spend limit set there is the hard guarantee.

Storage: data/usage.json, one row per day: {"2026-11-19": {"input", "output", "cache_read", "cache_write",
"usd", "calls"}}; 60 days kept.

Daily cap (settings "daily_cap_usd", default 0.50): once today's estimate reaches it, the Claude brain reports
itself unavailable until midnight, so the robot answers with the offline brain (and says so once).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path

PRICES = {   # USD per 1M tokens: (input, output)
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    # Groq chat models (20 Nov 2026, pro/ brain; console.groq.com/docs/models). A free-tier key with no card can't be
    # charged, so these are what it WOULD cost on a paid plan.
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
}
FALLBACK_PRICE = (4.00, 20.00)
CACHE_READ_X, CACHE_WRITE_X = 0.1, 1.25
USD_TO_INR = 88.0          # fallback; the dashboard shows the rate used
KEEP_DAYS = 60

# Every outside service the robot can call, and whether it can cost money.
SERVICES = [
    {"name": "Anthropic Claude API", "used_for": "AI brain, notification triage", "cost": "paid per token",
     "note": "billed to your Anthropic Console account (prepaid credits); NOT part of a Claude.ai Pro/Max plan"},
    {"name": "Groq Whisper", "used_for": "speech-to-text, only if stt is groq/auto", "cost": "free tier",
     "note": "no card on file = cannot be charged; default stt is local"},
    {"name": "Groq chat (gpt-oss)", "used_for": "AI brain, first choice in main.py pro", "cost": "free tier",
     "note": "same GROQ_API_KEY; no card on file = cannot be charged"},
    {"name": "OpenAI Whisper", "used_for": "speech-to-text fallback", "cost": "PAID - blocked",
     "note": "never called unless allow_paid_apis is on"},
    {"name": "Open-Meteo", "used_for": "weather", "cost": "free", "note": "no key"},
    {"name": "Wikipedia", "used_for": "facts", "cost": "free", "note": "no key"},
    {"name": "Official Joke API", "used_for": "jokes", "cost": "free", "note": "no key"},
    {"name": "open.er-api.com", "used_for": "currency, rupee rate", "cost": "free", "note": "no key"},
    {"name": "Google Calendar API", "used_for": "reminders on your calendar", "cost": "free",
     "note": "a Google Cloud project with NO billing account cannot be charged"},
    {"name": "Spotify Web API", "used_for": "music", "cost": "free",
     "note": "playback control needs a Spotify Premium subscription (not an API fee)"},
    {"name": "GitHub (opencv_zoo)", "used_for": "one-time face model download for focus mode", "cost": "free",
     "note": "230 kB, once"},
]


def price(model):
    return PRICES.get(model, FALLBACK_PRICE)


def cost_usd(usage, model=None):
    model = model or usage.get("model") or ""
    pin, pout = price(model)
    return (usage.get("input", 0) * pin + usage.get("output", 0) * pout
            + usage.get("cache_read", 0) * pin * CACHE_READ_X + usage.get("cache_write", 0) * pin * CACHE_WRITE_X) / 1e6


class CostMeter:
    def __init__(self, path: Path, cap_usd=lambda: 0.50, today=date.today, alert=None):
        self.path = Path(path)
        self.cap_usd = cap_usd
        self.today = today
        self.alert = alert                 # fn(message) once when the cap is reached
        self._lock = threading.Lock()
        self.days = {}
        self.inr = USD_TO_INR
        self._capped_day = None
        if self.path.exists():
            try:
                self.days = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.days = {}

    def add(self, usage, model=None):
        if not usage:
            return 0.0
        usd = cost_usd(usage, model)
        day = self.today().isoformat()
        with self._lock:
            row = self.days.setdefault(day, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0, "calls": 0})
            for k in ("input", "output", "cache_read", "cache_write"):
                row[k] += int(usage.get(k, 0) or 0)
            row["usd"] = round(row["usd"] + usd, 6)
            row["calls"] += 1
            for old in sorted(self.days)[:-KEEP_DAYS]:
                del self.days[old]
            self._save()
        if self.over_cap() and self._capped_day != day:
            self._capped_day = day
            if self.alert:
                self.alert(f"I've used today's AI budget of {self.cap_usd():.2f} dollars, so I'm in simple mode until midnight.")
        return usd

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.days, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def today_usd(self):
        return self.days.get(self.today().isoformat(), {}).get("usd", 0.0)

    def over_cap(self):
        cap = self.cap_usd()
        return cap > 0 and self.today_usd() >= cap

    def guard(self, claude):
        """Make claude.available() false while over the cap (the brain then answers offline)."""
        original = claude.available

        def available():
            return original() and not self.over_cap()
        claude.available = available
        return self

    def refresh_rate(self, fetch=None):
        """Today's USD->INR rate from the free exchange-rate API (assistant/tools.py); keeps the fallback on failure."""
        try:
            if fetch is None:
                from ..assistant.tools import convert_currency
                fetch = lambda: convert_currency(1, "USD", "INR")["rate"]   # noqa: E731
            rate = float(fetch())
            if 50 < rate < 200:
                self.inr = rate
        except Exception:
            pass

    def status(self):
        day = self.today().isoformat()
        with self._lock:
            rows = {d: dict(r) for d, r in sorted(self.days.items())[-14:]}
        month = day[:7]
        month_usd = sum(r["usd"] for d, r in self.days.items() if d.startswith(month))
        today = rows.get(day, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0, "calls": 0})
        return {"today": today, "today_inr": round(today["usd"] * self.inr, 2), "month_usd": round(month_usd, 4),
                "month_inr": round(month_usd * self.inr, 2), "cap_usd": self.cap_usd(), "over_cap": self.over_cap(),
                "usd_to_inr": round(self.inr, 2), "days": rows, "services": SERVICES, "prices": PRICES,
                "t": time.time()}
