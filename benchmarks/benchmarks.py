#!/usr/bin/env python3
"""
Open-source benchmarks for the whole project (benchmarks/requirements.txt). Reports go to benchmarks/results/suite_<time>.json.

    python benchmarks/benchmarks.py perf                speed of planners, costmap, filters        (pyperf, MIT)
    python benchmarks/benchmarks.py planners            our planners vs PythonRobotics A*           (MIT)
    python benchmarks/benchmarks.py odometry            pose error, simulated or from TUM files     (evo, GPL-3.0)
    python benchmarks/benchmarks.py tracking            fixed vs adaptive detection                 (TrackEval, MIT)
    python benchmarks/benchmarks.py detection --limit 50   mAP on COCO val2017 images               (pycocotools)
    python benchmarks/benchmarks.py speech --limit 20   word error rate on LibriSpeech dev-clean     (jiwer, Apache-2.0)
    python benchmarks/benchmarks.py all                 everything that needs no large download

Hardware odometry:  python benchmarks/benchmarks.py odometry --reference truth.tum --estimate robot.tum
Your own tracking data (MOT format): python benchmarks/benchmarks.py tracking --gt gt.txt --results tracker.txt
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "run_prototype"     # the robot's code lives here
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parents[1] / "benchmarks")]

import deskbot  # noqa: E402,F401  (sys.path setup)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", choices=["perf", "planners", "odometry", "tracking", "detection", "speech", "all"])
    p.add_argument("--limit", type=int, default=30, help="images or audio clips")
    p.add_argument("--reference"), p.add_argument("--estimate")
    p.add_argument("--gt"), p.add_argument("--results")
    p.add_argument("--whisper-model", default="tiny.en")
    a = p.parse_args()
    from desk_bench import suite

    jobs = {"perf": suite.perf, "planners": suite.planners,
            "odometry": lambda: suite.odometry(a.reference, a.estimate),
            "tracking": lambda: suite.tracking(a.gt, a.results),
            "detection": lambda: suite.detection(a.limit),
            "speech": lambda: suite.speech(a.limit, a.whisper_model)}
    names = ["perf", "planners", "odometry", "tracking"] if a.name == "all" else [a.name]
    out, failed = {}, False
    for name in names:
        print(f"\n=== {name} ===", flush=True)
        try:
            out[name] = jobs[name]()
            print(json.dumps(out[name], indent=2))
        except Exception as exc:
            failed = True
            out[name] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"FAILED: {out[name]['error']}")
    folder = suite.BENCH_HOME / "results"
    folder.mkdir(exist_ok=True)
    path = folder / time.strftime("suite_%Y%m%d_%H%M%S.json")
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSaved {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
