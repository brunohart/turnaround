"""Day 3: demand. The objective is seats sold, not seats offered: a title's k-th
session in a daypart draws less than the one before, no room sells more than it
holds, and the checker re-counts the solver's claim from the brief alone."""

import pytest
from pydantic import ValidationError

from turnaround.check import admissions, check, check_week
from turnaround.model import Brief, Demand, Grid, Session, WeekBrief, WeekGrid
from turnaround.render import render_html
from turnaround.solve import solve, solve_week


def _sess(brief: Brief, screen: str, film: str, start: int) -> Session:
    f = brief.film(film)
    fs = start + brief.policy.preshow_min
    fe = fs + f.runtime_min
    return Session(
        screen=screen, film=film, start=start, feature_start=fs, feature_end=fe, clear=fe + 20
    )


def _hand(brief: Brief, *sessions: Session, **claims: object) -> Grid:
    return Grid.model_validate(
        {
            "house": brief.house,
            "status": "HAND",
            "objective": 0,
            "solve_seconds": 0,
            "sessions": [s.model_dump() for s in sessions],
            **claims,
        }
    )


def _two_x_one_y(brief: Brief) -> list[Session]:
    """A clean hand grid for the tiny house: x twice in the big room, y once in the small."""
    return [
        _sess(brief, "a", "x", 12 * 60),
        _sess(brief, "a", "x", 15 * 60),
        _sess(brief, "b", "y", 12 * 60 + 15),
    ]


def test_expected_decays_within_a_daypart_and_scales_by_day_and_holiday(tiny: Brief) -> None:
    b = tiny.model_copy(deep=True)
    y = b.film("y")
    y.demand = Demand(
        per_session={"prime": 200, "matinee": 50},
        decay=0.5,
        weekday={"Sat": 1.5},
        holiday=2.0,
    )
    prime = b.policy.daypart_at(18 * 60)
    matinee = b.policy.daypart_at(12 * 60)
    assert b.expected(y, prime, 0) == 200
    assert b.expected(y, prime, 1) == 100  # the second prime show draws half
    assert b.expected(y, prime, 2) == 50
    assert b.expected(y, matinee, 0) == 50
    assert b.expected(y, b.policy.daypart_at(16 * 60), 0) == 0  # no forecast for the afternoon
    b.weekday = "Sat"
    assert b.expected(y, prime, 0) == 300
    b.policy.school_holiday = True
    assert b.expected(y, prime, 0) == 600
    # A title without a block falls back to weight x daypart weight x assumed admissions.
    x = b.film("x")
    assert b.expected(x, prime, 0) == pytest.approx(1.0 * 1.0 * 100)
    assert b.expected(x, matinee, 0) == pytest.approx(0.55 * 100)
    assert b.expected(x, prime, 1) == pytest.approx(60)


def test_the_weekday_comes_from_the_date_when_not_stated(tiny: Brief) -> None:
    b = tiny.model_copy(update={"date": "2026-09-12"})  # a Saturday
    assert b.day_name == "Sat"
    assert tiny.day_name is None
    assert b.model_copy(update={"weekday": "Mon"}).day_name == "Mon"


def test_two_shows_in_one_daypart_earn_less_than_one_in_each(tiny: Brief) -> None:
    # Same title, same room, two matinees vs a matinee and an afternoon show.
    same = _hand(tiny, _sess(tiny, "a", "x", 12 * 60), _sess(tiny, "a", "x", 13 * 60))
    spread = _hand(tiny, _sess(tiny, "a", "x", 12 * 60), _sess(tiny, "a", "x", 15 * 60))
    a_same = next(r for r in admissions(tiny, same) if r.film == "x")
    a_spread = next(r for r in admissions(tiny, spread) if r.film == "x")
    assert a_same.shows == a_spread.shows == 2
    assert a_same.demand < a_spread.demand
    # 55 + 55 x 0.6 for the two matinees; 55 + 75 for one of each.
    assert a_same.demand == pytest.approx(55 + 33)
    assert a_spread.demand == pytest.approx(55 + 75)


def test_raising_a_titles_demand_moves_it_to_the_bigger_room(tiny: Brief) -> None:
    b = tiny.model_copy(deep=True)
    # As briefed, x (weight 1.0) is the heavy title and takes the 100-seat room.
    before = solve(b, time_limit_s=10)
    assert "a" in {s.screen for s in before.by_film()["x"]}
    # Now y is the one people come for: every daypart wants more than any room holds.
    b.film("y").demand = Demand(per_session={d.name: 400 for d in b.policy.dayparts})
    b.film("x").demand = Demand(per_session={d.name: 20 for d in b.policy.dayparts})
    after = solve(b, time_limit_s=10)
    assert after.status in ("OPTIMAL", "FEASIBLE")
    # The 100-seat room is y's all day; x's two guaranteed shows go to the 60-seat room,
    # where a seat given up to x costs 40 admissions instead of 80.
    assert all(s.film == "y" for s in after.by_screen()["a"])
    assert {s.screen for s in after.by_film()["x"]} == {"b"}
    assert check(b, after).clean, check(b, after).failures


def test_capping_capacity_leaves_turned_away_non_zero_and_reported(tiny: Brief) -> None:
    b = tiny.model_copy(deep=True)
    b.film("y").demand = Demand(per_session={d.name: 400 for d in b.policy.dayparts})
    grid = solve(b, time_limit_s=10)
    rows = {r.film: r for r in admissions(b, grid)}
    y = rows["y"]
    assert y.shows >= 1
    assert y.admissions <= y.offered  # nobody sells a seat the room does not have
    assert y.turned_away > 0
    assert y.demand == pytest.approx(y.admissions + y.turned_away)
    # The solver's claim is exactly the checker's re-count, and the objective is the claim.
    assert grid.admissions == pytest.approx(sum(r.admissions for r in rows.values()), abs=0.05)
    assert grid.objective == pytest.approx(grid.admissions or 0)
    rep = check(b, grid)
    assert rep.clean, rep.failures
    ev = next(c for c in rep.checks if c.name == "admissions").evidence
    assert "turned away at capacity" in ev
    html = render_html(b, grid, rep)
    assert "Turned away" in html and "expected admissions" in html


def test_checker_rejects_a_grid_that_claims_admissions_it_did_not_earn(tiny: Brief) -> None:
    honest = _hand(tiny, *_two_x_one_y(tiny))
    rep = check(tiny, honest)
    assert next(c for c in rep.checks if c.name == "admissions").ok
    assert "unclaimed" in next(c for c in rep.checks if c.name == "admissions").evidence
    assert not any(c.name == "objective" for c in rep.checks)  # nothing to hold it to

    counted = sum(r.admissions for r in admissions(tiny, honest))
    forged = _hand(tiny, *_two_x_one_y(tiny), admissions=counted + 50, objective=counted + 50)
    rep = check(tiny, forged)
    assert [c.name for c in rep.failures] == ["admissions"]

    # The right admissions but an objective that is not admissions less the penalty paid.
    off = _hand(tiny, *_two_x_one_y(tiny), admissions=counted, objective=counted - 1)
    assert [c.name for c in check(tiny, off).failures] == ["objective"]


def test_the_hold_penalty_is_paid_in_admissions_and_the_week_checker_re_derives_it(
    tiny: Brief,
) -> None:
    base = tiny.model_dump()
    base.pop("date")
    base.pop("weekday")
    w = WeekBrief.model_validate(
        {
            **base,
            "days": [
                {"name": "Mon"},
                {"name": "Tue", "terms": {"x": {"min_shows": 1, "max_shows": 1}}},
            ],
            "hold_penalty": 100_000,
        }
    )
    wg = solve_week(w, time_limit_s=10)
    mon, tue = wg.grids
    assert mon.hold_paid == 0  # the anchor pays nothing
    assert tue.hold_paid == pytest.approx(100_000)  # x had to move; y held
    assert tue.objective == pytest.approx((tue.admissions or 0) - tue.hold_paid)
    rep = check_week(w, wg)
    assert rep.ok and rep.clean, rep.failures
    paid = next(c for c in rep.week.checks if c.name == "hold_paid")
    assert "100,000 admissions paid" in paid.evidence

    # Claim the penalty was never paid: the week checker knows what Tuesday owed.
    forged = WeekGrid.model_validate(wg.model_dump())
    forged.grids[1].hold_paid = 0
    forged.grids[1].objective = forged.grids[1].admissions or 0
    rep = check_week(w, forged)
    assert not rep.ok
    assert ("week", "hold_paid") in {(d, c.name) for d, c in rep.failures}


def test_brief_rejects_a_forecast_for_a_daypart_the_house_does_not_have() -> None:
    with pytest.raises(ValidationError, match="does not define"):
        Brief.model_validate(
            {
                "house": "h",
                "screens": [{"id": "1", "capacity": 10}],
                "films": [
                    {
                        "id": "f",
                        "title": "F",
                        "runtime_min": 90,
                        "demand": {"per_session": {"evening": 40}},
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="negative"):
        Brief.model_validate(
            {
                "house": "h",
                "screens": [{"id": "1", "capacity": 10}],
                "films": [
                    {
                        "id": "f",
                        "title": "F",
                        "runtime_min": 90,
                        "demand": {"per_session": {"prime": -1}},
                    }
                ],
            }
        )
