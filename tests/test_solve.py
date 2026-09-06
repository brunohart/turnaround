from turnaround.check import check
from turnaround.model import Brief
from turnaround.solve import candidates, solve


def test_candidates_respect_windows(regent: Brief) -> None:
    cs = candidates(regent)
    bees = [c for c in cs if c.film == "bees"]
    assert bees and all(c.start <= 17 * 60 for c in bees)
    assert all(c.screen == "2" for c in bees)  # only screen 2 has 3D
    signal = [c for c in cs if c.film == "signal"]
    assert all(c.start >= 16 * 60 for c in signal)


def test_tiny_solves_and_checks(tiny: Brief) -> None:
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    rep = check(tiny, grid)
    assert rep.ok, [c for c in rep.failures]
    assert len(grid.by_film()["x"]) >= 2
    assert len(grid.by_film()["y"]) >= 1


def test_regent_solves_and_checks(regent: Brief) -> None:
    grid = solve(regent, time_limit_s=20)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    rep = check(regent, grid)
    assert rep.ok, [c for c in rep.failures]
    # The PLF exclusive lives on screen 1 and nothing else plays there.
    on_1 = grid.by_screen()["1"]
    assert on_1 and all(s.film == "odyssey" for s in on_1)


def test_infeasible_terms_are_reported_not_relaxed(tiny: Brief) -> None:
    tiny.films[0].terms.min_shows = 40
    grid = solve(tiny, time_limit_s=10)
    assert grid.status == "INFEASIBLE"
    assert grid.sessions == []


def test_solver_prefers_the_big_room_for_the_heavy_film(tiny: Brief) -> None:
    grid = solve(tiny, time_limit_s=10)
    x_screens = {s.screen for s in grid.by_film()["x"]}
    assert "a" in x_screens
