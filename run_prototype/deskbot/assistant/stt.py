"""
Speech to text. Input is always a 16 kHz mono 16-bit WAV (the dashboard records it in the browser; the
robot's own USB mic records it with arecord).

Backends (settings "stt"; "auto" picks the first available in this order):
    local   faster-whisper on the Pi's CPU, offline and free (`pip install faster-whisper`);
            tiny.en takes ~1-2 s for a 5 s clip on a Pi 4, base.en ~3-5 s
    groq    Whisper large-v3-turbo on Groq's free tier - fast (~0.3 s), needs GROQ_API_KEY
    openai  OpenAI whisper-1, needs OPENAI_API_KEY
If the chosen backend fails, the next available one is tried; if all fail, the caller gets an
SttError with a message that is spoken to the user.

Before any of that, silent clips (peak below -50 dBFS) are rejected locally so a mis-click never costs
an API call.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

MAX_SECONDS = 30
SILENCE_DBFS = -50.0


class SttError(Exception):
    """Message is meant to be spoken to the user."""


def wav_info(data: bytes):
    """(seconds, peak dBFS) of a PCM WAV. Raises SttError if it isn't one."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            n, rate, width, ch = w.getnframes(), w.getframerate(), w.getsampwidth(), w.getnchannels()
            raw = w.readframes(n)
    except (wave.Error, EOFError) as exc:
        raise SttError("The recording wasn't a valid audio file.") from exc
    if width != 2:
        raise SttError("The recording must be 16-bit audio.")
    x = np.frombuffer(raw, "<i2")
    peak = float(np.max(np.abs(x.astype(np.int32)))) if x.size else 0.0
    dbfs = 20 * math.log10(peak / 32768.0) if peak > 0 else -120.0
    return n / float(rate or 1), dbfs


def _multipart(fields: dict, file_field: str, filename: str, data: bytes, ctype="audio/wav"):
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
              f"Content-Type: {ctype}\r\n\r\n".encode())
    out.write(data)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


class _WhisperHTTP:
    url = ""
    model = ""
    key_env = ""

    def available(self):
        return bool(os.environ.get(self.key_env))

    def transcribe(self, wav: bytes, timeout=20.0):
        body, ctype = _multipart({"model": self.model, "response_format": "json", "temperature": "0"},
                                 "file", "speech.wav", wav)
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": f"Bearer {os.environ[self.key_env]}", "Content-Type": ctype,
            "User-Agent": "deskbot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())["text"].strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            if exc.code in (401, 403):
                raise RuntimeError(f"{self.name}: API key rejected ({exc.code})") from exc
            if exc.code == 429:
                raise RuntimeError(f"{self.name}: rate limited, try again in a minute") from exc
            raise RuntimeError(f"{self.name}: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name}: no connection ({exc.reason})") from exc


class GroqWhisper(_WhisperHTTP):
    name = "groq"
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    model = "whisper-large-v3-turbo"
    key_env = "GROQ_API_KEY"


class OpenAIWhisper(_WhisperHTTP):
    name = "openai"
    url = "https://api.openai.com/v1/audio/transcriptions"
    model = "whisper-1"
    key_env = "OPENAI_API_KEY"


class LocalWhisper:
    name = "local"

    def __init__(self, model_name="tiny.en"):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def available(self):
        try:
            import importlib.util
            return importlib.util.find_spec("faster_whisper") is not None
        except Exception:
            return False

    def transcribe(self, wav: bytes, timeout=None):
        with self._lock:   # one transcription at a time; the model isn't thread-safe and the Pi has no spare cores
            if self._model is None:
                from faster_whisper import WhisperModel
                # int8 on CPU: ~4x less memory and ~2x faster than float32 on the Pi's Cortex-A72
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8", cpu_threads=2)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav)
                path = f.name
            try:
                segments, _ = self._model.transcribe(path, beam_size=1, vad_filter=True)
                return " ".join(s.text.strip() for s in segments).strip()
            finally:
                os.unlink(path)


class Transcriber:
    def __init__(self, settings, alerts=None):
        self.settings = settings
        self.alerts = alerts
        self.backends = {"groq": GroqWhisper(), "openai": OpenAIWhisper(),
                         "local": LocalWhisper(settings.get("local_whisper_model", "tiny.en"))}
        self.last = None    # {"backend", "ms", "text"} or {"error"}

    def order(self):
        pref = self.settings.get("stt", "auto")
        if pref == "none":
            return []
        if pref == "local":                   # strictly local: audio is never sent anywhere as a fallback
            return ["local"] if self.backends["local"].available() else []
        names = ["local", "groq", "openai"]   # free and private first, when faster-whisper is installed
        if pref in names:
            names.remove(pref)
            names.insert(0, pref)
        return [n for n in names if self.backends[n].available()]

    def status(self):
        return {"preference": self.settings.get("stt", "auto"),
                "available": self.order(), "last": self.last}

    def transcribe(self, wav: bytes) -> str:
        seconds, peak = wav_info(wav)
        if seconds < 0.3:
            raise SttError("That recording was too short. Hold the button while you talk.")
        if seconds > MAX_SECONDS:
            raise SttError(f"That recording was too long. Keep it under {MAX_SECONDS} seconds.")
        if peak < SILENCE_DBFS:
            raise SttError("I didn't hear anything. Is the microphone muted?")
        order = self.order()
        if not order:
            raise SttError("I can't understand speech yet: add a GROQ_API_KEY to secrets.env, "
                           "or install faster-whisper. You can type to me instead.")
        errors = []
        for name in order:
            t0 = time.perf_counter()
            try:
                text = self.backends[name].transcribe(wav)
                self.last = {"backend": name, "ms": round((time.perf_counter() - t0) * 1000), "text": text}
                if errors and self.alerts:
                    self.alerts.warn("stt", f"Speech to text fell back to {name}.", speak=False, detail="; ".join(errors))
                elif self.alerts:
                    self.alerts.resolve("stt")
                return text
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        self.last = {"error": "; ".join(errors)}
        if self.alerts:
            self.alerts.warn("stt", "Speech to text isn't working.", detail="; ".join(errors))
        raise SttError("Sorry, my speech recognition isn't working right now. You can type to me instead.")


# ---------------- the robot's own microphone (USB sound card, see microphone.md) ----------------

def capture_devices():
    """[(alsa_name, description)] from `arecord -l`."""
    if not shutil.which("arecord"):
        return []
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    return [(f"plughw:{m.group(1)},{m.group(4)}", f"{m.group(3)} - {m.group(5)}")
            for m in re.finditer(r"card (\d+): (\S+) \[(.*?)\], device (\d+): .*?\[(.*?)\]", out)]


def record_robot_mic(seconds=5.0):
    """Record from the robot's microphone. Raises SttError (spoken) when there is none."""
    if not shutil.which("arecord"):
        raise SttError("I have no microphone tools. Install alsa-utils, or talk to me from the dashboard.")
    device = os.environ.get("DESKBOT_MIC_DEVICE") or next(iter(capture_devices()), (None,))[0]
    if not device:
        raise SttError("I can't find my microphone. Is the USB sound card plugged in?")
    seconds = max(1.0, min(15.0, float(seconds)))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "mic.wav")
        r = subprocess.run(["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "1",
                            "-d", str(int(math.ceil(seconds))), path], capture_output=True, timeout=seconds + 5)
        if r.returncode != 0:
            raise SttError("My microphone didn't work: " + r.stderr.decode(errors="replace").strip()[:120])
        with open(path, "rb") as f:
            return f.read()
