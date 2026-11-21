# Running the robot completely locally (no internet, no cloud, no API costs)

Everything the robot needs can run on the Pi, or on the Pi plus a laptop on the same Wi-Fi. Nothing leaves your
network, and nothing costs money.

## The short version

```bash
cd run_prototype
bash scripts/setup.sh                          # once: also installs Tesseract and the local speech packages
python main.py full --lan                       # start
```

Then in the dashboard:

1. Open the **Features** card and tick **Local only** (it asks for `ADMIN_PIN`). Every feature marked 🌐 switches
   off together; their own on/off choices are remembered for later.
2. Make sure speech-to-text is **local** (the default; *Personality & voice* card).
3. For a smart brain instead of the keyword rules, set up the local AI (below). Otherwise the robot still
   understands every built-in sentence: commands, tasks, ideas, focus, routines, smart home, games and more.

Before switching to local only, download the models once while you're still online. They are fetched
automatically the first time each feature is used, or you can start `python main.py full` with internet once and
use each feature.

| model | size | used by | file |
| --- | --- | --- | --- |
| YOLO26n (NCNN) | 6 MB | the camera | `models/` (`python main.py model export`) |
| Whisper `tiny.en-q8_0` (whisper.cpp) | 44 MB | speech-to-text | `models/whisper/` |
| Vosk small English | 40 MB | "Hey Pip" | `models/vosk-model-small-en-us-0.15/` |
| YuNet face detector | 0.2 MB | focus mode, faces | `models/face_detection_yunet_2023mar.onnx` |
| SFace face recogniser | 37 MB | owner recognition | `models/face_recognition_sface_2021dec.onnx` |
| Piper voice (optional) | 20–60 MB | a natural voice | `models/piper/*.onnx` (espeak-ng works without it) |
| Ollama models (optional) | 1–3 GB | local AI brain, reading | `ollama pull ...` (below) |

## What changes in local-only mode

| feature | online | local only |
| --- | --- | --- |
| Understanding you | Claude | **local AI (Ollama)** if set up, else the built-in sentence rules |
| Speech-to-text | local Whisper (default), or Groq | local Whisper |
| Voice | espeak-ng / Piper (always local) | same |
| "Hey Pip" | Vosk on the robot (always local) | same |
| Camera, maps, navigation, focus, faces, guard, hydration, games | on the robot (always local) | same |
| Read this for me | local vision model → Tesseract → Claude | local vision model → Tesseract |
| Summaries / flashcards | local AI → Claude | local AI only |
| Phone notifications | rules + Claude for unclear ones | rules only |
| Tasks, ideas, routines, briefings | local | local (no weather or calendar in the briefing) |
| Smart home | Home Assistant / Shelly / Tasmota on your Wi-Fi (always local) | same |
| Weather, Wikipedia, jokes, exchange rates | free web APIs | **off** |
| Google Calendar, Spotify, Telegram | their servers | **off** |

How it's enforced, so nothing slips through:

- **Local only** makes every 🌐 feature report "off" (`FeatureFlags.on`).
- The web tools refuse to make requests (`assistant/tools.py` `ALLOW_INTERNET`).
- Claude reports itself unavailable, and model downloads are refused.
- The local AI only accepts a server on your own network: `OLLAMA_URL` must be localhost, a private IP or a
  `name.local`.

## The local AI (Ollama)

[Ollama](https://ollama.com) runs open models on your own computer. It's free, needs no account, and works offline.

**On a laptop (recommended: much faster):**

```bash
# on the laptop, once
ollama pull llama3.2:3b        # the brain (2 GB)
ollama pull qwen2.5vl:3b       # reading pages (3.2 GB)
# let the robot reach it: start Ollama listening on your network
OLLAMA_HOST=0.0.0.0 ollama serve          # Windows PowerShell: $env:OLLAMA_HOST="0.0.0.0"; ollama serve
```

Then on the robot add `OLLAMA_URL=http://<laptop-ip>:11434` to `secrets.env` and restart. The *Local AI* card shows
the models it found.

**On the Pi itself:** `curl -fsSL https://ollama.com/install.sh | sh`, then `ollama pull llama3.2:1b` (or
`qwen2.5:1.5b`), and set the *Text model* on the Local AI card. It works, but expect 5–20 s a reply on a Pi 4, and
reading pages with a vision model isn't practical there (use Tesseract, or the laptop).

**Measured on the development laptop** (8 GB RAM, CPU only, 19 Nov 2026):

| | first time (loading) | after that |
| --- | --- | --- |
| `llama3.2:3b` reply (robot JSON) | 42 s | ~6 s |
| `qwen2.5vl:3b` reading a 2-line image | 154 s | ~4 s |

Models stay loaded for 10 minutes after use (`keep_alive`). The robot waits up to 45 s for a reply, and falls
back to the keyword rules if it takes longer.

**What the local brain can and can't do:**

- It answers in the robot's own reply format: speech, mood, sound and robot commands, so "spin around twice"
  works.
- It has no tools. Tasks, ideas, focus, routines, music, smart home and so on are handled by the built-in
  sentences, which run before it, so those still work.
- It doesn't know live facts (weather, news), and it says so.

## Reading pages without the internet

- **Tesseract:** `sudo apt install tesseract-ocr` (`setup.sh` does it). Fast and good for printed pages that are
  flat and well lit.
- **Local vision model:** `qwen2.5vl:3b` through Ollama. It reads photos, curved pages and some handwriting.
- **Photo quality:** the robot's camera runs at 320×240, which is enough only for large print held close. For a
  page, take a photo with your phone: use the Reader card's **Photo of a page** button, which opens the phone
  camera.

Every reading is saved as text in `data/reads/`.

## Without Wi-Fi at all

`bash scripts/hotspot.sh` makes the Pi its own Wi-Fi network. Connect your phone or laptop to it and open
`http://10.42.0.1:8000`. With local only on, the robot then never needs an outside connection.
