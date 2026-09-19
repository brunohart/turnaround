// The desk: take the files, tell a grid from a brief, hand both to the sheet. Nothing is
// uploaded and nothing is kept: no fetch of anything but this page's own example, no
// storage, no query string. Reload and the board has forgotten.
import { kindOf, renderSheet } from "./sheet.js";

const $ = (id) => document.getElementById(id);
const held = { grid: null, brief: null, names: [] };

function fail(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

function take(name, doc) {
  const kind = kindOf(doc);
  if (kind === "brief") held.brief = doc;
  else if (kind) held.grid = doc;
  else throw new Error(`${name} is neither a grid nor a brief — a grid has sessions and a status, a brief has screens and films`);
  held.names.push(`${name} · ${kind === "brief" ? "brief" : kind === "week-grid" ? "week" : "grid"}`);
}

function draw() {
  $("held").textContent = held.names.join("  +  ");
  if (!held.grid) return fail("That is a brief. Drop its grid as well — the brief says what could play, the grid says what does.");
  const weekBrief = held.brief && Array.isArray(held.brief.days);
  if (held.brief && weekBrief !== (kindOf(held.grid) === "week-grid")) return fail("The brief and the grid are not the same shape: one is a day, the other a week or a festival.");
  $("out").innerHTML = renderSheet(held.grid, held.brief);
  $("bar-what").textContent = held.brief ? held.names.join("  +  ") : `${held.names.join("")} · no brief: drop it too for titles, seats and prime`;
  $("desk").hidden = true;
  $("bar").hidden = false;
  document.title = `${held.grid.house} — the board — turnaround`;
  window.scrollTo(0, 0);
}

async function read(files) {
  $("error").hidden = true;
  try {
    for (const file of files) {
      let doc;
      try {
        doc = JSON.parse(await file.text());
      } catch {
        throw new Error(`${file.name} is not JSON`);
      }
      take(file.name, doc);
    }
    draw();
  } catch (e) {
    fail(e.message);
  }
}

function reset() {
  held.grid = held.brief = null;
  held.names = [];
  $("out").innerHTML = "";
  $("held").textContent = "";
  $("files").value = "";
  $("error").hidden = true;
  $("bar").hidden = true;
  $("desk").hidden = false;
  document.title = "The board — turnaround";
}

// the whole window is the drop zone, so a brief can be dropped onto a drawn sheet
addEventListener("dragover", (e) => { e.preventDefault(); $("drop").classList.add("over"); });
addEventListener("dragleave", () => $("drop").classList.remove("over"));
addEventListener("drop", (e) => {
  e.preventDefault();
  $("drop").classList.remove("over");
  if (e.dataTransfer && e.dataTransfer.files.length) read([...e.dataTransfer.files]);
});
$("files").addEventListener("change", (e) => read([...e.target.files]));
$("again").addEventListener("click", reset);
$("print").addEventListener("click", () => print());
$("example").addEventListener("click", async () => {
  try {
    const [brief, grid] = await Promise.all(["examples/regent.json", "examples/regent.grid.json"].map((u) => fetch(u).then((r) => r.json())));
    take("regent.json", brief);
    take("regent.grid.json", grid);
    draw();
  } catch {
    fail("The example did not load. Opened from a file:// address the page cannot read its own folder; run scripts/board.sh --serve.");
  }
});
