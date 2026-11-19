# Putting it on the Pi: deploy, clean-up, hotspot, start on boot (17 Nov 2026)

## 1. Copy the project from the laptop (`scripts/deploy.sh`)

Runs in **Git Bash** on Windows (or any Linux/macOS shell). It needs only `ssh` and `tar`, which Git for Windows has
(no rsync).

```bash
ssh-copy-id pi@deskbot.local                      # once: log in with a key instead of a password
cp secrets.env.example secrets.env                # once: add your API keys (copied to the Pi, mode 600)

bash scripts/deploy.sh pi@deskbot.local --wipe-home --install --service   # first time: clean Pi → running robot
bash scripts/deploy.sh pi@deskbot.local                                   # later: just update the code
```

| Option | Effect on the Pi |
| --- | --- |
| *(none)* | replaces the code in `~/deskbot` but **keeps** `.venv`, `models/` (NCNN export), `data/` (settings, certificate), `secrets.env`: fast updates |
| `--clean` | deletes `~/deskbot` completely first |
| `--wipe-home` | **"clean up all files on the Pi"**: lists every normal file/folder in the Pi user's home, asks you to type `WIPE`, deletes them. **Hidden files are kept** (`.ssh`, `.bashrc`, `.config`); deleting `.ssh` would lock you out. System files outside the home aren't touched |
| `--install` | runs `scripts/setup.sh` on the Pi (apt packages, venv, Python packages, model export; asks for sudo) |
| `--service` | installs + starts the systemd service (§3) |
| `--dir NAME` | another folder name in the home directory |

What's sent: a 2.4 MB tar.gz of the repo **without** `.venv`, `.git`, `__pycache__`, `models/`, benchmark data,
`data/` and `secrets.env` (which goes separately over ssh with `umask 077`). It uses 3–5 ssh connections in total.
The service is stopped before the copy. The tar is written with `tar czf - … > file`, because GNU tar would read a
Windows path like `C:/…` as a remote host name.

**By hand** (without the script):
```bash
tar czf - --exclude=./.venv --exclude=./.git --exclude=./models --exclude=./data . | ssh pi@deskbot.local "mkdir -p ~/deskbot && tar xzf - -C ~/deskbot"
ssh pi@deskbot.local
cd ~/deskbot && bash scripts/setup.sh && bash scripts/assistant.sh
```

## 2. The Pi as its own Wi-Fi hotspot (`scripts/hotspot.sh`, on the Pi)

NetworkManager (Raspberry Pi OS Bookworm+), profile `deskbot-hotspot`: WPA2 (RSN/CCMP), 2.4 GHz, `ipv4.method shared`,
so the Pi is **10.42.0.1** and hands out addresses. The SSID is `DeskBot-XXXX` (the last 4 hex digits of the MAC). The
password is random (10 characters) unless you pass `--password`, and it's stored in `~/.deskbot-hotspot` (mode 600)
so it stays the same.

```bash
bash scripts/hotspot.sh on          # now (prints SSID + password); SSH over Wi-Fi drops
bash scripts/hotspot.sh off         # back to your normal Wi-Fi
bash scripts/hotspot.sh fallback    # at boot: your Wi-Fi if it's in range, otherwise the hotspot
bash scripts/hotspot.sh status
```

Join it from a phone → `http://10.42.0.1:8000/remote` (microphone: `https://10.42.0.1:8443/remote`). The HTTPS
certificate already lists 10.42.0.1.

**Trade-off: one radio.** While the Pi is the hotspot it isn't on your Wi-Fi, so it has **no internet** unless
Ethernet is plugged in. The AI brain, cloud speech-to-text and weather stop working; the robot says so and switches
to the offline brain (driving, the remote, presence, lift detection and maps all keep working). If you need both,
turn on your **phone's** hotspot and connect the Pi to it as a normal client (`sudo nmtui`). Everyone on the phone's
hotspot can then reach the robot, and it has internet. Running a client and an access point at the same time on the
Pi 4's single chip (a virtual `uap0` interface) is possible but locks both to one channel and is fragile, so it
isn't used.

`fallback` gives the hotspot autoconnect priority −10 (normal Wi-Fi profiles are 0), so NetworkManager prefers known
networks. Once the hotspot is up, the radio can't scan, so it only switches back after `hotspot.sh off` or a reboot.

## 3. Start on boot (`scripts/install-service.sh`, on the Pi)

```bash
bash scripts/install-service.sh install    # enable + start now
bash scripts/install-service.sh logs       # live log (journalctl -f)
bash scripts/install-service.sh stop|start|restart|status|uninstall
```

`/etc/systemd/system/deskbot.service` runs `.venv/bin/python -m deskbot assistant --lan` as **you** (not root) in the
repo folder, with `Restart=on-failure` (5 s), `KillSignal=SIGINT` (the same clean shutdown as Ctrl+C: motors
stopped, GPIO released), and `LimitRTPRIO=60` / `LimitNICE=-10`. Services don't read `/etc/security/limits.d`, so
these lines grant the real-time priorities from [runtime.md](runtime.md). Install also adds you to the `gpio`,
`audio`, `bluetooth` and `video` groups.

While the service runs, the GPIO pins are busy, so stop it before `scripts/start.sh`, sensor tests or `robot_shell.py`.

## 4. First boot checklist

1. `bash scripts/doctor.sh` (camera, model, pins).
2. `aplay -l`. If the speaker is on a USB card, add `DESKBOT_AUDIO_DEVICE=plughw:<card>,0` to `secrets.env`. Then
   `espeak-ng "hello"` to check you can hear it.
3. `bluetoothctl show` → `Powered: yes`.
4. Start the assistant, open the dashboard, check the tags (brain / speech / voice) and the **Warnings** card. Every
   problem is listed there with the reason.
