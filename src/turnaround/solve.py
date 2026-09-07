"""The CP-SAT model.

One boolean per (screen, film, start slot). An optional interval per boolean
carries the block the session would occupy; NoOverlap per screen keeps the
turnaround honest. Distributor terms are linear constraints over those
booleans. The objective is weighted seats on offer: each session earns
film.weight x daypart weight x screen capacity, so the solver puts the film
people want in the big room at the hour they want it.

The solver never silently relaxes a term. If the terms cannot all be met the
status is INFEASIBLE and the grid names a minimal set of terms that cannot
hold together. Every term is guarded by an assumption literal; on INFEASIBLE
the solver's unsat core gives the culprits, and a deletion pass shrinks the
core so nothing is blamed that is not needed for the contradiction.

Relaxation is a separate, explicit call. It drops one term at a time from the
conflict, in a fixed order, until a grid exists, and records what was given up
on the grid itself (ADR-002).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .model import Brief, Film, Grid, Session, TermRef, parse_time

# Relaxation order: the term with the smallest key goes first.
# exclusive_screen is always last; otherwise the lightest film first,
# and within a film prime_shows before max_shows before min_shows.
_TERM_RANK = {"prime_shows": 0, "max_shows": 1, "min_shows": 2, "exclusive_screen": 3}


@dataclass(frozen=True)
class Candidate:
    screen: str
    film: str
    start: int
    block: int  # preshow + runtime + clean
    prime: bool
    value: float


def candidates(brief: Brief) -> list[Candidate]:
    """Every (screen, film, start) the terms and the house allow."""
    p = brief.policy
    out: list[Candidate] = []
    for scr in brief.screens:
        for f in brief.films:
            if not brief.can_play(scr, f):
                continue
            lo = p.open_min
            hi = p.last_start_min
            t = f.terms
            if t.earliest_start:
                lo = max(lo, parse_time(t.earliest_start))
            if t.latest_start:
                hi = min(hi, parse_time(t.latest_start))
            block = brief.block_len(scr, f)
            # Align to the slot grid from opening time.
            first = lo + (-(lo - p.open_min) % p.slot_min)
            for start in range(first, hi + 1, p.slot_min):
                dp = p.daypart_at(start)
                w = dp.weight if dp else 0.5
                if f.daypart_weights and dp and dp.name in f.daypart_weights:
                    w *= f.daypart_weights[dp.name]
                value = f.weight * w * scr.capacity + p.fill_bonus * scr.capacity
                out.append(
                    Candidate(
                        screen=scr.id,
                        film=f.id,
                        start=start,
                        block=block,
                        prime=p.is_prime(start),
                        value=value,
                    )
                )
    return out


def terms_of(film: Film) -> list[TermRef]:
    """The relaxable terms this film's booking carries, as the solver names them."""
    t = film.terms
    out: list[TermRef] = []
    if t.min_shows > 0:
        out.append(TermRef(film=film.id, term="min_shows", value=str(t.min_shows)))
    if t.max_shows is not None:
        out.append(TermRef(film=film.id, term="max_shows", value=str(t.max_shows)))
    if t.prime_shows > 0:
        out.append(TermRef(film=film.id, term="prime_shows", value=str(t.prime_shows)))
    if t.exclusive_screen:
        out.append(TermRef(film=film.id, term="exclusive_screen"))
    return out


@dataclass
class _Model:
    m: cp_model.CpModel
    cands: list[Candidate]
    x: dict[Candidate, cp_model.IntVar]
    assumptions: dict[TermRef, cp_model.IntVar] = field(default_factory=dict)

    def guard(self, ref: TermRef) -> cp_model.IntVar:
        a = self.assumptions.get(ref)
        if a is None:
            a = self.m.new_bool_var(f"assume[{ref.film},{ref.term}]")
            self.assumptions[ref] = a
        return a


def _build(
    brief: Brief,
    dropped: frozenset[tuple[str, str]] = frozenset(),
    *,
    feasibility_only: bool = False,
) -> _Model:
    """The model. Terms in `dropped` are not enforced; every other term is guarded.
    A feasibility-only model has no objective: a probe stops at the first grid it finds."""
    p = brief.policy
    cands = candidates(brief)
    m = cp_model.CpModel()
    mdl = _Model(m=m, cands=cands, x={})

    intervals_by_screen: dict[str, list[cp_model.IntervalVar]] = {s.id: [] for s in brief.screens}
    for c in cands:
        v = m.new_bool_var(f"x[{c.screen},{c.film},{c.start}]")
        mdl.x[c] = v
        iv = m.new_optional_interval_var(
            c.start, c.block, c.start + c.block, v, f"iv[{c.screen},{c.film},{c.start}]"
        )
        intervals_by_screen[c.screen].append(iv)

    # One thing on a screen at a time, turnaround included in the block.
    for ivs in intervals_by_screen.values():
        if ivs:
            m.add_no_overlap(ivs)

    # Redundant but sharp: the blocks on a screen cannot outlast the day. NoOverlap
    # implies this, but stating it as a sum lets the solver prove "too many shows for
    # the hours" in one step instead of by search.
    for scr in brief.screens:
        mine_here = [c for c in cands if c.screen == scr.id]
        if mine_here:
            day_len = p.last_start_min + max(c.block for c in mine_here) - p.open_min
            m.add(sum(c.block * mdl.x[c] for c in mine_here) <= day_len)

    # Stagger: within any window of stagger_min, at most one start house-wide.
    if p.stagger_min > 0:
        starts = sorted({c.start for c in cands})
        by_start: dict[int, list[cp_model.IntVar]] = {}
        for c in cands:
            by_start.setdefault(c.start, []).append(mdl.x[c])
        for s0 in starts:
            window = [v for s in starts if s0 <= s < s0 + p.stagger_min for v in by_start[s]]
            if len(window) > 1:
                m.add(sum(window) <= 1)

    # Distributor terms, each under its own assumption literal.
    for f in brief.films:
        mine = [c for c in cands if c.film == f.id]
        vs = [mdl.x[c] for c in mine]
        t = f.terms
        for ref in terms_of(f):
            if (ref.film, ref.term) in dropped:
                continue
            a = mdl.guard(ref)
            if ref.term == "min_shows":
                if vs:
                    m.add(sum(vs) >= t.min_shows).only_enforce_if(a)
                else:  # no screen can play it: the term is false on its own
                    m.add(a == 0)
            elif ref.term == "max_shows" and t.max_shows is not None:
                if vs:
                    m.add(sum(vs) <= t.max_shows).only_enforce_if(a)
            elif ref.term == "prime_shows":
                pv = [mdl.x[c] for c in mine if c.prime]
                if pv:
                    m.add(sum(pv) >= t.prime_shows).only_enforce_if(a)
                else:
                    m.add(a == 0)
            elif ref.term == "exclusive_screen":
                # y[s] = 1 means screen s plays only this film today.
                ys = []
                for scr in brief.screens:
                    if not brief.can_play(scr, f):
                        continue
                    y = m.new_bool_var(f"excl[{scr.id},{f.id}]")
                    ys.append(y)
                    for c in cands:
                        if c.screen == scr.id and c.film != f.id:
                            m.add_implication(y, mdl.x[c].negated())
                    # An exclusive screen must actually carry the film.
                    own = [mdl.x[c] for c in mine if c.screen == scr.id]
                    if own:
                        m.add(sum(own) >= 1).only_enforce_if(y)
                    else:
                        m.add(y == 0)
                if ys:
                    m.add(sum(ys) >= 1).only_enforce_if(a)
                else:
                    m.add(a == 0)

    # Objective: weighted seats on offer. Scale to integers for CP-SAT.
    if not feasibility_only:
        m.maximize(sum(int(round(c.value * 100)) * mdl.x[c] for c in cands))
    return mdl


def _solver(time_limit_s: float, workers: int) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit_s
    s.parameters.num_workers = workers
    return s


def _pin(mdl: _Model, enforced: list[TermRef]) -> None:
    """Hold these terms as plain constraints. Assumptions force CP-SAT single-threaded;
    a pinned guard is an ordinary fixed literal and the search stays parallel."""
    keep = set(enforced)
    for ref, a in mdl.assumptions.items():
        mdl.m.add(a == 1) if ref in keep else mdl.m.add(a == 0)


def _seed_core(
    brief: Brief,
    dropped: frozenset[tuple[str, str]],
    terms: list[TermRef],
    *,
    time_limit_s: float,
    workers: int,
) -> list[TermRef]:
    """A first, possibly loose, set of culprits from the solver's own unsat core. If the
    solver cannot prove it in time, every term is a suspect."""
    mdl = _build(brief, dropped, feasibility_only=True)
    mdl.m.add_assumptions([mdl.assumptions[r] for r in terms])
    solver = _solver(time_limit_s, workers)
    if solver.solve(mdl.m) != cp_model.INFEASIBLE:
        return list(terms)
    by_index = {v.index: ref for ref, v in mdl.assumptions.items()}
    culprits = {by_index[i] for i in solver.sufficient_assumptions_for_infeasibility()}
    return [r for r in terms if r in culprits]


def _alone(
    brief: Brief,
    dropped: frozenset[tuple[str, str]],
    core: list[TermRef],
    *,
    time_limit_s: float,
    workers: int,
) -> list[TermRef]:
    """The blamed terms that fail on their own: each is a conflict of size one, and
    no explanation is smaller than that."""
    out = []
    for ref in core:
        mdl = _build(brief, dropped, feasibility_only=True)
        _pin(mdl, [ref])
        if _solver(time_limit_s, workers).solve(mdl.m) == cp_model.INFEASIBLE:
            out.append(ref)
    return out


def _minimise(
    brief: Brief,
    dropped: frozenset[tuple[str, str]],
    core: list[TermRef],
    *,
    time_limit_s: float,
    workers: int,
) -> list[TermRef]:
    """Deletion pass: drop each blamed term in turn; if the rest still conflict, it was
    never needed. A probe that runs out of time keeps its term (never blame less
    than we can prove)."""
    kept = list(core)
    for ref in list(core):
        trial = [r for r in kept if r != ref]
        if not trial:
            break
        mdl = _build(brief, dropped, feasibility_only=True)
        _pin(mdl, trial)
        st = _solver(time_limit_s, workers).solve(mdl.m)
        if st == cp_model.INFEASIBLE:
            kept = trial
    return kept


def _grid(
    brief: Brief,
    mdl: _Model,
    solver: cp_model.CpSolver,
    status: cp_model.CpSolverStatus,
    elapsed: float,
    *,
    conflict: list[TermRef],
    relaxed: list[TermRef],
) -> Grid:
    p = brief.policy
    sessions: list[Session] = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in mdl.cands:
            if solver.value(mdl.x[c]):
                scr = brief.screen(c.screen)
                film = brief.film(c.film)
                fs = c.start + p.preshow_min
                fe = fs + film.runtime_min
                sessions.append(
                    Session(
                        screen=c.screen,
                        film=c.film,
                        start=c.start,
                        feature_start=fs,
                        feature_end=fe,
                        clear=fe + brief.clean_for(scr),
                    )
                )
    sessions.sort(key=lambda s: (s.screen, s.start))
    objective = solver.objective_value / 100 if sessions else 0.0
    return Grid(
        house=brief.house,
        date=brief.date,
        status=solver.status_name(status),
        objective=objective,
        solve_seconds=round(elapsed, 3),
        sessions=sessions,
        conflict=conflict,
        relaxed=relaxed,
    )


def solve(
    brief: Brief,
    *,
    time_limit_s: float = 30.0,
    workers: int = 8,
    dropped: frozenset[tuple[str, str]] = frozenset(),
    minimise: bool = True,
) -> Grid:
    """Solve one day. On INFEASIBLE the grid carries the conflicting terms."""
    t0 = time.perf_counter()
    mdl = _build(brief, dropped)
    terms = list(mdl.assumptions)
    _pin(mdl, terms)
    solver = _solver(time_limit_s, workers)
    status = solver.solve(mdl.m)
    conflict: list[TermRef] = []
    alone = False
    if status == cp_model.INFEASIBLE:
        probe = min(time_limit_s, 5.0)
        # Smallest first: any term that fails by itself is a conflict of size one.
        solo = _alone(brief, dropped, terms, time_limit_s=probe, workers=workers)
        if solo:
            conflict, alone = solo, True
        else:
            conflict = _seed_core(brief, dropped, terms, time_limit_s=probe, workers=workers)
            if minimise and len(conflict) > 1:
                conflict = _minimise(
                    brief, dropped, conflict, time_limit_s=time_limit_s, workers=workers
                )
    elapsed = time.perf_counter() - t0
    relaxed = [r for f in brief.films for r in terms_of(f) if (r.film, r.term) in dropped]
    grid = _grid(brief, mdl, solver, status, elapsed, conflict=conflict, relaxed=relaxed)
    grid.conflict_alone = alone
    return grid


def relax_key(brief: Brief, ref: TermRef) -> tuple[int, float, int]:
    """Which term to give up first: never the exclusive while anything else will do,
    then the lightest film, then prime before max before min."""
    return (
        1 if ref.term == "exclusive_screen" else 0,
        brief.film(ref.film).weight,
        _TERM_RANK.get(ref.term, 99),
    )


def relax(brief: Brief, *, time_limit_s: float = 30.0, workers: int = 8) -> Grid:
    """Drop terms one at a time, from the conflict, in relax_key order, until a grid
    exists. The grid lists every term dropped. Nothing is dropped that the
    conflict did not name."""
    t0 = time.perf_counter()
    dropped: frozenset[tuple[str, str]] = frozenset()
    while True:
        grid = solve(brief, time_limit_s=time_limit_s, workers=workers, dropped=dropped)
        if grid.status != "INFEASIBLE" or not grid.conflict:
            break
        if grid.conflict_alone:  # each fails by itself; every one of them has to go
            dropped = dropped | {(r.film, r.term) for r in grid.conflict}
        else:
            victim = min(grid.conflict, key=lambda r: relax_key(brief, r))
            dropped = dropped | {(victim.film, victim.term)}
    grid.solve_seconds = round(time.perf_counter() - t0, 3)
    return grid


def explain(brief: Brief, grid: Grid) -> str:
    """The conflict in the trade's words."""
    conflict = grid.conflict
    if not conflict:
        return "the terms cannot all hold, and no single set of them is to blame"
    p = brief.policy
    parts = []
    for ref in conflict:
        title = brief.film(ref.film).title
        parts.append(f"{title} {ref.term}" + (f" {ref.value}" if ref.value else ""))
    lead = (
        (
            "this cannot hold on its own: "
            if len(conflict) == 1
            else "these cannot hold, each on its own: "
        )
        if grid.conflict_alone
        else "these cannot hold together: "
    )
    plf = [s for s in brief.screens if "PLF" in s.formats]
    house = (
        f"the house has {len(brief.screens)} screen{'s' if len(brief.screens) != 1 else ''}"
        + (f" ({len(plf)} PLF)" if plf and len(plf) < len(brief.screens) else "")
        + f", doors {p.open} to last start {p.last_start}"
        + f" and a {p.prime_start}–{p.prime_end} prime window"
    )
    return lead + " · ".join(parts) + " — " + house
