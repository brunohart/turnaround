#!/usr/bin/env bash
# Solve every example and write its grid + sheet into docs/grids/. The sheets are the screenshots.
# An example whose terms conflict on purpose (exit 2) is re-planned with --relax so its sheet
# shows what was given up; any other failure stops the script.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
chflags -R nohidden .venv 2>/dev/null || true  # see build.sh
mkdir -p docs/grids
# With names given (scripts/run.sh sixteen regent) only those examples are regenerated.
if [ "$#" -gt 0 ]; then
  briefs=()
  for n in "$@"; do briefs+=("examples/$n.json"); done
else
  briefs=(examples/*.json)
fi
for b in "${briefs[@]}"; do
  n=$(basename "$b" .json)
  rc=0
  why=""
  tl=30
  [ "$n" = "regent" ] && why="--why"  # the hero sheet carries every session's why (one solve per session)
  [ "$n" = "sixteen" ] && tl=90       # the multiplex: the bench's minute per day and a half again (docs/bench.md)
  chflags -R nohidden .venv 2>/dev/null || true  # uv re-hides it under ~/Documents
  uv run turnaround plan "$b" --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet --time-limit $tl $why || rc=$?
  if [ "$rc" -eq 2 ]; then
    uv run turnaround plan "$b" --relax --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet --time-limit $tl
  elif [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  uv run turnaround terms "$b" "docs/grids/$n.json" --html "docs/grids/$n-terms.html"
done
