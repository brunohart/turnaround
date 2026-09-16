"""Day 11: the diff. Two grids of one day, what changed, and the two promises: every
diff is symmetric (read the other way it is the other diff) and composable (applied
to the old grid it yields the new one)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from turnaround.diff import apply, diff, diff_week, invert, schedule
from turnaround.model import Brief, Grid, Session, TermRef, WeekGrid


def _session(screen: str, film: str, start: int, runtime: int = 100, pre: int = 20) -> Session:
    return Session(
        screen=screen,
        film=film,
        start=start,
        feature_start=start + pre,
        feature_end=start + pre + runtime,
        clear=start + pre + runtime + 20,
    )


def _grid(sessions: list[Session], **claims: object) -> Grid:
    base: dict[str, object] = {
        "house": "Tiny",
        "date": "2026-09-17",
        "status": "OPTIMAL",
        "objective": 100.0,
        "admissions": 100.0,
        "solve_seconds": 0.1,
        "sessions": sessions,
    }
    return Grid.model_validate({**base, **claims})


def test_diff_names_added_removed_and_moved(tiny: Brief) -> None:
    a = _grid(
        [
            _session("a", "x", 720),
            _session("a", "x", 900),
            _session("b", "y", 750, 90),
            _session("b", "y", 960, 90),
        ]
    )
    b = _grid(
        [
            _session("a", "x", 720),  # unchanged
            _session("a", "x", 930),  # moved in time
            _session("a", "y", 750, 90),  # moved room
            _session("b", "x", 1080),  # added
        ],
        objective=130.0,
        admissions=130.0,
    )
    d = diff(a, b, tiny)
    assert d.unchanged == 1
    assert [s.key for s in d.added] == ["b@18:00"]
    assert [s.key for s in d.removed] == ["b@16:00"]
    assert sorted((m.what, m.sentence) for m in d.moved) == [
        ("room", "b@12:30 → a@12:30"),
        ("time", "a@15:00 → a@15:30"),
    ]
    assert d.moved[0].title == "X" or d.moved[1].title == "X"
    assert d.sessions == (4, 4)
    assert d.seats is not None and d.seats.old == 320 and d.seats.new == 360
    assert [(t.film, t.old, t.new) for t in d.titles] == [("x", 2, 3), ("y", 2, 1)]
    assert d.terms.objective.delta == 30.0
    assert d.summary == "1 added · 1 removed · 2 moved · 1 unchanged"
    assert diff(a, a).empty and diff(a, a).summary == "no change"


def test_a_length_change_is_a_move_in_place() -> None:
    a = _grid([_session("a", "x", 720)])
    b = _grid([_session("a", "x", 720, runtime=110)])
    d = diff(a, b)
    assert len(d.moved) == 1 and d.moved[0].what == "length"
    assert "clear 14:20 → 14:30" in d.moved[0].sentence
    assert not d.added and not d.removed and d.unchanged == 0


def test_terms_delta_carries_the_claims() -> None:
    gave = TermRef(film="x", term="min_shows", value="2")
    a = _grid([_session("a", "x", 720)], relaxed=[gave], hold_paid=60.0, status="FEASIBLE")
    b = _grid([_session("a", "x", 720)], clash_paid=12.5)
    d = diff(a, b)
    assert d.terms.status == ("FEASIBLE", "OPTIMAL")
    assert d.terms.relaxed_removed == [gave] and d.terms.relaxed_added == []
    assert d.terms.hold_paid.delta == -60.0 and d.terms.clash_paid.delta == 12.5
    c = _grid([_session("a", "x", 720)], admissions=None, status="IMPORTED")
    assert diff(a, c).terms.admissions is None


def test_a_diff_is_symmetric_and_composable(tiny: Brief) -> None:
    a = _grid([_session("a", "x", 720), _session("b", "y", 750, 90), _session("a", "x", 900)])
    b = _grid(
        [_session("a", "x", 720), _session("a", "y", 780, 90), _session("b", "x", 1000)],
        objective=120.0,
        relaxed=[TermRef(film="y", term="prime_shows", value="1")],
    )
    c = _grid([_session("b", "y", 750, 90)], objective=40.0, status="FEASIBLE")
    d_ab = diff(a, b, tiny)
    assert invert(d_ab).model_dump() == diff(b, a, tiny).model_dump()
    assert invert(invert(d_ab)).model_dump() == d_ab.model_dump()
    got = apply(a, d_ab)
    assert schedule(got) == schedule(b)
    assert (got.status, got.objective, got.relaxed) == (b.status, b.objective, b.relaxed)
    # and back again, then on to a third grid
    assert schedule(apply(got, invert(d_ab))) == schedule(a)
    assert schedule(apply(apply(a, d_ab), diff(b, c))) == schedule(c)
    assert schedule(apply(a, diff(a, c))) == schedule(c)


def test_a_diff_of_another_day_does_not_fit() -> None:
    a = _grid([_session("a", "x", 720)])
    b = _grid([_session("a", "x", 800)])
    other = _grid([_session("b", "y", 720)])
    d = diff(a, b)
    try:
        apply(other, d)
    except ValueError as e:
        assert "no such session" in str(e)
    else:
        raise AssertionError("a diff of one day applied to another should refuse")


_sessions = st.lists(
    st.builds(
        _session,
        screen=st.sampled_from(["a", "b", "c"]),
        film=st.sampled_from(["x", "y"]),
        start=st.integers(min_value=600, max_value=1400).map(lambda m: m - m % 5),
        runtime=st.sampled_from([90, 100]),
    ),
    max_size=6,
    unique_by=lambda s: (s.screen, s.start),
)


@given(_sessions, _sessions, _sessions)
@settings(max_examples=150, deadline=None)
def test_every_diff_is_symmetric_and_composable(
    xs: list[Session], ys: list[Session], zs: list[Session]
) -> None:
    a, b, c = _grid(xs), _grid(ys, objective=7.0), _grid(zs, status="FEASIBLE")
    d_ab, d_bc = diff(a, b), diff(b, c)
    assert invert(d_ab).model_dump() == diff(b, a).model_dump()
    assert schedule(apply(a, d_ab)) == schedule(b)
    assert schedule(apply(b, invert(d_ab))) == schedule(a)
    assert schedule(apply(apply(a, d_ab), d_bc)) == schedule(c)
    assert d_ab.unchanged + len(d_ab.removed) + len(d_ab.moved) == len(a.sessions)
    assert d_ab.unchanged + len(d_ab.added) + len(d_ab.moved) == len(b.sessions)
    # a move is always the same title, and never the same session
    for m in d_ab.moved:
        assert m.old.film == m.new.film
        assert (m.old.screen, m.old.start, m.old.clear) != (m.new.screen, m.new.start, m.new.clear)


def test_a_week_is_diffed_by_day_name_and_a_dropped_day_reads_as_removed() -> None:
    thu = _grid([_session("a", "x", 720)])
    fri = _grid([_session("a", "x", 1200)])
    old = WeekGrid(house="Tiny", days=["Thu", "Fri", "Sat"], grids=[thu, fri, thu], held=["x"])
    new = WeekGrid(house="Tiny", days=["Fri", "Sat", "Sun"], grids=[fri, fri, thu])
    wd = diff_week(old, new)
    assert [d.day for d in wd.days] == ["Fri", "Sat", "Sun", "Thu"]
    assert wd.days_added == ["Sun"] and wd.days_removed == ["Thu"]
    assert wd.day("Fri") is not None and wd.day("Fri").empty
    sat = wd.day("Sat")
    assert sat is not None and [m.sentence for m in sat.moved] == ["a@12:00 → a@20:00"]
    sun = wd.day("Sun")
    assert sun is not None and len(sun.added) == 1 and sun.terms.status[0] == "ABSENT"
    gone = wd.day("Thu")
    assert gone is not None and len(gone.removed) == 1 and gone.terms.status[1] == "ABSENT"
    assert wd.held == (["x"], [])
    assert "days added Sun" in wd.summary and "days dropped Thu" in wd.summary
