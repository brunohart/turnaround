"""The week sheet.

Renders a grid as a single HTML file in the house identity: warm paper, one
row per screen, the day as a ruler, each session a printed block with the
feature in ink and the turnaround as a hatched strip. Designed to be printed
and pinned in the booth. A week renders as one sheet: the by-title week table
first, then every day's grid on its own page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .check import Report, WeekReport, admissions
from .model import Brief, Grid, WeekBrief, WeekGrid, fmt_time

_TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters["hhmm"] = fmt_time
    return env


def day_context(brief: Brief, grid: Grid) -> dict[str, Any]:
    """Everything the grid macro needs to draw one day: rows of blocks on a ruler."""
    p = brief.policy
    day_start = p.open_min - (p.open_min % 60)
    latest_clear = max((s.clear for s in grid.sessions), default=p.last_start_min + 120)
    day_end = latest_clear + (60 - latest_clear % 60) % 60
    span = max(day_end - day_start, 60)
    hours = list(range(day_start, day_end + 1, 60))
    rows = []
    for scr in brief.screens:
        sessions = grid.by_screen().get(scr.id, [])
        blocks = []
        for s in sessions:
            f = brief.film(s.film)
            block = s.clear - s.start
            turn_begin, _ = brief.turnaround_of(scr, f, s.start)
            # Strip widths are percentages of the block. The turnaround strip is pulled
            # left over the feature by the credits it overlaps, so the three still add up.
            blocks.append(
                {
                    "film": f,
                    "s": s,
                    "left": (s.start - day_start) / span * 100,
                    "w": block / span * 100,
                    "pre": brief.preshow_for(f) / block * 100,
                    "feat": f.runtime_min / block * 100,
                    "clean": (s.clear - turn_begin) / block * 100,
                    "over": (s.feature_end - turn_begin) / block * 100,
                    "turn_begin": turn_begin,
                    "prime": p.is_prime(s.start),
                }
            )
        own_hours = scr.open is not None or scr.last_start is not None
        rows.append(
            {
                "screen": scr,
                "blocks": blocks,
                "count": len(sessions),
                "hours": (
                    f"{fmt_time(brief.open_for(scr))}–{fmt_time(brief.last_start_for(scr))}"
                    if own_hours
                    else None
                ),
            }
        )
    preshows = [f"preshow {p.preshow_min}′"] + [
        f"{fmt} {mins}′" for fmt, mins in p.preshow_by_format.items() if mins != p.preshow_min
    ]
    stagger = (
        f"stagger ≥ {p.stagger_min}′"
        if p.max_starts_per_window == 1
        else f"≤ {p.max_starts_per_window} starts in {p.stagger_min}′"
    )
    staff = (
        f"floor clears {p.max_concurrent_turnarounds} "
        f"room{'s' if p.max_concurrent_turnarounds != 1 else ''} at once"
        if p.max_concurrent_turnarounds is not None
        else None
    )
    films = []
    seats_sold = {a.film: a for a in admissions(brief, grid)}
    for f in brief.films:
        ss = grid.by_film().get(f.id, [])
        a = seats_sold[f.id]
        films.append(
            {
                "film": f,
                "starts": [fmt_time(s.start) for s in ss],
                "prime": sum(1 for s in ss if p.is_prime(s.start)),
                "seats": a.offered,
                "admissions": a.admissions,
                "turned_away": a.turned_away,
            }
        )
    return {
        "rows": rows,
        "films": films,
        "hours": hours,
        "day_start": day_start,
        "span": span,
        "prime_left": (p.prime_start_min - day_start) / span * 100,
        "prime_w": (p.prime_end_min - p.prime_start_min) / span * 100,
        "preshows": " · ".join(preshows),
        "stagger": stagger,
        "staff": staff,
        "credits": any(brief.film(s.film).credits_min for s in grid.sessions),
        "seats": sum(brief.screen(s.screen).capacity for s in grid.sessions),
        "admissions": sum(a.admissions for a in seats_sold.values()),
        "turned_away": sum(a.turned_away for a in seats_sold.values()),
    }


def render_html(brief: Brief, grid: Grid, report: Report | None = None) -> str:
    tpl = _env().get_template("sheet.html.j2")
    return tpl.render(brief=brief, grid=grid, report=report, d=day_context(brief, grid))


def _overrides(week: WeekBrief, i: int) -> list[str]:
    """The day's differences from the base brief, as short labels for the sheet."""
    d = week.days[i]
    out = [f"{k} {v}" for k, v in d.policy.items()]
    for fid, fields in d.terms.items():
        title = week.film_title(fid)
        for k, v in fields.items():
            out.append(f"{title} {k} {str(v).lower()}")
    for sid, fields in d.screens.items():
        label = next(s.label for s in week.screens if s.id == sid)
        for k, v in fields.items():
            out.append(f"{label} {k} {str(v).lower()}")
    return out


def render_week_html(
    week: WeekBrief,
    wg: WeekGrid,
    report: WeekReport | None = None,
    explain: dict[str, str] | None = None,
) -> str:
    """One sheet for the week. `explain` maps a day name to the sentence for its conflict."""
    tpl = _env().get_template("week.html.j2")
    briefs = week.briefs()
    hold = set(week.hold_indices)
    days = []
    for i, (d, brief, grid) in enumerate(zip(week.days, briefs, wg.grids, strict=True)):
        days.append(
            {
                "name": d.name,
                "brief": brief,
                "grid": grid,
                "d": day_context(brief, grid),
                "report": report.reports[i] if report else None,
                "hold": i in hold,
                "overrides": _overrides(week, i),
                "explain": (explain or {}).get(d.name),
            }
        )
    sold_by_day = [
        {a.film: a for a in admissions(b, g)} for b, g in zip(briefs, wg.grids, strict=True)
    ]
    title_rows = []
    for f in week.films:
        cells = []
        total = 0
        for i, grid in enumerate(wg.grids):
            starts = [fmt_time(s.start) for s in grid.by_film().get(f.id, [])]
            total += len(starts)
            cells.append({"starts": starts, "status": grid.status, "hold": i in hold})
        title_rows.append(
            {
                "film": f,
                "cells": cells,
                "total": total,
                "admissions": sum(d[f.id].admissions for d in sold_by_day),
                "turned_away": sum(d[f.id].turned_away for d in sold_by_day),
            }
        )
    seats = sum(
        brief.screen(s.screen).capacity
        for brief, grid in zip(briefs, wg.grids, strict=True)
        for s in grid.sessions
    )
    return tpl.render(
        week=week,
        wg=wg,
        days=days,
        title_rows=title_rows,
        week_report=report,
        seats=seats,
        admissions=sum(a.admissions for d in sold_by_day for a in d.values()),
        turned_away=sum(a.turned_away for d in sold_by_day for a in d.values()),
        hold_paid=sum(g.hold_paid for g in wg.grids),
        relaxed_total=sum(len(g.relaxed) for g in wg.grids),
    )
