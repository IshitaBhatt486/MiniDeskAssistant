# Install the robot on a Raspberry Pi

Only the `run_prototype/` folder goes on the Pi. It is installed as `~/deskbot`.

> These steps have not yet been run on a real Pi. The first install may show problems that the simulator can't.

## What you need

| Item | Recommendation |
|---|---|
| Raspberry Pi | Pi 4 or 5 with at least 4 GB of RAM (8 GB is more comfortable) |
| microSD card | 32 GB or larger (16 GB minimum) |
| Operating system | 64-bit Raspberry Pi OS |
| Power | A good 5 V / 3 A supply for the Pi, separate from the motor supply |
| Network | Internet on the Pi during installation, on the same network as your laptop |
| Laptop | Git Bash on Windows, or any Linux or macOS terminal |

Finish the wiring first: see [`pins.md`](pins.md). The encoder outputs must be at 3.3 V logic, because the Pi's GPIO pins are not 5 V tolerant.

## 1. Prepare the card

1. Open **Raspberry Pi Imager** and choose your Pi model and **Raspberry Pi OS (64-bit)**.
2. In the OS customisation settings, set a hostname such as `deskbot`, a username and password, and your Wi-Fi.
3. Enable **SSH**.
4. Write the card, put it in the Pi and power it on.

Check the connection from the laptop, replacing `pi` with your username:

```bash
ssh pi@deskbot.local
exit
```

If `deskbot.local` doesn't work, use the Pi's IP address from your router. Optional, to avoid repeated password prompts:

```bash
ssh-copy-id pi@deskbot.local
```

## 2. Copy and install

Run this from the top of the repository, on the laptop:

```bash
bash tools/deploy.sh pi@deskbot.local --install
```

It copies the code to `~/deskbot`, installs the system and Python packages, turns on I2C and prepares the vision model. The first install
downloads a lot and can take a long time. It will ask for the Pi's password.

## 3. Restart the Pi

```bash
ssh pi@deskbot.local
sudo reboot
```

This applies the I2C setting and the new hardware permissions. Wait a minute, then connect again:

```bash
ssh pi@deskbot.local
cd ~/deskbot
```

## 4. Optional: add API keys

The robot works without a key, using its on-board commands. For open conversation with Claude:

```bash
cp secrets.env.example secrets.env
chmod 600 secrets.env
nano secrets.env
```

Add your `ANTHROPIC_API_KEY`.

## 5. Check and calibrate

Put the robot on a clear desk, away from the edge, and keep a hand near it the first time it moves.

```bash
.venv/bin/python main.py check
.venv/bin/python main.py face
```

Press Ctrl+C when you have seen the eyes on the OLED. Then lift the robot and measure the encoders. Turn each wheel forward by hand when asked:

```bash
.venv/bin/python calibrate_encoders.py --diameter <wheel diameter in metres> --revolutions 10
```

Put it back on the desk with about 30 cm clear all round:

```bash
.venv/bin/python main.py calibrate
.venv/bin/python main.py health
```

## 6. Start the robot

```bash
.venv/bin/python main.py start --lan
```

Open `http://deskbot.local:8000` on a device on the same network. Press Ctrl+C in the terminal to stop the motors and quit.

`--lan` has no login, so anyone on that network can control the robot. Read the security section of the main README first.

## Start automatically on boot (optional)

```bash
bash scripts/install-service.sh install
sudo systemctl status deskbot
```

To stop it for now: `sudo systemctl stop deskbot`. To read its log: `journalctl -u deskbot -f`.

## Update the code later

From the top of the repository on the laptop:

```bash
bash tools/deploy.sh pi@deskbot.local
```

This keeps the Pi's `.venv`, `models`, `data` and `secrets.env`. It removes everything else in `~/deskbot`, including saved `outputs`, so copy
those off first if you want them. If the Python packages changed, add `--install`.

## Without the deploy script

Copy `run_prototype` to the Pi as `~/deskbot`, by USB drive or with this command run from the top of the repository:

```bash
scp -r run_prototype pi@deskbot.local:~/deskbot
```

Then install it on the Pi and continue from step 3:

```bash
ssh pi@deskbot.local
cd ~/deskbot
bash scripts/setup.sh
```

## If something goes wrong

| Problem | Try |
|---|---|
| Can't connect with SSH | Check the Pi is on the same network, and use its IP address |
| `$'\r': command not found` | The script has Windows line endings. Use `deploy.sh`, or run `sed -i 's/\r$//' scripts/*.sh` on the Pi |
| OLED or MPU-6050 not found | Run `i2cdetect -y 1`. Expect `3c` for the OLED and usually `68` for the MPU-6050. Check 3.3 V, GND, SDA and SCL |
| A 1.3 inch OLED looks wrong | It may be an SH1106: put `{"oled": {"driver": "sh1106"}}` in `data/companion.json` |
| Vision model export failed | Run `bash scripts/export-model.sh` (needs internet and ~1.5 GB free for a few minutes). Until it works the robot runs without object detection ("Vision disabled" in the log) |
| Encoder counts don't change | Check the wiring on GPIO5/6 and GPIO20/16, and that outputs are at 3.3 V |
| The robot is slow or restarts | Check `free -h` and `vcgencmd measure_temp`, the power supply, and try turning gestures off |
| Voice input doesn't work | Run `.venv/bin/python main.py doctor`, and check that `pywhispercpp` (whisper.cpp) installed. You can still type on the dashboard |
| The robot drives the wrong way | Stop it and correct the motor wiring or pin settings in `robot_config.py` before continuing |

More detail: [`deploy.md`](deploy.md), [`pi.md`](pi.md), [`encoders.md`](encoders.md) and [`companion.md`](companion.md).
