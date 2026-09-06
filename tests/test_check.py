from turnaround.check import check
from turnaround.model import Brief, Grid, Session


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
