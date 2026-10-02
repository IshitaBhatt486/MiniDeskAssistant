"""
Microphone test - STANDALONE (uses only the preinstalled ALSA tools arecord/aplay).

    python3 hardware_tests/test_microphone.py

A bare 2-wire electret capsule (red/black) can NOT be wired to the Pi's GPIO - the Pi has
no analog audio input. Connect it to a USB sound card's mic input (red -> plug tip,
black -> plug sleeve); the sound card powers the capsule. See docs/microphone.md.

Menu:
  1. live level meter  - a bar that moves with sound, until you press Enter
  2. record 5 s and play it back (needs speakers/headphones on the sound card or Pi)
  3. pick a different input device
"""

import array
import math
import re
import shutil
import subprocess
import sys
import threading

RATE = 16000          # Hz - plenty for voice, supported by almost every USB card
CHUNK = RATE // 20    # samples per meter update (50 ms)
RECORD_SECONDS = 5
CLIP = "mic_test.wav"


def require_tools():
    missing = [t for t in ("arecord", "aplay") if not shutil.which(t)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}:  sudo apt install -y alsa-utils")


def list_capture_devices():
    """[(alsa_name, description)] from `arecord -l`."""
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    devices = []
    for m in re.finditer(r"card (\d+): (\S+) \[(.*?)\], device (\d+): .*?\[(.*?)\]", out):
        card, _, card_name, dev, dev_name = m.groups()
        devices.append((f"plughw:{card},{dev}", f"{card_name} - {dev_name}"))
    return devices


def choose_device():
    devices = list_capture_devices()
    if not devices:
        print("\nNo microphone / capture device found.")
        print("  - Is the USB sound card plugged in?  Check:  lsusb   and   arecord -l")
        print("  - The Pi's own 3.5 mm jack is output only - it cannot record.")
        sys.exit(1)
    print("\nCapture devices:")
    for i, (name, desc) in enumerate(devices, 1):
        print(f"  {i}. {desc}  ({name})")
    if len(devices) == 1:
        print("Using the only device.")
        return devices[0][0]
    while True:
        choice = input("Device number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(devices):
            return devices[int(choice) - 1][0]


def level_meter(device):
    print(f"\nLive level on {device} - speak, clap or tap the mic. Press Enter to stop.\n")
    proc = subprocess.Popen(
        ["arecord", "-D", device, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw", "-q"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stop = threading.Event()

    def wait_for_enter():
        try:
            input()
        except EOFError:
            pass
        stop.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()
    peak_db, quietest_db = -120.0, 0.0
    width = max(20, min(60, shutil.get_terminal_size((80, 24)).columns - 30))
    try:
        while not stop.is_set():
            data = proc.stdout.read(CHUNK * 2)
            if not data:
                err = proc.stderr.read().decode(errors="replace").strip()
                print(f"\narecord stopped: {err or 'no data'}")
                break
            samples = array.array("h", data)
            rms = math.sqrt(sum(s * s for s in samples) / len(samples)) or 1e-9
            db = 20 * math.log10(rms / 32768)            # dBFS: 0 = loudest possible
            peak_db, quietest_db = max(peak_db, db), min(quietest_db, db)
            filled = int(max(0.0, min(1.0, (db + 60) / 60)) * width)   # -60..0 dBFS -> bar
            clip = "  CLIPPING" if max(abs(min(samples)), max(samples)) >= 32700 else ""
            print(f"\r{db:6.1f} dBFS |{'#' * filled}{' ' * (width - filled)}|{clip:<10}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait()
    if peak_db > -120:
        print(f"\n\nQuietest {quietest_db:.1f} dBFS, loudest {peak_db:.1f} dBFS")
        if peak_db - quietest_db < 6:
            print("Hardly any change - the mic may not be connected/powered, or the input is muted (run: alsamixer, F4).")
        else:
            print("Level reacts to sound - the microphone works.")


def record_and_play(device):
    print(f"\nRecording {RECORD_SECONDS} s from {device} - talk now...")
    r = subprocess.run(["arecord", "-D", device, "-f", "S16_LE", "-c", "1", "-r", str(RATE),
                        "-d", str(RECORD_SECONDS), CLIP], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Recording failed: {r.stderr.strip()}")
        return
    print(f"Saved {CLIP}. Playing it back...")
    p = subprocess.run(["aplay", CLIP], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"Playback failed ({p.stderr.strip()}). Copy {CLIP} to a laptop to listen:  scp pi@<pi-ip>:{CLIP} .")
    else:
        print("Done. Heard yourself? The mic works. Silence/hiss only? Check wiring and alsamixer capture level.")


def main():
    require_tools()
    device = choose_device()
    while True:
        print(f"\nMicrophone test  ({device})")
        print("  1. live level meter")
        print(f"  2. record {RECORD_SECONDS} s and play back")
        print("  3. choose another device")
        print("  q. quit")
        try:
            choice = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if choice == "1":
            level_meter(device)
        elif choice == "2":
            record_and_play(device)
        elif choice == "3":
            device = choose_device()
        elif choice in ("q", "quit", "0"):
            break
        else:
            print("Enter 1, 2, 3 or q.")
    print("Bye.")


if __name__ == "__main__":
    main()
