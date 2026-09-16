"""Day 10: the festival profile. A festival brief unfolds like a week into plain day
briefs, venues as screens; the festival's own terms — screenings, a guest's window,
the days a print is in town — are counted across the days by the checker from the
sessions alone; the print move and the strand clash are day checks. The checker learns
each rule first and catches a hand-built violation of every one; then the solver."""

import pytest
from pydantic import ValidationError

from turnaround.check import check, check_festival, clash_minutes, clashes
from turnaround.model import Brief, FestivalBrief, Grid, Session, TermRef, WeekGrid


def _fest(**extra: object) -> FestivalBrief:
    """Two venues, four titles in two strands, three days. Gala screens twice and its
    director is there Sat evening; the documentary's print arrives Sunday."""
    base: dict[str, object] = {
        "festival": "Brightwater Film Festival",
        "venues": [
            {"id": "hall", "name": "Grand Hall", "capacity": 400},
            {"id": "box", "name": "The Box", "capacity": 80},
        ],
        "films": [
            {
                "id": "gala",
                "title": "Gala",
                "runtime_min": 110,
                "strand": "Competition",
                "weight": 2.0,
                "terms": {
                    "screenings": 2,
                    "max_shows": 1,
                    "guest": {"name": "the director", "days": ["Sat"], "earliest": "18:00"},
                },
            },
            {
                "id": "rival",
                "title": "Rival",
                "runtime_min": 95,
                "strand": "Competition",
                "weight": 1.2,
                "terms": {"screenings": 2, "max_shows": 1},
            },
            {
                "id": "doc",
                "title": "Doc",
                "runtime_min": 80,
                "strand": "Documentary",
                "weight": 0.8,
                "terms": {"screenings": 1, "available": ["Sun"]},
            },
            {"id": "short", "title": "Short", "runtime_min": 60, "terms": {"screenings": 1}},
        ],
        "policy": {
            "open": "12:00",
            "last_start": "21:00",
            "preshow_min": 10,
            "clean_min": 20,
            "stagger_min": 0,
            "slot_min": 15,
            "move_min": 45,
            "clash_penalty": 40,
        },
        "days": [{"name": "Fri"}, {"name": "Sat"}, {"name": "Sun"}],
    }
    return FestivalBrief.model_validate({**base, **extra})


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


def _hand(brief: Brief, *sessions: Session, clash_paid: float = 0.0) -> Grid:
    return Grid(
        house=brief.house,
        status="HAND",
        objective=0,
        solve_seconds=0,
        sessions=list(sessions),
        clash_paid=clash_paid,
    )


def _hand_fest(fest: FestivalBrief, *days: list[Session]) -> WeekGrid:
    briefs = fest.briefs()
    return WeekGrid(
        house=fest.festival,
        days=[d.name for d in fest.days],
        grids=[_hand(briefs[i], *ss) for i, ss in enumerate(days)],
    )


# --- the unfold --------------------------------------------------------------------


def test_a_festival_unfolds_into_plain_day_briefs() -> None:
    fest = _fest()
    fri, sat, sun = fest.briefs()
    assert [s.id for s in fri.screens] == ["hall", "box"]
    assert fri.house == "Brightwater Film Festival"
    assert fri.film("gala").terms.guest is None  # the director is not there Friday
    assert sat.film("gala").terms.guest is not None
    assert sat.film("gala").terms.guest.window == "Sat 18:00–30:00"
    assert fri.film("doc").terms.max_shows == 0  # the print arrives Sunday
    assert sun.film("doc").terms.max_shows is None
    assert fri.film("rival").terms.screenings == 2  # carried for the record
    assert fest.strands == ["Competition", "Documentary"]
    assert fest.hold_days == [] and fest.hold_penalty == 0.0


def test_a_day_brief_refuses_a_festival_term_in_a_sentence(tiny: Brief) -> None:
    raw = tiny.model_dump()
    raw["films"][0]["terms"]["screenings"] = 2
    with pytest.raises(ValidationError, match="festival term"):
        Brief.model_validate(raw)


def test_a_festival_refuses_a_guest_or_a_print_on_a_day_it_does_not_have() -> None:
    with pytest.raises(ValidationError, match="not festival days"):
        _fest(days=[{"name": "Fri"}, {"name": "Sun"}])  # the guest's Sat is gone
    fest = _fest().model_dump()
    fest["films"][2]["terms"]["available"] = ["Mon"]
    with pytest.raises(ValidationError, match="not festival days"):
        FestivalBrief.model_validate(fest)
    fest["films"][2]["terms"]["available"] = ["Fri"]
    fest["films"][2]["terms"]["guest"] = {"days": ["Sun"]}
    with pytest.raises(ValidationError, match="only available"):
        FestivalBrief.model_validate(fest)
    fest = _fest().model_dump()
    fest["films"][0]["terms"]["screenings"] = 4  # 3 days at one a day
    with pytest.raises(ValidationError, match="cannot fit"):
        FestivalBrief.model_validate(fest)


# --- day checks: the print move and the strand clash ---------------------------------


def test_checker_catches_a_print_that_cannot_make_the_move() -> None:
    fri = _fest().day(0)
    # Gala in the hall 12:00 → feature ends 14:00; the box would need it by 14:45.
    bad = _hand(fri, _sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "gala", 14 * 60 + 30))
    fail = [c for c in check(fri, bad).failures if c.name == "print-move"]
    assert fail and "too tight" in fail[0].evidence and "Grand Hall ends 14:00" in fail[0].evidence
    same_minute = _hand(
        fri, _sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "gala", 12 * 60)
    )
    fail = [c for c in check(fri, same_minute).failures if c.name == "print-move"]
    assert fail and "1 too tight" in fail[0].evidence  # one print, two rooms, one slip
    good = _hand(fri, _sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "gala", 14 * 60 + 45))
    assert [c for c in check(fri, good).failures if c.name == "print-move"] == []


def test_clash_minutes_are_counted_on_the_start_grid() -> None:
    fri = _fest().day(0)
    # Gala 12:00 runs to 14:00 (doors to feature end); Rival 13:00 runs to 14:45. They
    # overlap 13:00–14:00: four 15-minute steps of one extra title.
    grid = _hand(fri, _sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "rival", 13 * 60))
    found = clashes(fri, grid)
    assert len(found) == 1
    assert found[0].strand == "Competition" and found[0].titles == ("gala", "rival")
    assert found[0].at == 13 * 60 and found[0].minutes == 60
    assert clash_minutes(fri, grid) == 60
    # Short has no strand and Doc is another strand: no clash with either.
    apart = _hand(fri, _sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "short", 13 * 60))
    assert clashes(fri, apart) == []


def test_checker_holds_the_grid_to_the_clash_it_says_it_paid() -> None:
    fri = _fest().day(0)
    sessions = (_sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "rival", 13 * 60))
    # 60 minutes at 40 an hour: 40 expected admissions owed.
    unpaid = _hand(fri, *sessions)
    fail = [c for c in check(fri, unpaid).failures if c.name == "strand-clash"]
    assert fail and "paid 0.0, owed 40.0" in fail[0].evidence
    paid = _hand(fri, *sessions, clash_paid=40.0)
    ok = [c for c in check(fri, paid).checks if c.name == "strand-clash"]
    assert ok and ok[0].ok and "1 clash, 60′ at once" in ok[0].evidence
    overpaid = _hand(fri, *sessions, clash_paid=80.0)
    assert [c for c in check(fri, overpaid).failures if c.name == "strand-clash"]


# --- festival checks: screenings, the guest, the print's days --------------------------


def test_checker_counts_screenings_across_the_festival() -> None:
    fest = _fest()
    fri, sat, sun = fest.briefs()
    wg = _hand_fest(
        fest,
        [_sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "rival", 15 * 60)],
        [_sess(sat, "hall", "gala", 19 * 60), _sess(sat, "box", "short", 12 * 60)],
        [_sess(sun, "hall", "rival", 12 * 60), _sess(sun, "box", "doc", 15 * 60)],
    )
    rep = check_festival(fest, wg)
    assert rep.ok, [(d, c.name, c.evidence) for d, c in rep.failures]
    by = {(c.name, c.film): c for c in rep.week.checks}
    assert by[("screenings", "gala")].evidence == "2 of 2 · Fri 1 Sat 1"
    assert by[("guest", "gala")].ok and "Sat 19:00" in by[("guest", "gala")].evidence
    assert by[("available", "doc")].ok
    # One screening short for Rival, one over for Short: both named.
    short = _hand_fest(
        fest,
        [_sess(fri, "hall", "gala", 12 * 60), _sess(fri, "box", "short", 15 * 60)],
        [_sess(sat, "hall", "gala", 19 * 60), _sess(sat, "box", "short", 12 * 60)],
        [_sess(sun, "hall", "rival", 12 * 60), _sess(sun, "box", "doc", 15 * 60)],
    )
    rep = check_festival(fest, short)
    names = {(c.name, c.film) for _, c in rep.failures}
    assert ("screenings", "rival") in names and ("screenings", "short") in names
    by = {(c.name, c.film): c for c in rep.week.checks}
    assert by[("screenings", "rival")].evidence == "1 of 2 · Sun 1"


def test_checker_catches_a_guest_screening_they_could_not_attend() -> None:
    fest = _fest()
    fri, sat, sun = fest.briefs()
    # Gala twice, but Saturday's is a matinee and the director is there from 18:00.
    wg = _hand_fest(
        fest,
        [_sess(fri, "hall", "gala", 19 * 60), _sess(fri, "box", "rival", 15 * 60)],
        [_sess(sat, "hall", "gala", 14 * 60), _sess(sat, "box", "short", 12 * 60)],
        [_sess(sun, "hall", "rival", 12 * 60), _sess(sun, "box", "doc", 15 * 60)],
    )
    rep = check_festival(fest, wg)
    fail = [c for _, c in rep.failures if c.name == "guest"]
    assert fail and fail[0].film == "gala"
    assert "the director there Sat 18:00–30:00: no screening they can attend" in fail[0].evidence
    # A grid that declares the guest given up is not a failure, and says so.
    wg.grids[1].relaxed = [TermRef(film="gala", term="guest", value="Sat 18:00–30:00")]
    rep = check_festival(fest, wg)
    assert rep.ok and not rep.clean
    assert [c.name for c in rep.week.relaxations] == ["guest"]


def test_checker_catches_a_screening_without_the_print() -> None:
    fest = _fest()
    fri, sat, sun = fest.briefs()
    wg = _hand_fest(
        fest,
        [_sess(fri, "hall", "gala", 19 * 60), _sess(fri, "box", "doc", 15 * 60)],
        [_sess(sat, "hall", "gala", 19 * 60), _sess(sat, "box", "rival", 12 * 60)],
        [_sess(sun, "hall", "rival", 12 * 60), _sess(sun, "box", "short", 15 * 60)],
    )
    rep = check_festival(fest, wg)
    # The day's own check catches it first (max_shows 0 today), and the festival names it.
    assert any(c.name == "max_shows" and c.film == "doc" for _, c in rep.failures)
    fail = [c for _, c in rep.failures if c.name == "available"]
    assert fail and "screened Fri without the print" in fail[0].evidence
