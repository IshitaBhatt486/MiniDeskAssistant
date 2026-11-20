"""
Spotify: play, pause, skip, volume and "what's playing", through the Spotify Web API (free).

Where the music plays: any Spotify Connect device on your account (your phone, laptop, a speaker), or the robot
itself if raspotify (librespot) runs on the Pi; then the device is called whatever you named it (settings
"device", default "deskbot"). The robot picks: the device named in the settings, else the active device, else
the first one. Playback control needs Spotify Premium (Spotify's rule: free accounts get 403 PREMIUM_REQUIRED).

Search picks the best match of the kind asked for: "play lo-fi beats" -> a playlist if one matches well, "play
Blinding Lights" -> a track, "play some Arijit Singh" -> the artist's top tracks (artist context).
"""

from __future__ import annotations

from urllib.parse import urlencode

from .accounts import AccountError

API = "https://api.spotify.com/v1"
KINDS = ("track", "artist", "playlist", "album")


class Spotify:
    def __init__(self, accounts, settings=lambda: {"device": "deskbot"}):
        self.accounts = accounts
        self.settings = settings
        self.last = None

    def available(self):
        return self.accounts.connected("spotify")

    def _call(self, method, path, body=None, query=None):
        token = self.accounts.token("spotify")
        url = f"{API}{path}" + (f"?{urlencode(query)}" if query else "")
        status, data = self.accounts.http(method, url, json_body=body, headers={"Authorization": f"Bearer {token}"})
        if status == 401:
            raise AccountError("Spotify sign-in is no longer valid. Connect it again.")
        if status == 403:
            reason = (data.get("error") or {}).get("reason", "")
            if reason == "PREMIUM_REQUIRED" or "premium" in str(data).lower():
                raise AccountError("Spotify only lets Premium accounts control playback.")
            raise AccountError("Spotify refused that. If your app is in development mode, add your account under "
                               "User Management on developer.spotify.com.")
        if status == 404 and "device" in str(data).lower():
            raise AccountError("No Spotify device is on. Open Spotify on your phone or computer, or start raspotify on the robot.")
        if status == 429:
            raise AccountError("Spotify asked me to slow down. Try again in a minute.")
        if status >= 400:
            raise AccountError(f"Spotify error {status}")
        return data

    def device(self):
        devices = self._call("GET", "/me/player/devices").get("devices", [])
        if not devices:
            raise AccountError("No Spotify device is on. Open Spotify on your phone or computer, or start raspotify on the robot.")
        want = (self.settings().get("device") or "").lower()
        return (next((d for d in devices if want and want in d.get("name", "").lower()), None)
                or next((d for d in devices if d.get("is_active")), None) or devices[0])

    def search(self, query, kind=""):
        kinds = [kind] if kind in KINDS else ["track", "artist", "playlist"]
        data = self._call("GET", "/search", query={"q": query, "type": ",".join(kinds), "limit": 3})
        q = query.lower()
        best = []
        for k in kinds:
            for item in (data.get(f"{k}s") or {}).get("items") or []:
                if not item:
                    continue
                name = item.get("name", "")
                exact = name.lower() == q
                score = (3 if exact else 1 if q in name.lower() or name.lower() in q else 0) + (0.5 if k == kind else 0)
                if k == "track":
                    score += 0.4                                  # a song is the usual meaning of "play X"
                best.append((score, k, item))
        if not best:
            raise AccountError(f"I couldn't find {query!r} on Spotify")
        score, k, item = max(best, key=lambda x: x[0])
        artist = ", ".join(a["name"] for a in item.get("artists", [])[:2]) if k in ("track", "album") else ""
        return {"kind": k, "uri": item["uri"], "name": item.get("name"), "by": artist}

    def play(self, query="", kind=""):
        dev = self.device()
        q = {"device_id": dev["id"]}
        if not query.strip():
            self._call("PUT", "/me/player/play", query=q)
            self.last = {"action": "resume", "device": dev.get("name")}
            return self.last
        hit = self.search(query.strip(), kind)
        body = {"uris": [hit["uri"]]} if hit["kind"] == "track" else {"context_uri": hit["uri"]}
        self._call("PUT", "/me/player/play", body, query=q)
        self.last = {"action": "play", **hit, "device": dev.get("name")}
        return self.last

    def control(self, action, volume=None):
        if action == "pause":
            self._call("PUT", "/me/player/pause")
        elif action == "resume":
            return self.play()
        elif action in ("next", "previous"):
            self._call("POST", f"/me/player/{action}")
        elif action == "volume":
            v = max(0, min(100, int(volume if volume is not None else 50)))
            self._call("PUT", "/me/player/volume", query={"volume_percent": v})
        else:
            raise AccountError(f"unknown action {action}")
        self.last = {"action": action, **({"volume": volume} if action == "volume" else {})}
        return self.last

    def now_playing(self):
        data = self._call("GET", "/me/player/currently-playing")
        item = (data or {}).get("item")
        if not item:
            return {"playing": False}
        return {"playing": bool(data.get("is_playing")), "name": item.get("name"),
                "by": ", ".join(a["name"] for a in item.get("artists", [])[:2]),
                "progress_s": round((data.get("progress_ms") or 0) / 1000), "length_s": round(item.get("duration_ms", 0) / 1000)}
