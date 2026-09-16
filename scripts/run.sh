#!/usr/bin/env bash
# Solve every example and write its grid + sheet into docs/grids/. The sheets are the screenshots.
# An example whose terms conflict on purpose (exit 2) is re-planned with --relax so its sheet
# shows what was given up; any other failure stops the script.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# uv re-hides .venv under ~/Documents after every command it runs (see build.sh), and any
# other uv invocation on the machine does the same mid-run, so every command unhides it first.
tr() { chflags -R nohidden .venv 2>/dev/null || true; uv run turnaround "$@"; }
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
  tr plan "$b" --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet --time-limit $tl $why || rc=$?
  if [ "$rc" -eq 2 ]; then
    tr plan "$b" --relax --out "docs/grids/$n.json" --html "docs/grids/$n.html" --quiet --time-limit $tl
  elif [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
  tr terms "$b" "docs/grids/$n.json" --html "docs/grids/$n-terms.html"
  # Out (Day 9): a calendar per screen, a flat CSV for signage, JSON for a website.
  tr export "$b" "docs/grids/$n.json" --out-dir docs/grids/export
  if [ "$n" = "regent" ]; then
    # In (Day 9): the Regent's Thursday as a manager typed it, imported against the brief and
    # rendered with its proof. The checker is meant to reject it — the slips are the point —
    # so its exit code is reported, not obeyed.
    tr import --csv examples/regent-hand.csv --brief "$b" --out docs/grids/regent-hand.json
    tr render "$b" docs/grids/regent-hand.json --html docs/grids/regent-hand.html
    tr check "$b" docs/grids/regent-hand.json \
      || echo "regent-hand: the checker rejects the hand-made grid, as it should (exit $?)"
  fi
done
