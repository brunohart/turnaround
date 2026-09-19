"""turnaround — the showtime grid, solved."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from . import __version__
from .check import WeekReport, admissions, check_festival, check_week, whys
from .check import check as run_check
from .diff import GridDiff, WeekDiff, diff, diff_week
from .inout import Day, export_csv, export_ical, export_json_text, import_csv, screen_ids
from .model import (
    Brief,
    FestivalBrief,
    Grid,
    Session,
    WeekBrief,
    WeekGrid,
    fmt_time,
    validation_sentences,
)
from .render import (
    render_festival_html,
    render_festival_terms_html,
    render_html,
    render_terms_html,
    render_week_html,
    render_week_terms_html,
)
from .solve import (
    Tuning,
    explain,
    probe,
    probe_all,
    relax,
    solve,
    solve_festival,
    solve_week,
    what_if,
)

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


def _is_week(path: Path) -> bool:
    """A week brief carries `days`; a week grid carries `grids`. Cheap to tell apart. A
    festival brief carries `days` too, and `festival`; it is not a week."""
    head = json.loads(path.read_text())
    return isinstance(head, dict) and ("days" in head or "grids" in head) and "festival" not in head


def _is_festival(path: Path) -> bool:
    """A festival brief says `festival` where a house says `house`."""
    head = json.loads(path.read_text())
    return isinstance(head, dict) and "festival" in head


def _load_festival(path: Path) -> FestivalBrief:
    raw = json.loads(path.read_text())
    try:
        return FestivalBrief.model_validate(raw)
    except ValidationError as e:
        _refuse(e, raw, path)
        raise


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
    if grid.clash_paid:
        line += f" · {grid.clash_paid:,.0f} paid in clashes"
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


OUT_OF_TIME = 4


def _exit_without_a_grid(statuses: list[str], relax_terms: bool, *, week: bool) -> NoReturn:
    """No grid, and why matters: exit 2 says the terms conflict, which is an answer about
    the brief (ADR-002); exit 4 says the clock ran out, which is an answer about the
    machine. A caller that relaxes terms on 2 must never do it on 4 — a slow runner is
    not a reason to drop a distributor's minimum. In a week, a day with no grid leaves its
    share of every week term to the days after it, so an INFEASIBLE after an UNKNOWN is
    not to be believed either, and the whole week exits 4."""
    if any(st != "INFEASIBLE" for st in statuses):
        if week and "INFEASIBLE" in statuses:
            console.print(
                "[dim]a day that ran out of time leaves its share of the week's terms to the "
                "days after it — their INFEASIBLE may be the clock's, not the terms'[/dim]"
            )
        console.print("[dim]out of time, not out of options: raise --time-limit[/dim]")
        raise typer.Exit(code=OUT_OF_TIME)
    if not relax_terms:
        drops = "day by day until each day fits" if week else "until a grid exists"
        console.print(f"[dim]turnaround plan --relax drops terms {drops}[/dim]")
    raise typer.Exit(code=2)


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


def _print_festival(fest: FestivalBrief, wg: WeekGrid) -> None:
    """One row per day: status, seconds, sessions, what plays where."""
    t = Table(
        title=f"{fest.festival} · {len(fest.days)} days · {wg.status} · {wg.solve_seconds}s",
        show_lines=False,
    )
    t.add_column("Day", style="bold")
    t.add_column("Status")
    t.add_column("Sessions", justify="right")
    t.add_column("Programme")
    for d, brief, grid in zip(fest.days, fest.briefs(), wg.grids, strict=True):
        cells = [d.name, f"{grid.status} {grid.solve_seconds}s", str(len(grid.sessions))]
        if grid.status in ("OPTIMAL", "FEASIBLE"):
            cells.append(
                "  ·  ".join(
                    f"{fmt_time(s.start)} {brief.film(s.film).title} [dim]{s.screen}[/dim]"
                    for s in sorted(grid.sessions, key=lambda s: (s.start, s.screen))
                )
                or "[dim]dark[/dim]"
            )
        else:
            cells.append(f"[red]{explain(brief, grid)}[/red]")
        t.add_row(*cells)
    console.print(t)
    for d, brief, grid in zip(fest.days, fest.briefs(), wg.grids, strict=True):
        if grid.status in ("OPTIMAL", "FEASIBLE"):
            _say_admissions(brief, grid, prefix=f"{d.name}: ")


def _print_week_report(week: WeekBrief | FestivalBrief, wg: WeekGrid) -> WeekReport:
    festival = isinstance(week, FestivalBrief)
    rep = check_festival(week, wg) if isinstance(week, FestivalBrief) else check_week(week, wg)
    t = Table(title="Proof, the festival" if festival else "Proof, the week", show_lines=False)
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


def _say_stats(grid: Grid) -> None:
    """One dim line: the model's size, the grid it was solved on, the first grid's time
    and, on a grid not proven best, the bound and the gap."""
    st = grid.stats
    if st is None:
        return
    line = (
        f"{st.candidates:,} candidates on a {st.slot_min}-minute grid · "
        f"{st.booleans:,} booleans, {st.rank_literals:,} of them ranks · "
        f"{st.constraints:,} constraints"
    )
    if st.first_feasible_s is not None:
        line += f" · first grid at {st.first_feasible_s:.1f}s"
    if grid.status == "FEASIBLE" and st.bound is not None and st.gap is not None:
        line += f" · bound {st.bound:,.1f} · gap {st.gap:.1%}"
    if st.hinted:
        line += f" · {st.hinted} sessions hinted"
    if st.symmetry_groups:
        line += f" · {st.symmetry_groups} groups of identical screens ordered"
    console.print(f"[dim]{line}[/dim]")
    if st.slot_reason:
        console.print(f"[yellow]{st.slot_reason}[/yellow]")


def _tuning(max_candidates: int) -> Tuning:
    return Tuning(candidate_cap=max_candidates or None)


def _plan_week(
    path: Path,
    out: Path | None,
    html: Path | None,
    time_limit: float,
    relax_terms: bool,
    quiet: bool,
    tuning: Tuning,
) -> None:
    week = _load_week(path)
    wg = solve_week(week, time_limit_s=time_limit, relax_terms=relax_terms, tuning=tuning)
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
        _exit_without_a_grid([g.status for _, _, g in bad], relax_terms, week=True)
    if not quiet:
        _print_week(week, wg)
    for d, b, g in zip(week.days, briefs, wg.grids, strict=True):
        _say_relaxed(b, g, prefix=f"{d.name} ")
        if g.stats and (g.stats.slot_reason or g.status == "FEASIBLE"):
            console.print(f"[dim]{d.name}[/dim]", end=" ")
            _say_stats(g)
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


def _plan_festival(
    path: Path,
    out: Path | None,
    html: Path | None,
    time_limit: float,
    relax_terms: bool,
    quiet: bool,
    tuning: Tuning,
) -> None:
    fest = _load_festival(path)
    wg = solve_festival(fest, time_limit_s=time_limit, relax_terms=relax_terms, tuning=tuning)
    briefs = fest.briefs()
    bad = [
        (d.name, b, g)
        for d, b, g in zip(fest.days, briefs, wg.grids, strict=True)
        if g.status not in ("OPTIMAL", "FEASIBLE")
    ]
    for name, b, g in bad:
        if g.status == "INFEASIBLE":
            console.print(f"[red bold]{name} INFEASIBLE[/red bold] — {explain(b, g)}")
        else:
            console.print(f"[red bold]{name} {g.status}[/red bold] — no grid within {time_limit}s")
            _say_relaxed(b, g, prefix=f"{name} ")
    if bad:
        _exit_without_a_grid([g.status for _, _, g in bad], relax_terms, week=True)
    if not quiet:
        _print_festival(fest, wg)
    for d, b, g in zip(fest.days, briefs, wg.grids, strict=True):
        _say_relaxed(b, g, prefix=f"{d.name} ")
        if g.stats and (g.stats.slot_reason or g.status == "FEASIBLE"):
            console.print(f"[dim]{d.name}[/dim]", end=" ")
            _say_stats(g)
    rep = _print_week_report(fest, wg) if not quiet else check_festival(fest, wg)
    if out:
        out.write_text(wg.model_dump_json(indent=2))
        console.print(f"grid → {out}")
    if html:
        html.write_text(render_festival_html(fest, wg, rep))
        console.print(f"sheet → {html}")
    if not rep.ok:
        console.print(
            "[red bold]the solver produced a festival the checker rejects — "
            "this is a bug[/red bold]"
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
    probe_budget: Annotated[
        float | None,
        typer.Option(
            "--probe-budget",
            help="Seconds the whole --why probe may take; sessions left unprobed are unknown",
        ),
    ] = None,
    hint: Annotated[
        Path | None,
        typer.Option("--hint", help="A grid to start the search from: yesterday's, or this one"),
    ] = None,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Coarsen the start grid until the candidates fit under this; 0 never coarsens",
        ),
    ] = 20_000,
) -> None:
    """Solve a day, or a week, and print the grid with its proof. Exit 2 if the terms conflict,
    4 if the clock ran out before any grid was found."""
    tuning = _tuning(max_candidates)
    if _is_festival(brief_path):
        if why:
            console.print("[red]--why probes a day; a festival is solved day by day[/red]")
            raise typer.Exit(code=1)
        _plan_festival(brief_path, out, html, time_limit, relax_terms, quiet, tuning)
        return
    if _is_week(brief_path):
        if why:
            console.print("[red]--why probes a day; run explain on one day of the week[/red]")
            raise typer.Exit(code=1)
        _plan_week(brief_path, out, html, time_limit, relax_terms, quiet, tuning)
        return
    brief = _load_brief(brief_path)
    start_from = _load_grid(hint) if hint else None
    grid = (
        relax(brief, time_limit_s=time_limit, tuning=tuning, hint=start_from)
        if relax_terms
        else solve(brief, time_limit_s=time_limit, tuning=tuning, hint=start_from)
    )
    if grid.status not in ("OPTIMAL", "FEASIBLE"):
        if grid.status == "INFEASIBLE":
            console.print(f"[red bold]INFEASIBLE[/red bold] — {explain(brief, grid)}")
            if not relax_terms:
                console.print("[dim]turnaround plan --relax drops terms until a grid exists[/dim]")
        else:
            console.print(f"[red bold]{grid.status}[/red bold] — no grid within {time_limit}s")
            _say_relaxed(brief, grid)  # what had already been given up when time ran out
            _exit_without_a_grid([grid.status], relax_terms, week=False)
        raise typer.Exit(code=2)
    if not quiet:
        _print_grid(brief, grid)
    _say_relaxed(brief, grid)
    _say_stats(grid)
    ok = _print_report(brief, grid) if not quiet else run_check(brief, grid).ok
    if why:
        probe_all(brief, grid, time_limit_s=min(time_limit, 10.0), budget_s=probe_budget)
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
    if _is_week(brief_path) or _is_festival(brief_path):
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
    if _is_week(brief_path) or _is_festival(brief_path):
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
            raise typer.Exit(code=OUT_OF_TIME)
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


def _delta_text(old: float, new: float) -> str:
    """`1,532 → 1,609 (+76)`; the arrow only when the number moved."""
    if abs(new - old) < 0.05:
        return f"{new:,.0f}"
    d = new - old
    colour = "blue" if d > 0 else "red"
    return f"{old:,.0f} → [bold]{new:,.0f}[/bold] [{colour}]({d:+,.0f})[/{colour}]"


def _print_diff(d: GridDiff, heading: str) -> None:
    """The re-plan as a table: what moved, what came, what went; then the titles whose
    count changed and the grids' claims in one line each."""
    t = Table(title=heading, show_lines=False)
    t.add_column("What", style="bold")
    t.add_column("Title")
    t.add_column("Was")
    t.add_column("Now")
    rows: list[tuple[int, str, str, str, str]] = []
    for m in d.moved:
        rows.append(
            (m.new.start, f"moved · {m.what}", m.title or m.film, m.old.key, m.new.key)
            if m.what != "length"
            else (
                m.new.start,
                "moved · length",
                m.title or m.film,
                f"{m.old.key} clear {fmt_time(m.old.clear)}",
                f"{m.new.key} clear {fmt_time(m.new.clear)}",
            )
        )
    for s in d.added:
        rows.append((s.start, "[blue]added[/blue]", s.film, "—", f"[blue]{s.key}[/blue]"))
    for s in d.removed:
        rows.append((s.start, "[red]removed[/red]", s.film, f"[strike]{s.key}[/strike]", "—"))
    titles = {t.film: t.title for t in d.titles if t.title}
    titles.update({m.film: m.title for m in d.moved if m.title})
    for _, what, film, was, now in sorted(rows, key=lambda r: (r[0], r[1])):
        t.add_row(what, titles.get(film, film), was, now)
    if not rows:
        t.add_row("[dim]no change[/dim]", "", "", "")
    console.print(t)
    if d.titles:
        console.print(
            "by title: "
            + " · ".join(f"{x.title or x.film} {x.old} → {x.new} ({x.delta:+d})" for x in d.titles)
        )
    tm = d.terms
    line = f"sessions {_delta_text(*d.sessions)}"
    if d.seats:
        line += f" · seats on offer {_delta_text(d.seats.old, d.seats.new)}"
    line += (
        f" · status {tm.status[0]} → {tm.status[1]}"
        if tm.status[0] != tm.status[1]
        else f" · {tm.status[1]}"
    )
    console.print(line)
    claims = f"objective {_delta_text(tm.objective.old, tm.objective.new)}"
    if tm.admissions:
        claims += f" · expected admissions {_delta_text(tm.admissions.old, tm.admissions.new)}"
    if tm.hold_paid.old or tm.hold_paid.new:
        claims += f" · paid to hold {_delta_text(tm.hold_paid.old, tm.hold_paid.new)}"
    if tm.clash_paid.old or tm.clash_paid.new:
        claims += f" · paid in clashes {_delta_text(tm.clash_paid.old, tm.clash_paid.new)}"
    console.print(claims)
    if tm.relaxed_added:
        console.print("[red]now given up:[/red] " + " · ".join(str(x) for x in tm.relaxed_added))
    if tm.relaxed_removed:
        console.print("[blue]held again:[/blue] " + " · ".join(str(x) for x in tm.relaxed_removed))


def _is_week_grid(path: Path) -> bool:
    head = json.loads(path.read_text())
    return isinstance(head, dict) and "grids" in head


@app.command("diff")
def diff_cmd(
    old_path: Annotated[Path, typer.Argument(help="The grid as it stands (JSON)")],
    new_path: Annotated[Path, typer.Argument(help="The re-planned grid (JSON)")],
    brief_path: Annotated[
        Path | None,
        typer.Option(
            "--brief",
            help="The brief both grids answer: names the titles, counts the seats, and "
            "is what the sheet needs",
        ),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the diff as JSON instead of the table")
    ] = False,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the diff JSON")] = None,
    html: Annotated[
        Path | None, typer.Option("--html", help="Write the re-plan sheet (needs --brief)")
    ] = None,
) -> None:
    """What changed between two grids of one day, or two weeks, or two festivals:
    sessions added, removed and moved (same title, new time or room), the seats and the
    show counts by title, and the grids' claims. The Thursday re-plan artefact. A week
    is diffed day by day by name, so a re-plan that drops a day reads as one."""
    if html and not brief_path:
        console.print("[red]--html needs --brief: the sheet is drawn on the brief[/red]")
        raise typer.Exit(code=1)
    if _is_week_grid(old_path) != _is_week_grid(new_path):
        console.print("[red]one of these is a week of grids and the other a day[/red]")
        raise typer.Exit(code=1)
    if _is_week_grid(old_path):
        old_w, new_w = _load_week_grid(old_path), _load_week_grid(new_path)
        week: WeekBrief | FestivalBrief | None = None
        briefs: dict[str, Brief] = {}
        if brief_path:
            week = (
                _load_festival(brief_path) if _is_festival(brief_path) else _load_week(brief_path)
            )
            briefs = {d.name: b for d, b in zip(week.days, week.briefs(), strict=True)}
        wd: WeekDiff = diff_week(old_w, new_w, briefs)
        if as_json:
            console.print_json(wd.model_dump_json())
        else:
            for d in wd.days:
                _print_diff(d, f"{d.day} · {d.summary}")
            console.print(f"[bold]{wd.house}[/bold] · {wd.summary}")
            if wd.held[0] != wd.held[1]:
                console.print(
                    f"holds: {', '.join(wd.held[0]) or 'none'} → {', '.join(wd.held[1]) or 'none'}"
                )
        if out:
            out.write_text(wd.model_dump_json(indent=2))
            console.print(f"diff → {out}")
        if html and week is not None:
            diffs = {d.day: d for d in wd.days if d.day}
            if isinstance(week, FestivalBrief):
                text = render_festival_html(week, new_w, check_festival(week, new_w), diffs=diffs)
            else:
                text = render_week_html(week, new_w, check_week(week, new_w), diffs=diffs)
            html.write_text(text)
            console.print(f"sheet → {html}")
        return
    old_g, new_g = _load_grid(old_path), _load_grid(new_path)
    brief = _load_brief(brief_path) if brief_path else None
    d = diff(old_g, new_g, brief)
    if as_json:
        console.print_json(d.model_dump_json())
    else:
        _print_diff(d, f"{d.house} · {d.date or 'the day'} · {d.summary}")
    if out:
        out.write_text(d.model_dump_json(indent=2))
        console.print(f"diff → {out}")
    if html and brief is not None:
        html.write_text(render_html(brief, new_g, run_check(brief, new_g), diff=d))
        console.print(f"sheet → {html}")


@app.command("check")
def check_cmd(
    brief_path: Annotated[Path, typer.Argument(help="Brief JSON")],
    grid_path: Annotated[Path, typer.Argument(help="Grid JSON")],
) -> None:
    """Verify a grid, or a week or a festival of them, against its brief, independently
    of the solver."""
    if _is_week(brief_path) or _is_festival(brief_path):
        week = _load_festival(brief_path) if _is_festival(brief_path) else _load_week(brief_path)
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


@app.command("import")
def import_cmd(
    csv_path: Annotated[
        Path,
        typer.Option(
            "--csv",
            help="A showtimes export: screen, title, start, runtime. Other columns "
            "(film, format, rating, capacity, preshow, clean, credits, date, day) are read "
            "when present and ignored otherwise",
        ),
    ],
    brief_path: Annotated[
        Path | None,
        typer.Option(
            "--brief",
            help="The house's brief to import against. Without it a brief skeleton is made "
            "from the CSV alone and written beside the grid",
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the grid here (default: <csv>.grid.json)"),
    ] = None,
    brief_out: Annotated[
        Path | None,
        typer.Option("--brief-out", help="Write the skeleton here (default: <csv>.brief.json)"),
    ] = None,
    day: Annotated[
        str | None,
        typer.Option("--day", help="The day to take from a week brief, or from a CSV of several"),
    ] = None,
    date: Annotated[
        str | None,
        typer.Option("--date", help="The grid's date, or the date to take from a CSV of several"),
    ] = None,
    house: Annotated[
        str | None, typer.Option("--house", help="The skeleton's house name (default: the CSV's)")
    ] = None,
    capacity: Annotated[
        int, typer.Option(help="Seats assumed per screen on a skeleton when the CSV does not say")
    ] = 100,
    preshow: Annotated[
        int, typer.Option(help="Preshow minutes assumed on a skeleton when the CSV does not say")
    ] = 20,
    clean: Annotated[
        int, typer.Option(help="Turnaround minutes assumed on a skeleton when the CSV does not say")
    ] = 20,
) -> None:
    """A plain showtimes CSV (screen, title, start, runtime) as a grid the checker can
    read — against the house's brief, or with a brief skeleton made from the CSV alone —
    so a hand-made grid can be checked before the solver is trusted with anything.
    The import never judges the grid; `turnaround check` does."""
    brief: Brief | None = None
    if brief_path is not None:
        if _is_week(brief_path) or _is_festival(brief_path):
            week: WeekBrief | FestivalBrief = (
                _load_festival(brief_path) if _is_festival(brief_path) else _load_week(brief_path)
            )
            names = [d.name for d in week.days]
            if day is None or day not in names:
                console.print(
                    f"[red]{brief_path} is a week — say which day to import against with "
                    f"--day ({', '.join(names)})[/red]"
                )
                raise typer.Exit(code=1)
            brief = week.day(week.day_index(day))
        else:
            brief = _load_brief(brief_path)
    try:
        brief, grid, notes = import_csv(
            csv_path.read_text(),
            brief=brief,
            house=house or csv_path.stem,
            day=day,
            date=date,
            capacity=capacity,
            preshow=preshow,
            clean=clean,
        )
    except (ValueError, ValidationError) as e:
        console.print(f"[red bold]{csv_path} is not a showtimes CSV the tool can take[/red bold]")
        lines = validation_sentences(e, None) if isinstance(e, ValidationError) else [str(e)]
        for line in lines:
            console.print(f"  [red]✗[/red] {line}")
        raise typer.Exit(code=1) from None
    screens = len({s.screen for s in grid.sessions})
    titles = len({s.film for s in grid.sessions})
    console.print(
        f"[bold]{brief.house}[/bold]"
        + (f" · {grid.date}" if grid.date else "")
        + f" · {len(grid.sessions)} sessions on {screens} screens · {titles} titles · "
        f"{grid.objective:,.0f} expected admissions by the checker's count"
    )
    for n in notes:
        console.print(f"  [yellow]·[/yellow] {n}")
    grid_path = out or csv_path.with_suffix(".grid.json")
    grid_path.write_text(grid.model_dump_json(indent=2))
    console.print(f"grid → {grid_path}")
    if brief_path is None:
        skeleton_path = brief_out or csv_path.with_suffix(".brief.json")
        skeleton_path.write_text(brief.model_dump_json(indent=2, exclude_none=True))
        console.print(f"brief skeleton → {skeleton_path}")
        brief_path = skeleton_path
    rep = run_check(brief, grid)
    green = sum(1 for c in rep.checks if c.ok)
    verdict = f"{green} of {len(rep.checks)} checks green"
    if rep.failures:
        verdict += (
            " · [red bold]"
            + "; ".join(
                f"{c.name}{' ' + brief.film(c.film).title if c.film else ''}: {c.evidence}"
                for c in rep.failures
            )
            + "[/red bold]"
        )
    console.print(verdict)
    console.print(f"[dim]turnaround check {brief_path} {grid_path} prints the proof[/dim]")


@app.command()
def export(
    brief_path: Annotated[Path, typer.Argument(help="Brief JSON, a day or a week")],
    grid_path: Annotated[Path, typer.Argument(help="Grid JSON, a day or a week")],
    ical: Annotated[
        bool, typer.Option("--ical", help="A calendar per screen: <grid>.screen-<id>.ics")
    ] = False,
    csv_: Annotated[
        bool, typer.Option("--csv", help="A flat CSV for signage: <grid>.sessions.csv")
    ] = False,
    json_: Annotated[
        bool, typer.Option("--json", help="JSON for a website: <grid>.sessions.json")
    ] = False,
    out_dir: Annotated[
        Path | None, typer.Option("--out-dir", help="Where to write (default: beside the grid)")
    ] = None,
) -> None:
    """A grid out: a calendar per screen, a flat CSV for signage, JSON for a website.
    With no format named, all three. A week grid goes out as one CSV and one JSON of
    seven days and one calendar per screen across the week."""
    days: list[Day]
    if _is_week(brief_path) or _is_festival(brief_path):
        week = _load_festival(brief_path) if _is_festival(brief_path) else _load_week(brief_path)
        wg = _load_week_grid(grid_path)
        days = [(d.name, b, g) for d, b, g in zip(week.days, week.briefs(), wg.grids, strict=True)]
    else:
        days = [(None, _load_brief(brief_path), _load_grid(grid_path))]
    if not (ical or csv_ or json_):
        ical = csv_ = json_ = True
    where = out_dir or grid_path.parent
    where.mkdir(parents=True, exist_ok=True)
    stem = grid_path.stem
    try:
        files: list[tuple[str, str, str]] = []
        if csv_:
            files.append(("csv", f"{stem}.sessions.csv", export_csv(days)))
        if json_:
            files.append(("json", f"{stem}.sessions.json", export_json_text(days)))
        if ical:
            files += [
                ("ical", f"{stem}.screen-{sid}.ics", export_ical(days, sid))
                for sid in screen_ids(days)
            ]
    except ValueError as e:
        console.print(f"  [red]✗[/red] {e}")
        raise typer.Exit(code=1) from None
    for kind, name, text in files:
        (where / name).write_text(text)
        console.print(f"{kind} → {where / name}")


@app.command()
def render(
    brief_path: Annotated[Path, typer.Argument()],
    grid_path: Annotated[Path, typer.Argument()],
    html: Annotated[Path, typer.Option("--html")],
) -> None:
    """Render an existing grid, or a week or a festival of grids, as the sheet."""
    if _is_festival(brief_path):
        fest = _load_festival(brief_path)
        wg = _load_week_grid(grid_path)
        html.write_text(render_festival_html(fest, wg, check_festival(fest, wg)))
        console.print(f"sheet → {html}")
        return
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
    if _is_festival(brief_path):
        fest = _load_festival(brief_path)
        wg = _load_week_grid(grid_path)
        html.write_text(render_festival_terms_html(fest, wg, check_festival(fest, wg)))
    elif _is_week(brief_path):
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
    if _is_festival(brief_path):
        fest = _load_festival(brief_path)
        console.print_json(
            json.dumps(
                {
                    "festival": fest.festival,
                    "days": [d.name for d in fest.days],
                    "venues": [v.label for v in fest.venues],
                    "films": len(fest.films),
                    "strands": fest.strands,
                    "screenings": sum(f.terms.screenings or 0 for f in fest.films),
                    "guests": sum(1 for f in fest.films if f.terms.guest),
                    "move_min": fest.policy.move_min,
                    "clash_penalty": fest.policy.clash_penalty,
                }
            )
        )
        return
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
