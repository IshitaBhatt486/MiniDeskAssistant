# The laptop as the robot's speaker (21 Nov 2026)

The speaker + amplifier on the Pi is postponed. Until it's wired, **everything the robot would play comes out of the
laptop**: spoken replies, alerts, chatter, buddy reminders and the musical chimes.

## Using it

1. Start the robot as usual (`python main.py start`, `pro`, `full`, …, with `--lan` so the laptop can reach it).
2. On the laptop, open the dashboard `http://<pi>:8000` or the speaker-only page `http://<pi>:8000/speaker`.
3. Click **Turn on** in the **🔊 Speaker** box (bottom right of every dashboard; full size on `/speaker`). Browsers
   only play sound after a click. The choice is remembered, and after a reload the next click anywhere turns it
   back on.

The box shows:
- whether it's listening and how many clips it has played;
- what's playing now ("“Hello!”" or "♪ fanfare");
- "Can't reach the robot, retrying…" if the connection drops (it keeps retrying, waiting up to 10 s between tries);
- a menu **Sound plays on: this laptop / the robot / both**.

If nothing is listening when the robot speaks, its alert list says *"Sound goes to the laptop, but no browser is
listening…"*. That clears by itself once a tab turns the speaker on.

**Once the real speaker is wired:** choose *the robot* (or *both*) in the box, or start with `DESKBOT_SPEAKER=robot`.
The audio device is still picked with `DESKBOT_AUDIO_DEVICE`.

## How it works

```
Speaker._loop ──► Speaker._emit(wav, kind, text)
                    ├─ laptop/both: LaptopSpeaker.push() ──► numbered clip queue (newest 24)
                    │                                          ▲ GET /api/speaker/clips?after=N  (long poll, ≤ 25 s)
                    │                                          └ GET /api/speaker/clip/<id>.wav
                    │                                   browser: laptop-speaker.js → Web Audio, in order
                    └─ robot/both:  Player.play() (aplay / pw-play / paplay / ffplay / winsound)
```

- **Where sound goes** is the assistant setting `speaker_output` (`laptop` | `robot` | `both`, default `laptop`,
  saved in `data/assistant.json`, validated in `settings.validate`). The environment variable `DESKBOT_SPEAKER`
  overrides it. `Speaker.output()` reads it on every clip, so changing it takes effect on the next sound without a
  restart.
- **`_emit`** replaces the two `player.play()` calls (speech and chimes). In `laptop` mode it pushes the clip and then
  waits out the clip's length (read from the WAV header) plus 0.15 s. That keeps the speaker queue, the `speaking`
  status, the 6-item queue limit and the order of speech after chimes exactly as with a real speaker. `interrupt()`
  ("Stop all") ends that wait early through an `Event`. In `both` mode the robot's player blocks as before.
- **`LaptopSpeaker`** (`assistant/laptop_speaker.py`):
  - A `deque(maxlen=24)` of `(id, kind, text, wav, duration)` behind a `Condition`.
  - `wait_clips(after, wait)` returns the clips newer than `after`. If there are none, it sleeps on the condition
    until `push()` (or `interrupt()`) wakes it, or `wait` runs out (capped at 25 s).
  - `after=-1` returns only `latest`, so a newly opened tab doesn't replay old speech.
  - `interrupt()` clears the queue and increments a counter. Tabs send the last counter they saw and stop playing
    when it changes.
  - Each request carries a random tab id. Tabs seen in the last 45 s count as listeners (shown in the box and used
    for the "no one is listening" alert).
  - The server is a `ThreadingHTTPServer` (daemon threads), so a waiting long poll only holds its own thread, like
    the camera's MJPEG stream.
- **Browser** (`web/static/laptop-speaker.js`, loaded on every dashboard through `build_assistant_index()`, which
  companion/buddy/hub/full/pro all build on, and on `/speaker`):
  - Loop: long-poll → queue the clips → fetch each WAV → `AudioContext.decodeAudioData` → play one
    `AudioBufferSource` after another.
  - A clip that's already gone (404) is skipped. On errors it backs off 1 s, 2 s, … up to 10 s.
  - Only one tab plays: turning it on posts `{takeover}` on a `BroadcastChannel`, and other tabs turn themselves off,
    so sound never doubles.
  - The output menu posts `{"speaker_output"}` to `/api/assistant/settings`.
- **Health check:** in `laptop` mode, "Speaker output" passes with instructions instead of needing a player on the
  Pi, then the microphone check runs as before.
- The older `/remote` "play replies" option (newest reply only, `/api/assistant/speech.wav`) is unchanged. Leave it
  off on a phone if the laptop is already playing, or replies play twice.

## Limits

- Latency is about 0.1-0.5 s on the local Wi-Fi: the long poll answers as soon as the clip exists, then the WAV
  (~40 KB per second of speech) is fetched.
- If the laptop is asleep or the tab is closed, speech is lost (only the newest 24 clips are kept, and a tab that
  reopens starts from "now").
- Sound comes from wherever the laptop is, not from the robot.

## Tests

`tests/test_laptop_speaker.py` (12 tests):
- the queue: duration, no replay, long-poll wake-up and timeout, interrupt, keeping the newest;
- routing in all three modes (clips pushed vs. robot player calls);
- the environment override, "Stop all", and setting validation.

Tested by hand against `python -m deskbot assistant --sim`: `/speaker` and the script are served, the long poll woke
1.5 s after `/api/assistant/say`, the clip is a valid 16-bit WAV, the output switch and its validation work, and
"Stop all" increments the interrupt counter.
