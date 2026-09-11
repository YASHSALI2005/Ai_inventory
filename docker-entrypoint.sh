#!/bin/sh
# Build the dataset/results for $1 (default "full") if not already there, then serve.
set -e

PRESET="${1:-full}"
SUMMARY="data/${PRESET}/results/summary.json"

if [ ! -f "$SUMMARY" ]; then
  echo "no results for preset '${PRESET}' — running build/run/score/report ..."
  python cli.py all --preset "$PRESET"
fi

exec python cli.py serve --preset "$PRESET" --host 0.0.0.0 --port 8000 --no-browser
