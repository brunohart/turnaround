# Bench — the sixteen

Day 8. Measurements of `examples/sixteen.json` (The Palladium: 16 screens in six capacity classes, 22 titles, a full week) on the machine the slot runs on (Apple silicon, 10 cores, 8 CP-SAT workers, nothing else running). `scripts/bench.py` produces the tables; rerun it before trusting a number on another machine. CP-SAT is not deterministic under a wall-clock limit with eight workers: the same row moves a few percent run to run, and the first-grid time moved from 15 s to 50 s for the same model on two runs.

## Target, written before optimising

**One day of the sixteen under 60 s to a proven-optimal grid or a gap of 2 % or less.**

## Number hit

**13.4 % gap at 60 s** (Thursday, hinted, ranks per capacity class, 10-minute grid: 7,410.8 against a bound of 8,561.9). Unhinted, the default reaches **16.3 %** (7,249.6 against 8,660.7). The Day 7 model reaches 21.6 %. The target was not met; no day of the sixteen is proven optimal in a minute, and the bound is probably the loose half of the gap (the LP relaxation of the rank literals lets fractional sessions sell), but that is a guess and the number above is not.

## Thursday, step by step

### The Palladium · Thu · 16 screens · 22 titles · 60 s limit

| model | slot | candidates | booleans | ranks | constraints | first grid s | status | s | objective | bound | gap |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|--:|--:|
| Day 7 model, as shipped | 5 | 34,109 | 59,739 | 25,593 (43%) | 77,144 | 14.9 | FEASIBLE | 62.1 | 6,815.9 | 8,689.4 | 21.6% |
| + ranks per capacity class | 5 | 34,109 | 43,682 | 9,536 (22%) | 76,522 | 50.5 | FEASIBLE | 61.1 | 6,729.1 | 8,603.1 | 21.8% |
| + rank count capped by the stagger | 5 | 34,109 | 43,682 | 9,536 (22%) | 76,522 | 49.3 | FEASIBLE | 61.3 | 6,753.7 | 8,592.9 | 21.4% |
| + identical screens ordered by load | 5 | 34,109 | 43,682 | 9,536 (22%) | 76,532 | — | UNKNOWN | 61.1 | 0.0 | — | — |
| candidate cap 20,000, ranks per screen, no ordering (the unhinted default) | 10 | 17,059 | 42,257 | 25,161 (60%) | 40,709 | 11.7 | FEASIBLE | 61.0 | 7,249.6 | 8,660.7 | 16.3% |
| same, hinted from the grid above, ranks per capacity class (the hinted default) | 10 | 17,059 | 26,470 | 9,374 (35%) | 40,087 | 24.9 | FEASIBLE | 60.8 | 7,410.8 | 8,561.9 | 13.4% |

What each row says:

- **The rank literals' share** (Day 3's question first). On the sixteen they are 43 % of the booleans (25,593 of 59,739) and 60 % on the 10-minute grid, where the candidates halve and the ranks do not. On the Regent they are 12 % (171 of 1,439), so Day 3's 0.8 s → 4.4 s was the objective's search, not the literal count.
- **Ranks per capacity class** (exact: two rooms with the same seats sell the same, so a rank on either is the same rank) cuts the rank literals from 25,593 to 9,536 and the booleans by 27 %. Unhinted it does not help the search — in three runs it found its first grid at 50 s, 61 s and never — because the linking sum now ties a whole class of rooms to a whole ladder of ranks and the first-solution heuristics lose the per-screen foothold. Hinted, it gives the best grid and the best bound of the day. So it is on when there is a hint (every day of a week after the first, and any re-plan) and off when there is not.
- **The rank count capped by the stagger** (exact) changes nothing here: three starts in any ten minutes across a five-hour daypart allows far more sessions of a title than its screens can hold, so the cap never bites. It stays because on a one-in-ten house with many small rooms it would.
- **Identical screens ordered by load** (exact: any grid can be permuted into the order) cost the first grid outright — UNKNOWN at 60 s on every run. CP-SAT detects the twins itself (`max_lp_sym` in its log) and the ordering fights its heuristics. Shipped, tested, off by default.
- **The candidate cap** is the one switch that is not exact: 34,109 candidates on the 5-minute grid exceed 20,000, so the day is solved on a 10-minute grid (17,059 candidates), and the grid, the CLI and the sheet say so. It is the biggest single gain: the gap from 21.6 % to 16.3 %, the first grid from 15 s to 12 s, presolve from 12 s to 8 s. The checker accepts a 10-minute grid because every start is on the 5-minute one.
- **A hint** (exact: a starting point, never a constraint) from a grid of the same day takes the gap to 13.4 %. `solve_week` hints every day from the day before; `plan --hint yesterday.json` does it for a re-plan. The hint costs the solver about 12 s to adopt on this model (the first grid appears at 25 s, not at once), which is CP-SAT completing and repairing the partial assignment.
- **Solver parameters** tried and not kept: probing off (`cp_model_probing_level=0`) moved the first grid from 12 s to 57 s — presolve is expensive here, 8–13 s, but it is what makes the search possible.

## The Regent, for scale

### The Regent · 3 screens · 5 titles · 30 s limit

| model | slot | candidates | booleans | ranks | constraints | first grid s | status | s | objective | bound | gap |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|--:|--:|
| Day 7 model, as shipped | 5 | 1,259 | 1,439 | 171 (12%) | 1,906 | 0.1 | OPTIMAL | 5.6 | 1,608.6 | 1,608.6 | proven |
| + ranks per capacity class | 5 | 1,259 | 1,439 | 171 (12%) | 1,906 | 0.1 | OPTIMAL | 5.1 | 1,608.6 | 1,608.6 | proven |
| + rank count capped by the stagger | 5 | 1,259 | 1,439 | 171 (12%) | 1,906 | 0.1 | OPTIMAL | 4.7 | 1,608.6 | 1,608.6 | proven |
| + identical screens ordered by load | 5 | 1,259 | 1,439 | 171 (12%) | 1,906 | 0.1 | OPTIMAL | 4.1 | 1,608.6 | 1,608.6 | proven |
| candidate cap 20,000, ranks per screen, no ordering (the unhinted default) | 5 | 1,259 | 1,439 | 171 (12%) | 1,906 | 0.1 | OPTIMAL | 4.7 | 1,608.6 | 1,608.6 | proven |
| same, hinted from the grid above, ranks per capacity class (the hinted default) | 5 | 1,259 | 1,439 | 171 (12%) | 1,906 | 0.1 | OPTIMAL | 5.3 | 1,608.6 | 1,608.6 | proven |

Every switch is exact on the Regent (1,608.6 every row, proven), the model is small enough that none of them matters, and the seconds move with the machine's mood more than with the row.

## Not done, and why

- **Dominated starts** were not pruned. On this model no start is dominated in the exact sense: an earlier start of the same session in the same daypart is not always better, because the previous session on that screen must clear by it, and the house-wide stagger and the staff cumulative both care about the minute. The prunes that are exact (a start no title could use because its demand block omits the daypart and no term counts it) do not occur on any example. A heuristic prune would make `OPTIMAL` mean optimal over a pruned model, which is the candidate cap's sin again without the honesty of a stated grid.
- **A full probe** (`plan --why`) on the sixteen is one 60-second solve per session for about 70 sessions: over an hour. `--probe-budget SECONDS` bounds it and marks what it did not reach `unknown`.
