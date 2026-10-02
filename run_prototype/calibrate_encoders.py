#!/usr/bin/env python3
"""
Measure the wheel encoders on the Pi (GPIO5/6 left, GPIO20/16 right). Saves data/encoders.json.

    python calibrate_encoders.py --diameter 0.065 --revolutions 10

Lift the robot. Turn each wheel by hand, FORWARD, exactly that many revolutions when asked.
Until this file exists, the encoders are used to detect stuck wheels but not to measure distance.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import deskbot  # noqa: E402,F401  (sys.path setup)
from deskbot.config import ENCODER_FILE  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--diameter", type=float, required=True, help="wheel diameter in metres")
    p.add_argument("--revolutions", type=float, default=10)
    a = p.parse_args()
    from deskbot.runtime.hardware import open_encoders

    enc = open_encoders()
    if enc is None:
        print("Could not open the encoders. Run this on the Pi with GPIO5, 6, 16 and 20 wired.")
        return 1
    result = {"wheel_diameter_m": a.diameter}
    for i, side in enumerate(("left", "right")):
        input(f"Press Enter, then turn the {side} wheel forward {a.revolutions:g} revolutions...")
        start = enc.read()[i]
        input("Press Enter when done.")
        time.sleep(0.1)
        counts = enc.read()[i] - start
        if abs(counts) < 5:
            print(f"The {side} encoder barely changed ({counts}). Check its wiring.")
            return 1
        result[f"{side}_counts_per_rev"] = abs(counts) / a.revolutions
        result[f"{side}_sign"] = 1 if counts > 0 else -1
        print(f"  {side}: {result[f'{side}_counts_per_rev']:.1f} counts per revolution, sign {result[f'{side}_sign']:+d}")
    ENCODER_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENCODER_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved {ENCODER_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
