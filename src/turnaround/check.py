"""The independent checker.

Reads a brief and a grid and re-verifies every hard constraint without the
solver. This is the proof: a grid is only as good as the checks it passes, and
the checks must not share code with the thing that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Brief, Daypart, Grid, Session, Terms, WeekBrief, WeekGrid, fmt_time, parse_time

RELAXABLE = ("min_shows", "max_shows", "prime_shows", "exclusive_screen")


@dataclass
class TitleAdmissions:
    """One title's day in seats: offered, expected to come, expected to sell, turned away."""

    film: str
    shows: int
    offered: int
    demand: float  # who would come, capacity ignored
    admissions: float  # who gets a seat: min(demand, capacity), session by session

    @property
    def turned_away(self) -> float:
        return self.demand - self.admissions


def admissions(brief: Brief, grid: Grid) -> list[TitleAdmissions]:
    """Re-count expected admissions from the brief and the grid alone. Within a title's
    sessions in one daypart the first draws the most and each further one decays, and
    the biggest room takes the first rank: a room can only sell the seats it has, so
    no other assignment sells more. Written here without the solver."""
    out: list[TitleAdmissions] = []
    for f in brief.films:
        mine = [s for s in grid.sessions if s.film == f.id]
        by_dp: dict[str | None, list[tuple[Daypart | None, Session]]] = {}
        for s in mine:
            dp = brief.policy.daypart_at(s.start)
            by_dp.setdefault(dp.name if dp else None, []).append((dp, s))
        demand = 0.0
        sold = 0.0
        for group in by_dp.values():
            group.sort(key=lambda x: -brief.screen(x[1].screen).capacity)
            for rank, (dp, s) in enumerate(group):
                e = brief.expected(f, dp, rank)
                demand += e
                sold += min(float(brief.screen(s.screen).capacity), e)
        out.append(
            TitleAdmissions(
                film=f.id,
                shows=len(mine),
                offered=sum(brief.screen(s.screen).capacity for s in mine),
                demand=demand,
                admissions=sold,
            )
        )
    return out


def term_is_set(t: Terms, name: str) -> bool:
    """Does this film's booking actually carry the named term?"""
    v = getattr(t, name)
    return v is not None if name == "max_shows" else bool(v)


@dataclass
class Check:
    name: str
    ok: bool
    evidence: str
    film: str | None = None
    relaxed: bool = False  # the term fails, and the grid says so on its face


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Every check holds, or fails only where the grid declares a relaxation."""
        return all(c.ok or c.relaxed for c in self.checks)

    @property
    def clean(self) -> bool:
        """Every check holds and nothing was relaxed."""
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.relaxed]

    @property
    def relaxations(self) -> list[Check]:
        return [c for c in self.checks if c.relaxed]

    def add(
        self, name: str, ok: bool, evidence: str, film: str | None = None, relaxed: bool = False
    ) -> None:
        self.checks.append(Check(name, ok, evidence, film, relaxed and not ok))


def check(brief: Brief, grid: Grid) -> Report:
    r = Report()
    p = brief.policy
    declared = {(t.film, t.term) for t in grid.relaxed}

    # A declared relaxation must name a real film and a term that film actually carries.
    film_ids = {f.id for f in brief.films}
    bogus = [
        t
        for t in grid.relaxed
        if t.film not in film_ids
        or t.term not in RELAXABLE
        or not term_is_set(brief.film(t.film).terms, t.term)
    ]
    r.add(
        "relaxed",
        not bogus,
        f"{len(grid.relaxed)} declared"
        + (f", {len(bogus)} name no such term" if bogus else "")
        + ("" if grid.relaxed else " — every term held as written"),
    )

    # References resolve.
    bad = [s for s in grid.sessions if s.screen not in {x.id for x in brief.screens}] + [
        s for s in grid.sessions if s.film not in {x.id for x in brief.films}
    ]
    r.add("references", not bad, f"{len(grid.sessions)} sessions, {len(bad)} dangling")
    if bad:
        return r

    # Timing arithmetic is internally consistent.
    wrong = []
    for s in grid.sessions:
        scr = brief.screen(s.screen)
        f = brief.film(s.film)
        preshow_ok = s.feature_start == s.start + p.preshow_min
        runtime_ok = s.feature_end == s.feature_start + f.runtime_min
        clean_ok = s.clear == s.feature_end + brief.clean_for(scr)
        if not (preshow_ok and runtime_ok and clean_ok):
            wrong.append(s)
    r.add("timing", not wrong, f"{len(wrong)} sessions with inconsistent preshow/runtime/clean")

    # Hours.
    early = [s for s in grid.sessions if s.start < p.open_min]
    late = [s for s in grid.sessions if s.start > p.last_start_min]
    r.add(
        "hours",
        not early and not late,
        f"open {p.open} · last start {p.last_start} · {len(early)} early · {len(late)} late",
    )

    # Slot alignment.
    off = [s for s in grid.sessions if (s.start - p.open_min) % p.slot_min != 0]
    r.add("slot-grid", not off, f"{p.slot_min}-minute grid, {len(off)} off-grid")

    # Format and screen eligibility.
    ineligible = [
        s for s in grid.sessions if not brief.can_play(brief.screen(s.screen), brief.film(s.film))
    ]
    r.add(
        "eligibility",
        not ineligible,
        f"{len(ineligible)} sessions on a screen that cannot play the film",
    )

    # No overlap per screen, turnaround included.
    overlaps: list[str] = []
    for sid, sessions in grid.by_screen().items():
        for a, b in zip(sessions, sessions[1:], strict=False):
            if b.start < a.clear:
                overlaps.append(
                    f"{sid}: {a.film}@{fmt_time(a.start)} clears {fmt_time(a.clear)} "
                    f"but {b.film} starts {fmt_time(b.start)}"
                )
    r.add("turnaround", not overlaps, "; ".join(overlaps) or "no screen double-booked")

    # Stagger house-wide.
    starts = sorted(s.start for s in grid.sessions)
    crush = [(a, b) for a, b in zip(starts, starts[1:], strict=False) if 0 <= b - a < p.stagger_min]
    r.add(
        "stagger",
        not crush,
        f"min gap {p.stagger_min} min; "
        + (
            f"{len(crush)} pairs too close, first {fmt_time(crush[0][0])}/{fmt_time(crush[0][1])}"
            if crush
            else "every start clears the lobby"
        ),
    )

    # Terms per film.
    by_film = grid.by_film()
    for f in brief.films:
        mine = by_film.get(f.id, [])
        t = f.terms
        n = len(mine)
        gave_up = {name for (fid, name) in declared if fid == f.id}
        if t.min_shows:
            r.add(
                "min_shows", n >= t.min_shows, f"{n} ≥ {t.min_shows}", f.id, "min_shows" in gave_up
            )
        if t.max_shows is not None:
            r.add(
                "max_shows", n <= t.max_shows, f"{n} ≤ {t.max_shows}", f.id, "max_shows" in gave_up
            )
        if t.prime_shows:
            pn = sum(1 for s in mine if p.is_prime(s.start))
            r.add(
                "prime_shows",
                pn >= t.prime_shows,
                f"{pn} ≥ {t.prime_shows} in {p.prime_start}–{p.prime_end}",
                f.id,
                "prime_shows" in gave_up,
            )
        if t.earliest_start:
            lo = parse_time(t.earliest_start)
            e = [s for s in mine if s.start < lo]
            r.add("earliest_start", not e, f"{len(e)} before {t.earliest_start}", f.id)
        if t.latest_start:
            hi = parse_time(t.latest_start)
            l_ = [s for s in mine if s.start > hi]
            r.add("latest_start", not l_, f"{len(l_)} after {t.latest_start}", f.id)
        if t.exclusive_screen:
            owned = [
                sid
                for sid, ss in grid.by_screen().items()
                if ss and all(s.film == f.id for s in ss)
            ]
            r.add(
                "exclusive_screen",
                bool(owned),
                f"own screen: {', '.join(owned) or 'none'}",
                f.id,
                "exclusive_screen" in gave_up,
            )

    # The objective, re-counted. The solver claims expected admissions; count them again
    # from the brief and the sessions, and hold the claim to within a cent a session.
    rows = admissions(brief, grid)
    sold = sum(x.admissions for x in rows)
    away = sum(x.turned_away for x in rows)
    tol = 0.01 * max(len(grid.sessions), 1) + 1e-6
    tail = f"{sold:,.1f} re-counted · {away:,.0f} turned away at capacity"
    if grid.admissions is None:
        r.add("admissions", True, "unclaimed · " + tail)
    else:
        r.add(
            "admissions",
            abs(grid.admissions - sold) <= tol,
            f"{grid.admissions:,.1f} claimed · " + tail,
        )
        net = grid.admissions - grid.hold_paid
        r.add(
            "objective",
            abs(grid.objective - net) <= 0.01,
            f"{grid.objective:,.1f} = {grid.admissions:,.1f} admissions"
            + (f" − {grid.hold_paid:,.0f} hold penalty" if grid.hold_paid else ""),
        )
    return r


def starts_of(grid: Grid, film_id: str) -> frozenset[int]:
    """The set of start times a title has on this grid, screens ignored."""
    return frozenset(s.start for s in grid.sessions if s.film == film_id)


def held_titles(week: WeekBrief, wg: WeekGrid) -> list[str]:
    """Film ids whose start times are identical on every hold day that has a grid.
    A day that did not solve is left out; if fewer than two hold days solved,
    nothing can be said to hold and the list is empty."""
    solved = [
        wg.grids[i]
        for i in week.hold_indices
        if i < len(wg.grids) and wg.grids[i].status in ("OPTIMAL", "FEASIBLE")
    ]
    if len(solved) < 2:
        return []
    out = []
    for f in week.films:
        sets = {starts_of(g, f.id) for g in solved}
        if len(sets) == 1:
            out.append(f.id)
    return out


@dataclass
class WeekReport:
    """One report per day, plus the checks that only make sense across the week."""

    days: list[str]
    reports: list[Report]
    week: Report = field(default_factory=Report)

    @property
    def ok(self) -> bool:
        return self.week.ok and all(r.ok for r in self.reports)

    @property
    def clean(self) -> bool:
        return self.week.clean and all(r.clean for r in self.reports)

    @property
    def failures(self) -> list[tuple[str, Check]]:
        out = [("week", c) for c in self.week.failures]
        for d, r in zip(self.days, self.reports, strict=True):
            out += [(d, c) for c in r.failures]
        return out


def check_week(week: WeekBrief, wg: WeekGrid) -> WeekReport:
    """Every day against its own unfolded brief, then the week's own claims:
    the grids line up with the days, and the titles the grid says held their
    times really did."""
    names = [d.name for d in week.days]
    w = Report()
    w.add(
        "days",
        wg.days == names and len(wg.grids) == len(names),
        f"{len(wg.grids)} grids for {len(names)} days"
        + ("" if wg.days == names else f"; grid names {wg.days}, brief names {names}"),
    )
    reports = [
        check(week.day(i), wg.grids[i]) if i < len(wg.grids) else Report()
        for i in range(len(week.days))
    ]
    truly = sorted(held_titles(week, wg))
    claimed = sorted(wg.held)
    run = "/".join(d for d in names if d in week.hold_days)
    w.add(
        "held",
        claimed == truly,
        f"{len(truly)} of {len(week.films)} titles keep their starts on {run}"
        + ("" if claimed == truly else f"; the grid claims {claimed}, found {truly}"),
    )
    # The hold penalty each day says it paid, re-derived: nothing before the anchor, and
    # after it `hold_penalty` per title whose starts differ from the anchor's.
    solved = [
        i
        for i in week.hold_indices
        if i < len(wg.grids) and wg.grids[i].status in ("OPTIMAL", "FEASIBLE")
    ]
    anchor = solved[0] if solved else None
    owed = 0.0
    wrong: list[str] = []
    for i, g in enumerate(wg.grids):
        due = 0.0
        if anchor is not None and i in solved and i > anchor:
            moved = sum(
                1 for f in week.films if starts_of(g, f.id) != starts_of(wg.grids[anchor], f.id)
            )
            due = week.hold_penalty * moved
        owed += due
        if abs(g.hold_paid - due) > 0.01:
            wrong.append(f"{names[i]} paid {g.hold_paid:,.0f}, owed {due:,.0f}")
    w.add(
        "hold_paid",
        not wrong,
        f"{owed:,.0f} admissions paid to hold times" + ("; " + "; ".join(wrong) if wrong else ""),
    )
    return WeekReport(days=names, reports=reports, week=w)
