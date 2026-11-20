# Desk buddy: tasks, reminders, celebrations, phone notifications, sound effects (19 Nov 2026)

```bash
cd run_prototype
python main.py buddy --sim            # any computer: simulated robot, desk, camera and phone
python main.py buddy --lan            # on the Pi (the phone must reach it over Wi-Fi)
bash scripts/buddy.sh                 # same as the line above
```

`main.py buddy` is a **new runtime**. It is the companion robot (`main.py start`) plus the features in this document.
`main.py start`, `deskbot assistant` and `deskbot run` still work as before. The only changes they see are the
`sound` field in the AI reply, the `celebrate` and `nudge` actions, and the `celebrating` eyes. All of those are
backwards compatible.

| file | what |
| --- | --- |
| `deskbot/buddy/app.py` | runtime + HTTP routes (`BuddyHandler`, a `CompanionHandler` subclass), `run_buddy()` |
| `deskbot/buddy/core.py` | `Buddy`: celebrations, the 1 Hz reminder and notification loop, when it may speak or move |
| `deskbot/buddy/tasks.py` | `TaskStore` (persistent list), the 5 AI tools, offline sentences, reminder wording |
| `deskbot/buddy/when.py` | deadlines in words ↔ datetimes, with no extra packages |
| `deskbot/buddy/notify.py` | notification payloads, importance rules, AI triage, `NotificationCenter` |
| `deskbot/buddy/config.py` | `data/buddy.json` settings, the phone token |
| `web/static/buddy_cards.html`, `buddy.js`, `buddy.css` | Tasks and Phone notifications cards, confetti |
| `scripts/buddy.sh` | start on the Pi |
| `tests/test_buddy.py` | 27 tests, with no hardware, network or API key |

Small hooks added to the existing code (each is documented where it is defined):

- `assistant/commands.py`: `SOUNDS`, the `sound` schema field, the `celebrate`/`nudge` actions, `CELEBRATIONS`, `NUDGE`,
  `Executor._routine`
- `assistant/brain.py`: `Brain.add_tool(spec, fn)`, `Brain.add_prompt(text)`, `Brain.local_handlers`, and the sound cleanup
- `assistant/core.py`: `Assistant.context_hooks`, `Assistant.turn_listeners`; the sound is played before the speech
- `assistant/motifs.py`: 15 synthesised sound effects
- `companion/animations.py` + `eyes.py`: the `celebrating` emotion (5 animations) and the `confetti` effect
- `companion/app.py`: `run_companion(handler_cls=..., on_ready=...)`
- `companion/cli.py`: the `buddy` command and two menu entries

---

## 1. Sound effects in the AI reply

The reply schema (structured outputs) is now:

```json
{"speech": "Why did the robot cross the desk? To get to the other byte.", "mood": "happy", "sound": "rimshot",
 "commands": []}
```

`sound` is required and is an enum: `none, tada, ding, pop, boing, whoosh, giggle, rimshot, drumroll, sad_trombone,
beep_boop, fanfare, notification, reminder, gasp, yawn`. The system prompt lists each one with a one-line meaning
and says most replies should use `none`.

- **Playback order:** `core.py` queues `speaker.chime(sound)` and then `speaker.say(speech)` on the speaker's one
  queue, so the effect always plays first.
- **Validation:** `Brain.think` replaces any unknown value with `none`, even though the schema already prevents one.
- **Synthesis** (`motifs.py` `_effect`) uses numpy only and no sound files. There are three building blocks:
  - plucked notes (`_note`: sine plus octave, 8 ms attack, exponential decay)
  - pitch glides (`_sweep`: exponential or linear, optional vibrato)
  - noise bursts (`_hit`: white noise through a moving-average low-pass, exponential decay)

  Each effect is normalised to a peak of 0.85, uses a fixed noise seed (so it sounds the same every time), lasts
  0.07–1.9 s, and is cached after its first use. All 15 take about 0.6 s the first time on the laptop. The
  low-pass is a vectorised `np.convolve`: the first version used a per-sample Python loop and took 6.8 s.
- **Settings:** the existing `sounds` setting turns these off along with the state motifs.
- **Dashboard:** the conversation log shows a `♪ name` chip, and the reply's JSON includes `sound`.

## 2. Task list (`tasks.py`, `when.py`)

### Storage

`data/tasks.json` (`data/tasks_sim.json` in simulation) is written atomically (`.tmp` then `replace`) after every
change. A damaged file is renamed to `tasks.corrupt.json`, a spoken warning says a new list was started, and the
robot keeps working.

```json
{"id": 3, "title": "submit the report", "due": "2026-11-20T17:00:00", "created": "...", "done": false,
 "done_at": null, "reminded": ["soon"]}
```

Times are naive local time. Ids keep counting after a restart (`next_id`). Done tasks are kept for 14 days, and the
list holds at most 200 tasks. Adding a task with the same name as an open one updates its deadline instead of
creating a duplicate.

### Telling the robot

**With the AI**, Claude gets five tools: `add_task(title, due)`, `complete_task(task)`, `update_task(task, title, due)`,
`remove_task(task)` and `list_tasks()`.

- All five are strict, with every field required (`""` means "none" or "keep").
- They are registered with `Brain.add_tool`, run in the existing tool loop, and are added to the cached tool list.
- The system prompt gets the `tasks.PROMPT` rules through `Brain.add_prompt`:
  - turn relative times into local ISO 8601 using the time in `robot_context`
  - a day with no time means 17:00
  - congratulate in words only, because the robot celebrates by itself
  - ask when a task name is ambiguous
- The open list (nearest deadline first, with OVERDUE marks) and today's done tasks go into `robot_context`
  through `Assistant.context_hooks`. That way "what's next?" can be answered without a tool call.

**Without the AI** (no key, the API is down, or the call failed), `Brain.local_handlers` runs `tasks.local_intent`
before the offline keyword rules. It understands:

- "remind me to … / add … to my list / I need to … / don't let me forget to …"
- "I finished … / done with … / mark … as done"
- "remove/delete/cancel …"
- "what's on my list / what do I have to do"

Plain robot commands still go first (`local_command`), so "turn left" never reaches the task rules.

**From the dashboard:** the Tasks card has an add box (the deadline is parsed from the text), tick to complete,
untick to reopen, and × to remove.

### Finding a task from words

`TaskStore.find` scores every open task by
`max(SequenceMatcher ratio, 0.85 × word overlap + 0.15 × ratio)`, after lowercasing and dropping filler words
(the, a, my, to, task, …). The best task is accepted if its score is at least 0.5 **and** at least 0.12 better than
the second best. Otherwise it raises `LookupError("that could be X or Y")`, and the AI asks which one. A number like
`#3` always works.

### Deadlines in words (`when.py`)

| said | means |
| --- | --- |
| in 20 minutes / in an hour / in half an hour / in 3 days / in a week | now + that |
| today, tomorrow, the day after tomorrow, (on/by/this/next) Monday…Sunday | that day; weekday = the next one (today counts unless "next") |
| at 5, at 5pm, at 5:30 pm, at 17:30, by 9 am | that time; with no am/pm, 1–7 means pm; 8–11 means pm if that hour has already passed today |
| noon, midnight (23:59), morning 9:00, afternoon 14:00, evening 18:00, tonight 20:00, end of day 18:00 | |
| a day without a time | 17:00 that day |
| a time without a day that has already passed | tomorrow |

A plain number is not a time: "buy 2 apples" has no deadline. Clock times need "at/by/before", am/pm, or `h:mm`.
`say_due()` speaks deadlines the way people say them: "in 20 minutes", "today at 5 PM", "tomorrow at 5:30 PM",
"on Monday at 9 AM", "on 3 December at 5 PM".

### Reminders

`TaskStore.reminders_due(now, before_min=15, overdue_min=60)` returns at most one reminder per open task with a
deadline:

| kind | when | said |
| --- | --- | --- |
| `soon` | `remind_before_min` before (skipped if the task was added less than that before the deadline) | "Heads up! Submit the report is due in 15 minutes." |
| `due` | at the deadline | "It's time: submit the report is due now." |
| `overdue` | `overdue_after_min` after | "Submit the report was due 1 hour ago. Tell me when it's done!" |

The buddy loop marks a reminder as said only after saying it. A late `overdue` also marks `soon` and `due`, so
nothing is repeated. Changing the deadline clears `reminded`.

Each reminder plays the `reminder` chime, shows `excited` eyes (soon) or `curious` eyes (due/overdue) for 5 s,
speaks, and does a `nudge` if moving is allowed.

## 3. Celebrations

`Buddy.celebrate(task, source)` runs on every `completed` event from the store, whatever the source (voice, AI tool,
dashboard, offline sentence):

1. `fanfare` chime.
2. `celebrating` eyes for 5 s (7 s when the whole list is done). The emotion engine's reaction slot ranks below
   "lifted" and "annoyed", so a celebration never hides those.
3. Words only when nobody else speaks: the dashboard and API say "Nice work! X is done." Voice and AI completions
   already have their own reply.
4. If moving is allowed (`tasks.move` on, not lifted, awake, no other command sequence running, not calibrating),
   `executor.run([celebrate])`. The last task on the list adds `spin 1`.
5. `last_celebration.seq` increases, and the dashboard shows confetti (90 pieces for "all done", otherwise 45; turned
   off with `prefers-reduced-motion`).

**The `celebrate` action** picks one of `CELEBRATIONS` at random, never the same one twice in a row:

| routine | steps |
| --- | --- |
| victory spin | left 360° |
| happy wiggle | left 20°, right 40°, left 40°, right 20° |
| hop hop | forward 0.15 s, back 0.15 s, twice, then left 15°, right 15° |
| twist and shout | right 90°, left 180°, right 90° |

Each routine ends where it started: the turns sum to a multiple of 360° and the forward/back moves sum to 0, which a
test checks. `nudge` is left 12°, right 24°, left 12°. Both run through `Executor._routine`, which uses `_turn` and
`_move`, so every motor-process safety rule (edges, obstacles, stale sensors) applies, and a safety stop ends the
routine. The AI can use both actions too.

**The `celebrating` eyes** (`animations.py`) are a new 11th emotion, added at the end of `EMOTIONS` so the indices in
shared memory don't change for the others. The base pose is big, round, smiling eyes. There are 5 animations:
confetti, victory bounce, proud wink, spin eyes and happy dance. The `confetti` effect draws 14 falling, drifting
pieces whose positions come from their index and the clock, so no state is kept.
`python main.py face --emotion celebrating` plays them.

## 4. Phone notifications (`notify.py`)

### Getting them from the phone

A phone doesn't share other apps' notifications with a Bluetooth gadget in any standard way that works on both
platforms, so the phone **pushes** each one to the robot over Wi-Fi:

```
POST http://<robot>:8000/api/notify
Content-Type: application/json
X-Deskbot-Token: <token>                (or "token" in the body)
{"app": "WhatsApp", "title": "Mom", "text": "Call me when you're free", "category": "msg", "priority": "high"}
```

Aliases are accepted, so most automation apps' variable names work: `app_name`/`application`/`package` → app,
`sender`/`from`/`name` → title, `message`/`body`/`content`/`bigtext` → text. Priority can be a word
(`max, urgent, high, default, low, min`) or −2…2. Each field is cut to 400 characters, and the body is at most 10 kB.

- **Android:** use [MacroDroid](https://www.macrodroid.com/), Tasker or Automate.
  - Trigger: *Notification received* (choose "any app", or only the apps you care about).
  - Action: *HTTP request*, method POST, content type `application/json`, body as above, with the app's variables
    inserted for the app name, title and text.
  - The dashboard's "Connect your phone" section shows the exact URL, the token and an example body.
  - The robot must be on the same Wi-Fi, so start it with `--lan` (`scripts/buddy.sh` does).
- **iPhone:** iOS doesn't let apps read other apps' notifications. A Shortcuts automation ("When I get a message
  from …" → *Get contents of URL*, POST JSON) covers messages from chosen people. Apple's notification service over
  Bluetooth LE (ANCS) would cover everything, but needs pairing as an accessory. It is not implemented; see Future.
- **Token:** `NOTIFY_TOKEN` in `secrets.env` if set. Otherwise a random 16-character token is made once and saved in
  `data/notify_token` (git-ignored). "New token" on the dashboard replaces it. It is compared with
  `hmac.compare_digest`. A wrong or missing token gets a 403.
- **Notifications off** (`notify.enabled`): the robot still answers 200 but ignores the notification.

### Deciding what is important

1. **Sensitive → blocked.** One-time codes, verification codes and links, passwords, PINs, CVV, "123456 is your …",
   "code: 1234".
   - Never spoken, never sent to the AI.
   - The title and text are removed from memory straight away; the dashboard shows "Messages (hidden)".
   - The pattern errs on the side of hiding (any "password" or "pin" counts).
2. **Rules** (`score`):

| | points |
| --- | --- |
| app on your *never read* list | −10 (stop) |
| calls / phone app, calendar, clock and alarms | +3 |
| messaging apps (WhatsApp, Signal, Telegram, Messages, …) | +2 |
| e-mail | +1, work chat (Slack, Teams, Classroom, …) +1 |
| social, shopping, food, streaming, games, store apps | −2 |
| Android category call / alarm / reminder / event | +3; msg +2; email +1; promo / social / status / progress / system −3 |
| app on your *always* list | +3 |
| a VIP name (whole word) in the sender or text | +4 |
| urgent words: urgent, asap, emergency, important, call me, missed call, deadline, help, where are you, running late, cancelled, rescheduled, due today, … | +3 |
| one of your keywords | +3 |
| promo / noise words: % off, sale, offer, liked your, is live, downloading, battery, update available, newsletter, … | −3 |
| Android priority high/max +1, low/min −2 | |

   - **≥ 3 important.** It is spoken with a template: "Mom on WhatsApp: …", "Missed call from …",
     "Calendar: Physics lab. Starts in 15 minutes."
   - **≤ 0 skipped.**
   - **1–2 "maybe".**
3. **A maybe goes to the AI** if "Let the AI judge" is on and the AI is available.
   - It is a separate one-shot call: Haiku, effort low, max 300 tokens, structured output
     `{"important", "reason", "speech"}`.
   - The system prompt describes what is worth interrupting a person at a desk for, plus your VIPs, keywords and
     apps.
   - Only the app, title, text and category are sent.
   - Without the AI, or if the call fails, a score of 2 (a plain message from a person) counts as important and a
     score of 1 doesn't. The dashboard shows "by rules (no AI)".
4. **Repeats** (the same app, title and text within 10 minutes, as when apps update a notification) are ignored.
5. With "Read the message itself" off, the robot only says "New WhatsApp notification from Mom."

Triage runs on its own thread (queue of up to 50), so the phone's request returns immediately (`202`, status
`triaging`). Everything stays in memory: the last 60 notifications, never written to disk.

### When they're said (`core.py`, every second)

A notification is said only when **all** of these hold:

- notifications are on
- the robot is not in quiet hours (default 22:00–07:00; ranges that cross midnight work; empty = never quiet)
- you're present, if "hold while away" is on (no Bluetooth presence running, or the robot is awake)
- no conversation turn is in progress
- at least 6 s have passed since the buddy last spoke

When those hold, the robot plays the `notification` chime, shows `curious` eyes and speaks. If several are waiting it
says "You have N important notifications", the first three, then "And N more on the dashboard". It can also nudge
(`notify.move`, off by default).

Held notifications expire after `max_age_h` (12 h). The newest important ones (last hour, up to 3) go into
`robot_context`, so "what did Mom say?" works.

Task reminders use the same presence and "busy" checks, but **ignore quiet hours**, except the overdue nag: you set
the deadline yourself.

## 5. Settings (`data/buddy.json`, dashboard)

| setting | default | |
| --- | --- | --- |
| `tasks.remind_before_min` | 15 | 0–1440 |
| `tasks.overdue_after_min` | 60 | 5–1440 |
| `tasks.celebrate` | true | fanfare + eyes + move |
| `tasks.move` | true | off: sound and eyes only |
| `notify.enabled` | true | |
| `notify.use_ai` | true | send unclear ones (never codes) to Claude |
| `notify.read_text` | true | |
| `notify.vip`, `keywords`, `important_apps`, `muted_apps` | [] | comma-separated on the dashboard, at most 30 each, 40 characters each |
| `notify.quiet_start` / `quiet_end` | 22:00 / 07:00 | `HH:MM`, empty = off |
| `notify.hold_when_away` | true | |
| `notify.move` | false | |
| `notify.max_age_h` | 12 | 1–48 |

## 6. API

| route | body | |
| --- | --- | --- |
| `GET /api/buddy` | | tasks, notifications, settings, phone URL and token, celebrations |
| `POST /api/notify` | notification + token | from the phone; 202 / 403 |
| `POST /api/buddy/tasks` | `{"add": "text"}` (+ optional `"due"`) · `{"complete": id}` · `{"reopen": id}` · `{"remove": id}` · `{"update": {"id", "title", "due"}}` | |
| `POST /api/buddy/settings` | `{"tasks": {...}, "notify": {...}}` | validated |
| `POST /api/buddy/notifications/test` | `{"app", "title", "text", "category"}` | the dashboard's "Try one"; no token |
| `POST /api/buddy/celebrate` | `{}` | try the celebration |
| `POST /api/buddy/token` | `{}` | new phone token |

Like the rest of the API, every POST needs `Content-Type: application/json`.

## 7. Security and privacy

- The dashboard has no login (see README, "Security"). Anyone on the Wi-Fi can see the notification history, the
  task list and the phone token, and can make the robot speak (that was already possible). The token only keeps
  stray or malicious posts out of `/api/notify` from devices that haven't seen the dashboard. Use the hotspot mode
  or a trusted network.
- Codes and passwords are blocked before anything else and their text is dropped.
- With "Let the AI judge" on, the app, sender and text of *unclear* notifications go to Anthropic's API. Turn it off
  to keep everything on the robot. Clear cases are decided by the rules locally.
- Tasks are stored in plain JSON on the SD card.

## 8. Verified (laptop, simulation, 19 Nov 2026)

- `tests/test_buddy.py`: 27 tests, all passing; the whole suite (217 tests) passes. They cover:
  - every sound synthesises, has the right length and level, and plays before the speech
  - deadline parsing (10 sentences) and spoken deadlines
  - add, find, ambiguity, persistence, corrupt file, reminders (soon/due/overdue, late tasks)
  - the AI tools, including a scripted Claude tool loop calling `add_task`
  - offline sentences
  - notification rules, blocking, duplicates, AI and AI-failure paths, settings validation, quiet hours
  - the buddy celebrating (and not moving while lifted), holding reminders and notifications while away and saying
    them on return
  - routines that end where they started
  - the confetti eyes
- `python main.py buddy --sim --camera none` with the API on port 8123:
  - "remind me to submit the report at 5pm tomorrow" → "Got it: submit the report, due tomorrow at 5 PM." (sound
    `ding`, offline brain)
  - "I finished the report" → "Woohoo! …", eyes `celebrating`, the executor ran `celebrate` (victory spin)
  - a 1-minute task's `due` reminder fired on time
  - a wrong token → 403
  - WhatsApp "Call me, it is urgent" → read aloud (score 5)
  - a Myntra sale → skipped (−5)
  - an OTP → blocked and hidden
  - the dashboard cards render (headless Edge)
- Not verified here: the real speaker, motors and OLED (Pi only), the Claude triage call against the live API (no key
  on the laptop; the tests use a scripted client), and an actual Android automation app posting.

## 9. Future

- iPhone: an ANCS client over BlueZ, so every iOS notification arrives without Shortcuts.
- Android: a tiny companion app using `NotificationListenerService`, instead of a general automation app.
- Recurring tasks ("every Monday"), and a morning summary of today's deadlines.
