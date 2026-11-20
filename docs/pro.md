# The pro robot (20 Nov 2026)

```bash
cd run_prototype
python main.py pro --sim         # any computer      ·   on the Pi: bash scripts/pro.sh
python ../tools/sim_console.py --mode pro --script ../tools/sim_scenarios/pro.txt     # end-to-end check
python3 hardware_tests/test_touch.py                                                  # the touch pads, on the Pi
```

`main.py pro` is a **new runtime** on top of the full robot ([full.md](full.md)), which still runs as before. It adds:

1. a configurable dashboard (add, remove and drag cards) with light / dark mode and a sleeker look
2. headpats from three TTP223 touch pads
3. more from the MPU-6050: knock, bump, shake, tipped over, dropped
4. a voice studio: independent pitch and speed, loudness, voice type, the engine's own voices, personality profiles
5. Groq as the first AI brain, with Claude as its fallback
6. view-only **Accounts** and live **APIs in use** cards

The speaker (red/black wires) isn't configured yet: that was postponed. See [Speaker](#speaker-not-configured-yet).

| file | what |
| --- | --- |
| `deskbot/pro/app.py` | runtime, routes (`ProHandler`), `build()` (constructs and wires every part), page builder |
| `deskbot/pro/core.py` | `Pro`: touch and motion reactions, profile voice commands, context lines, status |
| `deskbot/pro/touch.py` | `TouchSense`: GPIO reading and touch classification (pat, hold, streak, stroke) |
| `deskbot/pro/motion.py` | `MotionDetector` (pure event rules) and `MotionSense` (shared-memory reader, test injection) |
| `deskbot/pro/groq_brain.py` | `GroqClient` (HTTP), `GroqBrain` (tool loop, JSON reply, repair round) |
| `deskbot/pro/profiles.py` | personality + voice profiles |
| `deskbot/pro/apis.py` | accounts (masked keys, linked accounts) and the APIs-in-use inventory |
| `deskbot/pro/config.py` | `data/pro.json` settings |
| `web/static/layout.js` | layout manager + theme switch |
| `web/static/pro_cards.html`, `pro.js`, `pro.css` | the 6 new cards and the sleeker skin |
| `hardware_tests/test_touch.py` | standalone pad test |
| `scripts/pro.sh` | start on the Pi |
| `tests/test_pro.py` | 51 tests |

Small hooks in existing code (each commented where it is defined):

- `assistant/brain.py`: `Brain.primary_brains` (tried before Claude), `Brain.order()`, `status()` reports the order and the model
- `assistant/voice.py`: `time_stretch`, `pitch_shift`, `process(pitch=, speed=)`; engines got `speed`, `voice_name`, `voices()`; `Speaker.voices()`
- `assistant/settings.py`: `voice_pitch`, `voice_speed`, `voice_name`
- `full/app.py`: `run_full(handler_cls=, on_ready_extra=)`
- `hub/costs.py`: Groq model prices, and a Groq row in the services list
- `companion/cli.py`: the `pro` command and menu entries
- `robot_config.py`: `TOUCH` pins (checked for conflicts with everything else)
- `scripts/setup.sh`: serial console off (GPIO 14)
- `web/static/fusion.js`, `dashboard/static/app.js`: redraw cached map colours on the `deskbot-theme` event

## 1. Configurable dashboard (`layout.js`)

The page is still the full robot's page with the pro cards added (51 cards). `layout.js` runs last and turns every
`<section class="card">` in `<main class="grid">` into a managed card:

- **Key**: the card's `id`, or `c-` + its title slugged (`Status` → `c-status`). Duplicates get `-2`.
- **Toolbar** (sticky, under the top bar, blurred background):
  - **＋ Add a card…**: a dropdown of the hidden cards, grouped as Pro / Full robot / Hub / Buddy / Companion / Robot
    and sorted by title. Picking one shows it **at the top**, scrolls to it and flashes it.
  - **Customize**: edit mode. Every card shows its drag handle and remove button, with a dashed outline.
  - **Reset**: back to the defaults, after a confirmation.
  - a card count, and the **theme** switch (Auto / Light / Dark).
- **Per card**: **⠿** (drag) and **×** (remove) in the header. They appear on hover, always in edit mode, and always
  on touch screens. Removing shows "Removed *X* · Undo" for 6 s. The handle can also be moved with the arrow keys.
- **Drag and drop** uses pointer events, so it works with mouse, touch and pen. On `pointerdown` a placeholder the
  size of the card takes its place, and the card becomes `position: fixed` and follows the pointer, slightly
  rotated. On every move, the card under the pointer (`elementsFromPoint`, skipping hidden cards) gets the
  placeholder before or after it. Which side depends on which half the pointer is in: left/right for wide cards,
  top/bottom otherwise. Near the top or bottom edge the page scrolls 12 px per move. `pointerup` puts the card where
  the placeholder is and saves the order. `Escape` or `pointercancel` puts it back.
- **Saved** in the browser's `localStorage` as `deskbot.layout.v1` = `{order, hidden, known}`, so a phone and a
  laptop can have different layouts. Cards that appear in a later version (not in `known`) follow the defaults.
  Without storage (a private window) everything works for the session.
- **Defaults** (14 visible): Assistant, Voice studio, Touch & headpats, AI brain, Camera, Status, Drive, Warnings,
  Motion sense, Presence, Eyes, Tasks, APIs in use, Accounts. The older **Personality & voice** card is hidden by
  default, because the Voice studio replaces it. It still works if you add it back.
- Hidden cards get `lm-hidden` (`display: none`) but keep their scripts. `pro.js` skips polling hidden pro cards.
  Showing a card fires `resize` (so canvases size themselves) and `deskbot-card-shown`.

**Theme.** `document.documentElement.dataset.theme` = `light` / `dark`, or no attribute for Auto. Every colour is a
CSS custom property defined three times: for the system theme (`prefers-color-scheme`, unless `data-theme="light"`),
for `data-theme="dark"`, and the light default. The choice is saved as `deskbot.theme`, and a tiny inline script in
`<head>` applies it **before the first paint**, so dark-mode users never see a white flash. Changing the theme fires
`deskbot-theme`. The fusion maps and the occupancy map rebuild their cached colour tables on it. Every other canvas
reads its colours when it draws.

**Sleeker look** (`pro.css`, pro page only): cooler neutrals, one accent colour (indigo `#5b5bd6` / `#8f8ff7` dark),
14 px radius, soft two-layer shadows that lift on hover, sentence-case card titles, pill tags, consistent 9 px-radius
inputs with an accent focus ring, sticky frosted toolbar, `prefers-reduced-motion` respected. The older dashboards
keep their look.

## 2. Touch pads (`touch.py`)

**Wiring** (3× "Electronic Spices TTP223", VCC / I/O / GND):

| pad | I/O → | physical pin |
| --- | --- | --- |
| top | GPIO 7 | 26 |
| left | GPIO 8 | 24 |
| right | GPIO 14 | 8 |

All three: **VCC → 3.3 V** (pin 1 or 17) and GND → GND. The module works on 2.5–5.5 V, but its I/O pin outputs its
supply voltage, so at 5 V it would push 5 V into a 3.3 V GPIO. GPIO 7/8 are SPI chip-selects (SPI is off). GPIO 14 is
the UART TX pin, so `setup.sh` turns the serial console and UART off (`raspi-config nonint do_serial_cons 1`,
`do_serial_hw 1`). Don't touch the pads for ~0.5 s after power-up: the TTP223 calibrates its baseline then.

**Jumpers**: A open = output HIGH while touched (expected). B open = momentary. With B closed the pad is
self-locking (each touch flips the output): set **Pad type → Self-locking** on the card (`touch.mode = toggle`), and
every flip counts as one touch (no "long pat" in that mode).

**Reading**: one gpiozero `DigitalInputDevice(pin, pull_up=False, bounce_time=0.02)` per pad. The pull-down makes an
unplugged pad read "not touched". The callbacks only record edges. Classification runs under a lock, plus a 20 Hz
`tick()` for holds. Without GPIO (laptop, simulation) the pads exist only through `simulate()`, which the card's pad
buttons and `:touch` in the sim console use.

**What a touch means** (time-driven, unit-tested with a fake clock):

| event | rule | reaction (`core.py`) |
| --- | --- | --- |
| touch | any pad goes down | happy face at once; wakes a sleeping robot |
| pat | released before `hold_s` (1.2 s) | giggle chime + a random thank-you; a small `nudge` wiggle at most every 2 × `cooldown_s` |
| hold | still down after `hold_s`, reported once, while held | blushing face + contented sigh ("Mmm, that's nice") |
| pats | the 3rd pat (`pats_for_excited`) within 4 s on any pads | celebrating face + "Yay!" + `celebrate` move |
| stroke | left → top → right (or reverse) pressed within 1.5 s | happy face + "Ooh, that feels lovely" + nudge |

Speech is limited to once per `cooldown_s` (2 s) for pats. Movement happens only if *Wiggle* is on, the robot isn't
lifted and isn't already moving, and it still goes through every safety rule (a nudge at the desk edge is refused:
"blocked by a safety rule"). The AI's context gets "Headpats today: N". Settings: Touch card → Settings, saved in
`data/pro.json`.

**Is there a way to save pins?** Yes. These were offered before wiring, and you chose separate pins, which keeps
the pads distinguishable (the stroke needs that). For later:

- **Diode-OR onto one GPIO**: each I/O through a diode (1N4148, stripe toward the GPIO) to one pin with a pull-down.
  1 pin instead of 3, but no stroke or per-pad reactions. The outputs can't be tied directly: they are push-pull
  and would short against each other.
- **PCF8574 I2C expander** (~₹80): daisy-chained on the existing I2C bus with the MPU-6050 and OLED (address 0x20),
  0 new GPIO, 8 inputs. I2C is the "daisy chain" the robot already uses: both I2C devices share GPIO 2/3.
- **Elsewhere**: the four sonar TRIG pins could share one GPIO only if the sonars fire together, which causes
  crosstalk, so not recommended. Using only one channel per encoder frees 2 pins but loses direction (it can be
  inferred from the motor command).

After this, **GPIO 15** is the only free pin (`python3 robot_config.py` prints the table and checks for conflicts).

## 3. MPU-6050: what it already did, and what's new (`motion.py`)

It was already configured and in use: I2C bus 1 at 0x68 (shared with the OLED), read by the body process at 100 Hz,
Madgwick fusion, used for **pick-up detection, heading hold and turn-rate PID, the closed-loop "face the user", and
the tilting eyes** ([companion.md](companion.md)). Wiring: VCC → 3.3 V, GND, SDA → GPIO 2 (pin 3), SCL → GPIO 3 (pin 5).

New: event detection on the same samples, read from the shared-memory IMU block (`fresh_imu`) at ~100 Hz in a
thread. There is no second I2C reader. Each sample has `ax ay az` (m/s², robot frame), `gx gy gz`, `gyro_norm`
(rad/s), `tilt` (rad).

| event | rule (thresholds in `data/pro.json` → `motion`) | reaction |
| --- | --- | --- |
| knock | not driving, not lifted, gyro < 1.5 rad/s, \|a\|−g above `knock_ms2` (4) for **less than 90 ms** (a push lasts longer) | curious face, "Who's there?" |
| double_knock | a second knock within 0.6 s | wakes up, turns to face you |
| bump | driving, horizontal acceleration √(ax²+ay²) above `bump_ms2` (5) | **stop**, annoyed face, "Oof!" |
| shake | ≥ 3 sign reversals of the strongest gyro axis above `shake_rads` (4) within 1.2 s | dizzy (confused) face, "Whoa!" |
| tipped | tilt above `tip_deg` (60°) for 0.8 s **while the gyro is quiet** (< 0.6 rad/s: lying still, not being carried) | **stop**, scared face, a dashboard warning, asks for help |
| righted | after tipped: tilt below `tip_deg` − 15° for 1 s | warning cleared, "Phew, thank you!" |
| drop | \|a\| below 3 m/s² (free fall) for ≥ 60 ms | scared face + gasp |

Every event has a 2 s cool-down (tipped/righted are a pair instead). `MotionDetector.update()` is pure: sample,
time and driving/lifted in, events out. That is how it's tested, and the Motion card's buttons and `:imu` feed it
synthetic sequences (`MotionSense.inject`) at the current time, so live samples carry on seamlessly afterwards.
"Driving" = the executor is running a command. "Lifted" = the lift detector says so.

**Limits.** The body process configures a 44 Hz low-pass filter, which rounds off very short knocks, so lower
`knock_ms2` if real knocks are missed. The thresholds are starting points from the datasheet ranges (±4 g,
±500 °/s); tune them on the real robot.

## 4. Voice studio and profiles

**Pitch and speed are independent** (`voice.py`):

- **Speed**: every engine does it natively, which sounds cleaner than stretching: espeak-ng `-s 160 × speed` words
  per minute, Windows SAPI `Rate = round(log(speed) / log 1.1)` (−10…10), Piper `--length_scale 1/speed`. An engine
  without native speed falls back to `time_stretch`.
- **`time_stretch(x, rate, speed)`**: WSOLA. 40 ms Hann frames, overlap-added every 20 ms of output. Each frame is
  taken from near its nominal input position (`k × hop × speed`), shifted by up to ±10 ms to where it best continues
  the previous frame (cross-correlation with the natural continuation). The waveform stays phase-continuous, so
  there is no metallic phasing. Output is normalised by the summed window.
- **`pitch_shift(x, rate, semitones)`**: resample by f = 2^(st/12) (pitch and tempo × f), then `time_stretch` by 1/f
  to restore the duration.
- Order: engine (native speed, chosen voice) → voice type effect (chipmunk/deep/robot/radio/cave/natural) → pitch →
  normalise → loudness.
- Measured on a 220 Hz tone: speed 0.5 / 1.5 / 2.0 → 2.0 / 0.667 / 0.5 s at 220 Hz. Pitch −5 / +7 / +12 st → 165 /
  330 / 440 Hz, still 1.0 s. 1–13 ms per second of audio.

**Engine voices** (`Speaker.voices()`, cached): espeak-ng `--voices=en` (en-us, en-gb, en-gb-scotland, …; the gender
setting adds `+f3` / `+m3`), SAPI `GetInstalledVoices()` (e.g. Zira, David), Piper: every `models/piper/*.onnx`.
Chosen with `voice_name`.

**Settings** (assistant settings, `data/assistant.json`): `voice_pitch` −12…+12 semitones, `voice_speed` 0.5…2.0,
`voice_name`, plus the existing `volume` (loudness), `voice_style`, `voice_gender`, `chipmunk_factor`. The card
saves each change through the existing `POST /api/assistant/settings` (250 ms debounce), and **Test voice** speaks
the test sentence.

**Profiles** (`profiles.py`): a profile = personality text + every voice setting. Built-in: Cheerful helper
(chipmunk), Sarcastic sidekick (robot, −2 st), Calm butler (natural, −3 st, 0.85×), Pirate (deep, 0.9×). **Save as
profile…** stores the current settings under a name in `data/profiles.json` (max 30; names are letters, digits,
spaces and `. , ' & -`). Built-ins can be overwritten but not deleted. Applying writes the keys into the assistant
settings, which the brain and speaker read on every turn, so the switch is immediate. By voice, answered before the AI
(so it works offline): "switch to the pirate profile", "use the calm butler personality", "change to sarcastic
sidekick mode", "which profile are you using?". A sentence that doesn't name a profile ("switch to focus mode", "use
a deeper voice") passes through to the other handlers.

## 5. Groq first, Claude as fallback (`groq_brain.py`)

**Order** for a sentence: routines / smart home / games / profiles (pre-handlers) → plain robot commands (local) →
**Groq** → **Claude** → local sentence rules → local AI (Ollama) → offline keyword rules.

- **API**: OpenAI-compatible `POST https://api.groq.com/openai/v1/chat/completions`, `Authorization: Bearer
  GROQ_API_KEY` (the same key as Whisper), standard library only, 25 s timeout.
- **Model**: `openai/gpt-oss-120b` by default (a Groq production model with tool use and JSON mode, $0.15 / $0.60 per
  million tokens; a free-tier key with no card can't be charged). Changeable on the AI brain card: `openai/gpt-oss-20b`
  is faster, and the Llama models also work. gpt-oss models get `reasoning_effort: low` for voice latency. Models
  were checked against console.groq.com/docs/models on 20 Nov 2026.
- **Prompt**: exactly Claude's system prompt (actions, sounds, personality, add-on instructions such as tasks), plus
  "answer with ONE JSON object" and the reply schema. The last 6 exchanges go along, then the robot context and
  the sentence.
- **Tools**: the same as Claude's (weather, time, Wikipedia, jokes, currency, robot status, plus add-on tools such as
  tasks), converted to OpenAI function format, at most 4 rounds. Each call is answered with a `tool` message.
- **Reply**: the JSON object is extracted (a ```json fence or text around it is tolerated). If there is none, one
  **repair call** with `response_format: json_object` rewrites it, and if that fails too, the text is spoken as is.
- **No pictures**: none of Groq's production models takes images. A turn that needs the camera frame goes to Claude
  when Claude is available. Otherwise Groq answers from the on-board detections, which always go along as text.
- **Failure** (no key, 401, 429, 5xx, timeout): a dashboard warning "Groq isn't answering (reason), using Claude", not
  spoken, then Claude answers the same turn. If Claude also fails, the local brains answer.
- Groq obeys the **AI brain** feature switch and **Local only** mode, like Claude. Its usage goes into the cost meter.
- Without any key the warning says to add a free `GROQ_API_KEY`.

## 6. Accounts and APIs in use (`apis.py`)

**Accounts** (view only, as you asked): every key the robot knows about (`GROQ_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `HA_URL`/`HA_TOKEN`, Google and Spotify client ids, `OLLAMA_URL`, `ADMIN_PIN`,
`ACCOUNTS_KEY`, `NOTIFY_TOKEN`): what it's for and whether it's set. A key is shown masked as its type prefix plus its
last 4 characters (`gsk_…a91f`), a URL as scheme + host + port only, and PINs and encryption keys only as "set". The
full value never leaves the robot (tested). Plus the linked accounts (Google, Spotify: connected, which account,
granted scopes, last error) and Telegram (bot name, paired chats). To change anything, edit `secrets.env` on the
robot and restart: the dashboard can't.

**APIs in use** (refreshed every 5 s), grouped:

- AI brain: each brain in order, "in use" for the first and "fallback" for the rest, with the model and answers
  counted
- Speech to text: the backends in order
- Voice: the TTS engine, voice and player
- Wake word, local AI (Ollama reachable?), Telegram, smart home, linked accounts
- Free web tools (Open-Meteo, Wikipedia, jokes, currency): counted from each turn's tool calls

## Speaker (not configured yet)

A bare speaker (red/black) can't be driven from a GPIO pin. It needs an amplifier: e.g. a PAM8403 (5 V) fed from the
Pi's 3.5 mm jack, or the USB sound card's output (red = tip, black = sleeve). Every free PWM-capable pin is already
in use (GPIO 12/13 motors, 18/19 sonar and IR), so I2S amps (MAX98357A: GPIO 18/19/21) don't fit without rewiring.
Speech already plays through whatever ALSA device `DESKBOT_AUDIO_DEVICE` names, so once the speaker is connected the
only change is that variable.

## Verified (laptop, simulation, 20 Nov 2026)

- **Tests**: `tests/test_pro.py`, 51 tests (touch classification, every IMU event and its false positives, Groq
  reply / tool round / repair round / errors, the brain order and fallback, pitch and speed accuracy, native engine
  speed, profiles and voice commands, settings ranges, key masking, the page and the pins). The whole suite passes
  (327).
- **End to end** (`tools/sim_scenarios/pro.txt` against `main.py pro --sim`), all expectations passed:
  - pat → pat; 1.6 s → long pat
  - left → top → right → stroke + pat streak + celebrate
  - knock, shake
  - tip over → stop; bump → stop
  - "switch to the pirate profile" → switched; "which profile" → Pirate
  - "turn left 45" still local
- **Layout manager in a real browser** (headless Edge, a test harness on the real page): 14 default cards; remove
  and undo; the add dropdown lists the 37 hidden cards and shows a picked one at the top; saved to localStorage;
  pointer drag moves a card to the right place and Escape cancels; dark/auto theme; edit mode; reset.
- **Screenshots**: light and dark, every default card readable.
- **Not verified here**:
  - real TTP223 pads and real knocks / bumps on the MPU-6050 (the Pi): start with `hardware_tests/test_touch.py`,
    then tune the motion thresholds
  - a real Groq call (no key on the laptop): the request format follows Groq's OpenAI-compatible API and is checked
    with a fake client
  - espeak-ng and Piper voice lists (Linux)
