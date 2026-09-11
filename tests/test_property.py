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
            "open": draw(st.sampled_from([None, "14:00", "15:30"])),
            "last_start": draw(st.sampled_from([None, "18:00", "19:30"])),
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
        if draw(st.booleans()):  # a brief with min_shows above max_shows is refused
            terms["max_shows"] = draw(st.integers(max(1, int(terms["min_shows"])), 4))
        if draw(st.booleans()):
            terms["earliest_start"] = draw(st.sampled_from(["12:00", "14:00", "16:00"]))
        if draw(st.booleans()):
            terms["latest_start"] = draw(st.sampled_from(["17:00", "19:00", "21:00"]))
        film: dict[str, object] = {
            "id": f"f{i}",
            "title": f"F{i}",
            "runtime_min": draw(st.integers(60, 150)),
            "credits_min": draw(st.sampled_from([0, 0, 5, 12, 30])),
            "format": draw(st.sampled_from(FORMATS)),
            "weight": draw(st.floats(0.3, 2.5)),
            "terms": terms,
        }
        if draw(st.booleans()):  # a stated demand block; otherwise weight stands in
            film["demand"] = {
                "per_session": {
                    d: draw(st.floats(0, 400)) for d in ["matinee", "afternoon", "prime", "late"]
                },
                "decay": draw(st.floats(0.2, 1.0)),
                "weekday": {"Sat": draw(st.floats(0.5, 2.0))},
                "holiday": draw(st.floats(1.0, 2.0)),
            }
        films.append(film)
    open_ = draw(st.sampled_from(["10:00", "12:00", "13:30"]))
    last = draw(st.sampled_from(["19:00", "20:30", "22:00"]))
    preshow_by_format = {"3D": draw(st.integers(0, 35))} if draw(st.booleans()) else {}
    staff = draw(st.sampled_from([None, 1, 2]))
    return Brief.model_validate(
        {
            "house": "Random",
            "screens": screens,
            "films": films,
            "weekday": draw(st.sampled_from([None, "Sat", "Tue"])),
            "policy": {
                "open": open_,
                "last_start": last,
                "school_holiday": draw(st.booleans()),
                "preshow_min": draw(st.integers(0, 25)),
                "preshow_by_format": preshow_by_format,
                "clean_min": draw(st.integers(5, 30)),
                "max_concurrent_turnarounds": staff,
                "stagger_min": draw(st.integers(0, 15)),
                "max_starts_per_window": draw(st.integers(1, 2)),
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
        preshow = p.preshow_by_format.get(f.format, p.preshow_min)
        if s.feature_start != s.start + preshow:
            return False
        if s.feature_end != s.feature_start + f.runtime_min:
            return False
        turn_end = s.feature_end - f.credits_min + clean
        if s.clear != (turn_end if turn_end > s.feature_end else s.feature_end):
            return False
        opens = parse_time(scr.open) if scr.open is not None else p.open_min
        closes = parse_time(scr.last_start) if scr.last_start is not None else p.last_start_min
        if s.start < opens or s.start > closes:
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
    for a in grid.sessions:
        # The window that starts at a's start, a itself included.
        in_window = [b for b in grid.sessions if 0 <= b.start - a.start < p.stagger_min]
        if len(in_window) > p.max_starts_per_window:
            return False
    if p.max_concurrent_turnarounds is not None:
        turns = []
        for s in grid.sessions:
            clean = brief.clean_for(brief.screen(s.screen))
            begin = s.feature_end - brief.film(s.film).credits_min
            end = max(s.feature_end, begin + clean)
            if end > begin:
                turns.append((begin, end))
        for t in range(
            min((a for a, _ in turns), default=0), max((b for _, b in turns), default=0)
        ):
            if sum(1 for a, b in turns if a <= t < b) > p.max_concurrent_turnarounds:
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
        fs = start + brief.preshow_for(f)
        fe = fs + f.runtime_min
        clear = brief.turnaround_of(scr, f, start)[1]
        if draw(st.integers(0, 9)) == 0:  # now and then, the arithmetic is wrong on purpose
            clear += draw(st.integers(-3, 3))
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
