"""The independent checker.

Reads a brief and a grid and re-verifies every hard constraint without the
solver. This is the proof: a grid is only as good as the checks it passes, and
the checks must not share code with the thing that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Brief, Grid, Terms, fmt_time, parse_time

RELAXABLE = ("min_shows", "max_shows", "prime_shows", "exclusive_screen")


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
    return r
