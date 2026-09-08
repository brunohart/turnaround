"""The brief and the grid.

A *brief* is what a programmer hands the solver: the house (screens), the slate
(films with their distributor terms), and the house policy (hours, prime window,
turnaround, stagger). A *grid* is what comes back: sessions on screens with
start times, plus the proof that every term was honoured.

Times are minutes after midnight on the day being planned. "24:30" is a valid
last-start time (a late show), so minutes may exceed 1440.

A *week brief* is seven briefs that share a house and a slate: each day may
override the policy (Friday's late show) and a film's terms (the opening
exclusive lifts on Monday). It unfolds into one plain `Brief` per day, so the
solver and the checker never learn what a week is.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_time(value: str | int) -> int:
    """'19:30' -> 1170. Hours past 24 are allowed for late shows ('25:00' -> 1500)."""
    if isinstance(value, int):
        return value
    m = _TIME.match(value.strip())
    if not m:
        raise ValueError(f"time must look like HH:MM, got {value!r}")
    h, mnt = int(m.group(1)), int(m.group(2))
    if mnt >= 60:
        raise ValueError(f"minutes must be < 60, got {value!r}")
    return h * 60 + mnt


def fmt_time(minutes: int) -> str:
    """1170 -> '19:30'. Minutes past midnight fold to the clock ('25:00' -> '01:00')."""
    h, m = divmod(minutes % 1440, 60)
    return f"{h:02d}:{m:02d}"


Minutes = Annotated[int, Field(ge=0)]


class Screen(BaseModel):
    """One auditorium."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    capacity: int = Field(gt=0)
    formats: list[str] = Field(default_factory=lambda: ["2D"])
    clean_min: int | None = Field(default=None, ge=0, description="Overrides policy.clean_min")

    @property
    def label(self) -> str:
        return self.name or self.id


class Terms(BaseModel):
    """What the distributor's booking says this film must get today.

    Every field is a hard constraint. If the house cannot honour them all the
    solver says so rather than quietly dropping one.
    """

    model_config = ConfigDict(extra="forbid")

    min_shows: int = Field(default=0, ge=0, description="At least this many sessions today")
    max_shows: int | None = Field(
        default=None, ge=0, description="At most this many sessions today"
    )
    prime_shows: int = Field(
        default=0, ge=0, description="At least this many sessions starting in the prime window"
    )
    exclusive_screen: bool = Field(
        default=False, description="Must have at least one screen playing nothing else today"
    )
    earliest_start: str | None = Field(default=None, description="HH:MM")
    latest_start: str | None = Field(default=None, description="HH:MM")
    screens: list[str] | None = Field(default=None, description="Only these screen ids")
    min_capacity: int | None = Field(default=None, ge=0, description="Only screens this big")


DEFAULT_DECAY = 0.6
"""Each further session of a title in the same daypart draws this fraction of the one before."""

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Demand(BaseModel):
    """What the programmer expects a title to draw, stated so the file carries its reasoning.

    `per_session` is expected admissions for the *first* session of the title in each
    daypart on an ordinary day. Each further session in the same daypart draws `decay`
    times the one before: the second 19:00 show earns less. `weekday` multiplies by the
    day's name; `holiday` applies when the day's policy says school holidays. None of it
    is a forecast the tool makes; it is the house's own assumptions, written down.
    """

    model_config = ConfigDict(extra="forbid")

    per_session: dict[str, float] = Field(
        description="Daypart name -> admissions the first session there would draw"
    )
    decay: float = Field(
        default=DEFAULT_DECAY,
        gt=0,
        le=1,
        description="Fraction of the previous session's admissions the next one in the same "
        "daypart draws",
    )
    weekday: dict[str, float] = Field(
        default_factory=dict, description="Multiplier by day name, e.g. {'Sat': 1.5}"
    )
    holiday: float = Field(
        default=1.0, gt=0, description="Multiplier when policy.school_holiday is true"
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Where the numbers came from, in words"
    )

    @field_validator("per_session", "weekday")
    @classmethod
    def _non_negative(cls, v: dict[str, float]) -> dict[str, float]:
        bad = [k for k, x in v.items() if x < 0]
        if bad:
            raise ValueError(f"demand cannot be negative: {bad}")
        return v


class Film(BaseModel):
    """A title on the slate."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    runtime_min: int = Field(gt=0, description="Feature running time, credits included")
    format: str = "2D"
    rating: str | None = None
    weight: float = Field(
        default=1.0,
        gt=0,
        description="Relative demand for a title with no demand block. 2.0 draws twice 1.0",
    )
    daypart_weights: dict[str, float] | None = Field(
        default=None,
        description="Optional per-daypart multipliers for a title with no demand block, "
        "e.g. {'matinee': 1.4, 'late': 0.2}",
    )
    demand: Demand | None = Field(
        default=None,
        description="Expected admissions by daypart. Without it, `weight` and the house's "
        "assumed_admissions stand in",
    )
    terms: Terms = Field(default_factory=Terms)


class Daypart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    start: str
    end: str
    weight: float = Field(gt=0)

    @property
    def start_min(self) -> int:
        return parse_time(self.start)

    @property
    def end_min(self) -> int:
        return parse_time(self.end)


DEFAULT_DAYPARTS = [
    Daypart(name="matinee", start="09:00", end="14:00", weight=0.55),
    Daypart(name="afternoon", start="14:00", end="17:30", weight=0.75),
    Daypart(name="prime", start="17:30", end="20:45", weight=1.0),
    Daypart(name="late", start="20:45", end="27:00", weight=0.65),
]


class Policy(BaseModel):
    """How this house runs a day."""

    model_config = ConfigDict(extra="forbid")

    open: str = Field(default="10:00", description="First possible start")
    last_start: str = Field(default="21:30", description="Latest a session may start")
    preshow_min: int = Field(default=20, ge=0, description="Ads and trailers before the feature")
    clean_min: int = Field(
        default=20, ge=0, description="Turnaround: credits out to next preshow in"
    )
    stagger_min: int = Field(
        default=10, ge=0, description="Minimum gap between any two starts across the house"
    )
    slot_min: int = Field(default=5, gt=0, description="Start-time granularity")
    prime_start: str = "17:30"
    prime_end: str = "20:45"
    dayparts: list[Daypart] = Field(default_factory=lambda: list(DEFAULT_DAYPARTS))
    school_holiday: bool = Field(
        default=False, description="School holidays today: demand blocks apply their uplift"
    )
    assumed_admissions: float = Field(
        default=100.0,
        gt=0,
        description="For a title with no demand block: admissions its first prime session "
        "would draw at weight 1.0. Dayparts scale it by their weight",
    )

    @property
    def open_min(self) -> int:
        return parse_time(self.open)

    @property
    def last_start_min(self) -> int:
        return parse_time(self.last_start)

    @property
    def prime_start_min(self) -> int:
        return parse_time(self.prime_start)

    @property
    def prime_end_min(self) -> int:
        return parse_time(self.prime_end)

    def daypart_at(self, start: int) -> Daypart | None:
        for d in self.dayparts:
            if d.start_min <= start < d.end_min:
                return d
        return None

    def slot_weight(self, start: int) -> float:
        d = self.daypart_at(start)
        return d.weight if d else 0.5

    def is_prime(self, start: int) -> bool:
        return self.prime_start_min <= start < self.prime_end_min

    @model_validator(mode="after")
    def _check(self) -> Policy:
        if self.last_start_min < self.open_min:
            raise ValueError("last_start is before open")
        for d in self.dayparts:
            if d.end_min <= d.start_min:
                raise ValueError(f"daypart {d.name} ends before it starts")
        return self


class Brief(BaseModel):
    """Everything the solver needs for one day."""

    model_config = ConfigDict(extra="forbid")

    house: str
    date: str | None = Field(default=None, description="ISO date, informational")
    weekday: str | None = Field(
        default=None,
        description="Mon…Sun, for demand multipliers. Derived from `date` when absent",
    )
    screens: list[Screen] = Field(min_length=1)
    films: list[Film] = Field(min_length=1)
    policy: Policy = Field(default_factory=Policy)

    @field_validator("screens")
    @classmethod
    def _unique_screens(cls, v: list[Screen]) -> list[Screen]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("screen ids must be unique")
        return v

    @field_validator("films")
    @classmethod
    def _unique_films(cls, v: list[Film]) -> list[Film]:
        ids = [f.id for f in v]
        if len(ids) != len(set(ids)):
            raise ValueError("film ids must be unique")
        return v

    @model_validator(mode="after")
    def _refs(self) -> Brief:
        screen_ids = {s.id for s in self.screens}
        for f in self.films:
            if f.terms.screens:
                unknown = set(f.terms.screens) - screen_ids
                if unknown:
                    raise ValueError(f"film {f.id} names unknown screens {sorted(unknown)}")
            if f.terms.earliest_start:
                parse_time(f.terms.earliest_start)
            if f.terms.latest_start:
                parse_time(f.terms.latest_start)
            if f.demand is not None:
                names = {d.name for d in self.policy.dayparts}
                missing = sorted(set(f.demand.per_session) - names)
                if missing:
                    raise ValueError(
                        f"film {f.id} forecasts a daypart the policy does not define: "
                        f"{missing}; the dayparts are {sorted(names)}"
                    )
        if self.date is not None:
            date.fromisoformat(self.date)
        return self

    @property
    def day_name(self) -> str | None:
        """Mon…Sun: the stated weekday, else the date's, else nothing."""
        if self.weekday:
            return self.weekday
        if self.date:
            return WEEKDAYS[date.fromisoformat(self.date).weekday()]
        return None

    def expected(self, film: Film, daypart: Daypart | None, rank: int) -> float:
        """Admissions the `rank`-th session (0 first) of `film` in `daypart` would draw
        today, capacity ignored. A title with a demand block speaks for itself; one
        without it is `weight` x daypart weight x the house's assumed_admissions. A
        start outside every daypart draws half the assumed figure, as before."""
        p = self.policy
        d = film.demand
        if d is not None:
            base = d.per_session.get(daypart.name, 0.0) if daypart else 0.0
            day = self.day_name
            if day is not None:
                base *= d.weekday.get(day, 1.0)
            if p.school_holiday:
                base *= d.holiday
            decay = d.decay
        else:
            w = daypart.weight if daypart else 0.5
            if film.daypart_weights and daypart and daypart.name in film.daypart_weights:
                w *= film.daypart_weights[daypart.name]
            base = film.weight * w * p.assumed_admissions
            decay = DEFAULT_DECAY
        return base * decay**rank

    def screen(self, screen_id: str) -> Screen:
        for s in self.screens:
            if s.id == screen_id:
                return s
        raise KeyError(screen_id)

    def film(self, film_id: str) -> Film:
        for f in self.films:
            if f.id == film_id:
                return f
        raise KeyError(film_id)

    def clean_for(self, screen: Screen) -> int:
        return screen.clean_min if screen.clean_min is not None else self.policy.clean_min

    def block_len(self, screen: Screen, film: Film) -> int:
        """Minutes a session occupies the screen: preshow + feature + clean."""
        return self.policy.preshow_min + film.runtime_min + self.clean_for(screen)

    def can_play(self, screen: Screen, film: Film) -> bool:
        if film.format not in screen.formats:
            return False
        t = film.terms
        if t.screens is not None and screen.id not in t.screens:
            return False
        return not (t.min_capacity is not None and screen.capacity < t.min_capacity)


class Session(BaseModel):
    """One session on the grid."""

    model_config = ConfigDict(extra="forbid")

    screen: str
    film: str
    start: int = Field(description="Minutes after midnight when the preshow begins")
    feature_start: int
    feature_end: int
    clear: int = Field(description="Minutes after midnight when the screen is clean again")

    @property
    def start_hhmm(self) -> str:
        return fmt_time(self.start)

    @property
    def feature_start_hhmm(self) -> str:
        return fmt_time(self.feature_start)

    @property
    def feature_end_hhmm(self) -> str:
        return fmt_time(self.feature_end)


class TermRef(BaseModel):
    """One distributor term on one film: the unit the solver can name or give up."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    film: str
    term: str = Field(description="A field of Terms: min_shows, prime_shows, exclusive_screen…")
    value: str = Field(default="", description="The term's value as written, for the record")

    def __str__(self) -> str:
        return f"{self.film} {self.term}{' ' + self.value if self.value else ''}"


class Grid(BaseModel):
    """The solver's answer for one day."""

    model_config = ConfigDict(extra="forbid")

    house: str
    date: str | None = None
    status: str
    objective: float = Field(
        description="What the solver maximised: expected admissions less the hold penalty"
    )
    admissions: float | None = Field(
        default=None,
        description="The solver's claim: expected admissions, seat by seat under capacity. "
        "None on a grid nobody solved",
    )
    hold_paid: float = Field(
        default=0.0, ge=0, description="Hold penalty this day paid, in expected admissions"
    )
    solve_seconds: float
    sessions: list[Session]
    conflict: list[TermRef] = Field(
        default_factory=list,
        description="On INFEASIBLE: a minimal set of terms that cannot hold together",
    )
    conflict_alone: bool = Field(
        default=False, description="Each term in `conflict` is infeasible by itself"
    )
    relaxed: list[TermRef] = Field(
        default_factory=list,
        description="Terms the solver was told it could drop, and did. Never silent (ADR-002)",
    )

    def by_screen(self) -> dict[str, list[Session]]:
        out: dict[str, list[Session]] = {}
        for s in sorted(self.sessions, key=lambda x: (x.screen, x.start)):
            out.setdefault(s.screen, []).append(s)
        return out

    def by_film(self) -> dict[str, list[Session]]:
        out: dict[str, list[Session]] = {}
        for s in sorted(self.sessions, key=lambda x: (x.film, x.start)):
            out.setdefault(s.film, []).append(s)
        return out


HOLD_DAYS_DEFAULT = ["Mon", "Tue", "Wed", "Thu"]


class DayOverride(BaseModel):
    """One day of the week: a name, a date, and what differs from the base brief."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Thu, Fri, … — the day as the booth calls it")
    date: str | None = Field(default=None, description="ISO date, informational")
    policy: dict[str, Any] = Field(
        default_factory=dict, description="Policy fields that differ today, e.g. last_start"
    )
    terms: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per film id, the term fields that differ today, e.g. exclusive_screen",
    )


class WeekBrief(BaseModel):
    """Seven days (or fewer) sharing a house, a slate and a base policy.

    `day(i)` is the plain Brief for that day with the overrides applied. The
    hold days are the run of the week where a title should keep the same start
    times if it can; the solver pays `hold_penalty` expected admissions for each
    title whose starts on a hold day differ from the first hold day's.
    """

    model_config = ConfigDict(extra="forbid")

    house: str
    screens: list[Screen] = Field(min_length=1)
    films: list[Film] = Field(min_length=1)
    policy: Policy = Field(default_factory=Policy)
    days: list[DayOverride] = Field(min_length=1, max_length=7)
    hold_days: list[str] = Field(
        default_factory=lambda: list(HOLD_DAYS_DEFAULT),
        description="Days on which a title should keep the same starts, where it can",
    )
    hold_penalty: float = Field(
        default=60.0,
        ge=0,
        description="Expected admissions the objective gives up per title that changes its "
        "times on a hold day",
    )

    @model_validator(mode="after")
    def _check(self) -> WeekBrief:
        names = [d.name for d in self.days]
        if len(names) != len(set(names)):
            raise ValueError("day names must be unique")
        film_ids = {f.id for f in self.films}
        for d in self.days:
            unknown = set(d.terms) - film_ids
            if unknown:
                raise ValueError(f"day {d.name} sets terms for unknown films {sorted(unknown)}")
            self.day(self.days.index(d))  # every day must be a valid Brief on its own
        return self

    @property
    def hold_indices(self) -> list[int]:
        """Positions of the hold days, in week order."""
        return [i for i, d in enumerate(self.days) if d.name in self.hold_days]

    def day(self, i: int) -> Brief:
        """The plain brief for day i, overrides applied."""
        d = self.days[i]
        policy = Policy.model_validate({**self.policy.model_dump(), **d.policy})
        films = []
        for f in self.films:
            if f.id in d.terms:
                terms = Terms.model_validate({**f.terms.model_dump(), **d.terms[f.id]})
                films.append(f.model_copy(update={"terms": terms}))
            else:
                films.append(f)
        return Brief(
            house=self.house,
            date=d.date,
            weekday=d.name if d.name in WEEKDAYS else None,
            screens=self.screens,
            films=films,
            policy=policy,
        )

    def briefs(self) -> list[Brief]:
        return [self.day(i) for i in range(len(self.days))]

    def film_title(self, film_id: str) -> str:
        for f in self.films:
            if f.id == film_id:
                return f.title
        raise KeyError(film_id)


class WeekGrid(BaseModel):
    """The solver's answer for a week: one grid per day, and which titles held their times."""

    model_config = ConfigDict(extra="forbid")

    house: str
    days: list[str] = Field(description="Day names, in order, matching `grids`")
    grids: list[Grid]
    hold_days: list[str] = Field(default_factory=list)
    held: list[str] = Field(
        default_factory=list,
        description="Film ids whose start times are the same on every hold day that solved",
    )
    solve_seconds: float = 0.0

    @property
    def status(self) -> str:
        """OPTIMAL if every day is, else the worst day's status."""
        order = ["INFEASIBLE", "UNKNOWN", "MODEL_INVALID", "FEASIBLE", "OPTIMAL"]
        worst = min(self.grids, key=lambda g: order.index(g.status) if g.status in order else 0)
        return worst.status

    @property
    def sessions(self) -> int:
        return sum(len(g.sessions) for g in self.grids)

    @property
    def objective(self) -> float:
        return sum(g.objective for g in self.grids)

    def grid(self, name: str) -> Grid:
        return self.grids[self.days.index(name)]
