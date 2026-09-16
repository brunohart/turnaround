"""Bench one day of a brief under each tuning, from the plain Day 7 model up: candidates,
booleans (and how many are rank literals), constraints, the first grid's time, the status,
the seconds, the objective, the bound and the gap. Prints a Markdown table for docs/bench.md.

    uv run scripts/bench.py examples/sixteen.json --day Thu --limit 60
    uv run scripts/bench.py examples/regent.json --limit 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from turnaround.model import Brief, Grid, WeekBrief
from turnaround.solve import PLAIN, Tuning, solve

STEPS: list[tuple[str, Tuning]] = [
    ("Day 7 model, as shipped", PLAIN),
    (
        "+ ranks per capacity class",
        Tuning(group_ranks=True, tighten_ranks=False, symmetry=False, candidate_cap=None),
    ),
    (
        "+ rank count capped by the stagger",
        Tuning(group_ranks=True, tighten_ranks=True, symmetry=False, candidate_cap=None),
    ),
    (
        "+ identical screens ordered by load",
        Tuning(group_ranks=True, tighten_ranks=True, symmetry=True, candidate_cap=None),
    ),
    ("candidate cap 20,000, ranks per screen, no ordering (the unhinted default)", Tuning()),
]


def row(name: str, g: Grid) -> str:
    st = g.stats
    assert st is not None
    first = f"{st.first_feasible_s:.1f}" if st.first_feasible_s is not None else "—"
    gap = "proven" if st.gap == 0.0 else (f"{st.gap:.1%}" if st.gap is not None else "—")
    bound = f"{st.bound:,.1f}" if st.bound is not None else "—"
    return (
        f"| {name} | {st.slot_min} | {st.candidates:,} | {st.booleans:,} | {st.rank_literals:,} "
        f"({st.rank_literals / st.booleans:.0%}) | {st.constraints:,} | {first} | {g.status} | "
        f"{g.solve_seconds:.1f} | {g.objective:,.1f} | {bound} | {gap} |"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief", type=Path)
    ap.add_argument("--day", help="A day of a week brief; the first if omitted")
    ap.add_argument("--limit", type=float, default=60.0)
    ap.add_argument("--hint-from", type=Path, help="A grid JSON to add a hinted row from")
    args = ap.parse_args()
    raw = json.loads(args.brief.read_text())
    if "days" in raw:
        week = WeekBrief.model_validate(raw)
        i = week.day_index(args.day) if args.day else 0
        brief = week.day(i)
        label = f"{week.house} · {week.days[i].name}"
    else:
        brief = Brief.model_validate(raw)
        label = brief.house
    n_s, n_f = len(brief.screens), len(brief.films)
    print(f"### {label} · {n_s} screens · {n_f} titles · {args.limit:.0f} s limit\n")
    print(
        "| model | slot | candidates | booleans | ranks | constraints | first grid s | "
        "status | s | objective | bound | gap |"
    )
    print("|---|--:|--:|--:|--:|--:|--:|---|--:|--:|--:|--:|")
    last: Grid | None = None
    for name, tuning in STEPS:
        g = solve(brief, time_limit_s=args.limit, tuning=tuning)
        print(row(name, g), flush=True)
        last = g
    if last is not None and last.status in ("OPTIMAL", "FEASIBLE"):
        hint = Grid.model_validate_json(args.hint_from.read_text()) if args.hint_from else last
        g = solve(brief, time_limit_s=args.limit, hint=hint)
        src = args.hint_from.name if args.hint_from else "the grid above"
        print(row(f"same, hinted from {src}, ranks per capacity class (the hinted default)", g))


if __name__ == "__main__":
    main()
