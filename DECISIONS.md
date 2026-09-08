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

## ADR-009 — Relaxation drops only named terms, in a fixed order, and writes every drop on the grid

**Decided:** 2026-09-07 (Day 1).
**Decision:** A relaxable term is one the solver can name: it has an assumption literal in `solve.terms_of` and an entry in `check.RELAXABLE`. A term added to `Terms` is not relaxable until it is in both, and the checker's list is written first. `--relax` drops one term per round, always from the conflict the solver has just named, in the order `exclusive_screen` last, then the lightest film, then `prime_shows` before `max_shows` before `min_shows`. A round that ends `UNKNOWN` stops relaxation: nothing is dropped on a guess. Every drop is recorded in `Grid.relaxed`; the checker treats a failed check as acceptable only when the grid declares it, and rejects a declared relaxation that names a term the brief does not carry.
**Why:** ADR-002 says the solver never relaxes silently. This is what "not silently" means in code: the grid itself is the record, and the checker, which shares no code with the solver, refuses to trust a relaxation it cannot match to a real term. Dropping only from the named conflict means the tool never gives up a term that was not part of the problem. The fixed order is a judgment (a distributor's exclusive is the term hardest to renegotiate; a light title's prime guarantee the easiest) and lives in one function, `relax_key`, so a later day can replace it deliberately.
**Cost:** When several equally small conflicts exist the order rule alone decides which title pays, and a dropped `min_shows` lets the title vanish from the grid under the placeholder objective (ADR-006).

## ADR-010 — The week unfolds into plain days; holding times is soft, per title, against one anchor

**Decided:** 2026-09-08 (Day 2).
**Decision:** A `WeekBrief` is a base brief plus per-day overrides, and `week.day(i)` produces an ordinary `Brief`. The solver solves days, not weeks: `solve_week` is a loop over `solve`, and `check_week` is a loop over `check` plus the two checks that only exist at week scope (the grids match the days; the `held` list is true). Week-scoped distributor terms (Day 5) will be the first thing that cannot be expressed this way and must be designed then, not smuggled in now. The only cross-day coupling is the soft term: the first hold day that solves is the anchor, and each later hold day pays `hold_penalty` per title whose *set of start times* differs from the anchor's. Rooms are not compared. Nothing is forced; a day whose hours cannot carry the anchor's starts pays and moves on. `WeekGrid.held` is the solver's claim; the checker re-derives it and fails the week if the claim is wrong.
**Why:** Every term, conflict, relaxation and check written on Days 0 and 1 keeps working per day with no second code path, and the checker's independence (ADR-003) extends to the week for free. Anchoring to one day rather than chaining day to day means "holds" has one meaning (same as the anchor) and cannot drift across the run. Start sets rather than sessions because the customer remembers *when*, not *where*.
**Cost:** The anchor is the first hold day in week order, which for a Thursday-opening week is the day that still carries the opening exclusive; the tail of the week is pulled toward Thursday rather than toward the grid the tail would agree on. The penalty is in weighted seats, the placeholder unit of ADR-006, and must be restated when Day 3 replaces the objective.

## ADR-011 — The objective is expected admissions under capacity, and the biggest room takes the first audience

**Decided:** 2026-09-09 (Day 3). Supersedes ADR-006.
**Decision:** A session's worth is `min(expected, capacity)`: the seats it would sell, not the seats it offers. `expected` for the k-th session of a title in a daypart is the title's stated first-session figure for that daypart × its weekday multiplier × its holiday multiplier (when the day's policy says school holidays) × `decay^k`. A title with no `demand` block gets `weight × daypart weight × policy.assumed_admissions` with the default decay, so a brief that states only judgment still solves and its objective still means admissions. In the model, ranks are literals per (screen, title, daypart, rank), one holder per rank, tied to the session booleans by a sum per screen; the solver assigns ranks and, since `min(capacity, expected)` can only grow with capacity, the maximising assignment gives rank 0 to the biggest room. The checker re-counts the same way, sorted by capacity, and holds the solver's `admissions` claim to a cent a session. The hold penalty (ADR-010) is in expected admissions; `Grid.objective` = `admissions − hold_paid`, and the week checker re-derives what each day owed.
**Why:** Seats on offer rewards a grid for opening rooms nobody fills. Seats sold rewards the grid the house actually wants: the big room for the title that fills it, a second show only where the first would turn people away, the family title in the morning because that is when its audience exists. Diminishing returns per daypart are what stop the solver stacking one title into every slot. The assumptions live in the brief, in words beside the numbers, because the tool has no data of its own and should not pretend to.
**Cost:** "Biggest room first" is a modelling choice: the demand model says how many come to the first, second and third show of a title in a daypart, not which physical session they choose, and the optimistic reading is the one the objective takes. The rank literals cost solve time (the Regent went from 0.8 s to 4.4 s); Day 8 measures it. A stated block that omits a daypart makes sessions there worthless, which is a statement the house makes by omission and may not intend.
