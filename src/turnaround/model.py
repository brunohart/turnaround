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
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

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
    open: str | None = Field(
        default=None, description="HH:MM; this screen's first possible start, overrides policy"
    )
    last_start: str | None = Field(
        default=None, description="HH:MM; this screen's latest start, overrides policy"
    )

    @property
    def label(self) -> str:
        return self.name or self.id

    @model_validator(mode="after")
    def _hours(self) -> Screen:
        if self.open is not None:
            parse_time(self.open)
        if self.last_start is not None:
            parse_time(self.last_start)
        if (
            self.open is not None
            and self.last_start is not None
            and parse_time(self.last_start) < parse_time(self.open)
        ):
            raise ValueError(f"screen {self.id}: last_start {self.last_start} is before open")
        return self


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
    plf_lock: bool = Field(
        default=False,
        description="Every session on a PLF room belongs to this title: no other title plays a "
        "PLF screen while this one is booked",
    )
    min_shows_per_week: int = Field(
        default=0,
        ge=0,
        description="At least this many sessions across the week. A week term: a day brief "
        "refuses it",
    )
    prime_shows_per_week: int = Field(
        default=0,
        ge=0,
        description="At least this many sessions starting in prime across the week. A week term",
    )
    exclusive_until: str | None = Field(
        default=None,
        description="A day name: exclusive_screen holds on every day of the week up to and "
        "including this one, then lifts. A week term",
    )


WEEK_TERMS = ("min_shows_per_week", "prime_shows_per_week", "exclusive_until")
"""Terms that mean nothing on one day. A day brief refuses them; a week unfolds them."""

TERM_SCOPE = {
    "min_shows": "day",
    "max_shows": "day",
    "prime_shows": "day",
    "exclusive_screen": "day",
    "earliest_start": "day",
    "latest_start": "day",
    "screens": "day",
    "min_capacity": "day",
    "plf_lock": "day",
    "min_shows_per_week": "week",
    "prime_shows_per_week": "week",
    "exclusive_until": "week",
}


def week_terms_set(t: Terms) -> list[tuple[str, str]]:
    """The week-scoped terms this booking carries, as (name, value as written)."""
    out = []
    if t.min_shows_per_week:
        out.append(("min_shows_per_week", str(t.min_shows_per_week)))
    if t.prime_shows_per_week:
        out.append(("prime_shows_per_week", str(t.prime_shows_per_week)))
    if t.exclusive_until:
        out.append(("exclusive_until", t.exclusive_until))
    return out


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
    credits_min: int = Field(
        default=0,
        ge=0,
        description="Closing credits: the turnaround may begin this many minutes before the "
        "feature ends, because the room empties while they roll",
    )
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

    @model_validator(mode="after")
    def _credits(self) -> Film:
        if self.credits_min > self.runtime_min:
            raise ValueError(
                f"film {self.id}: credits_min {self.credits_min} is longer than the feature"
            )
        return self


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
    preshow_by_format: dict[str, int] = Field(
        default_factory=dict,
        description="Preshow per format where it differs, e.g. {'3D': 25, 'PLF': 30}: 3D hands "
        "out glasses, PLF runs a longer reel",
    )
    clean_min: int = Field(
        default=20, ge=0, description="Turnaround: credits out to next preshow in"
    )
    max_concurrent_turnarounds: int | None = Field(
        default=None,
        ge=1,
        description="Rooms the floor staff can clear at once. Two ushers cannot clear three",
    )
    stagger_min: int = Field(
        default=10,
        ge=0,
        description="The stagger window: at most max_starts_per_window starts house-wide in any "
        "run of this many minutes. The default, 1 in 10, keeps every two starts 10 apart",
    )
    max_starts_per_window: int = Field(
        default=1, ge=1, description="Starts allowed house-wide within any stagger_min window"
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
        bad = {k: v for k, v in self.preshow_by_format.items() if v < 0}
        if bad:
            raise ValueError(f"preshow cannot be negative: {bad}")
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
    def _refs(self, info: ValidationInfo) -> Brief:
        """Every reference resolves and every term could be met by *some* grid. A term
        that cannot is refused here, in the trade's words, rather than found INFEASIBLE
        later. A brief unfolded from a week (validation context `in_week`) may carry
        week-scoped terms; a brief that is one day may not."""
        in_week = bool((info.context or {}).get("in_week"))
        screen_ids = {s.id for s in self.screens}
        for s in self.screens:
            if self.last_start_for(s) < self.open_for(s):
                raise ValueError(
                    f"screen {s.id}: last start {fmt_time(self.last_start_for(s))} is before "
                    f"it opens at {fmt_time(self.open_for(s))}"
                )
        doors = min(self.open_for(s) for s in self.screens)
        last = max(self.last_start_for(s) for s in self.screens)
        plf_rooms = [s for s in self.screens if "PLF" in s.formats]
        for f in self.films:
            t = f.terms
            if t.screens:
                unknown = set(t.screens) - screen_ids
                if unknown:
                    raise ValueError(f"film {f.id} names unknown screens {sorted(unknown)}")
            lo = parse_time(t.earliest_start) if t.earliest_start else None
            hi = parse_time(t.latest_start) if t.latest_start else None
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(
                    f"{f.title}: earliest_start {t.earliest_start} is after latest_start "
                    f"{t.latest_start} — no session could start"
                )
            if hi is not None and hi < doors:
                raise ValueError(
                    f"{f.title}: latest_start {t.latest_start} is before the house opens at "
                    f"{fmt_time(doors)} — no session could start"
                )
            if lo is not None and lo > last:
                raise ValueError(
                    f"{f.title}: earliest_start {t.earliest_start} is after the last start "
                    f"{fmt_time(last)} — no session could start"
                )
            if t.max_shows is not None and t.min_shows > t.max_shows:
                raise ValueError(
                    f"{f.title}: min_shows {t.min_shows} is more than max_shows {t.max_shows} "
                    "— no day could carry both"
                )
            if t.max_shows is not None and t.prime_shows > t.max_shows:
                raise ValueError(
                    f"{f.title}: prime_shows {t.prime_shows} is more than max_shows "
                    f"{t.max_shows} — no day could carry both"
                )
            if t.plf_lock and not plf_rooms:
                played = sorted({fmt for s in self.screens for fmt in s.formats})
                raise ValueError(
                    f"{f.title}: plf_lock asks for every PLF room and the house has none — "
                    f"the screens play {', '.join(played)}"
                )
            if not in_week:
                for name, value in week_terms_set(t):
                    raise ValueError(
                        f"{f.title}: {name} {value} is a week term and this brief is one day "
                        "— put it in a week brief, under days"
                    )
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

    def preshow_for(self, film: Film) -> int:
        """Ads and trailers before this title: the house figure, or its format's."""
        return self.policy.preshow_by_format.get(film.format, self.policy.preshow_min)

    def open_for(self, screen: Screen) -> int:
        return parse_time(screen.open) if screen.open is not None else self.policy.open_min

    def last_start_for(self, screen: Screen) -> int:
        if screen.last_start is not None:
            return parse_time(screen.last_start)
        return self.policy.last_start_min

    def turnaround_of(self, screen: Screen, film: Film, start: int) -> tuple[int, int]:
        """When the floor staff are in the room: from `credits_min` before the feature ends,
        for the screen's clean time. The room is clear at the later of the feature's end
        and the turnaround's; the next preshow never starts over the last reel."""
        feature_end = start + self.preshow_for(film) + film.runtime_min
        begin = feature_end - film.credits_min
        return begin, max(feature_end, begin + self.clean_for(screen))

    def block_len(self, screen: Screen, film: Film) -> int:
        """Minutes a session occupies the screen: preshow + feature + clean, less the
        credits the turnaround overlaps."""
        return self.turnaround_of(screen, film, 0)[1]

    def can_play(self, screen: Screen, film: Film) -> bool:
        if film.format not in screen.formats:
            return False
        t = film.terms
        if t.screens is not None and screen.id not in t.screens:
            return False
        return not (t.min_capacity is not None and screen.capacity < t.min_capacity)


class TermRef(BaseModel):
    """One distributor term on one film: the unit the solver can name or give up."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    film: str
    term: str = Field(description="A field of Terms: min_shows, prime_shows, exclusive_screen…")
    value: str = Field(default="", description="The term's value as written, for the record")

    def __str__(self) -> str:
        return f"{self.film} {self.term}{' ' + self.value if self.value else ''}"


class Forced(BaseModel):
    """What the solver found when it forbade one show — this title, in this room, in
    this daypart — and solved the day again. A claim the checker cannot re-derive
    without solving, and labelled as one."""

    model_config = ConfigDict(extra="forbid")

    by: Literal["terms", "objective", "free", "unknown"] = Field(
        description="terms: no grid honours the terms without this show (the conflict is "
        "named); objective: every grid without it sells fewer seats; free: an equally good "
        "grid does without it; unknown: the probe ran out of time"
    )
    delta: float = Field(
        default=0.0, description="Expected admissions the best grid without it gives up"
    )
    terms: list[TermRef] = Field(
        default_factory=list, description="On `terms`: the terms that cannot hold without it"
    )
    instead: str = Field(default="", description="What the grid without it did with the slot")
    seconds: float = 0.0

    def __str__(self) -> str:
        if self.by == "terms":
            return "forced by " + " · ".join(str(t) for t in self.terms)
        if self.by == "objective":
            return f"forced by the objective · −{self.delta:,.0f} without it" + (
                f" · {self.instead}" if self.instead else ""
            )
        if self.by == "free":
            return "free" + (f" · {self.instead}" if self.instead else "")
        return "unknown · the probe ran out of time"


class Session(BaseModel):
    """One session on the grid."""

    model_config = ConfigDict(extra="forbid")

    screen: str
    film: str
    start: int = Field(description="Minutes after midnight when the preshow begins")
    feature_start: int
    feature_end: int
    clear: int = Field(
        description="Minutes after midnight when the screen is clean again. The turnaround "
        "may begin before feature_end where the title's credits allow"
    )
    forced: Forced | None = Field(
        default=None,
        description="Set by a probe (plan --why, explain): is this session in every grid?",
    )

    @property
    def key(self) -> str:
        """How the CLI names a session: screen@start, e.g. 1@17:30."""
        return f"{self.screen}@{fmt_time(self.start)}"

    @property
    def start_hhmm(self) -> str:
        return fmt_time(self.start)

    @property
    def feature_start_hhmm(self) -> str:
        return fmt_time(self.feature_start)

    @property
    def feature_end_hhmm(self) -> str:
        return fmt_time(self.feature_end)


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
    screens: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per screen id, the screen fields that differ today, e.g. open 12:00 on "
        "a weekday",
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
        screen_ids = {s.id for s in self.screens}
        for f in self.films:
            until = f.terms.exclusive_until
            if until is not None and until not in names:
                raise ValueError(
                    f"{f.title}: exclusive_until {until} names a day the week does not have "
                    f"— the days are {', '.join(names)}"
                )
        for d in self.days:
            unknown = set(d.terms) - film_ids
            if unknown:
                raise ValueError(f"day {d.name} sets terms for unknown films {sorted(unknown)}")
            unknown = set(d.screens) - screen_ids
            if unknown:
                raise ValueError(f"day {d.name} sets hours for unknown screens {sorted(unknown)}")
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
            base = f.terms.model_dump()
            until = f.terms.exclusive_until
            if until is not None:
                # The exclusive holds through the named day and lifts the day after.
                base["exclusive_screen"] = f.terms.exclusive_screen or i <= self.day_index(until)
            override = d.terms.get(f.id, {})
            if until is not None or override:
                films.append(
                    f.model_copy(update={"terms": Terms.model_validate({**base, **override})})
                )
            else:
                films.append(f)
        screens = [
            Screen.model_validate({**s.model_dump(), **d.screens[s.id]}) if s.id in d.screens else s
            for s in self.screens
        ]
        return Brief.model_validate(
            {
                "house": self.house,
                "date": d.date,
                "weekday": d.name if d.name in WEEKDAYS else None,
                "screens": screens,
                "films": films,
                "policy": policy,
            },
            context={"in_week": True},
        )

    def day_index(self, name: str) -> int:
        """Position of a day in the week, by the name the booth calls it."""
        return [d.name for d in self.days].index(name)

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


_MODEL_AT: dict[str, type[BaseModel]] = {
    "terms": Terms,
    "films": Film,
    "screens": Screen,
    "policy": Policy,
    "demand": Demand,
    "dayparts": Daypart,
    "days": DayOverride,
}


def validation_sentences(err: Exception, raw: Any, *, week: bool | None = None) -> list[str]:
    """A pydantic error in the trade's words: which title or screen, which field, what
    was wrong, and — for a field the booking cannot carry — what it can. `raw` is the
    parsed JSON, so a film can be named by its title rather than its index."""
    from pydantic import ValidationError

    if not isinstance(err, ValidationError):
        return [str(err)]
    if week is None:
        week = isinstance(raw, dict) and "days" in raw
    out: list[str] = []
    for e in err.errors():
        loc = [x for x in e["loc"] if x != "__root__"]
        # Walk the path, naming things as the booth would.
        node: Any = raw
        words: list[str] = []
        model: type[BaseModel] = WeekBrief if week else Brief
        last_key: str | None = None
        for part in loc:
            if isinstance(part, int):
                node = node[part] if isinstance(node, list) and part < len(node) else None
                name = None
                if isinstance(node, dict):
                    name = node.get("title") or node.get("name") or node.get("id")
                words.append(str(name) if name else f"#{part + 1}")
            else:
                node = node.get(part) if isinstance(node, dict) else None
                last_key = str(part)
                if part in _MODEL_AT:
                    model = _MODEL_AT[part]
                    if part not in ("terms", "policy", "demand"):
                        continue  # "films → The Long Voyage", not "films → films"
                words.append(str(part))
        where = " → ".join(words)
        kind = e["type"]
        msg = e["msg"]
        if kind == "extra_forbidden":
            field = words.pop() if words else str(last_key)
            where = " → ".join(words)
            allowed = ", ".join(model.model_fields)
            noun = {
                "Terms": "a term a booking can carry",
                "Film": "something a title can carry",
                "Screen": "something a screen can carry",
                "Policy": "a house policy",
                "Demand": "part of a demand block",
                "DayOverride": "something a day can override",
                "Daypart": "part of a daypart",
            }.get(model.__name__, "a field of the brief")
            out.append(
                (f"{where}: " if where else "")
                + f"`{field}` is not {noun} — the fields are {allowed}"
            )
        elif kind == "value_error":
            text = msg.removeprefix("Value error, ")
            out.append(f"{where}: {text}" if where and where not in text else text)
        else:
            got = e.get("input")
            out.append(f"{where}: {msg}" + (f" (got {got!r})" if got is not None else ""))
    return out
