# The answer was no

*A draft. Fourteen days building a constraint solver for the cinema showtime grid, and the day it refused to give me one. Every number here is in `docs/LOG.md` or `docs/bench.md`; check against those before adding any.*

## The Wednesday problem

Every week, in every cinema, someone builds a grid: which title plays on which screen at what time, Thursday to Wednesday. They do it on a Wednesday, usually in a spreadsheet, usually in an afternoon, holding in their head a set of rules nobody has written in one place. A screen holds one thing at a time. The room needs twenty minutes between features and the floor staff can turn two rooms at once, not five. Two shows should not start within ten minutes of each other or the lobby cannot cope. The distributor's confirmation says *three shows a day, one in prime, its own screen through Sunday*. The kids' film cannot start after five. The horror cannot start before four.

The grid they arrive at is one they can live with. It is not one they can prove, and the first anyone hears of a missed term is the distributor's report.

I built `turnaround` to find out whether that grid could be proven instead: a command-line tool in Python on OR-Tools CP-SAT that takes the house, the slate and the terms as a JSON brief and returns the sessions, with a proof. This is what I learned, evidence first.

## The hero is the word INFEASIBLE

On Day 1 I doubled the minimums on a three-screen house and asked for a grid. This is the whole of what came back:

```
INFEASIBLE — this cannot hold on its own: The Long Voyage min_shows 6 — the house
has 3 screens (1 PLF), doors 10:00 to last start 21:30 and a 17:30–20:45 prime window.
turnaround plan --relax drops terms until a grid exists
```

Exit code 2, no grid. That refusal is the most useful thing the tool does, and it is the thing a spreadsheet, a heuristic or a penalty-scored optimiser cannot do. A 168-minute feature with a twenty-minute preshow and a twenty-minute turnaround on the one PLF room fits four times between ten in the morning and a 21:30 last start. Six is not a hard week; it is an impossible one, and the person who agreed to it should hear that on Wednesday and not on the following Tuesday.

How it works is short. Every distributor term sits in the model behind its own *assumption literal* — one boolean per (title, term) that the term's constraint is enforced under. When CP-SAT says `INFEASIBLE` it can name a set of assumptions sufficient for the contradiction. That set is not minimal, so the tool first tries each term alone (a term that fails by itself is a conflict of size one, and is the commonest case), and otherwise shrinks the core by deletion: drop a term, solve again, keep it out if the contradiction survives. What is left is a set of terms where every one is needed for the clash — *these two exclusives and that prime guarantee cannot hold together* — and it is said in the trade's words with the house's facts beside it, because the reader is a film programmer and not a solver.

Two decisions followed and both are in `DECISIONS.md` so that no later day could quietly undo them. The solver **never relaxes a term silently** (ADR-002): there is no mode in which a minimum is a soft constraint with a big weight. And when you do want a grid anyway, `--relax` drops terms from the named conflict **one at a time, in a fixed order, out loud** (ADR-009) — the exclusive last, the lightest title first — prints each drop, writes it on the grid file, and stamps *RELAXED* in rust beside the failing check on the sheet, with "4 terms given up · see proof" in the header. The relaxed Regent is a usable Thursday. It is also a document that says exactly which four promises it breaks.

The tests for this were the first place the problem taught me something. My first test hard-coded which pair of terms the solver would blame. There were three equally minimal conflicts and it named a different one. A minimal conflict is not unique; the test now asks the solver to confirm that whatever was named is minimal, rather than guessing what it will be.

## Why constraint programming, and not something gentler

The honest alternative is a heuristic: place the big title, fill around it, repair. It would be faster to write and would produce a plausible grid nearly always. The trouble is "nearly". A heuristic that cannot find a grid does not know whether none exists; it can only say it failed, and then someone relaxes something by hand. The other alternative, a weighted score with penalties for broken terms, will happily trade a distributor's minimum for forty admissions.

In CP-SAT the week is written the way the trade already states it. One boolean per (screen, title, start) on a five-minute grid. One optional interval per session, with the preshow and the turnaround *inside* the block, under a `NoOverlap` per screen — so "the room is turned before the next doors" is not a rule to check afterwards but a shape that cannot overlap. The floor staff are a cumulative. The stagger is a window count. Every term is a linear constraint. What is left to optimise is the one thing that should be: expected admissions, where each title's demand is stated per daypart, a second show in the same daypart draws less than the first, and no room sells more seats than it holds — so the report can say, in rust, that 2,206 people are turned away at capacity in the school-holiday week, which is an argument for a second print and not a rounding error.

The Regent — three screens, five titles, one PLF exclusive with a prime guarantee — is proven `OPTIMAL` in about five seconds at 1,608.6 expected admissions. Its week, seven days with titles holding their start times across the weekdays, in about twenty.

## Two readings

A solver's `OPTIMAL` is a statement about a model, and the model was written by the same person who might have misread the term. So there is a second program, `check.py`, that reads the brief and the sessions and re-verifies every rule, and it **shares no code with the solver** (ADR-003) — not the block arithmetic, not the prime window, nothing. When a day added a constraint it went into the checker first, then the solver, then a test that the checker catches a hand-built violation. Two readings that agree are evidence. One is an assertion.

This paid for itself on Day 9, in a way I had not planned. `turnaround import --csv` takes the four columns any ticketing system can export — screen, title, start, runtime — and makes a grid the checker can read. I typed the Regent's Thursday the way a manager would and ran `check`. It found five slips: a turnaround cut short, two starts five minutes apart, a horror show before its earliest start, a title one show short and one prime start short. None of them is visible in a spreadsheet. The checker does not need the solver to be useful; it may be the more useful half.

The same separation governs explanation. `turnaround explain` says why a session is where it is. What terms it helps satisfy and what it sells are the checker's reading. Whether it is *forced* is found by forbidding that session and solving again — and that is the solver's claim about its own model, so the sheet labels it as one (ADR-015). An explanation that borrowed the checker's authority for the solver's opinion would be worse than none.

## Where it stopped working

Day 8 was scale: The Palladium, sixteen screens in six capacity classes, twenty-two titles. I wrote the target down before touching the model: *one day under 60 seconds to a proven-optimal grid or a gap of 2 % or less.*

**I missed it, by a lot.** The model as shipped reached a 21.6 % gap at 60 seconds. The best configuration reaches 13.4 %.

| | booleans | first grid | gap at 60 s |
|---|--:|--:|--:|
| Day 7 model, 5-minute grid | 59,739 | 14.9 s | 21.6 % |
| ranks per capacity class (exact) | 43,682 | 50.5 s | 21.8 % |
| identical screens ordered by load (exact) | 43,682 | never | — |
| candidate cap: a 10-minute grid | 42,257 | 11.7 s | 16.3 % |
| the same, hinted from a grid of the day | 26,470 | 24.9 s | 13.4 % |

Three things in that table are worth more than the number. First, the two *exact* reformulations I was proudest of did nothing or did harm: sharing demand ranks across rooms of equal capacity cut the booleans by 27 % and made the first grid three times slower unhinted, because the linking sum took away the per-screen foothold the first-solution heuristics were using; and my hand-written symmetry breaking for identical screens cost the first grid outright on every run, because CP-SAT finds those symmetries itself and my ordering fought it. Second, the single biggest gain was the one switch that is *not* exact — solving on a 10-minute start grid when the 5-minute one has more than 20,000 candidates — and so the grid file, the CLI and the sheet all say that it happened (ADR-016). An `OPTIMAL` over a quietly pruned model would be the silent relaxation again wearing a different coat. Third, the same row moves a few percent from run to run: eight workers under a wall-clock limit are not deterministic, and any benchmark of this kind that prints one number per row is telling you less than it looks.

So a sixteen-screen week comes back in about eleven minutes, every day `FEASIBLE`, every grid passing the checker, every sheet saying *not proven best, gap 13 %* in its header. They are good grids. They are not proven grids, and the tool does not say otherwise. I think the bound is the loose half of that gap — the LP relaxation of the rank literals lets fractional sessions sell — but that is a guess, and the number is not.

## What I would tell someone starting

- **Make infeasibility a first-class answer on day one.** Assumption literals per business rule cost nothing to add at the start and are miserable to retrofit. The explanation is the product; the grid is what you get when there is nothing to explain.
- **Write the checker first and share nothing.** It is eight hundred lines of dull code beside the solver's thirteen hundred, and it is the only reason to believe the interesting code.
- **Write the performance target before optimising, and publish the miss.** I would not have learned that my exact reformulations were useless if I had been free to pick the target afterwards.
- **Every inexact step must be stated on the artefact**, not in the docs. If the sheet is what gets pinned in the booth, the sheet is where it says *10-minute grid* and *gap 13 %*.
- **Label whose claim each sentence is.** The checker verifies; the solver claims; the brief states demand; the board, which draws a dropped grid in a browser with no checker at all, heads its panel *The grid's claims* and carries no ticks.

## What it is not

It does not forecast demand; the brief states it, with the programmer's assumptions in words beside the numbers. It does not optimise a week at once; a week term reaches each day as a debt, which is exact for the terms and not for the objective. It has been run on invented houses — the Regent, the Palladium, a ten-day festival with guests and prints that are only in town some days — and on no real one. Whether a working programmer would rather be told *no* on a Wednesday is the thing fourteen days of building cannot answer.

The code, the twenty decisions, and a log of what each day left rough: github.com/brunohart/turnaround.
