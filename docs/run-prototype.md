# run_prototype/: what goes on the robot

(This was `run_prototype/README.md` until 20 Nov 2026; it moved here so the folder holds only what the robot runs.)

Everything the robot needs to run and be tested. The folder works on its own: copy only `run_prototype/` to the Raspberry Pi.
Documentation, unit tests, benchmarks, the digital twin, older scripts and laptop-only tools (`tools/deploy.sh`) stay outside it.

## Put it on the Pi

Full guide: [install-on-raspberry-pi.md](install-on-raspberry-pi.md). In short, use **64-bit Raspberry Pi OS** with SSH enabled. From the top of the repository, in Git Bash on the laptop:

```bash
bash tools/deploy.sh pi@<pi-address> --install
```

This copies the folder to `~/deskbot`, then installs the packages and prepares the vision model. It needs internet on the Pi.
If you copied the folder by USB instead, run `bash scripts/setup.sh` inside it. Then:

```bash
ssh pi@<pi-address>
sudo reboot                                  # once, so I2C is on
cd ~/deskbot
cp secrets.env.example secrets.env           # optional: add ANTHROPIC_API_KEY for conversation
.venv/bin/python main.py check               # libraries, MPU-6050 and OLED
.venv/bin/python calibrate_encoders.py --diameter <wheel diameter in metres> --revolutions 10
.venv/bin/python main.py calibrate           # leave 30 cm clear
.venv/bin/python main.py health              # test every part
.venv/bin/python main.py start --lan         # dashboard: http://<pi-address>:8000
```

To try it on a computer without hardware: `python main.py start --sim`.

## What is here

| Path | Purpose |
|---|---|
| `main.py` | The one command for the robot |
| `robot_config.py` | Every pin number |
| `calibrate_encoders.py` | Measures the wheel encoders |
| `deskbot/` | The robot application |
| `dashboard/` | Motor, sensor and safety code, and the base web dashboard |
| `hardware_tests/` | `hardware_test.py`: every sensor, camera, mic, OLED and touch test in one menu |
| `scripts/` | Install, start, start-on-boot and hotspot scripts (deploying is `tools/deploy.sh`, outside) |
| `requirements*.txt` | Python packages |
| `models/`, `data/`, `outputs/` | Created on the machine: vision models, settings and keys, saved results. Not copied by `tools/deploy.sh` |

## Where the eyes appear

On the **SSD1306 128x64 I2C OLED** (address 0x3C): VCC to pin 1, GND to pin 6, SDA to pin 3, SCL to pin 5.
The same picture is mirrored on the dashboard's face card. Test it with `python main.py face`, or save
every animation as images with `python main.py face --preview`.
