"""The CLI's explain and what-if, driven the way a programmer would drive them."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from turnaround.cli import app
from turnaround.model import Brief, Grid
from turnaround.solve import solve

EXAMPLES = Path(__file__).parent.parent / "examples"
runner = CliRunner()


def _regent_grid(tmp_path: Path) -> tuple[Path, Path]:
    brief = EXAMPLES / "regent.json"
    b = Brief.model_validate_json(brief.read_text())
    grid = solve(b, time_limit_s=20)
    out = tmp_path / "regent-grid.json"
    out.write_text(grid.model_dump_json(indent=2))
    return brief, out


def test_explain_one_session_prints_its_why_and_probes_it(tmp_path: Path) -> None:
    brief, grid = _regent_grid(tmp_path)
    g = Grid.model_validate_json(grid.read_text())
    prime = next(s for s in g.sessions if s.film == "odyssey" and 1050 <= s.start < 1245)
    out = tmp_path / "with-why.json"
    r = runner.invoke(
        app,
        ["explain", str(brief), str(grid), "--session", prime.key, "--out", str(out)],
    )
    assert r.exit_code == 0, r.output
    assert "The Long Voyage" in r.output and prime.key in r.output
    assert "prime_shows 1/1" in r.output
    assert "forced by" in r.output or "free" in r.output or "unknown" in r.output
    written = Grid.model_validate_json(out.read_text())
    probed = [s for s in written.sessions if s.forced]
    assert len(probed) == 1 and probed[0].key == prime.key


def test_explain_refuses_a_session_that_is_not_on_the_grid(tmp_path: Path) -> None:
    brief, grid = _regent_grid(tmp_path)
    r = runner.invoke(app, ["explain", str(brief), str(grid), "--session", "1@03:00"])
    assert r.exit_code == 1
    assert "no session 1@03:00" in r.output
    r = runner.invoke(app, ["explain", str(brief), str(grid), "--session", "nonsense"])
    assert r.exit_code == 1 and "screen@start" in r.output


def test_what_if_drops_a_title_and_says_where_the_slots_went(tmp_path: Path) -> None:
    brief, grid = _regent_grid(tmp_path)
    r = runner.invoke(
        app, ["what-if", str(brief), "--drop", "bees", "--against", str(grid), "--time-limit", "20"]
    )
    assert r.exit_code == 0, r.output
    assert "dropped" in r.output and "freed slots" in r.output and "objective" in r.output
    r = runner.invoke(app, ["what-if", str(brief), "--drop", "nope", "--against", str(grid)])
    assert r.exit_code == 1 and "no such title: nope" in r.output
    r = runner.invoke(app, ["what-if", str(brief)])
    assert r.exit_code == 1 and "nothing to ask" in r.output


def test_what_if_can_add_an_usher(tmp_path: Path) -> None:
    brief = EXAMPLES / "booth.json"
    b = Brief.model_validate_json(brief.read_text())
    grid = solve(b, time_limit_s=20)
    against = tmp_path / "booth-grid.json"
    against.write_text(grid.model_dump_json())
    r = runner.invoke(
        app,
        [
            "what-if",
            str(brief),
            "--set",
            "max_concurrent_turnarounds=3",
            "--against",
            str(against),
            "--time-limit",
            "20",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "objective" in r.output


def test_diff_names_the_re_plan_as_a_table_and_as_json(tmp_path: Path) -> None:
    brief, grid = _regent_grid(tmp_path)
    g = Grid.model_validate_json(grid.read_text())
    first = min(g.sessions, key=lambda s: s.start)
    # the re-plan: the first session five minutes earlier, the last one gone
    last = max(g.sessions, key=lambda s: s.start)
    moved = first.model_copy(
        update={
            "start": first.start - 5,
            "feature_start": first.feature_start - 5,
            "feature_end": first.feature_end - 5,
            "clear": first.clear - 5,
        }
    )
    new = g.model_copy(
        update={"sessions": [moved] + [s for s in g.sessions if s not in (first, last)]}
    )
    new_path = tmp_path / "replan.json"
    new_path.write_text(new.model_dump_json(indent=2))
    out = tmp_path / "diff.json"
    html = tmp_path / "replan.html"
    r = runner.invoke(
        app,
        [
            "diff",
            str(grid),
            str(new_path),
            "--brief",
            str(brief),
            "--out",
            str(out),
            "--html",
            str(html),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "1 removed" in r.output and "1 moved" in r.output
    assert f"{first.key}" in r.output and moved.key in r.output
    assert "sessions 15 → 14" in r.output
    assert "seats on offer" in r.output
    written = json.loads(out.read_text())
    assert len(written["removed"]) == 1 and written["removed"][0]["start"] == last.start
    assert written["moved"][0]["title"]  # the brief names the titles
    text = html.read_text()
    assert "Re-plan sheet" in text and 'class="block was-here' in text
    r = runner.invoke(app, ["diff", str(grid), str(new_path), "--json"])
    assert r.exit_code == 0 and '"moved"' in r.output
    r = runner.invoke(app, ["diff", str(grid), str(new_path), "--html", str(html)])
    assert r.exit_code == 1 and "--html needs --brief" in r.output
