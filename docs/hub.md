# Desk hub: ideas, focus mode, Google Calendar, Spotify, connected accounts, costs (19 Nov 2026)

```bash
cd run_prototype
python main.py hub --sim         # any computer: simulated robot, desk, camera and phone
python main.py hub --lan         # on the Pi          ·   bash scripts/hub.sh (same)
```

`main.py hub` is a **new runtime**: it is the buddy robot (`main.py buddy`, [buddy.md](buddy.md)) plus the features in
this document. `main.py buddy`, `main.py start` and the older runtimes still work as before.

| file | what |
| --- | --- |
| `deskbot/hub/app.py` | runtime + HTTP routes (`HubHandler`, a `BuddyHandler` subclass), the OAuth callback page, `run_hub()` |
| `deskbot/hub/core.py` | `Hub`: wires every feature into the assistant (tools, prompts, offline sentences, context, reactions) |
| `deskbot/hub/accounts.py` | OAuth 2.0 + PKCE sign-in, token vault, refresh, disconnect, `PinGate` |
| `deskbot/hub/google_cal.py` | Google Calendar reminders + task sync |
| `deskbot/hub/spotify.py` | Spotify play / pause / skip / volume / now playing |
| `deskbot/hub/ideas.py` | the ideas notebook |
| `deskbot/hub/focus.py` | focus mode: sessions, attention tracking (YuNet face direction + phone detection), nudges |
| `deskbot/hub/costs.py` | Claude token meter, daily cap, the list of every outside service and its cost |
| `deskbot/hub/config.py` | `data/hub.json` settings |
| `web/static/hub_cards.html`, `hub.js`, `hub.css` | Focus, Ideas, Music, Connected accounts and API costs cards |
| `tests/test_hub.py` | 21 tests (OAuth flow and security, calendar, Spotify, ideas, focus, costs) |

Small hooks added to existing code (each documented where it is defined):

- `assistant/brain.py`: `Brain.not_local` (sentences that are never a plain robot command), and cache-write tokens in `usage`
- `assistant/stt.py` + `settings.py`: `allow_paid_apis` (default off) removes OpenAI from the speech-to-text order
- `buddy/core.py`: `Buddy.hold_checks` (focus mode holds notifications)
- `buddy/notify.py`: `make_ai_triage(..., on_usage=)`, so notification triage is counted too
- `buddy/app.py`: `run_buddy(handler_cls=..., on_ready_extra=...)`
- `companion/cli.py`: the `hub` command and two menu entries
- `secrets.env.example`: `ADMIN_PIN`, `ACCOUNTS_KEY`, `GOOGLE_CLIENT_ID/SECRET`, `SPOTIFY_CLIENT_ID`

---

## 1. "Remember this idea" (`ideas.py`)

| say | does |
| --- | --- |
| "remember this idea: a lamp that dims when I focus" | saved straight away (ding) |
| "remember this idea" … "a lamp that dims when I focus" | "What is it?", then the next sentence within 60 s is saved |
| "note down an idea …", "save an idea …", "idea: …" | saved |
| "what were my ideas?" / "what was my last idea?" | the newest three / the newest one |
| "forget the lamp idea" | deleted (words match with endings: "plant" finds "plants") |

- **Storage:** `data/ideas.json`, written atomically, up to 500 ideas.
- **With the AI:** Claude gets `save_idea`, `list_ideas` and `delete_idea`, and asks "What's the idea?" itself when
  none was given.
- **Without the AI:** `ideas.local_intent` runs **first** among the offline handlers, so a sentence that's waiting
  to be saved isn't mistaken for a task.
- **Context:** the idea count and the newest idea go into the AI's context.
- **Dashboard:** list, search, delete, and export everything as Markdown (`GET /api/hub/ideas.md`).

## 2. Connected accounts and their security (`accounts.py`)

### Setting one up

1. Put a PIN in `secrets.env`: `ADMIN_PIN=<something only you know>`. Without it, connecting is refused, because
   anyone on the Wi-Fi can open the dashboard.
2. Optional but recommended: `pip install cryptography`, then make a key and add it as `ACCOUNTS_KEY=...`:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. **Google:** at console.cloud.google.com:
   1. Create a project (**don't attach a billing account**).
   2. Enable the *Google Calendar API*.
   3. Set up the OAuth consent screen: External, add yourself as a test user.
   4. Create credentials → *OAuth client ID* → **Desktop app**.
   5. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `secrets.env`. A desktop client's secret isn't
      confidential by Google's design; it still stays in `secrets.env`.

   While the consent screen is in **Testing**, Google expires the sign-in after **7 days**. Switch it to
   *In production* to keep it; for your own account that only means an "unverified app" warning when you sign in.
4. **Spotify:** at developer.spotify.com/dashboard:
   1. Create an app with the Web API.
   2. Add the redirect URI shown on the dashboard card (`http://127.0.0.1:8000/oauth/spotify/callback`).
   3. In development mode, add your Spotify account under *User Management*.
   4. Put `SPOTIFY_CLIENT_ID` in `secrets.env`. There is no secret, because PKCE is used.
5. Restart, open the dashboard → *Connected accounts* → **Connect** → enter the PIN → approve in the new tab.
   - **If the browser runs on the robot,** it lands back on `/oauth/<provider>/callback` and finishes by itself.
   - **If the browser is on your laptop or phone,** it shows "can't connect to 127.0.0.1". That's expected: copy that
     page's whole address into *Finish connecting* (PIN again).

   The redirect is a loopback address because Google "Desktop app" clients and Spotify accept loopback addresses
   without a public domain, and the robot has none.

### What protects the accounts

| risk | protection |
| --- | --- |
| a stranger on the Wi-Fi connects their account or disconnects yours | every connect, finish and disconnect needs `ADMIN_PIN` (`hmac.compare_digest`); 5 wrong tries lock it for 5 minutes; the dashboard keeps the PIN only in the page's memory |
| a forged or replayed sign-in callback (login CSRF) | random 192-bit `state`, single use, expires after 10 minutes; anything else is refused |
| a stolen authorization code | PKCE S256: the code is useless without the verifier, which never leaves the robot |
| tokens leaking through the dashboard or API | no route returns a token: status shows the account name, scopes and dates only (a test checks that the status never contains a token) |
| tokens leaking from disk | `data/accounts/<provider>.json` is created with mode 0600 in a 0700 folder; it's encrypted with Fernet (AES-128-CBC + HMAC) when `ACCOUNTS_KEY` is set; `data/` is git-ignored, and so is `secrets.env`, where the key lives |
| tokens in logs | error texts pass through `scrub()`, which hides `*_token=`, `code=`, `client_secret` and any 40+ character token-like string |
| requests sent somewhere unexpected | `accounts.http` only talks HTTPS to accounts.google.com, oauth2.googleapis.com, www.googleapis.com, accounts.spotify.com and api.spotify.com, with certificate checks and an 8 s timeout |
| too much access | smallest scopes: Google `calendar.events` (events only; not your contacts, mail or calendar settings) + `openid email`; Spotify playback state/control + `user-read-private` (to tell Premium from free) |
| the address bar leaking the code | the callback page sends `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and a CSP that loads nothing |
| a sign-in that stops working | refresh failures are shown on the card and spoken once; Spotify's rotated refresh tokens are saved |
| removing access | **Disconnect** revokes the token at Google (`oauth2.googleapis.com/revoke`) and deletes the file. Spotify has no revocation API, so the card links to spotify.com/account/apps to remove it there |

**What remains:**

- Anyone who can talk to the robot or reach its API on your Wi-Fi can *use* the connected accounts the way the
  robot does: play music, or add and list your calendar events. They can't read the tokens or connect other
  accounts. Use a trusted network or the robot's own hotspot ([deploy.md](deploy.md)).
- Without `ACCOUNTS_KEY`, someone with the SD card can read the tokens. With the key, they also need `secrets.env`,
  which is on the same card. If the robot or its card is lost, remove its access at myaccount.google.com/permissions
  and spotify.com/account/apps.
- On Windows (simulation), file modes are not enforced.

## 3. Google Calendar reminders (`google_cal.py`)

- **Task sync** (default on once connected): every task with a deadline (`main.py buddy` task list) becomes a 15-minute
  event on your primary calendar with a **pop-up reminder** `minutes_before` (default 10), so your phone reminds you
  too.
  - Renaming a task or moving its deadline moves the event.
  - Finishing the task renames it "✓ title" and removes the reminder.
  - Deleting the task deletes the event.
  - The task → event map is `data/google_events.json`.
  - Sync runs on its own thread, so a slow or failed Google call never delays the robot. Failures show on the card
    and are spoken once.
- **By voice:** "put the dentist on my calendar tomorrow at 9" (`google_add_reminder`) and "what's on my calendar?"
  (`calendar_upcoming`, next 24 h). Both also work offline ("add … to my calendar", "what's on my calendar").
- **Times:** naive local times are sent with the robot's UTC offset (RFC 3339), so set the Pi's time zone
  (`sudo raspi-config` → Localisation).
- **Cost:** free. The Calendar API has no fee, and a project with no billing account can't be charged.

## 4. Spotify (`spotify.py`)

- **By voice:** "play Blinding Lights", "play some lo-fi", "pause the music", "next song", "previous song",
  "volume 40", "what's playing?". The dashboard has the same controls.
- **Search:** tracks, artists and playlists, best match first; an exact name wins, and a song is preferred.
- **Where it plays:** a Spotify Connect device on your account (settings `spotify.device`, default "deskbot"),
  else the active device, else the first one. To play from the **robot's own speaker**, install
  [raspotify](https://github.com/dtcooper/raspotify) on the Pi and name the device "deskbot".
- **Premium:** playback control needs Spotify Premium; that's Spotify's rule. A free account gets a clear spoken
  "Spotify only lets Premium accounts control playback." Search and "what's playing" still work.
- **"Stop the music" is not "stop":** `Brain.not_local` keeps music, focus, idea and calendar sentences away from
  the instant robot-command path, so they reach the AI or the music handler instead of stopping the wheels.
- **Cost:** the Web API is free.

## 5. Focus mode (`focus.py`)

"Start focus mode", "focus for 50 minutes", "Pomodoro", "stop focus mode", "how am I doing?", or the card's buttons.

**Placement:** put the robot next to or under your screen, facing you. "Paying attention" means looking at your
work. For the first 4 s with your face in view, the robot learns where your face points while you work (the
median yaw and pitch), so it doesn't have to sit straight in front of you.

**What it watches**, twice a second, using the camera frames already in shared memory. Nothing is saved, and
nothing is sent to Claude or anywhere else:

| signal | how |
| --- | --- |
| face direction | OpenCV **YuNet** (`cv2.FaceDetectorYN`, ~5–10 ms per 320×240 frame on a Pi 4). The model `models/face_detection_yunet_2023mar.onnx` (233 kB) is downloaded once from github.com/opencv/opencv_zoo. From its 5 landmarks: `yaw = (nose_x − eye_mid_x) / eye_distance`, `pitch = (nose_y − eye_mid_y) / (mouth_mid_y − eye_mid_y)` |
| phone | the YOLO detector's `cell phone` class (score ≥ 0.4) |
| person | YOLO `person` (≥ 0.45) |

| observation | rule |
| --- | --- |
| focused | \|yaw − base\| ≤ 0.35 (about 20°) and pitch within 0.22 of the baseline |
| away | yaw beyond that, head tipped right up, or a person with no face for 3 observations (turned right round) |
| down | pitch more than 0.22 above the baseline: usually reading a phone in your lap |
| phone | a phone in view |
| absent | nobody there: the timer runs, nothing counts against you |
| unknown | a person, but the face was briefly lost (and treated as focused) |

**Nudges:**

- Distraction time adds up while you're not focused, and resets after 3 s of focus.
- At **20 s** of distraction, or **10 s** with a phone in view, the robot reacts:
  - sound: `pop`, or `gasp` for the phone
  - eyes: `sad` for looking away, `annoyed` for the phone
  - one line, such as "Hey, eyes back on the work!" or "Phone down, please. Focus time!" (never the same one twice
    in a row)
  - a small `nudge` wiggle, if moving is allowed
- After that it nudges again every 45 s while you stay distracted. Each distraction episode is counted once.

**During the session:**

- Phone notifications are held and said at the break (`focus.hold_notifications`).
- Task reminders still come, because you set those deadlines.
- The AI is told to keep replies very short.

**At the end:**

- The robot says "Time's up! You were focused 86 percent of the time, with 2 distractions. Take a 5 minute break."
- At 80 % or more it celebrates (fanfare, confetti eyes, victory move).
- Breaks are 5 minutes, or 15 after every fourth session; a chime marks the end of the break.
- Sessions are logged in `data/focus.json`. The card shows the time left, the live observation, % focused,
  distractions and today's focused minutes.

**Without a camera** it's a plain timer. **Without the face model** (the download failed, or OpenCV is older than
4.5.4) the phone and presence checks still work.

## 6. Costs: Claude is the only paid API (`costs.py`)

| service | cost | when it's used |
| --- | --- | --- |
| **Anthropic Claude API** | **paid per token** | AI replies, unclear-notification triage |
| Groq Whisper | free tier (no card = can't be charged) | only if `stt` is `groq`/`auto`; the default is `local` |
| OpenAI Whisper | **paid**: now **blocked** | never, unless `allow_paid_apis` is switched on |
| Open-Meteo, Wikipedia, Official Joke API, open.er-api.com | free, no key | weather, facts, jokes, currency + the rupee rate |
| Google Calendar API | free (no billing account) | calendar |
| Spotify Web API | free (Premium is a subscription, not an API fee) | music |
| GitHub (opencv_zoo) | free | one 233 kB download |

**Is the Claude API included in a Claude plan?** No. Claude.ai Free, Pro and Max (and Claude Code's subscriptions)
cover the apps, not API calls. The robot uses an API key from **console.anthropic.com**, billed separately from
prepaid credits. Set a monthly **spend limit** there: that is the hard guarantee.

**The meter:** every Claude response reports its token counts. The hub adds them up per day in `data/usage.json`
(60 days) and prices them:

| model | input $/M | output $/M |
| --- | --- | --- |
| `claude-haiku-5-5` (the default) | 0.10 | 0.50 |
| `claude-sonnet-5-5` | 2.00 | 10.00 |
| `claude-opus-5-5` (and any unknown model) | 4.00 | 20.00 |

Cache reads are estimated at 0.1× the input price and cache writes at 1.25×. The rupee figure uses the day's rate
from open.er-api.com (₹88 if that's unreachable).

**Daily cap** (`costs.daily_cap_usd`, default **$0.50**, 0 = none): when today's estimate reaches it,
`claude.available()` turns false until midnight. The robot answers with the offline brain and says once that it's
in simple mode.

**A typical day** with Haiku 5.5: a voice turn is about 4,000 cached prompt tokens + ~800 new tokens (+ ~300 for a
camera frame when needed) + ~120 out. That's roughly **$0.0002 a turn**, or about $0.0007 for the first turn after
a 5-minute gap, which rewrites the cache. 100 turns a day is about **$0.02–0.05 ≈ ₹2–4 a day**. Notification
triage is about $0.0001 each. The API costs card shows the real day-by-day numbers.

## 7. Settings (`data/hub.json`)

| setting | default | |
| --- | --- | --- |
| `costs.daily_cap_usd` | 0.50 | 0–20 |
| `google.sync_tasks` | true | tasks with deadlines → calendar events |
| `google.minutes_before` | 10 | pop-up reminder |
| `spotify.device` | "deskbot" | preferred device name (contains) |
| `focus.minutes` / `focus.break_minutes` | 25 / 5 | |
| `focus.move` | true | nudge wiggle |
| `focus.hold_notifications` | true | |

The assistant settings also gained `allow_paid_apis` (default false).

## 8. API

| route | body | |
| --- | --- | --- |
| `GET /api/hub` | | accounts (no tokens), ideas, focus, costs, settings |
| `GET /api/hub/ideas.md` | | Markdown export |
| `GET /oauth/<provider>/callback` | `?code&state` | the sign-in return page |
| `POST /api/hub/accounts` | `{"pin", "action": "start" \| "finish" \| "disconnect", "provider", "url"}` | 403 without the right PIN |
| `POST /api/hub/ideas` | `{"add": text}` \| `{"remove": id}` | |
| `POST /api/hub/focus` | `{"start": min, "break": min}` \| `{"stop": true}` | |
| `POST /api/hub/spotify` | `{"play": query, "kind"}` \| `{"action": "pause" \| "resume" \| "next" \| "previous" \| "volume" \| "now", "volume"}` | |
| `POST /api/hub/settings` | `{"costs", "google", "spotify", "focus"}` | validated |

## 9. Verified (laptop, simulation, 19 Nov 2026)

- `tests/test_hub.py`: 21 tests; the whole suite passes. They cover:
  - PKCE: the verifier matches the challenge
  - `state`: single use, forged, expired, cancelled sign-in
  - no tokens in the status, refresh and failed refresh, Google revocation
  - the host allow-list, `scrub()`, PIN lockout, token-file privacy and encryption (the encryption part is skipped
    here: `cryptography` isn't installed on the laptop)
  - calendar body and the task sync add/complete/delete, calendar errors reported but not raised
  - Spotify device choice, search and play bodies, the Premium and no-device errors
  - ideas by voice, including the follow-up capture, plus the ideas tools
  - focus classification and a full session: baseline, away nudge at 20 s, phone nudge at 10 s, the end summary,
    the break, the no-camera timer
  - the cost cap switching the AI off and back on the next day, blocking paid speech-to-text, "stop the music" not
    stopping the wheels
- `python main.py hub --sim --camera none` on port 8124:
  - "remember this idea: …" saved; "remember this idea" → "What is it?" → the next sentence saved; "what were my
    ideas" read both
  - focus mode started and stopped by voice
  - "stop the music" went to the music handler (Spotify not connected), while "stop" still stopped the robot
  - connecting with no `ADMIN_PIN` → 403
  - a forged callback → "Couldn't connect", with the security headers present
  - `/api/hub` contains no tokens
  - the dashboard cards render (headless Edge)
- The YuNet model downloaded (232,589 bytes) and ran on the laptop (OpenCV 5.0).
- **Not verified:**
  - YuNet on a real face: the laptop webcam gave a black frame
  - real Google and Spotify sign-ins: no client IDs on this machine
  - raspotify, and anything on the Pi itself
