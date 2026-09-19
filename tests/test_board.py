"""The board (Day 12) draws the sheet in a browser from the same stylesheet and the same
example the package ships. These hold the copies to their sources."""

from __future__ import annotations

import json
from pathlib import Path

from turnaround.model import Brief, Grid
from turnaround.render import board_css

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "board"


def test_the_boards_stylesheet_is_the_templates() -> None:
    assert (BOARD / "sheet.css").read_text(encoding="utf-8") == board_css(), (
        "board/sheet.css has drifted from _day.html.j2 — run scripts/board.sh"
    )


def test_the_boards_example_is_the_regent() -> None:
    brief = Brief.model_validate_json((BOARD / "examples/regent.json").read_text())
    grid = Grid.model_validate_json((BOARD / "examples/regent.grid.json").read_text())
    assert brief == Brief.model_validate_json((ROOT / "examples/regent.json").read_text())
    assert grid.house == brief.house
    assert {s.film for s in grid.sessions} <= {f.id for f in brief.films}


def test_the_board_asks_for_nothing_from_anywhere_else() -> None:
    """No server, no accounts, no tracking: every address in the board is its own."""
    for page in BOARD.glob("*.*"):
        if page.suffix not in {".html", ".js", ".css"}:
            continue
        text = page.read_text(encoding="utf-8")
        assert "http://" not in text.replace("http://www.w3.org/2000/svg", ""), page.name
        assert "https://" not in text, page.name
        for word in ("localStorage", "sessionStorage", "cookie", "sendBeacon", "location.search"):
            assert word not in text, f"{page.name} mentions {word}"
    policy = json.loads((BOARD / "vercel.json").read_text())["headers"][0]["headers"][0]["value"]
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy
