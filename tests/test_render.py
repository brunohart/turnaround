"""The sheet as a document: the booth strips, the print pages, the phone view.

These read the HTML, not pixels. The screenshots in docs/grids are the eyes; the
tests make sure the markup they depend on does not quietly disappear.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from turnaround.check import check, check_week
from turnaround.model import Brief, WeekBrief
from turnaround.render import render_html, render_terms_html, render_week_html
from turnaround.solve import solve, solve_week

EXAMPLES = Path(__file__).parent.parent / "examples"


@cache
def _booth() -> tuple[Brief, str]:
    b = Brief.model_validate_json((EXAMPLES / "booth.json").read_text())
    grid = solve(b, time_limit_s=20)
    assert grid.status in ("OPTIMAL", "FEASIBLE")
    return b, render_html(b, grid, check(b, grid))


def test_booth_strips_one_page_per_screen_with_the_turnaround_called_out() -> None:
    b, html = _booth()
    strips = re.findall(r'<section class="strip-page">', html)
    assert len(strips) == len(b.screens)
    for scr in b.screens:
        assert f"{scr.capacity} seats" in html
    # the three-strip block turned vertical: doors, feature, turnaround, then the dark gap
    assert html.count('class="vpre mono"') == html.count('<div class="vfeat">')
    assert "turnaround " in html and "clear <b>" in html
    assert "over the credits" in html  # the Regent's PLF title has 11 minutes of credits
    assert "dark " in html or "back to back" in html


def test_print_pages_are_declared_in_the_same_html() -> None:
    _, html = _booth()
    assert "@page pinup { size:A3 landscape;" in html
    assert "@page strip { size:A4 portrait;" in html
    assert re.search(r"\.sheet \{[^}]*page:pinup;", html)
    assert ".strip-page { page:strip;" in html
    # the phone rule is scoped to screens so print layout never picks it up
    assert "@media screen and (max-width:800px)" in html
    assert "@media (max-width:800px)" not in html


def test_identity_marks_are_present() -> None:
    _, html = _booth()
    for mark in (
        'class="ghost" aria-hidden="true"',  # the misregistered title pass
        "transform:rotate(-.8deg)",  # rubber stamps
        "feTurbulence",  # grain
        ".stamp::after",  # the pad's offset shadow
        'class="wash"',  # the orange field off the top-right
        'class="wash blue"',  # the navy field off the bottom-left
        "transparent 38% 41%",  # the broken divider
    ):
        assert mark in html, mark


def test_week_sheet_carries_strips_for_every_day_and_screen() -> None:
    raw = json.loads((EXAMPLES / "regent-week.json").read_text())
    raw["days"] = raw["days"][:2]  # Thu and Fri; the week terms name days that are now gone
    for f in raw["films"]:
        for term in ("exclusive_until", "min_shows_per_week", "prime_shows_per_week"):
            f.get("terms", {}).pop(term, None)
    w = WeekBrief.model_validate(raw)
    wg = solve_week(w, time_limit_s=20)
    html = render_week_html(w, wg, check_week(w, wg))
    assert html.count('<section class="strip-page">') == 2 * len(w.screens)
    assert "Booth strip · Thu" in html and "Booth strip · Fri" in html


def test_terms_sheet_is_a_letter() -> None:
    b = Brief.model_validate_json((EXAMPLES / "booth.json").read_text())
    grid = solve(b, time_limit_s=20)
    html = render_terms_html(b, grid, check(b, grid))
    assert "@page letter { size:A4 portrait;" in html
    assert ".sheet { page:letter; }" in html
