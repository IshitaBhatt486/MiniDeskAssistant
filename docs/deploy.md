# Putting it on the Pi: deploy, clean-up, hotspot, start on boot (17 Nov 2026)

## 1. Copy the project from the laptop (`tools/deploy.sh`)

Runs in **Git Bash** on Windows (or any Linux/macOS shell). It needs only `ssh` and `tar`, which Git for Windows has
(no rsync).

```bash
ssh-copy-id pi@deskbot.local                      # once: log in with a key instead of a password
cp run_prototype/secrets.env.example run_prototype/secrets.env   # once: add your API keys (copied to the Pi, mode 600)

bash tools/deploy.sh pi@deskbot.local --wipe-home --install --service   # first time: clean Pi → running robot
bash tools/deploy.sh pi@deskbot.local                                   # later: just update the code
```

| Option | Effect on the Pi |
| --- | --- |
| *(none)* | **only what changed** (21 Nov 2026): sends new/changed files, deletes files you removed on the laptop, installs only **missing** Python packages. Never touches `.venv`, `models/` (NCNN export), `data/` (settings, calibration, certificate), `outputs/`, `secrets.env` |
| `--full` | the old behaviour: deletes all the code in `~/deskbot` (keeping `.venv`, `models/`, `data/`, `secrets.env`) and sends everything |
| `--clean` | deletes `~/deskbot` completely first |
| `--wipe-home` | **"clean up all files on the Pi"**: lists every normal file/folder in the Pi user's home, asks you to type `WIPE`, deletes them. **Hidden files are kept** (`.ssh`, `.bashrc`, `.config`); deleting `.ssh` would lock you out. System files outside the home aren't touched |
| `--no-packages` | skip the missing-package check |
| `--install` | runs `scripts/setup.sh` on the Pi (apt packages, venv, Python packages, model export; asks for sudo) |
| `--service` | installs + starts the systemd service (§3) |
| `--dir NAME` | another folder name in the home directory |

### How the incremental update works (21 Nov 2026)

1. **Compare.** The same `find … | xargs sha256sum` runs on the laptop and (over ssh) in `~/deskbot` on the Pi. Both
   leave out `.venv`, `.git`, `__pycache__`/`*.pyc`, `models/`, `data/`, `outputs/`, benchmark data and `secrets.env`,
   so deploy never sends, compares or deletes any of those. `awk` compares the two lists by path. A file goes in the
   **send** list when it's new or its SHA-256 differs, and in the **delete** list when it's on the Pi but no longer on
   the laptop. sha256sum prints `hash  path` on Linux and `hash *path` in Git Bash, so the path is read from column 67
   in both. The remote list is matched by file name (`FILENAME == ARGV[1]`), not `NR == FNR`: with that trick, an empty
   list from a fresh Pi would have read the laptop list as the remote one and marked everything for deletion.
2. **Update.** If either list isn't empty, the service is stopped. The deleted files are removed, along with folders
   left empty (`rmdir -p --ignore-fail-on-non-empty`). Then a tar.gz of **only the changed files** (`tar -T list`) is
   unpacked. If nothing changed, nothing is sent and the service keeps running. Up to 20 paths per list are printed
   (`+ ./main.py`, `- ./old.py`).
3. **secrets.env** is sent only when its hash differs from the Pi's copy (still `umask 077`).
4. **Packages.** `scripts/missing_packages.py` runs in the Pi's `.venv`. For every line of every `requirements*.txt` it
   checks the installed version with `importlib.metadata` and `packaging` (the copy inside pip, so it works in a bare
   venv). It skips lines whose environment marker doesn't apply and prints the unsatisfied lines. pip installs **only
   those** (`TMPDIR=~/.cache/pip-tmp`, because `/tmp` on the Pi is a small RAM disk). If the install fails, the deploy
   still finishes and says so. With no `.venv` yet, it says to run `--install` once. Skipped with `--install`, because
   `setup.sh` installs everything anyway.

Limits: it checks every requirements file, so a Pi set up with `setup.sh --no-vision` / `--no-assistant` gets those
packages on the next deploy (use `--no-packages` to avoid that). apt packages, MediaPipe (installed `--no-deps` by
`setup.sh`) and the NCNN model aren't checked: use `--install` for those. Stale `__pycache__` folders aren't deleted
(Python ignores a `.pyc` whose source file is gone). The ssh calls are: connection check, file list, update (only if
needed), tar (only if needed), secrets check, packages. `--full` and `--clean` clear the folder first, so everything is
sent.

The tar is written with `tar czf - … > file`, because GNU tar would read a Windows path like `C:/…` as a remote host
name.

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

## Where `deploy.sh` lives (20 Nov 2026)

`deploy.sh` moved from `run_prototype/scripts/` to `tools/`: it only runs on the laptop, and `run_prototype/` holds only
what the Pi needs. It sets `SELF` to its own absolute path and `ROOT` to `../run_prototype`, then `cd`s there.
So it packs the same folder as before, and `secrets.env` is still read from `run_prototype/secrets.env`. `--help` reads
`$SELF`, not the relative `$0`. Before, `--help` failed after the `cd` when the script was started by a relative path.
`python main.py deploy` still works from the full repository: the robot CLI's `SH_TOOLS` paths are now relative to
`run_prototype/` (`../tools/deploy.sh`), and on a Pi without `tools/` it says the tool is only in the full repository.
At the same time `run_prototype/README.md` became [run-prototype.md](run-prototype.md), and `scripts/oled.sh` was removed
(the same thing as `hardware_tests/hardware_test.py oled --text ...`, see [hardware-test.md](hardware-test.md)).
