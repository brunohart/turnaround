"""Day 2: property tests. Two properties, each stated once.

1. Whatever small brief the solver is given, if it returns a grid the checker
   passes it clean. The solver and the checker share no code (ADR-003), so this
   is the two readings agreeing across the whole space of briefs, not the two
   examples in the repository.
2. Whatever grid is handed to the checker, its verdict matches a brute-force
   re-check written here from the rules in the brief, with every pair examined.
"""

from __future__ import annotations

import itertools

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from turnaround.check import check
from turnaround.model import Brief, Grid, Session, parse_time
from turnaround.solve import solve

FORMATS = ["2D", "3D"]


@st.composite
def briefs(draw: st.DrawFn) -> Brief:
    n_screens = draw(st.integers(1, 3))
    n_films = draw(st.integers(1, 3))
    screens = [
        {
            "id": f"s{i}",
            "capacity": draw(st.integers(40, 300)),
            "formats": draw(st.sampled_from([["2D"], ["2D", "3D"]])),
            "clean_min": draw(st.one_of(st.none(), st.integers(5, 25))),
        }
        for i in range(n_screens)
    ]
    films = []
    for i in range(n_films):
        terms: dict[str, object] = {
            "min_shows": draw(st.integers(0, 2)),
            "prime_shows": draw(st.integers(0, 1)),
            "exclusive_screen": draw(st.booleans()) if n_screens > 1 else False,
        }
        if draw(st.booleans()):
            terms["max_shows"] = draw(st.integers(1, 4))
        if draw(st.booleans()):
            terms["earliest_start"] = draw(st.sampled_from(["12:00", "14:00", "16:00"]))
        if draw(st.booleans()):
            terms["latest_start"] = draw(st.sampled_from(["17:00", "19:00", "21:00"]))
        films.append(
            {
                "id": f"f{i}",
                "title": f"F{i}",
                "runtime_min": draw(st.integers(60, 150)),
                "format": draw(st.sampled_from(FORMATS)),
                "weight": draw(st.floats(0.3, 2.5)),
                "terms": terms,
            }
        )
    open_ = draw(st.sampled_from(["10:00", "12:00", "13:30"]))
    last = draw(st.sampled_from(["19:00", "20:30", "22:00"]))
    return Brief.model_validate(
        {
            "house": "Random",
            "screens": screens,
            "films": films,
            "policy": {
                "open": open_,
                "last_start": last,
                "preshow_min": draw(st.integers(0, 25)),
                "clean_min": draw(st.integers(5, 30)),
                "stagger_min": draw(st.integers(0, 15)),
                "slot_min": draw(st.sampled_from([15, 30])),
            },
        }
    )


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(briefs())
def test_whatever_the_solver_returns_the_checker_passes_clean(brief: Brief) -> None:
    grid = solve(brief, time_limit_s=8)
    if grid.status not in ("OPTIMAL", "FEASIBLE"):
        assert grid.sessions == []
        return
    rep = check(brief, grid)
    assert rep.clean, [(c.name, c.film, c.evidence) for c in rep.failures]


def brute(brief: Brief, grid: Grid) -> bool:
    """The rules, re-read from the brief with every pair of sessions examined.
    No sorting, no consecutive-pair shortcut, no shared helper beyond the model."""
    p = brief.policy
    screen_ids = {s.id for s in brief.screens}
    film_ids = {f.id for f in brief.films}
    for s in grid.sessions:
        if s.screen not in screen_ids or s.film not in film_ids:
            return False
        scr, f = brief.screen(s.screen), brief.film(s.film)
        clean = scr.clean_min if scr.clean_min is not None else p.clean_min
        if s.feature_start != s.start + p.preshow_min:
            return False
        if s.feature_end != s.feature_start + f.runtime_min:
            return False
        if s.clear != s.feature_end + clean:
            return False
        if s.start < p.open_min or s.start > p.last_start_min:
            return False
        if (s.start - p.open_min) % p.slot_min:
            return False
        if f.format not in scr.formats:
            return False
        if f.terms.screens is not None and scr.id not in f.terms.screens:
            return False
        if f.terms.min_capacity is not None and scr.capacity < f.terms.min_capacity:
            return False
        if f.terms.earliest_start and s.start < parse_time(f.terms.earliest_start):
            return False
        if f.terms.latest_start and s.start > parse_time(f.terms.latest_start):
            return False
    for a, b in itertools.combinations(grid.sessions, 2):
        if a.screen == b.screen and a.start < b.clear and b.start < a.clear:
            return False
        if abs(a.start - b.start) < p.stagger_min:
            return False
    for f in brief.films:
        mine = [s for s in grid.sessions if s.film == f.id]
        t = f.terms
        if len(mine) < t.min_shows:
            return False
        if t.max_shows is not None and len(mine) > t.max_shows:
            return False
        if sum(1 for s in mine if p.prime_start_min <= s.start < p.prime_end_min) < t.prime_shows:
            return False
        if t.exclusive_screen:
            owns = False
            for scr in brief.screens:
                here = [s for s in grid.sessions if s.screen == scr.id]
                if here and all(s.film == f.id for s in here):
                    owns = True
            if not owns:
                return False
    return True


@st.composite
def briefs_with_hand_grids(draw: st.DrawFn) -> tuple[Brief, Grid]:
    brief = draw(briefs())
    p = brief.policy
    n = draw(st.integers(0, 6))
    sessions = []
    for _ in range(n):
        scr = draw(st.sampled_from(brief.screens))
        f = draw(st.sampled_from(brief.films))
        # Mostly on the grid and inside the hours; sometimes not, so both verdicts occur.
        if draw(st.integers(0, 4)):
            start = p.open_min + draw(st.integers(0, 40)) * p.slot_min
        else:
            start = draw(st.integers(p.open_min - 60, p.last_start_min + 90))
        fs = start + p.preshow_min
        fe = fs + f.runtime_min
        clean = scr.clean_min if scr.clean_min is not None else p.clean_min
        clear = fe + clean + (draw(st.integers(-3, 3)) if draw(st.integers(0, 9)) == 0 else 0)
        sessions.append(
            Session(
                screen=scr.id, film=f.id, start=start, feature_start=fs, feature_end=fe, clear=clear
            )
        )
    grid = Grid(house=brief.house, status="HAND", objective=0, solve_seconds=0, sessions=sessions)
    return brief, grid


@settings(max_examples=300, deadline=None)
@given(briefs_with_hand_grids())
def test_checker_verdict_matches_a_brute_force_reread(pair: tuple[Brief, Grid]) -> None:
    brief, grid = pair
    assert check(brief, grid).clean == brute(brief, grid)
