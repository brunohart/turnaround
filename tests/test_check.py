from turnaround.check import check
from turnaround.model import Brief, Grid, Session, TermRef


def _sess(brief: Brief, screen: str, film: str, start: int) -> Session:
    scr = brief.screen(screen)
    f = brief.film(film)
    fs = start + brief.policy.preshow_min
    fe = fs + f.runtime_min
    return Session(
        screen=screen,
        film=film,
        start=start,
        feature_start=fs,
        feature_end=fe,
        clear=fe + brief.clean_for(scr),
    )


def test_checker_catches_overlap(tiny: Brief) -> None:
    grid = Grid(
        house="Tiny",
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=[
            _sess(tiny, "a", "x", 12 * 60),
            _sess(tiny, "a", "x", 13 * 60),
            _sess(tiny, "b", "y", 12 * 60 + 15),
        ],
    )
    rep = check(tiny, grid)
    names = {c.name for c in rep.failures}
    assert "turnaround" in names


def test_checker_catches_stagger_and_terms(tiny: Brief) -> None:
    grid = Grid(
        house="Tiny",
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=[
            _sess(tiny, "a", "x", 12 * 60),
            _sess(tiny, "b", "y", 12 * 60 + 5),
        ],
    )
    rep = check(tiny, grid)
    names = {c.name for c in rep.failures}
    assert "stagger" in names
    assert "min_shows" in names  # x wanted 2


def test_checker_catches_bad_arithmetic(tiny: Brief) -> None:
    s = _sess(tiny, "a", "x", 12 * 60)
    s.clear -= 5
    rep = check(tiny, Grid(house="Tiny", status="HAND", objective=0, solve_seconds=0, sessions=[s]))
    assert any(c.name == "timing" and not c.ok for c in rep.checks)


def test_checker_accepts_a_declared_relaxation_but_calls_it_unclean(tiny: Brief) -> None:
    # x wanted 2 and got 1; the grid says so on its face.
    grid = Grid(
        house="Tiny",
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=[_sess(tiny, "a", "x", 12 * 60), _sess(tiny, "b", "y", 12 * 60 + 15)],
        relaxed=[TermRef(film="x", term="min_shows", value="2")],
    )
    rep = check(tiny, grid)
    assert rep.ok and not rep.clean
    assert [c.name for c in rep.relaxations] == ["min_shows"]
    assert rep.failures == []


def test_checker_rejects_an_undeclared_shortfall_even_when_something_else_is_relaxed(
    tiny: Brief,
) -> None:
    # y's min_shows is declared relaxed; x's shortfall is not, and still fails.
    grid = Grid(
        house="Tiny",
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=[_sess(tiny, "a", "x", 12 * 60)],
        relaxed=[TermRef(film="y", term="min_shows", value="1")],
    )
    rep = check(tiny, grid)
    assert not rep.ok
    assert {(c.film, c.name) for c in rep.failures} == {("x", "min_shows")}


def test_checker_catches_a_relaxation_that_names_no_real_term(tiny: Brief) -> None:
    grid = Grid(
        house="Tiny",
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=[
            _sess(tiny, "a", "x", 12 * 60),
            _sess(tiny, "a", "x", 15 * 60),
            _sess(tiny, "b", "y", 12 * 60 + 15),
        ],
        relaxed=[
            TermRef(film="x", term="prime_shows"),  # x carries no prime term
            TermRef(film="nobody", term="min_shows"),  # no such film
        ],
    )
    rep = check(tiny, grid)
    assert not rep.ok
    assert [c.name for c in rep.failures] == ["relaxed"]
    assert "2 name no such term" in rep.failures[0].evidence


def test_checker_passes_a_clean_hand_grid(tiny: Brief) -> None:
    grid = Grid(
        house="Tiny",
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=[
            _sess(tiny, "a", "x", 12 * 60),
            _sess(tiny, "a", "x", 15 * 60),
            _sess(tiny, "b", "y", 12 * 60 + 15),
        ],
    )
    rep = check(tiny, grid)
    assert rep.ok, rep.failures
