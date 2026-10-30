"""
Speaker: text -> speech WAV -> chipmunk effect -> the robot's speaker.

Text-to-speech engines, tried in this order (first one installed wins, all offline + free):
    piper       natural neural voice; `piper` on PATH + a voice in models/piper/*.onnx (optional)
    espeak-ng   robotic but tiny; `sudo apt install espeak-ng` (scripts/setup.sh --assistant installs it)
    espeak      older package name
    sapi        Windows only (System.Speech through PowerShell) - for simulation on the laptop

Chipmunk effect: the classic one - play the recording faster. Resampling the waveform to 1/f of its
length and playing it at the original sample rate multiplies every frequency by f (pitch up) and divides
the duration by f (tempo up). f = 1.6 sounds like a chipmunk and stays understandable; >2 gets hard
to follow. Done with numpy linear interpolation (no extra packages).

Voice styles (dashboard, settings "voice_style") work with every engine: natural, chipmunk, deep, robot,
radio and cave are numpy effects on the finished speech. "voice_gender" picks the engine's male or female
voice where it has one (espeak-ng variants, Windows SAPI voices).

Players: aplay (ALSA, preinstalled on Raspberry Pi OS; set DESKBOT_AUDIO_DEVICE=plughw:1,0 for a USB
card), paplay / pw-play, ffplay; winsound on Windows.

One worker thread speaks a queue (max 6 items, oldest dropped). Nothing here may raise into the
caller: failures go to alerts (never spoken - there's no voice to speak them with) and the status.
"""

from __future__ import annotations

import io
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from .. import MODELS_DIR

PIPER_DIR = MODELS_DIR / "piper"

VOICE_STYLES = {"chipmunk": "Chipmunk", "natural": "Natural", "deep": "Deep", "robot": "Robot", "radio": "Radio", "cave": "Cave echo"}
VOICE_GENDERS = {"auto": "Default", "female": "Female", "male": "Male"}


# ---------------- text cleanup ----------------

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def clean_for_speech(text: str) -> str:
    """Remove things a TTS engine would read out literally (markdown, emoji, URLs)."""
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_`#>|~]+", "", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


# ---------------- WAV helpers ----------------

def read_wav(data: bytes):
    """(samples float32 mono -1..1, sample_rate) from 8/16-bit PCM WAV bytes."""
    with wave.open(io.BytesIO(data)) as w:
        rate, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128.0
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV sample width {width}")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def write_wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def chipmunk(samples: np.ndarray, factor: float) -> np.ndarray:
    """Pitch AND tempo up by `factor` (resample to 1/factor of the length, same playback rate)."""
    if factor <= 1.0001 or len(samples) < 2:
        return samples
    n_out = max(2, int(len(samples) / factor))
    src = np.linspace(0, len(samples) - 1, n_out)
    return np.interp(src, np.arange(len(samples)), samples).astype(np.float32)


def resample(samples: np.ndarray, factor: float) -> np.ndarray:
    """factor > 1: higher and faster. factor < 1: lower and slower."""
    n_out = max(2, int(len(samples) / factor))
    return np.interp(np.linspace(0, len(samples) - 1, n_out), np.arange(len(samples)), samples).astype(np.float32)


def apply_style(x: np.ndarray, rate: int, style: str, factor=1.6) -> np.ndarray:
    if len(x) < 2 or style == "natural":
        return x
    if style == "chipmunk":
        return chipmunk(x, factor)
    if style == "deep":
        return resample(x, 0.78)
    if style == "robot":                     # ring modulation: the classic metallic voice
        t = np.arange(len(x)) / rate
        return (x * (0.35 + 0.65 * np.sin(2 * np.pi * 70 * t))).astype(np.float32)
    if style == "radio":                     # telephone band + soft clipping
        spectrum = np.fft.rfft(x)
        f = np.fft.rfftfreq(len(x), 1 / rate)
        spectrum[(f < 350) | (f > 3200)] = 0
        y = np.fft.irfft(spectrum, len(x))
        return np.tanh(3 * y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)
    if style == "cave":                      # three fading echoes
        out = np.zeros(len(x) + int(0.54 * rate), np.float32)
        for delay, gain in ((0.0, 1.0), (0.18, 0.45), (0.36, 0.25), (0.54, 0.12)):
            start = int(delay * rate)
            out[start:start + len(x)] += x * gain
        return out
    raise ValueError(f"unknown voice style {style!r}")


def process(wav_bytes: bytes, factor=1.0, volume=1.0, style="chipmunk") -> bytes:
    x, rate = read_wav(wav_bytes)
    x = apply_style(x, rate, style, factor)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0:
        x = x * (0.95 / peak)        # normalise: espeak output is quiet
    return write_wav(x * volume, rate)


# ---------------- engines ----------------

def _run(cmd, inp=None, timeout=30):
    r = subprocess.run(cmd, input=inp, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode(errors="replace").strip()[:200] or f"exit {r.returncode}")
    return r


class PiperTTS:
    name = "piper"
    gender = "auto"          # a Piper model has one fixed voice

    def __init__(self):
        exe = shutil.which("piper")
        voices = sorted(PIPER_DIR.glob("*.onnx")) if PIPER_DIR.exists() else []
        if not exe or not voices:
            raise RuntimeError("piper or a voice in models/piper/ not found")
        self.exe, self.voice = exe, voices[0]

    def synth(self, text):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            _run([self.exe, "--model", str(self.voice), "--output_file", str(out)], inp=text.encode())
            return out.read_bytes()


class EspeakTTS:
    gender = "auto"

    def __init__(self, exe_name="espeak-ng"):
        self.exe = shutil.which(exe_name)
        if not self.exe:
            raise RuntimeError(f"{exe_name} not installed")
        self.name = exe_name

    def synth(self, text):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            variant = {"female": "en-us+f3", "male": "en-us+m3"}.get(self.gender, "en-us")
            _run([self.exe, "-v", variant, "-s", "160", "-w", str(out), text])
            return out.read_bytes()


class SapiTTS:
    """Windows System.Speech via PowerShell (simulation on the laptop)."""
    name = "sapi"
    gender = "auto"

    def __init__(self):
        if sys.platform != "win32" or not shutil.which("powershell"):
            raise RuntimeError("Windows only")

    def synth(self, text):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            # the text goes through an environment variable, so nothing in it can break the script
            pick = {"female": "$s.SelectVoiceByHints('Female'); ", "male": "$s.SelectVoiceByHints('Male'); "}.get(self.gender, "")
            script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                      f"{pick}$s.SetOutputToWaveFile('{out}'); $s.Speak($env:DESKBOT_TTS_TEXT); $s.Dispose()")
            env = dict(os.environ, DESKBOT_TTS_TEXT=text)
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, timeout=30, env=env)
            if r.returncode != 0 or not out.exists():
                raise RuntimeError((r.stderr or b"").decode(errors="replace")[:200] or "SAPI failed")
            return out.read_bytes()


def find_tts():
    errors = []
    for make in (PiperTTS, EspeakTTS, lambda: EspeakTTS("espeak"), SapiTTS):
        try:
            return make(), errors
        except Exception as exc:
            errors.append(str(exc))
    return None, errors


class Player:
    def __init__(self):
        self.device = os.environ.get("DESKBOT_AUDIO_DEVICE")
        self._proc = None
        if sys.platform == "win32":
            self.name = "winsound"
        elif shutil.which("aplay"):
            self.name = "aplay"
        elif shutil.which("pw-play"):
            self.name = "pw-play"
        elif shutil.which("paplay"):
            self.name = "paplay"
        elif shutil.which("ffplay"):
            self.name = "ffplay"
        else:
            self.name = None

    def play(self, wav: bytes):
        if self.name is None:
            raise RuntimeError("no audio player (install alsa-utils for aplay)")
        if self.name == "winsound":
            import winsound
            winsound.PlaySound(wav, winsound.SND_MEMORY)
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav)
            path = f.name
        try:
            cmd = {"aplay": ["aplay", "-q"] + (["-D", self.device] if self.device else []),
                   "pw-play": ["pw-play"], "paplay": ["paplay"],
                   "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]}[self.name] + [path]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            _, err = self._proc.communicate(timeout=60)
            if self._proc.returncode not in (0, -15):   # -15 = we interrupted it
                raise RuntimeError(err.decode(errors="replace").strip()[:200] or f"{self.name} exit {self._proc.returncode}")
        finally:
            self._proc = None
            try:
                os.unlink(path)
            except OSError:
                pass

    def interrupt(self):
        p = self._proc
        if p and p.poll() is None:
            p.terminate()
        if self.name == "winsound":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass


# ---------------- speaker ----------------

class Speaker:
    MAX_QUEUE = 6

    def __init__(self, settings, alerts=None):
        self.settings = settings
        self.alerts = alerts
        self.tts, errors = find_tts()
        self.player = Player()
        self.engine = self.tts.name if self.tts else None
        self.error = None
        if self.tts is None:
            self.error = "no text-to-speech engine: sudo apt install espeak-ng"
            self._alert("tts", "No text-to-speech engine. Install espeak-ng to hear me.", detail="; ".join(errors))
        elif self.player.name is None:
            self.error = "no audio player: sudo apt install alsa-utils"
            self._alert("speaker", "No audio player found. Install alsa-utils.")
        self._q = queue.Queue()
        self.speaking = None
        self.spoken = 0
        self.last_wav = None          # newest processed reply, served to the dashboard for in-browser playback
        self.last_wav_id = 0
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="speaker", daemon=True)
        self._thread.start()

    def _alert(self, key, msg, detail=None):
        if self.alerts:
            self.alerts.warn(key, msg, speak=False, detail=detail)   # never spoken: the voice is what failed

    def say(self, text, kind="reply"):
        """Queue `text`. kind: reply | alert | chatter. Returns immediately."""
        text = clean_for_speech(text or "")
        if not text:
            return
        if kind == "reply" and not self.settings.get("speak", True):
            return
        if kind == "alert" and not self.settings.get("speak_alerts", True):
            return
        while self._q.qsize() >= self.MAX_QUEUE:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._q.put((text, kind))

    def chime(self, name):
        """Queue a short musical motif (assistant/motifs.py). Returns immediately."""
        if self.settings.get("sounds", True) and self._q.qsize() < self.MAX_QUEUE:
            self._q.put((name, "motif"))

    def synth(self, text):
        """Processed WAV bytes for `text` (also used by tests and the dashboard preview)."""
        if self.tts is None:
            raise RuntimeError(self.error or "no TTS engine")
        self.tts.gender = self.settings.get("voice_gender", "auto")
        raw = self.tts.synth(text)
        style = self.settings.get("voice_style", "chipmunk")
        if style == "chipmunk" and not self.settings.get("chipmunk", True):
            style = "natural"            # settings saved before voice styles existed
        return process(raw, float(self.settings.get("chipmunk_factor", 1.6)), float(self.settings.get("volume", 0.9)), style)

    def interrupt(self):
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self.player.interrupt()

    def _loop(self):
        while self._running:
            try:
                text, kind = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "motif":
                try:
                    from .motifs import motif_wav
                    self.player.play(motif_wav(text, float(self.settings.get("volume", 0.9))))
                except Exception as exc:
                    self.error = f"{type(exc).__name__}: {exc}"[:200]
                continue
            if self.tts is None:
                continue
            self.speaking = text
            try:
                wav = self.synth(text)
                if kind == "reply":
                    self.last_wav, self.last_wav_id = wav, self.last_wav_id + 1
                self.player.play(wav)
                self.spoken += 1
                if self.error and self.alerts:
                    self.alerts.resolve("speaker", "Speaker works again.", speak=False)
                self.error = None
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:200]
                self._alert("speaker", "Couldn't play speech on the speaker.", detail=self.error)
                time.sleep(1.0)   # don't spin on a broken device
            finally:
                self.speaking = None

    def status(self):
        return {"engine": self.engine, "player": self.player.name, "speaking": self.speaking,
                "queued": self._q.qsize(), "spoken": self.spoken, "error": self.error,
                "device": self.player.device, "last_wav_id": self.last_wav_id}

    def close(self):
        self._running = False
        self.interrupt()
