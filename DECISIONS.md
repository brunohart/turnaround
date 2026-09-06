# Decisions

Architecture decision records. A future day must not reverse one of these by accident; if it reverses one on purpose, it writes the ADR that supersedes it.

## ADR-001 — CP-SAT, not a heuristic

**Decided:** 2026-09-06 (Day 0).
**Decision:** The grid is built by Google OR-Tools CP-SAT, one boolean per (screen, film, start slot), optional intervals under `NoOverlap` per screen, distributor terms as linear constraints, and an objective the solver proves optimal or bounds.
**Why:** Distributor terms are contractual. A greedy scheduler that fills the grid and then discovers it has broken a prime guarantee has to lie or back out; a constraint solver either finds a grid that honours every term or proves that no such grid exists. The proof is the product. It is also the discipline this repository exists to learn.
**Cost:** Solve time grows with screens × titles × slots. Day 8 exists to measure and contain it.

## ADR-002 — The solver never relaxes a term silently

**Decided:** 2026-09-06.
**Decision:** If the terms cannot all hold, `plan` exits 2 with `INFEASIBLE` and no grid. Relaxation, when it arrives (Day 1), is an explicit flag that names what was given up in the proof table.
**Why:** A schedule that quietly dropped a distributor's minimum is worse than no schedule: it looks finished. The person who has to phone the distributor should learn it from the tool, not from the distributor.

## ADR-003 — The checker shares no code with the solver

**Decided:** 2026-09-06.
**Decision:** `check.py` re-derives every hard constraint from the brief and the grid with plain Python and no import from `solve.py`. `plan` runs it on its own output and exits 3 if it disagrees with itself.
**Why:** A solver that grades its own homework proves nothing. Two independent readings of the same rules that agree are evidence; one reading is an assertion. Same principle as the golden fixtures in the sibling repositories.

## ADR-004 — Time is minutes after midnight and the day may pass 24:00

**Decided:** 2026-09-06.
**Decision:** All times are integers, minutes after midnight on the day being planned. `"25:15"` is a valid last-start time and means 01:15 the following morning. Rendering folds to the clock.
**Why:** A cinema's Friday ends at two in the morning and belongs to Friday. Date-times with time zones would force a midnight seam through the busiest part of the night.

## ADR-005 — Turnaround lives inside the block

**Decided:** 2026-09-06.
**Decision:** A session occupies `preshow + runtime + clean`. The next session on that screen may begin its preshow at `clear`, not before. `clean_min` is a house policy with a per-screen override.
**Why:** The turnaround is the constraint the whole grid is built around, and putting it inside the interval is what lets a single `NoOverlap` per screen carry it. It is also the name of the tool.

## ADR-006 — Day 0's objective is weighted seats on offer, and it is a placeholder

**Decided:** 2026-09-06.
**Decision:** Each session earns `film.weight × daypart weight × screen capacity`, plus a small fill bonus. `weight` is the programmer's judgment about relative demand, not a forecast.
**Why:** It puts the wanted film in the big room at the wanted hour with no data the house does not already have in its head. Day 3 replaces it with expected admissions under capacity, which is the honest objective and needs a demand model to exist first. This ADR is here so nobody mistakes the placeholder for the design.

## ADR-007 — Python, uv, OR-Tools; not TypeScript

**Decided:** 2026-09-06.
**Decision:** The tool is a Python 3.13 package managed with uv, published to PyPI as `turnaround`.
**Why:** CP-SAT's home is Python and its bindings elsewhere lag. The data-side sibling (`cinema-ops-platform`) is Python; the SDK sibling (`theatrical`) is TypeScript, and an adapter between them is a later, separate concern (Day 9).

## ADR-008 — No vendor's name in the product

**Decided:** 2026-09-06.
**Decision:** The brief is the tool's own format. Imports from any platform's export are adapters and arrive later; the core never depends on one.
**Why:** The tool is for the exhibitor. Its usefulness must not depend on which system sells their tickets.
