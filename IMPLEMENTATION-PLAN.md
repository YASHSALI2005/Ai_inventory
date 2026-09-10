# How We Build It — Implementation Plan

Ma'aden MRO Intelligence POC · **Phase 1, scoped 2026-09-10**
Written plainly, for the person building it. Tick steps off as they land.

---

## What the POC has to prove

Three claims, and nothing else. Every item below serves one of them.

1. **We can find data problems** — measured against a sealed answer key.
2. **We can set better stock levels than the plant's min/max** — measured by
   backtest on the evaluation year.
3. **A planner can ask a question in English and get a checkable answer.**

If a piece of work does not serve one of those three, it is out of scope. Do not
build beyond this without asking.

---

## Build order

### Step 2 — Data quality (capability 4)  ·  *in progress*

Six remaining rule checks plus the duplicate matcher. **One at a time, with the
full-preset scoreboard after each** — a batch of six checks landing together makes
a regression impossible to attribute.

| Check | Signal |
|---|---|
| `NEGATIVE_STOCK` | ✅ done — balance below zero |
| `LEDGER_MISMATCH` | ✅ done — movements do not sum to the balance (informational) |
| `BLANK_MPN` | manufacturer part number empty |
| `BLANK_UOM` | unit of measure empty |
| `UOM_MISMATCH` | UOM disagrees with the material group's dominant unit, with no matching price change |
| `IMPOSSIBLE_LEAD_TIME` | lead time at or below 1 day, or beyond any real procurement window |
| `ISSUE_WITHOUT_WORK_ORDER` | stock issued with no maintenance job behind it |
| `DUPLICATE_MATERIAL` | two masters describing the same physical part |

**The matcher.** A list of scorers, combined:
- TF-IDF character n-grams over noun / modifier / size token
- RapidFuzz token-set ratio over the full description
- exact and near manufacturer-part-number match

It has to survive two things the generator does on purpose:
- **Split history** — half the planted duplicates carry 20–60% of the original's
  issues, so neither line looks anomalous on its own.
- **Shadowed blank MPNs** — a copy that lost its part number is also a real
  `BLANK_MPN`, recorded in the answer key so it scores as a hit rather than a
  guaranteed false alarm.

Scored as **unordered pairs**. Target **recall ≥ 90%, precision ≥ 85%**, with
misses reported per mangle style so a loss to a dropped size token is
distinguishable from a loss to a one-character typo.

### Step 3 — Demand classifier

ADI × CV² (Syntetos-Boylan-Croston), **fitted on the train slice only**. Scored
against `PROFILE_TO_SBC_CLASS`, which is a many-to-many tolerance table — a truth
profile constrains which quadrant is reasonable without determining it. Report the
mix; it should come out majority intermittent/lumpy.

### Step 4 — Forecast, Croston family only

| Class | Method |
|---|---|
| intermittent, lumpy | Croston / SBA / TSB via `statsforecast` |
| smooth, erratic | seasonal naive or simple exponential smoothing |
| insurance | Poisson from `mtbf_years` × installed base |

Planned work orders and shutdown windows are added **on top** as known demand —
that is what `created_date` and `planned_date` exist for.

**No LightGBM in the POC.** Fit on train, score **MASE per class** on eval against
both a naive and a zero-forecast baseline, and report honestly where we lose. For
intermittent and lumpy classes the decisive number is the step-5 backtest, not
MASE.

### Step 5 — Levels and backtest  ·  *headline number two*

Reorder point and safety stock per position:
- empirical quantile over the protection window (lead time + review period)
- service level from `cfg.costs.critical_fractile`
- criticality floor from `cfg.dead_money.criticality_floor`
- **a plain-English reason string per position** — a number a planner cannot
  question is a number they will not act on

Then replay the **evaluation year** through `sim.walk` with our levels against the
stale min/max, on **identical demand and identical lead-time draws** — the same
world, two policies, or any improvement reported is an artefact.

Report **stockout days, units short, average capital and shortage cost**, per
policy × criticality × storeroom.

### Step 6a — Dead money

The engine computes its own dead-money list: step 5's justified quantity, plus
obsolescence inferred from equipment status and demand cessation. Ranked in SAR at
SAP moving average.

Scored against truth: SAR found / SAR true / SAR wrongly flagged, and obsolete
found / missed / false. The engine's figure goes on the dashboard **beside** the
truth figure, both labelled.

### Screens — two, and only two

**Dashboard** (extend the existing one): backtest result, engine-vs-truth
dead-money comparison, top-20 dead-money table.

**Item view** (new): usage history chart, forecast, recommended levels against the
current min/max, and the reason string.

Both read-only from `results/`. **Vendored JS, no CDN** — a dashboard that renders
blank in a meeting room is worse than no dashboard.

### Step 8 — Chat, thin

Claude with exactly four tools:

```
get_stockouts(storeroom?, criticality?)
get_dead_money(storeroom?, top_n)
get_item(material_id)
get_levels(material_id)
```

Tools read `results/` only and validate arguments with Pydantic. **The model
narrates; it never calculates.** Every answer shows the numbers and the item list
beneath it.

Twenty golden questions in a test, each with its expected tool call and expected
figures.

---

## Only if all of the above is green

- Transfers (step 6b)
- Scenario slider, from the precomputed sweep
- Work queue as a sortable table on the dashboard

## Not being built

LightGBM · embedding-based matching · Arabic descriptions · login · SAP connection ·
purchase orders · any screen beyond the two above.

---

## Rules that do not bend

- **`engine/` never touches `answer_key/`.** A test parses the AST and the source
  text and fails if it does.
- **Score after every step.** Not after every three.
- **Every recommendation carries a reason.**
- **The chat never calculates.**
- **No new library without a reason in `DECISIONS.md`.**
- **`stock.on_hand` is never written by hand** — it is recomputed from the ledger.
- No Co-Author lines on commits.

---

## Tools

| For | Choice |
|---|---|
| Language | Python 3.12 |
| Data | Parquet + pandas; no database server |
| Forecasting | `statsforecast` — Croston / SBA / TSB |
| Matching | RapidFuzz + scikit-learn TF-IDF |
| API | FastAPI |
| Screens | React, vendored, no build step |
| Chat | Claude, tool use |

---

## How we know it worked

Three sentences, each backed by a number this pipeline produces:

- *"We hid N problems in the data. It found X, with Y false alarms."*
- *"Against the plant's own min/max, over the same year and the same demand: A%
  fewer stockout days and SAR B less capital employed."*
- *"Here is SAR C of dead stock, item by item — and here is the same figure
  measured from the answer key, so you can see how close we got."*
