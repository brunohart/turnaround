---
name: turnaround-daily
description: Turnaround (cinema showtime grid solver) — daily autonomous build slot (Day-gated from 2026-09-06; backlog-driven after Day 13). Invokes the turnaround-build skill.
---

Run one day of the Turnaround build.

Execute by invoking the `turnaround-build` skill (`~/.claude/skills/turnaround-build/SKILL.md`) with no argument; it derives the day from the date. It works in `/Users/brunohart/turnaround`, builds and tests with uv, regenerates and screenshots the week sheets, commits, pushes to `origin main`, and closes the day's Linear issue in project "Turnaround — the showtime grid solver".

After the fourteen-day playbook the skill works the Linear backlog (highest-priority Todo without `bruno-gated`); if the backlog is empty it logs "backlog empty" and exits cleanly.

Note: a launchd agent (`com.designedbybruno.turnaround-slot`, 08:45 Pacific/Auckland) also fires `~/turnaround/scripts/slot.sh`, which is idempotent per calendar day via `build/slots/<date>.ran`. If you enable this scheduled task in the app as well, unload the launchd agent to avoid two runs:
`launchctl bootout gui/$(id -u)/com.designedbybruno.turnaround-slot`.
