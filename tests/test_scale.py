"""Day 8: containing the model on a big house. Every tuning switch but the candidate cap
is exact (the tuned optimum is the plain optimum); the cap coarsens the grid and says so;
hints start the search and change nothing; a probe with a budget says unknown honestly."""

from pathlib import Path

from turnaround.check import check
from turnaround.model import Brief, FestivalBrief, Film, WeekBrief
from turnaround.solve import (
    PLAIN,
    Tuning,
    candidates,
    choose_slot,
    day_bounds,
    identical_screens,
    probe_all,
    solve,
    solve_week,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _twins(tiny: Brief) -> Brief:
    """The tiny house with three identical 100-seat rooms and the small one."""
    raw = tiny.model_dump()
    raw["screens"] = [
        {"id": "a", "capacity": 100},
        {"id": "a2", "capacity": 100},
        {"id": "a3", "capacity": 100},
        {"id": "b", "capacity": 60},
    ]
    return Brief.model_validate(raw)


def test_tuned_model_matches_the_plain_one_on_the_regent(regent: Brief) -> None:
    plain = solve(regent, time_limit_s=30, tuning=PLAIN)
    tuned = solve(regent, time_limit_s=30)
    assert plain.status == tuned.status == "OPTIMAL"
    assert abs(plain.objective - tuned.objective) < 0.01
    assert check(regent, tuned).ok
    assert tuned.stats is not None and plain.stats is not None
    assert tuned.stats.slot_min == regent.policy.slot_min and tuned.stats.slot_reason is None
    assert tuned.stats.rank_literals <= plain.stats.rank_literals  # the stagger tightens
    assert tuned.stats.gap == 0.0 and tuned.stats.first_feasible_s is not None


def test_identical_screens_are_found_and_ordered_by_load(tiny: Brief) -> None:
    twins = _twins(tiny)
    groups = identical_screens(twins)
    assert [[s.id for s in g] for g in groups] == [["a", "a2", "a3"]]
    tuned = solve(twins, time_limit_s=20, tuning=Tuning(symmetry=True))
    plain = solve(twins, time_limit_s=20, tuning=PLAIN)
    assert tuned.status == plain.status == "OPTIMAL"
    assert abs(tuned.objective - plain.objective) < 0.01
    assert check(twins, tuned).ok
    assert tuned.stats is not None and tuned.stats.symmetry_groups == 1

    def load(sid: str) -> int:
        return sum(
            twins.block_len(twins.screen(sid), twins.film(s.film))
            for s in tuned.sessions
            if s.screen == sid
        )

    assert load("a") >= load("a2") >= load("a3")


def test_a_booking_that_names_one_twin_breaks_the_group(tiny: Brief) -> None:
    twins = _twins(tiny)
    twins.films[1].terms.screens = ["a2"]
    assert identical_screens(twins) == []
    grid = solve(twins, time_limit_s=20)
    assert grid.status == "OPTIMAL" and all(s.screen == "a2" for s in grid.by_film()["y"])


def test_grouped_ranks_share_a_literal_per_capacity(tiny: Brief) -> None:
    twins = _twins(tiny)
    plain = solve(twins, time_limit_s=20, tuning=Tuning(group_ranks=False, symmetry=False))
    grouped = solve(twins, time_limit_s=20, tuning=Tuning(group_ranks=True))
    unhinted = solve(twins, time_limit_s=20)  # the default: per screen without a hint
    hinted = solve(twins, time_limit_s=20, hint=unhinted)  # and per class with one
    assert plain.stats is not None and grouped.stats is not None
    assert grouped.stats.rank_literals < plain.stats.rank_literals
    assert abs(plain.objective - grouped.objective) < 0.01
    assert unhinted.stats is not None and hinted.stats is not None
    assert unhinted.stats.rank_literals == plain.stats.rank_literals
    assert hinted.stats.rank_literals == grouped.stats.rank_literals


def test_candidate_cap_coarsens_the_grid_and_says_so(tiny: Brief) -> None:
    n = len(candidates(tiny))
    cap = n * 3 // 5
    slot, m, reason = choose_slot(tiny, Tuning(candidate_cap=cap))
    assert slot == 10 and m <= cap and reason is not None and "10-minute grid" in reason
    grid = solve(tiny, time_limit_s=20, tuning=Tuning(candidate_cap=cap))
    assert grid.status == "OPTIMAL"
    assert grid.stats is not None
    assert grid.stats.slot_min == 10 and grid.stats.slot_asked == 5 and grid.stats.slot_reason
    assert all((s.start - tiny.policy.open_min) % 10 == 0 for s in grid.sessions)
    assert check(tiny, grid).ok  # a 10-minute grid is on the 5-minute grid too
    kept, _, none = choose_slot(tiny, Tuning(candidate_cap=None))
    assert kept == 5 and none is None


def test_a_hint_is_taken_and_changes_nothing(tiny: Brief) -> None:
    first = solve(tiny, time_limit_s=20)
    again = solve(tiny, time_limit_s=20, hint=first)
    assert again.stats is not None and again.stats.hinted == len(first.sessions)
    assert abs(again.objective - first.objective) < 0.01


def test_the_week_hints_each_day_from_the_day_before(tiny: Brief) -> None:
    base = tiny.model_dump()
    base.pop("date")
    base.pop("weekday")
    week = WeekBrief.model_validate({**base, "days": [{"name": "Thu"}, {"name": "Fri"}]})
    wg = solve_week(week, time_limit_s=20)
    assert wg.grids[0].stats is not None and wg.grids[0].stats.hinted == 0
    assert wg.grids[1].stats is not None and wg.grids[1].stats.hinted == len(wg.grids[0].sessions)


def test_a_probe_budget_marks_the_rest_unknown(tiny: Brief) -> None:
    grid = solve(tiny, time_limit_s=20)
    probe_all(tiny, grid, time_limit_s=5, budget_s=0.0)
    assert all(
        s.forced and s.forced.by == "unknown" and s.forced.seconds == 0 for s in grid.sessions
    )
    probe_all(tiny, grid, time_limit_s=5, budget_s=None)
    assert all(s.forced and s.forced.by != "unknown" for s in grid.sessions)


def _day_bound_one_title(brief: Brief, film: Film) -> tuple[int, int]:
    """The definition, one title at a time, as it was written before the one-pass version."""
    shows = 0
    prime = 0
    cands = [c for c in candidates(brief) if c.film == film.id]
    for scr in brief.screens:
        mine = [c for c in cands if c.screen == scr.id]
        if not mine:
            continue
        block = brief.block_len(scr, film)
        starts = [c.start for c in mine]
        shows += (max(starts) - min(starts)) // block + 1
        ps = [c.start for c in mine if c.prime]
        if ps:
            prime += (max(ps) - min(ps)) // block + 1
    if film.terms.max_shows is not None:
        shows = min(shows, film.terms.max_shows)
        prime = min(prime, film.terms.max_shows)
    return shows, min(prime, shows)


def test_day_bounds_is_every_title_s_bound_from_one_pass() -> None:
    week = WeekBrief.model_validate_json((EXAMPLES / "regent-week.json").read_text())
    fest = FestivalBrief.model_validate_json((EXAMPLES / "festival.json").read_text())
    # The festival's first four days: prints away, guests due, late nights; the rest repeat them.
    for brief in week.briefs() + fest.briefs()[:4]:
        bounds = day_bounds(brief)
        assert bounds == {f.id: _day_bound_one_title(brief, f) for f in brief.films}
