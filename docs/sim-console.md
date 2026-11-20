# Simulation test console (20 Nov 2026)

One terminal for trying every feature without the Pi: typed sentences, **voice input** (synthetic or your own
microphone), the `main.py` CLI, and the simulated robot's events (lifted, phone nearby, stuck wheel, hand gestures,
phone notifications, wake word). It can also run a scenario file with checks, so a change can be smoke-tested in
one command.

```bash
python tools/sim_console.py                      # starts `main.py full --sim` on port 8150, then a prompt
python tools/sim_console.py --open               # ... and opens the dashboard next to it
python tools/sim_console.py --mode buddy         # assistant | buddy | hub | full | pro
python tools/sim_console.py --mode pro --script tools/sim_scenarios/pro.txt   # touch, IMU, profiles
python tools/sim_console.py --attach 8000        # a robot or simulation that is already running (also on the Pi: --attach http://<pi>:8000)
python tools/sim_console.py --run "turn left; :voice do a dance"
python tools/sim_console.py --script tools/sim_scenarios/smoke.txt     # exit code 1 if an expectation fails
```

Run it with the project's Python (`.venv\Scripts\python.exe` on the laptop). The console itself only uses the
standard library. It lives in `tools/` because it never runs on the robot.

## Commands

| at the prompt | what happens | route |
| --- | --- | --- |
| `turn left 90` (anything without `:`) | typed to the robot, like the dashboard's text box | `POST /api/assistant/text` |
| `:voice spin around twice` | this PC's text-to-speech says it into a 16 kHz WAV, which goes through **speech to text** and the brain: the whole voice pipeline, no microphone | `POST /api/assistant/audio` |
| `:mic 4` | records 4 s (default) from this PC's microphone, then the same as `:voice` | `POST /api/assistant/audio` |
| `:wav clip.wav` | sends a WAV file you already have | `POST /api/assistant/audio` |
| `:wake turn on the lamp` | the "Hey Pip" path, as if the wake word had been heard (full mode, *Wake word* switched on) | `POST /api/full/wake` |
| `:do turn_left 45` | one robot command, no AI (`move_forward`, `move_backward`, `turn_left`, `turn_right`, `spin`, `dance`, `look_around`, `stop`, ...: `commands.ACTIONS`) | `POST /api/assistant/commands` |
| `:cli help guard` | runs `python main.py help guard` in `run_prototype/` (any `main.py` command; Ctrl+C stops a long one) | subprocess |
| `:lift on` / `:lift off` | picks the simulated robot up / puts it down (it resets its pose and looks around) | `POST /api/sim/lift` |
| `:phone on` / `:phone off` | the simulated phone comes near / leaves (presence: wake, greet, sleep) | `POST /api/sim/phone` |
| `:stuck left` / `right` / `none` | jams a simulated wheel (wheel-fault warnings) | `POST /api/sim/wheel` |
| `:shuffle` | moves an object on the simulated desk | `POST /api/sim/shuffle` |
| `:gesture Thumb_Up` | a simulated hand gesture (`Closed_Fist`, `Open_Palm`, `Pointing_Up`, `Thumb_Down`, `Thumb_Up`, `Victory`, `ILoveYou`; `thumb up` works too) | `POST /api/sim/gesture` |
| `:touch top 1.5` · `:touch left top right` | (pro) a pat on a touch pad, held 1.5 s; several pads in quick succession (a stroke / pat streak) | `POST /api/pro/touch/test` |
| `:imu knock` | (pro) an MPU-6050 event: `knock`, `double_knock`, `bump`, `shake`, `tipped`, `righted`, `drop` | `POST /api/pro/motion/test` |
| `:profile Pirate` | (pro) switch the personality + voice profile | `POST /api/pro/profiles` |
| `:notify Mum: call me` | a phone notification (buddy, hub, full) | `POST /api/buddy/notifications/test` |
| `:state` | phase, current and last movement, awake, phone near, lifted, speech-to-text backends, brain, active alerts | `GET /api/assistant` |
| `:log 5` | the last 5 conversation turns | `GET /api/assistant` |
| `:stop` | stop all movement and speech | `POST /api/assistant/stop` |
| `:get /api/full` · `:post /api/sim/lift {"lifted": true}` | raw API calls, pretty-printed | any |
| `:open` · `:wait 2` · `:help` · `:quit` | dashboard in the browser · watch for 2 s · help · leave (or Ctrl+D) | |
| `expect left\|right` | the last reply contains one of these (case-insensitive) | |
| `expect move turn_left\|spin` | the last reply's commands, or anything the robot ran since, include one of these actions | |

Several commands can go on one line, separated by `;` (except `:post`, whose JSON may contain one). Lines starting
with `#` are comments.

**What gets printed.** Every new conversation turn: what speech-to-text heard (for voice), Pip's reply, mood, which
brain answered (`claude`, `local` rules, `offline`, `system` for errors), how long it took (and the speech-to-text
time), the movements, and any problems. Movements started outside a conversation (a gesture, `:do`, being put
down, a routine) are printed as `robot moved (<source>): action (result)`.

## How it works

**Starting the simulation** (`Server`). `python main.py <mode> --sim --port <p> --https-port 0` runs as a child
process in `run_prototype/` with the console's own Python. `assistant` mode uses `python -m deskbot assistant`
(that runtime isn't in `main.py`). Its output goes to `%TEMP%\deskbot_sim_<mode>_<port>.log`. The port is the first
free one from 8150, so it never clashes with a dashboard already on 8000. HTTPS is off because the console doesn't
need a browser microphone. The console waits up to 180 s for `GET /api/assistant` to answer (17–60 s on the laptop).
If the process dies first, it prints the log's last 15 lines. On exit it kills the whole process tree
(`taskkill /T /F` on Windows, `killpg` elsewhere), because the runtime starts child processes (body, gestures). `--keep` leaves it running.

**Following what happened** (`Console.drain`). Replies are read back from the conversation log in
`GET /api/assistant` (`assistant.log`, the newest 20 turns, each with an `id`), not from the POST's response, so
answers that arrive later are caught as well (wake word, notifications, gestures, routines). After a typed or voice
turn it prints the new entries right away. After an event it keeps polling every 0.3 s until 1.5 s pass with
nothing new, or until the event's limit: wake 20 s, notification 8 s, gesture 5 s, `:do` 4 s, lift/phone 3 s.
Background movements come from `executor.last` (`t`, `source`, `commands` with each `result`). A new `t` that
isn't from `ai` gets printed, because AI moves are already shown with their reply.

**Synthetic voice** (`synth_wav`). On Windows: PowerShell + `System.Speech.Synthesis.SpeechSynthesizer` writes
straight to a WAV in `SpeechAudioFormatInfo(16000, 16-bit, mono)`, the format the robot's speech-to-text expects.
The text and path are passed in environment variables, so quotes in the sentence can't break the command. On
Linux/the Pi: `espeak-ng -w`. This tests everything after the microphone: the WAV checks (0.3–30 s, louder than
−50 dBFS), the speech-to-text backend, the brain and the movement.

**This PC's microphone** (`record_mic`). On Windows: the winmm MCI string interface through `ctypes`
(`open new type waveaudio`, `set ... bitspersample 16 samplespersec R channels C`, `record`, `stop`, `save`), so
no audio package is needed. Many laptop microphones refuse anything but their native format: this laptop's records
only at 48 kHz stereo and rejects 16 kHz mono and 44.1 kHz mono with MCI error 328. So the formats are tried in
order (16 k mono, 48 k stereo, 48 k mono, 44.1 k stereo, 44.1 k mono). `to_16k_mono` averages the channels, then
box-filters down to 16 kHz: each output sample is the mean of the input samples it covers, the same anti-aliasing
the dashboard's browser recorder uses. On Linux: `arecord -f S16_LE -r 16000 -c 1`. A countdown shows while it records.

**Scenario files** (`--script`). One console command per line. `expect` lines record a failure instead of
stopping, so one run reports every problem, and the exit code is 1 if any failed. `tools/sim_scenarios/smoke.txt`
covers typed text, voice, a direct command, lift, phone, a gesture, `:state` and a CLI command.

## Voice input on the laptop: the `windows` speech-to-text backend

Before this, voice input couldn't work in simulation on the laptop. `faster-whisper` is blocked by Smart App Control
(`ctranslate2`), and there's no Groq/OpenAI key. So `deskbot/assistant/stt.py` gained a fourth backend,
**`windows`** (`WindowsSpeech`): Windows' own offline recogniser (`System.Speech.Recognition`, *Microsoft Speech
Recognizer 8.0, en-US*, shipped with Windows 10/11), run through PowerShell. Small hook, documented in `stt.py`:

- **Available** only when `os.name == "nt"` and `powershell` is on PATH, so it never exists on the Pi.
- **Order:** last in `auto` (`local → groq → openai → windows`), and also allowed when the setting is strict
  `local`, because it runs on the device and never sends audio anywhere. Selectable as `"stt": "windows"`
  (`settings.validate` accepts it).
- **How:** the WAV is written to a temp file. A `DictationGrammar` engine reads it with `SetInputToWaveFile`.
  `InitialSilenceTimeout` is 60 s of *file* time and `BabbleTimeout` is 0, so recognition only stops at the end of the
  file. At the end, the engine detaches its input and `Recognize()` throws "No audio input…": that is treated as
  the end, unless nothing was recognised yet, in which case the error is real and is raised. The phrases are joined
  and printed **base64 of UTF-8**, because PowerShell 5.1's console code page mangled "90°" into "90?". The time
  limit is 20 s.
- `Transcriber.order()` now skips names that aren't in `backends`, so code (and tests) that replace the backend
  table keep working.
- **Measured on the laptop:** "turn right" (synthetic voice) → `Turn right` → *Turning right* + `turn_right 90`.
  The first clip took ~14 s, because the blocked `faster-whisper` is tried and fails first, then PowerShell starts.
  The Windows recogniser on its own takes ~2–3 s per clip (mostly PowerShell's start-up). Dictation is less accurate than
  Whisper, especially on unusual words. It's for testing the pipeline, not the robot's real recogniser.

## Verified (laptop, 20 Nov 2026)

- `tests/test_sim_console.py`, 12 tests: resampling (48 kHz stereo and 44.1 kHz → 16 kHz mono; an 8-bit clip is
  rejected), command splitting, every `:` command posting to the right route, bad input not crashing,
  `expect`/`expect move`, background moves, speech-to-text order (`auto`, strict `local`, `none`), the setting, and
  a real Windows TTS → recogniser round trip. The whole suite passes.
- `tools/sim_scenarios/smoke.txt` against `main.py full --sim`: all expectations pass. Typed "turn left 90"
  → `turn_left 90`; `:voice turn right` → heard "Turn right" → `turn_right 90`; `:do spin 1` → spin ok; lift on/off
  (put down → `look_around`); phone near; `Thumb_Up` → `dance`; `:state`; `:cli help guard`.
- `:mic`: recording from the laptop microphone gives a valid 16 kHz mono WAV (it fell back to 48 kHz stereo).
  Recognising real speech from it wasn't tried here (nobody spoke). A silent room measured −59 dBFS, which the robot
  rejects as "Is the microphone muted?". That's expected.
- **Not covered:** the Pi's own USB microphone (`listen` on the robot) and anything needing API keys (Claude
  answers, Groq Whisper). Without keys the brain runs in *simple mode* (local rules), which the console shows in
  `:state`.

## Troubleshooting

| symptom | fix |
| --- | --- |
| `heard` is wrong or empty | speak a bit slower; dictation is weaker than Whisper. Add `GROQ_API_KEY` to `secrets.env` for Whisper |
| "I didn't hear anything. Is the microphone muted?" | the clip peaked below −50 dBFS: raise the input volume (Settings → System → Sound → Input), and check *Let desktop apps access your microphone* (Privacy & security → Microphone) |
| `microphone: No wave device is installed…` on every format | no usable input device: plug one in or enable it in `mmsys.cpl` → Recording |
| `HTTP 400: ... switched off` | that feature is off: switch it on in the dashboard's *Features* card or `:post /api/full/features {...}` |
| first reply takes ~45 s | the local AI (Ollama) isn't running, and the full robot waits for its time-out once. Start Ollama, or switch *Local AI* off |
| startup fails | read the log path the console printed |
