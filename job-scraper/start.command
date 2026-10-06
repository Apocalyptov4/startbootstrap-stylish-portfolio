#!/bin/sh
# Double-click this file on macOS (or run ./start.command on Linux) to open Job Radar.
cd "$(dirname "$0")" || exit 1
PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
if ! command -v $PY >/dev/null 2>&1; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ and try again."
  read -r _; exit 1
fi
$PY -c "import requests" 2>/dev/null || $PY -m pip install --user -r requirements.txt
exec $PY -m jobscraper ui "$@"
