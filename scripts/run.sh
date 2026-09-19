#!/usr/bin/env bash
# Solve every example and write its grid + sheet into docs/grids/. The sheets are the screenshots.
# An example whose terms conflict on purpose (exit 2) is re-planned with --relax so its sheet
# shows what was given up; any other failure stops the script — exit 4 above all, which is
# the clock running out and never a reason to drop a term.
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
  # TURNAROUND_SKIP="sixteen" leaves an example's committed grid as it stands. CI sets it:
  # the sixteen needs eight workers to find a first grid inside its minute and a half, a
  # hosted runner has two to four, and a benchmark is not a proof (docs/bench.md). CI still
  # runs the checker over the committed grid.
  case " ${TURNAROUND_SKIP:-} " in *" $n "*) echo "$n: skipped, the committed grid stands"; continue ;; esac
  rc=0
  why=""
  tl=30
  [ "$n" = "regent" ] && why="--why"  # the hero sheet carries every session's why (one solve per session)
  [ "$n" = "sixteen" ] && tl=90       # the multiplex: the bench's minute per day and a half again (docs/bench.md)
  [ "$n" = "festival" ] && tl=20      # the festival: ten sparse days, each proven in about a second
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
    # Diff (Day 11): the Thursday re-plan artefact — the grid the manager typed against the
    # one the solver made, every move a ghost on the sheet.
    tr diff docs/grids/regent-hand.json docs/grids/regent.json --brief "$b" \
      --out docs/grids/regent-replan.json --html docs/grids/regent-replan.html
  fi
done
