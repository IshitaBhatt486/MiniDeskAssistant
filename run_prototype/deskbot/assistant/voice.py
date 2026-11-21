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


def time_stretch(x: np.ndarray, rate: int, speed: float) -> np.ndarray:
    """Change the duration by 1/speed WITHOUT changing the pitch (20 Nov 2026). WSOLA: 40 ms Hann frames are
    overlap-added every 20 ms of output; each frame is taken from near its nominal input position (hop x speed),
    shifted by up to +-10 ms to the spot that best continues the previous frame (cross-correlation), so the
    waveform stays phase-continuous (no phasey/metallic sound). Gains are normalised by the window sum."""
    if abs(speed - 1.0) < 0.01 or len(x) < 4:
        return x
    n = max(64, int(0.040 * rate)) & ~1
    hop = n // 2
    tol = int(0.010 * rate)
    win = np.hanning(n).astype(np.float32)
    n_out = int(len(x) / speed)
    frames = max(1, (n_out - n) // hop + 2)
    pad = np.concatenate([np.zeros(tol, np.float32), x.astype(np.float32),
                          np.zeros(n * 2 + 2 * tol + int(hop * speed) + 1, np.float32)])
    out = np.zeros(frames * hop + n, np.float32)
    norm = np.zeros_like(out)
    prev_tail = None
    for k in range(frames):
        nominal = min(int(k * hop * speed) + tol, len(pad) - n - hop - tol)
        if prev_tail is None:
            start = nominal
        else:
            seg = pad[nominal - tol: nominal + tol + hop]
            corr = np.correlate(seg, prev_tail, mode="valid")
            start = nominal - tol + int(np.argmax(corr))
        out[k * hop:k * hop + n] += pad[start:start + n] * win
        norm[k * hop:k * hop + n] += win
        prev_tail = pad[start + hop:start + 2 * hop]      # what naturally follows this frame
    norm[norm < 1e-3] = 1.0
    return (out / norm)[:n_out].astype(np.float32)


def pitch_shift(x: np.ndarray, rate: int, semitones: float) -> np.ndarray:
    """Pitch up/down by `semitones`, same duration: resample (pitch and tempo x f), then stretch back by 1/f."""
    if abs(semitones) < 0.05 or len(x) < 4:
        return x
    f = 2.0 ** (semitones / 12.0)
    return time_stretch(resample(x, f), rate, 1.0 / f)


def process(wav_bytes: bytes, factor=1.0, volume=1.0, style="chipmunk", pitch=0.0, speed=1.0) -> bytes:
    """pitch (semitones) and speed (20 Nov 2026) are applied after the style. speed is only applied here when the
    engine couldn't do it itself (Speaker passes 1.0 when it could)."""
    x, rate = read_wav(wav_bytes)
    x = apply_style(x, rate, style, factor)
    x = pitch_shift(x, rate, pitch)
    x = time_stretch(x, rate, speed)
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
    speed = 1.0              # 20 Nov 2026: native speed (--length_scale) and voice_name (a model file's stem)
    voice_name = ""

    def __init__(self):
        exe = shutil.which("piper")
        voices = sorted(PIPER_DIR.glob("*.onnx")) if PIPER_DIR.exists() else []
        if not exe or not voices:
            raise RuntimeError("piper or a voice in models/piper/ not found")
        self.exe, self.voice, self.models = exe, voices[0], voices

    def voices(self):
        return [{"id": p.stem, "label": p.stem.replace("_", " ")} for p in self.models]

    def synth(self, text):
        model = next((p for p in self.models if p.stem == self.voice_name), self.voice)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            _run([self.exe, "--model", str(model), "--length_scale", f"{1.0 / max(0.5, self.speed):.3f}",
                  "--output_file", str(out)], inp=text.encode())
            return out.read_bytes()


class EspeakTTS:
    gender = "auto"
    speed = 1.0              # 20 Nov 2026: -s words per minute = 160 x speed
    voice_name = ""          # an English voice id from `espeak-ng --voices=en` (en-gb, en-us, en-gb-scotland, ...)

    def __init__(self, exe_name="espeak-ng"):
        self.exe = shutil.which(exe_name)
        if not self.exe:
            raise RuntimeError(f"{exe_name} not installed")
        self.name = exe_name
        self._voices = None

    def voices(self):
        if self._voices is None:
            try:
                rows = _run([self.exe, "--voices=en"], timeout=10).stdout.decode(errors="replace").splitlines()[1:]
                self._voices = [{"id": c[4], "label": c[3].replace("_", " ")} for c in (r.split() for r in rows) if len(c) >= 5]
            except Exception:
                self._voices = []
        return self._voices

    def synth(self, text):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            base = self.voice_name or "en-us"
            variant = {"female": base + "+f3", "male": base + "+m3"}.get(self.gender, base)
            _run([self.exe, "-v", variant, "-s", str(int(160 * self.speed)), "-w", str(out), text])
            return out.read_bytes()


class SapiTTS:
    """Windows System.Speech via PowerShell (simulation on the laptop)."""
    name = "sapi"
    gender = "auto"
    speed = 1.0              # 20 Nov 2026: $s.Rate (-10..10, about x1.1 per step)
    voice_name = ""          # an installed voice's name, e.g. "Microsoft Zira Desktop"

    def __init__(self):
        if sys.platform != "win32" or not shutil.which("powershell"):
            raise RuntimeError("Windows only")
        self._voices = None

    def voices(self):
        if self._voices is None:
            script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                      "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Gender }")
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, timeout=20)
                rows = [ln.split("|") for ln in r.stdout.decode(errors="replace").splitlines() if "|" in ln]
                self._voices = [{"id": n.strip(), "label": f"{n.strip().replace('Microsoft ', '').replace(' Desktop', '')} ({g.strip().lower()})"}
                                for n, g in rows]
            except Exception:
                self._voices = []
        return self._voices

    def synth(self, text):
        import math
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s.wav"
            # the text and the voice name go through environment variables, so nothing in them can break the script
            pick = {"female": "$s.SelectVoiceByHints('Female'); ", "male": "$s.SelectVoiceByHints('Male'); "}.get(self.gender, "")
            if self.voice_name:
                pick = "try { $s.SelectVoice($env:DESKBOT_TTS_VOICE) } catch { }; "
            rate = max(-10, min(10, round(math.log(max(0.5, min(2.0, self.speed))) / math.log(1.1))))
            script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                      f"{pick}$s.Rate = {rate}; $s.SetOutputToWaveFile('{out}'); $s.Speak($env:DESKBOT_TTS_TEXT); $s.Dispose()")
            env = dict(os.environ, DESKBOT_TTS_TEXT=text, DESKBOT_TTS_VOICE=self.voice_name)
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
        # 21 Nov 2026: until a speaker is wired, sound plays in the laptop's browser (assistant/laptop_speaker.py)
        from .laptop_speaker import LaptopSpeaker
        self.laptop = LaptopSpeaker()
        self._pace = threading.Event()        # set by interrupt(): stops waiting out a clip the laptop plays
        self._no_listener_warned = False
        self.engine = self.tts.name if self.tts else None
        self.error = None
        if self.tts is None:
            self.error = "no text-to-speech engine: sudo apt install espeak-ng"
            self._alert("tts", "No text-to-speech engine. Install espeak-ng to hear me.", detail="; ".join(errors))
        elif self.player.name is None and self.output() != "laptop":
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

    def output(self):
        """Where sound goes: laptop | robot | both. DESKBOT_SPEAKER overrides the saved setting."""
        from .laptop_speaker import OUTPUTS, output_from_env
        value = output_from_env() or self.settings.get("speaker_output", "laptop")
        return value if value in OUTPUTS else "laptop"

    def _emit(self, wav, kind, text=""):
        """Play one clip on the configured output(s). Blocks for about the clip's length either way, so the
        queue order, `speaking` and the queue limit behave the same on the laptop as on a real speaker."""
        out = self.output()
        if out in ("laptop", "both"):
            _, duration = self.laptop.push(wav, kind, text)
            self._check_listeners()
            if out == "laptop":
                self._pace.clear()
                self._pace.wait(duration + 0.15)    # interrupt() ends this early
                return
        self.player.play(wav)

    def _check_listeners(self):
        if self.laptop.listeners() == 0:
            if not self._no_listener_warned:
                self._no_listener_warned = True
                self._alert("laptop_speaker", "Sound goes to the laptop, but no browser is listening: open the dashboard "
                            "(or /speaker) on the laptop and click 'Turn on' in the speaker box.")
        elif self._no_listener_warned:
            self._no_listener_warned = False
            if self.alerts:
                self.alerts.resolve("laptop_speaker", "The laptop is playing my sound.", speak=False)

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
        speed = float(self.settings.get("voice_speed", 1.0))
        native = hasattr(self.tts, "speed")          # the built-in engines set their own rate (cleaner than stretching)
        if native:
            self.tts.speed = speed
        if hasattr(self.tts, "voice_name"):
            self.tts.voice_name = self.settings.get("voice_name", "")
        raw = self.tts.synth(text)
        style = self.settings.get("voice_style", "chipmunk")
        if style == "chipmunk" and not self.settings.get("chipmunk", True):
            style = "natural"            # settings saved before voice styles existed
        return process(raw, float(self.settings.get("chipmunk_factor", 1.6)), float(self.settings.get("volume", 0.9)), style,
                       pitch=float(self.settings.get("voice_pitch", 0.0)), speed=1.0 if native else speed)

    def voices(self):
        """The engine's installed voices [{"id", "label"}] (20 Nov 2026, pro/ voice studio); cached by the engine."""
        fn = getattr(self.tts, "voices", None)
        return fn() if fn else []

    def interrupt(self):
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self.laptop.interrupt()
        self._pace.set()
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
                    self._emit(motif_wav(text, float(self.settings.get("volume", 0.9))), "motif", text)
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
                self._emit(wav, kind, text)
                self.spoken += 1
                if self.error and self.alerts:
                    self.alerts.resolve("speaker", "Speaker works again.", speak=False)
                self.error = None
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:200]
                self._alert("speaker", "Couldn't play speech on the speaker. Set the speaker to 'laptop' in the dashboard "
                            "to hear me in the browser instead.", detail=self.error)
                time.sleep(1.0)   # don't spin on a broken device
            finally:
                self.speaking = None

    def status(self):
        return {"engine": self.engine, "player": self.player.name, "speaking": self.speaking,
                "queued": self._q.qsize(), "spoken": self.spoken, "error": self.error,
                "device": self.player.device, "last_wav_id": self.last_wav_id,
                "output": self.output(), "laptop": self.laptop.status()}

    def close(self):
        self._running = False
        self.interrupt()
