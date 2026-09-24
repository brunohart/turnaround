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
from turnaround.model import Brief, Grid, WeekBrief
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


def test_the_re_plan_sheet_marks_moves_additions_and_removals() -> None:
    from turnaround.diff import diff
    from turnaround.render import day_context

    b, _ = _booth()
    grid = solve(b, time_limit_s=20)
    by_start = sorted(grid.sessions, key=lambda s: s.start)
    first, last = by_start[0], by_start[-1]
    moved = first.model_copy(
        update={
            "start": first.start - 5,
            "feature_start": first.feature_start - 5,
            "feature_end": first.feature_end - 5,
            "clear": first.clear - 5,
        }
    )
    old = grid.model_copy(update={"sessions": [moved] + [s for s in by_start[1:]]})
    new = grid.model_copy(update={"sessions": [s for s in by_start if s is not last]})
    d = diff(old, new, b)
    assert len(d.moved) == 1 and len(d.removed) == 1 and not d.added
    html = render_html(b, new, check(b, new), diff=d)
    assert "Re-plan sheet" in html and "Re-plan · 1 removed · 1 moved" in html
    # the ghost where the moved session was, on the ink hatch, and its old time
    assert html.count('class="block was-here mono"') == 1
    assert f"was {moved.start_hhmm}" in html
    # the removed session struck through in the by-title table
    assert html.count('class="st gone"') == 1
    assert f'title="removed · was on {b.screen(last.screen).label}">{last.start_hhmm}' in html
    # the orange stamp only on an addition, and none here; the legend says what the marks mean
    assert '<span class="new">added</span>' not in html
    assert "was here" in html and "removed</span>" in html
    added = grid.model_copy(update={"sessions": by_start + [moved]})
    html2 = render_html(b, added, None, diff=diff(grid, added, b))
    assert html2.count('<span class="new">added</span>') == 2  # the block and its booth strip
    # a removed title with no session left today survives the festival fold
    away = b.model_copy(
        update={
            "films": [
                f.model_copy(update={"terms": f.terms.model_copy(update={"max_shows": 0})})
                if f.id == last.film
                else f
                for f in b.films
            ]
        }
    )
    gone = grid.model_copy(update={"sessions": [s for s in by_start if s.film != last.film]})
    d2 = diff(grid, gone, away)
    ctx = day_context(away, gone, hide_away=True, diff=d2)
    assert any(f["film"].id == last.film and f["removed"] for f in ctx["films"])
    assert all(f["film"].id != last.film for f in day_context(away, gone, hide_away=True)["films"])


def test_a_brief_is_data_and_never_markup_on_the_sheet(regent: Brief) -> None:
    """Every template is named *.html.j2, which select_autoescape(["html"]) never matched,
    so a title or a house name went into the sheet as markup: a CSV import's titles, or a
    brief from a distributor, could put a script in the booth's browser, and a title with a
    quote cut its own hover title short."""
    evil = '"><img src=x onerror=alert(1)>'
    films = [f.model_copy(update={"title": evil}) for f in regent.films]
    b = regent.model_copy(update={"house": evil, "films": films})
    grid = Grid.model_validate_json(
        (EXAMPLES.parent / "docs/grids/regent.json").read_text(encoding="utf-8")
    )
    for html in (render_html(b, grid, check(b, grid)), render_terms_html(b, grid, check(b, grid))):
        assert "<img" not in html
        assert "&lt;img src=x onerror" in html
        assert "<style>" in html  # the style macro is markup and stays markup
