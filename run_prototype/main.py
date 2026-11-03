#!/usr/bin/env python3
"""
The one command for the whole desk robot project.

    python main.py                 menu of everything
    python main.py start           start the robot (add --sim to try it without hardware)
    python main.py calibrate       run the complete calibration
    python main.py --help          all commands

Details: README.md
"""

import multiprocessing
import sys


def main():
    from deskbot.companion.cli import main as run
    return run()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
