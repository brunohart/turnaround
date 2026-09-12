"""The CLI's explain and what-if, driven the way a programmer would drive them."""

from __future__ import annotations

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
