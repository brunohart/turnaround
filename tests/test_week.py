"""Day 2: the week as a unit. Per-day overrides unfold into plain briefs; a title
keeps its start times across the hold days where it can; the checker verifies the
week's own claims."""

import pytest
from pydantic import ValidationError

from turnaround.check import check_week, held_titles
from turnaround.model import Brief, WeekBrief, WeekGrid
from turnaround.solve import solve, solve_week


def _week(tiny: Brief, **extra: object) -> WeekBrief:
    base = tiny.model_dump()
    base.pop("date")
    base.pop("weekday")
    return WeekBrief.model_validate(
        {
            **base,
            "days": [
                {"name": "Thu"},
                {"name": "Fri", "policy": {"last_start": "22:00"}},
                {"name": "Sun", "policy": {"open": "13:00"}},
                {"name": "Mon", "terms": {"x": {"min_shows": 1}}},
                {"name": "Tue"},
            ],
            **extra,
        }
    )


def test_overrides_unfold_into_plain_briefs(tiny: Brief) -> None:
    w = _week(tiny)
    assert w.day(0).policy.last_start == "20:00"
    assert w.day(1).policy.last_start == "22:00"
    assert w.day(1).policy.open == "12:00"  # untouched fields come from the base
    assert w.day(2).policy.open == "13:00"
    assert w.day(3).film("x").terms.min_shows == 1
    assert w.day(0).film("x").terms.min_shows == 2  # the override does not leak
    assert w.day(3).film("y").terms.min_shows == 1
    assert w.hold_indices == [0, 3, 4]  # Thu, Mon, Tue; Fri and Sun are not hold days


def test_week_rejects_unknown_film_field_and_duplicate_day(tiny: Brief) -> None:
    with pytest.raises(ValidationError, match="unknown films"):
        _week(tiny, days=[{"name": "Thu", "terms": {"nobody": {"min_shows": 1}}}])
    with pytest.raises(ValidationError):
        _week(tiny, days=[{"name": "Thu", "policy": {"no_such_field": 1}}])
    with pytest.raises(ValidationError, match="unique"):
        _week(tiny, days=[{"name": "Thu"}, {"name": "Thu"}])


def test_week_solves_day_by_day_and_checks(tiny: Brief) -> None:
    w = _week(tiny)
    wg = solve_week(w, time_limit_s=10)
    assert wg.days == ["Thu", "Fri", "Sun", "Mon", "Tue"]
    assert all(g.status in ("OPTIMAL", "FEASIBLE") for g in wg.grids)
    # Sunday's doors are 13:00; nothing starts before them.
    assert all(s.start >= 13 * 60 for s in wg.grid("Sun").sessions)
    rep = check_week(w, wg)
    assert rep.ok and rep.clean, rep.failures
    assert held_titles(w, wg) == sorted(wg.held, key=held_titles(w, wg).index)


def test_hold_days_keep_their_starts_when_the_house_is_unchanged(tiny: Brief) -> None:
    w = _week(tiny, days=[{"name": "Mon"}, {"name": "Tue"}, {"name": "Wed"}])
    wg = solve_week(w, time_limit_s=10)
    assert set(wg.held) == {"x", "y"}
    starts = [{(s.film, s.start) for s in g.sessions} for g in wg.grids]
    assert starts[0] == starts[1] == starts[2]


def test_a_title_pays_rather_than_breaks_a_hard_term(tiny: Brief) -> None:
    # Tuesday allows one show of x, so Monday's starts cannot hold whatever the penalty.
    # With a penalty no seat gain can pay for, y (untouched) must hold.
    w = _week(
        tiny,
        days=[{"name": "Mon"}, {"name": "Tue", "terms": {"x": {"min_shows": 1, "max_shows": 1}}}],
        hold_penalty=100_000,
    )
    wg = solve_week(w, time_limit_s=10)
    assert len(wg.grid("Mon").by_film()["x"]) >= 2
    assert len(wg.grid("Tue").by_film()["x"]) == 1
    assert "x" not in wg.held
    assert "y" in wg.held
    assert check_week(w, wg).ok


def test_hold_penalty_zero_means_days_are_independent(tiny: Brief) -> None:
    w = _week(tiny, days=[{"name": "Mon"}, {"name": "Tue"}], hold_penalty=0)
    wg = solve_week(w, time_limit_s=10)
    alone = solve(tiny, time_limit_s=10)
    assert wg.grid("Tue").objective == pytest.approx(alone.objective)


def test_an_infeasible_day_keeps_its_own_conflict_and_the_rest_still_solve(tiny: Brief) -> None:
    w = _week(tiny, days=[{"name": "Mon"}, {"name": "Tue", "terms": {"x": {"min_shows": 40}}}])
    wg = solve_week(w, time_limit_s=10)
    assert wg.grid("Mon").status in ("OPTIMAL", "FEASIBLE")
    assert wg.grid("Tue").status == "INFEASIBLE"
    assert {(r.film, r.term) for r in wg.grid("Tue").conflict} == {("x", "min_shows")}
    assert wg.status == "INFEASIBLE"
    assert wg.held == []  # one solved hold day is not a run

    relaxed = solve_week(w, time_limit_s=10, relax_terms=True)
    assert relaxed.grid("Tue").status in ("OPTIMAL", "FEASIBLE")
    assert [(r.film, r.term) for r in relaxed.grid("Tue").relaxed] == [("x", "min_shows")]
    assert relaxed.grid("Mon").relaxed == []  # relaxation stays on the day that needed it
    rep = check_week(w, relaxed)
    assert rep.ok and not rep.clean


def test_checker_rejects_a_week_that_claims_a_hold_it_did_not_keep(tiny: Brief) -> None:
    w = _week(tiny, days=[{"name": "Mon"}, {"name": "Tue"}])
    wg = solve_week(w, time_limit_s=10)
    forged = WeekGrid.model_validate({**wg.model_dump(), "held": ["x", "y"]})
    tue = forged.grids[1]
    tue.sessions = [s for s in tue.sessions if s.film != "y"] + [
        s.model_copy(
            update={
                "start": s.start + 5,
                "feature_start": s.feature_start + 5,
                "feature_end": s.feature_end + 5,
                "clear": s.clear + 5,
            }
        )
        for s in tue.sessions
        if s.film == "y"
    ]
    rep = check_week(w, forged)
    assert not rep.ok
    # The forged Tuesday moved y's starts without paying for it, so both week claims fail.
    assert [c.name for _, c in rep.failures if _ == "week"] == ["held", "hold_paid"]
    assert "the grid claims" in rep.week.checks[1].evidence


def test_checker_rejects_a_week_with_the_wrong_number_of_grids(tiny: Brief) -> None:
    w = _week(tiny, days=[{"name": "Mon"}, {"name": "Tue"}])
    wg = solve_week(w, time_limit_s=10)
    short = WeekGrid.model_validate({**wg.model_dump(), "grids": wg.model_dump()["grids"][:1]})
    rep = check_week(w, short)
    assert not rep.ok
    assert rep.week.checks[0].name == "days" and not rep.week.checks[0].ok


def test_a_day_may_open_a_screen_later_than_the_week_does(tiny: Brief) -> None:
    # Screen b opens at 15:00 on Tuesday only; every other day it keeps the house hours.
    w = _week(
        tiny,
        days=[{"name": "Mon"}, {"name": "Tue", "screens": {"b": {"open": "15:00"}}}],
    )
    assert w.day(0).open_for(w.day(0).screen("b")) == 12 * 60
    assert w.day(1).open_for(w.day(1).screen("b")) == 15 * 60
    assert w.day(1).screen("b").capacity == 60  # untouched fields come from the base
    with pytest.raises(ValidationError, match="unknown screens"):
        _week(tiny, days=[{"name": "Mon", "screens": {"z": {"open": "15:00"}}}])
    wg = solve_week(w, time_limit_s=10)
    assert all(g.status in ("OPTIMAL", "FEASIBLE") for g in wg.grids)
    assert all(s.start >= 15 * 60 for s in wg.grid("Tue").sessions if s.screen == "b")
    assert check_week(w, wg).ok
