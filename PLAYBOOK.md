# Turnaround — fourteen-day playbook

Epoch: **2026-09-06 = Day 0** (this playbook was written and Day 0 shipped that day). One slot per day at 08:45 Pacific/Auckland, run by `scripts/slot.sh` through the `turnaround-build` skill. Each slot reads its day here, does the work, proves it, commits, pushes, and closes the matching Linear issue.

Every day ends the same way, no exceptions:

1. `scripts/build.sh` is clean (ruff, format, mypy strict) and `scripts/test.sh` is green.
2. `scripts/run.sh` regenerates every example grid and sheet into `docs/grids/`, and `turnaround check` passes on each. Screenshot the sheet that changed to `docs/grids/day-N-<what>.png` (headless Chrome) and look at it.
3. `docs/LOG.md` gets a dated entry: what shipped, what the solver did (status, seconds, objective), what broke, what is still rough.
4. Commits are small and Conventional (`feat(solve): …`, `fix(check): …`, `docs: …`). Push to `origin main`.
5. The Linear issue for the day is moved to Done with a comment: commit SHAs, the sheet path, one honest sentence about what is still rough.

If the previous day left the build broken, fixing that comes before anything below. After Day 13 the slot is backlog-driven: it takes the highest-priority `Todo` issue in the Linear project that does not carry `bruno-gated`.

---

## Day 0 — Sat 6 Sep — The grid exists ✅

Shipped: the brief (house, slate, terms, policy) as Pydantic models; the CP-SAT model (booleans per screen × film × start, optional intervals, NoOverlap per screen, house-wide stagger, min/max/prime/exclusive/window terms); the independent checker with a proof table; the `plan` / `check` / `render` / `validate` CLI; the week sheet in the house identity; sixteen tests; CI; the Regent example (3 screens, 5 titles, one PLF exclusive) solved OPTIMAL in under a second with every check green.

## Day 1 — Sun 7 Sep — Infeasibility, explained ✅

- When the terms cannot all hold, name the smallest set that conflicts. One assumption literal per (film, term) in the model; on `INFEASIBLE`, `solver.sufficient_assumptions_for_infeasibility()` gives the culprits. `plan` exits 2 and prints them in the trade's words: *"these cannot hold together: The Long Voyage min_shows 6 · The Long Voyage exclusive_screen · Harvest Moon prime_shows 2 — the house has 3 screens and a 17:30–20:45 prime window."*
- `--relax`: drop terms in order (lowest film weight first, `prime_shows` before `min_shows`, `exclusive_screen` last) until feasible, and print each dropped term in the proof table as a rust ✗ *relaxed*, never silently (ADR-002).
- Tests: three constructed conflicts (too many shows for the hours; two exclusives, one eligible screen; prime guarantees exceeding the prime window) each name the right terms. Relaxation of the Regent with `min_shows` doubled produces a checkable grid and lists what was given up.

## Day 2 — Mon 8 Sep — The week ✅

- A `WeekBrief`: seven days sharing house and slate, with per-day `policy` overrides (Fri/Sat `last_start` 22:30, Sun doors 11:00) and per-day `terms` overrides (the opening Thursday's exclusive lifts on Monday). Solve day by day; a `WeekGrid` carries seven `Grid`s.
- Soft constraint: a title keeps the same start times Monday to Thursday where it can (customers remember times). Penalty per differing start set; report how many titles hold their times.
- The sheet gains a week view: seven rows of the by-title table, one full grid per day on its own page, print stylesheet stacks them.
- Property tests with Hypothesis: for random small briefs that solve, the checker always passes; for random hand-built grids, the checker's verdict matches a brute-force re-check.

## Day 3 — Tue 9 Sep — Demand ✅

- Replace the placeholder objective (ADR-006). A `demand` block per film: expected admissions per session by daypart and weekday, with diminishing returns per additional same-title session in the same daypart (the second 19:00 show earns less). Objective becomes Σ min(expected, capacity): seats *sold*, not seats offered.
- A `demand.json` example built from stated assumptions (weekend uplift, school-holiday flag, family titles front-loaded) — assumptions written in the file, not the code.
- Report per title and per day: seats on offer, expected admissions, expected turned away at capacity. Sheet footer carries expected admissions for the day.
- Tests: raising a title's demand moves it to the bigger room; capping capacity leaves turned-away non-zero and reported.
- *From Day 2:* `WeekBrief.hold_penalty` is in weighted seats (ADR-010); restate it in expected admissions with the new objective, and keep `Grid.objective` net of the penalty so the week's `held` count stays honest.

## Day 4 — Wed 10 Sep — The booth's realities ✅

- Credits overlap: `film.credits_min` lets the clean start that many minutes before feature end. Block length adjusts; checker updated first, then solver.
- Preshow by format (3D hands out glasses; PLF runs a longer reel) via `policy.preshow_by_format`.
- Staff: `policy.max_concurrent_turnarounds` as a cumulative constraint over clean intervals (`add_cumulative`), because two ushers cannot clear three rooms.
- Per-screen hours: `screen.open` / `screen.last_start` overrides (Screen 3 opens at noon on weekdays).
- Generalise stagger to `max_starts_per_window` (e.g. at most 2 starts in any 15 minutes) with the 1-per-10 default preserved.
- *Shipped besides:* a week day may override a screen's hours (`DayOverride.screens`). *Left for Day 6:* look at the credits-overlap hatch at print size. *Left for Day 8:* measure the staff cumulative's share of solve time.

## Day 5 — Thu 11 Sep — Distributor terms, fully ✅

- Week-scoped terms: `min_shows_per_week`, `prime_shows_per_week`, `exclusive_until` (day index), `plf_lock` (every PLF session in the house belongs to this title while booked), `max_shows_per_day` already exists.
- A printed *terms sheet* per title (mono, one page) showing each term, its scope, and where in the week it was honoured — the document the programmer would send back to the distributor.
- Validation speaks the trade's language: unknown fields, impossible windows, a PLF term on a house with no PLF room, all as sentences.
- Tests per term; the Regent week example gains real terms for the opening title.
- *Shipped besides:* a day brief refuses a week term in a sentence; `validation_sentences` translates every pydantic error. *Left for Day 7:* a week term's floor is a necessary bound, not a spread — the what-if is where "spread the 28 over the week" belongs. *Left for Day 8:* `day_bound` re-enumerates candidates per film per day; measure it on sixteen screens.

## Day 6 — Fri 12 Sep — The sheet, properly ✅

- Full identity pass against `digital-design-taste.md`: misregistered title pass, rubber-stamp labels, grain, offset shadows, a colour wash bleeding off-frame, the broken divider; nothing level.
- Print: A3 landscape pin-up and A4 portrait per screen (the *booth strip*: one screen, its sessions in mono, the turnarounds called out) — printable from the same HTML with `@page` rules.
- Mobile: the grid becomes a per-screen list with the same three-strip block turned vertical.
- Screenshot desktop, print preview (Chrome `--print-to-pdf`), and a phone width. Look at all three before committing.
- *Shipped besides:* `scripts/shot.py`, screenshots over the DevTools protocol with device emulation, because headless Chrome clamps the window near 500px and a `--window-size=390` shot is a crop. *Run on Sat 13 Sep:* the Friday slot did not fire. *Left for Day 12:* the hatches as SVG pattern fills for print (the A3 PDF is 33 MB as CSS gradients) — the board ports the block anyway. *Left open:* a per-screen week strip for small houses; whether the sheet should link fonts.

## Day 7 — Sat 13 Sep — Explain ✅

- *Shipped besides:* `what-if --set key=value` for a policy change; `plan --why`; ADR-015 (the why is the checker's, forced is the solver's claim, a show is a title in a room in a daypart). *Left for Day 8:* a probe budget — one solve per session is a minute on three screens. *Left for Day 11:* the what-if prints the two days side by side and writes no diff. *Left open (from Day 5):* a week what-if, "spread the 28 over the week"; `what_if` takes a day.


- Every session carries a `why`: the terms it satisfies (`min_shows 3/3`, `prime 1/1`), its objective contribution, and whether it is *forced* (present in every optimal grid — probe by forbidding it and re-solving; report the objective delta or `INFEASIBLE`).
- `turnaround explain grid.json --session 1@17:30` prints that session's why. `turnaround what-if brief.json --drop bees` re-solves without a title and reports what the freed slots went to.
- The sheet's hover title and the by-title table show the why; the proof table gains a *forced* column.

## Day 8 — Sun 14 Sep — Scale

- `examples/sixteen.json`: a 16-screen multiplex, 22 titles, a full week. Measure: candidates, booleans, time to first feasible, time to optimal or the gap at 60 s. Write `docs/bench.md` as a table and commit it.
- Contain it: prune dominated starts, break symmetry between identical screens, adaptive `slot_min` (10-minute grid when candidates exceed a threshold, with the choice reported), solver hints from yesterday's grid when re-planning.
- Target written down before optimising: one day of the sixteen under 60 s to a proven-optimal or ≤2 % gap. Record the number hit, not the number hoped for.
- *From Day 3:* the demand rank literals (one per screen × title × daypart × rank) took the Regent from 0.8 s to 4.4 s. Measure their share first; the rank count is an upper bound the house-wide stagger could tighten.

## Day 9 — Mon 15 Sep — In and out

- `turnaround import --csv sessions.csv` reads a plain showtimes export (screen, title, start, runtime) into a brief skeleton plus a grid, so a house can `check` the grid it made by hand before it trusts the solver with anything.
- `turnaround export grid.json --ical --csv --json`: a calendar per screen, a flat CSV for signage, JSON for a website.
- Round-trip tests: export → import → check passes; the Regent grid survives the loop unchanged.

## Day 10 — Tue 16 Sep — The festival profile

- A second brief profile: many titles with one or two screenings each, several venues, `strand`s, guest availability windows (hard), print or DCP move time between venues (hard), and clash-minimisation between titles in the same strand (soft: an audience should not have to choose).
- `examples/festival.json`: 40 fictional titles, 3 venues, 10 days. Same checker discipline, new checks named for the festival's terms.
- The sheet learns to render venues as screens and days as pages; strands get a mono tag, never a colour.

## Day 11 — Wed 17 Sep — Diff

- `turnaround diff old.json new.json`: sessions added, removed, moved (same title, new time or room), seats delta, terms delta. Output as a table and as JSON.
- The sheet renders a diff: moved blocks with a ghost outline at their old position in the ink hatch, additions with an orange stamp, removals struck through in the by-title table. This is the Thursday re-plan artefact.
- Tests: every diff is symmetric and composable (diff(a,b) applied to a yields b).

## Day 12 — Thu 18 Sep — The board

- A static page (`board/`) that loads a grid JSON by drag-and-drop and renders the sheet client-side; the template logic ported to a small JavaScript module with the same three-strip block. No server, no accounts, no tracking; the URL carries nothing.
- Deploy to Vercel as `turnaround.vercel.app` — the deploy is **bruno-gated** (project creation); the build can prepare `vercel.json` and a preview script.
- Playwright pass on the board at desktop and phone widths; screenshots committed.

## Day 13 — Fri 19 Sep — The write-up

- README rewritten around the sheets (Day 0 → Day 12 screenshots inline), the benchmark table, and the argument: why constraint programming for the cinema week, why the checker, what the tool refuses to do.
- `docs/post.md`: a draft essay on CP-SAT for exhibition scheduling — evidence first, the infeasibility explanation as the hero, no hype.
- Tag `v0.1.0`. PyPI publish is **bruno-gated** (`uv publish` needs a token); prepare the release and leave the command in the log.
