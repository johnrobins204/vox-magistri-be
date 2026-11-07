#!/usr/bin/env bash
# Quiet CI gate: prints one line per step when it passes, full output only on failure.
# Usage: scripts/gate.sh            (full gate: pytest, ruff, black)
#        scripts/gate.sh tests/test_x.py -k name   (extra args go to pytest only, ruff/black skipped)
set -u
cd "$(dirname "$0")/.."
BIN=./venv-dnd-server/bin
[ -x "$BIN/pytest" ] || BIN=$(dirname "$(command -v pytest)")

run() {
  local label=$1
  shift
  local out
  if out=$("$@" 2>&1); then
    echo "ok   $label: $(echo "$out" | tail -n 1)"
  else
    echo "FAIL $label"
    echo "$out"
    exit 1
  fi
}

if [ $# -gt 0 ]; then
  run pytest "$BIN/pytest" -q -p no:warnings "$@"
  exit 0
fi

run pytest "$BIN/pytest" -q -p no:warnings
run ruff "$BIN/ruff" check app tests scripts
run black "$BIN/black" --check app tests scripts
