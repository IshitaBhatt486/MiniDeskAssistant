"""
Connected accounts (Google, Spotify): OAuth 2.0 sign-in, token storage, refresh, disconnect.

Security model (details and remaining risks: docs/hub.md section 2):
    - Authorization code flow with PKCE (S256) and a random one-time `state` (10 minutes), checked with
      hmac.compare_digest. A code without a matching state is refused.
    - Smallest scopes that work: Google calendar.events + openid email; Spotify playback + user-read-private.
    - Client IDs/secrets only from secrets.env / the environment, never over HTTP.
    - Tokens live only on the robot, in data/accounts/<provider>.json (data/ is git-ignored), file mode 0600 on
      Linux, encrypted with Fernet when ACCOUNTS_KEY is set and `cryptography` is installed. No API ever returns a
      token: status() reports the account name, scopes and dates only.
    - Connecting / disconnecting needs ADMIN_PIN (secrets.env); 5 wrong PINs lock it for 5 minutes.
    - Requests go only to the fixed HTTPS hosts in ALLOWED_HOSTS, with certificate checks (urllib's default) and
      a timeout. Error texts are scrubbed of anything token-like before they are logged or shown.
    - Disconnect revokes the token at the provider where it has a revocation endpoint (Google) and deletes the file.

Redirect: http://127.0.0.1:<port>/oauth/<provider>/callback (a loopback address, which Google "Desktop app" and
Spotify clients accept). If the browser runs on the robot itself it finishes on its own; otherwise the browser
shows "can't connect" and you paste that page's address into the dashboard (finish_from_url).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 8.0
STATE_TTL_S = 600
ALLOWED_HOSTS = {"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com",
                 "accounts.spotify.com", "api.spotify.com"}

PROVIDERS = {
    "google": {
        "title": "Google Calendar",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scopes": ["openid", "email", "https://www.googleapis.com/auth/calendar.events"],
        "client_id_env": "GOOGLE_CLIENT_ID", "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "extra_auth": {"access_type": "offline", "prompt": "consent"},     # consent: always returns a refresh token
        "manage_url": "https://myaccount.google.com/permissions",
    },
    "spotify": {
        "title": "Spotify",
        "auth_url": "https://accounts.spotify.com/authorize",
        "token_url": "https://accounts.spotify.com/api/token",
        "revoke_url": None,                                                # Spotify has no revocation API
        "scopes": ["user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
                   "user-read-private"],
        "client_id_env": "SPOTIFY_CLIENT_ID", "client_secret_env": None,  # PKCE public client: no secret
        "extra_auth": {},
        "manage_url": "https://www.spotify.com/account/apps/",
    },
}

_TOKENISH = re.compile(r"(?i)(access_token|refresh_token|id_token|code|token|client_secret)(\"?\s*[:=]\s*\"?)[^\s\"&,}]+")
_LONG = re.compile(r"\b[A-Za-z0-9_\-\.]{40,}\b")


def scrub(text):
    """Remove anything that looks like a token from an error message."""
    text = _TOKENISH.sub(lambda m: m.group(1) + m.group(2) + "***", str(text))
    return _LONG.sub("***", text)[:300]


class AccountError(Exception):
    pass


def http(method, url, data=None, headers=None, json_body=None, timeout=TIMEOUT):
    """(status, parsed JSON or {}). Only to ALLOWED_HOSTS over HTTPS."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise AccountError(f"refusing to call {parts.hostname}")
    body = None
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "deskbot/1.0")
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except ValueError:
            payload = {}
        return exc.code, payload if isinstance(payload, dict) else {}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AccountError(f"can't reach {parts.hostname} ({scrub(getattr(exc, 'reason', exc))})") from exc


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt_claims(token):
    """The payload of an id_token. Not verified: it came straight from Google's token endpoint over TLS."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


class Vault:
    """Encrypted-if-possible token files, never readable from the web."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._fernet = None
        self.encryption = "off"
        key = os.environ.get("ACCOUNTS_KEY", "").strip()
        if key:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(key.encode())
                self.encryption = "fernet"
            except ImportError:
                self.encryption = "unavailable (pip install cryptography)"
            except Exception:
                self.encryption = "bad ACCOUNTS_KEY"

    def _path(self, provider):
        if provider not in PROVIDERS:
            raise AccountError("unknown provider")
        return self.folder / f"{provider}.json"

    def load(self, provider):
        p = self._path(provider)
        if not p.exists():
            return None
        raw = p.read_bytes()
        try:
            if raw.startswith(b"gAAAA"):
                if self._fernet is None:
                    raise AccountError("the token file is encrypted but ACCOUNTS_KEY is missing or wrong")
                raw = self._fernet.decrypt(raw)
            return json.loads(raw)
        except AccountError:
            raise
        except Exception as exc:
            raise AccountError(f"the saved {provider} sign-in can't be read; connect again") from exc

    def save(self, provider, record):
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.folder, 0o700)
        except OSError:
            pass
        raw = json.dumps(record).encode()
        if self._fernet is not None:
            raw = self._fernet.encrypt(raw)
        p = self._path(provider)
        tmp = p.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # created private, never world-readable
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        tmp.replace(p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def delete(self, provider):
        p = self._path(provider)
        if p.exists():
            p.unlink()


class PinGate:
    """ADMIN_PIN check with a lockout. Without a PIN, account changes are refused."""
    MAX_FAILS, LOCK_S = 5, 300

    def __init__(self, pin=None, clock=time.monotonic):
        self.pin = (pin if pin is not None else os.environ.get("ADMIN_PIN", "")).strip()
        self.clock = clock
        self.fails = []
        self.locked_until = 0.0

    def check(self, given):
        now = self.clock()
        if not self.pin:
            raise PermissionError("Set ADMIN_PIN in secrets.env first (then restart) to connect accounts")
        if now < self.locked_until:
            raise PermissionError(f"Too many wrong PINs. Try again in {int(self.locked_until - now)} s")
        if hmac.compare_digest(str(given or "").encode(), self.pin.encode()):
            self.fails.clear()
            return True
        self.fails = [t for t in self.fails if now - t < self.LOCK_S] + [now]
        if len(self.fails) >= self.MAX_FAILS:
            self.locked_until = now + self.LOCK_S
            self.fails.clear()
        raise PermissionError("Wrong PIN")


class Accounts:
    def __init__(self, folder: Path, port=8000, clock=time.time, http_fn=http, log=print):
        self.vault = Vault(folder)
        self.port = port
        self.clock = clock
        self.http = http_fn
        self.log = log
        self._pending = {}             # state -> {"provider", "verifier", "t", "redirect"}
        self._lock = threading.Lock()
        self.errors = {}               # provider -> last error (scrubbed)
        self.last_used = {}
        self.listeners = []            # fn(provider, connected: bool)

    # -- configuration --

    def client(self, provider):
        cfg = PROVIDERS[provider]
        cid = os.environ.get(cfg["client_id_env"], "").strip()
        secret = os.environ.get(cfg["client_secret_env"], "").strip() if cfg["client_secret_env"] else ""
        return cid, secret

    def redirect_uri(self, provider):
        return f"http://127.0.0.1:{self.port}/oauth/{provider}/callback"

    # -- sign-in --

    def start(self, provider):
        if provider not in PROVIDERS:
            raise AccountError("unknown provider")
        cid, _ = self.client(provider)
        if not cid:
            raise AccountError(f"Add {PROVIDERS[provider]['client_id_env']} to secrets.env first (see docs/hub.md)")
        cfg = PROVIDERS[provider]
        verifier = _b64url(secrets.token_bytes(48))
        state = _b64url(secrets.token_bytes(24))
        now = self.clock()
        with self._lock:
            self._pending = {s: p for s, p in self._pending.items() if now - p["t"] < STATE_TTL_S}
            self._pending[state] = {"provider": provider, "verifier": verifier, "t": now,
                                    "redirect": self.redirect_uri(provider)}
        params = {"client_id": cid, "response_type": "code", "redirect_uri": self.redirect_uri(provider),
                  "scope": " ".join(cfg["scopes"]), "state": state,
                  "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
                  **cfg["extra_auth"]}
        return {"url": cfg["auth_url"] + "?" + urllib.parse.urlencode(params), "redirect_uri": self.redirect_uri(provider)}

    def _take_state(self, state):
        now = self.clock()
        with self._lock:
            match = None
            for s in list(self._pending):
                if hmac.compare_digest(s.encode(), str(state or "").encode()):
                    match = self._pending.pop(s)             # one use only
            if match is None or now - match["t"] > STATE_TTL_S:
                raise AccountError("This sign-in link has expired or was already used. Press Connect again.")
            return match

    def finish(self, code, state, error=None):
        if error:
            raise AccountError(f"Sign-in was cancelled ({scrub(error)})")
        if not code:
            raise AccountError("No authorization code in that address")
        p = self._take_state(state)
        provider = p["provider"]
        cid, secret = self.client(provider)
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect"], "client_id": cid,
                "code_verifier": p["verifier"]}
        if secret:
            data["client_secret"] = secret
        status, tok = self.http("POST", PROVIDERS[provider]["token_url"], data=data)
        if status != 200 or "access_token" not in tok:
            raise AccountError(f"{PROVIDERS[provider]['title']} refused the sign-in: "
                               f"{scrub(tok.get('error_description') or tok.get('error') or status)}")
        record = self._record(provider, tok, previous=None)
        record["account"] = self._identify(provider, record, tok)
        record["connected_at"] = self.clock()
        self.vault.save(provider, record)
        self.errors.pop(provider, None)
        self.log(f"Connected {PROVIDERS[provider]['title']} as {record['account']}")
        for fn in self.listeners:
            fn(provider, True)
        return self.status()[provider]

    def finish_from_url(self, url):
        """The pasted address of the browser's 'can't connect' page after signing in."""
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(str(url).strip()).query)
        one = lambda k: (q.get(k) or [None])[0]   # noqa: E731
        return self.finish(one("code"), one("state"), one("error"))

    def _record(self, provider, tok, previous):
        rec = dict(previous or {})
        rec["access_token"] = tok["access_token"]
        if tok.get("refresh_token"):                 # Spotify may rotate it; Google sends it once
            rec["refresh_token"] = tok["refresh_token"]
        rec["expires_at"] = self.clock() + int(tok.get("expires_in", 3600))
        if tok.get("scope"):
            rec["scopes"] = tok["scope"].split()
        rec.setdefault("scopes", PROVIDERS[provider]["scopes"])
        return rec

    def _identify(self, provider, record, tok):
        if provider == "google":
            return _jwt_claims(tok.get("id_token", "")).get("email") or "Google account"
        status, me = self.http("GET", "https://api.spotify.com/v1/me",
                               headers={"Authorization": f"Bearer {record['access_token']}"})
        if status == 200:
            record["premium"] = me.get("product") == "premium"
            return me.get("display_name") or me.get("id") or "Spotify account"
        return "Spotify account"

    # -- using it --

    def token(self, provider):
        """A valid access token, refreshed if it expires within a minute. Raises AccountError if not connected."""
        rec = self.vault.load(provider)
        if rec is None:
            raise AccountError(f"{PROVIDERS[provider]['title']} isn't connected. Connect it on the dashboard.")
        if rec["expires_at"] - self.clock() < 60:
            if not rec.get("refresh_token"):
                raise AccountError(f"{PROVIDERS[provider]['title']} sign-in expired. Connect it again.")
            cid, secret = self.client(provider)
            data = {"grant_type": "refresh_token", "refresh_token": rec["refresh_token"], "client_id": cid}
            if secret:
                data["client_secret"] = secret
            status, tok = self.http("POST", PROVIDERS[provider]["token_url"], data=data)
            if status != 200 or "access_token" not in tok:
                msg = f"{PROVIDERS[provider]['title']} sign-in stopped working ({scrub(tok.get('error') or status)}). Connect it again."
                self.errors[provider] = msg
                raise AccountError(msg)
            rec = self._record(provider, tok, previous=rec)
            self.vault.save(provider, rec)
        self.last_used[provider] = self.clock()
        return rec["access_token"]

    def disconnect(self, provider):
        rec = None
        try:
            rec = self.vault.load(provider)
        except AccountError:
            pass
        revoked = False
        url = PROVIDERS[provider]["revoke_url"]
        if rec and url:
            try:
                status, _ = self.http("POST", url, data={"token": rec.get("refresh_token") or rec["access_token"]})
                revoked = status == 200
            except AccountError:
                pass
        self.vault.delete(provider)
        self.errors.pop(provider, None)
        for fn in self.listeners:
            fn(provider, False)
        return {"revoked": revoked, "manage_url": PROVIDERS[provider]["manage_url"]}

    def connected(self, provider):
        try:
            return self.vault.load(provider) is not None
        except AccountError:
            return False

    def status(self):
        out = {}
        for name, cfg in PROVIDERS.items():
            cid, _ = self.client(name)
            row = {"title": cfg["title"], "configured": bool(cid), "connected": False, "redirect_uri": self.redirect_uri(name),
                   "client_id_env": cfg["client_id_env"], "requested_scopes": cfg["scopes"], "manage_url": cfg["manage_url"],
                   "error": self.errors.get(name), "last_used": self.last_used.get(name)}
            try:
                rec = self.vault.load(name)
            except AccountError as exc:
                rec, row["error"] = None, str(exc)
            if rec:
                row.update(connected=True, account=rec.get("account"), scopes=rec.get("scopes"),
                           connected_at=rec.get("connected_at"), premium=rec.get("premium"),
                           can_refresh=bool(rec.get("refresh_token")))
            out[name] = row
        return out
