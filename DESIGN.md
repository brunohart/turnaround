# Design

The output of this tool is a **week sheet**: the thing a programmer prints on Wednesday and pins in the booth. It is paper first and screen second.

**Substrate.** Warm parchment (`#F0EDE6`), ink that is never pure black, a 6% grain. The prime window is a cold navy wash at 4–5% behind the grid, not a box.

**The ruler.** Hours run across the top in mono, uppercase, wide-tracked. One row per screen. The screen's name is poster type; its capacity and formats sit under it as an archival label.

**Blocks.** Every session is three strips joined: the preshow (fine diagonal hatch in ink), the feature (cream, the title in poster type, the start time and running time in mono), and the turnaround (a coarser hatch in the signature orange). The orange is the turnaround. That is the one place the accent lives on the grid, because that is the constraint the grid is built around.

**Sessions starting in prime** print on white rather than cream. Nothing else changes.

**Offsets.** The feature block carries a second, orange-outlined pass offset 6px at 35% opacity: a misregistered print. The house name has a ghost pass offset 4px at 9%. The section labels are rubber stamps at −0.8°.

**Below the fold.** Two columns at 1.15fr / 0.85fr. Left: by title, with starts in mono. Right: the proof table, blue ticks and rust crosses, with the evidence sentence beside each.

**What it is not.** No dark mode (paper does not have one). No gradients, no glass, no rounded pills. No colour per film; the sheet is read by position and type, and a fourteen-film house would otherwise become a paint chart. Motion is limited to a 1px lift on hover, because hovering a schedule is a high-frequency act and should not perform.

**Print.** Two pages from one HTML. The pin-up is A3 landscape (`@page pinup`): the grid, the by-title table and the proof on one sheet, legible from the booth door; the grain and the washes are dropped, the rotations are straightened, the hatches print. The **booth strip** is A4 portrait (`@page strip`), one per screen: the screen's name in poster type, its doors and last start under it, then the three-strip block turned vertical — doors and preshow on the ink hatch, the feature in cream (white in prime), the turnaround on the orange hatch with when it begins and when the room is clear — and the dark minutes between sessions. The terms sheet is a letter (`@page letter`, A4 portrait). Every page-opening section has 3px of air above it so a rotated stamp stays on its page.

**Phone.** Under 800px the grid is not shrunk; it is replaced by the booth strips, one screen after another, before the tables. Wide tables scroll sideways inside their own box. Nothing rotates.

**Offsets, continued.** Rubber stamps carry a navy offset (3px, 18%) behind them. A second colour field, navy, bleeds off the bottom-left behind the by-title table. The meta block and the legend are pinned a fraction off level; the two panels below the fold sit at −0.3° and +0.35° and straighten on hover. The grid stays level: a block's position is data.

Source of truth for the identity: `digital-design-taste.md` in the designedbybruno workspace. Day 6 was the full pass against it (ADR-014).
