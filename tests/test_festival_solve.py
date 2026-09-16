"""Day 10, the solver half: screenings reach a day as a floor and a ceiling, a guest's
window as a debt on their last day, the print move as a hard pair, the strand clash as
a penalty the checker holds the grid to."""

from test_festival import _fest

from turnaround.check import check_festival, clash_minutes
from turnaround.model import FestivalBrief
from turnaround.solve import solve_festival


def test_the_festival_solves_day_by_day_and_the_checker_agrees() -> None:
    fest = _fest()
    wg = solve_festival(fest, time_limit_s=10)
    assert wg.days == ["Fri", "Sat", "Sun"]
    assert all(g.status in ("OPTIMAL", "FEASIBLE") for g in wg.grids), [g.status for g in wg.grids]
    rep = check_festival(fest, wg)
    assert rep.ok and rep.clean, [(d, c.name, c.evidence) for d, c in rep.failures]
    shows = {
        f.id: sum(1 for g in wg.grids for s in g.sessions if s.film == f.id) for f in fest.films
    }
    assert shows == {"gala": 2, "rival": 2, "doc": 1, "short": 1}
    # The director's screening: Saturday, from 18:00.
    assert any(s.film == "gala" and s.start >= 18 * 60 for s in wg.grid("Sat").sessions)
    # The documentary only on Sunday.
    assert all(s.film != "doc" for g in wg.grids[:2] for s in g.sessions)
    # Every day's objective is its admissions less what it paid to clash.
    for g in wg.grids:
        assert g.admissions is not None
        assert abs(g.objective - (g.admissions - g.clash_paid)) < 0.01


def test_the_solver_pays_for_a_clash_rather_than_hides_it() -> None:
    # One venue-day cannot hold both Competition titles apart from each other unless the
    # solver keeps them apart or pays; the checker holds it to the clash it declares.
    fest = _fest(
        days=[{"name": "Sat"}],
        films=[
            {
                "id": "gala",
                "title": "Gala",
                "runtime_min": 110,
                "strand": "Competition",
                "weight": 2.0,
                "terms": {"screenings": 1, "guest": {"days": ["Sat"], "earliest": "18:00"}},
            },
            {
                "id": "rival",
                "title": "Rival",
                "runtime_min": 95,
                "strand": "Competition",
                "weight": 2.0,
                "terms": {"screenings": 1, "earliest_start": "18:00"},
            },
        ],
    )
    wg = solve_festival(fest, time_limit_s=10)
    g = wg.grids[0]
    assert g.status == "OPTIMAL"
    rep = check_festival(fest, wg)
    assert rep.ok, [(d, c.name, c.evidence) for d, c in rep.failures]
    fri = fest.day(0)
    owed = fri.policy.clash_penalty * clash_minutes(fri, g) / 60
    assert abs(g.clash_paid - owed) < 0.01
    # With the penalty off, the same brief pays nothing and the checker still counts.
    free = FestivalBrief.model_validate(
        {**fest.model_dump(), "policy": {**fest.policy.model_dump(), "clash_penalty": 0}}
    )
    wg2 = solve_festival(free, time_limit_s=10)
    assert wg2.grids[0].clash_paid == 0.0 and check_festival(free, wg2).ok


def test_a_screening_the_terms_cannot_place_names_the_festival_term() -> None:
    # The guest is there Saturday from 18:00 but the print leaves Friday: the validator
    # refuses that. A softer conflict: Gala must screen twice at one a day, but the hall
    # is the only room it fits and Saturday's hall is shut from 17:00.
    fest = _fest(
        days=[{"name": "Fri"}, {"name": "Sat", "screens": {"hall": {"last_start": "17:00"}}}],
        films=[
            {
                "id": "gala",
                "title": "Gala",
                "runtime_min": 110,
                "weight": 2.0,
                "terms": {
                    "screenings": 2,
                    "max_shows": 1,
                    "min_capacity": 200,
                    "guest": {"days": ["Sat"], "earliest": "18:00"},
                },
            },
        ],
    )
    wg = solve_festival(fest, time_limit_s=10)
    assert wg.grid("Sat").status == "INFEASIBLE"
    assert {r.term for r in wg.grid("Sat").conflict} == {"guest"}
    relaxed = solve_festival(fest, time_limit_s=10, relax_terms=True)
    assert relaxed.grid("Sat").status in ("OPTIMAL", "FEASIBLE")
    assert [(r.film, r.term) for r in relaxed.grid("Sat").relaxed] == [("gala", "guest")]
    rep = check_festival(fest, relaxed)
    assert rep.ok and not rep.clean
