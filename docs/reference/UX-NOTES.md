# UX reference for step 7 — what to carry over from Noah Stock

The previous project (Noah Stock, retail F&B across nine cinemas) solved the same
screen problem: hundreds of lines, a planner with ten minutes, and the need to make
"what should I do today" obvious. Step 7 inherits its layout language.

> **Screenshots**: the six Noah Stock reference images are in this folder —
> [`noah-dashboard.png`](noah-dashboard.png),
> [`noah-organizations.png`](noah-organizations.png),
> [`noah-sites.png`](noah-sites.png), [`noah-calendar.png`](noah-calendar.png),
> [`noah-board.png`](noah-board.png) and [`noah-drawer.png`](noah-drawer.png).
> They are the illustration; this file is the specification, and the screens were
> built from the text.

---

## The layout language, unchanged

```
┌──────────┬────────────────────────────────────────────────────────┐
│ left nav │  Title + one line of context                           │
│          │  ┌────────┬────────┬────────┬────────┐                 │
│  org     │  │  KPI   │  KPI   │  KPI   │  KPI   │  cards          │
│  picker  │  └────────┴────────┴────────┴────────┘                 │
│          │  ┌──────────────────────────────────────┐              │
│ Dashboard│  │  ONE table — the work queue          │              │
│ Sites    │  │  click a row → drawer                │              │
│ Calendar │  └──────────────────────────────────────┘              │
│ Inventory│  ┌──────────────────────────────────────┐              │
│          │  │  secondary panel (stock to move)     │              │
└──────────┴────────────────────────────────────────────────────────┘
```

Four things made it work, and all four transfer:

**1. Ranked by what it costs to ignore, not by quantity.** Stated on the screen, in
those words. It is the single line that changes how the board is read: the top row
is not the biggest number, it is the most expensive mistake.

**2. KPI cards that are counts with a consequence**, not totals. Noah used *Needs an
order · Value at risk · Money standing still · Needs counting*, each with a
sub-line ("out of 383 lines this cinema actually uses"). The sub-line is what stops
a number being meaningless.

**3. A colour band per state, repeated everywhere.** Sold out (red) · order today
(red) · order this week (amber) · well stocked (green) · too much stock (blue) ·
never used here (grey). The same colours on the cards, the breakdown chips and the
row stripe, so the eye learns them once.

**4. The drawer, not a page.** Clicking a row opens a panel over the board: the
item, where it is, what to do, and — the part that earns trust — a sentence in
plain English explaining the recommendation with its own arithmetic visible.

Noah's drawer sentence is the model to copy:

> *"Order about 676,365 Grm, today. You are exposed for 25 days — 16 between orders
> plus 9 for delivery. Holding 796,179 Grm covers 90.0% of past 25-day stretches;
> there are 119,814."*

Our step-5 reason strings are already written in that shape.

---

## What has to change for MRO, and why

Noah's plant sold popcorn. Ours holds a spare transformer that may never be issued.
Four adaptations follow from that, and getting them wrong would make the board
useless on exactly the items that matter.

| Noah (fast movers) | Ours (mostly slow movers) | Why |
|---|---|---|
| **"Lasts 2.4 days"** | **"About a 1 in 12 chance of being needed before the next delivery"** | Days-of-cover is meaningless when the run rate is 0.02 a month. It reads as "lasts 40 years", which is true and useless. Stockout probability over the lead time is the same idea expressed in a way that survives sparse demand. |
| **Ranked by lost margin** | **Ranked by criticality × SAR at risk** | Nothing here is sold, so there is no margin. What replaces it is what the absence costs: an A-critical part stops the plant, a C-critical part inconveniences somebody. |
| **"Used daily / weekly / rarely"** | **The four demand groups from step 3** | Steady / jumpy / occasional / rare-and-large. Same idea, and it is already computed. |
| **Run-rate per day** | **Run-rate per month, plus "never issued in 2 years"** | A per-day rate on an item used twice a decade is a row of zeros. |

**Keep:** the "stock that could be moved" panel (one storeroom short while another
is long — it is capability 5 and the layout already exists), and the calendar of
known events (Noah used Ramadan and Eid; ours uses planned shutdowns, and it serves
exactly the same purpose — demand that is known in advance rather than forecast).

**Drop:** the organisation picker. One client, one plant.

---

## Round 2 — 2026-09-10, readability for someone who has never seen inventory data

The first build was correct and unreadable. One page carried the money, the work
queue, the marks and the method at once, and everything on it was written for
somebody who already knew what a reorder point was. What changed, and why:

| Change | Why |
|---|---|
| **One page became four** — Today, Stock board, Storerooms, How well it works | Noah's board had one audience. This has three: somebody who wants the number, somebody who has to act on it, and somebody who has to believe it. Mixing them meant none of them was served. |
| **Today: three tiles, nothing else** | A first screen that has to be scrolled has already lost. Dead value, parts unused in two years, critical parts below level — each with a sentence saying what it means and what to do. |
| **"What to do" is the second column** on the board, before every measurement | Carried straight from Noah's drawer sentence, but promoted to the table. A board that says what is wrong is a report; a board that says what to do is a tool. |
| **"SAR 24.9bn at risk" removed from the screen** | Arithmetically defensible, reads as a typo, loses the room. Replaced by "N parts need action today, SAR X to bring them to level" — a figure a planner can take to a buyer. The ranking still uses shortage cost underneath. |
| **Demand groups renamed** — used regularly / regular, varying amounts / now and then / rarely, in bursts | Noah said "used daily / weekly / rarely" and that was already the right instinct. `smooth` / `erratic` / `intermittent` / `lumpy` are Syntetos-Boylan terms, and they now live in the tooltip. |
| **An ⓘ on every tile label and column header** | The thing that stops a plain-word label being *vaguer* than the technical one. "Our level" with "when the shelf falls to this number, order more" behind it is both readable and exact. |
| **"How to read this page" under every title** | One line. It is the difference between a screen somebody uses and a screen somebody asks about. |
| **All money in SAR millions, one decimal** | `SAR 1,412,694,541` is skipped; `SAR 1,412.7m` is read. |
| **Storerooms page carries the transfer panel** | This is Noah's "stock that could be moved", and the data existed all along. |
| **Page four keeps the jargon and says so** | Recall, MASE, TSB and the honest callouts live in one place, labelled as the evidence page. Hiding them would be worse than showing them. |
| **Drawer reordered**: what to do, then why, then the chart | The explanation earns the number. The chart is evidence for the explanation, not the other way round. |

One naming collision worth knowing about: the *state* band for "on hand is under
our reorder point" is labelled **Below our level**, while the *action*
**Below safe level** means the part is under the plant's own old minimum but at or
above ours. Two different things, and the first draft called both of them the same
words.

## Rounds 3 and 4 — 2026-09-10, presentation quality and the business order

| Change | Why |
|---|---|
| **Nav is the presentation sequence**: Dashboard · Storerooms · Stock board · Recommendations | The size of it, where it is, what to do about each part, what to do first. Evidence moved to a footer link — one click for the engineer, out of the way for everyone else. |
| **Present mode** — nav hidden, type enlarged, ← → through the four pages, "n / 4", Esc | This is what is on the wall. A tool has a nav; a presentation has a sequence. |
| **Dark by default, toggle in the nav and the HUD** | Asked for. Light stays one click away for a projector. |
| **One accent, one element per page** | Rust on the number the page exists for and nothing else. Chips, tags and criticality are neutral; the only colour on the board is the "Order N now" instruction. |
| **Tiles without borders, tables without vertical lines** | Shadow and tint separate things; lines just add lines. 14px in tables, 40px on tile numbers, 12px labels, 32px+ between sections, 1080px content. |
| **Charts as inline SVG, one style** | Bars, a stacked bar, a line with the forecast laid over the tested year, the frontier with both policies. Thin axes, muted grid, one highlighted series. A 12-month sparkline in every board row — the "how it moves" tag now has evidence beside it. |
| **Storeroom cards** with top-five lists, click-through to the store's parts | Noah's site table, but a card can carry the two lists a manager actually asks for. |
| **Recommendations** as three tabs ranked by money with a total and an export | The "what do I do with this" page. Noah never had one; the reference board *was* the to-do list. Here the board is the diagnosis and this page is the prescription. |
| **"Order by" and "runs out around"** on below-level rows | Noah's "runs out 12 Sat / order by 10 Thu", adapted: the data's own today, not the wall clock. |
| **Drawer**: what to do first in the accent, one stat row, chart, reason in a quiet panel at the bottom | Round 2 had the reason above the chart; round 3 asked for it below. The chart now overlays the forecast on the tested year instead of drawing it a year to the right — that was a bug, not a choice. |

## Status — built 2026-09-10

All three screens exist: `api/static/index.html`, served by `python cli.py serve`.
Everything below was carried over, except where the "what has to change" table
says otherwise.

| From Noah | In ours | Where |
|---|---|---|
| Left nav, KPI tiles, one table, drawer on click | same | all four screens |
| "Ranked by what it costs to ignore, not by quantity" — those words on screen | same words | stock board sub-head |
| Colour band per state, repeated everywhere | six bands, on the row tag and the chips | stock board |
| Drawer with a plain-English sentence and its arithmetic visible | the "Why this number" panel, ending with the engine's own reason string verbatim | item drawer |
| Days-of-cover | replaced: months between issues, and the service level the level was set at | item drawer |
| Ranked by lost margin | replaced: criticality weight x unit price x units below reorder | stock board |
| "Used daily / weekly / rarely" | replaced: the four demand groups from step 3 | chips and drawer |
| Run-rate per day | replaced: per month, plus "never issued in three years" | item drawer |
| Organisation picker | dropped — one client, one plant | — |
| Calendar of known events | **still not built.** The data exists (planned work orders are already a second series on the drawer chart); a calendar screen is not in the approved scope | — |
| "Stock that could be moved" panel | **built** — the Storerooms page. The sending store only offers what it holds above its own level. Ranking by distance and delivery time is not done | Storerooms |

## The two screens step 7 builds

**Dashboard.** KPI cards, then one table: the work queue, ranked by criticality ×
SAR at risk, with the state colour band. Plus the backtest result and the
engine-versus-truth dead-money comparison, since those are the two headline numbers.

**Item view.** Usage history, the forecast, our recommended level against the
current min/max, and the reason string. Reached by clicking a row — a drawer if it
is cheap to build, otherwise a page, but the drawer is what made Noah's board quick
to work through.

Both read-only from `results/`, vendored JavaScript, no CDN.

---

## One caution

Noah's board was fast because its numbers were fast: run rate, days of cover, value
at risk. Ours are the output of a simulation over 25,000 positions. Everything the
screen shows must already be computed and written to `results/` — the API reads
files and nothing else. A screen that recalculates will disagree with the scoreboard
beside it, and will stall while somebody is watching it.
