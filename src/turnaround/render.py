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

from .check import Check, Report, WeekReport, admissions, term_is_set
from .model import TERM_SCOPE, Brief, Film, Grid, WeekBrief, WeekGrid, fmt_time, week_terms_set

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


def _verdict(checks: list[tuple[str, Check]]) -> tuple[str, str]:
    """One word for a term across its days, from the checker's own verdicts:
    honoured, given up (declared on the grid), or not met. And the days it failed on."""
    if not checks:
        return "unchecked", ""
    given = [d for d, c in checks if c.relaxed]
    failed = [d for d, c in checks if not c.ok and not c.relaxed]
    if failed:
        return "not met", ", ".join(failed)
    if given:
        return "given up", ", ".join(given)
    return "honoured", ""


def _delivered(name: str, day_checks: list[tuple[str, Check]]) -> str:
    """The checker's evidence per day, shortened to what a distributor reads."""
    out = []
    for d, c in day_checks:
        ev = c.evidence
        if name in ("min_shows", "max_shows", "prime_shows"):
            ev = ev.split(" ")[0]  # "4 ≥ 3 in 17:30–20:45" -> "4"
        elif name == "exclusive_screen":
            ev = ev.replace("own screen: ", "")
        elif name in ("earliest_start", "latest_start"):
            ev = "none" if ev.startswith("0 ") else ev
        elif name == "plf_lock":
            ev = ev.split(": ", 1)[-1]
        out.append(f"{d} {ev}")
    return " · ".join(out)


def terms_context(
    house: str,
    films: list[Film],
    days: list[tuple[str, Brief, Grid, Report | None]],
    week_checks: list[Check],
) -> list[dict[str, Any]]:
    """One terms sheet per title: every term the booking carries, its scope, what was
    asked, what the grid delivered day by day, and the checker's verdict. The proof is
    the checker's, not the solver's (ADR-003)."""
    sheets = []
    for f in films:
        base = f.terms
        rows: list[dict[str, Any]] = []
        for name, scope in TERM_SCOPE.items():
            if scope == "week":
                continue
            if not term_is_set(base, name) and not any(
                term_is_set(b.film(f.id).terms, name) for _, b, _, _ in days
            ):
                continue
            if name == "exclusive_screen" and base.exclusive_until and not base.exclusive_screen:
                continue  # the exclusive_until row says it
            asked = getattr(base, name)
            asked_s = ", ".join(asked) if isinstance(asked, list) else str(asked).lower()
            overrides = []
            for d, b, _, _ in days:
                v = getattr(b.film(f.id).terms, name)
                if v != asked and not (name == "exclusive_screen" and base.exclusive_until):
                    overrides.append(f"{d} {str(v).lower()}")
            day_checks = [
                (d, c)
                for d, _, _, rep in days
                if rep
                for c in rep.checks
                if c.film == f.id and c.name == name
            ]
            if name in ("screens", "min_capacity"):
                day_checks = [
                    (d, c)
                    for d, _, _, rep in days
                    if rep
                    for c in rep.checks
                    if c.name == "eligibility"
                ]
                delivered = " · ".join(
                    f"{d} "
                    + (", ".join(sorted({s.screen for s in g.sessions if s.film == f.id})) or "—")
                    for d, _, g, _ in days
                )
            else:
                delivered = _delivered(name, day_checks)
            verdict, where = _verdict(day_checks)
            rows.append(
                {
                    "term": name,
                    "scope": "each day",
                    "asked": asked_s + (" · " + " · ".join(overrides) if overrides else ""),
                    "delivered": delivered,
                    "verdict": verdict,
                    "where": where,
                }
            )
        for name, value in week_terms_set(base):
            wc = [("week", c) for c in week_checks if c.film == f.id and c.name == name]
            verdict, where = _verdict(wc)
            if name == "exclusive_until":
                value = f"through {value}"
            rows.append(
                {
                    "term": name,
                    "scope": "the week",
                    "asked": value,
                    "delivered": wc[0][1].evidence if wc else "—",
                    "verdict": verdict,
                    "where": where,
                }
            )
        schedule: list[dict[str, Any]] = []
        shows = 0
        primes = 0
        for d, b, g, _ in days:
            mine = sorted((s for s in g.sessions if s.film == f.id), key=lambda s: s.start)
            shows += len(mine)
            primes += sum(1 for s in mine if b.policy.is_prime(s.start))
            schedule.append(
                {
                    "day": d,
                    "date": b.date,
                    "status": g.status,
                    "sessions": [
                        {
                            "start": fmt_time(s.start),
                            "screen": b.screen(s.screen).label,
                            "prime": b.policy.is_prime(s.start),
                        }
                        for s in mine
                    ],
                }
            )
        sheets.append(
            {
                "film": f,
                "rows": rows,
                "schedule": schedule,
                "shows": shows,
                "primes": primes,
                "honoured": all(r["verdict"] == "honoured" for r in rows),
                "given_up": sum(1 for r in rows if r["verdict"] == "given up"),
                "not_met": sum(1 for r in rows if r["verdict"] == "not met"),
            }
        )
    return sheets


def render_terms_html(brief: Brief, grid: Grid, report: Report | None = None) -> str:
    """The terms sheets for one day: one page per title."""
    tpl = _env().get_template("terms.html.j2")
    days = [(brief.day_name or brief.date or "the day", brief, grid, report)]
    return tpl.render(
        house=brief.house,
        span=brief.date or "",
        days=[d[0] for d in days],
        sheets=terms_context(brief.house, brief.films, days, []),
    )


def render_week_terms_html(week: WeekBrief, wg: WeekGrid, report: WeekReport | None = None) -> str:
    """The terms sheets for the week: one page per title, every day in its columns."""
    tpl = _env().get_template("terms.html.j2")
    briefs = week.briefs()
    days = [
        (d.name, b, g, report.reports[i] if report else None)
        for i, (d, b, g) in enumerate(zip(week.days, briefs, wg.grids, strict=True))
    ]
    first, last = week.days[0], week.days[-1]
    span = f"{first.name} {first.date or ''} → {last.name} {last.date or ''}".replace("  ", " ")
    return tpl.render(
        house=week.house,
        span=span.strip(),
        days=[d[0] for d in days],
        sheets=terms_context(week.house, week.films, days, report.week.checks if report else []),
    )
