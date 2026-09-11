#!/usr/bin/env bash
# Solve every example and write its grid + sheet into docs/grids/. The sheets are the screenshots.
# An example whose terms conflict on purpose (exit 2) is re-planned with --relax so its sheet
# shows what was given up; any other failure stops the script.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
chflags -R nohidden .venv 2>/dev/null || true  # see build.sh
mkdir -p docs/grids
for b in examples/*.json; do
  n=$(basename "$b" .json)
  rc=0
  uv run turnaround plan "$b" --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet || rc=$?
  if [ "$rc" -eq 2 ]; then
    uv run turnaround plan "$b" --relax --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet
  elif [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  uv run turnaround terms "$b" "docs/grids/$n.json" --html "docs/grids/$n-terms.html"
done
