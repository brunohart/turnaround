# turnaround

**The showtime grid, solved — and proven.**
A constraint solver for the cinema week: every screen, every session, every distributor term, and the turnaround between them.

[![PyPI](https://img.shields.io/pypi/v/turnaround?color=D4622B&label=pypi)](https://pypi.org/project/turnaround/)
[![Python](https://img.shields.io/pypi/pyversions/turnaround?color=1B2D4F)](https://pypi.org/project/turnaround/)
[![CI](https://github.com/brunohart/turnaround/actions/workflows/ci.yml/badge.svg)](https://github.com/brunohart/turnaround/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-1A1A1A)](https://github.com/brunohart/turnaround/blob/main/LICENSE)

<img src="https://raw.githubusercontent.com/brunohart/turnaround/v0.1.1/docs/grids/regent.png" alt="The Regent's sheet: three screens, fifteen sessions on an hour ruler, each a preshow, a feature and an orange-hatched turnaround; the prime window washed navy; the by-title table and a proof table of green ticks" width="100%">

*The Regent. Three screens, five titles, a PLF exclusive with a prime guarantee, a kids' title that must start by 17:00, a horror held to 16:00 or later. Proven `OPTIMAL` in about five seconds. Every check green.*

## The problem

Every Wednesday, in every cinema, someone builds next week's grid in a spreadsheet, holding the rules in their head: one thing per screen, twenty minutes to turn the room, no two starts inside ten minutes, and a distributor who was promised *three shows a day, one in prime, its own screen*.

The grid they arrive at is one they can live with. It is not one they can **prove** — and the first anyone hears of a missed term is the distributor's report.

`turnaround` takes the house, the slate and the terms as a JSON brief, and returns the grid **with its proof**. When the terms cannot all hold, it says so and gives you nothing.

## Thirty seconds

```bash
uv tool install turnaround        # or: pipx install turnaround · pip install turnaround
curl -O https://raw.githubusercontent.com/brunohart/turnaround/v0.1.1/examples/regent.json
turnaround plan regent.json --html sheet.html
```

```text
                         The Regent · OPTIMAL · 5.063s
 Screen 1   10:40 The Long Voyage · 14:15 The Long Voyage · 17:45 The Long Voyage · 21:20 The Long Voyage
 Screen 2   10:00 Harvest Moon · 12:25 The Bee Kingdom · 14:30 The Bee Kingdom · 16:35 Harvest Moon · …
 Screen 3   10:10 Atlas of Small Rooms · 13:15 Harvest Moon · 16:00 Dead Signal · 18:25 Dead Signal · …

 expected admissions 1,609 of 2,840 seats on offer · 14 turned away at capacity (Dead Signal)

 ✓ turnaround         no screen double-booked
 ✓ stagger            min gap 10 min; every start clears the lobby
 ✓ min_shows          odyssey   4 ≥ 3
 ✓ prime_shows        odyssey   1 ≥ 1 in 17:30–20:45
 ✓ exclusive_screen   odyssey   own screen: 1
 ✓ earliest_start     signal    0 before 16:00
 ✓ latest_start       bees      0 after 17:00
 ✓ admissions         1,608.6 claimed · 1,608.6 re-counted
```

`sheet.html` is the picture above: paper-first, prints as an A3 pin-up plus an A4 booth strip per screen, and turns into the booth strips on a phone.

## The best thing it does is refuse

Double the minimums and ask again:

```text
$ turnaround plan regent-overbooked.json
INFEASIBLE — this cannot hold on its own: The Long Voyage min_shows 6 — the house has
3 screens (1 PLF), doors 10:00 to last start 21:30 and a 17:30–20:45 prime window
```

Exit code 2. No grid. Not a grid with a distributor's minimum quietly dropped.

Every term sits behind its own assumption literal, so an infeasible week comes back as the **smallest set of terms that cannot hold together**, in the trade's words. If you want a grid anyway, `--relax` drops terms one at a time, in a fixed order, out loud — and stamps every one of them on the sheet.

<img src="https://raw.githubusercontent.com/brunohart/turnaround/v0.1.1/docs/grids/relaxed.png" alt="The relaxed sheet: the header stamped RELAXED with 4 terms given up in rust, and RELAXED stamped beside each failing check in the proof table" width="100%">

## Two readings, not one

A solver's `OPTIMAL` is a statement about a model — written by the same hand that might have misread the term. So every grid is re-verified by a **checker that shares no code with the solver**. Two readings that agree are evidence; one is an assertion.

It also means you can check a grid you made by hand, before trusting the solver with anything:

```text
$ turnaround import --csv thursday.csv --brief regent.json --out hand.json
$ turnaround check regent.json hand.json
 ✗ turnaround       2: harvest@19:10 clears 21:34 but signal starts 21:30
 ✗ stagger          min gap 10 min; 1 windows too busy, first 17:40 with 2 starts
 ✗ earliest_start   signal   1 before 16:00
 ✗ min_shows        atlas    1 ≥ 2
 ✗ prime_shows      atlas    0 ≥ 1 in 17:30–20:45
```

Five slips in a Thursday a manager typed. None of them visible in a spreadsheet.

## What is in the box

| | |
|---|---|
| **`plan`** | Solve a day, a seven-day week, or a festival of up to 21 days. Exit 2 if the terms conflict, 4 if the clock ran out — which is never a reason to relax a term. |
| **`check`** | Verify any grid — the solver's or yours — against its brief. |
| **`explain`** | Why a session is where it is, and whether the terms or the objective *force* it. |
| **`what-if`** | The day without a title, or under a changed policy, beside the day as it stands. |
| **`diff`** | The Thursday re-plan: what moved, what came, what went. Symmetric and composable. |
| **`terms`** | One page per title: every term, what was delivered day by day — the sheet you send the distributor. |
| **`import` / `export`** | A four-column showtimes CSV in; calendars per screen, signage CSV and JSON out. |
| **`render`** | The sheet, from any grid. |

**The model.** [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver). One boolean per (screen, title, start) on a five-minute grid; an interval per session with the preshow and the turnaround *inside* the block under `NoOverlap`; floor staff as a cumulative; every distributor term a linear constraint. The objective is **expected admissions under capacity** — demand stated per daypart with the programmer's assumptions in words beside it, a second show in a daypart drawing less than the first, no room selling more seats than it holds.

**Terms it speaks.** `min_shows` · `max_shows` · `prime_shows` · `exclusive_screen` · `exclusive_until` · `earliest_start` · `latest_start` · `screens` · `min_capacity` · `plf_lock` · `min_shows_per_week` · `prime_shows_per_week` · and for festivals `screenings`, a `guest` who can attend only some days, and a print that is only `available` for part of the run.

<img src="https://raw.githubusercontent.com/brunohart/turnaround/v0.1.1/docs/grids/day-11-replan.png" alt="The re-plan sheet: dashed ghost outlines where twelve sessions used to be, one orange ADDED stamp, and a table of every change under the grid" width="100%">

*`turnaround diff`: a moved session leaves a ghost where it was.*

## The board

No install at all: **[turnaround-tau.vercel.app](https://turnaround-tau.vercel.app)**. Drop a grid JSON on it, and its brief beside it, and the sheet is drawn in your browser. No server, no accounts, no tracking, nothing in the address — a content-security policy lets nothing leave the page. It draws and does nothing else; the proof stays the checker's.

## Honest numbers

The target for sixteen screens was written down before optimising — *one day in under 60 s, proven optimal or within 2 %* — and **it was missed**.

| house | status | time | gap |
|---|---|--:|--:|
| The Regent — 3 screens, 5 titles, one day | `OPTIMAL` | 5 s | proven |
| The Regent — a full week, titles holding their times | `OPTIMAL` ×7 | 22 s | proven |
| A festival — 3 venues, 10 days, guests and prints in town | `OPTIMAL` ×10 | 6 s | proven |
| The Palladium — 16 screens, 22 titles, one day | `FEASIBLE` | 60 s | **13.4 %** |

Big houses get good, checkable grids that say *not proven best, gap 13 %* in their own header. The one inexact step the solver ever takes — a 10-minute start grid when the 5-minute one is too large — is printed on the grid, the CLI and the sheet. [The full bench](https://github.com/brunohart/turnaround/blob/v0.1.1/docs/bench.md), including the two clever reformulations that made things worse.

## What it will not do

- Relax a term silently. Ever.
- Call a grid optimal it has not proven.
- Forecast. Demand is what your brief states; the report says who is turned away under those numbers.
- Colour-code films, carry a vendor's name, run a server, or send your grid anywhere.

## Read on

- [The full README](https://github.com/brunohart/turnaround/blob/v0.1.1/README.md) — the brief format, every term, the week, the booth's realities
- [The answer was no](https://github.com/brunohart/turnaround/blob/v0.1.1/docs/post.md) — the essay: CP-SAT for exhibition scheduling, evidence first
- [Twenty decisions](https://github.com/brunohart/turnaround/blob/v0.1.1/DECISIONS.md) and [the day-by-day log](https://github.com/brunohart/turnaround/blob/v0.1.1/docs/LOG.md) — built in fourteen days, each one ending with what was still rough

Python 3.13+. MIT. Built by [designedbybruno](https://github.com/brunohart). Not affiliated with any cinema software vendor; the brief is the tool's own format.
