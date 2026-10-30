"""
Tools the AI can call (Claude tool use). All web APIs here are free and need no API key.

    get_weather        Open-Meteo (geocoding + forecast)      open-meteo.com, no key, 10k calls/day
    get_time           the Pi's clock
    wikipedia_summary  Wikipedia REST API                     en.wikipedia.org, no key
    tell_joke          Official Joke API                      official-joke-api.appspot.com
    convert_currency   ExchangeRate-API open endpoint          open.er-api.com, no key, daily rates
    robot_status       local: sensors, what's on the map, presence

A tool never raises into the brain's loop: `run_tool` returns (text, is_error). An error result goes
back to Claude as `is_error: true`, so it can apologise or try something else, and the failure is
also reported to alerts (not spoken: the AI's reply already explains it).

Requests send a generic User-Agent ("deskbot/1.0") - Wikimedia asks for one - and no personal data.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

UA = "deskbot/1.0 (desk assistant robot)"
TIMEOUT = 6.0

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
    82: "violent showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


class ToolError(Exception):
    pass


def http_json(url, params=None, timeout=TIMEOUT):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ToolError(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(f"no internet connection ({getattr(exc, 'reason', exc)})") from exc
    except ValueError as exc:
        raise ToolError("bad response") from exc


# ---------------- individual tools ----------------

_geo_cache = {}


def geocode(place):
    key = place.strip().lower()
    if key in _geo_cache:
        return _geo_cache[key]
    # Open-Meteo matches the place name only ("Delhi", not "Delhi, India"): try the full string, then the first part
    for name in dict.fromkeys([place.strip(), place.split(",")[0].strip()]):
        data = http_json("https://geocoding-api.open-meteo.com/v1/search",
                         {"name": name, "count": 1, "language": "en", "format": "json"})
        if data.get("results"):
            r = data["results"][0]
            out = (r["latitude"], r["longitude"], ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x))
            _geo_cache[key] = out
            return out
    raise ToolError(f"couldn't find a place called {place!r}")


def ip_location():
    data = http_json("https://ipapi.co/json/")
    if "latitude" not in data:
        raise ToolError("couldn't work out where I am; tell me a city")
    return data["latitude"], data["longitude"], ", ".join(x for x in (data.get("city"), data.get("country_name")) if x)


def get_weather(location="", default_location=""):
    place = (location or default_location or "").strip()
    lat, lon, name = geocode(place) if place else ip_location()
    data = http_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
    })
    c, d = data["current"], data["daily"]
    out = {
        "place": name,
        "now": {"conditions": WEATHER_CODES.get(c["weather_code"], "unknown"), "temperature_c": c["temperature_2m"],
                "feels_like_c": c["apparent_temperature"], "humidity_pct": c["relative_humidity_2m"],
                "wind_kmh": c["wind_speed_10m"], "precipitation_mm": c["precipitation"]},
        "forecast": [{"date": d["time"][i], "conditions": WEATHER_CODES.get(d["weather_code"][i], "unknown"),
                      "max_c": d["temperature_2m_max"][i], "min_c": d["temperature_2m_min"][i],
                      "rain_chance_pct": d["precipitation_probability_max"][i]} for i in range(len(d["time"]))],
        "sunrise": d["sunrise"][0], "sunset": d["sunset"][0],
    }
    return out


def get_time():
    now = datetime.now().astimezone()
    return {"local_time": now.strftime("%H:%M"), "date": now.strftime("%A %d %B %Y"), "timezone": str(now.tzinfo)}


def wikipedia_summary(topic):
    hits = http_json("https://en.wikipedia.org/w/api.php",
                     {"action": "opensearch", "search": topic, "limit": 1, "namespace": 0, "format": "json"})
    if not hits or len(hits) < 2 or not hits[1]:
        raise ToolError(f"no Wikipedia article about {topic!r}")
    title = hits[1][0]
    data = http_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")))
    extract = data.get("extract", "")
    return {"title": data.get("title", title), "summary": extract[:1200]}


def tell_joke():
    data = http_json("https://official-joke-api.appspot.com/random_joke")
    return {"setup": data.get("setup"), "punchline": data.get("punchline")}


_rates = {"t": 0.0, "base": None, "rates": None}


def convert_currency(amount, from_currency, to_currency):
    src, dst = from_currency.upper().strip(), to_currency.upper().strip()
    if _rates["base"] != src or time.time() - _rates["t"] > 3600:
        data = http_json(f"https://open.er-api.com/v6/latest/{urllib.parse.quote(src)}")
        if data.get("result") != "success":
            raise ToolError(f"unknown currency {src}")
        _rates.update(t=time.time(), base=src, rates=data["rates"])
    if dst not in _rates["rates"]:
        raise ToolError(f"unknown currency {dst}")
    rate = _rates["rates"][dst]
    return {"amount": amount, "from": src, "to": dst, "rate": rate, "result": round(float(amount) * rate, 2)}


# ---------------- registry ----------------

TOOL_SPECS = [
    {"name": "get_weather",
     "description": "Current weather and a 3-day forecast. Leave location empty to use the robot's configured "
                    "home city (or its IP location).",
     "input_schema": {"type": "object", "properties": {
         "location": {"type": "string", "description": "City name, e.g. 'Delhi' or 'Paris, France'. Empty = home."}},
         "required": ["location"], "additionalProperties": False}},
    {"name": "get_time", "description": "The current local date and time.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "wikipedia_summary", "description": "A short factual summary of a topic from Wikipedia.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}},
                      "required": ["topic"], "additionalProperties": False}},
    {"name": "tell_joke", "description": "A random (clean) joke with setup and punchline.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "convert_currency", "description": "Convert money between currencies using today's exchange rate.",
     "input_schema": {"type": "object", "properties": {
         "amount": {"type": "number"}, "from_currency": {"type": "string", "description": "ISO code, e.g. USD"},
         "to_currency": {"type": "string", "description": "ISO code, e.g. INR"}},
         "required": ["amount", "from_currency", "to_currency"], "additionalProperties": False}},
    {"name": "robot_status",
     "description": "The robot's own state: distance sensors, whether it is on the desk, objects it remembers on its "
                    "map (with positions), whether the owner's phone is nearby, and current activity.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
]
for _spec in TOOL_SPECS:
    _spec["strict"] = True


def run_tool(name, args, ctx):
    """(result text, is_error). ctx: {"default_location": str, "robot_status": callable}."""
    try:
        if name == "get_weather":
            out = get_weather(args.get("location", ""), ctx.get("default_location", ""))
        elif name == "get_time":
            out = get_time()
        elif name == "wikipedia_summary":
            out = wikipedia_summary(str(args.get("topic", "")))
        elif name == "tell_joke":
            out = tell_joke()
        elif name == "convert_currency":
            out = convert_currency(float(args["amount"]), str(args["from_currency"]), str(args["to_currency"]))
        elif name == "robot_status":
            out = ctx["robot_status"]() if ctx.get("robot_status") else {"error": "not available"}
        else:
            return f"Unknown tool {name}", True
        return json.dumps(out, default=str), False
    except ToolError as exc:
        return f"Error: {exc}", True
    except Exception as exc:  # a tool bug must not end the conversation
        return f"Error: {type(exc).__name__}: {exc}", True
