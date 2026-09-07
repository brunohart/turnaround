"""Day 1: when the terms cannot all hold, the solver names the smallest set that
conflicts, and relaxation drops terms out loud (ADR-002)."""

from turnaround.check import check
from turnaround.model import Brief, Grid
from turnaround.solve import explain, relax, relax_key, solve, terms_of


def _named(grid: Grid) -> set[tuple[str, str]]:
    return {(r.film, r.term) for r in grid.conflict}


def _is_minimal_conflict(brief: Brief, grid: Grid) -> bool:
    """The named terms conflict on their own, and no proper subset of them does.
    Checked with the solver itself: enforce exactly the named set, then each subset
    one short."""
    every = {(r.film, r.term) for f in brief.films for r in terms_of(f)}
    named = _named(grid)
    others = frozenset(every - named)
    if solve(brief, time_limit_s=10, dropped=others).status != "INFEASIBLE":
        return False
    return all(
        solve(brief, time_limit_s=10, dropped=others | {ref}).status in ("OPTIMAL", "FEASIBLE")
        for ref in named
    )


def test_too_many_shows_for_the_hours_blames_that_term_alone(tiny: Brief) -> None:
    # Two screens, 12:00 to a 20:00 last start, 140-minute blocks: eight shows fit.
    tiny.films[0].terms.min_shows = 12
    grid = solve(tiny, time_limit_s=10)
    assert grid.status == "INFEASIBLE"
    assert grid.sessions == []
    assert _named(grid) == {("x", "min_shows")}
    assert grid.conflict_alone
    assert _is_minimal_conflict(tiny, grid)
    text = explain(tiny, grid)
    assert "on its own" in text
    assert "X min_shows 12" in text
    assert "2 screens" in text


def test_two_exclusives_one_eligible_screen_names_a_pair(tiny: Brief) -> None:
    # Only screen a can play 3D; both titles demand a screen of their own. Three
    # different pairs explain this (the two exclusives; either exclusive with the other
    # title's min_shows). Any of them is a fair answer; the solver must name exactly
    # one such pair, minimal, and at least one exclusive is in it.
    tiny.screens[0].formats = ["2D", "3D"]
    for f in tiny.films:
        f.format = "3D"
        f.terms.exclusive_screen = True
        f.terms.min_shows = 1
    grid = solve(tiny, time_limit_s=10)
    assert grid.status == "INFEASIBLE"
    named = _named(grid)
    assert len(named) == 2
    assert any(term == "exclusive_screen" for _, term in named)
    assert not grid.conflict_alone  # each holds by itself
    assert _is_minimal_conflict(tiny, grid)
    assert "cannot hold together" in explain(tiny, grid)


def test_prime_guarantees_beyond_the_window_name_only_the_prime_terms(tiny: Brief) -> None:
    # The 17:30-20:45 window takes two starts per screen for these runtimes: four in all.
    tiny.policy.last_start = "22:00"
    tiny.films[0].terms.prime_shows = 3
    tiny.films[1].terms.prime_shows = 3
    grid = solve(tiny, time_limit_s=10)
    assert grid.status == "INFEASIBLE"
    assert _named(grid) == {("x", "prime_shows"), ("y", "prime_shows")}
    assert not grid.conflict_alone
    assert _is_minimal_conflict(tiny, grid)
    # The min_shows terms were never part of the problem and are not blamed.
    assert ("x", "min_shows") not in _named(grid)


def test_feasible_brief_carries_no_conflict_and_no_relaxation(tiny: Brief) -> None:
    grid = solve(tiny, time_limit_s=10)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert grid.conflict == [] and grid.relaxed == []


def test_relax_order_is_exclusive_last_then_lightest_film_then_prime_first(regent: Brief) -> None:
    refs = [r for f in regent.films for r in terms_of(f)]
    order = sorted(refs, key=lambda r: relax_key(regent, r))
    assert order[-1].term == "exclusive_screen"
    assert order[0].film == "bees"  # weight 0.8
    atlas = [r.term for r in order if r.film == "atlas"]
    assert atlas.index("prime_shows") < atlas.index("min_shows")


def test_relaxing_the_overbooked_regent_gives_a_checkable_grid_and_says_what_went(
    regent: Brief,
) -> None:
    for f in regent.films:
        f.terms.min_shows *= 2
    # A 10-minute slot grid keeps the test quick; the terms and the house are the Regent's.
    regent.policy.slot_min = 10
    strict = solve(regent, time_limit_s=10)
    assert strict.status == "INFEASIBLE"

    grid = relax(regent, time_limit_s=15)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert grid.relaxed, "relaxation must list what it gave up"
    # Every drop is a term the film really carries.
    for r in grid.relaxed:
        assert getattr(regent.film(r.film).terms, r.term)
    # The exclusive survives while anything else could go.
    assert ("odyssey", "exclusive_screen") not in {(r.film, r.term) for r in grid.relaxed}

    rep = check(regent, grid)
    assert rep.ok, rep.failures  # every failure is a declared relaxation
    assert not rep.clean
    assert {(c.film, c.name) for c in rep.relaxations} <= {(r.film, r.term) for r in grid.relaxed}
