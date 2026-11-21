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
    # 21 Nov 2026: errors are explained instead of dumped (deskbot/recovery.py, docs/error-recovery.md).
    # Started with the system Python (`python3 main.py` on the Pi)? Switch to .venv, where setup.sh put the packages.
    from deskbot import recovery
    recovery.use_project_venv()
    try:
        from deskbot.companion.cli import main as run
        return run()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:                 # last line of defence: explain, save the traceback, offer the fix
        recovery.report_crash(exc, "main.py")
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
