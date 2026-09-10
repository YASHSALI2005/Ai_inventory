# Demo script — ten minutes in Present mode

*Numbers regenerated from `results/` (full preset). Start the server with
`python cli.py serve --preset full`, click **Present** in the nav (or open
`#/present/`), and walk with → . Escape leaves Present mode. Set `ANTHROPIC_API_KEY`
before starting if the chat is part of the demo.*

## 0 · The problem — 1 minute, no screen yet

"The storeroom is full: 35% of the parts on its shelves have not
moved in two years. The plant is still running short: jobs wait for parts that are not
there while the same part sits idle in the next store. And it pays twice — once for
stock nobody will use, again at three to five times the price for the emergency buy.
Everything you are about to see was measured against a sealed answer key, not asserted."

## 1 · Dashboard — 2 minutes  (`#/present/`)

Four tiles, left to right:
- **SAR 1,460.8m on the shelves.** "That is the pile."
- **SAR 388.1m that will never come back — found by the system.** Point at the
  sub-line: the answer key says SAR 391.7m; we found 98%
  of it with SAR 5.3m wrongly flagged. "That is the third headline number."
- **2,999 critical parts below their safe level**,
  SAR 316.4m to put right. "That is today's list."
- **56% fewer days waiting for a part** with our levels, holding
  +28% more stock, all costs -36%.
  "That is the second headline number — and yes, we hold more stock. More stock, less waste."

Click **ROLLING** in the store selector: tiles and the monthly line re-scope. Click **Whole
plant** again. Hover the monthly line: actual usage, the forecast laid over the tested year,
and the dashed year ahead.

## 2 · The frontier — 1 minute  (same page, bottom chart)

"Every point is the same year replayed at one blanket service level." Drag the handle
from 50% to 99.5%: the four figures under it move — value on the shelves, days waiting,
all costs, purchase orders — each with its delta against the plant today. "The plant's own
levels are the black ring, off the left end: they wait longer than our worst sampled point
while holding less. Their policy is under-serving, not over-invested. That is why the cash
comes from dead money, not from levels." The orange dot is ours: each part at its own level.

## 3 · Recommendations — 2 minutes  (→ to `#/present/recommendations`)

Three tabs, each ranked by money with a total and an Excel export.
- **Order** — "7,678 orders, SAR 974.1m. Quantity, order-by
  date, cost, and the reason for the level in plain words."
- **Move** — "60 parts sitting spare in one store while another is short:
  SAR 6.3m of buying avoided. The sending store only gives what it holds above
  its own level."
- **Write off / review** — "The dead-money list, one reason per record: the machine is gone,
  never used, duplicate, idle with nothing scheduled, excess."

## 4 · One part — 2 minutes  (Stock board, first row, or any row)

Click the top row. Read the drawer top to bottom: **what to do** in the accent; the stat row;
the chart — three years of movement, the forecast laid over the tested year, scheduled work
dashed; then **why this number**: how often it moves, how much, which method, the old rule
against ours, and the engine's own sentence. If the filter (M-016367) is in view, tell its
story: "a part that draws ~900 a month and 5,000 in a burst twice a year. The first version
of the levels held eighteen months of it. Now: three windows of everyday usage, with the
outage draw scheduled against the calendar instead of buffered."

## 5 · Ask — 1½ minutes  (→ to `#/present/chat`)

Three questions, typed or from the chips:
1. "Which A-critical parts are out of stock in the rolling mill?"
2. "How much dead money is there, and what is the biggest item?"
3. "Tell me about M-016367."
Point at the line under each answer: *answered by get_stockouts {…} — every figure above is
in the rows below*. "The model never calculates. It picks one of four questions the system
has already answered and reads the answer back. Ask it something the data cannot answer and
it will say so."

## 6 · Evidence — 30 seconds  (footer link)

"For the engineers." Faults found: 98% recall, 98%
precision against the sealed answer key. Forecast accuracy per class. The backtest table with
the honest callout. The service-level curve. Stop here; leave it on the screen for questions.

## If asked

- *Is the data real?* No — invented plant, planted faults, sealed answer key. Phase 1 swaps the
  generator for the SAP/PiLog extract behind the same interface; the screens do not change.
- *Why does capital go up?* Because the plant under-serves today. Pricing an expedite properly
  makes holding almost any part worthwhile; the cash release is the dead-money list.
- *Why 98% on dead money?* Most of it is a lookup on fields the plant already has. The value is
  applying one rule consistently across every record with a reason on each.
