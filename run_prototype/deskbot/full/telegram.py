"""
Telegram bot: talk to the robot from anywhere, get guard alerts and briefings, send it pages to read.

Setup (free): in Telegram, message @BotFather -> /newbot -> copy the token into secrets.env as
TELEGRAM_BOT_TOKEN=... and restart. Then pair YOUR chat: the dashboard's Telegram card shows a 6-digit code
(valid 10 minutes, single use); send "/pair 123456" to your bot. Only paired chats are answered; anyone else gets
one "this robot is private" reply an hour and nothing more. Paired chats: data/telegram.json (unpair on the card).

No public address or port forwarding is needed: the robot asks Telegram for new messages (long polling,
getUpdates with a 25 s timeout), outbound HTTPS to api.telegram.org only.

    /help                 this list
    /tasks  /add <task>  /done <task>       the task list (deadlines understood: "/add call mom at 6")
    /idea <text>  /ideas                     the ideas notebook
    /brief                                   today's briefing
    /focus [minutes]  /stopfocus             focus mode
    /guard on|off  /photo                    guard mode; a snapshot of the desk now
    /water                                   hydration today
    /say <text>                              the robot says it out loud
    /status                                  what the robot is doing
    (a photo)                                read it (caption "summary" or "flashcards" for those); text saved
    (anything else)                          answered by the assistant, like talking to it (not spoken aloud)

Outgoing: guard snapshots, briefings (settings), and the routine step telegram{text}.
The bot token is never shown or logged (errors are scrubbed of it).
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = "https://api.telegram.org"
PAIR_TTL_S = 600
MAX_MSG = 4000


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, path: Path, commands, enabled=lambda: True, token=None, log=print, urlopen=urllib.request.urlopen):
        self.path = Path(path)
        self.commands = commands          # name -> fn(args text, chat_id) -> reply text; plus "_text", "_photo"
        self.enabled = enabled
        self.token = (token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.log = log
        self.urlopen = urlopen
        self.chats = []
        self.pair_code = None
        self.pair_until = 0.0
        self.offset = 0
        self.username = None
        self.error = None
        self.last = None
        self.received = self.sent = 0
        self._told = {}
        self._running = False
        if self.path.exists():
            try:
                self.chats = [int(c) for c in json.loads(self.path.read_text(encoding="utf-8")).get("chats", [])]
            except (OSError, ValueError, TypeError):
                self.chats = []

    def configured(self):
        return bool(self.token)

    def _scrub(self, text):
        return str(text).replace(self.token, "***") if self.token else str(text)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"chats": self.chats}), encoding="utf-8")

    def call(self, method, params=None, files=None, timeout=35):
        url = f"{API}/bot{self.token}/{method}"
        if files:
            boundary = uuid.uuid4().hex
            body = bytearray()
            for k, v in (params or {}).items():
                body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
            for k, (fname, data, ctype) in files.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                         f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            req = urllib.request.Request(url, data=json.dumps(params or {}).encode(), headers={"Content-Type": "application/json"})
        try:
            with self.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                desc = json.loads(exc.read()).get("description", "")
            except ValueError:
                desc = ""
            raise TelegramError(self._scrub(f"Telegram {exc.code}: {desc}")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TelegramError(self._scrub(f"can't reach Telegram ({getattr(exc, 'reason', exc)})")) from exc
        if not out.get("ok"):
            raise TelegramError(self._scrub(out.get("description", "Telegram error")))
        return out.get("result")

    def file_bytes(self, file_id):
        info = self.call("getFile", {"file_id": file_id})
        with self.urlopen(f"{API}/file/bot{self.token}/{info['file_path']}", timeout=30) as r:
            return r.read(10_000_000)

    # -- pairing --

    def new_pair_code(self):
        self.pair_code = f"{random.SystemRandom().randint(0, 999999):06d}"
        self.pair_until = time.monotonic() + PAIR_TTL_S
        return self.pair_code

    def unpair(self, chat_id=None):
        self.chats = [] if chat_id is None else [c for c in self.chats if c != int(chat_id)]
        self._save()

    # -- sending --

    def send(self, text, chat_ids=None):
        for chat in chat_ids or self.chats:
            for i in range(0, max(1, len(text)), MAX_MSG):
                self.call("sendMessage", {"chat_id": chat, "text": text[i:i + MAX_MSG] or "(empty)"})
                self.sent += 1

    def send_photo(self, jpeg, caption="", chat_ids=None):
        for chat in chat_ids or self.chats:
            self.call("sendPhoto", {"chat_id": chat, "caption": caption[:1000]}, files={"photo": ("desk.jpg", jpeg, "image/jpeg")})
            self.sent += 1

    def broadcast(self, text, jpeg=None):
        """Best-effort send to every paired chat (guard alerts, briefings). Never raises."""
        if not (self.configured() and self.enabled() and self.chats):
            return False
        try:
            self.send_photo(jpeg, text) if jpeg else self.send(text)
            return True
        except TelegramError as exc:
            self.error = str(exc)
            return False

    # -- receiving --

    def start(self):
        if not self.configured():
            self.error = "no TELEGRAM_BOT_TOKEN in secrets.env"
            return self
        self._running = True
        threading.Thread(target=self._loop, name="telegram", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        backoff = 5
        while self._running:
            if not self.enabled():
                time.sleep(2)
                continue
            try:
                if self.username is None:
                    self.username = self.call("getMe").get("username")
                    self.log(f"Telegram bot @{self.username} ready")
                updates = self.call("getUpdates", {"offset": self.offset, "timeout": 25, "allowed_updates": ["message"]}, timeout=40)
                for u in updates or []:
                    self.offset = max(self.offset, u["update_id"] + 1)
                    self.handle(u.get("message") or {})
                self.error, backoff = None, 5
            except Exception as exc:
                self.error = self._scrub(f"{type(exc).__name__}: {exc}")[:200]
                time.sleep(backoff)
                backoff = min(300, backoff * 2)

    def handle(self, msg):
        """One incoming message. Returns the reply text (also sent), or None."""
        chat = (msg.get("chat") or {}).get("id")
        if chat is None:
            return None
        self.received += 1
        text = (msg.get("text") or msg.get("caption") or "").strip()
        m = re.match(r"^/pair\s+(\d{6})$", text)
        if m:
            ok = self.pair_code and time.monotonic() < self.pair_until and m.group(1) == self.pair_code
            if ok:
                self.pair_code = None
                if chat not in self.chats:
                    self.chats.append(chat)
                    self._save()
                return self._reply(chat, "Paired! I'm your desk robot. Send /help to see what I can do.")
            return self._reply(chat, "That code is wrong or expired. Get a new one on the robot's dashboard.")
        if chat not in self.chats:
            if time.monotonic() - self._told.get(chat, -1e9) > 3600:
                self._told[chat] = time.monotonic()
                return self._reply(chat, "This robot is private. Its owner can pair a chat from the dashboard.")
            return None
        self.last = {"t": time.time(), "text": text[:80] or "(photo)"}
        try:
            if msg.get("photo"):
                jpeg = self.file_bytes(msg["photo"][-1]["file_id"])         # the largest size
                return self._reply(chat, self.commands["_photo"](jpeg, text, chat))
            m = re.match(r"^/(\w+)(?:@\w+)?\s*(.*)$", text, re.S)
            if m:
                name, args = m.group(1).lower(), m.group(2).strip()
                fn = self.commands.get(name)
                if fn is None:
                    return self._reply(chat, "I don't know that command. Send /help.")
                return self._reply(chat, fn(args, chat))
            if text:
                return self._reply(chat, self.commands["_text"](text, chat))
        except Exception as exc:
            return self._reply(chat, f"Sorry, that didn't work: {self._scrub(exc)}"[:300])
        return None

    def _reply(self, chat, text):
        if text:
            try:
                self.send(str(text), [chat])
            except TelegramError as exc:
                self.error = str(exc)
        return text

    def status(self):
        return {"configured": self.configured(), "enabled": self.enabled(), "bot": self.username, "paired": len(self.chats),
                "pair_code": self.pair_code if self.pair_code and time.monotonic() < self.pair_until else None,
                "pair_left_s": max(0, round(self.pair_until - time.monotonic())) if self.pair_code else 0,
                "error": self.error, "last": self.last, "received": self.received, "sent": self.sent}
