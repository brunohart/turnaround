"""Day 4: the booth's realities. Credits overlap, preshow by format, floor staff,
per-screen hours, and the stagger as a window. For each: the checker catches a
hand-built violation first, then the solver is shown to honour the rule."""

from __future__ import annotations

import pytest

from turnaround.check import check
from turnaround.model import Brief, Grid, Screen, Session
from turnaround.solve import candidates, solve


def _sess(brief: Brief, screen: str, film: str, start: int) -> Session:
    """A session written the way the brief says one runs."""
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
        clear=brief.turnaround_of(scr, f, start)[1],
    )


def _grid(brief: Brief, *sessions: Session) -> Grid:
    return Grid(
        house=brief.house, status="HAND", objective=0, solve_seconds=0, sessions=list(sessions)
    )


def _names(brief: Brief, grid: Grid) -> set[str]:
    return {c.name for c in check(brief, grid).failures}


# --- credits overlap -----------------------------------------------------------


def test_credits_shorten_the_block_and_the_turnaround_starts_over_them(tiny: Brief) -> None:
    x = tiny.film("x")
    a = tiny.screen("a")
    plain = tiny.block_len(a, x)
    x.credits_min = 8
    assert tiny.block_len(a, x) == plain - 8
    begin, clear = tiny.turnaround_of(a, x, 12 * 60)
    fe = 12 * 60 + tiny.policy.preshow_min + x.runtime_min
    assert begin == fe - 8
    assert clear == fe - 8 + tiny.clean_for(a)


def test_credits_longer_than_the_clean_still_clear_at_feature_end(tiny: Brief) -> None:
    x = tiny.film("x")
    a = tiny.screen("a")
    x.credits_min = 30  # clean is 20
    fe = 12 * 60 + tiny.policy.preshow_min + x.runtime_min
    assert tiny.turnaround_of(a, x, 12 * 60)[1] == fe


def test_checker_rejects_a_clear_that_ignores_the_credits(tiny: Brief) -> None:
    tiny.film("x").credits_min = 8
    s = _sess(tiny, "a", "x", 12 * 60)
    assert s.clear == 14 * 60 + 12  # 14:00 less 8 of credits, plus 20 to clean
    honest = _grid(
        tiny, s, _sess(tiny, "a", "x", 14 * 60 + 15), _sess(tiny, "b", "y", 12 * 60 + 15)
    )
    assert check(tiny, honest).clean
    s.clear += 8  # the old arithmetic: clean after the last frame
    assert "timing" in _names(tiny, _grid(tiny, s))


def test_credits_cannot_outlast_the_feature() -> None:
    with pytest.raises(ValueError, match="credits_min"):
        Brief.model_validate(
            {
                "house": "H",
                "screens": [{"id": "a", "capacity": 10}],
                "films": [{"id": "x", "title": "X", "runtime_min": 60, "credits_min": 61}],
            }
        )


def test_solver_packs_tighter_when_the_credits_overlap(tiny: Brief) -> None:
    # 12:00 to 20:00 on two screens, starts 10 apart; x runs 20 + 100 + 20 = 140 a block,
    # four to a screen. With 20 minutes of credits the block is 120 and a fifth fits on
    # the screen that opens on the hour.
    tiny.films[1].terms.min_shows = 0
    tiny.films[0].terms.min_shows = 9
    assert solve(tiny, time_limit_s=10).status == "INFEASIBLE"
    tiny.films[0].credits_min = 20
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert check(tiny, grid).clean
    assert all(s.clear == s.feature_end for s in grid.sessions if s.film == "x")


# --- preshow by format ---------------------------------------------------------


def test_preshow_by_format_changes_the_feature_start(tiny: Brief) -> None:
    tiny.policy.preshow_by_format = {"3D": 30}
    tiny.films[1].format = "3D"
    tiny.screens[0].formats = ["2D", "3D"]
    assert tiny.preshow_for(tiny.film("x")) == tiny.policy.preshow_min
    assert tiny.preshow_for(tiny.film("y")) == 30
    s = _sess(tiny, "a", "y", 12 * 60)
    assert s.feature_start == 12 * 60 + 30
    grid = _grid(tiny, s, _sess(tiny, "a", "x", s.clear), _sess(tiny, "b", "x", 12 * 60 + 15))
    assert check(tiny, grid).clean
    s.feature_start -= 10  # the house preshow, wrongly applied to a 3D title
    assert "timing" in _names(tiny, grid)


def test_solver_uses_the_formats_preshow(tiny: Brief) -> None:
    tiny.policy.preshow_by_format = {"3D": 30}
    tiny.films[1].format = "3D"
    tiny.screens[0].formats = ["2D", "3D"]
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert check(tiny, grid).clean
    ys = [s for s in grid.sessions if s.film == "y"]
    assert ys and all(s.feature_start == s.start + 30 for s in ys)
    xs = [s for s in grid.sessions if s.film == "x"]
    assert xs and all(s.feature_start == s.start + 20 for s in xs)


# --- floor staff ---------------------------------------------------------------


def test_checker_counts_rooms_clearing_at_once(tiny: Brief) -> None:
    tiny.screens.append(Screen(id="c", capacity=50))
    tiny.policy.max_concurrent_turnarounds = 2
    tiny.films[0].terms.min_shows = 0
    tiny.films[1].terms.min_shows = 0
    # x on a and b ten minutes apart, y on c ten minutes after that: y is ten minutes
    # shorter, so all three turnarounds are open at 14:10.
    three = _grid(
        tiny,
        _sess(tiny, "a", "x", 12 * 60),
        _sess(tiny, "b", "x", 12 * 60 + 10),
        _sess(tiny, "c", "y", 12 * 60 + 20),
    )
    rep = check(tiny, three)
    staff = next(c for c in rep.checks if c.name == "staff")
    assert not staff.ok
    assert "busiest 3" in staff.evidence
    # Pull the third far enough that only two ever overlap.
    two = _grid(
        tiny,
        _sess(tiny, "a", "x", 12 * 60),
        _sess(tiny, "b", "x", 12 * 60 + 10),
        _sess(tiny, "c", "y", 14 * 60),
    )
    assert check(tiny, two).clean


def test_checker_says_nothing_about_staff_when_the_house_does_not(tiny: Brief) -> None:
    grid = _grid(tiny, _sess(tiny, "a", "x", 12 * 60))
    assert "staff" not in {c.name for c in check(tiny, grid).checks}


def test_solver_never_clears_more_rooms_than_the_floor_can(tiny: Brief) -> None:
    tiny.policy.max_concurrent_turnarounds = 1
    tiny.policy.stagger_min = 0  # let starts land anywhere; only the staff cap separates them
    tiny.films[0].terms.min_shows = 3
    tiny.films[1].terms.min_shows = 2
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert check(tiny, grid).clean
    turns = [
        tiny.turnaround_of(tiny.screen(s.screen), tiny.film(s.film), s.start) for s in grid.sessions
    ]
    for a, b in turns:
        assert sum(1 for c, d in turns if c < b and a < d) == 1  # only itself


# --- per-screen hours ----------------------------------------------------------


def test_a_screen_may_open_later_than_the_house(tiny: Brief) -> None:
    tiny.screens[1].open = "14:00"
    tiny.screens[1].last_start = "18:00"
    assert tiny.open_for(tiny.screens[0]) == 12 * 60
    assert tiny.open_for(tiny.screens[1]) == 14 * 60
    early = _grid(tiny, _sess(tiny, "b", "y", 13 * 60))
    assert "hours" in _names(tiny, early)
    late = _grid(tiny, _sess(tiny, "b", "y", 18 * 60 + 30))
    assert "hours" in _names(tiny, late)
    inside = _grid(
        tiny,
        _sess(tiny, "b", "y", 14 * 60),
        _sess(tiny, "a", "x", 12 * 60),
        _sess(tiny, "a", "x", 12 * 60 + 140),
    )
    assert check(tiny, inside).clean


def test_a_screen_cannot_close_before_it_opens() -> None:
    with pytest.raises(ValueError, match="before"):
        Screen(id="a", capacity=10, open="14:00", last_start="13:00")
    with pytest.raises(ValueError, match="before it opens"):
        Brief.model_validate(
            {
                "house": "H",
                "screens": [{"id": "a", "capacity": 10, "open": "22:00"}],
                "films": [{"id": "x", "title": "X", "runtime_min": 60}],
                "policy": {"last_start": "21:00"},
            }
        )


def test_solver_keeps_a_late_opening_screen_dark_until_it_opens(tiny: Brief) -> None:
    tiny.screens[1].open = "15:00"
    assert all(c.start >= 15 * 60 for c in candidates(tiny) if c.screen == "b")
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert check(tiny, grid).clean
    assert all(s.start >= 15 * 60 for s in grid.sessions if s.screen == "b")


# --- the stagger as a window ---------------------------------------------------


def test_stagger_window_allows_the_stated_number_of_starts(tiny: Brief) -> None:
    tiny.screens.append(Screen(id="c", capacity=50))
    tiny.policy.stagger_min = 15
    tiny.policy.max_starts_per_window = 2
    tiny.films[0].terms.min_shows = 0
    tiny.films[1].terms.min_shows = 0
    two = _grid(tiny, _sess(tiny, "a", "x", 12 * 60), _sess(tiny, "b", "x", 12 * 60 + 5))
    assert check(tiny, two).clean
    three = _grid(
        tiny,
        _sess(tiny, "a", "x", 12 * 60),
        _sess(tiny, "b", "x", 12 * 60 + 5),
        _sess(tiny, "c", "y", 12 * 60 + 10),
    )
    stagger = next(c for c in check(tiny, three).checks if c.name == "stagger")
    assert not stagger.ok
    assert "3 starts" in stagger.evidence
    # Fifteen minutes on from the first is a new window.
    spread = _grid(
        tiny,
        _sess(tiny, "a", "x", 12 * 60),
        _sess(tiny, "b", "x", 12 * 60 + 5),
        _sess(tiny, "c", "y", 12 * 60 + 15),
    )
    assert check(tiny, spread).clean


def test_the_default_stagger_is_one_start_in_ten(tiny: Brief) -> None:
    assert tiny.policy.max_starts_per_window == 1
    close = _grid(tiny, _sess(tiny, "a", "x", 12 * 60), _sess(tiny, "b", "y", 12 * 60 + 5))
    assert "stagger" in _names(tiny, close)


def test_solver_honours_the_stagger_window(tiny: Brief) -> None:
    tiny.screens.append(Screen(id="c", capacity=50))
    tiny.policy.stagger_min = 15
    tiny.policy.max_starts_per_window = 2
    tiny.policy.slot_min = 5
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert check(tiny, grid).clean
    starts = sorted(s.start for s in grid.sessions)
    assert all(sum(1 for u in starts if t <= u < t + 15) <= 2 for t in starts)
