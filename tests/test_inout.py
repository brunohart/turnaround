"""In and out: a grid goes out as CSV and comes back the same grid; a plain four-column
export becomes a skeleton the checker can read; a hand-made grid's slips are caught;
the calendar and the JSON say what the grid says."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from turnaround.check import check
from turnaround.cli import app
from turnaround.inout import (
    CSV_COLUMNS,
    export_csv,
    export_ical,
    export_json,
    import_csv,
    read_rows,
    screen_ids,
)
from turnaround.model import Brief, Grid, WeekBrief, WeekGrid

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
GRIDS = ROOT / "docs" / "grids"
runner = CliRunner()


def _bare(grid: Grid) -> list[tuple[str, str, int, int, int, int]]:
    """A session without the solver's claims: what the checker reads."""
    return sorted(
        (s.screen, s.film, s.start, s.feature_start, s.feature_end, s.clear) for s in grid.sessions
    )


def _example(name: str) -> tuple[Brief, Grid]:
    brief = Brief.model_validate_json((EXAMPLES / f"{name}.json").read_text())
    grid = Grid.model_validate_json((GRIDS / f"{name}.json").read_text())
    return brief, grid


def test_the_regent_grid_survives_the_loop_unchanged() -> None:
    brief, grid = _example("regent")
    text = export_csv([(None, brief, grid)])
    assert text.splitlines()[0] == ",".join(CSV_COLUMNS)
    back_brief, back, notes = import_csv(text, brief=brief)
    assert back_brief is brief
    assert _bare(back) == _bare(grid)
    assert back.date == grid.date and back.house == grid.house
    assert back.status == "IMPORTED" and back.stats is None and back.admissions is None
    assert notes == []
    # the solver's grid claims its admissions and the checker holds it to them (the
    # `objective` row); an imported grid claims nothing, so that row is the one difference
    before = [(c.name, c.film, c.ok) for c in check(brief, grid).checks if c.name != "objective"]
    after = [(c.name, c.film, c.ok) for c in check(brief, back).checks]
    assert before == after
    assert check(brief, back).ok
    # the objective is the checker's count, and the checker counted the solver's grid the same
    assert back.objective == pytest.approx(grid.objective, abs=0.1)


def test_our_own_export_makes_a_skeleton_the_checker_passes() -> None:
    brief, grid = _example("regent")
    text = export_csv([(None, brief, grid)])
    skel, back, notes = import_csv(text, house="The Regent")
    assert skel is not brief
    assert [s.id for s in skel.screens] == ["1", "2", "3"]
    assert {s.id: s.capacity for s in skel.screens} == {"1": 320, "2": 180, "3": 96}
    assert skel.screen("3").clean_min == 15 and skel.screen("1").clean_min is None
    assert skel.policy.clean_min == 20 and skel.policy.preshow_min == 20
    assert {f.title for f in skel.films} == {f.title for f in brief.films}
    assert {f.id for f in skel.films} == {f.id for f in brief.films}  # the film column
    assert all(not f.terms.min_shows for f in skel.films)  # a skeleton carries no terms
    assert skel.date == "2026-09-10" and skel.weekday == "Thu"
    assert _bare(back) == _bare(grid)
    rep = check(skel, back)
    assert rep.ok, rep.failures
    assert not any("assumed" in n for n in notes)  # the CSV said everything


def test_the_booth_credits_and_preshows_survive_the_skeleton() -> None:
    brief, grid = _example("booth")
    text = export_csv([(None, brief, grid)])
    skel, back, notes = import_csv(text, house="The Regent")
    assert skel.film("odyssey").credits_min == brief.film("odyssey").credits_min
    assert skel.preshow_for(skel.film("odyssey")) == brief.preshow_for(brief.film("odyssey"))
    assert skel.preshow_for(skel.film("bees")) == brief.preshow_for(brief.film("bees"))
    assert _bare(back) == _bare(grid)
    rep = check(skel, back)
    # A skeleton knows no terms and no staff cap, and assumes the default stagger of one
    # start in ten; the booth allows two, so that is the one check the skeleton fails —
    # the note says so, and the house edits the skeleton. Everything else it knows holds.
    assert {c.name for c in rep.failures} == {"stagger"}, rep.failures
    assert any("stagger is the default 1 in 10" in n for n in notes)


def test_a_plain_four_column_export_gets_the_defaults_and_says_so() -> None:
    text = (
        "Auditorium,Title,Showtime,Running time\n"
        "A,Ninefold,10:15,95 min\n"
        "A,Ninefold,13:00,95 min\n"
        "B,The Quiet Ferry,10:30,110\n"
        "\n"
        "B,The Quiet Ferry,25:15,110\n"
    )
    skel, grid, notes = import_csv(text, house="The Bijou", capacity=80)
    assert [s.id for s in skel.screens] == ["A", "B"]
    assert all(s.capacity == 80 for s in skel.screens)
    assert [f.id for f in skel.films] == ["ninefold", "the-quiet-ferry"]
    assert skel.policy.open == "10:00" and skel.policy.last_start == "25:15"
    assert len(grid.sessions) == 4 and grid.status == "IMPORTED"
    late = next(s for s in grid.sessions if s.start == 25 * 60 + 15)
    assert late.feature_start == late.start + 20 and late.clear == late.feature_end + 20
    assert any("80 seats assumed" in n for n in notes)
    assert any("preshow 20 min assumed" in n for n in notes)
    assert any("turnaround 20 min assumed" in n for n in notes)
    assert check(skel, grid).ok


def test_the_hand_made_regent_is_caught_by_the_checker() -> None:
    brief = Brief.model_validate_json((EXAMPLES / "regent.json").read_text())
    _, grid, notes = import_csv((EXAMPLES / "regent-hand.csv").read_text(), brief=brief)
    assert notes == []
    assert len(grid.sessions) == 14
    rep = check(brief, grid)
    assert not rep.ok
    assert {(c.name, c.film) for c in rep.failures} == {
        ("turnaround", None),  # Dead Signal at 21:30 on Screen 2 before Harvest Moon clears
        ("stagger", None),  # 17:40 and 17:45
        ("earliest_start", "signal"),  # 15:30 is before 16:00
        ("min_shows", "atlas"),  # one show, two owed
        ("prime_shows", "atlas"),  # and none in prime
    }


def test_import_refuses_in_sentences() -> None:
    brief = Brief.model_validate_json((EXAMPLES / "regent.json").read_text())
    with pytest.raises(ValueError, match="no runtime column"):
        read_rows("screen,title,start\n1,X,10:00\n")
    with pytest.raises(ValueError, match="line 2: start time must look like HH:MM"):
        read_rows("screen,title,start,runtime\n1,X,ten,90\n")
    with pytest.raises(ValueError, match="line 3: runtime must be minutes"):
        read_rows("screen,title,start,runtime\n1,X,10:00,90\n1,X,13:00,long\n")
    with pytest.raises(ValueError, match="no title 'The Long Voyag' on the brief — the slate"):
        import_csv("screen,title,start,runtime\n1,The Long Voyag,10:00,168\n", brief=brief)
    with pytest.raises(ValueError, match="no screen '4' on the brief — the screens are 1"):
        import_csv("screen,title,start,runtime\n4,The Long Voyage,10:00,168\n", brief=brief)
    with pytest.raises(ValueError, match="holds 2 days .* import one with --day or --date"):
        import_csv(
            "day,screen,title,start,runtime\nThu,1,X,10:00,90\nFri,1,X,10:00,90\n", house="H"
        )
    with pytest.raises(ValueError, match="Harvest Moon is 2D in one row and 3D in another"):
        import_csv(
            "screen,title,start,runtime,format\n1,Harvest Moon,10:00,104,2D\n"
            "2,Harvest Moon,13:00,104,3D\n",
            house="H",
        )


def test_the_week_goes_out_as_one_csv_and_each_day_comes_back() -> None:
    week = WeekBrief.model_validate_json((EXAMPLES / "regent-week.json").read_text())
    wg = WeekGrid.model_validate_json((GRIDS / "regent-week.json").read_text())
    days = [(d.name, b, g) for d, b, g in zip(week.days, week.briefs(), wg.grids, strict=True)]
    text = export_csv(days)
    rows = read_rows(text)
    assert len(rows) == wg.sessions
    assert [r.day for r in rows if r.day == "Fri"] and rows[0].date == "2026-09-10"
    with pytest.raises(ValueError, match="holds 7 days"):
        import_csv(text, brief=week.day(1))
    fri = week.day(1)
    _, back, _ = import_csv(text, brief=fri, day="Fri")
    assert _bare(back) == _bare(wg.grid("Fri"))
    assert back.date == "2026-09-11"
    with pytest.raises(ValueError, match="no day 'Aug' in the CSV — the days are Thu, Fri"):
        import_csv(text, brief=fri, day="Aug")
    # the four-column case: a --day names the week's day, and the CSV has no day column
    bare = "screen,title,start,runtime\n1,The Long Voyage,10:30,168\n"
    _, one, _ = import_csv(bare, brief=fri, day="Fri")
    assert one.date == "2026-09-11" and len(one.sessions) == 1


def test_the_calendar_is_one_per_screen_and_folds_past_midnight() -> None:
    brief, grid = _example("regent")
    ics = export_ical([(None, brief, grid)], "1")
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert "X-WR-CALNAME:The Regent · Screen 1" in ics
    assert ics.count("BEGIN:VEVENT") == len(grid.by_screen()["1"])
    assert "SUMMARY:The Long Voyage" in ics and "LOCATION:Screen 1" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    late = brief.model_copy(update={"date": "2026-09-11"})
    g = grid.model_copy(update={"date": None})
    g.sessions[0].start = 24 * 60 + 15  # a quarter past midnight belongs to the 11th's night
    ics = export_ical([(None, late, g)], "1")
    assert "DTSTART:20260912T001500" in ics
    undated = brief.model_copy(update={"date": None})
    with pytest.raises(ValueError, match="has no date — a calendar needs one"):
        export_ical([(None, undated, g)], "1")
    assert screen_ids([(None, brief, grid)]) == ["1", "2", "3"]


def test_the_json_is_the_grid_in_clock_time() -> None:
    brief, grid = _example("regent")
    j = export_json([(None, brief, grid)])
    assert j["house"] == "The Regent"
    assert {t["id"] for t in j["titles"]} == {f.id for f in brief.films}
    day = j["days"][0]
    assert day["date"] == "2026-09-10" and day["day"] == "Thu" and day["status"] == "OPTIMAL"
    assert sum(len(s["sessions"]) for s in day["screens"]) == len(grid.sessions)
    first = day["screens"][0]["sessions"][0]
    s1 = grid.by_screen()["1"][0]
    assert first["minutes"] == s1.start and first["start"] == s1.start_hhmm
    assert first["prime"] is brief.policy.is_prime(s1.start)
    assert any(s["prime"] for scr in day["screens"] for s in scr["sessions"])


def test_the_cli_imports_checks_and_exports(tmp_path: Path) -> None:
    grid = tmp_path / "hand.json"
    r = runner.invoke(
        app,
        [
            "import",
            "--csv",
            str(EXAMPLES / "regent-hand.csv"),
            "--brief",
            str(EXAMPLES / "regent.json"),
            "--out",
            str(grid),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "14 sessions on 3 screens" in r.output and "checks green" in r.output
    assert "stagger" in r.output and "Atlas of Small Rooms" in r.output
    r = runner.invoke(app, ["check", str(EXAMPLES / "regent.json"), str(grid)])
    assert r.exit_code == 1
    # a skeleton, from the same CSV
    r = runner.invoke(
        app,
        [
            "import",
            "--csv",
            str(EXAMPLES / "regent-hand.csv"),
            "--out",
            str(tmp_path / "skel-grid.json"),
            "--brief-out",
            str(tmp_path / "skel.json"),
            "--house",
            "The Regent",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "brief skeleton" in r.output and "seats assumed" in r.output
    skel = Brief.model_validate_json((tmp_path / "skel.json").read_text())
    assert skel.house == "The Regent" and len(skel.films) == 5
    # a week brief wants a day
    r = runner.invoke(
        app,
        [
            "import",
            "--csv",
            str(EXAMPLES / "regent-hand.csv"),
            "--brief",
            str(EXAMPLES / "regent-week.json"),
        ],
    )
    assert r.exit_code == 1 and "--day (Thu, Fri" in r.output
    # export the Regent, every format, into a directory
    out = tmp_path / "out"
    r = runner.invoke(
        app,
        [
            "export",
            str(EXAMPLES / "regent.json"),
            str(GRIDS / "regent.json"),
            "--out-dir",
            str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    assert sorted(p.name for p in out.iterdir()) == [
        "regent.screen-1.ics",
        "regent.screen-2.ics",
        "regent.screen-3.ics",
        "regent.sessions.csv",
        "regent.sessions.json",
    ]
    r = runner.invoke(
        app,
        [
            "export",
            str(EXAMPLES / "regent.json"),
            str(GRIDS / "regent.json"),
            "--csv",
            "--out-dir",
            str(tmp_path / "csv-only"),
        ],
    )
    assert r.exit_code == 0 and [p.name for p in (tmp_path / "csv-only").iterdir()] == [
        "regent.sessions.csv"
    ]
