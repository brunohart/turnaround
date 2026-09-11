"""Day 5: distributor terms, fully. A PLF lock; week-scoped minimums carried day by
day as a debt; an exclusive that lifts on a named day; validation in the trade's
words; and the terms sheet a programmer sends back to the distributor. The checker
learns each rule first and catches a hand-built violation of every one."""

import pytest
from pydantic import ValidationError

from turnaround.check import check, check_week
from turnaround.model import (
    Brief,
    Grid,
    Session,
    TermRef,
    WeekBrief,
    WeekGrid,
    validation_sentences,
)
from turnaround.render import render_terms_html, render_week_terms_html
from turnaround.solve import explain, relax_key, solve, solve_week


def _sess(brief: Brief, screen: str, film: str, start: int) -> Session:
    scr = brief.screen(screen)
    f = brief.film(film)
    fs = start + brief.preshow_for(f)
    fe = fs + f.runtime_min
    return Session(
        screen=screen,
        film=film,
        start=start,
        feature_start=fs,
        feature_end=fe,
        clear=fe + brief.clean_for(scr),
    )


def _hand(brief: Brief, *sessions: Session) -> Grid:
    return Grid(
        house=brief.house, status="HAND", objective=0, solve_seconds=0, sessions=list(sessions)
    )


def _week(tiny: Brief, days: list[dict[str, object]], **films: dict[str, object]) -> WeekBrief:
    base = tiny.model_dump()
    base.pop("date")
    base.pop("weekday")
    for f in base["films"]:
        f["terms"] = {**f["terms"], **films.get(f["id"], {})}
    return WeekBrief.model_validate({**base, "days": days})


# --- plf_lock: every session on a PLF room is this title's -------------------------


def _plf_house(tiny: Brief) -> Brief:
    tiny.screens[0].formats = ["2D", "PLF"]
    tiny.films[0].terms.plf_lock = True
    return tiny


def test_checker_catches_another_title_on_a_locked_plf_room(tiny: Brief) -> None:
    b = _plf_house(tiny)
    bad = _hand(
        b,
        _sess(b, "a", "x", 12 * 60),
        _sess(b, "a", "y", 15 * 60),
        _sess(b, "a", "x", 17 * 60 + 30),
    )
    rep = check(b, bad)
    fail = [c for c in rep.failures if c.name == "plf_lock"]
    assert fail and fail[0].film == "x" and "1 session by other titles" in fail[0].evidence
    good = _hand(
        b,
        _sess(b, "a", "x", 12 * 60),
        _sess(b, "b", "y", 15 * 60),
        _sess(b, "a", "x", 17 * 60 + 30),
    )
    assert [c for c in check(b, good).failures if c.name == "plf_lock"] == []


def test_solver_keeps_the_plf_room_for_the_locked_title(tiny: Brief) -> None:
    b = _plf_house(tiny)
    grid = solve(b, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert all(s.film == "x" for s in grid.sessions if s.screen == "a")
    assert any(s.film == "y" for s in grid.sessions)  # y still gets its one show, on b
    assert check(b, grid).clean


def test_a_plf_lock_needs_a_plf_room(tiny: Brief) -> None:
    with pytest.raises(ValidationError, match="asks for every PLF room and the house has none"):
        Brief.model_validate(
            {
                **tiny.model_dump(),
                "films": [{**tiny.films[0].model_dump(), "terms": {"plf_lock": True}}],
            }
        )


# --- validation in the trade's words ---------------------------------------------------


def test_a_day_brief_refuses_a_week_term(tiny: Brief) -> None:
    raw = tiny.model_dump()
    raw["films"][0]["terms"]["min_shows_per_week"] = 12
    with pytest.raises(
        ValidationError, match="X: min_shows_per_week 12 is a week term and this brief is one day"
    ):
        Brief.model_validate(raw)


@pytest.mark.parametrize(
    ("terms", "words"),
    [
        (
            {"earliest_start": "16:00", "latest_start": "15:00"},
            "earliest_start 16:00 is after latest_start 15:00",
        ),
        ({"latest_start": "09:00"}, "latest_start 09:00 is before the house opens at 12:00"),
        ({"earliest_start": "21:00"}, "earliest_start 21:00 is after the last start 20:00"),
        ({"min_shows": 3, "max_shows": 2}, "min_shows 3 is more than max_shows 2"),
        ({"prime_shows": 2, "max_shows": 1}, "prime_shows 2 is more than max_shows 1"),
    ],
)
def test_an_impossible_term_is_refused_in_a_sentence(
    tiny: Brief, terms: dict[str, object], words: str
) -> None:
    raw = tiny.model_dump()
    raw["films"][1]["terms"] = terms
    with pytest.raises(ValidationError, match="Y: " + words):
        Brief.model_validate(raw)


def test_unknown_fields_are_named_by_title_and_what_the_booking_can_carry(tiny: Brief) -> None:
    raw = tiny.model_dump()
    raw["films"][0]["terms"]["min_show"] = 1
    raw["policy"]["stagger"] = 10
    with pytest.raises(ValidationError) as e:
        Brief.model_validate(raw)
    lines = validation_sentences(e.value, raw)
    assert any(
        line.startswith(
            "X → terms: `min_show` is not a term a booking can carry — the fields are min_shows"
        )
        for line in lines
    )
    assert any(
        line.startswith("policy: `stagger` is not a house policy — the fields are open")
        for line in lines
    )


def test_exclusive_until_must_name_a_day_of_the_week(tiny: Brief) -> None:
    with pytest.raises(
        ValidationError,
        match="X: exclusive_until Sat names a day the week does not have — the days are Thu, Fri",
    ):
        _week(tiny, [{"name": "Thu"}, {"name": "Fri"}], x={"exclusive_until": "Sat"})


# --- exclusive_until: the exclusive holds through a named day, then lifts --------------


def test_exclusive_until_unfolds_and_a_day_override_wins(tiny: Brief) -> None:
    w = _week(
        tiny,
        [
            {"name": "Thu"},
            {"name": "Fri"},
            {"name": "Sat"},
            {"name": "Mon", "terms": {"x": {"exclusive_screen": True}}},
        ],
        x={"exclusive_until": "Fri"},
    )
    assert [w.day(i).film("x").terms.exclusive_screen for i in range(4)] == [
        True,
        True,
        False,
        True,
    ]
    assert w.day(0).film("x").terms.exclusive_until == "Fri"  # carried for the record


def test_checker_catches_an_exclusive_broken_before_it_lifts(tiny: Brief) -> None:
    w = _week(
        tiny, [{"name": "Mon"}, {"name": "Tue"}, {"name": "Wed"}], x={"exclusive_until": "Tue"}
    )
    wg = solve_week(w, time_limit_s=10)
    assert check_week(w, wg).clean
    ok = check_week(w, wg).week.checks
    until = next(c for c in ok if c.name == "exclusive_until")
    assert until.film == "x" and until.ok and "own screen through Tue: Mon" in until.evidence
    # Tuesday: hand y onto the screen x owns. The day's exclusive_screen and the week's
    # exclusive_until both fail; Wednesday, after the lift, is untouched.
    tue = wg.grids[1]
    own = next(sid for sid, ss in tue.by_screen().items() if all(s.film == "x" for s in ss))
    forged = WeekGrid.model_validate(wg.model_dump())
    forged.grids[1].sessions.append(_sess(w.day(1), own, "y", 12 * 60 + 5))
    rep = check_week(w, forged)
    week_fails = {c.name for d, c in rep.failures if d == "week"}
    assert "exclusive_until" in week_fails
    assert week_fails <= {"exclusive_until", "held", "hold_paid"}  # y moved, unpaid
    assert "exclusive_screen" in {c.name for d, c in rep.failures if d == "Tue"}


# --- min_shows_per_week / prime_shows_per_week: a debt the week carries day by day ------


def _light_y(tiny: Brief) -> Brief:
    tiny.films[1].weight = 0.05  # the objective alone would barely show y
    tiny.films[1].terms.min_shows = 0
    return tiny


def test_solver_meets_a_week_minimum_the_days_alone_would_not(tiny: Brief) -> None:
    b = _light_y(tiny)
    alone = solve(b, time_limit_s=10)
    assert 2 * len(alone.by_film().get("y", [])) < 5
    w = _week(b, [{"name": "Mon"}, {"name": "Tue"}], y={"min_shows_per_week": 5})
    wg = solve_week(w, time_limit_s=10)
    assert wg.status == "OPTIMAL"
    assert sum(len(g.by_film().get("y", [])) for g in wg.grids) >= 5
    rep = check_week(w, wg)
    assert rep.clean
    c = next(c for c in rep.week.checks if c.name == "min_shows_per_week")
    assert c.film == "y" and c.ok and "≥ 5 · Mon " in c.evidence and "Tue " in c.evidence


def test_solver_meets_a_week_prime_minimum(tiny: Brief) -> None:
    b = _light_y(tiny)
    w = _week(b, [{"name": "Mon"}, {"name": "Tue"}], y={"prime_shows_per_week": 3})
    wg = solve_week(w, time_limit_s=10)
    assert wg.status == "OPTIMAL"
    primes = sum(
        1
        for i, g in enumerate(wg.grids)
        for s in g.sessions
        if s.film == "y" and w.day(i).policy.is_prime(s.start)
    )
    assert primes >= 3
    assert check_week(w, wg).clean


def test_checker_catches_a_week_minimum_the_grids_do_not_meet(tiny: Brief) -> None:
    b = _light_y(tiny)
    # Fri and Sat are not hold days, so the forgery below fails only the week terms.
    w = _week(
        b,
        [{"name": "Fri"}, {"name": "Sat"}],
        y={"min_shows_per_week": 5, "prime_shows_per_week": 2},
    )
    wg = solve_week(w, time_limit_s=10)
    assert check_week(w, wg).clean
    forged = WeekGrid.model_validate(wg.model_dump())
    for g in forged.grids:
        g.sessions = [s for s in g.sessions if s.film != "y"]
        g.admissions = None  # a hand-edited grid makes no claim the checker could hold
    rep = check_week(w, forged)
    assert {c.name for d, c in rep.failures if d == "week"} == {
        "min_shows_per_week",
        "prime_shows_per_week",
    }
    # Declared on any day's grid, the shortfall is a relaxation, not a failure; a
    # declaration of a term the booking does not carry is still bogus.
    forged.grids[1].relaxed = [
        TermRef(film="y", term="min_shows_per_week", value="5"),
        TermRef(film="y", term="prime_shows_per_week", value="2"),
    ]
    rep = check_week(w, forged)
    assert rep.ok and not rep.clean
    forged.grids[1].relaxed.append(TermRef(film="x", term="min_shows_per_week", value="9"))
    assert not check_week(w, forged).ok


def test_a_week_minimum_the_week_cannot_carry_names_itself(tiny: Brief) -> None:
    b = _light_y(tiny)
    w = _week(b, [{"name": "Mon"}, {"name": "Tue"}], y={"min_shows_per_week": 40})
    wg = solve_week(w, time_limit_s=10)
    assert wg.grid("Mon").status == "INFEASIBLE"
    ref = next(r for r in wg.grid("Mon").conflict if r.term == "min_shows_per_week")
    assert ref.film == "y" and ref.value.startswith("40 · ") and ref.value.endswith(" owed today")
    assert "Y min_shows_per_week 40 ·" in explain(w.day(0), wg.grid("Mon"))
    relaxed = solve_week(w, time_limit_s=10, relax_terms=True)
    assert relaxed.status == "OPTIMAL"
    assert ("y", "min_shows_per_week") in {
        (r.film, r.term) for g in relaxed.grids for r in g.relaxed
    }
    rep = check_week(w, relaxed)
    assert rep.ok and not rep.clean
    assert next(c for c in rep.week.checks if c.name == "min_shows_per_week").relaxed


def test_the_days_terms_are_given_up_before_the_weeks(tiny: Brief) -> None:
    order = [
        "prime_shows",
        "max_shows",
        "min_shows",
        "prime_shows_per_week",
        "min_shows_per_week",
        "exclusive_screen",
        "plf_lock",
    ]
    keys = [relax_key(tiny, TermRef(film="x", term=t)) for t in order]
    assert keys == sorted(keys)


# --- the terms sheet -------------------------------------------------------------------


def test_the_terms_sheet_states_every_term_its_scope_and_the_verdict(tiny: Brief) -> None:
    tiny.screens[0].formats = ["2D", "PLF"]
    w = _week(
        tiny,
        [{"name": "Mon"}, {"name": "Tue", "terms": {"y": {"min_shows": 2}}}, {"name": "Wed"}],
        x={
            "exclusive_until": "Tue",
            "min_shows_per_week": 6,
            "prime_shows_per_week": 2,
            "plf_lock": True,
        },
    )
    wg = solve_week(w, time_limit_s=10)
    rep = check_week(w, wg)
    html = render_week_terms_html(w, wg, rep)
    for word in (
        "min_shows_per_week",
        "prime_shows_per_week",
        "exclusive_until",
        "plf_lock",
        "through Tue",
        "the week",
        "each day",
        "✓ honoured",
        "every term honoured",
        "Tue 2",
        "Mon ",
        "As delivered",
    ):
        assert word in html, word
    assert "not met" not in html.replace("not_met", "")
    day = render_terms_html(w.day(0), wg.grids[0], check(w.day(0), wg.grids[0]))
    assert "min_shows" in day and "Y" in day and "X" in day
