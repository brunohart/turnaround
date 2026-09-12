"""turnaround — the showtime grid, solved."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from . import __version__
from .check import WeekReport, admissions, check_week, whys
from .check import check as run_check
from .model import Brief, Grid, Session, WeekBrief, WeekGrid, fmt_time, validation_sentences
from .render import render_html, render_terms_html, render_week_html, render_week_terms_html
from .solve import explain, probe, probe_all, relax, solve, solve_week, what_if

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


def _is_week(path: Path) -> bool:
    """A week brief carries `days`; a week grid carries `grids`. Cheap to tell apart."""
    head = json.loads(path.read_text())
    return isinstance(head, dict) and ("days" in head or "grids" in head)


def _refuse(err: ValidationError, raw: object, path: Path) -> None:
    """A brief the tool will not take, and why, in sentences. Exit 1."""
    console.print(f"[red bold]{path} is not a brief the tool can take[/red bold]")
    for line in validation_sentences(err, raw):
        console.print(f"  [red]✗[/red] {line}")
    raise typer.Exit(code=1)


def _load_brief(path: Path) -> Brief:
    raw = json.loads(path.read_text())
    try:
        return Brief.model_validate(raw)
    except ValidationError as e:
        _refuse(e, raw, path)
        raise  # unreachable; _refuse exits


def _load_week(path: Path) -> WeekBrief:
    raw = json.loads(path.read_text())
    try:
        return WeekBrief.model_validate(raw)
    except ValidationError as e:
        _refuse(e, raw, path)
        raise


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


def _print_whys(brief: Brief, grid: Grid, only: Session | None = None) -> None:
    """One row per session: the terms it helps satisfy, what it sells, and whether the
    solver found it forced."""
    probed = any(s.forced for s in grid.sessions)
    t = Table(title="Why", show_lines=False)
    t.add_column("Session", style="bold")
    t.add_column("Title")
    t.add_column("Terms")
    t.add_column("Sells", justify="right")
    if probed:
        t.add_column("Forced")
    for w in whys(brief, grid):
        s = w.session
        if only and (s.screen, s.start) != (only.screen, only.start):
            continue
        sold = f"{w.admissions:,.0f}"
        if w.expected - w.admissions >= 0.5:
            sold += f" [red]of {w.expected:,.0f}[/red]"
        sold += f" [dim]{w.daypart or ''} #{w.rank + 1}[/dim]"
        row = [s.key, brief.film(s.film).title, " · ".join(w.terms) or "[dim]none[/dim]", sold]
        if probed:
            f = s.forced
            if f is None:
                row.append("[dim]not probed[/dim]")
            elif f.by == "terms":
                row.append("[red bold]" + str(f) + "[/red bold]")
            elif f.by == "objective":
                row.append("[blue]" + str(f) + "[/blue]")
            elif f.by == "free":
                row.append("[dim]" + str(f) + "[/dim]")
            else:
                row.append("[red]" + str(f) + "[/red]")
        t.add_row(*row)
    console.print(t)


def _find_session(brief: Brief, grid: Grid, key: str) -> Session:
    """`1@17:30` → the session on screen 1 whose preshow begins at 17:30."""
    if "@" not in key:
        console.print(f"[red]a session is named screen@start, e.g. 1@17:30 — not {key!r}[/red]")
        raise typer.Exit(code=1)
    sid, hhmm = key.split("@", 1)
    for s in grid.sessions:
        if s.screen == sid and fmt_time(s.start) == hhmm:
            return s
    on = ", ".join(x.key for x in grid.by_screen().get(sid, []))
    console.print(
        f"[red]no session {key} on the grid[/red]"
        + (f" — {brief.screen(sid).label} has {on}" if on else f" — screen {sid} is dark")
    )
    raise typer.Exit(code=1)


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
        if c.relaxed:
            mark, evidence = "[red bold]✗[/red bold]", f"[red]relaxed[/red] · {c.evidence}"
        elif c.ok:
            mark, evidence = "[blue]✓[/blue]", c.evidence
        else:
            mark, evidence = "[red bold]✗[/red bold]", c.evidence
        t.add_row(mark, c.name + (f" {week.film_title(c.film)}" if c.film else ""), evidence)
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
    why: Annotated[
        bool,
        typer.Option(
            "--why",
            help="Probe every session: forbid it, solve again, and record whether the terms "
            "or the objective force it. One solve per session; a day only.",
        ),
    ] = False,
) -> None:
    """Solve a day, or a week, and print the grid with its proof. Exit 2 if the terms conflict."""
    if _is_week(brief_path):
        if why:
            console.print("[red]--why probes a day; run explain on one day of the week[/red]")
            raise typer.Exit(code=1)
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
    if why:
        probe_all(brief, grid, time_limit_s=min(time_limit, 10.0))
        if not quiet:
            _print_whys(brief, grid)
        _say_forced(grid)
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


def _say_forced(grid: Grid) -> None:
    """One line: how many sessions the terms force, the objective forces, and are free."""
    kinds = {"terms": 0, "objective": 0, "free": 0, "unknown": 0}
    for s in grid.sessions:
        if s.forced:
            kinds[s.forced.by] += 1
    probed = sum(kinds.values())
    seconds = sum(s.forced.seconds for s in grid.sessions if s.forced)
    line = (
        f"{probed} sessions probed in {seconds:,.1f}s · "
        f"[red bold]{kinds['terms']} forced by the terms[/red bold] · "
        f"[blue]{kinds['objective']} by the objective[/blue] · {kinds['free']} free"
    )
    if kinds["unknown"]:
        line += f" · [red]{kinds['unknown']} unknown[/red]"
    console.print(line)


@app.command("explain")
def explain_cmd(
    brief_path: Annotated[Path, typer.Argument(help="Brief JSON")],
    grid_path: Annotated[Path, typer.Argument(help="Grid JSON")],
    session: Annotated[
        str | None, typer.Option("--session", "-s", help="One session, as screen@start: 1@17:30")
    ] = None,
    do_probe: Annotated[
        bool,
        typer.Option(
            "--probe/--no-probe",
            help="Forbid the session and solve again to learn whether it is forced. "
            "On by default for one session; with no --session, every session is probed.",
        ),
    ] = True,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the grid back with `forced` set")
    ] = None,
    time_limit: Annotated[float, typer.Option(help="Seconds per probe")] = 10.0,
) -> None:
    """Why a session is where it is: the terms it helps satisfy, what it sells, and —
    by forbidding it and solving again — whether the terms or the objective force it."""
    if _is_week(brief_path):
        console.print("[red]explain takes a day's brief and grid; pick a day of the week[/red]")
        raise typer.Exit(code=1)
    brief = _load_brief(brief_path)
    grid = _load_grid(grid_path)
    only = _find_session(brief, grid, session) if session else None
    if do_probe:
        if only:
            only.forced = probe(brief, grid, only, time_limit_s=time_limit)
        else:
            probe_all(brief, grid, time_limit_s=time_limit)
    _print_whys(brief, grid, only)
    if only:
        w = next(x for x in whys(brief, grid) if x.session is only)
        console.print(f"{brief.film(only.film).title} {only.key}: {w.sentence}")
    elif do_probe:
        _say_forced(grid)
    if out:
        out.write_text(grid.model_dump_json(indent=2))
        console.print(f"grid → {out}")


def _print_what_if(base_brief: Brief, base: Grid, brief: Brief, grid: Grid) -> None:
    """The day as it was beside the day as it would be: per title, shows and admissions
    before and after; the sessions that appeared; where the freed slots went."""
    t = Table(title=f"What if · {grid.status} · {grid.solve_seconds}s", show_lines=False)
    t.add_column("Title", style="bold")
    t.add_column("Shows")
    t.add_column("Expected", justify="right")
    t.add_column("Starts")
    was = {a.film: a for a in admissions(base_brief, base)}
    now = {a.film: a for a in admissions(brief, grid)}
    for f in base_brief.films:
        a = was[f.id]
        b = now.get(f.id)
        if b is None:
            t.add_row(
                f"[dim]{f.title}[/dim]",
                f"{a.shows} → [red]dropped[/red]",
                f"{a.admissions:,.0f} → —",
                "",
            )
            continue
        old_starts = {(s.screen, s.start) for s in base.sessions if s.film == f.id}
        new_starts = {(s.screen, s.start) for s in grid.sessions if s.film == f.id}
        starts = []
        for s in sorted(grid.by_film().get(f.id, []), key=lambda x: x.start):
            k = (s.screen, s.start)
            starts.append(f"[blue]{s.key}[/blue]" if k not in old_starts else s.key)
        for scr, st in sorted(old_starts - new_starts, key=lambda k: k[1]):
            starts.append(f"[dim strike]{scr}@{fmt_time(st)}[/dim strike]")
        shows = f"{a.shows} → {b.shows}" if a.shows != b.shows else str(b.shows)
        delta = b.admissions - a.admissions
        exp = f"{b.admissions:,.0f}" + (
            f" [{'blue' if delta > 0 else 'red'}]({delta:+,.0f})[/{'blue' if delta > 0 else 'red'}]"
            if abs(delta) >= 0.5
            else ""
        )
        t.add_row(f.title, shows, exp, " ".join(starts))
    console.print(t)
    gone = [s for s in base.sessions if s.film not in {f.id for f in brief.films}]
    if gone:
        freed = []
        for s in gone:
            taker = [
                x
                for x in grid.sessions
                if x.screen == s.screen and x.start < s.clear and x.clear > s.start
            ]
            if taker:
                x = min(taker, key=lambda y: abs(y.start - s.start))
                freed.append(f"{s.key} → {brief.film(x.film).title} {fmt_time(x.start)}")
            else:
                freed.append(f"{s.key} → dark")
        console.print("freed slots: " + " · ".join(freed))
    d = grid.objective - base.objective
    console.print(
        f"objective {base.objective:,.1f} → [bold]{grid.objective:,.1f}[/bold] "
        f"({d:+,.1f} expected admissions) · new starts in blue, gone ones struck"
    )


@app.command("what-if")
def what_if_cmd(
    brief_path: Annotated[Path, typer.Argument(help="Brief JSON")],
    drop: Annotated[
        list[str] | None, typer.Option("--drop", help="A title id to leave out; repeatable")
    ] = None,
    set_: Annotated[
        list[str] | None,
        typer.Option(
            "--set", help="A policy field to change, key=value: max_concurrent_turnarounds=3"
        ),
    ] = None,
    against: Annotated[
        Path | None,
        typer.Option("--against", help="The day's grid as it stands; solved afresh if omitted"),
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the what-if grid")] = None,
    html: Annotated[Path | None, typer.Option("--html", help="Write its sheet")] = None,
    time_limit: Annotated[float, typer.Option(help="Solver time limit, seconds")] = 30.0,
) -> None:
    """The day without a title, or under a changed policy, beside the day as it stands:
    what the freed slots went to and what the objective gained or lost. Terms are never
    relaxed; a what-if that cannot hold them says INFEASIBLE."""
    if _is_week(brief_path):
        console.print("[red]what-if takes a day's brief; pick a day of the week[/red]")
        raise typer.Exit(code=1)
    if not drop and not set_:
        console.print("[red]nothing to ask: give --drop TITLE or --set KEY=VALUE[/red]")
        raise typer.Exit(code=1)
    brief = _load_brief(brief_path)
    policy: dict[str, object] = {}
    for kv in set_ or []:
        if "=" not in kv:
            console.print(f"[red]--set wants key=value, not {kv!r}[/red]")
            raise typer.Exit(code=1)
        k, v = kv.split("=", 1)
        policy[k] = int(v) if v.isdigit() else v
    try:
        changed, grid = what_if(brief, drop=drop, policy=policy, time_limit_s=time_limit)
    except (ValueError, ValidationError) as e:
        lines = validation_sentences(e, None) if isinstance(e, ValidationError) else [str(e)]
        for line in lines:
            console.print(f"  [red]✗[/red] {line}")
        raise typer.Exit(code=1) from None
    base = _load_grid(against) if against else solve(brief, time_limit_s=time_limit)
    if grid.status not in ("OPTIMAL", "FEASIBLE"):
        if grid.status == "INFEASIBLE":
            console.print(f"[red bold]INFEASIBLE[/red bold] — {explain(changed, grid)}")
        else:
            console.print(f"[red bold]{grid.status}[/red bold] — no grid within {time_limit}s")
        raise typer.Exit(code=2)
    _print_what_if(brief, base, changed, grid)
    rep = run_check(changed, grid)
    if out:
        out.write_text(grid.model_dump_json(indent=2))
        console.print(f"grid → {out}")
    if html:
        html.write_text(render_html(changed, grid, rep))
        console.print(f"sheet → {html}")
    if not rep.ok:
        console.print("[red bold]the what-if grid fails its own check — this is a bug[/red bold]")
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
def terms(
    brief_path: Annotated[Path, typer.Argument()],
    grid_path: Annotated[Path, typer.Argument()],
    html: Annotated[Path, typer.Option("--html")],
) -> None:
    """The terms sheets: one page per title, every term the booking carries, what the
    grid delivered day by day, and the checker's verdict. The document a programmer
    sends back to the distributor."""
    if _is_week(brief_path):
        week = _load_week(brief_path)
        wg = _load_week_grid(grid_path)
        html.write_text(render_week_terms_html(week, wg, check_week(week, wg)))
    else:
        brief = _load_brief(brief_path)
        grid = _load_grid(grid_path)
        html.write_text(render_terms_html(brief, grid, run_check(brief, grid)))
    console.print(f"terms → {html}")


@app.command()
def validate(brief_path: Annotated[Path, typer.Argument()]) -> None:
    """Validate a brief, or a week brief, and summarise it. A brief the tool cannot
    take is refused in sentences: which title, which term, and why."""
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
