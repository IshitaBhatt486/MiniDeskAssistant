# Camera test: `hardware_test.py camera` (13 Nov 2026; was `test_camera.py` until 20 Nov 2026, see hardware-test.md)

Shows the Raspberry Pi camera module's image **directly in the terminal**, so it works over SSH with no monitor
and no desktop. Standalone: it needs only `picamera2` and `numpy`, which are both preinstalled on Raspberry Pi OS Bookworm
(otherwise `sudo apt install -y python3-picamera2`).

```bash
python3 hardware_tests/hardware_test.py camera                 # live view until you press Enter (or Ctrl+C)
python3 hardware_tests/hardware_test.py camera --snap          # one picture, then exit
python3 hardware_tests/hardware_test.py camera --save pic.jpg  # also save a JPEG (copy it to a laptop to see it properly)
python3 hardware_tests/hardware_test.py camera --ascii         # plain characters, for terminals without colour
python3 hardware_tests/hardware_test.py camera --width 80      # fixed width in characters (default: fit the terminal)
```

To view the saved photo on your laptop: `scp pi@<pi-ip>:~/desk-assistant-robot/pic.jpg .`

## How it works

1. **Detect:** `Picamera2.global_camera_info()` lists the attached cameras. If there are none, the script prints the
   checklist below and exits. Otherwise it prints the sensor model (e.g. `imx708` = Camera Module 3,
   `imx219` = v2, `ov5647` = v1).
2. **Configure:** a preview configuration at 640 × 480 in `RGB888`. picamera2's "RGB888" actually stores bytes as
   **B, G, R**, so `grab()` flips the channels (`[:, :, 2::-1]`). Without that, red and blue would be swapped. It waits
   1 s after `start()` so auto-exposure and white balance can settle (otherwise the first frames are dark or tinted).
3. **Scale:** `fit()` uses the terminal size (`shutil.get_terminal_size`) and keeps the aspect ratio. A
   terminal cell is about twice as tall as it is wide, so:
   - colour mode packs **2 pixels per cell vertically**: `rows = cols × h / w / 2` cells, giving `2 × rows` pixel rows
   - ASCII mode samples **1 pixel per cell**, with the same row count, so both look the same shape
   - if the image would be taller than the terminal, it's scaled down to fit (3 lines are kept for the status line)

   Pixels are picked with nearest-neighbour sampling (`numpy.linspace` index arrays). That's fast enough for a live view.
4. **Draw:**
   - **Colour:** each cell is the upper-half-block character `▀`. Its text colour is the top pixel and its background colour is
     the bottom pixel, using 24-bit ANSI escape codes (`ESC[38;2;R;G;Bm` / `ESC[48;2;R;G;Bm`). Each line ends with a reset.
   - **ASCII:** brightness = 0.299 R + 0.587 G + 0.114 B, mapped onto `" .:-=+*#%@"` (dark → bright).
5. **Live loop:** clears the screen once and hides the cursor. Each frame moves the cursor to the top-left (`ESC[H`) and
   overwrites the previous one, so there's no flicker or scrolling, with a status line showing the frame rate. A background thread waits for Enter
   and sets a `threading.Event`. On exit, the colours are reset, the cursor is shown again, and the camera is stopped and closed (even after
   `Ctrl+C`).
6. **`--save`** calls `capture_file()` on the running camera (a JPEG of the 640 × 480 stream).

## If it fails

| Message / symptom | Fix |
| --- | --- |
| `picamera2 is not installed` | `sudo apt install -y python3-picamera2` (don't use pip inside a venv; it needs the system libcamera) |
| `No camera detected` | power off and reseat the ribbon at both ends (on the Pi 4 the contacts face the HDMI ports); check `rpicam-hello --list-cameras` (`libcamera-hello` on older OS) |
| "Camera in use" / failed to acquire | another program has the camera; close `rpicam-hello` and any other camera script |
| Garbage characters instead of an image | the terminal doesn't support 24-bit colour; use `--ascii` |
| Image is dark or tinted | lighting; the first second is skipped already, so wait a few frames in live mode |
| Red and blue look swapped | a different picamera2 format; remove the `2::-1` flip in `grab()` |
| Very slow live view | make the terminal smaller or use `--width 60`; drawing more characters costs more time |

## Verified

Tested against a fake `picamera2` module that returns a known pattern (red/green/blue/white bars over a grey ramp,
stored in B, G, R order like the real camera):
- colour mode output the exact colours `(255,0,0)`, `(0,255,0)`, `(0,0,255)` and `(255,255,255)`, so the BGR → RGB flip is correct
- ASCII mode rendered the bars and a smooth dark→bright ramp
- live mode drew 279 frames in about 3 s and stopped cleanly on Enter (exit code 0)
- "no camera" printed the troubleshooting checklist

**Not run with the real camera yet.**

## Next: object detection (15 Nov 2026)

The camera is now used by the full app for YOLO26n + ByteTrack object detection and the semantic map. Terminal test:
`bash scripts/sensors.sh detect`. Design and latency: [vision.md](vision.md).
