#!/usr/bin/env bash
# Benchmark: detection under 11 lighting conditions (COCO), tracking with detect-every-N (Objectron),
# and the multi-process runtime's latency. Report in benchmarks/results/<date>/report.md
#   tools/run_benchmarks.sh                    everything (downloads ~420 MB of data the first time, keeps ~85 MB)
#   tools/run_benchmarks.sh download           data only
#   tools/run_benchmarks.sh images --limit 50  quick accuracy run
#   tools/run_benchmarks.sh video --every 1,3,5
#   tools/run_benchmarks.sh video --video my_desk.mp4 --label cup
#   tools/run_benchmarks.sh system             runtime latency only (no data, no model)
source "$(dirname "${BASH_SOURCE[0]}")/../run_prototype/scripts/_common.sh"
exec "$PY" -m deskbot bench "$@"
