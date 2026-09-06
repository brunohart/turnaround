#!/usr/bin/env bash
# Solve every example and write its grid + sheet into docs/grids/. The sheets are the screenshots.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p docs/grids
for b in examples/*.json; do
  n=$(basename "$b" .json)
  uv run turnaround plan "$b" --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet
done
