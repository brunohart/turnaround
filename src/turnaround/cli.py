"""turnaround — the showtime grid, solved."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .check import check as run_check
from .model import Brief, Grid, fmt_time
from .render import render_html
from .solve import explain, relax, solve

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


def _load_brief(path: Path) -> Brief:
    return Brief.model_validate_json(path.read_text())


def _load_grid(path: Path) -> Grid:
    return Grid.model_validate_json(path.read_text())


def _print_grid(brief: Brief, grid: Grid) -> None:
    t = Table(title=f"{brief.house} · {grid.status} · {grid.solve_seconds}s", show_lines=False)
    t.add_column("Screen", style="bold")
    t.add_column("Sessions")
    for scr in brief.screens:
        ss = grid.by_screen().get(scr.id, [])
        cells = [f"{fmt_time(s.start)} {brief.film(s.film).title}" for s in ss]
        t.add_row(scr.label, "  ·  ".join(cells) or "[dim]dark[/dim]")
    console.print(t)


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


def _say_relaxed(brief: Brief, grid: Grid) -> None:
    for r in grid.relaxed:
        console.print(
            f"[red]✗ relaxed[/red]  {brief.film(r.film).title} {r.term}"
            + (f" {r.value}" if r.value else "")
        )


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
    """Solve a day and print the grid with its proof. Exit 2 if the terms conflict."""
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
    """Verify a grid against its brief, independently of the solver."""
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
    """Render an existing grid as the week sheet."""
    brief = _load_brief(brief_path)
    grid = _load_grid(grid_path)
    html.write_text(render_html(brief, grid, run_check(brief, grid)))
    console.print(f"sheet → {html}")


@app.command()
def validate(brief_path: Annotated[Path, typer.Argument()]) -> None:
    """Validate a brief and summarise it."""
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
