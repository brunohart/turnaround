# Design

The output of this tool is a **week sheet**: the thing a programmer prints on Wednesday and pins in the booth. It is paper first and screen second.

**Substrate.** Warm parchment (`#F0EDE6`), ink that is never pure black, a 6% grain. The prime window is a cold navy wash at 4–5% behind the grid, not a box.

**The ruler.** Hours run across the top in mono, uppercase, wide-tracked. One row per screen. The screen's name is poster type; its capacity and formats sit under it as an archival label.

**Blocks.** Every session is three strips joined: the preshow (fine diagonal hatch in ink), the feature (cream, the title in poster type, the start time and running time in mono), and the turnaround (a coarser hatch in the signature orange). The orange is the turnaround. That is the one place the accent lives on the grid, because that is the constraint the grid is built around.

**Sessions starting in prime** print on white rather than cream. Nothing else changes.

**Offsets.** The feature block carries a second, orange-outlined pass offset 6px at 35% opacity: a misregistered print. The house name has a ghost pass offset 4px at 9%. The section labels are rubber stamps at −0.8°.

**Below the fold.** Two columns at 1.15fr / 0.85fr. Left: by title, with starts in mono. Right: the proof table, blue ticks and rust crosses, with the evidence sentence beside each.

**What it is not.** No dark mode (paper does not have one). No gradients, no glass, no rounded pills. No colour per film; the sheet is read by position and type, and a fourteen-film house would otherwise become a paint chart. Motion is limited to a 1px lift on hover, because hovering a schedule is a high-frequency act and should not perform.

**Print.** `@media print` drops the grain, tightens the type, stacks the columns. An A3 landscape sheet should be legible from the booth door.

Source of truth for the identity: `digital-design-taste.md` in the designedbybruno workspace. Day 6 is the full pass against it.
