# Desk Assistant Robot

A Raspberry Pi 4 differential-drive desk robot with sonars, edge sensors, wheel encoders, a camera, an IMU, an OLED face, a voice
assistant and a web dashboard. **`run_prototype/main.py`** runs all of it. The original terminal script is kept in `legacy/`.

## Repository layout

```text
run_prototype/   Holds all the material to test and run; the only folder the Pi needs
docs/            design notes and build documentation
tests/           automated tests
tools/           navigation demo, interactive shell, simulation test console, end-to-end test, test runners
benchmarks/      open-source benchmark suite, its data and results
digital_twin/    MATLAB digital twin (runs on a computer, not on the Pi)
legacy/          earlier scripts, kept working
```

**Commands below that start with `python main.py` or `scripts/` run from inside `run_prototype/`.** Commands that start with
`python tools/`, `python benchmarks/` or `python legacy/` run from the top of the repository. To run the tests:
`python -m unittest discover -s tests -t .`

## Running it on a Raspberry Pi

Copy only `run_prototype/`. Full steps: [`docs/install-on-raspberry-pi.md`](docs/install-on-raspberry-pi.md).

```bash
bash tools/deploy.sh pi@<pi-address> --install
```

| Item | Size |
|---|---|
| `run_prototype` code | about 1 MB (0.3 MB compressed) |
| Vision and gesture models | about 14 MB |
| Python packages | 427 MB on the Pi, measured (was 1.7 GB): MediaPipe 129 MB, OpenCV + ncnn 106 MB, matplotlib 59 MB, numpy 56 MB. See [`docs/slim-dependencies.md`](docs/slim-dependencies.md) |
| Whole repository, without its environment or Git history | about 43 MB, of which 22 MB is benchmark data |

| Pi | Expectation for the full robot |
|---|---|
| Pi 4 or 5, 8 GB | Comfortable |
| Pi 4 or 5, 4 GB | Should work; the recommended minimum |
| Pi 4, 2 GB | Tight: turn off gestures, and expect swapping with local speech-to-text |
| 1 GB | Not recommended for the full robot |

Use a 32 GB or larger card (16 GB is the minimum), 64-bit Raspberry Pi OS, a good 5 V / 3 A supply separate from the motor supply, and
cooling. These are estimates: the simulated robot used 333 MB on a laptop, and loading the vision stack took about 360 MB more, before
speech-to-text. **It has not yet been run on a real Pi.** Check with `python main.py health`, and watch memory with `free -h` and temperature with `vcgencmd measure_temp`.

## Start here: one command for everything

```bash
cd run_prototype
python main.py                   # menu of everything
python main.py start --sim       # try the whole robot on any computer
python main.py start --lan       # on the Pi, reachable from your phone or laptop
python main.py buddy --lan       # the same + task list, reminders, celebrations, phone notifications (19 Nov 2026)
python main.py hub --lan         # buddy + ideas, focus mode, Google Calendar, Spotify, accounts, cost meter
python main.py full --lan        # EVERY feature (wake word, routines, smart home, reader, guard, Telegram, ...)
python main.py help              # every feature and voice command, in the terminal
python main.py health            # test every sensor and part, then report the robot's health
python main.py calibrate         # complete calibration (add --sim to try it)
python main.py --help            # every command
```

`python main.py` first offers the full health check, then opens the menu.

First time on the Pi: `bash scripts/setup.sh`, reboot once so I2C is on, wire the MPU-6050 and OLED (below), run
`python main.py check`, then `python main.py calibrate`. Open `http://<pi>:8000` for the dashboard.

### Features and how to use them

| Feature | What it does | How to use it |
| --- | --- | --- |
| **Whole robot** | Motors, safety stops, sonars, IR, camera, maps, assistant, phone remote | `python main.py start` |
| **Saved outputs** | Maps, plots, telemetry, events, conversation, object snapshots, calibration reports | Automatic, in `outputs/<date_time>_<mode>/`. List with `python main.py outputs` |
| **Save figures** | Saves every figure now, or one figure from its card | **Save figures** on the Saved outputs card, or **Save** on any figure card |
| **Complete calibration** | IMU, sonars, IR, camera, turn rate, motor dead zone, speed, wheel balance, 90° check | `python main.py calibrate`, menu, or **Run full calibration**. Leave 30 cm clear. A box 30–100 cm ahead and behind lets the sonars measure speed |
| **MPU-6050** | Tilt, heading, turn rate; better map heading | Live view: `python main.py imu`. Body card on the dashboard |
| **Self-correction (PID)** | Drives straight, holds turn speed, slows near obstacles, detects stalled turns, tracks you smoothly | On by default. Self-correction card shows target vs measured and has the switches |
| **Keep distance** | Holds about 45 cm from you with the front sonar | **Keep my distance from the user** switch (off by default) |
| **Pick-up detection** | Stops, freezes the map; when put down it saves the old map, starts a new one, resets heading and looks around | Automatic. Change the steps with `lift.on_place` in `data/companion.json` |
| **Gesture control** | Hand gestures trigger any robot command | Gestures card, or `python main.py gestures set Victory dance --hold 1`. `gestures reset` restores defaults |
| **OLED eyes** | Follow you, blink, and show 9 emotions with 5 animations each, chosen at random | Automatic. Test: `python main.py face`. Save all as images: `python main.py face --preview` |
| **Near an object** | Eyes turn curious and look toward something close (sonar under 30 cm, or a large recognised object) | Automatic |
| **Greeting** | Says hello and looks happy when a new person appears | Automatic. Settings under `greet` in `data/companion.json` |
| **Dance** | Picks one of 6 pre-coded routines at random | **Dance** on the Eyes card, say "dance", the remote, or the Thumb Up gesture |
| **3D orientation** | Live 3D robot showing roll, pitch and heading; drag to look around it | Body card |
| **Voice choice** | Chipmunk, Natural, Deep, Robot, Radio or Cave echo, plus default, female or male | Personality & voice card, then **Test voice** |
| **Health check** | Tests software, sensors, IMU, eyes, camera, detector, gestures, audio, Bluetooth, network and unit tests | `python main.py health` (`--motors` includes short moves). Report in `outputs/health/` |
| **Digital twin** | MATLAB model with the same control loops and safety rules; compares with real runs or follows the live robot | Open `digital_twin/` in MATLAB and run `run_twin`. See [its README](digital_twin/README.md) |
| **Voice assistant** | Talk or type; Claude or offline replies; spoken answers | Assistant card or `/remote`. Keys go in `secrets.env` |
| **Older tools** | Shell, sensor tests, earlier dashboards and scripts | `python main.py shell`, `test-sensors`, `test-camera`, `test-mic`, `e2e`, `drive-basic`, `dashboard-basic`, and more in `--help` |

Default gestures:

| Gesture | Action | Gesture | Action |
| --- | --- | --- | --- |
| Open palm | stop | Victory | spin once |
| Closed fist | stop following | Pointing up | look around |
| Thumb up | dance | I love you | follow me |
| Thumb down | sleep | | |

### Wiring the MPU-6050 and OLED

Both share I2C bus 1. Use 3.3 V.

| Signal | Pi pin | MPU-6050 | SSD1306 OLED |
| --- | --- | --- | --- |
| 3.3 V | 1 | VCC | VCC |
| GND | 6 | GND | GND |
| SDA (GPIO 2) | 3 | SDA | SDA |
| SCL (GPIO 3) | 5 | SCL | SCL |

Mount the IMU firmly with its X axis forward if you can; calibration corrects tilt and a reversed turn axis. For a
1.3" SH1106 screen, put `{"oled": {"driver": "sh1106"}}` in `data/companion.json`.

Design details and every constant: [`docs/companion.md`](docs/companion.md).

## Desk buddy: tasks, reminders, celebrations, phone notifications (`main.py buddy`, 19 Nov 2026)

```bash
python main.py buddy --sim       # anywhere          ·   on the Pi: bash scripts/buddy.sh
```

- **Tasks by voice.** "Remind me to submit the report by 5 tomorrow", "I finished the report", "what's on my list?".
  The list is kept in `data/tasks.json`; deadlines get a heads-up (15 min before), a reminder when they're due
  and one nudge an hour after a missed one. Each reminder plays a chime, changes the eyes and gives a small nudge.
- **Celebrations.** Finishing a task plays a fanfare, shows the new `celebrating` eyes (confetti) and does one of four
  victory moves; clearing the whole list adds a spin. The dashboard's Tasks card shows confetti too.
- **Phone notifications.** The phone posts each notification to `POST /api/notify` (an Android automation app does it;
  see the dashboard's "Connect your phone"). Rules, plus Claude for the unclear ones, decide what's important. Only
  those are read aloud, and they're held while you're away or during quiet hours. Codes and passwords are never
  read, never sent to the AI and never kept.
- **Sound effects.** The AI's reply now has a `sound` field (`"none"` or one of 15 effects), played before the speech.

Design, rules and every constant: [`docs/buddy.md`](docs/buddy.md).

## Desk hub: ideas, focus mode, Google, Spotify, accounts, costs (`main.py hub`, 19 Nov 2026)

```bash
python main.py hub --sim         # anywhere          ·   on the Pi: bash scripts/hub.sh
```

- **"Remember this idea"** saves what you say next to an ideas notebook. "What were my ideas?" reads them back, and
  the dashboard can search them and export them as Markdown.
- **Focus mode** ("start focus mode", "focus for 50 minutes"). The robot watches whether you're looking at your work:
  - It works out which way your face points from 5 face landmarks (OpenCV YuNet), and notices a phone in your hands.
  - It nudges you after 20 s of looking away, or 10 s on the phone: a sound, a change in the eyes, a short line and a
    wiggle.
  - It holds your notifications until the break, and celebrates a session where you were focused 80 % of the time.
  - Nothing is recorded or sent anywhere.
- **Google Calendar reminders.** Tasks with deadlines become calendar events with a pop-up reminder on your phone.
  "Put the dentist on my calendar tomorrow at 9" and "what's on my calendar?" also work.
- **Spotify.** "Play Blinding Lights", "pause the music", "next song", "volume 40". Playback control needs Spotify
  Premium.
- **Connected accounts card.** It shows each account, what it can access, and when it was connected and last used.
  - Connecting needs `ADMIN_PIN` and uses OAuth with PKCE and a one-time state.
  - Tokens are encrypted on the robot when `ACCOUNTS_KEY` is set, and are never shown or sent anywhere.
  - Disconnect revokes the token at Google.
- **API costs card** with a daily Claude cap; see the next section.

Setup, security model and every constant: [`docs/hub.md`](docs/hub.md).

## The full robot: every feature, each switchable (`main.py full`, 19 Nov 2026)

```bash
python main.py full --sim        # anywhere      ·   on the Pi: bash scripts/full.sh      ·   python main.py help
```

Everything above, plus:

| | say | notes |
| --- | --- | --- |
| **"Hey Pip" wake word** | "hey pip, what time is it?" | recognised on the robot (Vosk, or the local Whisper as a fallback); nothing is streamed |
| **Voice routines** | "study time", "break time" | your own phrases that run steps: focus, music, lights, messages; one JSON file each in `data/routines/`, editable on the dashboard; can also run on events (arrive, leave, a time) |
| **Morning / evening briefing** | "good morning", "how was my day?" | weather, calendar, deadlines; what you finished, focus time, water; automatic once a day |
| **Rock, paper, scissors** | "let's play rock paper scissors" | your hand (fist / palm / peace sign) or your voice; best of three |
| **Read this for me** | "read this for me", "summarise this" | camera, dashboard photo or Telegram photo; **local** vision model (Ollama) or Tesseract first; text saved in `data/reads/` |
| **Hydration buddy** | "I drank some water" | sees you drinking, reminds you after 45 minutes without a drink |
| **Owner recognition** | "learn my face" | greets you by name; only face numbers kept, on the robot |
| **Guard mode** | "guard my desk" | asks visitors who they are, takes an announced photo, sends it to your Telegram |
| **Telegram bot** | `/tasks`, `/add`, `/photo`, a photo of a page | private: paired to your chat with a one-time code |
| **Smart home** | "turn on the desk lamp" | Home Assistant, Shelly, Tasmota on your Wi-Fi; no cloud |
| **Local AI brain** | anything | Ollama on the Pi or your laptop when Claude is off: free and private |
| **Feature switches** | — | the Features card turns any feature on or off; **Local only** turns off everything that needs the internet |

Guard, faces, Telegram pairing and local-only need `ADMIN_PIN`. A visitor can't stop guard mode or enrol their face
by voice. Design: [`docs/full.md`](docs/full.md). Running with no internet at all:
[`docs/local-only.md`](docs/local-only.md).

## The pro robot: your dashboard, headpats, Groq first (`main.py pro`, 20 Nov 2026)

```bash
python main.py pro --sim         # anywhere      ·   on the Pi: bash scripts/pro.sh
```

The full robot, plus:

| | how | notes |
| --- | --- | --- |
| **Your own dashboard** | **＋ Add a card** dropdown, **×** on a card, drag the **⠿** handle | 14 cards shown by default, the other 37 one click away; **Customize** shows every handle; saved per browser; **Reset** |
| **Light / dark mode** | Auto · Light · Dark, top right | Auto follows your system; a sleeker look (accent colour, softer cards, sticky toolbar) |
| **Headpats** | touch the top, left or right pad | pat = giggle + "thank you", long pat = blush, 3 quick pats = celebration, left→top→right = a stroke; wakes a sleeping robot |
| **More from the MPU-6050** | knock, bump, shake, tip it over, drop it | knock = "who's there?", double knock wakes it, bump while driving = stop + "oof", shake = dizzy, tipped = stop + asks for help |
| **Voice studio** | sliders and dropdowns | pitch and speed (independent), loudness, voice type, the engine's own voices, gender, test button |
| **Personality profiles** | dropdown, or say "switch to the pirate profile" | personality + voice together; 4 built in, save your own |
| **Groq brain** | add `GROQ_API_KEY` | `openai/gpt-oss-120b` answers first; Claude takes over if Groq fails, and for questions that need the camera picture |
| **APIs in use** | card | every service, whether it's active or a fallback right now, call counts |
| **Accounts** | card (view only) | linked accounts and every key, masked (`gsk_…a91f`); keys are changed only in `secrets.env` |

Touch pads: 3× TTP223 on GPIO 7 (top), 8 (left), 14 (right), powered from **3.3 V**. Test them with
`python3 hardware_tests/hardware_test.py touch`. Design, wiring, thresholds and the pin-saving options:
[`docs/pro.md`](docs/pro.md).

## What it costs to run (APIs)

**Claude is the only paid API the robot uses.** Everything else it calls is free:

- Groq speech-to-text (free tier), Open-Meteo, Wikipedia, the joke and exchange-rate APIs, the Google Calendar API
  (with no billing account on the Google Cloud project) and the Spotify Web API.
- The one paid fallback that existed, OpenAI speech-to-text, is now blocked unless you switch `allow_paid_apis` on.
- The default speech-to-text is local, so it costs nothing.

**The Claude API is not included in a Claude.ai Free, Pro or Max plan.** Those subscriptions cover the Claude apps
(and Claude Code), not API calls. The robot uses an API key from [console.anthropic.com](https://console.anthropic.com),
billed separately from prepaid credits. Set a monthly spend limit there.

With the default model (Claude Haiku 5.5: $0.10 per million input tokens, $0.50 per million output tokens), a voice
turn costs about $0.0002. 100 turns a day is roughly **$0.02–0.05 (₹2–4) a day**. The hub's API costs card shows the
real numbers from each response's token counts, and switches the AI off for the rest of the day at a daily cap
(default $0.50).

## Test every feature in simulation from one terminal (`sim_console.py`, 20 Nov 2026)

```bash
python tools/sim_console.py --open                                  # starts the full robot in simulation + a prompt
python tools/sim_console.py --script tools/sim_scenarios/smoke.txt  # one-command smoke test (exit 1 on a failure)
```

At the prompt, type to the robot (`turn left 90`), talk to it with the PC's synthetic voice (`:voice do a dance`) or
your own microphone (`:mic 4`), run any `main.py` command (`:cli help guard`), and trigger the simulated robot's
events (`:lift on`, `:phone on`, `:gesture Thumb_Up`, `:notify Mum: call me`, `:wake ...`). Voice works on the laptop
without API keys through a new offline `windows` speech-to-text backend. Details: [`docs/sim-console.md`](docs/sim-console.md).

## Go from one obstacle to another (`navigate.py`, 18 Nov 2026)

Say or type **"go from the cup to the bottle"** (or "drive to the book"). The robot finds both on its map, plans around
everything else and stops in front of each one, outside the sonar stop distance. For every plan it measures the number of
obstacles, how blocked the desk is, tight gaps, unobserved floor, position uncertainty, distance and this computer's
search speed, then picks a straight line, Theta*, a visibility graph, A*, weighted A* or RRT-Connect.

```bash
python tools/navigate.py --compare                       # every planner on nine test desks, and which one gets chosen
python tools/navigate.py --from cup --to book --start 0.15 0.15 --stop-distance 0.10    # full simulated trip, saves a picture
python tools/navigate.py --from cup --to bottle --url http://localhost:8000             # ask a running robot
```

So far this has been tested in simulation only. Details, rules, measurements and limits:
[`docs/navigation.md`](docs/navigation.md).

## Improvements over earlier versions

**Space savings, 20 Nov 2026.** The robot's Python packages on the Pi went from **1,711 MB to 427 MB** (−75 %),
measured by installing both package sets for the Pi (aarch64, Python 3.11):

| Step | Removed | Pi packages |
| --- | --- | --- |
| Before | | 1,711 MB (104 + MediaPipe) |
| YOLO26n on NCNN directly, ByteTrack in numpy ([`docs/ncnn-detector.md`](docs/ncnn-detector.md)) | PyTorch, torchvision, Ultralytics, `lap`, polars, full-GUI OpenCV (headless instead) | 816 MB (86 + MediaPipe) |
| numpy instead of scipy, whisper.cpp instead of faster-whisper, Claude over plain HTTPS ([`docs/slim-dependencies.md`](docs/slim-dependencies.md)) | scipy, faster-whisper + CTranslate2 + onnxruntime + PyAV + tokenizers, the `anthropic` SDK + pydantic + httpx2 | **427 MB (61 + MediaPipe)** |

Same behaviour: detections, track IDs and boxes match Ultralytics frame by frame, track matching and IMU levelling
match scipy, speech-to-text uses the same Whisper tiny.en model (8-bit), and Claude gets the same requests.
What the 427 MB is now: MediaPipe 129, OpenCV + ncnn 106, matplotlib 59, numpy 56, Pillow 22, whisper.cpp 15, Vosk 8,
the rest 34. The YOLO model is still exported once, in a temporary venv that `scripts/export-model.sh` deletes afterwards.

**Upgrading an existing Pi:** run `bash scripts/setup.sh` (or `bash tools/deploy.sh pi@<pi> --install`). It uninstalls
every package the robot no longer needs (45 of them: torch, torchvision, ultralytics, lap, polars, opencv-python, scipy,
anthropic, faster-whisper, ctranslate2, onnxruntime, av, pydantic and their dependencies; the full list is `REMOVED_PKGS`
in `setup.sh`) from `run_prototype/.venv`, clears pip's download cache, and installs `opencv-python-headless` and
`pywhispercpp`. Your exported model is kept; the whisper.cpp model (44 MB) downloads on first use.
Also removed from `run_prototype/`: the README, `deploy.sh` (now `tools/`), `oled.sh` and seven hardware-test files
(now one `hardware_test.py`).

Measured or directly countable. Results marked *sim* come from the simulator, not the real robot.

| What | Before | Now | Evidence |
| --- | --- | --- | --- |
| Python packages on the Pi (aarch64, measured) | 1,711 MB, 104 packages | **427 MB, 61 packages (−1,284 MB, −75 %)** | aarch64 install of both sets with `uv`, [`docs/slim-dependencies.md`](docs/slim-dependencies.md) |
| Dependencies replaced by small code | scipy 120 MB, faster-whisper stack 261 MB, `anthropic` SDK ~25 MB | **numpy Hungarian + Rodrigues, whisper.cpp 15 MB, `claude_http.py` (stdlib)** | `tests/test_slim_deps.py` |
| PyTorch / Ultralytics on the robot | 625 MB torch + 172 MB polars + 136 MB GUI OpenCV + 16 smaller | **none** (YOLO26n on NCNN directly, ByteTrack in numpy; same detections and track IDs) | `tests/test_ncnn_detector.py` (60 frames vs Ultralytics) |
| AI calls for a plain robot command ("turn left", "go to the cup") | 1 | **0** | `tests/test_assistant.py` fails if the API is called |
| Camera frames sent for a question that doesn't need eyes | 1 per turn (~10 kB) | **0** | `needs_image`; detections still go as text |
| Default speech-to-text | cloud first | **on the robot only, never falls back to the cloud** | `tests/test_assistant.py` |
| Getting between two objects | drive straight at one | **6 planners, chosen per route, with replanning** | `python tools/navigate.py --compare` *sim* |
| Object not on the map | gives up | **looks around, then searches up to 3 more spots** | live run *sim* |
| Places remembered across restarts | none | **home, no-go zones, trouble spots, good corridors** | `tests/test_nav_memory.py` |
| Detector runs, simulated still-then-turning scene (240 frames) | 136 | **61**, IDF1 0.92 to 0.93, MOTA 0.85 to 0.88, HOTA 0.82 to 0.81 | `python benchmarks/benchmarks.py tracking` *sim* |
| Wheel problems | gyro check on turns only | **each wheel checked against its encoder, spoken warning, sad face** | `tests/test_reliability.py`, live run *sim* |
| Flickering sensors | acted on directly | **median filter, IR hysteresis, fault detection that fails toward stopping** | `tests/test_reliability.py` |
| Following a route | stop, turn, drive | **continuous curves with ramped wheel commands, steering away before a stop** | live run: 0 safety stops *sim* |
| Face animations | 45 | **50, plus tilt slide and wooziness** | `tests/test_nav_memory.py` |
| Automated tests (project `.venv`) | 136 | **190** | `python -m unittest discover -s tests -t .` |

Speed and accuracy on the real robot have not been re-measured for these changes.

## Benchmarks

All tools are open source (`pip install -r benchmarks/requirements.txt`).

| Command | Tool (licence) | Measures | Latest result on the development laptop |
| --- | --- | --- | --- |
| `python benchmarks/benchmarks.py perf` | pyperf (MIT) | Speed of the navigation and sensor code | costmap 3.4 ms, A* 14.6 ms, Theta* 23.0 ms, sensor filter 0.02 ms, colour of a box 0.27 ms |
| `python benchmarks/benchmarks.py planners` | PythonRobotics A* (MIT) | Route length and time against an independent planner | see `docs/benchmark.md`; this project also obeys the sonar stop rule, the baseline does not |
| `python benchmarks/benchmarks.py odometry` | evo (GPL-3.0) | Pose error against ground truth | ATE RMSE 1.9 cm on a simulated 2.8 m square with wheels 5% off |
| `python benchmarks/benchmarks.py tracking` | TrackEval (MIT) | HOTA, MOTA, IDF1 | fixed: 0.823 / 0.849 / 0.922 with 136 detector runs; adaptive: 0.806 / 0.876 / 0.934 with 61 (*simulated camera*) |
| `python benchmarks/benchmarks.py detection --limit 50` | pycocotools (BSD-style) | Detection accuracy on COCO | mAP50 0.50, mAP50-95 0.37 on only 10 images at 320 px: a smoke test, not a score to quote |
| `python benchmarks/benchmarks.py speech --limit 20` | jiwer (Apache-2.0) + LibriSpeech (CC BY 4.0) | Speech-to-text word error rate | not run yet: Windows Smart App Control blocks the speech engine on the laptop. Run it on the Pi |

Reports are saved in `benchmarks/results/`. Details: [`docs/benchmark.md`](docs/benchmark.md).

## What stays on the robot and what leaves it

**Processed locally, nothing sent:**

- Motors, safety rules, sonars, IR, IMU, wheel encoders, stuck-wheel detection
- Camera capture, object detection (YOLO26n), tracking, colour of detected objects
- Maps, navigation, path planning, home, no-go zones
- Speech to text (default `stt: local`, using whisper.cpp) and text to speech (Piper, eSpeak NG)
- Plain robot commands, "what do you see", "what colour is the cup", "what is this" when the detector recognises it
- OLED face, sounds, gestures, Bluetooth phone presence, dashboard, saved outputs

**Sent out, and how to keep it local:**

| What leaves | Goes to | When | How to process it locally instead |
| --- | --- | --- | --- |
| Your words, recent conversation (last 6 turns), time, sensor readings, detected and remembered objects, phone presence | Anthropic (Claude) | Questions and conversation that aren't plain commands | Remove `ANTHROPIC_API_KEY`: the offline brain handles commands and simple questions. For open conversation, add a small local language model through Ollama or llama.cpp on a stronger computer on your network; a Pi 4 would be slow |
| One 320x240 camera image, about 10 kB | Anthropic | Only for visual questions the detector can't answer, such as reading text | Set `send_image` to false. For richer descriptions, run an open vision-language model such as Moondream on a laptop or GPU box; it is too heavy for a Pi 4 at conversational speed |
| Audio, about 160 kB per 5 s | Groq or OpenAI | Only if you change `stt` to `auto`, `groq` or `openai` | Keep `stt: local` |
| City name | Open-Meteo | Weather questions | Remove the weather tool, or use a home weather sensor |
| Your IP address | ipapi.co, only if no city is set; every web service also sees it | Weather with no location | Set `location` in the assistant settings |
| Search topic | Wikipedia | Encyclopedia questions | Keep an offline copy, for example a Kiwix ZIM file |
| Currency names | open.er-api.com | Currency questions | Store rates locally |
| A request for a joke | Official Joke API | Joke requests | Keep a local joke list |
| Download requests | Hugging Face, Ultralytics, Google, COCO, OpenSLR, GitHub | First-time model and benchmark downloads only | Copy the files onto the robot yourself |

Nothing above sends your API keys anywhere except the service they belong to. The project has no analytics or telemetry of its own.

## Security: known weaknesses

**These are deliberately not solved yet.** This is a prototype for one person on a trusted network, and the priorities so far have been learning, easy setup, quick phone access and low latency. Do not treat it as safe on a shared or public network.

| Weakness | What could happen | How to reduce it |
| --- | --- | --- |
| The dashboard and API have no login when started with `--lan` (the start-on-boot service does this) | Anyone on the same network can drive the robot, change settings, watch the camera, read saved conversations and pictures | Leave out `--lan`, or use the robot's own hotspot, or put an authenticating reverse proxy (Caddy, nginx) or Tailscale in front |
| HTTP is unencrypted; HTTPS uses a self-signed certificate that browsers are told to accept | Someone on the network can read or alter traffic, including camera video, or impersonate the robot | Use HTTPS only, install your own trusted certificate on your devices, or use a VPN such as Tailscale or WireGuard |
| No per-user permissions or rate limits | Any connected client has full control and can flood the robot or run up API use | Add tokens and rate limits at the proxy; set a monthly spend limit in the Anthropic Console |
| Cross-site protection relies on the JSON `Content-Type` and browsers' CORS rules | A flaw or unusual client could still send commands from another page | Add CSRF tokens and check the `Origin` and `Host` headers |
| API keys are stored as plain text in `secrets.env` | Anyone who gets the SD card or a shell can use your keys | `chmod 600 secrets.env`, use a low-limit key, encrypt the disk, rotate keys if the card is lost |
| Conversations, map data and camera snapshots are saved unencrypted in `outputs/` and are served by the dashboard | Private images or speech can be read by anyone with access | Turn the recorder off or shorten retention, keep the dashboard off shared networks, encrypt the card |
| The robot acts on what it hears, and text seen by the camera or returned by web tools can influence the AI (prompt injection) | A stranger's voice or crafted text could trigger robot actions or a misleading reply | Commands are limited to a fixed list and motor safety still applies. Add a wake word or speaker check, require confirmation for movement, or turn off `execute_commands` |
| Physical access is not protected | Anyone holding the robot can remove the card or reach the Pi | Disk encryption, disabled unused ports, strong Pi password |
| Hotspot password is kept in plain text at `~/.deskbot-hotspot` (owner-only) | A compromised account reveals it | Change it with `scripts/hotspot.sh on --password ...` |
| Python dependencies are mostly not pinned, and benchmark baselines are downloaded code | A compromised or changed package could run on your machine | Pin versions with hashes, review updates, run benchmarks away from the robot's secrets |
| Bluetooth presence trusts a phone's advertised address or beacon | It can be spoofed to wake or put the robot to sleep | Treat presence as a convenience only, never as authentication |
| Safety rules depend on software, sensors and one Pi | A crash, sensor failure or fall can still cause damage | Keep a physical power switch, low speed and a desk lip; add a hardware motor cutoff |

## Quick start: the voice assistant + phone remote (`deskbot assistant`, 17 Nov 2026)

```bash
# on the laptop (Git Bash): copy everything to a cleaned Pi, install it, start it on every boot
cp secrets.env.example secrets.env        # add ANTHROPIC_API_KEY (AI brain) + GROQ_API_KEY (speech to text, free tier)
bash tools/deploy.sh pi@deskbot.local --wipe-home --install --service
# or by hand on the Pi:  bash scripts/assistant.sh        anywhere, no hardware:  bash scripts/assistant.sh --sim
```

Open `http://<pi>:8000` (dashboard) or `http://<pi>:8000/remote` (phone remote) from any device on the Wi-Fi.
To use a phone/laptop microphone, open `https://<pi>:8443` instead (accept the certificate warning once).
`bash scripts/hotspot.sh on` makes the Pi its own Wi-Fi network (dashboard at `http://10.42.0.1:8000`).

- **Talk to it**: hold-to-talk in the browser (or the robot's USB mic) → speech-to-text (Groq Whisper / OpenAI /
  offline whisper.cpp) → **Claude** gets your words + what the camera sees (detections, frame, remembered map
  objects, sensors) + the **personality** you set → JSON `{"speech", "mood", "commands"}` → said in a **chipmunk
  voice** on the speaker, shown on the dashboard, and the commands (move, turn, spin, dance, find phone, sleep, …)
  run with every safety rule. Free web APIs: weather (Open-Meteo), Wikipedia, jokes, currency, time.
- **Bluetooth LE**: wakes up when your phone comes near, goes to sleep when you leave, and on **find my phone** it
  turns to the strongest signal and drives toward it until the edge of the desk.
- **Picked up** → stops and pauses mapping; **put down** → starts a fresh map. The map updates at 25 Hz while moving.
- **Nothing just stops working**: every failure (no key, no internet, camera, sensors, Bluetooth, speaker, power,
  heat) is spoken out loud, shown on the Warnings card, and the robot falls back (e.g. offline brain).

Docs: [`assistant.md`](docs/assistant.md) · [`presence.md`](docs/presence.md) ·
[`deploy.md`](docs/deploy.md) (deploy, clean-up, hotspot, systemd).

## Quick start: the full app (`deskbot`, 15 Nov 2026)

The robot (4 ultrasonic + 2 IR + motors + safety loop), the **Pi camera with YOLO26n (NCNN) + ByteTrack** object
detection, **sensor-fusion maps** (geometric, semantic, and a confidence heatmap that fades stale data) and the web
dashboard, started by one command as **four processes, one per CPU core** (see below). Everything runs on the Pi:
no cloud, no API costs.

```bash
bash scripts/setup.sh      # once: camera packages, venv, NCNN + OpenCV, exports YOLO26n to NCNN (PyTorch only in a temporary venv)
bash scripts/start.sh      # start everything -> http://localhost:8000   (--lan for your phone/laptop)
bash tools/run_tests.sh       # all unit tests (no hardware needed)
bash scripts/sensors.sh    # test sensors: ultrasonic, IR, camera, camera + detection (motors never move)
bash scripts/sim.sh        # the whole app on any computer, simulated robot + desk + camera
bash tools/run_benchmarks.sh  # accuracy under 11 lighting conditions, tracking, latency -> benchmarks/results/
bash scripts/enable-realtime.sh   # once on the Pi: lets motor + sensor processes use real-time priority
bash scripts/deskbot.sh    # interactive menu for all of the above
```

| Dashboard card | Shows |
| --- | --- |
| Camera | live annotated stream, detection fps, inference ms, capture→result latency, tracked objects |
| Geometric map | sonar + IR occupancy; evidence halves every 90 s unseen, so stale areas fade to "unknown" |
| Semantic map | recognised objects (cup, book, …) with labels, confidence, uncertainty ring, last seen |
| Confidence heatmap | blue = sure nothing is there · grey = unknown or stale · red = sure an object is there |
| Processes | the four processes: core, priority, loop rate, CPU %, command → motor latency; "Face the user" switch |

Docs: [`deskbot.md`](docs/deskbot.md) (app, CLI, scripts) · [`runtime.md`](docs/runtime.md)
(processes, cores, scheduling, behaviour) · [`vision.md`](docs/vision.md) (camera, YOLO26n/NCNN, ByteTrack,
latency) · [`fusion.md`](docs/fusion.md) (maps, maths, staleness, glass/reflections) ·
[`benchmark.md`](docs/benchmark.md) (datasets, metrics). All the older scripts below still work unchanged.

### Four cores, four processes

The Raspberry Pi 4 has **4 CPU cores**, so the work is split into four processes, each pinned to its own core, so
all four are used and the heavy camera work can never delay the motors. Python's `multiprocessing` starts them;
Linux scheduling sets their priority:

| Core | Process | Priority | Does |
| --- | --- | --- | --- |
| 1 (cpu 0) | **motor** | highest: real-time `SCHED_FIFO 50` | owns the motor pins; runs the newest command; safety check on every sensor sample (≤ 20 ms) |
| 2 (cpu 1) | **sensors** | second: real-time `SCHED_FIFO 40` | owns 4 sonars + 2 IR; publishes all six readings at 50 Hz |
| 3 (cpu 2) | **camera** | medium: `nice 5` | camera + YOLO26n every 3 frames, optical flow in between, ByteTrack |
| 4 (cpu 3) | **navigation** | fourth: `nice 10` | fusion maps, "face the user" behaviour, web dashboard |

- **The latest command wins.** Commands go into a single slot. A new one replaces the running move immediately,
  and the motor process wakes for it at once (~0.4 ms p50 measured), instead of waiting for its next tick. A
  dashboard command also pauses the robot's own behaviour for 8 s.
- **Nothing is starved.** Only the two processes that sleep between short bursts (motor, sensors) are real-time.
  The camera, which is CPU-bound, never is. The kernel's real-time throttling stays on (≤ 95 % of each second),
  and every process has its own core. Real-time needs a one-time permission (`scripts/enable-realtime.sh`).
  Without it, everything still runs at normal priority.
- **Detection every 3 frames.** Between detections, boxes are moved with optical flow (~1–2 ms instead of a full
  inference). This cuts the detector's CPU by about 3× while boxes still update at the camera's frame rate.
  The rate is set by `VisionConfig.detect_every`: 3–5.
- **Frequently used data lives in shared memory**: sensor readings, motor state, wheel log, camera frames and
  detections. A read costs ~4 µs, against ~260 µs for a `multiprocessing.Queue` round trip (measured). It never
  blocks the writer.
- **Face the user.** When idle, the robot turns in place so the camera faces the nearest person. If no one is in
  view, it turns toward where the map last saw them, or looks around once. All of this goes through the same
  safety rules.
- **Reflections and glass** are handled in the maps; see [`fusion.md`](docs/fusion.md#reflections-and-glass).
- `python -m deskbot run --single-process` still starts the earlier one-process version.

## Hardware

| Component | Purpose |
| --- | --- |
| Raspberry Pi 4 | Main controller |
| L298N dual H-bridge | Motor direction + PWM speed control |
| 2 × DC geared motors + wheels | Left / right drive (differential drive) |
| Motor battery pack | Powers the motors via the L298N |
| HC-SR04 ultrasonic sensor | Front obstacle detection (stops at 20 cm) |
| 2 × IR edge/line sensors (digital out) | Front and rear desk-edge (cliff) detection |
| MPU-6050 IMU (I2C) | Heading, turn rate, tilt, pick-up detection |
| 128×64 SSD1306 or SH1106 OLED (I2C) | Animated eyes |
| Resistors for a voltage divider (e.g. 1 kΩ + 2 kΩ) | Drops the HC-SR04 5 V `ECHO` to 3.3 V for the Pi |

### Bill of materials and approximate cost

Estimates for November 2026, from typical prices at Indian robotics shops (Robu.in, Robocraze) and US ones (Adafruit,
Amazon). Prices change, so check before buying. Excludes the laptop, tools (soldering iron, multimeter) and
shipping.

| # | Part | Qty | ≈ ₹ | ≈ US$ | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | Raspberry Pi 4 Model B, 4 GB | 1 | 5,000–5,800 | 55–60 | 4 GB is the recommended minimum (see the RAM table above) |
| 2 | Official 5.1 V 3 A USB-C supply | 1 | 700–900 | 8–10 | for desk use; see the battery rows for driving untethered |
| 3 | microSD card, 32 GB, A1 | 1 | 350–500 | 6–9 | |
| 4 | Heatsink + fan case for the Pi | 1 | 300–600 | 5–10 | the vision pipeline runs four cores hard |
| 5 | Raspberry Pi Camera Module v2 (CSI) | 1 | 2,000–2,600 | 25 | a v1.3-style clone works for about ₹500 / $8 |
| 6 | L298N dual H-bridge motor driver | 1 | 120–200 | 3–6 | |
| 7 | DC geared motors with quadrature encoders (N20 / JGA25-370) | 2 | 700–1,400 | 10–25 | encoders on GPIO 5/6 and 20/16 |
| 8 | Wheels (about 65 mm) + a front caster | 1 set | 150–300 | 4–8 | |
| 9 | 2WD chassis plate + screws and standoffs | 1 | 250–500 | 8–15 | |
| 10 | Motor battery: 2 × 18650 Li-ion + holder (7.4 V), or a 6 × AA pack | 1 | 600–1,000 | 10–18 | plus a charger if you have none |
| 11 | Buck converter, 5 V 3 A (XL4015 / LM2596) | 1 | 100–200 | 3–5 | optional: runs the Pi from the battery |
| 12 | HC-SR04 ultrasonic sensors | 4 | 240–360 | 8–12 | front, left, right, rear |
| 13 | IR edge sensors (TCRT5000 module, digital out) | 2 | 80–120 | 3–4 | front and rear cliffs |
| 14 | MPU-6050 IMU (GY-521) | 1 | 120–200 | 3–6 | |
| 15 | 0.96" 128×64 SSD1306 OLED, I2C | 1 | 200–300 | 4–8 | the eyes |
| 16 | USB sound card + electret microphone capsule | 1 | 180–330 | 5–8 | |
| 17 | Small speaker (3 W) + PAM8403 amplifier, or a USB speaker | 1 | 100–250 | 4–8 | |
| 18 | 1 kΩ + 2 kΩ resistors, jumper wires, breadboard | 1 lot | 250–450 | 6–10 | one divider per HC-SR04 |
| | **Total** | | **≈ ₹11,500–16,000** (typically about ₹13,700) | **≈ $170–260** (typically about $205) | |

Running costs: a few rupees a day of Claude API at most (see "What it costs to run" above), and under 10 W of
electricity.

### Alternatives worth considering

| Instead of | Use | ≈ ₹ / US$ | Why it's better | Trade-off |
| --- | --- | --- | --- | --- |
| Raspberry Pi 4 | **Raspberry Pi 5 (4 or 8 GB)** | 6,500–8,500 / 60–80 | 2–3× faster CPU: YOLO and local speech-to-text run much faster; PCIe slot for an AI accelerator | needs the 27 W supply and active cooling |
| CPU-only vision | **Raspberry Pi AI HAT+ (Hailo-8L, 13 TOPS)** on a Pi 5 | 7,000–8,000 / 70 | detection at 30+ fps and the CPU left free for mapping and speech | Pi 5 only; models must be compiled for Hailo |
| Raspberry Pi | **NVIDIA Jetson Orin Nano Super** | 25,000–30,000 / 249 | CUDA GPU: far faster vision, local Whisper, even a small local LLM | several times the price and power; different OS setup |
| L298N | **TB6612FNG** driver | 150–250 / 5 | MOSFET driver: about 0.5 V lost instead of 2–3 V, so more speed from the same battery, runs cool, tiny, 3.3 V logic | 1.2 A per channel (plenty for N20 / TT motors) |
| HC-SR04 | **VL53L1X time-of-flight** sensors | 500–800 / 8–15 each | narrow beam, so fewer false echoes on a cluttered desk; I2C (no voltage divider); 4 m range; works on soft objects | each needs its own XSHUT pin or I2C address set at boot |
| IR edge sensors | **VL6180X ToF** cliff sensors | 400–600 / 6–10 each | measures the distance to the desk surface, so it works on black, glossy or glass desks where IR reflection fails | I2C addressing again |
| MPU-6050 | **BNO085 / BNO055** | 1,500–3,000 / 20–25 | sensor fusion on the chip plus a magnetometer: absolute heading with much less drift; the MPU-6050 is end-of-life | pricier; magnetometers dislike nearby motors |
| Electret mic + USB card | **ReSpeaker 2-Mic HAT** or **INMP441 I2S mic** | 1,500–2,500 / 12–20 (HAT), 150–250 / 3–5 (INMP441) | digital audio with less hiss; the HAT adds beamforming, a far-field pickup and a speaker output | the HAT uses I2S pins and needs its driver |
| PAM8403 + USB audio out | **MAX98357A I2S amplifier** | 250–400 / 6 | clean digital audio straight from the Pi, so no USB sound card is needed for output | one more I2S device to configure |
| Camera Module v2 | **Camera Module 3 (or 3 Wide)** | 2,700–3,300 / 25–35 | autofocus and HDR: better face direction in focus mode and better detection in mixed light; the Wide sees more of the desk | slightly larger, more processing |
| 0.96" mono OLED | **1.28" round GC9A01 colour LCD** | 400–900 / 6–12 | bigger, colour, more expressive eyes | SPI wiring; the eye drawing needs a colour version |
| AA / bare 18650s | **2S Li-ion pack with a BMS + 5 V 3 A buck**, or a USB-C PD power bank | 1,000–1,800 / 15–25 | rechargeable, protected against over-discharge, steadier voltage, so the Pi doesn't brown out when motors start | a charger, and Li-ion care |
| Wheel encoders alone | **+ PAA5100JE optical flow sensor** | 2,000–2,500 / 20 | measures real motion over the desk, so wheel slip doesn't corrupt the map | must sit 2–5 cm above the surface |

## Wiring (BCM numbering)

| Device | Signal | GPIO (BCM) | Physical pin |
| --- | --- | ---: | ---: |
| L298N (left motor) | ENA (PWM) | GPIO 13 | 33 |
| | IN1 (forward) | GPIO 22 | 15 |
| | IN2 (backward) | GPIO 23 | 16 |
| L298N (right motor) | ENB (PWM) | GPIO 12 | 32 |
| | IN3 (forward) | GPIO 27 | 13 |
| | IN4 (backward) | GPIO 17 | 11 |
| HC-SR04 | TRIG | GPIO 24 | 18 |
| | ECHO (**via voltage divider**) | GPIO 25 | 22 |
| Front IR sensor | OUT | GPIO 19 | 35 |
| Rear IR sensor | OUT | GPIO 26 | 37 |
| TTP223 touch pads (3.3 V) | top / left / right I/O | GPIO 7 / 8 / 14 | 26 / 24 / 8 |

- Remove the ENA/ENB jumpers on the L298N so the Pi controls motor speed.
- **All grounds must be common**: battery −, L298N GND and Pi GND.
- The Pi's GPIO pins use 3.3 V and are **not 5 V tolerant**. Power the IR sensors from 3.3 V,
  or level-shift their outputs. The HC-SR04 `ECHO` line must go through a voltage divider.
- If a motor spins the wrong way, swap its two wires on the L298N output (OUT1↔OUT2 or OUT3↔OUT4).

Full details: [`docs/pins.md`](docs/pins.md).

**All pin numbers live in [`robot_config.py`](robot_config.py).** Edit that file to rewire, then run
`python3 robot_config.py` to print the pin table and check for conflicts. The dashboard and
`13Nov-multisonar.py` read it. `3Nov-latest.py` keeps its own hard-coded copy as the reference version.
Details: [`docs/config.md`](docs/config.md).

## Setup

On Raspberry Pi OS (GPIO Zero is usually preinstalled):

```bash
sudo apt update
sudo apt install python3-gpiozero
```

## Running

```bash
python3 legacy/3Nov-latest.py
```

```
==============================
       ROBOT CONTROL
==============================

Select Movement:
1. Forward
2. Backward
3. Left
4. Right
0. Exit

Enter your choice: 1
Enter movement duration (seconds): 2

Moving FORWARD for 2.0 seconds
Movement completed.
```

- `Ctrl + C` performs an emergency stop. The `finally` block stops both motors and releases all GPIO devices.
- `0` exits cleanly.

## Web dashboard

`dashboard/` is a local control panel in the browser. It has the same pins and the same safety
rules as `3Nov-latest.py`, and no extra dependencies (Python standard library + gpiozero).

```bash
python3 dashboard/server.py                 # on the Pi, drives the real robot
python3 dashboard/server.py --sim           # any computer, simulated robot on a desk
python3 dashboard/server.py --host 0.0.0.0  # also reachable from other devices on your network
```

Then open <http://localhost:8000> (or `http://<pi-ip>:8000` with `--host 0.0.0.0`).

Cards:

| Card | Shows |
| --- | --- |
| Status | Current state, move progress, which directions are currently safe, move counters |
| Drive | Direction pad + STOP, move duration (0.5–10 s) |
| Ultrasonic | Live distance, last 15 s graph with the stop zone, min/average, obstacle stops |
| Edge sensors | Front/rear IR floor vs. edge, edge-stop counters |
| Desk | Top-down simulated desk (only in `--sim`): robot, obstacles, sonar beam |
| Configuration | Motor speed and obstacle stop distance (applied live), fixed settings |
| Sonar array | All four ultrasonic readings around the robot (only with `server_multisonar.py`) |
| Occupancy map | Live grid map, pose estimate and path (`server_mapping.py` / `server_multisonar.py`) |
| Event log | Moves, completions, safety stops |
| Wiring | Pin map (BCM + physical) |

Keyboard: arrow keys or `W A S D` to move, `Space` or `Esc` to stop.
`Ctrl + C` in the terminal stops the motors and releases the GPIO.

> The default `--host 127.0.0.1` only accepts connections from the Pi itself. The dashboard has no login,
> so with `--host 0.0.0.0` anyone on the same network can drive the robot. Only use that on a network you trust.

Don't run the dashboard and `3Nov-latest.py` at the same time, because both need the same GPIO pins.

## Occupancy grid mapping

`dashboard/server_mapping.py` is the same dashboard plus a live **occupancy map** built from the ultrasonic
and IR sensors (5 cm cells, 3 m × 3 m, centred on where the robot started).

```bash
python3 legacy/server_mapping.py          # on the Pi
python3 legacy/server_mapping.py --sim    # simulated desk
```

- The ultrasonic sensor marks free space along its beam and an obstacle where it hits (up to 1.2 m).
  The IR sensors mark floor under the robot and permanent desk-edge cells.
- Mapping runs in its own thread. It only reads the robot's latest sensor sample and a log of wheel
  commands, and never touches the motors or the 20 ms safety loop. A crashed or slow mapper can't delay a safety stop.
- The pose is dead-reckoned from motor commands (no encoders yet), so it drifts. Use **Clear map** to re-anchor it.
  Calibrate `WHEEL_SPEED_AT_FULL` / `TRACK_WIDTH` in `dashboard/mapping.py` on the real robot.
- The map is sent to the browser incrementally (only changed cells).

Full implementation details: [`docs/mapping.md`](docs/mapping.md).

## How it works

Each movement runs a control loop for the requested duration. Every **20 ms**
(`CHECK_INTERVAL`), the loop runs a safety check before it drives the motors:

| Movement | Safety condition (otherwise stop immediately) |
| --- | --- |
| Forward | Front IR sees the floor **and** ultrasonic distance > 20 cm |
| Backward | Rear IR sees the floor |
| Left / Right (spin in place) | Both front and rear IR see the floor |

- The IR sensors output **LOW (0) when the floor is detected** and HIGH when there is a drop (`FLOOR_VALUE = 0`).
  If your sensor modules use the opposite logic, change `FLOOR_VALUE` to `1`.
- Turning is a differential spin: one wheel forward, the other backward.
- The motors always stop when a movement ends, whether it completed, hit an edge or obstacle, or raised an error.

### Tunable settings (top of `3Nov-latest.py`)

| Constant | Default | Meaning |
| --- | --- | --- |
| `SPEED` | `0.5` | Motor PWM duty cycle (0–1) |
| `STOP_DISTANCE` | `0.20` | Obstacle stop distance in metres |
| `CHECK_INTERVAL` | `0.02` | Safety-check period in seconds |
| `FLOOR_VALUE` | `0` | IR reading that means "floor present" |

### Known limitations

- The ultrasonic sensor is only checked when moving forward. Turns and reverse ignore obstacles.
- Movement is time-based (open loop). Wheel encoders for distance/angle control are planned. See
  [`docs/encoders.md`](docs/encoders.md).

## Four ultrasonic sensors

**Test the hardware first** (motors are never touched). Every test is in one file, `hardware_tests/hardware_test.py`:
pick one from the menu, it runs until you press Enter, and you come back to the menu.

```bash
python3 hardware_tests/hardware_test.py                 # menu: sensors, camera, mic, oled, touch
python3 hardware_tests/hardware_test.py sensors         # any ultrasonic or IR sensor, live readings
python3 hardware_tests/hardware_test.py camera          # camera image in the terminal (SSH ok); --snap, --save pic.jpg, --ascii
python3 hardware_tests/hardware_test.py mic             # live level meter, or record 5 s and play back
python3 hardware_tests/hardware_test.py oled            # OLED on I2C bus 1: text, then a live clock; --sh1106, --addr 0x3d
python3 hardware_tests/hardware_test.py oled --text "hi" "line 2"   # write lines and leave them on screen
python3 hardware_tests/hardware_test.py touch           # the three TTP223 pads
bash scripts/sensors.sh                                 # all sensors at once + camera with live YOLO26n detection
```

It works when copied to the Pi on its own: pins come from `robot_config.py` if it is next door, otherwise from
the built-in copy. A test whose library or device is missing says how to fix it and returns to the menu.
The microphone is a 2-wire electret capsule on a USB sound card (red → tip, black → sleeve); the Pi has no analog
input. Details: [`docs/hardware-test.md`](docs/hardware-test.md), [`docs/sensor-tests.md`](docs/sensor-tests.md),
[`docs/camera.md`](docs/camera.md), [`docs/microphone.md`](docs/microphone.md).

**Run every feature in one go and watch the output** (one standalone file: copy just `test_e2e.py` to the Pi):

```bash
python3 tools/test_e2e.py --motors      # sensors, camera, YOLO detection, mic, driving with safety stops, map (robot MOVES)
python3 tools/test_e2e.py               # same without moving the wheels
python3 tools/test_e2e.py --sim         # fake robot + desk + sample photo: see it all on a laptop
```

Ctrl+C skips to the next feature. Outputs are also saved in `e2e_results/<time>/` (camera.jpg, detections.jpg, mic.wav,
map.png, summary.json). Details: [`docs/e2e-test.md`](docs/e2e-test.md).

**Tell the robot exactly what to do** (interactive shell, standalone: copy just `robot_shell.py` to the Pi):

```bash
python3 tools/robot_shell.py --motors   # robot[motors ON]> forward 30cm / left 90 / find cup / goto bottle / map / home
python3 tools/robot_shell.py --sim      # same on a fake desk;  add "cmd1; cmd2" to run commands and exit
```

Plain English works ("go forward 30 cm", "find the cup", "what do you see", "go home"). Press Enter for a
numbered menu; `help` lists every command. `--dashboard` adds a built-in web dashboard (open http://<pi-ip>:8080
on your laptop/phone): drive pad, live sensors, camera with YOLO boxes, map, settings, command box and log.
Run `calibrate` once on the real robot so cm and degrees come out right.
Details: [`docs/robot-shell.md`](docs/robot-shell.md).

Then run the robot:

```bash
python3 legacy/13Nov-multisonar.py                     # menu; option 5 prints all sensors
python3 legacy/server_multisonar.py [--sim]  # dashboard with Sonar array card + 4-beam mapping
```

| Sensor | TRIG | ECHO (via divider) | Used when |
| --- | --- | --- | --- |
| Front | GPIO 24 (pin 18) | GPIO 25 (pin 22) | forward: stop at 20 cm |
| Left | GPIO 4 (pin 7) | GPIO 18 (pin 12) | turning: stop at 8 cm |
| Right | GPIO 21 (pin 40) | GPIO 9 (pin 21) | turning: stop at 8 cm |
| Rear | GPIO 10 (pin 19) | GPIO 11 (pin 23) | backward: stop at 20 cm |

Each ECHO needs its own voltage divider. Full details (pin choice, mounting, safety rules, crosstalk, tests):
[`docs/multisonar.md`](docs/multisonar.md).

### Simplified one-file version

`legacy/simplified_code.py` is everything above in one standalone file: a typed CLI (`forward 2`, `back`, `left`,
`right`, `spin`, `stop`, `speed 0.6`, `status`), obstacle/edge stop, a rough obstacle map and a dashboard with
the camera at `http://<pi>:8080`. Same pins.

```bash
python3 legacy/simplified_code.py          # on the Pi
python3 legacy/simplified_code.py --sim    # laptop, simulated desk
```

Details: [`docs/simplified-code.md`](docs/simplified-code.md).

## Project layout

```text
README.md
run_prototype/
  main.py                the entry point for the whole robot
  robot_config.py        every pin number, with a conflict check
  calibrate_encoders.py  measures the wheel encoders
  deskbot/               the application
    assistant/           voice, AI brain, commands, sounds
    checks/              system and sensor checks
    companion/           IMU, PID control, lift handling, gestures, OLED eyes, calibration, saved outputs
    mapping/             geometric map, object map, sensor fusion
    navigation/          costmap, planners, adaptive selection, route following, saved places
    presence/            Bluetooth phone presence, find my phone
    runtime/             motor, sensor, camera and navigation processes; sensor filter; wheel monitor
    vision/              camera, YOLO26n, tracking, adaptive detection, colour
    web/                 dashboard server and cards
  dashboard/             motor and sensor classes, safety rules, simulator, base dashboard
  hardware_tests/        hardware_test.py: every sensor, camera, mic, OLED and touch test in one menu
  scripts/               setup, start, start on boot, hotspot
  models/, data/, outputs/   created while running (git-ignored)
docs/                    design notes
tests/                   automated tests
tools/                   deploy.sh (laptop → Pi), navigate.py, robot_shell.py, sim_console.py (+ sim_scenarios/), test_e2e.py, run_tests.sh, run_benchmarks.sh
benchmarks/              benchmarks.py, desk_bench/, requirements.txt, data/, results/
digital_twin/            MATLAB digital twin
legacy/                  3Nov-latest.py, 13Nov-multisonar.py, simplified_code.py, earlier dashboard servers
```

## Project docs

| File | Contents |
| --- | --- |
| [`docs/run-prototype.md`](docs/run-prototype.md) | What is in `run_prototype/` (the only folder the Pi needs) and the short Pi quick start |
| [`docs/companion.md`](docs/companion.md) | `main.py`: IMU, PID control, pick-up handling, gestures, OLED eyes, calibration, saved outputs |
| [`docs/navigation.md`](docs/navigation.md) | Obstacle-to-obstacle navigation: adaptive planner selection, safety-aware routes, replanning, search, home, no-go zones, confidence, limits |
| [`docs/full.md`](docs/full.md) | `main.py full`: wake word, routines, smart home, reader, local AI, games, hydration, briefings, faces, guard, Telegram, feature switches |
| [`docs/pro.md`](docs/pro.md) | `main.py pro`: configurable dashboard and themes, touch pads, MPU-6050 events, voice studio and profiles, Groq brain, accounts and APIs |
| [`docs/sim-console.md`](docs/sim-console.md) | `tools/sim_console.py`: every feature from one terminal in simulation; the Windows speech-to-text backend |
| [`docs/local-only.md`](docs/local-only.md) | running the robot with no internet, no cloud and no API costs (Ollama, Tesseract, local Whisper) |
| [`docs/hub.md`](docs/hub.md) | `main.py hub`: ideas, focus mode, Google Calendar, Spotify, connected accounts and their security, API costs |
| [`docs/buddy.md`](docs/buddy.md) | `main.py buddy`: spoken task list, deadlines, reminders, celebrations, phone notifications read aloud, sound effects |
| [`docs/assistant.md`](docs/assistant.md) | Voice assistant: STT, Claude brain + tools, JSON commands, chipmunk voice, remote, spoken warnings, live mapping |
| [`docs/presence.md`](docs/presence.md) | Bluetooth LE phone: wake/sleep, find my phone (RSSI scan), lift detection → new map |
| [`docs/install-on-raspberry-pi.md`](docs/install-on-raspberry-pi.md) | Step-by-step install on a Raspberry Pi: card, copy, setup, calibration, start, updates, troubleshooting |
| [`docs/deploy.md`](docs/deploy.md) | Copy to the Pi (`deploy.sh`: only changed files + missing packages, clean-up), Wi-Fi hotspot, start on boot (systemd) |
| [`docs/laptop-speaker.md`](docs/laptop-speaker.md) | The laptop as the robot's speaker until one is wired: `/speaker`, the Speaker box, `speaker_output` / `DESKBOT_SPEAKER` |
| [`docs/error-recovery.md`](docs/error-recovery.md) | Errors explained instead of tracebacks: `.venv` auto-switch, missing-package install offer, menu keeps running, saved tracebacks |
| [`docs/deskbot.md`](docs/deskbot.md) | The full app: commands, scripts, CLI, package layout, server, threads, tests, install |
| [`docs/runtime.md`](docs/runtime.md) | Four processes on four cores: scheduling, shared memory, newest-command-wins, detect-every-N, face the user |
| [`docs/benchmark.md`](docs/benchmark.md) | Benchmarks: lighting and tracking tests plus the open-source suite in `benchmarks.py` |
| [`docs/slim-dependencies.md`](docs/slim-dependencies.md) | numpy instead of scipy, whisper.cpp instead of faster-whisper, Claude over HTTPS, what setup removes, sizes |
| [`docs/ncnn-detector.md`](docs/ncnn-detector.md) | YOLO26n on NCNN without PyTorch: every step, ByteTrack in numpy, export in a temporary venv, sizes, verification |
| [`docs/vision.md`](docs/vision.md) | Camera + YOLO26n (NCNN) + ByteTrack: research, latency design, model export, geometry, measurements |
| [`docs/fusion.md`](docs/fusion.md) | Geometric / semantic / heatmap maps: maths, staleness, sensor fusion, tunables, verification |
| [`docs/order.md`](docs/order.md) | Build order |
| [`docs/components.md`](docs/components.md) | Parts list |
| [`docs/pins.md`](docs/pins.md) | Full wiring |
| [`docs/hardware-test.md`](docs/hardware-test.md) | `hardware_test.py`: every hardware test in one file, design, standalone pins |
| [`docs/sensor-tests.md`](docs/sensor-tests.md) | Sensor test: menu, live readings, what to look for |
| [`docs/camera.md`](docs/camera.md) | Camera test: terminal image rendering, troubleshooting |
| [`docs/robot-shell.md`](docs/robot-shell.md) | `robot_shell.py`: every command, units, find/goto/home maths, safety, inline display |
| [`docs/e2e-test.md`](docs/e2e-test.md) | `test_e2e.py`: standalone run of every feature, what each shows, safety, sim |
| [`docs/microphone.md`](docs/microphone.md) | Electret mic: how to connect it, the mic test, troubleshooting |
| [`docs/config.md`](docs/config.md) | `robot_config.py`: pin config, who reads it, validation |
| [`docs/pi.md`](docs/pi.md) | Pi setup, testing, GPIO notes |
| [`docs/software-stack.md`](docs/software-stack.md) | Software used |
| [`docs/mapping.md`](docs/mapping.md) | Occupancy grid mapping: design, maths, threading, API, tests |
| [`docs/multisonar.md`](docs/multisonar.md) | Four ultrasonic sensors: wiring, safety rules, code, tests |
| [`docs/simplified-code.md`](docs/simplified-code.md) | One-file CLI + dashboard: commands, safety, map, camera, errors |
| [`docs/encoders.md`](docs/encoders.md) | Wheel encoders: wiring, calibration, odometry, stuck-wheel detection |
| [`docs/chasis.md`](docs/chasis.md) | Chassis design notes |

## Future improvements

- **More cameras**: a rear or side camera, or a wide-angle one, to see behind the robot and cover blind spots.
  The semantic map already takes observations from any calibrated camera model.
- **Cooling**: a heatsink and fan, or the official active cooler. The Pi 4 throttles at 80 °C, and sustained
  inference on one core heats it. `scripts/doctor.sh` shows the temperature.
- **Built-in microphones and speakers** for voice commands and spoken replies. Local speech recognition
  (e.g. Vosk / whisper.cpp) keeps it free of API costs.
- **Lighting**: an LED ring or IR illuminator by the camera. The benchmark shows how much detection drops in dim
  and dark light.
- **A microcontroller for the low-level work** (e.g. RP2040 / ESP32 / Arduino). It would run motor PWM, the safety
  stop, the encoders and the ultrasonic timing in hard real time. The Pi would only send high-level commands over
  UART/I2C. The Pi then keeps all four cores for vision and navigation, and the safety stop no longer depends on
  Linux scheduling.
- **Wheel encoders** (pins already reserved, see [`encoders.md`](docs/encoders.md)) for odometry that
  doesn't drift.
- **A time-of-flight or LiDAR sensor** alongside the sonars, to settle sonar-vs-glass disagreements.
