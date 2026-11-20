"""
Simulation test console (20 Nov 2026): try every feature from one terminal, without the Pi.

    python tools/sim_console.py                         # starts `main.py full --sim` on port 8150, then a prompt
    python tools/sim_console.py --mode buddy            # assistant | buddy | hub | full (default)
    python tools/sim_console.py --attach 8000           # use a robot/simulation that is already running
    python tools/sim_console.py --open                  # also open the dashboard in the browser
    python tools/sim_console.py --run "turn left; :voice do a dance; :lift on"     # run, print, exit
    python tools/sim_console.py --script tools/sim_scenarios/smoke.txt            # scenario with checks (exit 1 on a fail)

At the prompt (anything not starting with ':' is typed to the robot, like the dashboard's text box):
    turn left 90                 typed text -> brain -> reply + movement
    :voice spin around twice     the PC's text-to-speech says it into a WAV -> speech to text -> brain
                                 (the whole voice pipeline, no microphone needed)
    :mic 4                       record 4 s from this PC's microphone -> speech to text -> brain
    :wav clip.wav                send a WAV file through speech to text
    :wake turn on the lamp       "Hey Pip, ..." wake-word path (full mode)
    :do turn_left 45             run a robot command directly (no AI): move_forward 1, spin 2, dance, stop, ...
    :cli help guard              run `python main.py help guard` (any main.py command; long-running ones: Ctrl+C)
    :lift on|off  :phone on|off  :stuck left|right|none  :shuffle  :gesture Thumb_Up  :notify Mum: call me
    :touch top [1.5]             (pro) pat a touch pad (top | left | right), optionally held for 1.5 s
    :imu knock                   (pro) an IMU event: knock | double_knock | bump | shake | tipped | righted | drop
    :profile Pirate              (pro) switch the personality + voice profile
    :state  :log 5  :stop  :open  :wait 2
    :get /api/full   :post /api/sim/lift {"lifted": true}          raw API calls
    expect left                  (scripts) the last reply must contain "left"; "a|b" = either; exit 1 if not
    :help  :quit

Several commands can go on one line, separated by ';'. Needs only the standard library (the server needs the
project's packages). Details: docs/sim-console.md
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "run_prototype"
MODES = ("assistant", "buddy", "hub", "full", "pro")
GESTURES = ("Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Down", "Thumb_Up", "Victory", "ILoveYou")
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text, code):
    """Colour (on a terminal), and plain ASCII in place of symbols the console's code page can't show."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        for u, a in (("✓", "OK"), ("✗", "FAIL"), ("●", "*"), ("…", "...")):
            text = text.replace(u, a)
        text = text.encode(enc, "replace").decode(enc, "replace")
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


# ---------------- HTTP ----------------

class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def call(self, method, path, body=None, raw=None, ctype="application/json", headers=None, timeout=90):
        data = raw if raw is not None else (json.dumps(body or {}).encode() if method == "POST" else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        try:
            return status, json.loads(payload or b"{}")
        except json.JSONDecodeError:
            return status, {"raw": payload[:200].decode("utf-8", "replace")}

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body, **kw)

    def up(self):
        try:
            return self.get("/api/assistant", timeout=3)[0] == 200
        except OSError:
            return False


# ---------------- the simulated robot ----------------

class Server:
    """`python main.py <mode> --sim` as a child process; its output goes to a log file."""

    def __init__(self, mode, port):
        self.mode, self.port = mode, port
        self.log_path = Path(tempfile.gettempdir()) / f"deskbot_sim_{mode}_{port}.log"
        self.proc = None

    def start(self, api, timeout=180):
        cmd = [sys.executable, "main.py", self.mode, "--sim", "--port", str(self.port), "--https-port", "0"]
        if self.mode == "assistant":
            cmd = [sys.executable, "-m", "deskbot", "assistant", "--sim", "--port", str(self.port), "--https-port", "0"]
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        self._log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        print(c(f"Starting the simulated robot: {' '.join(cmd[1:])}  (log: {self.log_path})", "2"))
        self.proc = subprocess.Popen(cmd, cwd=PROTO, stdout=self._log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, env=env, **kw)
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.proc.poll() is not None:
                self._log.flush()
                tail = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
                raise SystemExit("The simulation stopped while starting:\n  " + "\n  ".join(tail))
            if api.up():
                print(c(f"Ready in {time.monotonic() - t0:.0f} s: {api.base}", "32"))
                return
            time.sleep(0.5)
        self.stop()
        raise SystemExit(f"The simulation didn't answer within {timeout} s. See {self.log_path}")

    def stop(self):
        if self.proc is None or self.proc.poll() is not None:
            return
        if os.name == "nt":       # the runtime has child processes: kill the whole tree
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True)
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGINT)
                self.proc.wait(8)
            except Exception:
                os.killpg(self.proc.pid, signal.SIGKILL)
        self._log.close()


# ---------------- audio on this PC ----------------

def synth_wav(text) -> bytes:
    """Text -> 16 kHz mono 16-bit WAV with this computer's own voice (SAPI on Windows, espeak-ng elsewhere)."""
    path = Path(tempfile.gettempdir()) / f"deskbot_voice_{os.getpid()}.wav"
    try:
        if os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
                  "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono); "
                  "$s.SetOutputToWaveFile($env:DESKBOT_WAV, $f); $s.Speak($env:DESKBOT_TEXT); $s.Dispose()")
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True, timeout=30,
                           capture_output=True, env={**os.environ, "DESKBOT_WAV": str(path), "DESKBOT_TEXT": text})
        else:
            tts = shutil.which("espeak-ng") or shutil.which("espeak")
            if not tts:
                raise RuntimeError("no text-to-speech here: sudo apt install espeak-ng")
            subprocess.run([tts, "-w", str(path), text], check=True, timeout=30, capture_output=True)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def to_16k_mono(wav: bytes) -> bytes:
    """Any 16-bit PCM WAV -> 16 kHz mono 16-bit (what the robot's speech to text expects). Stdlib only:
    channels are averaged, then each output sample is the mean of the input samples it covers (a box filter,
    the same anti-aliasing the dashboard's browser recorder uses)."""
    import array
    import io
    import wave
    with wave.open(io.BytesIO(wav)) as w:
        rate, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise RuntimeError(f"the microphone gave {8 * width}-bit audio, 16-bit is needed")
    if rate == 16000 and ch == 1:
        return wav
    x = array.array("h", raw)
    if sys.byteorder == "big":
        x.byteswap()
    mono = [sum(x[i:i + ch]) / ch for i in range(0, len(x) - ch + 1, ch)] if ch > 1 else list(x)
    step = rate / 16000.0
    out = array.array("h")
    for k in range(int(len(mono) / step)):
        a, b = int(k * step), max(int((k + 1) * step), int(k * step) + 1)
        seg = mono[a:b]
        out.append(max(-32768, min(32767, int(round(sum(seg) / len(seg))))))
    if sys.byteorder == "big":
        out.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(out.tobytes())
    return buf.getvalue()


def record_mic(seconds) -> bytes:
    """Record from this computer's default microphone (Windows: winmm/MCI, no packages; Linux: arecord)."""
    path = Path(tempfile.gettempdir()) / f"deskbot_mic_{os.getpid()}.wav"
    try:
        if os.name == "nt":
            import ctypes
            mci = ctypes.windll.winmm.mciSendStringW
            err = ctypes.create_unicode_buffer(256)

            def send(cmd):
                code = mci(cmd, None, 0, None)
                if code:
                    ctypes.windll.winmm.mciGetErrorStringW(code, err, 256)
                    raise RuntimeError(f"microphone: {err.value} ({cmd.split()[0]})")

            if not ctypes.windll.winmm.waveInGetNumDevs():
                raise RuntimeError("no microphone found (Settings > System > Sound > Input)")
            # many laptop mics only take their native format, so try 16 kHz mono first, then the usual ones
            last_error = None
            for rate, ch in ((16000, 1), (48000, 2), (48000, 1), (44100, 2), (44100, 1)):
                send("open new type waveaudio alias deskbotmic")
                try:
                    send(f"set deskbotmic bitspersample 16 samplespersec {rate} channels {ch}")
                    send("record deskbotmic")
                except RuntimeError as exc:
                    last_error = exc
                    mci("close deskbotmic", None, 0, None)
                    continue
                try:
                    countdown(seconds)
                    send("stop deskbotmic")
                    send(f'save deskbotmic "{path}"')
                finally:
                    mci("close deskbotmic", None, 0, None)
                return to_16k_mono(path.read_bytes())
            raise last_error
        else:
            if not shutil.which("arecord"):
                raise RuntimeError("arecord missing: sudo apt install alsa-utils")
            p = subprocess.Popen(["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(int(round(seconds))),
                                  str(path)])
            countdown(seconds)
            p.wait(5)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def countdown(seconds):
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        print(c(f"\r  ● recording… {left:4.1f} s  (talk now)", "31"), end="", flush=True)
        time.sleep(min(0.1, left))
    print("\r" + " " * 40 + "\r", end="", flush=True)


# ---------------- the console ----------------

class Console:
    def __init__(self, api, mode):
        self.api, self.mode = api, mode
        self.seen = self._last_id()
        self.last_reply = ""
        self.last_moves = set()        # actions of the last reply + anything the executor ran since
        self.move_t = self._move_t()
        self.failures = []

    # -- output --

    def _log(self):
        status, s = self.api.get("/api/assistant")
        return s.get("assistant", {}).get("log", []) if status == 200 else []

    def _move_t(self):
        status, s = self.api.get("/api/assistant")
        return ((s.get("executor") or {}).get("last") or {}).get("t", 0) if status == 200 else 0

    def _new_moves(self):
        """Movements started outside a conversation turn (gestures, :do, lift, routines) are printed too."""
        status, s = self.api.get("/api/assistant")
        last = (s.get("executor") or {}).get("last") or {} if status == 200 else {}
        if not last or last.get("t", 0) <= self.move_t:
            return False
        self.move_t = last["t"]
        if last.get("source") in ("ai",):
            return False                     # already printed with the reply
        acts = last.get("commands") or []
        self.last_moves |= {str(x.get("action")).lower() for x in acts}
        desc = ", ".join(f"{x.get('action')} {x.get('amount') or ''}".strip() + f" ({x.get('result', '?')})" for x in acts)
        print(c(f"  robot moved ({last.get('source')}): ", "35") + desc)
        return True

    def _last_id(self):
        log = self._log()
        return log[-1]["id"] if log else 0

    def show_turn(self, e):
        self.seen = max(self.seen, e["id"])
        heard = e.get("user")
        if heard is not None and e.get("source") not in ("typed", "sim console"):
            print(c(f"  heard ({e.get('source')}): ", "36") + heard)
        speech = e.get("speech") or ""
        self.last_reply = speech
        tag = e.get("backend") or "?"
        ms = e.get("ms")
        stt = f", speech-to-text {e['stt_ms']} ms" if e.get("stt_ms") else ""
        print(c("  Pip: ", "1;33") + speech + c(f"   [{e.get('mood')}, {tag}, {ms} ms{stt}]", "2"))
        cmds = e.get("commands") or []
        self.last_moves = {str(x.get("action")).lower() for x in cmds}
        if cmds:
            desc = ", ".join(f"{x.get('action')}{'' if x.get('amount') in (None, 0) else ' ' + str(x.get('amount'))}"
                             for x in cmds)
            print(c("  moves: ", "35") + desc + ("" if e.get("executed", True) else c("  (not executed)", "31")))
        for p in e.get("problems") or []:
            print(c(f"  problem: {p}", "31"))
        if e.get("error") and e.get("backend") == "system":
            print(c(f"  error: {e['error']}", "31"))

    def drain(self, wait=0.0, quiet_after=1.5):
        """Print turns that appeared since the last one shown. With wait > 0, keep watching up to `wait` seconds
        (for things that answer in the background: wake word, gestures, notifications)."""
        t_end = time.monotonic() + wait
        t_quiet = None
        while True:
            new = [e for e in self._log() if e["id"] > self.seen]
            for e in new:
                self.show_turn(e)
            moved = self._new_moves()
            if new or moved:
                t_quiet = time.monotonic() + quiet_after
            now = time.monotonic()
            if now >= t_end or (t_quiet and now >= t_quiet):
                return
            time.sleep(0.3)

    def result(self, status, body, ok_text=None):
        if status >= 400:
            print(c(f"  HTTP {status}: {body.get('error', body)}", "31"))
            return False
        if ok_text:
            print(c(f"  {ok_text}", "32"))
        return True

    # -- commands --

    def run_line(self, line):
        for part in split_commands(line):
            if self.run_one(part) == "quit":
                return "quit"

    def run_one(self, cmd):
        cmd = cmd.strip()
        if not cmd or cmd.startswith("#"):
            return
        if cmd.lower().startswith("expect "):
            return self.expect(cmd[7:].strip())
        if not cmd.startswith(":"):
            return self.say_text(cmd)
        name, _, arg = cmd[1:].partition(" ")
        name, arg = name.lower(), arg.strip()
        fn = getattr(self, f"cmd_{name}", None)
        if fn is None:
            print(c(f"  unknown command :{name} (try :help)", "31"))
            return
        try:
            return fn(arg)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            print(c(f"  {type(exc).__name__}: {exc}", "31"))

    def say_text(self, text):
        self.drain()
        status, body = self.api.post("/api/assistant/text", {"text": text, "source": "sim console"})
        if self.result(status, body):
            self.drain()

    def send_audio(self, wav, source):
        self.drain()
        status, body = self.api.post("/api/assistant/audio", raw=wav, ctype="audio/wav", headers={"X-Source": source})
        if self.result(status, body):
            self.drain()

    def expect(self, wanted):
        if wanted.lower().startswith("move "):
            return self.expect_move(wanted[5:].strip())
        options = [w.strip().lower() for w in wanted.split("|") if w.strip()]
        got = (self.last_reply or "").lower()
        if any(o in got for o in options):
            print(c(f"  ✓ expect {wanted}", "32"))
        else:
            print(c(f"  ✗ expect {wanted}  (last reply: {self.last_reply!r})", "1;31"))
            self.failures.append((wanted, self.last_reply))

    def expect_move(self, wanted):
        options = [w.strip().lower() for w in wanted.split("|") if w.strip()]
        if any(o in self.last_moves for o in options):
            print(c(f"  ✓ expect move {wanted}", "32"))
        else:
            print(c(f"  ✗ expect move {wanted}  (last moves: {sorted(self.last_moves) or 'none'})", "1;31"))
            self.failures.append(("move " + wanted, sorted(self.last_moves)))

    def cmd_voice(self, arg):
        if not arg:
            raise ValueError("usage: :voice <what to say>")
        self.send_audio(synth_wav(arg), "sim voice")

    def cmd_mic(self, arg):
        self.send_audio(record_mic(float(arg or 4)), "pc mic")

    def cmd_wav(self, arg):
        self.send_audio(Path(arg.strip('"')).read_bytes(), "wav file")

    def cmd_wake(self, arg):
        if self.result(*self.api.post("/api/full/wake", {"text": arg or "hello"}), "wake word triggered"):
            self.drain(wait=20)

    def cmd_do(self, arg):
        parts = arg.split()
        if not parts:
            raise ValueError("usage: :do <action> [amount]   e.g. :do turn_left 45")
        command = {"action": parts[0]}
        if len(parts) > 1:
            command["amount"] = float(parts[1])
        status, body = self.api.post("/api/assistant/commands", {"commands": [command], "source": "sim console"})
        self.last_moves = set()
        self.result(status, body, "accepted" if body.get("accepted") else None)
        for p in body.get("problems") or []:
            print(c(f"  problem: {p}", "31"))
        self.drain(wait=4)

    def cmd_cli(self, arg):
        args = shlex.split(arg, posix=os.name != "nt")
        print(c(f"  $ python main.py {arg}", "2"), flush=True)
        try:
            subprocess.run([sys.executable, "main.py", *args], cwd=PROTO)
        except KeyboardInterrupt:
            print()

    def _onoff(self, arg):
        if arg.lower() not in ("on", "off"):
            raise ValueError("say on or off")
        return arg.lower() == "on"

    def cmd_lift(self, arg):
        self.result(*self.api.post("/api/sim/lift", {"lifted": self._onoff(arg)}), f"lifted: {arg}")
        self.drain(wait=3)

    def cmd_phone(self, arg):
        self.result(*self.api.post("/api/sim/phone", {"present": self._onoff(arg)}), f"phone nearby: {arg}")
        self.drain(wait=3)

    def cmd_stuck(self, arg):
        self.result(*self.api.post("/api/sim/wheel", {"stuck": arg or "none"}), f"stuck wheel: {arg or 'none'}")

    def cmd_shuffle(self, arg):
        self.result(*self.api.post("/api/sim/shuffle", {"label": arg or "Mug"}), "moved an object on the desk")

    def cmd_gesture(self, arg):
        name = next((g for g in GESTURES if g.lower() == arg.lower().replace(" ", "_")), None)
        if name is None:
            raise ValueError("gestures: " + ", ".join(GESTURES))
        if self.result(*self.api.post("/api/sim/gesture", {"gesture": name}), f"showed {name}"):
            self.drain(wait=5)

    def cmd_notify(self, arg):
        app, _, text = arg.partition(":") if ":" in arg else ("Messages", "", arg)
        body = {"app": app.strip() or "Messages", "title": app.strip(), "text": text.strip() or arg}
        if self.result(*self.api.post("/api/buddy/notifications/test", body), "phone notification sent"):
            self.drain(wait=8)

    def cmd_touch(self, arg):
        """:touch top [seconds]  one pad;  :touch left top right  several quick pats in a row (a stroke / pat streak)."""
        parts = arg.split()
        if not parts:
            raise ValueError("usage: :touch top|left|right [seconds]   or   :touch left top right")
        try:
            pads, hold = parts[:1], float(parts[1]) if len(parts) > 1 else 0.15
        except ValueError:
            pads, hold = parts, 0.15
        for i, pad in enumerate(pads):
            if not self.result(*self.api.post("/api/pro/touch/test", {"pad": pad, "hold_s": hold})):
                return
            time.sleep(hold + (0.25 if i < len(pads) - 1 else 0.4))
        print(c(f"  touched {' -> '.join(pads)}", "32"))
        self._show_pro("touch")
        self.drain(wait=4)

    def cmd_imu(self, arg):
        status, body = self.api.post("/api/pro/motion/test", {"event": arg or "knock"})
        if self.result(status, body, f"detected: {', '.join(body.get('events') or []) or 'nothing'}"):
            self.drain(wait=4)

    def cmd_profile(self, arg):
        status, body = self.api.post("/api/pro/profiles", {"apply": arg})
        self.result(status, body, f"profile: {body.get('active')}")

    def _show_pro(self, part):
        status, s = self.api.get("/api/pro")
        if status == 200:
            ev = [e for e in s[part]["events"] if e["kind"] != "touch" and e["t"] > getattr(self, "_pro_seen", 0)]
            if ev:
                self._pro_seen = ev[0]["t"]
                self.last_reply = " ".join(e["kind"] for e in ev)
                print(c(f"  {part}: " + ", ".join(e["kind"] + (f" ({e['pad']})" if e.get("pad") else "") for e in ev[::-1]), "36"))

    def cmd_stop(self, arg):
        self.result(*self.api.post("/api/assistant/stop", {}), "stopped")

    def cmd_state(self, arg):
        status, s = self.api.get("/api/assistant")
        if status != 200:
            return self.result(status, s)
        ex = s.get("executor") or {}
        pres = s.get("presence") or {}
        lift = s.get("lift") or {}
        stt = s.get("stt") or {}
        brain = s.get("brain") or {}
        last = ex.get("last") or {}
        moves = ", ".join(f"{x.get('action')} ({x.get('result', '?')})" for x in last.get("commands") or []) or "-"
        print(f"  phase: {s['assistant']['phase']}   moving: {ex.get('current') or '-'}   "
              f"last move: {moves}" + (f" from {last['source']}" if last.get("source") else ""))
        print(f"  awake: {pres.get('awake')}   phone near: {(pres.get('source') or {}).get('present')}   "
              f"lifted: {lift.get('lifted')}")
        print(f"  speech to text: {stt.get('preference')} -> available {stt.get('available')}")
        print(f"  brain: {brain.get('backend')}" + (f"  ({brain['why_offline']})" if brain.get("why_offline") else ""))
        alerts = (s.get("alerts") or {}).get("active") or []
        for a in alerts[:5]:
            print(c(f"  alert: {a.get('msg')}  {a.get('detail') or ''}", "33"))

    def cmd_log(self, arg):
        for e in self._log()[-int(arg or 5):]:
            print(c(f"  #{e['id']} {e.get('source')}: ", "2") + f"{e.get('user')!r} -> {e.get('speech')!r}")

    def cmd_get(self, arg):
        status, body = self.api.get(arg or "/api/assistant")
        print(f"  HTTP {status}\n" + json.dumps(body, indent=2)[:4000])

    def cmd_post(self, arg):
        path, _, raw = arg.partition(" ")
        status, body = self.api.post(path, json.loads(raw or "{}"))
        print(f"  HTTP {status}\n" + json.dumps(body, indent=2)[:4000])
        self.drain(wait=2)

    def cmd_open(self, arg):
        webbrowser.open(self.api.base)

    def cmd_wait(self, arg):
        self.drain(wait=float(arg or 1), quiet_after=1e9)

    def cmd_help(self, arg):
        print(__doc__.split("At the prompt", 1)[1].split("Several commands", 1)[0].rstrip())

    def cmd_quit(self, arg):
        return "quit"

    cmd_exit = cmd_q = cmd_quit

    # -- loops --

    def repl(self):
        print(c(f"Talk to Pip ({self.mode}, simulated). Type a sentence, or :help. Ctrl+D or :quit to leave.", "1"))
        while True:
            try:
                line = input(c("you> ", "1;34"))
            except EOFError:
                print()
                return
            except KeyboardInterrupt:
                print()
                continue
            try:
                if self.run_line(line) == "quit":
                    return
            except KeyboardInterrupt:
                print(c("  (interrupted)", "2"))


def split_commands(line):
    """Split on ';' except inside a :post JSON body."""
    if line.lstrip().startswith(":post"):
        return [line]
    return [p for p in line.split(";")]


def free_port(start):
    import socket
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free port")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Try the desk robot's features in simulation from one terminal.")
    ap.add_argument("--mode", choices=MODES, default="full", help="which runtime to start (default full)")
    ap.add_argument("--port", type=int, default=8150, help="port for the started simulation (default 8150)")
    ap.add_argument("--attach", metavar="PORT_OR_URL", help="use a running robot/simulation instead of starting one")
    ap.add_argument("--run", metavar="COMMANDS", help="run these ';'-separated commands, then exit")
    ap.add_argument("--script", metavar="FILE", help="run a scenario file (one command per line), then exit")
    ap.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    ap.add_argument("--keep", action="store_true", help="leave the started simulation running when the console exits")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if os.name == "nt":
        os.system("")            # turn on ANSI colours in the Windows console

    server = None
    if args.attach:
        base = args.attach if "://" in args.attach else f"http://127.0.0.1:{args.attach}"
        api = Api(base)
        if not api.up():
            raise SystemExit(f"Nothing answers at {base}/api/assistant (it needs the assistant, buddy, hub or full runtime).")
    else:
        port = free_port(args.port)
        api = Api(f"http://127.0.0.1:{port}")
        server = Server(args.mode, port)
        server.start(api)
    try:
        con = Console(api, args.mode if server else "attached")
        if args.open:
            con.cmd_open("")
        if args.script or args.run:
            lines = Path(args.script).read_text(encoding="utf-8").splitlines() if args.script else [args.run]
            for line in lines:
                if line.strip() and not line.lstrip().startswith("#"):
                    print(c(f"you> {line}", "1;34"))
                if con.run_line(line) == "quit":
                    break
            if con.failures:
                print(c(f"{len(con.failures)} expectation(s) failed.", "1;31"))
                return 1
            print(c("All expectations passed." if args.script else "Done.", "32"))
            return 0
        con.repl()
        return 0
    finally:
        if server and not args.keep:
            print(c("Stopping the simulation…", "2"))
            server.stop()
        elif server:
            print(f"Still running: {api.base}  (log: {server.log_path})")


if __name__ == "__main__":
    sys.exit(main())
