"""The week sheet.

Renders a grid as a single HTML file in the house identity: warm paper, one
row per screen, the day as a ruler, each session a printed block with the
feature in ink and the turnaround as a hatched strip. Designed to be printed
and pinned in the booth.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .check import Report
from .model import Brief, Grid, fmt_time

_TEMPLATES = Path(__file__).parent / "templates"


def render_html(brief: Brief, grid: Grid, report: Report | None = None) -> str:
    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters["hhmm"] = fmt_time
    tpl = env.get_template("sheet.html.j2")
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
            blocks.append(
                {
                    "film": f,
                    "s": s,
                    "left": (s.start - day_start) / span * 100,
                    "pre_w": p.preshow_min / span * 100,
                    "feat_w": f.runtime_min / span * 100,
                    "clean_w": brief.clean_for(scr) / span * 100,
                    "prime": p.is_prime(s.start),
                }
            )
        rows.append({"screen": scr, "blocks": blocks, "count": len(sessions)})
    films = []
    for f in brief.films:
        ss = grid.by_film().get(f.id, [])
        films.append(
            {
                "film": f,
                "starts": [fmt_time(s.start) for s in ss],
                "prime": sum(1 for s in ss if p.is_prime(s.start)),
                "seats": sum(brief.screen(s.screen).capacity for s in ss),
            }
        )
    seats = sum(brief.screen(s.screen).capacity for s in grid.sessions)
    return tpl.render(
        brief=brief,
        grid=grid,
        report=report,
        rows=rows,
        films=films,
        hours=hours,
        day_start=day_start,
        span=span,
        prime_left=(p.prime_start_min - day_start) / span * 100,
        prime_w=(p.prime_end_min - p.prime_start_min) / span * 100,
        seats=seats,
    )
