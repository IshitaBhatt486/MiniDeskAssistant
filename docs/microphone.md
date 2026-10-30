# Microphone: hardware + `test_microphone.py` (13 Nov 2026)

## The module: 2-wire electret capsule (red + black)

A microphone with just two wires is a bare **electret condenser capsule**:

- **red = + (signal and bias supply), black = − (ground)**. Polarity matters: the capsule has a built-in FET.
- It produces a tiny analog voltage (a few mV) and only works when it's powered through a bias resistor.
- **The Raspberry Pi can't read it directly.** The Pi has no analog input, and its 3.5 mm jack is output-only.
  **Do not connect it to a GPIO pin**: you'll just see noise or nothing.

### Ways to connect it

| Option | Parts | Notes |
| --- | --- | --- |
| **USB sound card (recommended)** | any cheap USB audio adapter with a pink 3.5 mm mic jack, plus a 3.5 mm plug | **red → plug tip, black → plug sleeve** (on a 3-contact plug you can join tip and ring). The card supplies the bias voltage ("plug-in power"), so no other parts are needed. Shows up as a normal ALSA capture device |
| Amplifier board + ADC | MAX9814 / MAX4466 module + MCP3008 (SPI) | more wiring. MCP3008 needs SPI (GPIO 8–11, which clashes with the right/rear sonar pins). Only sensible for detecting loudness, not real audio |
| Replace the capsule | a USB microphone, or an I2S MEMS mic (INMP441) | USB is plug-and-play. I2S needs GPIO 18/19/20/21, which are already used or reserved |

If the part has no "MIC" marking and has a magnet on the back, it may be a **speaker or buzzer** rather than a microphone.

## `test_microphone.py`

Standalone. It only uses `arecord`/`aplay` from `alsa-utils`, which come preinstalled on Raspberry Pi OS.

```bash
python3 hardware_tests/test_microphone.py
```

1. Lists the capture devices (parsed from `arecord -l`) and picks the only one automatically, or asks you to choose.
   With none found, it explains what to check (`lsusb`, `arecord -l`, and that the Pi's own jack can't record).
2. Menu:
   - **1. Live level meter:** streams raw audio from `arecord` (16 kHz, mono, signed 16-bit) and shows a bar every 50 ms.
     Press Enter to stop. Then it prints the quietest and loudest levels and a verdict.
   - **2. Record 5 s and play back:** saves `mic_test.wav` with `arecord -d 5`, then plays it with `aplay`. If there's no
     speaker, it tells you to `scp` the file to a laptop.
   - **3. Choose another device.** **q** quits.

### Level meter maths

- For each 50 ms block of 800 samples, RMS = √(mean of sample²). Level in **dBFS** = 20·log10(RMS / 32768), where
  0 dBFS is the loudest possible signal.
- The bar maps −60 … 0 dBFS onto the bar width. `CLIPPING` appears if any sample reaches ±32700 (input too loud, so turn the
  capture gain down).
- Verdict: if loudest − quietest < 6 dB, you get "hardly any change" (not connected or powered, or muted). Otherwise
  "reacts to sound".

Typical levels: a quiet room is −70 to −50 dBFS, normal speech at 30 cm is −35 to −20, and a clap near the mic is −10 to 0.

### If it fails

| Symptom | Fix |
| --- | --- |
| "No microphone / capture device found" | sound card not plugged in or not detected (`lsusb`); a capsule on GPIO is never a capture device |
| Meter stays at the noise floor | red/black swapped, plug in the headphone (green) jack instead of the mic jack, or capture muted: run `alsamixer`, press **F6** to pick the card and **F4** for Capture, then raise the level and unmute (`M`) |
| `arecord stopped: ... Device or resource busy` | another program is recording; close it |
| Recording is only hiss | capsule not biased (some cards don't supply plug-in power; add a 2.2 kΩ resistor from red to 3.3 V), or loose wires |
| Constant `CLIPPING` | capture gain too high in `alsamixer` |

## Verified

- Run end to end with fake `arecord`/`aplay`. It detected `USB PnP Sound Device (plughw:1,0)`, used it automatically,
  record and play-back worked, and `q` exited with code 0.
- The level meter was checked against a signal alternating between −64 dBFS hiss and a −11.7 dBFS tone. The bar followed it, and the verdict was
  "reacts to sound". With a constant quiet signal, the verdict was "hardly any change".
- On Windows (the dev laptop), reading the audio pipe stalls while another thread waits for Enter on a pipe. This is a
  Windows pipe quirk that doesn't affect Linux/the Pi, so the Enter-to-stop meter was checked using a timed stop instead.
- **Not run on the real Pi or sound card yet.**
