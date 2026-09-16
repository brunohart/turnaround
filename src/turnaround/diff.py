"""The diff: two grids of the same day, and what changed between them.

A re-plan is the Thursday ritual: the grid pinned in the booth on Wednesday against
the one the solver made after a print arrived late or a distributor rang. The diff
reads the two grids alone — no brief, no solver, no checker — and says which
sessions were **added**, which **removed**, which **moved** (the same title, a new
time or a new room), what that did to the seats on offer and the show counts by
title, and what the grid's own claims (objective, admissions, the hold and clash
penalties, the terms given up, the status) did.

A diff is a document, not a judgement: it is symmetric (`invert(diff(a, b))` is
`diff(b, a)`) and it composes (`apply(a, diff(a, b))` is `b`'s schedule and claims),
which is what the tests hold it to. The solver's account of itself (`stats`,
`solve_seconds`, the probe's `forced`) is not part of a schedule and a diff does not
carry it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .model import Brief, Grid, Session, TermRef, WeekGrid, fmt_time

# The fields of a Session that make it the session it is. `forced` is the solver's
# claim about a session, not the session.
_SESSION_FIELDS = ("screen", "film", "start", "feature_start", "feature_end", "clear")


def session_key(s: Session) -> tuple[Any, ...]:
    return tuple(getattr(s, f) for f in _SESSION_FIELDS)


def _bare(s: Session) -> Session:
    return s.model_copy(update={"forced": None})


class Move(BaseModel):
    """One session of a title that is still on the grid, but not where it was."""

    model_config = ConfigDict(extra="forbid")

    film: str
    title: str | None = None
    old: Session
    new: Session

    @property
    def what(self) -> str:
        """`time`, `room`, `room and time`, or `length` (same room and start, a different
        feature end or clear: the brief's runtime, preshow or turnaround changed)."""
        room = self.old.screen != self.new.screen
        time = self.old.start != self.new.start
        if room and time:
            return "room and time"
        if room:
            return "room"
        if time:
            return "time"
        return "length"

    @property
    def sentence(self) -> str:
        if self.what == "length":
            return f"{self.old.key} · clear {fmt_time(self.old.clear)} → {fmt_time(self.new.clear)}"
        return f"{self.old.key} → {self.new.key}"


class Delta(BaseModel):
    """A number as it was and as it is."""

    model_config = ConfigDict(extra="forbid")

    old: float
    new: float

    @property
    def delta(self) -> float:
        return self.new - self.old


class TitleDelta(BaseModel):
    """Shows of one title, before and after."""

    model_config = ConfigDict(extra="forbid")

    film: str
    title: str | None = None
    old: int
    new: int

    @property
    def delta(self) -> int:
        return self.new - self.old


class TermsDelta(BaseModel):
    """What the two grids claim: status, the objective and what it is made of, and the
    terms each was allowed to give up. `relaxed_added` are terms the new grid gave up
    that the old held; `relaxed_removed` the other way."""

    model_config = ConfigDict(extra="forbid")

    status: tuple[str, str]
    objective: Delta
    admissions: Delta | None = Field(
        default=None, description="None when either grid was not solved (imported)"
    )
    hold_paid: Delta
    clash_paid: Delta
    relaxed_added: list[TermRef] = Field(default_factory=list)
    relaxed_removed: list[TermRef] = Field(default_factory=list)


class GridDiff(BaseModel):
    """Everything that changed between two grids of one day."""

    model_config = ConfigDict(extra="forbid")

    house: str
    date: str | None = None
    day: str | None = Field(default=None, description="The day's name inside a week diff")
    added: list[Session]
    removed: list[Session]
    moved: list[Move]
    unchanged: int
    sessions: tuple[int, int]
    seats: Delta | None = Field(
        default=None, description="Seats on offer, before and after; needs the brief"
    )
    titles: list[TitleDelta] = Field(
        default_factory=list, description="Titles whose show count changed"
    )
    terms: TermsDelta

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.moved)

    @property
    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        if self.moved:
            parts.append(f"{len(self.moved)} moved")
        if not parts:
            return "no change"
        return " · ".join(parts) + f" · {self.unchanged} unchanged"

    def moved_from(self, s: Session) -> Session | None:
        """Where a session of the new grid was on the old one, if it moved."""
        for m in self.moved:
            if session_key(m.new) == session_key(s):
                return m.old
        return None

    def is_added(self, s: Session) -> bool:
        k = session_key(s)
        return any(session_key(a) == k for a in self.added)


def _pair_key(o: Session, n: Session) -> tuple[Any, ...]:
    """A pair's cost, symmetric in old and new: how far the start moved, whether the
    room changed, then the pair itself so ties break the same way read either way."""
    return (
        abs(o.start - n.start),
        o.screen != n.screen,
        min(o.start, n.start),
        max(o.start, n.start),
        min(o.screen, n.screen),
        max(o.screen, n.screen),
    )


_EXACT_UP_TO = 7


def _pair(old: list[Session], new: list[Session]) -> list[tuple[Session, Session]]:
    """Pair the old sessions of a title with the new ones so the moves read as short as
    they can: the matching whose starts moved least in total, room changes breaking a
    tie, exact up to seven sessions a side (every matching tried) and greedy — the closest
    pair first — beyond that. Symmetric in old and new, so diff(b, a) pairs what
    diff(a, b) pairs."""
    if not old or not new:
        return []
    if max(len(old), len(new)) <= _EXACT_UP_TO:
        from itertools import combinations, permutations

        small, big = (old, new) if len(old) <= len(new) else (new, old)
        best: tuple[Any, ...] | None = None
        best_pairs: list[tuple[Session, Session]] = []
        for chosen in combinations(big, len(small)):
            for perm in permutations(chosen):
                pairs = list(zip(small, perm, strict=True))
                keys = sorted(_pair_key(a, b) for a, b in pairs)
                cost = (
                    sum(k[0] for k in keys),
                    sum(1 for k in keys if k[1]),
                    keys,
                )
                if best is None or cost < best:
                    best = cost
                    best_pairs = pairs
        if old is not small:
            best_pairs = [(o, n) for n, o in best_pairs]
        return sorted(best_pairs, key=lambda p: _pair_key(*p))
    scored = sorted(((_pair_key(o, n), o, n) for o in old for n in new), key=lambda p: p[0])
    taken_old: set[int] = set()
    taken_new: set[int] = set()
    out = []
    for _, o, n in scored:
        if id(o) in taken_old or id(n) in taken_new:
            continue
        taken_old.add(id(o))
        taken_new.add(id(n))
        out.append((o, n))
    return out


def diff(old: Grid, new: Grid, brief: Brief | None = None, day: str | None = None) -> GridDiff:
    """What changed from `old` to `new`. With the brief, titles are named and the seats
    on offer are counted; without it, film ids and no seats."""
    titles = {f.id: f.title for f in brief.films} if brief else {}
    old_by: dict[str, list[Session]] = {}
    new_by: dict[str, list[Session]] = {}
    unchanged = 0
    old_keys = {session_key(s) for s in old.sessions}
    new_keys = {session_key(s) for s in new.sessions}
    for s in old.sessions:
        if session_key(s) in new_keys:
            unchanged += 1
        else:
            old_by.setdefault(s.film, []).append(s)
    for s in new.sessions:
        if session_key(s) not in old_keys:
            new_by.setdefault(s.film, []).append(s)
    added: list[Session] = []
    removed: list[Session] = []
    moved: list[Move] = []
    for film in sorted(set(old_by) | set(new_by)):
        o = sorted(old_by.get(film, []), key=lambda s: (s.start, s.screen))
        n = sorted(new_by.get(film, []), key=lambda s: (s.start, s.screen))
        pairs = _pair(o, n)
        paired_old = {id(p[0]) for p in pairs}
        paired_new = {id(p[1]) for p in pairs}
        moved.extend(
            Move(film=film, title=titles.get(film), old=_bare(a), new=_bare(b)) for a, b in pairs
        )
        removed.extend(_bare(s) for s in o if id(s) not in paired_old)
        added.extend(_bare(s) for s in n if id(s) not in paired_new)
    moved.sort(key=lambda m: (m.new.start, m.new.screen))
    added.sort(key=lambda s: (s.start, s.screen))
    removed.sort(key=lambda s: (s.start, s.screen))
    counts_old: dict[str, int] = {}
    counts_new: dict[str, int] = {}
    for s in old.sessions:
        counts_old[s.film] = counts_old.get(s.film, 0) + 1
    for s in new.sessions:
        counts_new[s.film] = counts_new.get(s.film, 0) + 1
    title_deltas = [
        TitleDelta(film=f, title=titles.get(f), old=counts_old.get(f, 0), new=counts_new.get(f, 0))
        for f in sorted(set(counts_old) | set(counts_new))
        if counts_old.get(f, 0) != counts_new.get(f, 0)
    ]
    seats = None
    if brief:
        seats = Delta(
            old=sum(brief.screen(s.screen).capacity for s in old.sessions),
            new=sum(brief.screen(s.screen).capacity for s in new.sessions),
        )
    old_relaxed = set(old.relaxed)
    new_relaxed = set(new.relaxed)
    terms = TermsDelta(
        status=(old.status, new.status),
        objective=Delta(old=old.objective, new=new.objective),
        admissions=(
            Delta(old=old.admissions, new=new.admissions)
            if old.admissions is not None and new.admissions is not None
            else None
        ),
        hold_paid=Delta(old=old.hold_paid, new=new.hold_paid),
        clash_paid=Delta(old=old.clash_paid, new=new.clash_paid),
        relaxed_added=sorted(new_relaxed - old_relaxed, key=str),
        relaxed_removed=sorted(old_relaxed - new_relaxed, key=str),
    )
    return GridDiff(
        house=new.house,
        date=new.date or old.date,
        day=day,
        added=added,
        removed=removed,
        moved=moved,
        unchanged=unchanged,
        sessions=(len(old.sessions), len(new.sessions)),
        seats=seats,
        titles=title_deltas,
        terms=terms,
    )


def invert(d: GridDiff) -> GridDiff:
    """The same diff read the other way: diff(b, a) from diff(a, b)."""
    return GridDiff(
        house=d.house,
        date=d.date,
        day=d.day,
        added=list(d.removed),
        removed=list(d.added),
        moved=sorted(
            (Move(film=m.film, title=m.title, old=m.new, new=m.old) for m in d.moved),
            key=lambda m: (m.new.start, m.new.screen),
        ),
        unchanged=d.unchanged,
        sessions=(d.sessions[1], d.sessions[0]),
        seats=Delta(old=d.seats.new, new=d.seats.old) if d.seats else None,
        titles=[TitleDelta(film=t.film, title=t.title, old=t.new, new=t.old) for t in d.titles],
        terms=TermsDelta(
            status=(d.terms.status[1], d.terms.status[0]),
            objective=Delta(old=d.terms.objective.new, new=d.terms.objective.old),
            admissions=(
                Delta(old=d.terms.admissions.new, new=d.terms.admissions.old)
                if d.terms.admissions
                else None
            ),
            hold_paid=Delta(old=d.terms.hold_paid.new, new=d.terms.hold_paid.old),
            clash_paid=Delta(old=d.terms.clash_paid.new, new=d.terms.clash_paid.old),
            relaxed_added=list(d.terms.relaxed_removed),
            relaxed_removed=list(d.terms.relaxed_added),
        ),
    )


def apply(grid: Grid, d: GridDiff) -> Grid:
    """The grid with the diff applied: the schedule and the claims of the grid the diff
    was taken against. Raises if the diff does not fit (a session it removes or moves
    is not there), because a diff of one Thursday says nothing about another."""
    keys = {session_key(s): s for s in grid.sessions}
    for s in list(d.removed) + [m.old for m in d.moved]:
        if session_key(s) not in keys:
            raise ValueError(
                f"the diff removes {s.key} ({s.film}) and the grid has no such session"
            )
        del keys[session_key(s)]
    for s in list(d.added) + [m.new for m in d.moved]:
        if session_key(s) in keys:
            raise ValueError(f"the diff adds {s.key} ({s.film}) and the grid already has it")
        keys[session_key(s)] = s
    sessions = sorted(keys.values(), key=lambda s: (s.screen, s.start, s.film))
    relaxed = [t for t in grid.relaxed if t not in set(d.terms.relaxed_removed)]
    relaxed += [t for t in d.terms.relaxed_added if t not in relaxed]
    return grid.model_copy(
        update={
            "sessions": sessions,
            "status": d.terms.status[1],
            "objective": d.terms.objective.new,
            "admissions": d.terms.admissions.new if d.terms.admissions else grid.admissions,
            "hold_paid": d.terms.hold_paid.new,
            "clash_paid": d.terms.clash_paid.new,
            "relaxed": relaxed,
            "stats": None,
            "conflict": [],
        }
    )


def schedule(grid: Grid) -> list[tuple[Any, ...]]:
    """A grid as the schedule it is: the sessions, sorted, without the solver's claims.
    What `apply` promises to reproduce."""
    return sorted(session_key(s) for s in grid.sessions)


class WeekDiff(BaseModel):
    """A week (or a festival) of diffs, day by day *by name*: a re-plan may drop a day
    or add one, and the days are matched by what the booth calls them, not by position."""

    model_config = ConfigDict(extra="forbid")

    house: str
    days: list[GridDiff]
    days_added: list[str] = Field(default_factory=list)
    days_removed: list[str] = Field(default_factory=list)
    held: tuple[list[str], list[str]] = Field(
        default=([], []), description="Titles that held their times, before and after"
    )

    @property
    def summary(self) -> str:
        added = sum(len(d.added) for d in self.days)
        removed = sum(len(d.removed) for d in self.days)
        moved = sum(len(d.moved) for d in self.days)
        parts = []
        if added:
            parts.append(f"{added} added")
        if removed:
            parts.append(f"{removed} removed")
        if moved:
            parts.append(f"{moved} moved")
        if self.days_added:
            parts.append(f"days added {', '.join(self.days_added)}")
        if self.days_removed:
            parts.append(f"days dropped {', '.join(self.days_removed)}")
        return " · ".join(parts) if parts else "no change"

    def day(self, name: str) -> GridDiff | None:
        for d in self.days:
            if d.day == name:
                return d
        return None


def _empty_like(g: Grid) -> Grid:
    return g.model_copy(
        update={
            "sessions": [],
            "objective": 0.0,
            "admissions": 0.0 if g.admissions is not None else None,
            "hold_paid": 0.0,
            "clash_paid": 0.0,
            "relaxed": [],
            "status": "ABSENT",
        }
    )


def diff_week(old: WeekGrid, new: WeekGrid, briefs: dict[str, Brief] | None = None) -> WeekDiff:
    """Day by day, by name. A day only one side has is diffed against an empty day with
    status ABSENT, so its sessions read as all added or all removed."""
    days = []
    old_names = list(old.days)
    new_names = list(new.days)
    for name in new_names:
        g_new = new.grid(name)
        g_old = old.grid(name) if name in old_names else _empty_like(g_new)
        days.append(diff(g_old, g_new, (briefs or {}).get(name), day=name))
    for name in old_names:
        if name not in new_names:
            g_old = old.grid(name)
            days.append(diff(g_old, _empty_like(g_old), (briefs or {}).get(name), day=name))
    return WeekDiff(
        house=new.house,
        days=days,
        days_added=[n for n in new_names if n not in old_names],
        days_removed=[n for n in old_names if n not in new_names],
        held=(list(old.held), list(new.held)),
    )
