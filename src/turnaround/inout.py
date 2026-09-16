"""In and out.

A plain showtimes CSV — the export any ticketing system can make — becomes a brief
skeleton and a grid the checker can read, so a house can check the grid it made by
hand before it trusts the solver with anything. A grid goes out as a calendar per
screen (iCal), a flat CSV for signage, and JSON for a website.

Four columns matter on the way in: `screen`, `title`, `start`, `runtime`. The import
reads those and ignores the rest. Our own export writes more — `film`, `format`,
`rating`, `capacity`, `preshow`, `clean`, `credits`, `date`, `day` — and the import
uses each when it is there, so a grid that goes out and comes back is the same grid.
Times are HH:MM on the day's own clock and may pass 24:00 (ADR-004): a 01:15 show on
Friday night is Friday's `25:15`.

Nothing here touches the solver. An imported grid is a hand-made grid: `status`
IMPORTED, no `stats`, `admissions` unclaimed. Its `objective` is the checker's own
re-count, because nobody maximised anything.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Any

from .check import admissions
from .model import WEEKDAYS, Brief, Film, Grid, Screen, Session, fmt_time, parse_time

REQUIRED = ("screen", "title", "start", "runtime")
"""The columns a showtimes export must have. Everything else is optional."""

ALIASES = {
    "auditorium": "screen",
    "room": "screen",
    "screen_id": "screen",
    "film_id": "film",
    "time": "start",
    "showtime": "start",
    "start_time": "start",
    "doors": "start",
    "runtime_min": "runtime",
    "running_time": "runtime",
    "duration": "runtime",
    "length": "runtime",
    "seats": "capacity",
    "clean_min": "clean",
    "preshow_min": "preshow",
    "credits_min": "credits",
    "screen_name": "screen_name",
}
"""Header spellings the import accepts for the columns it knows."""

CSV_COLUMNS = (
    "date",
    "day",
    "screen",
    "screen_name",
    "title",
    "film",
    "start",
    "feature_start",
    "feature_end",
    "clear",
    "runtime",
    "preshow",
    "clean",
    "credits",
    "format",
    "rating",
    "capacity",
    "daypart",
)
"""What the export writes, in order. `start` is the doors, on the day's clock."""


@dataclass
class Row:
    """One line of a showtimes CSV, read and typed. Optional columns are None when absent."""

    line: int
    screen: str
    title: str
    start: int
    runtime: int
    screen_name: str | None = None
    film: str | None = None
    format: str | None = None
    rating: str | None = None
    capacity: int | None = None
    preshow: int | None = None
    clean: int | None = None
    credits: int | None = None
    date: str | None = None
    day: str | None = None


def _header(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return ALIASES.get(key, key)


def _minutes(value: str, what: str, line: int) -> int:
    v = value.strip().lower().removesuffix("mins").removesuffix("min").removesuffix("m").strip()
    if not v.isdigit():
        raise ValueError(f"line {line}: {what} must be minutes, got {value.strip()!r}")
    return int(v)


def _opt_minutes(row: dict[str, str], key: str, line: int) -> int | None:
    v = row.get(key, "")
    return _minutes(v, key, line) if v and v.strip() else None


def _opt(row: dict[str, str], key: str) -> str | None:
    v = row.get(key)
    return v.strip() if v and v.strip() else None


def read_rows(text: str) -> list[Row]:
    """Read a showtimes CSV. Refuses, in a sentence, a file without the four columns, a
    time that is not HH:MM, or a runtime that is not minutes. Blank lines are skipped."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("the CSV has no header row — it needs screen, title, start, runtime")
    names = {_header(n): n for n in reader.fieldnames if n}
    missing = [c for c in REQUIRED if c not in names]
    if missing:
        raise ValueError(
            f"the CSV has no {', '.join(missing)} column — it needs screen, title, start, "
            f"runtime (it has {', '.join(n for n in reader.fieldnames if n)})"
        )
    rows: list[Row] = []
    for i, raw in enumerate(reader, start=2):
        row = {_header(k): (v or "") for k, v in raw.items() if k}
        if not any(v.strip() for v in row.values()):
            continue
        for c in REQUIRED:
            if not row.get(c, "").strip():
                raise ValueError(f"line {i}: {c} is empty")
        try:
            start = parse_time(row["start"])
        except ValueError as e:
            raise ValueError(f"line {i}: start {e}") from None
        cap = _opt(row, "capacity")
        if cap is not None and not cap.isdigit():
            raise ValueError(f"line {i}: capacity must be a number of seats, got {cap!r}")
        rows.append(
            Row(
                line=i,
                screen=row["screen"].strip(),
                title=" ".join(row["title"].split()),
                start=start,
                runtime=_minutes(row["runtime"], "runtime", i),
                screen_name=_opt(row, "screen_name"),
                film=_opt(row, "film"),
                format=_opt(row, "format"),
                rating=_opt(row, "rating"),
                capacity=int(cap) if cap is not None else None,
                preshow=_opt_minutes(row, "preshow", i),
                clean=_opt_minutes(row, "clean", i),
                credits=_opt_minutes(row, "credits", i),
                date=_opt(row, "date"),
                day=_opt(row, "day"),
            )
        )
    if not rows:
        raise ValueError("the CSV has a header and no sessions")
    return rows


def one_day(rows: list[Row], day: str | None = None, date: str | None = None) -> list[Row]:
    """The rows of one day. A CSV of several days (our own week export) must say which,
    by `day` name or `date`; a CSV of one day needs nothing."""
    # A filter on a column the CSV does not have is not a filter: --day Thu against a
    # four-column export names the week brief's day, and the rows are that day's.
    if day is not None and any(r.day for r in rows):
        picked = [r for r in rows if r.day == day]
        if not picked:
            have = list(dict.fromkeys(r.day for r in rows if r.day))
            raise ValueError(f"no day {day!r} in the CSV — the days are {', '.join(have)}")
        rows = picked
    if date is not None and any(r.date for r in rows):
        picked = [r for r in rows if r.date == date]
        if not picked:
            have = sorted({r.date for r in rows if r.date})
            raise ValueError(f"no date {date} in the CSV — the dates are {', '.join(have)}")
        rows = picked
    days = []
    for r in rows:
        k = (r.day, r.date)
        if k not in days:
            days.append(k)
    if len(days) > 1:
        names = ", ".join(" ".join(x for x in (d, dt) if x) for d, dt in days)
        raise ValueError(
            f"the CSV holds {len(days)} days ({names}) — import one with --day or --date"
        )
    return rows


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "title"


def _one_value(values: list[int | None], what: str, who: str) -> int | None:
    seen = sorted({v for v in values if v is not None})
    if len(seen) > 1:
        raise ValueError(
            f"{who} has more than one {what} in the CSV ({', '.join(map(str, seen))}) — it has one"
        )
    return seen[0] if seen else None


def skeleton(
    rows: list[Row],
    house: str,
    *,
    capacity: int = 100,
    preshow: int = 20,
    clean: int = 20,
) -> tuple[Brief, list[str]]:
    """A brief skeleton from the rows alone: the screens they name (capacity from the
    CSV or the stated default), the titles they play (runtime, format, rating from the
    CSV), and a policy with the house open from the first start's hour to the last start,
    the default stagger, and the preshow and clean the CSV states or the defaults. No
    terms: the house writes those. Returns the brief and the assumptions made, in
    sentences, so the house knows what to edit."""
    notes: list[str] = []
    rows = one_day(rows)
    # Screens, in order of first appearance.
    screen_ids: list[str] = []
    for r in rows:
        if r.screen not in screen_ids:
            screen_ids.append(r.screen)
    # Preshow: the CSV's, per format, else the default. Clean: the CSV's, per screen.
    preshow_by_format: dict[str, int] = {}
    for fmt in sorted({r.format or "2D" for r in rows}):
        v = _one_value([r.preshow for r in rows if (r.format or "2D") == fmt], "preshow", fmt)
        if v is not None:
            preshow_by_format[fmt] = v
    if preshow_by_format:
        preshow_min = Counter(preshow_by_format.values()).most_common(1)[0][0]
        preshow_by_format = {k: v for k, v in preshow_by_format.items() if v != preshow_min}
    else:
        preshow_min = preshow
        notes.append(f"preshow {preshow} min assumed — the CSV does not say")
    cleans = {
        sid: _one_value([r.clean for r in rows if r.screen == sid], "clean", f"screen {sid}")
        for sid in screen_ids
    }
    if any(v is not None for v in cleans.values()):
        clean_min = Counter(v for v in cleans.values() if v is not None).most_common(1)[0][0]
    else:
        clean_min = clean
        notes.append(f"turnaround {clean} min assumed — the CSV does not say")
    screens = []
    assumed_cap = []
    for sid in screen_ids:
        mine = [r for r in rows if r.screen == sid]
        caps = {r.capacity for r in mine if r.capacity is not None}
        cap = max(caps) if caps else capacity
        if not caps:
            assumed_cap.append(sid)
        names = {r.screen_name for r in mine if r.screen_name}
        c = cleans[sid]
        screens.append(
            Screen(
                id=sid,
                name=names.pop() if len(names) == 1 else None,
                capacity=cap,
                formats=sorted({r.format or "2D" for r in mine}),
                clean_min=c if c is not None and c != clean_min else None,
            )
        )
    if assumed_cap:
        notes.append(
            f"{capacity} seats assumed for screen{'s' if len(assumed_cap) != 1 else ''} "
            f"{', '.join(assumed_cap)} — the CSV does not say"
        )
    # Titles, in order of first appearance; the id is the CSV's or a slug of the title.
    films: list[Film] = []
    ids: set[str] = set()
    for title in dict.fromkeys(r.title for r in rows):
        mine = [r for r in rows if r.title == title]
        runtime = _one_value([r.runtime for r in mine], "runtime", title)
        fmts = {r.format or "2D" for r in mine}
        if len(fmts) > 1:
            raise ValueError(
                f"{title} is {' in one row and '.join(sorted(fmts))} in another — a title has "
                "one format; give the other print its own title"
            )
        fid = next((r.film for r in mine if r.film), None) or slug(title)
        base, n = fid, 2
        while fid in ids:
            fid = f"{base}-{n}"
            n += 1
        ids.add(fid)
        credits = _one_value([r.credits for r in mine], "credits", title) or 0
        films.append(
            Film(
                id=fid,
                title=title,
                runtime_min=runtime or 0,
                credits_min=credits,
                format=fmts.pop(),
                rating=next((r.rating for r in mine if r.rating), None),
            )
        )
    first = min(r.start for r in rows)
    last = max(r.start for r in rows)
    open_min = first - first % 60
    dates = {r.date for r in rows if r.date}
    days = {r.day for r in rows if r.day}
    brief = Brief.model_validate(
        {
            "house": house,
            "date": dates.pop() if len(dates) == 1 else None,
            "weekday": next(iter(days)) if len(days) == 1 and days <= set(WEEKDAYS) else None,
            "screens": screens,
            "films": films,
            "policy": {
                "open": fmt_time(open_min) if open_min < 1440 else f"{open_min // 60}:00",
                "last_start": _hhmm(last),
                "preshow_min": preshow_min,
                "preshow_by_format": preshow_by_format,
                "clean_min": clean_min,
            },
        }
    )
    notes.append(
        f"house open {brief.policy.open}, last start {brief.policy.last_start} — from the "
        "starts; the stagger is the default 1 in 10; no terms — write them in and check again"
    )
    return brief, notes


def _hhmm(minutes: int) -> str:
    """HH:MM on the day's clock, hours past 24 kept (ADR-004): 1515 -> '25:15'."""
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _find_screen(brief: Brief, row: Row) -> Screen:
    for s in brief.screens:
        if s.id == row.screen:
            return s
    for s in brief.screens:
        if s.name and s.name.lower() == row.screen.lower():
            return s
    have = ", ".join(f"{s.id}" + (f" ({s.name})" if s.name else "") for s in brief.screens)
    raise ValueError(
        f"line {row.line}: no screen {row.screen!r} on the brief — the screens are {have}"
    )


def _find_film(brief: Brief, row: Row) -> Film:
    if row.film:
        for f in brief.films:
            if f.id == row.film:
                return f
    for f in brief.films:
        if f.title.lower() == row.title.lower() or f.id == row.title:
            return f
    have = ", ".join(f.title for f in brief.films)
    raise ValueError(f"line {row.line}: no title {row.title!r} on the brief — the slate is {have}")


def grid_from_rows(
    brief: Brief, rows: list[Row], *, date: str | None = None
) -> tuple[Grid, list[str]]:
    """The rows as a grid against `brief`: each row's screen and title resolved (by id,
    then by name), each session's feature and clear times derived from the brief's
    preshow, runtime, credits and turnaround — the CSV's runtime is checked against the
    brief's and the brief's is used. Nothing is validated here beyond the references;
    that is the checker's job, and this grid is for it."""
    notes: list[str] = []
    rows = one_day(rows)
    sessions: list[Session] = []
    said: set[str] = set()
    for r in rows:
        scr = _find_screen(brief, r)
        f = _find_film(brief, r)
        if r.runtime != f.runtime_min and f.id not in said:
            said.add(f.id)
            notes.append(
                f"{f.title} runs {f.runtime_min} min on the brief and {r.runtime} in the CSV "
                "— the brief's figure is used"
            )
        feature_start = r.start + brief.preshow_for(f)
        _, clear = brief.turnaround_of(scr, f, r.start)
        sessions.append(
            Session(
                screen=scr.id,
                film=f.id,
                start=r.start,
                feature_start=feature_start,
                feature_end=feature_start + f.runtime_min,
                clear=clear,
            )
        )
    order = {s.id: i for i, s in enumerate(brief.screens)}
    sessions.sort(key=lambda s: (order[s.screen], s.start))
    dates = {r.date for r in rows if r.date}
    grid = Grid(
        house=brief.house,
        date=date or (dates.pop() if len(dates) == 1 else None) or brief.date,
        status="IMPORTED",
        objective=0.0,
        admissions=None,
        solve_seconds=0.0,
        sessions=sessions,
    )
    grid.objective = round(sum(a.admissions for a in admissions(brief, grid)), 1)
    return grid, notes


def import_csv(
    text: str,
    *,
    brief: Brief | None = None,
    house: str = "A house",
    day: str | None = None,
    date: str | None = None,
    capacity: int = 100,
    preshow: int = 20,
    clean: int = 20,
) -> tuple[Brief, Grid, list[str]]:
    """The whole way in: read the CSV, take one day of it, build or use the brief, make
    the grid. Returns the brief (the skeleton, or the one given), the grid, and the
    assumptions and discrepancies in sentences."""
    rows = one_day(read_rows(text), day=day, date=date)
    notes: list[str] = []
    if brief is None:
        brief, notes = skeleton(rows, house, capacity=capacity, preshow=preshow, clean=clean)
    grid, more = grid_from_rows(brief, rows, date=date)
    return brief, grid, notes + more


# ---- out -------------------------------------------------------------------------


Day = tuple[str | None, Brief, Grid]
"""One day to export: its name in the week (None for a lone day), its brief, its grid."""


def _date_of(brief: Brief, grid: Grid) -> str | None:
    return grid.date or brief.date


def _row(day: str | None, brief: Brief, grid: Grid, s: Session) -> dict[str, Any]:
    scr = brief.screen(s.screen)
    f = brief.film(s.film)
    dp = brief.policy.daypart_at(s.start)
    turn_begin, _ = brief.turnaround_of(scr, f, s.start)
    return {
        "date": _date_of(brief, grid) or "",
        "day": day or brief.day_name or "",
        "screen": scr.id,
        "screen_name": scr.label,
        "title": f.title,
        "film": f.id,
        "start": _hhmm(s.start),
        "feature_start": _hhmm(s.feature_start),
        "feature_end": _hhmm(s.feature_end),
        "clear": _hhmm(s.clear),
        "runtime": f.runtime_min,
        "preshow": brief.preshow_for(f),
        "clean": s.clear - turn_begin,
        "credits": f.credits_min,
        "format": f.format,
        "rating": f.rating or "",
        "capacity": scr.capacity,
        "daypart": dp.name if dp else "",
    }


def export_csv(days: list[Day]) -> str:
    """A flat CSV for signage: one line per session, screen by screen, start by start,
    day by day. The columns are `CSV_COLUMNS`; `import` reads it back whole."""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    w.writeheader()
    for day, brief, grid in days:
        order = {s.id: i for i, s in enumerate(brief.screens)}
        for s in sorted(grid.sessions, key=lambda x: (order[x.screen], x.start)):
            w.writerow(_row(day, brief, grid, s))
    return out.getvalue()


def export_json(days: list[Day]) -> dict[str, Any]:
    """JSON for a website: the house, its titles, and each day's screens with their
    sessions in clock time. `start` is what the sign shows (`01:15`); `minutes` is
    minutes after the day's midnight (1515), so a late show still belongs to its day."""
    house = days[0][1].house
    titles: dict[str, dict[str, Any]] = {}
    out_days = []
    for day, brief, grid in days:
        for f in brief.films:
            titles.setdefault(
                f.id,
                {
                    "id": f.id,
                    "title": f.title,
                    "runtime": f.runtime_min,
                    "format": f.format,
                    "rating": f.rating,
                },
            )
        screens = []
        for scr in brief.screens:
            sessions = []
            for s in grid.by_screen().get(scr.id, []):
                f = brief.film(s.film)
                dp = brief.policy.daypart_at(s.start)
                sessions.append(
                    {
                        "title": f.title,
                        "film": f.id,
                        "start": fmt_time(s.start),
                        "minutes": s.start,
                        "feature_start": fmt_time(s.feature_start),
                        "feature_end": fmt_time(s.feature_end),
                        "clear": fmt_time(s.clear),
                        "runtime": f.runtime_min,
                        "format": f.format,
                        "rating": f.rating,
                        "daypart": dp.name if dp else None,
                        "prime": brief.policy.is_prime(s.start),
                    }
                )
            screens.append(
                {
                    "id": scr.id,
                    "name": scr.label,
                    "capacity": scr.capacity,
                    "formats": scr.formats,
                    "sessions": sessions,
                }
            )
        out_days.append(
            {
                "day": day or brief.day_name,
                "date": _date_of(brief, grid),
                "status": grid.status,
                "sessions": len(grid.sessions),
                "screens": screens,
            }
        )
    return {"house": house, "titles": list(titles.values()), "days": out_days}


def _ical_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 folds content lines at 75 octets; the continuation begins with a space."""
    out = []
    data = line.encode()
    while len(data) > 74:
        cut = 74
        while cut > 0 and (data[cut] & 0xC0) == 0x80:  # never split a UTF-8 sequence
            cut -= 1
        out.append(data[:cut].decode())
        data = b" " + data[cut:]
    out.append(data.decode())
    return "\r\n".join(out)


def _stamp(d: str, minutes: int) -> str:
    when = datetime.combine(_date.fromisoformat(d), datetime.min.time()) + timedelta(
        minutes=minutes
    )
    return when.strftime("%Y%m%dT%H%M%S")


def export_ical(days: list[Day], screen_id: str) -> str:
    """One calendar for one screen across the days given: an event per session from
    doors to clear, the feature and the turnaround in the description. Floating local
    time, no zone: the calendar is the booth's and the booth is in one place. Every day
    needs a date; a grid without one is refused."""
    house = days[0][1].house
    label = next((s.label for _, b, _ in days for s in b.screens if s.id == screen_id), screen_id)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//turnaround//the showtime grid//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ical_text(house + ' · ' + label)}",
    ]
    for day, brief, grid in days:
        d = _date_of(brief, grid)
        if d is None:
            raise ValueError(
                f"{day or 'the day'} has no date — a calendar needs one; give --date, or put "
                "`date` on the brief"
            )
        for s in grid.by_screen().get(screen_id, []):
            f = brief.film(s.film)
            about = (
                f"Doors {fmt_time(s.start)} · feature {fmt_time(s.feature_start)}–"
                f"{fmt_time(s.feature_end)} · clear {fmt_time(s.clear)} · {f.format}"
                + (f" · {f.rating}" if f.rating else "")
                + (" · prime" if brief.policy.is_prime(s.start) else "")
            )
            lines += [
                "BEGIN:VEVENT",
                f"UID:{d}-{screen_id}-{s.start}@turnaround",
                f"DTSTAMP:{d.replace('-', '')}T000000Z",
                f"DTSTART:{_stamp(d, s.start)}",
                f"DTEND:{_stamp(d, s.clear)}",
                f"SUMMARY:{_ical_text(f.title)}",
                f"LOCATION:{_ical_text(label)}",
                f"DESCRIPTION:{_ical_text(about)}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def screen_ids(days: list[Day]) -> list[str]:
    """Every screen the days name, in the order the briefs list them."""
    seen: list[str] = []
    for _, brief, _ in days:
        for scr in brief.screens:
            if scr.id not in seen:
                seen.append(scr.id)
    return seen


def export_json_text(days: list[Day]) -> str:
    return json.dumps(export_json(days), indent=2, ensure_ascii=False) + "\n"
