"""
"Hey Pip": a wake word, recognised on the robot. Nothing is streamed or saved until it hears its name.

The phrase follows the robot's name (assistant settings "robot_name"): "hey <name>". Detectors, first that works:

    vosk     Vosk (alphacephei.com/vosk, Apache-2.0) in grammar mode: the recogniser may only output the phrases
             ["hey pip", "pip", "[unk]"], so it is tiny, fast (a few % of one Pi 4 core) and needs no training.
             Model: models/vosk-model-small-en-us-0.15 (40 MB; downloaded once, or by scripts/setup.sh).
             If the name isn't in Vosk's vocabulary, the status says so (rename the robot or use whisper).
    whisper  fallback: speech bursts of up to 2.5 s are transcribed with the local faster-whisper model already used
             for speech-to-text, and checked for the phrase. Heavier, but "hey pip, what time is it" in one breath
             works directly (the words after the name become the request).

Audio: 16 kHz mono 16-bit from `arecord` (the robot's USB mic, ALSA; DESKBOT_MIC_DEVICE overrides the device), or
`sounddevice` on a computer, in 30 ms frames.

After the wake word: the "recognition" motif plays, the eyes turn curious, and the request is recorded until
0.8 s of quiet (an energy threshold 3x the measured noise floor, at least 4 s to start talking, at most 8 s in
all), then handed to the assistant exactly like the dashboard's mic button (Assistant.handle_audio).

While the robot is speaking (or has speech queued) the detector ignores the microphone, so it doesn't wake itself.
pause()/resume() release the microphone for other users (guard mode's question, the "robot mic" button).
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import wave
import zipfile
from array import array
from pathlib import Path

RATE = 16000
FRAME = 480                 # 30 ms
VOSK_MODEL = "vosk-model-small-en-us-0.15"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip"
SILENCE_END_S, START_WAIT_S, MAX_REQUEST_S = 0.8, 4.0, 8.0
WHISPER_BURST_S = 2.5


def rms(frame: bytes):
    a = array("h", frame)
    return math.sqrt(sum(x * x for x in a) / max(1, len(a))) if a else 0.0


def to_wav(pcm: bytes):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------- microphone ----------------

class Mic:
    """A raw 16 kHz mono stream. open() raises RuntimeError when there's no microphone."""

    def __init__(self):
        self.proc = None
        self.sd_stream = None
        self.name = None

    def open(self):
        if shutil.which("arecord"):
            from ..assistant.stt import capture_devices
            device = os.environ.get("DESKBOT_MIC_DEVICE") or next(iter(capture_devices()), (None,))[0]
            if not device:
                raise RuntimeError("no microphone found (is the USB sound card plugged in?)")
            self.proc = subprocess.Popen(["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            self.name = f"arecord {device}"
            return self
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("no microphone tools (arecord on the Pi, or pip install sounddevice)") from exc
        self.sd_stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME)
        self.sd_stream.start()
        self.name = "sounddevice"
        return self

    def read(self):
        if self.proc is not None:
            data = self.proc.stdout.read(FRAME * 2)
            if not data:
                raise RuntimeError("the microphone stopped")
            return data
        data, _ = self.sd_stream.read(FRAME)
        return bytes(data)

    def close(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.sd_stream is not None:
            self.sd_stream.stop()
            self.sd_stream.close()
            self.sd_stream = None


# ---------------- detectors ----------------

class VoskDetector:
    name = "vosk"

    def __init__(self, models_dir: Path, phrase, download=True, log=print):
        self.dir = Path(models_dir) / VOSK_MODEL
        self.phrase = phrase
        self.download, self.log = download, log
        self.rec = None
        self.problem = None

    def load(self):
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        if not self.dir.exists():
            if not self.download:
                raise RuntimeError(f"no Vosk model at {self.dir}")
            self.log(f"Downloading the Vosk wake-word model (40 MB) to {self.dir}")
            with urllib.request.urlopen(urllib.request.Request(VOSK_URL, headers={"User-Agent": "deskbot/1.0"}), timeout=120) as r:
                data = r.read(80_000_000)
            zipfile.ZipFile(io.BytesIO(data)).extractall(self.dir.parent)
        model = Model(str(self.dir))
        words = self.phrase.split()
        missing = [w for w in words if model.find_word(w) < 0]
        if missing:
            self.problem = f"Vosk doesn't know the word(s) {', '.join(missing)}; rename the robot or install faster-whisper"
            raise RuntimeError(self.problem)
        self.rec = KaldiRecognizer(model, RATE, json.dumps([self.phrase, words[-1], "[unk]"]))
        return self

    def feed(self, frame):
        """(heard the phrase?, words after it)."""
        if self.rec.AcceptWaveform(frame):
            text = json.loads(self.rec.Result()).get("text", "")
        else:
            text = json.loads(self.rec.PartialResult()).get("partial", "")
        if self.phrase in text:
            self.rec.Reset()
            return True, ""
        return False, ""

    def reset(self):
        if self.rec is not None:
            self.rec.Reset()


class WhisperDetector:
    """Energy-gated bursts transcribed by the local Whisper (assistant/stt.py LocalWhisper)."""
    name = "whisper"

    def __init__(self, transcriber, phrase):
        self.stt, self.phrase = transcriber, phrase
        self.buf = bytearray()
        self.voiced = 0
        self.quiet = 0
        self.floor = 300.0

    def load(self):
        local = self.stt.backends.get("local")
        if local is None or not local.available():
            raise RuntimeError("faster-whisper isn't installed")
        self.local = local
        return self

    def feed(self, frame):
        e = rms(frame)
        if not self.buf:
            self.floor = 0.98 * self.floor + 0.02 * e
        if e > max(400.0, self.floor * 3) or self.buf:
            self.buf += frame
            self.quiet = self.quiet + 1 if e < self.floor * 2 else 0
            if self.quiet * FRAME / RATE > 0.5 or len(self.buf) / 2 / RATE > WHISPER_BURST_S:
                pcm, self.buf, self.quiet = bytes(self.buf), bytearray(), 0
                if len(pcm) / 2 / RATE < 0.4:
                    return False, ""
                text = self.local.transcribe(to_wav(pcm)).lower()
                clean = "".join(ch for ch in text if ch.isalnum() or ch == " ")
                for variant in (self.phrase, self.phrase.replace("hey ", "hi "), self.phrase.replace("hey ", "a ")):
                    if variant in clean:
                        return True, clean.split(variant, 1)[1].strip()
        return False, ""

    def reset(self):
        self.buf = bytearray()


# ---------------- the listener ----------------

class WakeWord:
    def __init__(self, phrase_fn, on_request, on_wake=None, speaking=lambda: False, detectors=(), mic_factory=Mic,
                 log=print, enabled=lambda: True):
        self.phrase_fn = phrase_fn            # fn() -> "hey pip"
        self.on_request = on_request          # fn(wav bytes or None, text or None)
        self.on_wake = on_wake or (lambda: None)
        self.speaking = speaking
        self.detectors = list(detectors)      # factories: fn(phrase) -> detector (tried in order)
        self.mic_factory = mic_factory
        self.log = log
        self.enabled = enabled
        self.detector = None
        self.mic = None
        self.error = None
        self.count = 0
        self.last = None
        self._paused = threading.Event()
        self._running = False
        self._phrase = None

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, name="wake-word", daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def pause(self):
        self._paused.set()
        time.sleep(0.15)                     # let the loop release the microphone

    def resume(self):
        self._paused.clear()

    def _setup(self):
        phrase = self.phrase_fn().lower().strip()
        errors = []
        for factory in self.detectors:
            try:
                det = factory(phrase).load()
                self.detector, self._phrase, self.error = det, phrase, None
                self.log(f"Wake word \"{phrase}\" ready ({det.name})")
                return True
            except Exception as exc:
                errors.append(f"{getattr(factory, '__name__', 'detector')}: {exc}"[:160])
        self.error = "; ".join(errors) or "no wake-word detector"
        return False

    def _loop(self):
        backoff = 5.0
        while self._running:
            if not self.enabled() or self._paused.is_set():
                self._close_mic()
                time.sleep(0.3)
                continue
            try:
                if self.detector is None or self._phrase != self.phrase_fn().lower().strip():
                    if not self._setup():
                        time.sleep(30)
                        continue
                if self.mic is None:
                    self.mic = self.mic_factory().open()
                frame = self.mic.read()
                if self.speaking():
                    self.detector.reset()
                    continue
                hit, rest = self.detector.feed(frame)
                if hit:
                    self._woken(rest)
                backoff = 5.0
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:200]
                self._close_mic()
                time.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    def _woken(self, rest):
        self.count += 1
        self.last = {"t": time.time(), "said": rest or None}
        self.on_wake()
        if rest and len(rest.split()) >= 2:          # "hey pip what time is it": the request is already here
            self.on_request(None, rest)
            return
        time.sleep(0.35)                              # the chime (the speaker is busy: frames are skipped meanwhile)
        pcm = self.record_request()
        self.on_request(to_wav(pcm) if pcm else None, None)

    def record_request(self):
        """Audio until 0.8 s of quiet (bytes), or b'' if nobody spoke within START_WAIT_S.
        Time is counted in audio frames (30 ms each), so it is exact even if reading falls behind."""
        floor, frames, started, quiet, elapsed = None, bytearray(), False, 0.0, 0.0
        calib = []
        while elapsed < MAX_REQUEST_S:
            frame = self.mic.read()
            elapsed += FRAME / RATE
            e = rms(frame)
            if len(calib) < 8:                        # the first 0.24 s: the room's noise level
                calib.append(e)
                floor = sorted(calib)[len(calib) // 2]
                continue
            loud = e > max(350.0, floor * 3)
            if not started:
                if loud:
                    started = True
                elif elapsed > START_WAIT_S:
                    return b""
                else:
                    continue
            frames += frame
            quiet = 0.0 if loud else quiet + FRAME / RATE
            if quiet >= SILENCE_END_S:
                break
        return bytes(frames)

    def _close_mic(self):
        if self.mic is not None:
            try:
                self.mic.close()
            except Exception:
                pass
            self.mic = None

    def simulate(self, text):
        """The dashboard's "Simulate 'Hey Pip'" (no microphone needed)."""
        self.count += 1
        self.last = {"t": time.time(), "said": text, "simulated": True}
        self.on_wake()
        self.on_request(None, text)

    def status(self):
        return {"phrase": self.phrase_fn().lower(), "enabled": self.enabled(), "backend": self.detector.name if self.detector else None,
                "mic": self.mic.name if self.mic else None, "paused": self._paused.is_set(), "count": self.count,
                "last": self.last, "error": self.error}
