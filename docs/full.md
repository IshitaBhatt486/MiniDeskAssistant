# The full robot: every feature, each switchable (19 Nov 2026)

```bash
cd run_prototype
python main.py full --sim        # any computer       ·   on the Pi: bash scripts/full.sh
python main.py help              # every feature and voice command, in the terminal (python main.py help guard, help cli, ...)
```

`main.py full` is a **new runtime**: the hub robot ([hub.md](hub.md)), and through it the buddy ([buddy.md](buddy.md))
and companion, plus everything in this document. The older runtimes still work as before. To run it without the
internet, see [local-only.md](local-only.md).

| file | what |
| --- | --- |
| `deskbot/full/app.py` | runtime, routes (`FullHandler`), `build()` (constructs every part) |
| `deskbot/full/core.py` | `Full`: sentence handling, tools, routine steps, Telegram commands, the vision and tick loops, switches |
| `deskbot/full/features.py` | `CATALOG` (every feature, for help + dashboard), `FeatureFlags`, `FeatureOff`, `help_text()` |
| `deskbot/full/wake.py` | "Hey Pip": microphone stream, Vosk / Whisper detectors, request recording |
| `deskbot/full/routines.py` | voice routines: JSON files, validation, matching, the runner, AI tools |
| `deskbot/full/smarthome.py` | Home Assistant, Shelly, Tasmota |
| `deskbot/full/reader.py` | read this for me: local vision model / Tesseract / Claude, files, summaries |
| `deskbot/full/local_llm.py` | Ollama client, `OllamaBrain` |
| `deskbot/full/rps.py` | rock, paper, scissors |
| `deskbot/full/hydration.py` | drinks seen and reminders |
| `deskbot/full/briefing.py` | morning and evening briefings |
| `deskbot/full/faces.py` | owner recognition (YuNet + SFace) |
| `deskbot/full/guard.py` | guard mode |
| `deskbot/full/telegram.py` | the Telegram bot |
| `deskbot/full/config.py` | `data/full.json` settings |
| `web/static/full_cards.html`, `full.js`, `full.css` | 12 dashboard cards |
| `tests/test_full.py` | 26 tests |

Small hooks added to the existing code (each documented where it is defined):

- `assistant/brain.py`: `Brain.pre_handlers` (tried first) and `Brain.fallback_brains` (after the local rules)
- `assistant/core.py`: `handle_text(..., speak=False)`, so Telegram replies aren't spoken at the desk
- `assistant/tools.py`: `ALLOW_INTERNET`
- `hub/app.py`: `run_hub(handler_cls=, on_ready_extra=)`
- `companion/cli.py`: the `full` and `help` commands
- `requirements-assistant.txt`: `vosk`; `scripts/setup.sh`: `tesseract-ocr`

## How a sentence is answered

| order | what | cost |
| --- | --- | --- |
| 1 | **pre-handlers** (`Full.pre_handler`): "switched off" replies, a spoken game move, routine phrases, smart-home device sentences, game / briefing / water / guard / face / reading sentences | free, instant |
| 2 | plain robot commands ("turn left") | free |
| 3 | Claude (if on, and under the daily cap) | paid |
| 4 | local sentence rules (ideas, tasks, focus, music, calendar) | free |
| 5 | the local AI (Ollama, if on and reachable) | free |
| 6 | the keyword rules | free |

## Features and switches (`features.py`)

`CATALOG` has one row per feature: key, title, group, what it does, example commands, where it is on the
dashboard, whether it needs the internet, and its default. It produces `python main.py help`, the Features card
and local-only mode.

- **Where the switches live:** new switches are saved in `data/features.json`. Older features use "adapters" onto
  the setting that already controls them:

  | switch | setting it controls |
  | --- | --- |
  | sound effects | assistant `sounds` |
  | gestures | `GestureController.enabled` |
  | phone notifications | buddy `notify.enabled` |
  | notification AI | buddy `notify.use_ai` |
  | celebrations | buddy `tasks.celebrate` |

- **Where they're checked:** where each feature acts, so a change takes effect at once:
  - a switched-off feature's Claude tools answer "… is switched off" (`TOOL_FEATURE`)
  - its sentences get a "switched off" reply instead of falling through to an AI that might pretend
  - Spotify, Calendar and focus methods raise `FeatureOff`, a subclass of `AccountError`, so the existing handlers
    already turn it into a message
  - the loops idle
- **Defaults:** guard mode and Telegram are off until you switch them on.
- **PIN:** switching guard, owner recognition, Telegram or local-only needs `ADMIN_PIN`.

## "Hey Pip" (`wake.py`)

- **The phrase** is "hey" plus the robot's name (assistant settings `robot_name`).
- **Detectors**, tried in order:
  1. **Vosk** in grammar mode. The recogniser may only output `["hey pip", "pip", "[unk]"]`, which makes it tiny
     and fast and needs no training. The model (`vosk-model-small-en-us-0.15`, 40 MB) downloads on first use. If
     the robot's name isn't in Vosk's vocabulary, the card says so.
  2. **Whisper** as a fallback. Speech bursts of up to 2.5 s go to the local Whisper (whisper.cpp). "Hey Pip, what time
     is it" in one breath works, because the words after the name become the request.
- **Audio:** `arecord` (the robot's mic; `DESKBOT_MIC_DEVICE` overrides it) or `sounddevice`, 16 kHz, in 30 ms frames.
- **After the wake word:** the `recognition` motif plays and the eyes turn curious. The request is then recorded:
  - the first 0.24 s measures the room's noise level
  - speech is anything louder than max(350, 3× that level)
  - recording ends after 0.8 s of quiet; if nobody starts talking within 4 s, it gives up; 8 s at most
  - time is counted in audio frames, so it stays exact

  The recording goes to `Assistant.handle_audio`, exactly like the dashboard's mic button.
- **Self-hearing:** while the robot speaks, has speech queued, or is within 1.2 s of its chime, the microphone is
  ignored.
- **Sharing the mic:** `pause()`/`resume()` let go of it for the robot-mic button and guard mode's question.
- **Simulation:** the Wake word card's "Say 'Hey Pip, …'" works without a microphone.

## Voice routines (`routines.py`)

- **Storage:** one JSON file per routine in `data/routines/`. The format is in the module docstring, which also
  shows an example.
- **Triggers:** phrases of 2+ words, matched whole, ignoring case and punctuation. "run X" and "start the X routine"
  work too. Two routines can't share a phrase.
- **Events:** `arrive` / `leave` (your phone, via presence), `focus_end`, `time:HH:MM` (checked once a minute).
- **Steps:**
  - say, sound, wait (1–60 s), commands (robot actions), emotion
  - focus, focus_stop, spotify (query or action), smart_home (device, action, value)
  - briefing, telegram, guard, task, water

  At most 20 steps. A routine can't start another routine, so there are no loops.
- **Validation:** checked by `validate()` before saving and on every load. A broken file is listed with its problem
  on the card and skipped.
- **Running:**
  - routines run on a thread, one at a time; "stop the routine", or a new routine, cancels the rest
  - a failing step is recorded (the card shows each step's result), and the routine goes on with the next step
  - a `guard {on: false}` step only disarms when the owner is recognised
- **Examples** written the first time: `study-time.json` (lamp on, lo-fi, 50 minutes of focus) and
  `break-time.json` (focus off, music paused, a dance).
- **Making them:**
  - by voice through Claude ("make a routine called movie night that …", `create_routine` with `steps_json`;
    validation errors go back to Claude so it can fix them)
  - on the dashboard (a JSON editor, run, enable, delete)
  - by editing the files and pressing reload

## Smart home (`smarthome.py`)

- **Devices:** `data/smart_home.json`, managed with the dashboard's *Add a device*.
  - **Home Assistant:** an `entity_id` of a light, switch, fan or input_boolean, plus `HA_URL` and `HA_TOKEN` (a
    long-lived token) in `secrets.env`. *Find Home Assistant devices* lists them.
  - **Shelly Gen2+ (RPC), Shelly Gen1, Tasmota:** an IP address or `name.local`.
- **Voice:**
  - "turn on/off the X", "X off", "set the X to 30 percent", "dim the X", "is the X on?"
  - these are matched before the robot's own commands, but only when a known device name (or alias) is in the
    sentence, so "turn left" still moves the robot
  - the AI has a `smart_home` tool
- **Safety:**
  - only private-network addresses (or `.local`) are accepted for devices and Home Assistant
  - Home Assistant entities are limited to lights, switches, fans and input booleans, so no locks or alarms
  - the token is never shown; 4 s timeouts
- **No cloud:** the robot talks to the devices directly.

## Read this for me (`reader.py`)

- **The picture:**
  - the robot camera ("read this for me"; 320×240, so only for big print held close)
  - a dashboard upload (on a phone, the button opens the camera)
  - a Telegram photo
- **Reading** (settings `reader.ocr`, default `auto`, local first):
  1. a local vision model (`qwen2.5vl:3b` through Ollama)
  2. Tesseract
  3. Claude vision (skipped when the AI is off or in local-only mode)

  Each backend's failure is collected, and the error lists them all.
- **Summary or flashcards:** "summarise this", "make flashcards from this", or the dropdown. They use the local AI,
  else Claude.
- **Files:** `data/reads/<date>_<time>.txt`, plus `.summary.txt` or `.flashcards.txt`.
- **Speaking:** the first ~2,500 characters are read aloud in sentence chunks (the speaker keeps 6 at most), then it
  says the rest is saved.
- **Time:** reading runs on a thread, because a cold local model can take minutes. File names are checked, so only
  plain `*.txt` names inside the folder can be downloaded.

**Can you use a local text model?** Yes, and it's the default when Ollama is set up:
- `qwen2.5vl:3b` read a test image exactly in 4 s once loaded (154 s the first time on the 8 GB laptop)
- Tesseract is the light local option
- details and timings are in [local-only.md](local-only.md)

## Local AI (`local_llm.py`)

`OllamaBrain` is a fallback brain: Claude off, missing, failing, or over its daily cap → the local model.

- It gets a short system prompt (the robot's name, moods, the action list, no internet), the last 4 exchanges, and
  the robot context.
- Ollama's structured output (`format` = a JSON schema) makes it answer in the robot's reply format.
- It has no tools; the local sentence rules come first.
- `OLLAMA_URL` must be on your own network.
- It waits 45 s at most; vision reading waits `local_llm.vision_timeout_s` (300 s by default).

## Rock, paper, scissors (`rps.py`)

- **Starting:** "let's play rock paper scissors" starts a best of three.
- **Each round:**
  - the robot says "Rock, paper, scissors, shoot!"
  - once the speaker is done, it watches the hand gestures for 2 s: fist = rock, open palm = paper, Victory (peace
    sign) = scissors
  - or you can say a move
- **The result:** the robot says its move and who won, with ta-da / sad trombone / boing, and the eyes react. If it
  sees nothing it asks once more, then gives up.
- **Gestures:** their normal actions (a fist stops the robot) are paused during a game.
- **The robot's choice:** random, but half the time it plays what beats your most frequent move.
- **Winning:** you get a celebration; when the robot wins, it dances.

## Hydration buddy (`hydration.py`)

- **Seeing a drink**, at 2 Hz (YOLO bottle / cup / wine glass):
  - **raised:** a container overlaps the top 35 % of your person box for 0.6 s
  - **lifted:** a container that sat in one place vanishes for 2–40 s and comes back within 60 px
  - either counts once per 2 minutes
- **Counting one yourself:** "I drank some water" or the +1 button.
- **Reminders:**
  - after `interval_min` (45) without a drink, while you're at the desk, between 08:00 and 22:00
  - never during focus mode (it waits for the break)
  - then every 30 minutes
- **Storage:** `data/hydration.json`, 60 days; the card shows a week of bars.

## Briefings (`briefing.py`)

- **Morning:** greeting (with your name), weather (today's high, rain if 40 %+), the calendar's first event, what's
  due today, overdue count, and a nudge to start a focus session.
- **Evening:** tasks finished, focus time, ideas saved, drinks, what's still open with the next deadline, and
  tomorrow's first event.
- **Missing parts:** a source that's switched off or fails is simply left out.
- **No AI:** they're built from templates, so they're free and instant.
- **When:**
  - automatically once a day each: the first time you're at the desk after 08:00 (until noon) and after 21:00
  - on request: "good morning" (before noon, which also wakes the robot), "brief me", "how was my day?", or the
    card's buttons
- **Telegram:** also sent there if paired (`briefing.telegram`).

## Owner recognition (`faces.py`)

- **The models:** YuNet finds faces; SFace (37 MB, downloaded once) turns each one into 128 numbers. Two faces match
  at a cosine similarity of 0.363 or more, OpenCV's published threshold.
- **Learning a face:**
  - "learn my face" takes ~8 s, sampling every 0.4 s while exactly one clear face (≥ 60 px, score ≥ 0.8) is in view
  - it needs at least 8 samples and keeps up to 20
  - "this is Arjun, learn his face" adds a friend
  - there's only one owner at a time
- **What's stored:** only the numbers, never a picture, in `data/faces/people.json` (0600). They aren't sent to
  Claude, Telegram or anywhere.
- **What it's used for:**
  - "Welcome back, <name>!" after 30+ minutes away
  - guard mode disarms when it sees the owner
  - the AI's context names who's at the desk
- **It's a convenience, not a lock:** a good photo could fool it, and 320×240 limits it to about a metre in front
  of the camera.
- **Voice rules:**
  - "learn my face" only works when no owner is enrolled yet, or the owner is recognised right now, and never
    while guarding (so a visitor can't make themselves the owner)
  - "forget my face" needs the owner in view
  - the dashboard needs the PIN

## Guard mode (`guard.py`)

- **Arming:** "guard my desk", the card, Telegram `/guard on`, a routine step, or automatically when your phone
  leaves (`guard.auto_arm`, off by default).
- **When someone shows up:** a person box (score ≥ 0.6, ≥ 4 % of the image) for 1.5 s while armed. Then the robot:
  1. turns to them and says: "Hi! I'm guarding this desk for my owner. Who are you? Please say your name."
  2. listens 5 s with the robot mic (the wake word lets go of it)
  3. if they say the passphrase → it disarms
  4. otherwise → "Thanks! I'll take a quick photo for my owner." → a snapshot to `data/guard/` + Telegram, with
     what they said
- **Limits:** a 2-minute cool-down, at most 10 photos an hour, deleted after 7 days.
- **Disarming:** seeing the owner, your phone coming back (when it was armed by the phone leaving), the passphrase,
  Telegram, or the dashboard with the PIN. A visitor saying "stop guarding" isn't enough. The AI can arm it but not
  disarm it.
- **Photos** are announced (nobody is photographed secretly), viewed on the dashboard only with the PIN, and never
  sent to Claude.
- **The passphrase** is changed with the PIN and is never sent to the browser.

## Telegram bot (`telegram.py`)

1. **Set up:** @BotFather → `/newbot` → `TELEGRAM_BOT_TOKEN=...` in `secrets.env`.
2. **Pair:** the Telegram card → *Pair my chat* (PIN) shows a 6-digit code, valid 10 minutes and single use. Send
   `/pair 123456` to your bot.

**Who it answers:**
- Only paired chats (`data/telegram.json`).
- Anyone else gets one "this robot is private" reply an hour, then nothing.

**How it connects:**
- No port forwarding: long polling (`getUpdates`, 25 s), outbound HTTPS to api.telegram.org only.
- The token is scrubbed from every error and status.

**Commands:**
- `/tasks`, `/add <task>` (deadlines understood), `/done <task>`
- `/idea <text>`, `/ideas`
- `/brief`, `/focus [min]`, `/stopfocus`
- `/guard on|off`, `/photo` (the desk now)
- `/water`, `/say <text>` (spoken at the desk), `/status`
- a photo is read and the text sent back (caption "summary" or "flashcards" for those)
- any other text is answered by the assistant without being spoken aloud (`telegram.speak_replies`)

**Outgoing:** guard alerts, briefings, and the `telegram` routine step.

## Security summary

| what | protection |
| --- | --- |
| changing guard, faces, Telegram pairing, local-only, viewing guard photos | `ADMIN_PIN` (5 wrong → 5 min lockout) |
| a visitor taking over | can't stop guard mode or enrol a face by voice; the AI can't disarm |
| secrets | passphrase, bot token, HA token, face numbers: never in any API response or log |
| network | smart home and Ollama only on private addresses; Telegram only api.telegram.org |
| privacy | camera frames are processed in memory; guard photos are announced, PIN-protected and deleted after 7 days; face data is numbers only |

The rest of the dashboard has no login (README, "Security"), so use a trusted Wi-Fi or the robot's own hotspot.

## Settings (`data/full.json`)

| setting | default |
| --- | --- |
| `owner.name` | "" |
| `briefing.auto` / `morning_time` / `evening_time` / `telegram` | true / 08:00 / 21:00 / true |
| `hydration.interval_min` / `goal` / `start` / `end` | 45 / 8 / 08:00 / 22:00 |
| `reader.ocr` / `speak` | auto / true |
| `local_llm.text_model` / `vision_model` / `vision_timeout_s` | llama3.2:3b / qwen2.5vl:3b / 300 |
| `guard.passphrase` / `auto_arm` (PIN) | "" / false |
| `telegram.speak_replies` | false |

## Verified (laptop, simulation, 19 Nov 2026)

- **Tests:** `tests/test_full.py`, 26 tests; the whole suite passes.
- **`python main.py full --sim` on ports 8125/8126:**
  - "study time" ran the routine: say ok, sound ok; smart home and Spotify failed because nothing was set up; focus
    ok
  - rock-paper-scissors played a voice round
  - "I drank some water", "brief me" and "how was my day" all worked
  - "turn on the desk lamp" reached the Shelly path (timed out: no device), and "turn left" still turned
  - switched-off guard and hydration gave "switched off" replies
  - a wrong PIN → 403
  - with the PIN, guard turned on; a visitor's "stop guarding" was refused; dashboard disarm worked
  - the passphrase never appears in `/api/full`
  - the Wake word card's simulate path ran a request
  - the cards render (headless Edge)
- **Local AI:** `OllamaBrain` (llama3.2:3b) answered "spin around twice…" with a valid spin command; `qwen2.5vl:3b`
  transcribed a test image exactly.
- **Not verified here:**
  - Vosk and arecord (no microphone tools on the laptop: the card says so)
  - SFace and YuNet on real faces, hydration and guard on real people (the laptop webcam is dark)
  - Telegram with a real bot, Home Assistant / Shelly / Tasmota hardware
  - anything on the Pi
