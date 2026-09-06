# Log

Newest first. One entry per slot.

## Day 0 — 2026-09-06 — The grid exists

**Shipped.** The brief as Pydantic models (`model.py`): screens with capacity, formats and a clean-time override; films with runtime, format, weight, optional daypart multipliers and distributor `Terms` (min/max shows, prime shows, exclusive screen, start window, screen and capacity restrictions); a `Policy` for hours, preshow, turnaround, stagger, slot size and dayparts. The CP-SAT model (`solve.py`): one boolean per (screen, film, start), an optional interval per boolean sized `preshow + runtime + clean`, `NoOverlap` per screen, sliding-window stagger house-wide, every term as a linear constraint, exclusive screens via a per-screen indicator that forbids every other title there. Objective: weighted seats on offer (ADR-006, a placeholder). The independent checker (`check.py`) with a proof table. CLI `plan` / `check` / `render` / `validate`. The week sheet (`render.py` + `templates/sheet.html.j2`). Sixteen tests. CI on Ubuntu. `scripts/build.sh`, `test.sh`, `run.sh`, `slot.sh`.

**Solver.** The Regent (3 screens · 5 titles · one PLF exclusive with a prime guarantee · a kids' 3D title capped at 17:00 · a horror title held to 16:00 or later): `OPTIMAL` in 0.957 s, 15 sessions, all 17 checks green. The grid reads right: the exclusive owns Screen 1 with four shows including 17:30; the family title takes 14:50 and 16:55 on the only 3D room; the horror closes both smaller rooms; no two starts within 10 minutes.

**Broke and fixed.** OR-Tools 9.15 removed the CamelCase API from its type stubs and `objective_value` became a property; the model was written against the old names and mypy caught all thirteen before the tests did. The tests then caught the property.

**For Bruno.** Nothing today. The launchd agent, the skill, the Linear project and the GitHub repository were created in the same session.

**Still rough.** The objective is judgment-weighted seats, not admissions (Day 3). `INFEASIBLE` is a verdict without a reason (Day 1). The sheet's identity pass is a first draft (Day 6). The infeasible-terms test spends its full 10 s limit proving nothing can work; a smaller limit or an early cut would make the suite faster.
