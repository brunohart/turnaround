"""The CP-SAT model.

One boolean per (screen, film, start slot). An optional interval per boolean
carries the block the session would occupy; NoOverlap per screen keeps the
turnaround honest. Distributor terms are linear constraints over those
booleans. The objective is weighted seats on offer: each session earns
film.weight x daypart weight x screen capacity, so the solver puts the film
people want in the big room at the hour they want it.

The solver never silently relaxes a term. If the terms cannot all be met the
status is INFEASIBLE and the caller decides what to give up.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .model import Brief, Grid, Session


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
                from .model import parse_time

                lo = max(lo, parse_time(t.earliest_start))
            if t.latest_start:
                from .model import parse_time

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


def solve(brief: Brief, *, time_limit_s: float = 30.0, workers: int = 8) -> Grid:
    p = brief.policy
    cands = candidates(brief)
    m = cp_model.CpModel()

    x: dict[Candidate, cp_model.IntVar] = {}
    intervals_by_screen: dict[str, list[cp_model.IntervalVar]] = {s.id: [] for s in brief.screens}
    for c in cands:
        v = m.new_bool_var(f"x[{c.screen},{c.film},{c.start}]")
        x[c] = v
        iv = m.new_optional_interval_var(
            c.start, c.block, c.start + c.block, v, f"iv[{c.screen},{c.film},{c.start}]"
        )
        intervals_by_screen[c.screen].append(iv)

    # One thing on a screen at a time, turnaround included in the block.
    for ivs in intervals_by_screen.values():
        if ivs:
            m.add_no_overlap(ivs)

    # Stagger: within any window of stagger_min, at most one start house-wide.
    if p.stagger_min > 0:
        starts = sorted({c.start for c in cands})
        by_start: dict[int, list[cp_model.IntVar]] = {}
        for c in cands:
            by_start.setdefault(c.start, []).append(x[c])
        for s0 in starts:
            window = [v for s in starts if s0 <= s < s0 + p.stagger_min for v in by_start[s]]
            if len(window) > 1:
                m.add(sum(window) <= 1)

    # Distributor terms.
    for f in brief.films:
        mine = [c for c in cands if c.film == f.id]
        vs = [x[c] for c in mine]
        t = f.terms
        if t.min_shows > 0:
            if not vs:
                raise ValueError(
                    f"film {f.id} has min_shows={t.min_shows} but no screen can play it"
                )
            m.add(sum(vs) >= t.min_shows)
        if t.max_shows is not None and vs:
            m.add(sum(vs) <= t.max_shows)
        if t.prime_shows > 0:
            pv = [x[c] for c in mine if c.prime]
            if not pv:
                raise ValueError(f"film {f.id} needs prime shows but no prime start is allowed")
            m.add(sum(pv) >= t.prime_shows)
        if t.exclusive_screen:
            # y[s] = 1 means screen s plays only this film today.
            ys = []
            for scr in brief.screens:
                if not brief.can_play(scr, f):
                    continue
                y = m.new_bool_var(f"excl[{scr.id},{f.id}]")
                ys.append(y)
                for c in cands:
                    if c.screen == scr.id and c.film != f.id:
                        m.add_implication(y, x[c].negated())
                # An exclusive screen must actually carry the film.
                own = [x[c] for c in mine if c.screen == scr.id]
                if own:
                    m.add(sum(own) >= 1).only_enforce_if(y)
                else:
                    m.add(y == 0)
            if not ys:
                raise ValueError(f"film {f.id} needs an exclusive screen but none can play it")
            m.add(sum(ys) >= 1)

    # Objective: weighted seats on offer. Scale to integers for CP-SAT.
    m.maximize(sum(int(round(c.value * 100)) * x[c] for c in cands))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = workers
    t0 = time.perf_counter()
    status = solver.solve(m)
    elapsed = time.perf_counter() - t0
    name = solver.status_name(status)

    sessions: list[Session] = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in cands:
            if solver.value(x[c]):
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
        status=name,
        objective=objective,
        solve_seconds=round(elapsed, 3),
        sessions=sessions,
    )
