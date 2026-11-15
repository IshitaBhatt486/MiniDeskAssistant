#!/usr/bin/env bash
# Run all unit tests (no hardware needed). Extra args go to unittest, e.g. -v
source "$(dirname "${BASH_SOURCE[0]}")/../run_prototype/scripts/_common.sh"
cd "$ROOT/.."
exec "$PY" -m unittest discover -s tests -t . "$@"
