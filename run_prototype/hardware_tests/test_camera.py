"""
Raspberry Pi camera test - shows the camera image IN THE TERMINAL (works over SSH).
Standalone: needs only picamera2 + numpy (both preinstalled on Raspberry Pi OS Bookworm).

    python3 hardware_tests/test_camera.py                 # live view until you press Enter
    python3 hardware_tests/test_camera.py --snap          # one picture, then exit
    python3 hardware_tests/test_camera.py --save pic.jpg  # also save a full-resolution JPEG
    python3 hardware_tests/test_camera.py --ascii         # plain characters (terminals without colour)
    python3 hardware_tests/test_camera.py --width 80      # fixed width in characters (default: fit terminal)

Colour mode draws two pixels per character with the "▀" half block (top pixel = text
colour, bottom pixel = background), using 24-bit ANSI colour.
"""

import argparse
import shutil
import sys
import threading
import time

ASCII_RAMP = " .:-=+*#%@"   # dark -> bright
CAPTURE_SIZE = (640, 480)


def open_camera():
    try:
        from picamera2 import Picamera2
    except ImportError:
        sys.exit("picamera2 is not installed:  sudo apt install -y python3-picamera2")

    cameras = Picamera2.global_camera_info()
    if not cameras:
        sys.exit("No camera detected.\n"
                 "  - Power off, reseat the ribbon cable (contacts facing the right way at both ends)\n"
                 "  - Check:  rpicam-hello --list-cameras   (older OS: libcamera-hello --list-cameras)\n"
                 "  - Make sure no other program (e.g. rpicam-hello) is using the camera")
    info = cameras[0]
    print(f"Camera: {info.get('Model', '?')}  (found {len(cameras)})")

    cam = Picamera2()
    # "RGB888" in picamera2 returns pixels in B, G, R byte order - flipped in grab()
    cam.configure(cam.create_preview_configuration(main={"size": CAPTURE_SIZE, "format": "RGB888"}))
    cam.start()
    time.sleep(1.0)  # let auto exposure / white balance settle
    return cam


def grab(cam):
    return cam.capture_array("main")[:, :, 2::-1]  # BGR -> RGB, drops any 4th channel


def fit(img_h, img_w, width, ascii_mode):
    term = shutil.get_terminal_size((80, 24))
    cols = width or term.columns
    rows_avail = max(4, term.lines - 3)            # leave room for the status line
    # a terminal cell is ~2x taller than wide: ascii = 1 pixel/cell, colour = 2 pixels/cell
    rows = int(cols * img_h / img_w / 2)
    if rows > rows_avail:
        rows = rows_avail
        cols = int(rows * 2 * img_w / img_h)
    return max(cols, 1), max(rows, 1)


def render(rgb, width, ascii_mode):
    import numpy as np

    h, w = rgb.shape[:2]
    cols, rows = fit(h, w, width, ascii_mode)
    xs = np.linspace(0, w - 1, cols).astype(int)

    if ascii_mode:
        ys = np.linspace(0, h - 1, rows).astype(int)
        small = rgb[ys][:, xs].astype(float)
        lum = (0.299 * small[..., 0] + 0.587 * small[..., 1] + 0.114 * small[..., 2]) / 255
        idx = (lum * (len(ASCII_RAMP) - 1)).round().astype(int)
        return "\n".join("".join(ASCII_RAMP[i] for i in row) for row in idx)

    ys = np.linspace(0, h - 1, rows * 2).astype(int)
    small = rgb[ys][:, xs]
    lines = []
    for r in range(rows):
        top, bottom = small[2 * r], small[2 * r + 1]
        parts = [f"\x1b[38;2;{t[0]};{t[1]};{t[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m▀" for t, b in zip(top, bottom)]
        lines.append("".join(parts) + "\x1b[0m")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Show the Pi camera image in the terminal")
    ap.add_argument("--snap", action="store_true", help="show one picture and exit")
    ap.add_argument("--save", metavar="FILE", help="also save a JPEG (e.g. pic.jpg)")
    ap.add_argument("--ascii", action="store_true", help="plain characters instead of colour blocks")
    ap.add_argument("--width", type=int, default=0, help="width in characters (default: fit terminal)")
    args = ap.parse_args()

    cam = open_camera()
    try:
        if args.save:
            cam.capture_file(args.save)
            print(f"Saved {args.save}")

        if args.snap:
            print(render(grab(cam), args.width, args.ascii))
            return

        stop = threading.Event()

        def wait_for_enter():
            try:
                input()
            except EOFError:
                pass
            stop.set()

        threading.Thread(target=wait_for_enter, daemon=True).start()
        sys.stdout.write("\x1b[2J\x1b[?25l")  # clear screen, hide cursor
        frames, t0 = 0, time.monotonic()
        try:
            while not stop.is_set():
                frame = render(grab(cam), args.width, args.ascii)
                frames += 1
                fps = frames / max(time.monotonic() - t0, 1e-6)
                sys.stdout.write(f"\x1b[H{frame}\n\x1b[0mLive view  {fps:4.1f} fps  - press Enter to stop\x1b[K")
                sys.stdout.flush()
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write("\x1b[0m\x1b[?25h\n")  # reset colours, show cursor
            print(f"Stopped after {frames} frames.")
    finally:
        cam.stop()
        cam.close()


if __name__ == "__main__":
    main()
