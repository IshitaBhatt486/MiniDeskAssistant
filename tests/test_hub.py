"""Hub (19 Nov 2026): ideas, focus mode, connected accounts (OAuth + security), Google Calendar, Spotify, costs.
No hardware, no network, no API key, no real accounts needed."""

import base64
import hashlib
import json
import os
import tempfile
import unittest
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import deskbot  # noqa: F401  (sys.path setup)
from deskbot.assistant.alerts import Alerts
from deskbot.assistant.brain import Brain
from deskbot.assistant.settings import Settings
from deskbot.assistant.stt import Transcriber
from deskbot.hub import accounts as acc
from deskbot.hub.config import HubSettings, validate
from deskbot.hub.costs import CostMeter, cost_usd
from deskbot.hub.focus import GRACE_S, PHONE_S, Focus, classify, face_angles
from deskbot.hub.google_cal import GoogleCalendar
from deskbot.hub.ideas import IdeaStore, local_intent, tool_handlers
from deskbot.hub.spotify import Spotify


def tmp():
    return Path(tempfile.mkdtemp())


# ---------------- costs ----------------

class CostTest(unittest.TestCase):
    def test_prices_and_cap(self):
        u = {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000, "cache_write": 0, "model": "claude-haiku-5-5"}
        self.assertAlmostEqual(cost_usd(u), 0.10 + 0.50 + 0.01)
        self.assertAlmostEqual(cost_usd({"input": 1_000_000}, "some-new-model"), 4.0)     # unknown: assume expensive
        alerts = []
        m = CostMeter(tmp() / "usage.json", cap_usd=lambda: 0.001, today=lambda: date(2026, 11, 19), alert=alerts.append)
        claude = SimpleNamespace(available=lambda: True)
        m.guard(claude)
        self.assertTrue(claude.available())
        m.add({"input": 2000, "output": 200, "cache_read": 4000, "model": "claude-haiku-5-5"})   # a typical turn
        self.assertLess(m.today_usd(), 0.001)
        for _ in range(5):
            m.add({"input": 2000, "output": 200, "cache_read": 4000, "model": "claude-haiku-5-5"})
        self.assertTrue(m.over_cap())
        self.assertFalse(claude.available())                    # the brain goes offline for the rest of the day
        self.assertEqual(len(alerts), 1)                        # said once
        again = CostMeter(m.path, today=lambda: date(2026, 11, 19))
        self.assertEqual(again.status()["today"]["calls"], 6)
        tomorrow = CostMeter(m.path, cap_usd=lambda: 0.001, today=lambda: date(2026, 11, 20))
        self.assertFalse(tomorrow.over_cap())

    def test_rate_refresh_guards_bad_values(self):
        m = CostMeter(tmp() / "u.json")
        m.refresh_rate(lambda: 1e9)
        self.assertEqual(m.inr, 88.0)
        m.refresh_rate(lambda: 84.2)
        self.assertEqual(m.inr, 84.2)

    def test_paid_speech_to_text_is_blocked(self):
        s = Settings(tmp() / "a.json")
        s.update({"stt": "openai"})
        t = Transcriber(s)
        for b in t.backends.values():
            b.available = lambda: True
        self.assertNotIn("openai", t.order())
        s.update({"allow_paid_apis": True})
        self.assertEqual(t.order()[0], "openai")


# ---------------- accounts: OAuth + security ----------------

class FakeHttp:
    def __init__(self):
        self.calls = []
        self.replies = {}

    def __call__(self, method, url, data=None, headers=None, json_body=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "headers": headers or {}, "json": json_body})
        for key, reply in self.replies.items():
            if key in url:
                return reply(self.calls[-1]) if callable(reply) else reply
        return 404, {}


def id_token(email):
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=").decode()
    return f"x.{payload}.sig"


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "gid", "GOOGLE_CLIENT_SECRET": "gsecret",
                                                "SPOTIFY_CLIENT_ID": "sid", "ACCOUNTS_KEY": ""})
        self.env.start()
        self.now = [1000.0]
        self.http = FakeHttp()
        self.a = acc.Accounts(tmp() / "accounts", port=8123, clock=lambda: self.now[0], http_fn=self.http, log=lambda *_: None)

    def tearDown(self):
        self.env.stop()

    def connect_google(self):
        start = self.a.start("google")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(start["url"]).query)
        self.http.replies["oauth2.googleapis.com/token"] = (200, {"access_token": "ya29.SECRET-ACCESS", "refresh_token": "1//SECRET-REFRESH",
                                                                  "expires_in": 3600, "scope": "openid email https://www.googleapis.com/auth/calendar.events",
                                                                  "id_token": id_token("me@example.com")})
        return q, self.a.finish_from_url(f"http://127.0.0.1:8123/oauth/google/callback?code=4/abc&state={q['state'][0]}")

    def test_pkce_state_and_no_tokens_in_status(self):
        q, row = self.connect_google()
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["redirect_uri"], ["http://127.0.0.1:8123/oauth/google/callback"])
        self.assertIn("calendar.events", q["scope"][0])
        exchange = self.http.calls[-1]["data"]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(exchange["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, q["code_challenge"][0])           # the verifier matches the challenge sent
        self.assertEqual(row["account"], "me@example.com")
        status = json.dumps(self.a.status())
        self.assertNotIn("SECRET", status)                            # tokens never leave the vault
        self.assertNotIn("gsecret", status)
        with self.assertRaises(acc.AccountError):                     # the state is single use
            self.a.finish("4/abc", q["state"][0])

    def test_bad_or_expired_state(self):
        with self.assertRaises(acc.AccountError):
            self.a.finish("code", "forged-state")
        start = self.a.start("spotify")
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(start["url"]).query)["state"][0]
        self.now[0] += acc.STATE_TTL_S + 1
        with self.assertRaises(acc.AccountError):
            self.a.finish("code", state)
        with self.assertRaises(acc.AccountError):
            self.a.finish(None, None, error="access_denied")

    def test_refresh_and_failure(self):
        self.connect_google()
        self.assertEqual(self.a.token("google"), "ya29.SECRET-ACCESS")
        self.now[0] += 3600
        self.http.replies["oauth2.googleapis.com/token"] = (200, {"access_token": "ya29.NEW", "expires_in": 3600})
        self.assertEqual(self.a.token("google"), "ya29.NEW")
        self.assertEqual(self.a.vault.load("google")["refresh_token"], "1//SECRET-REFRESH")  # kept when not rotated
        self.now[0] += 3600
        self.http.replies["oauth2.googleapis.com/token"] = (400, {"error": "invalid_grant"})
        with self.assertRaises(acc.AccountError):
            self.a.token("google")
        self.assertIn("Connect it again", self.a.status()["google"]["error"])

    def test_disconnect_revokes_google(self):
        self.connect_google()
        self.http.replies["oauth2.googleapis.com/revoke"] = (200, {})
        r = self.a.disconnect("google")
        self.assertTrue(r["revoked"])
        self.assertEqual(self.http.calls[-1]["data"]["token"], "1//SECRET-REFRESH")
        self.assertFalse(self.a.connected("google"))
        self.assertFalse((self.a.vault.folder / "google.json").exists())

    def test_unconfigured_and_hosts(self):
        with mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": ""}):
            with self.assertRaises(acc.AccountError):
                self.a.start("spotify")
        for url in ("http://oauth2.googleapis.com/token", "https://evil.example.com/x"):
            with self.assertRaises(acc.AccountError):
                acc.http("GET", url)

    def test_scrub(self):
        s = acc.scrub('{"access_token": "ya29.abc", "error": "x"} refresh_token=1//zzz Bearer ' + "A" * 50)
        self.assertNotIn("ya29.abc", s)
        self.assertNotIn("1//zzz", s)
        self.assertNotIn("A" * 50, s)

    def test_token_file_is_private_and_encrypted_when_keyed(self):
        self.connect_google()
        path = self.a.vault.folder / "google.json"
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            self.skipTest("cryptography not installed here")
        with mock.patch.dict(os.environ, {"ACCOUNTS_KEY": Fernet.generate_key().decode()}):
            v = acc.Vault(tmp())
            v.save("google", {"access_token": "SECRET"})
            self.assertNotIn(b"SECRET", (v.folder / "google.json").read_bytes())
            self.assertEqual(v.load("google")["access_token"], "SECRET")

    def test_pin_gate(self):
        t = [0.0]
        with self.assertRaises(PermissionError):
            acc.PinGate("").check("1234")                    # no PIN set: account changes refused
        g = acc.PinGate("2468", clock=lambda: t[0])
        self.assertTrue(g.check("2468"))
        for _ in range(5):
            with self.assertRaises(PermissionError):
                g.check("0000")
        with self.assertRaises(PermissionError) as cm:
            g.check("2468")                                  # locked, even with the right PIN
        self.assertIn("Too many", str(cm.exception))
        t[0] += 301
        self.assertTrue(g.check("2468"))


# ---------------- Google Calendar ----------------

class FakeAccounts:
    def __init__(self, replies):
        self.calls, self.replies = [], replies

    def connected(self, provider):
        return True

    def token(self, provider):
        return "tok"

    def http(self, method, url, data=None, headers=None, json_body=None):
        self.calls.append((method, url, json_body))
        for (m, key), reply in self.replies.items():
            if m == method and key in url:
                return reply
        return 200, {}


class CalendarTest(unittest.TestCase):
    def test_reminder_and_task_sync(self):
        fa = FakeAccounts({("POST", "/events"): (200, {"id": "ev1", "htmlLink": "https://cal"})})
        cal = GoogleCalendar(fa, tmp() / "map.json", lambda: {"sync_tasks": True, "minutes_before": 10})
        r = cal.add_reminder("call the bank", datetime(2026, 11, 20, 16, 0), 5)
        self.assertEqual(r["id"], "ev1")
        body = fa.calls[-1][2]
        self.assertEqual(body["reminders"], {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]})
        self.assertTrue(body["start"]["dateTime"].startswith("2026-11-20T16:00:00"))
        task = {"id": 7, "title": "submit report", "due": "2026-11-20T17:00:00"}
        cal._sync("added", task)
        self.assertEqual(cal.events["7"], "ev1")
        cal._sync("completed", task)
        self.assertEqual(fa.calls[-1][0], "PATCH")
        self.assertTrue(fa.calls[-1][2]["summary"].startswith("✓"))
        self.assertEqual(fa.calls[-1][2]["reminders"]["overrides"], [])
        cal._sync("removed", task)
        self.assertEqual(fa.calls[-1][0], "DELETE")
        self.assertNotIn("7", cal.events)

    def test_errors_are_reported_not_raised(self):
        fa = FakeAccounts({("POST", "/events"): (403, {})})
        said = []
        cal = GoogleCalendar(fa, tmp() / "m.json", alert=said.append)
        cal._sync("added", {"id": 1, "title": "x", "due": "2026-11-20T17:00:00"})
        self.assertIn("Calendar API enabled", cal.last_error)
        self.assertTrue(said)


# ---------------- Spotify ----------------

class SpotifyTest(unittest.TestCase):
    def test_play_search_and_errors(self):
        fa = FakeAccounts({
            ("GET", "/me/player/devices"): (200, {"devices": [{"id": "d1", "name": "Phone", "is_active": True},
                                                               {"id": "d2", "name": "deskbot"}]}),
            ("GET", "/search"): (200, {"tracks": {"items": [{"name": "Blinding Lights", "uri": "spotify:track:1", "artists": [{"name": "The Weeknd"}]}]},
                                       "artists": {"items": [{"name": "The Weeknd", "uri": "spotify:artist:9"}]},
                                       "playlists": {"items": [None]}}),
            ("PUT", "/me/player/play"): (204, {}),
        })
        sp = Spotify(fa, lambda: {"device": "deskbot"})
        hit = sp.play("blinding lights")
        self.assertEqual((hit["kind"], hit["device"], hit["by"]), ("track", "deskbot", "The Weeknd"))
        method, url, body = fa.calls[-1]
        self.assertIn("device_id=d2", url)
        self.assertEqual(body, {"uris": ["spotify:track:1"]})
        self.assertEqual(sp.play("the weeknd", "artist")["uri"], "spotify:artist:9")
        self.assertEqual(fa.calls[-1][2], {"context_uri": "spotify:artist:9"})
        fa.replies[("PUT", "/me/player/pause")] = (403, {"error": {"reason": "PREMIUM_REQUIRED"}})
        with self.assertRaises(acc.AccountError) as cm:
            sp.control("pause")
        self.assertIn("Premium", str(cm.exception))
        fa.replies[("GET", "/me/player/devices")] = (200, {"devices": []})
        with self.assertRaises(acc.AccountError):
            sp.play("x")


# ---------------- ideas ----------------

class IdeasTest(unittest.TestCase):
    def test_voice_and_capture(self):
        s = IdeaStore(tmp() / "ideas.json")
        r = local_intent("Remember this idea: a robot that waters my plants", s)
        self.assertEqual(r["sound"], "ding")
        self.assertEqual(s.ideas[-1]["text"], "A robot that waters my plants")
        self.assertIn("What is it", local_intent("remember this idea", s)["speech"])
        local_intent("Solar powered desk lamp", s)                    # the next sentence is the idea
        self.assertEqual(s.ideas[-1]["text"], "Solar powered desk lamp")
        self.assertIsNone(local_intent("what's the weather", s))       # capture over
        self.assertIn("Solar", local_intent("what was my last idea", s)["speech"])
        self.assertIn("newest ideas", local_intent("what were my ideas", s)["speech"])
        local_intent("forget the plant idea", s)
        self.assertEqual([i["text"] for i in s.ideas], ["Solar powered desk lamp"])
        again = IdeaStore(s.path)
        self.assertEqual(len(again.ideas), 1)
        self.assertIn("Solar", again.markdown())

    def test_tools(self):
        s = IdeaStore(tmp() / "i.json")
        t = tool_handlers(s)
        self.assertFalse(t["save_idea"]({"text": "Gesture-controlled lamp"})[1])
        self.assertTrue(t["save_idea"]({"text": " "})[1])
        self.assertEqual(json.loads(t["list_ideas"]({"query": "lamp"})[0])["ideas"][0]["id"], 1)
        self.assertFalse(t["delete_idea"]({"idea": "#1"})[1])


# ---------------- focus mode ----------------

def face(yaw=0.0, pitch=0.55, cx=160, cy=120):
    """A YuNet-like row with landmarks that give this yaw/pitch."""
    eye_d = 40.0
    rex, lex, ey = cx - 20, cx + 20, cy - 10
    nx = cx + yaw * eye_d
    mouth_y = ey + 30
    ny = ey + pitch * 30
    return [cx - 40, cy - 50, 80, 100, rex, ey, lex, ey, nx, ny, cx - 15, mouth_y, cx + 15, mouth_y, 0.95]


PERSON = [("person", 0.9, (0, 0, 300, 240))]


class FocusTest(unittest.TestCase):
    def test_angles_and_classify(self):
        y, p = face_angles(face(0.3, 0.6))
        self.assertAlmostEqual(y, 0.3, places=3)
        self.assertAlmostEqual(p, 0.6, places=3)
        base = (0.1, 0.55)
        self.assertEqual(classify(PERSON, face(0.15), base, 0)[0], "focused")
        self.assertEqual(classify(PERSON, face(0.7), base, 0)[0], "away")
        self.assertEqual(classify(PERSON, face(0.1, 0.95), base, 0)[0], "down")
        self.assertEqual(classify(PERSON + [("cell phone", 0.8, (1, 1, 2, 2))], face(0.1), base, 0)[0], "phone")
        self.assertEqual(classify([], None, base, 0)[0], "absent")
        self.assertEqual(classify(PERSON, None, base, 1)[0], "unknown")
        self.assertEqual(classify(PERSON, None, base, 3)[0], "away")    # a person, but the face turned right round

    def test_session(self):
        t = [0.0]
        nudges, ends, breaks = [], [], []
        f = Focus(tmp() / "focus.json", vision=object(), clock=lambda: t[0], wall=lambda: datetime(2026, 11, 19, 10, 0),
                  on_nudge=lambda k, line: nudges.append(k), on_end=ends.append, on_break_end=lambda: breaks.append(1))
        f.start(1, 1)
        self.assertTrue(f.holding())

        def run(seconds, obs):
            for _ in range(int(seconds * 2)):
                t[0] += 0.5
                f.tick(0.5, obs)
        run(4, (PERSON, face(0.2)))                         # the first 4 s set the baseline (yaw 0.2)
        self.assertTrue(f.status()["calibrated"])
        run(GRACE_S - 1, (PERSON, face(0.9)))               # looking away, not long enough yet
        self.assertEqual(nudges, [])
        run(2, (PERSON, face(0.9)))
        self.assertEqual(nudges, ["away"])
        run(4, (PERSON, face(0.2)))                         # 3 s of focus resets the counter
        run(PHONE_S + 1, (PERSON + [("cell phone", 0.8, (0, 0, 1, 1))], face(0.2)))
        self.assertEqual(nudges, ["away", "phone"])
        self.assertEqual(f.status()["distractions"], 2)
        run(40, (PERSON, face(0.2)))                        # past the 1-minute end
        self.assertEqual(f.state, "break")
        self.assertEqual(ends[0]["reason"], "finished")
        self.assertTrue(30 < ends[0]["focused_pct"] < 80)
        t[0] += 61
        f.tick(0.5, (PERSON, face(0.2)))
        self.assertEqual((f.state, breaks), ("idle", [1]))
        self.assertEqual(Focus(f.log_path).history[-1]["distractions"], 2)

    def test_no_camera_is_a_timer(self):
        t = [0.0]
        f = Focus(tmp() / "f.json", vision=None, clock=lambda: t[0])
        f.start(1)
        f.tick()
        self.assertEqual(f.status()["observation"], "no camera")
        t[0] += 61
        f.tick()
        self.assertEqual(f.state, "break")


# ---------------- wiring ----------------

class WiringTest(unittest.TestCase):
    def test_music_and_focus_words_are_not_robot_commands(self):
        from deskbot.hub.core import NOT_LOCAL
        b = Brain(Settings(tmp() / "a.json"), Alerts(log=lambda *_: None))
        b.not_local.append(NOT_LOCAL)
        b.claude.available = lambda: False
        seen = []
        b.local_handlers.append(lambda text, ctx: seen.append(text) or {"speech": "Paused.", "mood": "neutral", "commands": [], "backend": "local"})
        out = b.think("stop the music", "ctx")
        self.assertEqual(out["commands"], [])                       # not a robot "stop"
        self.assertEqual(seen, ["stop the music"])
        self.assertEqual(b.think("stop", "ctx")["commands"][0]["action"], "stop")

    def test_settings(self):
        s = HubSettings(tmp() / "h.json")
        s.update({"costs": {"daily_cap_usd": 1.25}, "focus": {"minutes": 50}})
        self.assertEqual(HubSettings(s.path).section("focus")["minutes"], 50)
        for bad in ({"costs": {"daily_cap_usd": 99}}, {"focus": {"minutes": 0}}):
            with self.assertRaises(ValueError):
                validate(bad)


if __name__ == "__main__":
    unittest.main()
