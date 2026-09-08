"""turnaround — the showtime grid, solved."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .check import WeekReport, admissions, check_week
from .check import check as run_check
from .model import Brief, Grid, WeekBrief, WeekGrid, fmt_time
from .render import render_html, render_week_html
from .solve import explain, relax, solve, solve_week

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


def _is_week(path: Path) -> bool:
    """A week brief carries `days`; a week grid carries `grids`. Cheap to tell apart."""
    head = json.loads(path.read_text())
    return isinstance(head, dict) and ("days" in head or "grids" in head)


def _load_brief(path: Path) -> Brief:
    return Brief.model_validate_json(path.read_text())


def _load_week(path: Path) -> WeekBrief:
    return WeekBrief.model_validate_json(path.read_text())


def _load_grid(path: Path) -> Grid:
    return Grid.model_validate_json(path.read_text())


def _load_week_grid(path: Path) -> WeekGrid:
    return WeekGrid.model_validate_json(path.read_text())


def _print_grid(brief: Brief, grid: Grid) -> None:
    t = Table(title=f"{brief.house} · {grid.status} · {grid.solve_seconds}s", show_lines=False)
    t.add_column("Screen", style="bold")
    t.add_column("Sessions")
    for scr in brief.screens:
        ss = grid.by_screen().get(scr.id, [])
        cells = [f"{fmt_time(s.start)} {brief.film(s.film).title}" for s in ss]
        t.add_row(scr.label, "  ·  ".join(cells) or "[dim]dark[/dim]")
    console.print(t)
    _say_admissions(brief, grid)


def _say_admissions(brief: Brief, grid: Grid, prefix: str = "") -> None:
    """One line: who is expected to come, who gets a seat, who is turned away."""
    rows = admissions(brief, grid)
    sold = sum(r.admissions for r in rows)
    offered = sum(r.offered for r in rows)
    away = sum(r.turned_away for r in rows)
    line = f"{prefix}expected admissions [bold]{sold:,.0f}[/bold] of {offered:,} seats on offer"
    if away >= 0.5:
        line += f" · [red]{away:,.0f} turned away at capacity[/red]"
        full = [brief.film(r.film).title for r in rows if r.turned_away >= 0.5]
        line += " (" + ", ".join(full) + ")"
    if grid.hold_paid:
        line += f" · {grid.hold_paid:,.0f} paid to hold times"
    console.print(line)


def _print_report(brief: Brief, grid: Grid) -> bool:
    rep = run_check(brief, grid)
    t = Table(title="Proof", show_lines=False)
    t.add_column("")
    t.add_column("Check")
    t.add_column("Title")
    t.add_column("Evidence")
    for c in rep.checks:
        if c.relaxed:
            mark, evidence = "[red bold]✗[/red bold]", f"[red]relaxed[/red] · {c.evidence}"
        elif c.ok:
            mark, evidence = "[blue]✓[/blue]", c.evidence
        else:
            mark, evidence = "[red bold]✗[/red bold]", c.evidence
        t.add_row(mark, c.name, c.film or "", evidence)
    console.print(t)
    return rep.ok


def _say_relaxed(brief: Brief, grid: Grid, prefix: str = "") -> None:
    for r in grid.relaxed:
        console.print(
            f"[red]✗ relaxed[/red]  {prefix}{brief.film(r.film).title} {r.term}"
            + (f" {r.value}" if r.value else "")
        )


def _print_week(week: WeekBrief, wg: WeekGrid) -> None:
    """One row per day: status, seconds, sessions, and each title's starts."""
    t = Table(
        title=f"{week.house} · the week · {wg.status} · {wg.solve_seconds}s", show_lines=False
    )
    t.add_column("Day", style="bold")
    t.add_column("Status")
    t.add_column("Sessions", justify="right")
    for f in week.films:
        t.add_column(f.title)
    for d, brief, grid in zip(week.days, week.briefs(), wg.grids, strict=True):
        cells = [
            d.name + (" *" if d.name in week.hold_days else ""),
            f"{grid.status} {grid.solve_seconds}s",
            str(len(grid.sessions)),
        ]
        if grid.status in ("OPTIMAL", "FEASIBLE"):
            for f in week.films:
                starts = [fmt_time(s.start) for s in grid.by_film().get(f.id, [])]
                cells.append(" ".join(starts) or "[dim]—[/dim]")
        else:
            cells.append(f"[red]{explain(brief, grid)}[/red]")
            cells += [""] * (len(week.films) - 1)
        t.add_row(*cells)
    console.print(t)
    run = "/".join(wg.hold_days)
    held = ", ".join(week.film_title(f) for f in wg.held) or "none"
    console.print(
        f"* hold days {run}: {len(wg.held)} of {len(week.films)} titles keep their starts — {held}"
    )
    for d, brief, grid in zip(week.days, week.briefs(), wg.grids, strict=True):
        if grid.status in ("OPTIMAL", "FEASIBLE"):
            _say_admissions(brief, grid, prefix=f"{d.name}: ")


def _print_week_report(week: WeekBrief, wg: WeekGrid) -> WeekReport:
    rep = check_week(week, wg)
    t = Table(title="Proof, the week", show_lines=False)
    t.add_column("")
    t.add_column("Day")
    t.add_column("Evidence")
    for c in rep.week.checks:
        mark = "[blue]✓[/blue]" if c.ok else "[red bold]✗[/red bold]"
        t.add_row(mark, c.name, c.evidence)
    for d, r in zip(rep.days, rep.reports, strict=True):
        green = sum(1 for c in r.checks if c.ok)
        mark = "[blue]✓[/blue]" if r.ok else "[red bold]✗[/red bold]"
        line = f"{green} of {len(r.checks)} checks green"
        if r.relaxations:
            line += f" · [red]{len(r.relaxations)} relaxed[/red]"
        if r.failures:
            line += (
                " · [red bold]"
                + "; ".join(
                    f"{c.name}{' ' + c.film if c.film else ''}: {c.evidence}" for c in r.failures
                )
                + "[/red bold]"
            )
        t.add_row(mark, d, line)
    console.print(t)
    return rep


def _plan_week(
    path: Path,
    out: Path | None,
    html: Path | None,
    time_limit: float,
    relax_terms: bool,
    quiet: bool,
) -> None:
    week = _load_week(path)
    wg = solve_week(week, time_limit_s=time_limit, relax_terms=relax_terms)
    briefs = week.briefs()
    bad = [
        (d.name, b, g)
        for d, b, g in zip(week.days, briefs, wg.grids, strict=True)
        if g.status not in ("OPTIMAL", "FEASIBLE")
    ]
    for name, b, g in bad:
        if g.status == "INFEASIBLE":
            console.print(f"[red bold]{name} INFEASIBLE[/red bold] — {explain(b, g)}")
        else:
            console.print(f"[red bold]{name} {g.status}[/red bold] — no grid within {time_limit}s")
            _say_relaxed(b, g, prefix=f"{name} ")
    if bad:
        if not relax_terms and any(g.status == "INFEASIBLE" for _, _, g in bad):
            console.print(
                "[dim]turnaround plan --relax drops terms day by day until each day fits[/dim]"
            )
        raise typer.Exit(code=2)
    if not quiet:
        _print_week(week, wg)
    for d, b, g in zip(week.days, briefs, wg.grids, strict=True):
        _say_relaxed(b, g, prefix=f"{d.name} ")
    rep = _print_week_report(week, wg) if not quiet else check_week(week, wg)
    if out:
        out.write_text(wg.model_dump_json(indent=2))
        console.print(f"grid → {out}")
    if html:
        html.write_text(render_week_html(week, wg, rep))
        console.print(f"sheet → {html}")
    if not rep.ok:
        console.print(
            "[red bold]the solver produced a week the checker rejects — this is a bug[/red bold]"
        )
        raise typer.Exit(code=3)


@app.command()
def plan(
    brief_path: Annotated[Path, typer.Argument(help="Brief JSON")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write grid JSON")] = None,
    html: Annotated[Path | None, typer.Option("--html", help="Write the week sheet")] = None,
    time_limit: Annotated[float, typer.Option(help="Solver time limit, seconds")] = 30.0,
    relax_terms: Annotated[
        bool,
        typer.Option(
            "--relax",
            help="If the terms conflict, drop them one at a time (lightest film first, "
            "prime before min, exclusive last) until a grid exists. Every drop is printed.",
        ),
    ] = False,
    quiet: bool = False,
) -> None:
    """Solve a day, or a week, and print the grid with its proof. Exit 2 if the terms conflict."""
    if _is_week(brief_path):
        _plan_week(brief_path, out, html, time_limit, relax_terms, quiet)
        return
    brief = _load_brief(brief_path)
    grid = (
        relax(brief, time_limit_s=time_limit)
        if relax_terms
        else solve(brief, time_limit_s=time_limit)
    )
    if grid.status not in ("OPTIMAL", "FEASIBLE"):
        if grid.status == "INFEASIBLE":
            console.print(f"[red bold]INFEASIBLE[/red bold] — {explain(brief, grid)}")
            if not relax_terms:
                console.print("[dim]turnaround plan --relax drops terms until a grid exists[/dim]")
        else:
            console.print(f"[red bold]{grid.status}[/red bold] — no grid within {time_limit}s")
            _say_relaxed(brief, grid)  # what had already been given up when time ran out
        raise typer.Exit(code=2)
    if not quiet:
        _print_grid(brief, grid)
    _say_relaxed(brief, grid)
    ok = _print_report(brief, grid) if not quiet else run_check(brief, grid).ok
    if out:
        out.write_text(grid.model_dump_json(indent=2))
        console.print(f"grid → {out}")
    if html:
        html.write_text(render_html(brief, grid, run_check(brief, grid)))
        console.print(f"sheet → {html}")
    if not ok:
        console.print(
            "[red bold]the solver produced a grid the checker rejects — this is a bug[/red bold]"
        )
        raise typer.Exit(code=3)


@app.command("check")
def check_cmd(
    brief_path: Annotated[Path, typer.Argument(help="Brief JSON")],
    grid_path: Annotated[Path, typer.Argument(help="Grid JSON")],
) -> None:
    """Verify a grid, or a week of them, against its brief, independently of the solver."""
    if _is_week(brief_path):
        week = _load_week(brief_path)
        wg = _load_week_grid(grid_path)
        for d, b, g in zip(week.days, week.briefs(), wg.grids, strict=True):
            _say_relaxed(b, g, prefix=f"{d.name} ")
        rep = _print_week_report(week, wg)
        raise typer.Exit(code=0 if rep.ok else 1)
    brief = _load_brief(brief_path)
    grid = _load_grid(grid_path)
    _say_relaxed(brief, grid)
    ok = _print_report(brief, grid)
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def render(
    brief_path: Annotated[Path, typer.Argument()],
    grid_path: Annotated[Path, typer.Argument()],
    html: Annotated[Path, typer.Option("--html")],
) -> None:
    """Render an existing grid, or week of grids, as the week sheet."""
    if _is_week(brief_path):
        week = _load_week(brief_path)
        wg = _load_week_grid(grid_path)
        html.write_text(render_week_html(week, wg, check_week(week, wg)))
        console.print(f"sheet → {html}")
        return
    brief = _load_brief(brief_path)
    grid = _load_grid(grid_path)
    html.write_text(render_html(brief, grid, run_check(brief, grid)))
    console.print(f"sheet → {html}")


@app.command()
def validate(brief_path: Annotated[Path, typer.Argument()]) -> None:
    """Validate a brief, or a week brief, and summarise it."""
    if _is_week(brief_path):
        week = _load_week(brief_path)
        console.print_json(
            json.dumps(
                {
                    "house": week.house,
                    "days": [d.name for d in week.days],
                    "hold_days": [d.name for d in week.days if d.name in week.hold_days],
                    "screens": len(week.screens),
                    "films": len(week.films),
                    "seats": sum(s.capacity for s in week.screens),
                    "overrides": {
                        d.name: {**d.policy, **{f: t for f, t in d.terms.items()}}
                        for d in week.days
                        if d.policy or d.terms
                    },
                }
            )
        )
        return
    brief = _load_brief(brief_path)
    console.print_json(
        json.dumps(
            {
                "house": brief.house,
                "screens": len(brief.screens),
                "films": len(brief.films),
                "seats": sum(s.capacity for s in brief.screens),
                "open": brief.policy.open,
                "last_start": brief.policy.last_start,
            }
        )
    )


@app.command()
def version() -> None:
    console.print(__version__)
