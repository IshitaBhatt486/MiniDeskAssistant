# Voice assistant, AI brain, remote and warnings (17 Nov 2026)

`python -m deskbot assistant` (= `scripts/assistant.sh`) runs the 4-process robot from [runtime.md](runtime.md)
**plus**: speech → text → AI (with what the camera sees and a personality you set) → a JSON reply holding speech
and commands → a chipmunk voice on the speaker and the robot's actions. It also adds a phone remote, Bluetooth
presence ([presence.md](presence.md)), lift detection, live mapping while moving, and spoken warnings for every
failure. The older entry points (`deskbot run`, `--single-process`, `dashboard/*`, `3Nov-latest.py`) are unchanged.
`deskbot/runtime/app.py` only gained two optional hooks (`mapper_cls`, `setup`) that default to the old behaviour.

| | |
| --- | --- |
| Start | `scripts/assistant.sh` (Pi, listens on the LAN) · `scripts/assistant.sh --sim` (anywhere) · menu: `scripts/deskbot.sh` → 🗣 |
| Code | `deskbot/assistant/`: `app.py` (routes, wiring), `core.py` (pipeline), `brain.py` (Claude + offline), `tools.py` (free APIs), `commands.py` (vocabulary + executor), `stt.py`, `voice.py` (TTS + chipmunk + speaker), `alerts.py`, `health.py`, `settings.py` · `deskbot/mapping/live.py` · `deskbot/web/tls.py` · `deskbot/web/static/assistant*.{html,js,css}`, `remote.{html,js}`, `voice-recorder.js` |
| Secrets | `secrets.env` (copy `secrets.env.example`): `ANTHROPIC_API_KEY`, `GROQ_API_KEY` (or `OPENAI_API_KEY`) |
| Settings | dashboard → *Personality & voice*, saved in `data/assistant.json` |
| Tests | `tests/test_assistant.py` (22 tests, no network/keys/hardware) |
| Deploy | [deploy.md](deploy.md): copy to the Pi, hotspot, start on boot |

## 1. Pipeline

```
 laptop/phone mic ─(browser, 16 kHz WAV)─┐
 robot USB mic ───(arecord 16 kHz WAV)───┼─▶ stt.Transcriber ─┐
 typed text (dashboard / remote) ────────┼────────────────────┼─▶ core.Assistant._turn
                                         │                    │      │ context(): time, sonar, IR, lifted?, phone near?,
                                         │                    │      │   camera detections (label, %, bearing, sonar range),
                                         │                    │      │   objects remembered on the map (distance + bearing)
                                         │                    │      │ + camera JPEG (320×240) + personality
                                         │                    │      ▼
                                         │                    │   brain.Brain ── Claude (tools: weather, time, Wikipedia,
                                         │                    │      │            jokes, currency, robot_status)
                                         │                    │      │   └─ fails → OfflineBrain (keyword rules)
                                         │                    │      ▼
                                         │                    │   {"speech", "mood", "commands": [{"action","amount"}]}
                                         │                    │      ├─▶ conversation log  → dashboard / remote
                                         │                    │      ├─▶ voice.Speaker     → TTS → chipmunk → speaker
                                         │                    │      └─▶ commands.Executor → RobotProxy.move (all safety rules)
```

One turn runs at a time. A second request while it's thinking gets HTTP 409 "I'm still answering". Talking to a
sleeping robot wakes it.

## 2. The JSON contract (`commands.py`)

The reply is forced into this schema with **structured outputs** (`output_config.format`, JSON schema), so it
always parses:

```json
{"speech": "Wheee! One spin coming up.", "mood": "excited", "sound": "whoosh",
 "commands": [{"action": "spin", "amount": 1, "from_object": "", "to_object": ""}]}
```

**`sound` (19 Nov 2026)** is a sound effect played just before the speech, or `"none"` (most replies). It must be one
of `commands.SOUNDS`: `tada, ding, pop, boing, whoosh, giggle, rimshot, drumroll, sad_trombone, beep_boop, fanfare,
notification, reminder, gasp, yawn`. The list with a one-line meaning for each is in the system prompt, so the model
knows when each fits. `Brain.think` turns anything else into `"none"`; `core.py` queues `speaker.chime(sound)` and then
the speech on the same speaker queue, so they always play in that order. The sounds are synthesised in `motifs.py`
(plucked notes, pitch glides, noise bursts; numpy only, no files), cached after the first use (all 15 take about 0.6 s
the first time on the laptop). The offline brain also picks a few (spin → whoosh, hello → beep_boop, joke → giggle,
good night → yawn, wake up → ding). The `sounds` setting switches them off together with the state motifs.

| action | amount (clamped) | does |
| --- | --- | --- |
| `move_forward` / `move_backward` | 0.2–3 s (default 1) | drive |
| `turn_left` / `turn_right` | 5–360° (default 90) | turn in place; seconds = rad ÷ `turn_rate(speed)` (odometry calibration) |
| `spin` | 1–3 turns | 360° × n left |
| `dance` | – | fwd 0.25, back 0.25, left 0.2, right 0.4, left 0.2 s (the "excitement" idea in `notes.txt`) |
| `look_around` | – | 8 × 45° with 0.6 s pauses so the camera gets sharp frames for the map |
| `stop` | – | stop now |
| `face_user` / `follow_user_on` / `follow_user_off` | – | turn to the person once / face-the-user behaviour on/off |
| `find_phone` | – | [presence.md](presence.md) §3 |
| `sleep` / `wake` | – | [presence.md](presence.md) §2 |
| `reset_map` | – | new map, pose back to (0, 0) |
| `set_speed` | 10–100 % | drive speed |
| `celebrate` | – | one of 4 victory routines at random (spin, wiggle, hop, twist), each ends where it started (19 Nov 2026) |
| `nudge` | – | a small attention wiggle: 12° left, 24° right, 12° left (reminders) |

- `normalise()` drops unknown actions, clamps amounts, turns 0/NaN into the default, and keeps at most **5**
  commands. Problems are shown as red chips under the reply.
- The executor runs them in order on a worker thread. Each one waits until the motor process reports idle (polling
  `snapshot()["state"]` every 50 ms, 15 s timeout). A **safety stop** (edge, obstacle, stale sensors) aborts the rest
  of the sequence, and the reason is spoken ("I stopped. Front edge detected."). A new command list, `Stop all`,
  the remote D-pad, falling asleep or being lifted all cancel the running sequence.
- Moves go through `RobotProxy.move` like dashboard moves, so every motor-process safety rule applies unchanged.
  Moves longer than `MAX_DURATION` (10 s) are split.
- **Passing the JSON on.** `POST /api/assistant/commands {"commands": [...]}` runs the same JSON from any program on the
  LAN. `Executor.on_command(fn)` lets your own code see each command first, or veto it by returning `False`. To add an
  action, add it to `ACTIONS` (the schema and the system prompt are built from it) and add a branch in `Executor._do`.

## 3. Brain (`brain.py`)

**Claude** (over plain HTTPS since 20 Nov 2026: `claude_http.py`, the same `client.beta.messages.create` call the `anthropic` SDK had, see [slim-dependencies.md](slim-dependencies.md)):

| Setting | Value | Why |
| --- | --- | --- |
| model | `claude-opus-5-5` (setting `model`) | the default; change it on the settings file if you like |
| effort | `low` (setting `effort`) | a voice assistant must answer in a couple of seconds; Opus 5.5 can't turn thinking off, effort is the control |
| tools | `tools.TOOL_SPECS`, `strict: true` | tool inputs always match the schema |
| output | `output_config.format` = `RESPONSE_SCHEMA` | the final answer is always valid JSON |
| fallbacks | `"default"` + beta `server-side-fallback-2026-07-01` | if the model declines a request for policy reasons, the API retries on its default fallback model in the same call |
| caching | top-level `cache_control: ephemeral` | system prompt + tools are identical every turn → cached; the per-turn context goes in the user message |
| history | last 6 exchanges (text only) | follow-up questions work ("and tomorrow?") |
| image | camera JPEG when *Send camera image* is on | a 320×240 frame is roughly 100–200 tokens |
| retries | SDK `max_retries=1`, `timeout=40` | a late answer is useless; the offline brain answers instead |

Tool loop: at most 4 rounds. Every `tool_result` of a round goes back in **one** user message. A tool that fails returns
`is_error: true` with the reason, so Claude can say "I couldn't get the weather". `stop_reason` handling:
`refusal` → "Sorry, I can't help with that one."; `max_tokens` → treated as an error; `tool_use` → run the tools.

**Offline brain** (no key, SDK missing, no internet, API error): regex intents for stop / move / turn (numbers in
words or digits) / spin / dance / look around / face me / follow me / find phone / sleep / wake / reset map / speed,
plus weather / time / joke / Wikipedia ("who is …") / "what do you see" through the same tools. It doesn't use the
personality. Every Claude failure is classified (`AuthenticationError` → "my AI key was rejected", `RateLimitError`,
`APIConnectionError` → "I can't reach the internet", …), spoken once, and the offline brain answers the same turn.

**Free APIs** (`tools.py`, no keys, generic User-Agent `deskbot/1.0`, 6 s timeout): Open-Meteo geocoding + forecast
(current + 3 days + sunrise/sunset; the city defaults to *Home city*, then the IP location via ipapi.co),
Wikipedia opensearch + REST summary, Official Joke API, open.er-api.com exchange rates (cached 1 h), and local
`get_time` / `robot_status`.

## 4. Speech to text (`stt.py`)

| Backend | Needs | Speed (5 s clip) |
| --- | --- | --- |
| `groq` | `GROQ_API_KEY` (free tier) | ~0.3–0.6 s, Whisper large-v3-turbo |
| `openai` | `OPENAI_API_KEY` | ~1 s, whisper-1 |
| `local` | `pip install pywhispercpp` (whisper.cpp, since 20 Nov 2026; faster-whisper still works if that's what is installed) | tiny.en, 8-bit (`tiny.en-q8_0`, 44 MB, downloaded once into `models/whisper/`). Not yet timed on the Pi; faster-whisper took ~1–2 s |
| `windows` | Windows 10/11 (laptop simulation only, 20 Nov 2026) | ~2–3 s, offline `System.Speech` dictation via PowerShell; tried last, also allowed in strict `local`. See [sim-console.md](sim-console.md) |

`auto` tries them in that order and falls back to the next one on an error. A clip under 0.3 s, over 30 s, or
**quieter than −50 dBFS** peak is rejected *before* any API call ("I didn't hear anything. Is the microphone muted?").
Uploads are multipart, built with `urllib` (no extra packages).

**Browser microphone** (`voice-recorder.js`): `getUserMedia` (echo cancellation, noise suppression, AGC) → a
ScriptProcessor collects Float32 → box-filter downsample to 16 kHz → 16-bit WAV → `POST /api/assistant/audio`
(`Content-Type: audio/wav`, ≤ 2 MB, stops at 25 s). WAV (not MediaRecorder's webm/mp4) because every backend,
including whisper.cpp (read with Python's `wave` module), reads it without ffmpeg.
**Browsers only allow the mic on HTTPS or `localhost`**, so the server also serves the same pages on
**`https://<robot>:8443`** with a self-signed certificate (`web/tls.py`, made once with `openssl`, SANs = hostname,
hostname.local, the LAN IP and 10.42.0.1 (hotspot), regenerated when a new address appears). Accept the warning
once per device. On plain `http://<ip>:8000` the dashboard shows a link to the HTTPS page.
Your laptop's mic: open `https://<pi>:8443` on the laptop and hold *Hold to talk* (or Space/Enter on the button).
The robot's own USB mic: *Robot mic (5 s)* → `arecord` 16 kHz (device: `DESKBOT_MIC_DEVICE` or the first capture card).

## 5. Voice (`voice.py`)

TTS engine, the first one found: **piper** (`piper` on PATH + `models/piper/*.onnx`, natural voice) → **espeak-ng**
(installed by `setup.sh`) → espeak → **Windows SAPI** (simulation on the laptop). Then:

- **Chipmunk**: resample to 1/f of the length with `np.interp` and play at the same rate. Every frequency is ×f and
  the duration ÷f. Default f = 1.6 (300 Hz → 480 Hz, checked in the tests). Range 1.0–2.5. Above ~2 it gets hard
  to understand.
- Normalise the peak to 0.95, then × volume.
- Play with `aplay` (`DESKBOT_AUDIO_DEVICE=plughw:1,0` for a USB card), else `pw-play` / `paplay` / `ffplay`; `winsound` on Windows.
- One worker thread, queue of 6 (oldest dropped). Kinds: `reply` (respects *Speak replies*), `alert` (respects *Speak
  warnings*), `chatter` (greetings, find-phone progress). `Stop all` empties the queue and kills `aplay`.
- The newest reply's WAV is kept, so the remote can play it on the phone (*Play replies on this phone*).
- Strips markdown, emoji and URLs before speaking. Speaker failures are shown on the dashboard but never spoken (there's no voice to speak them with).

## 6. Failures never stop the robot (`alerts.py`, `health.py`)

Every part reports to one `Alerts` hub instead of raising: `warn/error(key, message)`, `resolve(key, "back to normal")`,
`guard(...)` (a context manager that turns an exception into an alert) and `call(fn, fallback=...)`. Each alert is
logged to the terminal and the event log, shown on the **Warnings** card and the remote, and **spoken**. The same key
is spoken at most once a minute, with at least 4 s between any two spoken alerts, so a flapping sensor can't spam
the speaker.

`Health` checks every 2 s:

| Check | Message (spoken) |
| --- | --- |
| motor / sensors / camera process died | "My motor process stopped, so I can't drive…" (the motor process already stops itself on stale data) |
| newest sensor sample > 1 s old | "My sensors stopped updating, so I won't drive." |
| camera failed / not ready after 90 s | "My camera isn't working. I can still map with my sonars." |
| CPU > 80 °C | "I'm getting hot…" |
| `vcgencmd get_throttled` bit 0 (under-voltage) | "My power supply is too weak…" |
| internet (only with the Claude brain, every 60 s) | "I lost my internet connection. I'll use simple mode." |

Plus, where they happen: missing API key (start-up), speech-to-text down (with fallback), AI errors (→ offline), a
tool error (→ Claude explains), a missing TTS engine or player, Bluetooth errors (the scanner retries every 20 s),
HTTPS not starting (typing still works), a corrupt settings file (→ defaults), a command that fails (the rest is
skipped), and any unexpected error in an HTTP handler (JSON 500, the server keeps running). Each one gets a
"back to normal" message when it clears.

## 7. Dashboard and remote

- **Assistant** card (first, 2×2): mood face (happy / excited / curious / sleepy / sad / confused; the eyes move
  while thinking), backend tags (brain, speech, voice), *Hold to talk*, *Robot mic*, the conversation (your words,
  the reply, tool chips, command chips, raw JSON under *JSON*), a text box, *Stop all*.
- **Presence** card ([presence.md](presence.md)), **Personality & voice** (presets: Cheerful helper, Sarcastic
  sidekick, Calm butler, Pirate; or write your own; name, home city, switches, chipmunk amount, volume, *Test voice*;
  whether each API key is set, never the key itself), **Warnings** (active + recent).
- **`/remote`**: a phone-sized page with a mood face, the last reply, a **hold-to-drive D-pad** (`POST /api/drive`
  re-sent every 250 ms; each one is a 0.5 s move, newest wins, so losing Wi-Fi mid-drive stops within 0.5 s; logged
  once per press), STOP (motors + commands + speech), hold-to-talk, text, quick actions (spin, dance, look around,
  face me, find phone, sleep/wake), optional playback on the phone, and the top warning.
- Every device on the LAN (or the robot's hotspot) can open both pages. **There is no login**, so use them on trusted
  networks only. Mutating requests need a JSON / `audio/wav` Content-Type (a cross-site form can't send those
  without a CORS preflight, which the server never answers). API keys can't be read or set over HTTP.

API: see the docstring of `deskbot/assistant/app.py` (all routes).

## 8. Live map while moving (`mapping/live.py`)

`LiveFusionMapper` = `FusionMapper` with an adaptive rate: **25 Hz while the motors run**, 10 Hz idle. The sensor
process publishes at 50 Hz, so while driving each update uses a sample at most ~40 ms old, and odometry moves less
than ~1 cm between updates. Sonar cones land where they were measured instead of being smeared. Each new sample is
integrated once, in order (the inherited `step()` skips a sample it has already seen). `paused` (set by the lift
detector) stops updates. On resume, odometry re-anchors instead of integrating the carried motion. In the sim run,
279 of 582 updates happened while moving.

## 9. Verified (laptop, 16 Nov 2026)

- `tests/test_assistant.py` (22 tests): settings validation/persistence/corrupt file; command clamping + schema = action
  list; alert dedupe/cooldown/resolve/guard; chipmunk pitch (300 → 480 Hz) and length (÷1.6); WAV round trip; STT
  silence/short rejection and backend fallback order; **Claude tool loop with a scripted fake client** (tool_use →
  tool_result in one message → final JSON, model/effort/fallbacks/schema/image in the request, cache usage
  summed); refusal; API failure → offline answer + alert; offline intents; BLE tracker hysteresis; iBeacon parsing;
  circular best-heading; lift → pause → reset. Full suite: 75 tests OK.
- `deskbot assistant --sim` end to end over HTTP: text turns, live Open-Meteo weather ("In Delhi it's 20 degrees with
  clear sky"), commands with clamping (`spin 9` → 3) and rejection (`bogus`), settings validation, silent WAV → "I
  didn't hear anything", no STT backend → spoken explanation, `speech.wav` (Windows SAPI + chipmunk), `/remote`,
  HTTPS on 8766, simulated lift (map paused → put down → `map_resets 1`, epoch 1), find my phone (12-heading scan,
  6.8 dB spread, arrived after 1 hop, final heading 212° vs. the true 210° bearing to the phone).
- **Not run with a real API key, and not on the Pi** (espeak-ng/aplay, BlueZ, arecord, NetworkManager). On this
  Windows laptop, Smart App Control blocked the SDK's `jiter` DLL the first time. Since 20 Nov 2026 there is no SDK
  (`claude_http.py` is standard library only), so this can't happen any more.

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| "simple mode" / brain offline | `ANTHROPIC_API_KEY` in `secrets.env`, restart; the brain tag's tooltip says why |
| Mic button shows the HTTPS notice | open `https://<robot>:8443` (accept the certificate) |
| "I can't understand speech yet" | `GROQ_API_KEY` in `secrets.env`, or `.venv/bin/pip install pywhispercpp` |
| No sound | `aplay -l`, set `DESKBOT_AUDIO_DEVICE=plughw:<card>,0` in `secrets.env`; `alsamixer` volume; user in `audio` group |
| Voice tag "voice none" | `sudo apt install espeak-ng` |
| Robot talks too much | turn off *Speak warnings* (they're still listed on the card) |
| Replies slow | effort `low` is the default; check the internet; Groq STT is the fastest |

## Navigation command

`navigate` takes `from_object` and `to_object` instead of an amount ("go from the cup to the bottle"). It works with
Claude and with the offline brain. See [`navigation.md`](navigation.md).

## Keeping API use low

| Setting (`data/assistant.json`) | Default | Effect |
|---|---|---|
| `local_commands` | on | Plain robot commands are parsed on the robot and never reach Claude. Anything that looks like a question or longer thought still goes to Claude |
| `vision_on_demand` | on | A camera frame is attached only when the request needs eyes ("what colour is this?"). Detections always go as text |
| `send_image` | on | Master switch for sending frames at all |
| `stt` | `auto` | `auto` tries local Whisper (whisper.cpp) first if installed, then Groq, then OpenAI |
| `sounds` | on | Short musical motifs (`assistant/motifs.py`) for recognition, navigation, arrival, warning, confusion, low confidence, pick-up, embarrassment |

Speech output is always generated on the device (Piper, eSpeak NG or Windows SAPI).

## Model and on-board answers (18 Nov 2026)

The default model is `claude-haiku-5-5`. It has no server-side refusal fallback, so that option is sent only for models that support it.
`stt: local` never falls back to a cloud service. "What do you see", "what colour is the cup" and "what is this" are answered from the
detector and `vision/describe.py` whenever the object is detected, with no API call. Other visual questions can still attach one image.
