# Presence: Bluetooth phone tracking, sleep/wake, find my phone, lift detection (17 Nov 2026)

Part of the assistant runtime ([assistant.md](assistant.md)). Code: `deskbot/presence/` (`ble.py`, `manager.py`,
`lift.py`). Settings: dashboard → **Presence** card, saved under `ble` in `data/assistant.json`.

## 1. Hearing your phone (`ble.py`)

`BleScanner` runs a continuous **bleak** scan (BlueZ over D-Bus on the Pi, no root needed once you're in the
`bluetooth` group; `setup.sh` adds you) on its own asyncio thread. Every advertisement updates the "nearby" list.
Ones that match your phone feed `PhoneTracker.add(rssi)`. If the adapter errors (Bluetooth off, adapter reset), it
says so once and retries every 20 s.

**Matching**: by MAC address, by name substring, or by **iBeacon UUID** (Apple manufacturer data `0x004C`, type
`0x02 0x15`, UUID = bytes 2–17). Pick yours on the card (*Pick your phone / beacon* → *This is mine*).

**The catch with phones.** Phones only advertise now and then, and they change their Bluetooth address every ~15
minutes for privacy. Reliable options, best first:

1. **A beacon app on the phone with a fixed UUID.** Android: e.g. "Beacon Simulator" (runs in the background).
   iPhone: an advertiser app works only while it's open. → the device shows with "· iBeacon"; *This is mine* stores
   the UUID.
2. **A BLE tag, smartwatch or fitness band** with a fixed address, carried with the phone.
3. The phone's name while it advertises (for example with the Bluetooth settings screen open). Fine for a demo.

**Distance**: log-distance path loss, `d = 10^((−59 − RSSI) / (10 · 2.2))`. That's ±50 % at best (pockets, bodies,
orientation), so it's shown as "rough" and never used for decisions.

## 2. Wake when you come, sleep when you go (`PhoneTracker`, `Presence`)

RSSI is smoothed (EMA, new sample weight 0.3). States, with hysteresis:

| → | condition (defaults, editable in `ble` settings) |
| --- | --- |
| `near` | smoothed RSSI ≥ **−67 dBm** for 2 s |
| `away` | nothing heard for **25 s**, or smoothed < **−85 dBm** for 10 s |
| (no change) | between −85 and −67 dBm, so walking around the desk doesn't toggle it |

`near` while asleep → wake + "Welcome back!" (if `auto_wake`). `near → away` while awake → "Bye! Going to sleep."
(if `auto_sleep`). **Asleep** = the running command list cancelled, motors stopped, face-the-user off (restored on
wake), sleepy face. Speaking to it, sending a command or pressing *Wake* wakes it.

## 3. Find my phone (`Presence.find_phone`)

The robot has a single omnidirectional antenna, so direction comes from its own **body shadow**: the battery and
motors block some of the signal from behind. That's a few dB, enough to find the strongest heading.

1. **Scan**: 12 headings, 30° apart (turning left). At each one: settle 0.35 s, average RSSI over 1 s.
2. **Choose**: circular [1 2 1] smoothing across neighbouring headings, take the maximum. A spread < 3 dB is
   announced ("about the same everywhere") but still tried.
3. **Face it**: turn left or right, whichever is shorter.
4. **Approach**: hops of 0.6 s forward. Before each hop, a `cell phone` camera detection (if any) corrects the heading
   (80 % of its bearing). After each hop it listens 1 s:
   - RSSI ≥ **−45 dBm** → "Found it!"
   - **safety stop at the desk edge** → "I'm at the edge of the desk. Your phone should be just ahead of me." The IR
     rule in the motor process stops it, so it can never drive off.
   - an obstacle → stops and says so
   - RSSI more than 6 dB below the best for 2 hops → scan again (once), then give up politely.
5. Face-the-user is paused during the search. The dashboard draws the scan as a polar plot (dots = RSSI per
   heading, green line = chosen heading) and shows the phase, hops and RSSI.

Start it from the card, the remote, `{"action": "find_phone"}` or by saying "find my phone".
**Calibrate `ARRIVE_RSSI`** (`manager.py`) for your phone: put it 20 cm in front of the robot and read the Signal value.

**Simulation** (`SimPhoneSource`): the "Phone" object on the simulated desk advertises at 8 Hz with RSSI =
−59 − 22·log10(d) − 8·(1 − cos φ)/2 + N(0, 1.5) dB (φ = angle off the robot's nose). *Phone nearby (sim)* switches
it off to test sleep. Verified: it chose 120° with a 6.8 dB spread, and the final heading was 212° against a true
bearing of 210°.

## 4. Taken off the desk → fresh map (`lift.py`)

Two IR edge sensors, front and rear (LOW = surface). On a desk at most **one** can see nothing, because the motor
process stops the robot at the first edge. **Both** seeing nothing means it's in the air.

| → | condition | action |
| --- | --- | --- |
| lifted | both "no surface" for 0.4 s | stop, cancel commands, **pause the mapper**, "Whoa! Put me down gently please." |
| on the desk | both "surface" for 1.0 s | if it was up ≥ 1 s: **reset the map** (pose (0, 0), grids and objects cleared, track IDs reset), "New spot! Starting a fresh map."; a shorter blip only resumes mapping |
| (warning) | still "lifted" after 120 s | "…Am I lifted, or are the IR sensors unplugged?" |

Pausing matters: without it, every map update while it's carried would paint permanent "desk edge" marks under
the robot. In simulation, *Lift the robot (sim)* forces both IR readings to "no surface" (in the nav process),
and lowering it moves the simulated robot back to its start pose, like being put down somewhere else.
Runs at 20 Hz in the nav process.
