"""Puts the robot code and the benchmark package on the import path."""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_REPO / "run_prototype"), str(_REPO / "benchmarks")]
