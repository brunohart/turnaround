// The sheet, client-side. A port of src/turnaround/render.py's day_context and the macros
// of templates/_day.html.j2: the same ruler, the same three-strip block, the same booth
// strips under 800px. It draws what a grid says and what a brief names, and nothing else:
// no solver, no checker, no demand model. The proof stays the checker's (ADR-003), so the
// board prints the grid's claims and says whose they are.

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export const parseTime = (v) => {
  if (typeof v === "number") return v;
  const [h, m] = String(v).split(":").map(Number);
  return h * 60 + m;
};

// Past midnight the booth still says 24:30, as the Python does.
export const fmtTime = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;

const num = (n) => Math.round(n).toLocaleString("en-US");

const POLICY = { open: "10:00", last_start: "21:30", preshow_min: 20, clean_min: 20, stagger_min: 10, max_starts_per_window: 1, prime_start: "17:30", prime_end: "20:45" };

/** What was dropped: a day's grid, a week's or a festival's; a brief of any of the three. */
export function kindOf(doc) {
  if (!doc || typeof doc !== "object") return null;
  if (Array.isArray(doc.sessions) && "status" in doc) return "grid";
  if (Array.isArray(doc.grids) && Array.isArray(doc.days)) return "week-grid";
  if (Array.isArray(doc.films) && (Array.isArray(doc.screens) || Array.isArray(doc.venues))) return "brief";
  return null;
}

/** A grid alone names its screens and titles by id. This is the brief it implies: enough
 * to draw the blocks where they are, and honest about what it does not know. */
export function impliedBrief(grid) {
  const screens = [...new Set(grid.sessions.map((s) => s.screen))]
    .sort((a, b) => a.localeCompare(b, "en", { numeric: true }))
    .map((id) => ({ id, implied: true }));
  const films = new Map();
  for (const s of grid.sessions) if (!films.has(s.film)) films.set(s.film, { id: s.film, title: s.film, runtime_min: s.feature_end - s.feature_start, implied: true });
  const starts = grid.sessions.map((s) => s.start);
  const open = starts.length ? Math.min(...starts) : parseTime(POLICY.open);
  return { house: grid.house, date: grid.date, screens, films: [...films.values()], policy: { open: fmtTime(open - (open % 60)) }, implied: true };
}

/** One day of a week or a festival: the shared brief with the day's overrides laid over it. */
export function dayBrief(brief, i) {
  const day = (brief.days || [])[i] || {};
  const screens = (brief.screens || brief.venues || []).map((s) => ({ ...s, ...((day.screens || {})[s.id] || {}) }));
  const films = brief.films.map((f) => ({ ...f, terms: { ...(f.terms || {}), ...((day.terms || {})[f.id] || {}) } }));
  return { house: brief.house || brief.festival, date: day.date, day_name: day.name, screens, films, policy: { ...(brief.policy || {}), ...(day.policy || {}) } };
}

export function dayContext(brief, grid) {
  const p = { ...POLICY, ...(brief.policy || {}) };
  const screens = brief.screens || brief.venues || [];
  const film = (id) => brief.films.find((f) => f.id === id) || { id, title: id, runtime_min: 0 };
  const isPrime = (start) => parseTime(p.prime_start) <= start && start < parseTime(p.prime_end);
  const openMin = parseTime(p.open);
  let dayStart = openMin - (openMin % 60);
  if (grid.sessions.length) {
    const first = Math.min(...grid.sessions.map((s) => s.start));
    dayStart = Math.min(dayStart, first - (first % 60));
  }
  const latestClear = grid.sessions.length ? Math.max(...grid.sessions.map((s) => s.clear)) : parseTime(p.last_start) + 120;
  const dayEnd = latestClear + ((60 - (latestClear % 60)) % 60);
  const span = Math.max(dayEnd - dayStart, 60);
  const hours = [];
  for (let h = dayStart; h <= dayEnd; h += 60) hours.push(h);

  const rows = screens.map((scr) => {
    const sessions = grid.sessions.filter((s) => s.screen === scr.id).sort((a, b) => a.start - b.start);
    const blocks = sessions.map((s, i) => {
      const f = film(s.film);
      const block = s.clear - s.start;
      // the turnaround begins in the credits when the brief gives the title any
      const turnBegin = s.feature_end - (f.credits_min || 0);
      const nxt = sessions[i + 1];
      return {
        film: f, s, prime: isPrime(s.start), turnBegin,
        left: ((s.start - dayStart) / span) * 100,
        w: (block / span) * 100,
        pre: ((s.feature_start - s.start) / block) * 100,
        feat: ((s.feature_end - s.feature_start) / block) * 100,
        clean: ((s.clear - turnBegin) / block) * 100,
        over: ((s.feature_end - turnBegin) / block) * 100,
        preMin: s.feature_start - s.start,
        overMin: s.feature_end - turnBegin,
        gap: nxt ? nxt.start - s.clear : null,
      };
    });
    const ownHours = scr.open != null || scr.last_start != null;
    const open = scr.open ?? p.open;
    const last = scr.last_start ?? p.last_start;
    return { screen: scr, label: scr.name || scr.id, blocks, count: sessions.length, hours: ownHours ? `${open}–${last}` : null, open, last, cleanMin: scr.clean_min ?? p.clean_min };
  });

  const capacity = (id) => (screens.find((s) => s.id === id) || {}).capacity || 0;
  const films = brief.films
    .map((f) => {
      const ss = grid.sessions.filter((s) => s.film === f.id).sort((a, b) => a.start - b.start);
      return { film: f, sessions: ss, prime: ss.filter((s) => isPrime(s.start)).length, seats: ss.reduce((n, s) => n + capacity(s.screen), 0) };
    })
    // a festival day lists what plays, not the slate
    .filter((f) => f.sessions.length || !(brief.day_name && (f.film.terms || {}).max_shows === 0));

  const preshows = [`preshow ${p.preshow_min}′`];
  for (const [fmt, mins] of Object.entries(p.preshow_by_format || {})) if (mins !== p.preshow_min) preshows.push(`${fmt} ${mins}′`);
  const stagger = p.stagger_min === 0 ? "no stagger" : p.max_starts_per_window === 1 ? `stagger ≥ ${p.stagger_min}′` : `≤ ${p.max_starts_per_window} starts in ${p.stagger_min}′`;
  const staff = p.max_concurrent_turnarounds != null ? `floor clears ${p.max_concurrent_turnarounds} room${p.max_concurrent_turnarounds !== 1 ? "s" : ""} at once` : null;
  const forced = (by) => grid.sessions.filter((s) => s.forced && s.forced.by === by).length;

  return {
    p, rows, films, hours, dayStart, span,
    primeLeft: ((parseTime(p.prime_start) - dayStart) / span) * 100,
    primeW: ((parseTime(p.prime_end) - parseTime(p.prime_start)) / span) * 100,
    preshows: preshows.join(" · "), stagger, staff,
    credits: grid.sessions.some((s) => film(s.film).credits_min),
    seats: grid.sessions.reduce((n, s) => n + capacity(s.screen), 0),
    probed: grid.sessions.some((s) => s.forced),
    forcedCount: forced("terms"), objectiveCount: forced("objective"), freeCount: forced("free"),
  };
}

const forcedClass = (s) => (s.forced && s.forced.by === "terms" ? " forced" : s.forced && s.forced.by === "objective" ? " wanted" : "");
const tmLine = (b) => `${b.film.runtime_min}′${b.film.format && b.film.format !== "2D" ? ` · ${esc(b.film.format)}` : ""}`;
const capLine = (row) => [row.screen.capacity ? `${row.screen.capacity} seats` : null, (row.screen.formats || []).join("/") || null].filter(Boolean).map(esc);

function gridHtml(brief, d) {
  const pl = `--pl:${d.primeLeft}%; --pr:${d.primeLeft + d.primeW}%`;
  const rows = d.rows
    .map((row) => {
      const blocks = row.blocks
        .map((b) => {
          const tip = `${b.film.title}${b.film.strand ? ` · ${b.film.strand}` : ""} · preshow ${fmtTime(b.s.start)} · feature ${fmtTime(b.s.feature_start)}–${fmtTime(b.s.feature_end)}${b.over > 0 ? ` · turnaround from ${fmtTime(b.turnBegin)} over the credits` : ""} · clear ${fmtTime(b.s.clear)}`;
          return `<div class="block${b.prime ? " prime" : ""}" style="left:${b.left}%; width:${b.w}%" title="${esc(tip)}">
            <div class="pre" style="width:${b.pre}%"></div>
            <div class="feat${forcedClass(b.s)}" style="width:${b.feat}%"><div class="t">${esc(b.film.title)}</div><div class="tm mono">${fmtTime(b.s.start)} · ${tmLine(b)}</div></div>
            <div class="clean${b.over > 0 ? " over" : ""}" style="width:${b.clean}%${b.over > 0 ? `; margin-left:-${b.over}%` : ""}"></div>
          </div>`;
        })
        .join("");
      const cap = [...capLine(row), `${row.count} shows`, row.hours ? esc(row.hours) : null].filter(Boolean).join(" · ");
      return `<div class="row"><div class="name"><div class="n">${esc(row.label)}</div><div class="cap mono">${cap}</div></div><div class="lane">${blocks}</div></div>`;
    })
    .join("");
  const legend = [
    `<span><i class="pre"></i>${esc(d.preshows)}</span>`, `<span><i class="feat"></i>feature</span>`,
    `<span><i class="clean"></i>turnaround${d.credits ? " · from the credits" : ""}</span>`, `<span>${esc(d.stagger)}</span>`,
    d.staff ? `<span>${esc(d.staff)}</span>` : "",
    d.probed ? `<span><i class="feat forced-i"></i>forced by the terms</span><span><i class="feat wanted-i"></i>by the objective</span>` : "",
  ].join("");
  return `<div class="grid">
    <div class="ruler" style="${pl}"><span class="prime-label mono" style="left:${d.primeLeft}%">prime ${esc(d.p.prime_start)}–${esc(d.p.prime_end)}</span>${d.hours.map((h) => `<span class="h mono" style="left:${((h - d.dayStart) / d.span) * 100}%">${fmtTime(h)}</span>`).join("")}</div>
    <div style="position:relative; ${pl}">${rows}</div>
    <div class="legend mono">${brief.implied ? "" : legend}${brief.implied ? `<span><i class="pre"></i>preshow</span><span><i class="feat"></i>feature</span><span><i class="clean"></i>turnaround</span><span>no brief: screens and titles by id</span>` : ""}</div>
  </div>`;
}

function stripsHtml(brief, d, dayLabel) {
  const pages = d.rows
    .map((row) => {
      const blocks = row.blocks
        .map(
          (b) => `<div class="vblock${b.prime ? " prime" : ""}">
        <div class="vpre mono"><span><b>${fmtTime(b.s.start)}</b> doors</span><span>preshow ${b.preMin}′</span></div>
        <div class="vfeat"><div class="t">${esc(b.film.title)}</div><div class="tm mono">${fmtTime(b.s.feature_start)}–${fmtTime(b.s.feature_end)} · ${tmLine(b)}${b.prime ? " · prime" : ""}${b.film.strand ? ` <span class="tag">${esc(b.film.strand)}</span>` : ""}</div></div>
        <div class="vclean mono${b.overMin > 0 ? " over" : ""}"><span>turnaround ${fmtTime(b.turnBegin)}${b.overMin > 0 ? " over the credits" : ""}</span><span>clear <b>${fmtTime(b.s.clear)}</b></span></div>
      </div>${b.gap !== null ? `<div class="vgap mono"><i></i>${b.gap > 0 ? `dark ${b.gap}′` : "back to back"}</div>` : ""}`,
        )
        .join("");
      const cap = [...capLine(row), brief.implied ? null : `doors ${esc(row.open)} · last start ${esc(row.last)} · turnaround ${row.cleanMin}′`].filter(Boolean).join(" · ");
      return `<section class="strip-page"><div class="strip-head"><div>
        <div class="stamp mono">Booth strip · ${esc(dayLabel)}</div>
        <div class="n"><span class="ghost" aria-hidden="true">${esc(row.label)}</span>${esc(row.label)}</div>
        <div class="cap mono">${cap}</div></div>
        <div class="meta mono"><div><b>${row.count}</b> show${row.count !== 1 ? "s" : ""}</div><div>${esc(brief.house)}</div></div></div>
        ${row.blocks.length ? blocks : `<p class="mono" style="color:var(--grey)">dark all day</p>`}</section>`;
    })
    .join("");
  return `<div class="strips">${pages}</div>`;
}

function tablesHtml(brief, grid, d) {
  const rows = d.films
    .map(({ film: f, sessions, prime, seats }) => {
      const t = f.terms || {};
      const starts = sessions
        .map((s) => `<span class="st">${fmtTime(s.start)}${s.forced && s.forced.by === "terms" ? ` <b class="fx">forced</b>` : s.forced && s.forced.by === "objective" ? ` <b class="fo">−${num(s.forced.delta)}</b>` : ""}</span>`)
        .join("");
      const label = [`${f.runtime_min}′`, f.format, f.rating].filter(Boolean).map(esc).join(" · ");
      return `<tr><td class="title"><b>${esc(f.title)}</b>${f.strand ? ` <span class="tag">${esc(f.strand)}</span>` : ""}<br><span class="mono" style="color:var(--grey)">${label}</span></td>
        <td>${sessions.length}${t.min_shows ? `<span class="mono" style="color:var(--grey)"> /${t.min_shows} min</span>` : ""}</td>
        <td>${prime}${t.prime_shows ? `<span class="mono" style="color:var(--grey)"> /${t.prime_shows}</span>` : ""}</td>
        <td class="num">${seats ? num(seats) : "—"}</td><td class="starts">${starts}</td></tr>`;
    })
    .join("");
  const claims = [
    `<div>status <b>${esc(grid.status)}</b>${grid.status === "FEASIBLE" && grid.stats && grid.stats.gap != null ? ` · not proven best, gap ${(grid.stats.gap * 100).toFixed(1)}%` : ""}</div>`,
    `<div>objective <b>${num(grid.objective)}</b> expected admissions</div>`,
    grid.admissions != null ? `<div>admissions <b>${num(grid.admissions)}</b></div>` : "",
    grid.hold_paid ? `<div>paid to hold times <b>${num(grid.hold_paid)}</b></div>` : "",
    grid.clash_paid ? `<div>paid in clashes <b>${num(grid.clash_paid)}</b></div>` : "",
    (grid.relaxed || []).length ? `<div class="given-up">${grid.relaxed.length} term${grid.relaxed.length !== 1 ? "s" : ""} given up</div>` : "",
    d.probed ? `<div>${grid.sessions.length} sessions probed · ${d.forcedCount} forced by the terms · ${d.objectiveCount} by the objective · ${d.freeCount} free</div>` : "",
  ].join("");
  return `<div class="cols"><div class="wash blue"></div>
    <div class="panel"><div class="stamp mono">By title</div><div class="scroll"><table>
      <thead><tr><th>Title</th><th>Shows</th><th>Prime</th><th>Seats</th><th>Starts${d.probed ? " · forced" : ""}</th></tr></thead><tbody>${rows}</tbody>
      <tfoot><tr><td class="mono" style="color:var(--grey)">the day</td><td>${grid.sessions.length}</td><td></td><td class="num">${d.seats ? num(d.seats) : "—"}</td><td></td></tr></tfoot>
    </table></div></div>
    <div class="panel"><div class="stamp mono">The grid's claims</div>
      <div class="claims mono">${claims}</div>
      <p class="mono probed">the solver's claims, read from the file — not a proof. The proof is the checker's, and the checker does not run in a browser: <b>turnaround check brief.json grid.json</b></p>
    </div></div>`;
}

function dayHtml(brief, grid) {
  const d = dayContext(brief, grid);
  const label = `${brief.day_name ? `${brief.day_name} ` : ""}${brief.date || grid.date || "the day"}`;
  return { d, label, body: gridHtml(brief, d) + tablesHtml(brief, grid, d) + stripsHtml(brief, d, label) };
}

const metaDoors = (brief, p) => (brief.implied ? "" : `<div>doors ${esc(p.open)} · last start ${esc(p.last_start)} · turnaround ${p.clean_min}′${p.school_holiday ? " · school holidays" : ""}${brief.day_name ? ` · ${esc(brief.day_name)}` : ""}</div>`);
const solvedLine = (g) => (g.status === "IMPORTED" ? "made by hand · imported, not solved" : `solved in ${g.solve_seconds}s`);

/** The whole sheet for whatever was dropped: a day, or a week or festival as day pages. */
export function renderSheet(gridDoc, briefDoc) {
  if (kindOf(gridDoc) === "week-grid") {
    const pages = gridDoc.grids.map((g, i) => {
      const brief = briefDoc ? dayBrief(briefDoc, Math.max(0, (briefDoc.days || []).findIndex((x) => x.name === gridDoc.days[i]))) : { ...impliedBrief(g), day_name: gridDoc.days[i] };
      const { d, body } = dayHtml(brief, g);
      return `<section class="day-page"><div class="day-head"><div><div class="stamp mono">${esc(g.status)}</div><h2>${esc(gridDoc.days[i])}${g.date ? ` · ${esc(g.date)}` : ""}</h2></div>
        <div class="meta mono"><div>${g.sessions.length} sessions${d.seats ? ` · ${num(d.seats)} seats on offer` : ""}</div>${metaDoors({ ...brief, day_name: null }, d.p)}<div>${solvedLine(g)}</div></div></div>${body}</section>`;
    });
    const sessions = gridDoc.grids.reduce((n, g) => n + g.sessions.length, 0);
    const objective = gridDoc.grids.reduce((n, g) => n + g.objective, 0);
    const house = gridDoc.house;
    return `<div class="sheet"><div class="wash"></div><header><div><div class="stamp mono">Week sheet · ${gridDoc.days.length} days</div><h1><span class="ghost" aria-hidden="true">${esc(house)}</span>${esc(house)}</h1></div>
      <div class="meta mono"><div><b>${esc(gridDoc.days[0])}–${esc(gridDoc.days.at(-1))}</b></div><div>${sessions} sessions · ${gridDoc.days.length} days</div>
      ${(gridDoc.hold_days || []).length ? `<div>${(gridDoc.held || []).length} title${(gridDoc.held || []).length !== 1 ? "s" : ""} hold their times ${esc(gridDoc.hold_days.join(" "))}</div>` : ""}<div>solved in ${gridDoc.solve_seconds}s</div></div></header>
      <div class="divider"></div>${pages.join("")}${footer(`objective ${num(objective)} expected admissions over the days`)}</div>`;
  }
  const brief = briefDoc ? (briefDoc.days ? dayBrief(briefDoc, 0) : briefDoc) : impliedBrief(gridDoc);
  const { d, body } = dayHtml(brief, gridDoc);
  const house = brief.house || gridDoc.house;
  return `<div class="sheet"><div class="wash"></div><header><div><div class="stamp mono">Week sheet · ${esc(gridDoc.status)}${(gridDoc.relaxed || []).length ? " · relaxed" : ""}</div><h1><span class="ghost" aria-hidden="true">${esc(house)}</span>${esc(house)}</h1></div>
    <div class="meta mono"><div><b>${esc(brief.date || gridDoc.date || "—")}</b></div>
    <div>${gridDoc.sessions.length} sessions · ${d.rows.length} screens · ${brief.films.length} titles</div>
    ${d.seats ? `<div>${num(d.seats)} seats on offer</div>` : ""}${metaDoors(brief, d.p)}<div>${solvedLine(gridDoc)}</div></div></header>
    <div class="divider"></div>${body}${footer(`${gridDoc.status === "IMPORTED" ? "" : "objective "}${num(gridDoc.objective)} expected admissions`)}</div>`;
}

const footer = (right) => `<footer class="mono"><span>turnaround · the showtime grid, drawn in your browser · nothing left this page</span><span>${esc(right)}</span></footer>`;
