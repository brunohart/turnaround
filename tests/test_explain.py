"""Why a session is where it is: the checker's why, the solver's probe, the what-if."""

from __future__ import annotations

from pathlib import Path

import pytest

from turnaround.check import admissions, check, whys
from turnaround.model import Brief, fmt_time
from turnaround.solve import probe, probe_all, show_of, solve, what_if

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_whys_sum_to_the_admissions_the_checker_counts(regent: Brief) -> None:
    grid = solve(regent, time_limit_s=20)
    ws = whys(regent, grid)
    assert len(ws) == len(grid.sessions)
    by_title = {a.film: a.admissions for a in admissions(regent, grid)}
    for f in regent.films:
        mine = sum(w.admissions for w in ws if w.session.film == f.id)
        assert mine == pytest.approx(by_title[f.id])
    # the PLF exclusive's prime session names both terms it helps satisfy
    prime = next(
        w for w in ws if w.session.film == "odyssey" and regent.policy.is_prime(w.session.start)
    )
    assert any(t.startswith("prime_shows 1/1") for t in prime.terms), prime.terms
    assert "exclusive_screen 1" in prime.terms
    assert any(t.startswith("min_shows ") for t in prime.terms)
    # the kids' title carries its window
    bees = next(w for w in ws if w.session.film == "bees")
    assert "latest_start ≤ 17:00" in bees.terms
    assert "expected" in bees.sentence


def test_a_show_is_a_title_in_a_room_in_a_daypart(regent: Brief) -> None:
    grid = solve(regent, time_limit_s=20)
    s = grid.sessions[0]
    show = show_of(regent, s)
    assert (s.screen, s.film, s.start) in show
    assert all(scr == s.screen and f == s.film for scr, f, _ in show)
    dp = regent.policy.daypart_at(s.start)
    assert all(regent.policy.daypart_at(st) == dp for _, _, st in show)


def _packed(tiny: Brief) -> Brief:
    """One screen, one title that must play twice, hours for exactly two blocks."""
    raw = tiny.model_dump(mode="json")
    raw["screens"] = raw["screens"][:1]
    raw["films"] = [raw["films"][0]]
    raw["films"][0]["terms"] = {"min_shows": 2}
    b = Brief.model_validate(raw)
    block = b.block_len(b.screens[0], b.films[0])
    raw["policy"]["last_start"] = fmt_time(b.policy.open_min + block)
    return Brief.model_validate(raw)


def test_a_session_the_terms_force_is_named_with_its_term(tiny: Brief) -> None:
    b = _packed(tiny)
    grid = solve(b, time_limit_s=10)
    assert grid.status == "OPTIMAL" and len(grid.sessions) == 2
    for s in grid.sessions:
        f = probe(b, grid, s, time_limit_s=10)
        assert f.by == "terms", f
        assert [t.term for t in f.terms] == ["min_shows"]
        assert str(f).startswith("forced by x min_shows 2")


def test_a_session_the_objective_forces_reports_the_delta(tiny: Brief) -> None:
    raw = tiny.model_dump(mode="json")
    raw["screens"] = raw["screens"][:1]
    for f in raw["films"]:
        f["terms"] = {}
    raw["policy"]["last_start"] = raw["policy"]["open"]  # one start on offer: 12:00
    b = Brief.model_validate(raw)
    grid = solve(b, time_limit_s=10)
    assert len(grid.sessions) == 1 and grid.sessions[0].film == "x"
    f = probe(b, grid, grid.sessions[0], time_limit_s=10)
    assert f.by == "objective", f
    assert f.delta > 0
    assert f.instead == "the slot goes to Y 12:00 · 1 show fewer"


def test_the_probe_forbids_the_show_not_the_minute(regent: Brief) -> None:
    grid = solve(regent, time_limit_s=20)
    # the PLF title's prime show: exclusive on the one PLF room, one prime show promised
    prime = next(
        s for s in grid.sessions if s.film == "odyssey" and regent.policy.is_prime(s.start)
    )
    f = probe(regent, grid, prime, time_limit_s=20)
    assert f.by == "terms", f
    assert {t.term for t in f.terms} <= {"prime_shows", "exclusive_screen", "min_shows"}
    assert "prime_shows" in {t.term for t in f.terms}
    # its matinee show: the terms allow three, the objective wants the fourth
    first = min((s for s in grid.sessions if s.film == "odyssey"), key=lambda s: s.start)
    f = probe(regent, grid, first, time_limit_s=20)
    assert f.by in ("objective", "unknown"), f
    assert f.delta > 0 and "fewer" in f.instead, f
    assert f.seconds > 0


def test_probe_all_writes_forced_onto_the_grid_and_it_round_trips(tiny: Brief) -> None:
    b = _packed(tiny)
    grid = probe_all(b, solve(b, time_limit_s=10), time_limit_s=10)
    assert all(s.forced and s.forced.by == "terms" for s in grid.sessions)
    again = type(grid).model_validate_json(grid.model_dump_json())
    assert again.sessions[0].forced == grid.sessions[0].forced
    assert check(b, again).ok  # the checker ignores the claim and still passes the grid


def test_what_if_drops_a_title_and_the_terms_still_hold(regent: Brief) -> None:
    changed, grid = what_if(regent, drop=["bees"], time_limit_s=20)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    assert not [s for s in grid.sessions if s.film == "bees"]
    assert [f.id for f in changed.films] == [f.id for f in regent.films if f.id != "bees"]
    assert check(changed, grid).ok
    with pytest.raises(ValueError, match="no such title: nope"):
        what_if(regent, drop=["nope"])


def test_what_if_can_change_the_policy(tiny: Brief) -> None:
    changed, grid = what_if(tiny, policy={"last_start": "22:00"}, time_limit_s=10)
    assert changed.policy.last_start == "22:00"
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    base = solve(tiny, time_limit_s=10)
    assert grid.objective >= base.objective - 0.01
