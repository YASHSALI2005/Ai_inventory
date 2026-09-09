# What We Are Going To Build — Plan

**Ma'aden Aluminium · AI-Powered Inventory Intelligence & MRO Optimization**
SOW `MD-404-1000-OE-DG-SOW-0000_` Rev 0.0 · Use Case 01 · Phase 0

Written for a business reader. Where a technical choice matters to the outcome, it is named and
explained in one line — no maths background needed to follow it.

---

## 1. The problem in one page

Ma'aden Aluminium runs bauxite mine → 600 km rail → alumina refinery → smelter → rolling mill.
The refinery, smelter and mill all sit on one 20 km² site at Ras Al Khair.

Their storerooms are full. Their plants still go down waiting for parts.

**Both are true at the same time, in the same building.** A bearing fails at 2am; the storeroom
400 metres away does not have it; it is air-freighted at 3–5× the price and the mill sits idle
for three days. Meanwhile, three aisles away in that same storeroom, SAR 300,000 of filter
cartridges sit for a unit removed in 2019.

**The money to buy that bearing had already been spent. It was on a shelf, as something else.**

That is not a warehouse problem, and not a counting problem — their stock records are correct.
It is a **decision** problem: the wrong things were bought, because nobody could see across
20,000 items and several storerooms to know what would actually be needed.

---

## 2. What we are going to build

A platform that reads their inventory and maintenance data and answers four questions no stock
report can answer today:

1. **What will we need?** — and when
2. **What are we holding that we will never need?** — and what is it worth
3. **What should the stocking levels actually be?** — per item, not by habit
4. **What is wrong with the data itself?** — before any of the above is trusted

Plus a plain-language interface, so a planner can ask a question instead of learning a
reporting tool.

The Scope of Work lists seven capabilities. In order:

| # | Capability | In plain words | Depth |
|---|---|---|---|
| 1 | Predict demand | How many of this part will we need in six months — from usage history **plus** the maintenance plan, so a planned shutdown is a known spike, not a surprise | **Deep** |
| 2 | Find the dead money | Never-issued items, spares for scrapped equipment, the same part under three numbers, 400 held where 40 would do | **Deep** |
| 3 | Set the right levels | Reorder point and safety stock per item, from its own behaviour — not a number typed in years ago | **Deep** |
| 4 | Catch what is wrong | Negative stock, consumption with no work order, missing units of measure, blank part numbers | Solid |
| 5 | Move it, don't buy it | One storeroom holds 40 idle while another is about to buy five — costed by distance | Solid |
| 6 | Price the trade-off | "95% service instead of 98%?" — cash released against risk accepted | Interactive |
| 7 | Ask it a question | "Which critical spares at the smelter are below reorder point?" | **Deep** |

**How they connect:** 4 cleans the data → 1 predicts → 3 sets policy → 2 and 5 release the cash
→ 6 prices the trade-off → 7 is how people reach all of it.

**Explicitly out of scope for the POC:** writing back into SAP, single sign-on, production
transaction volumes, automatic purchase orders. **The system reads and recommends. A human
decides.**

---

## 3. The one technical idea that matters

Worth understanding even if you skip the rest of the technical section.

**MRO inventory is two different populations sharing one warehouse.**

| | Insurance spares | Consumables |
|---|---|---|
| Examples | Mill drive, main transformer, motor stator | Gaskets, filters, fasteners, lubricants |
| How many | A few thousand items | Tens of thousands |
| Value each | Very high | Low |
| Lead time | 6–18 months | Days to weeks |
| Used | Maybe once a decade | Continuously |
| If missing | **The plant stops** | Inconvenience |
| History to learn from | Almost none | Plenty |

Every inventory system on the market applies one safety-stock formula to everything. That
formula assumes usage follows a normal bell curve. **Fair for consumables, wrong for insurance
spares** — and insurance spares are exactly where being wrong is most expensive.

So the first thing our system does with any item is decide **which population it belongs to**,
and route it to the right method. That routing is the difference between a reporting dashboard
and something that changes a stocking decision.

---

## 4. How each capability will be built

Technical, but each entry gives the business reason first.

### Capability 4 — Data quality and anomaly detection
*Built first, because nothing downstream is believable until this is done.*

- **Rule checks** — negative stock, blank mandatory fields, unit-of-measure mismatch (EA vs
  BOX), impossible lead times, consumption with no matching work order. Deterministic rules, no
  AI needed. Most of the value here comes from simply *looking across everything at once*.
- **Unusual-usage detection** — flags consumption that does not fit an item's own history. Uses
  **robust z-scores based on median absolute deviation** rather than mean and standard
  deviation, because MRO usage is heavily skewed: one large issue would otherwise drag the
  average and hide the next anomaly.
- **Duplicate part detection** — the Alcoa/Alba problem. Two stages:
  1. *Narrow the field:* **TF-IDF over character n-grams** on normalised descriptions, plus
     exact manufacturer-part-number matching, to pull candidate pairs out of 20,000 items
     without comparing all 200 million combinations.
  2. *Score each pair:* fuzzy text similarity (**RapidFuzz token-set ratio**), agreement on
     structured attributes (manufacturer, size, UOM), and **sentence-embedding similarity** for
     cases where the words differ but the meaning does not — `BRG,BALL,6205` vs
     `BEARING BALL 6205`.
  - Above a confidence threshold it is flagged; borderline pairs go to a human review queue.
    **We never auto-merge master data.**

### Capability 1 — Demand forecasting

- **Step one: classify every item.** Using **ADI** (average interval between demands) and
  **CV²** (variability of demand size), each item falls into one of four classes — *smooth,
  erratic, intermittent, lumpy* — by the **Syntetos-Boylan-Croston** scheme. This is the
  population split from §3, made concrete and automatic.
- **Fast, regular items** → **gradient boosting (LightGBM)** over lagged usage, calendar
  features and maintenance-plan features. Handles non-linear patterns and multiple inputs well.
- **Intermittent and lumpy items** (the majority in MRO) → **Croston's method** and its two
  improvements: **SBA**, which corrects a known upward bias in Croston, and **TSB**, which
  updates the probability of demand every period so it reacts when an item is quietly going
  obsolete — that matters a great deal here. Implemented via the **`statsforecast`** library,
  which provides all three.
- **Insurance spares with no usable history** → do not forecast. Model **failure arrivals as a
  Poisson process** from the installed equipment population and its MTBF, and let criticality
  set a floor. Honest answer: for these items, reliability data beats demand history.
- **Maintenance overlay** — planned work orders and shutdown schedules are added as *known*
  future demand. Deterministic, not predicted, and a large part of the practical accuracy.
- **Accuracy measured with MASE**, not MAPE. MAPE breaks mathematically when demand is zero, and
  MRO demand is zero most days. Reported **separately per demand class** — a single blended
  figure would hide exactly where the model is weak.

### Capability 3 — Stocking policy (reorder points and safety stock)

- **Not** `z · σ · √LT`, for the reason in §3.
- **Empirical / bootstrap quantiles.** Resample the item's own historical demand over its
  protection window (lead time + review period) and read the quantile at the target service
  level. Non-parametric — no assumption about the shape of demand, so lumpiness is handled
  naturally rather than smoothed away.
- **Very sparse items** → fit a **compound Poisson** model (Poisson arrivals × a size
  distribution), the classical spare-parts approach; negative binomial where it fits better.
- **Service level per item, not one blanket number.** Derived from each item's own economics via
  the **newsvendor critical fractile** — holding cost against shortage cost. A cheap gasket and
  a mill drive should not both be stocked to 95%.
- **Criticality override.** A criticality-A insurance spare is stocked at a minimum of one
  regardless of what its history says. A business rule that overrules the maths, deliberately.
- Output is a standard **(s, S)** or **(R, s, Q)** policy per item — familiar to any planner.
- *Deferred:* multi-echelon optimisation across central and site stores (**METRIC /
  VARI-METRIC**) is the right long-term answer, but Phase 3 work, not POC.

### Capability 2 — Dead money (slow-moving, obsolete, excess, duplicate)

Mostly deterministic segmentation. This is not where AI is needed — it is where *seeing
everything at once* is needed.

- **ABC** (Pareto by annual value) × **XYZ** (demand predictability) × **FSN** (fast / slow /
  non-moving) × **criticality**, placing each item in a cell.
- **Excess** = on-hand minus the maximum the capability-3 policy engine would justify. Valued in
  SAR.
- **Obsolete** = no issues in N months **and** no link to any active equipment. That equipment
  link is what separates a genuinely obsolete part from an insurance spare — which is why the
  CMMS dependency in §10 matters.
- **Duplicate** = output of capability 4's matcher.
- Everything **ranked by money**, not by item count.

### Capability 5 — Stock transfers

- **Greedy assignment**: rank candidate moves by (receiver's need × item value) − transfer cost,
  capping the donor so it is never pushed below its own reorder point.
- **Transfer cost tiered by distance.** A move between two storerooms on the Ras Al Khair site is
  hours and a forklift; a move to or from Al Ba'itha is 600 km and several days. A system that
  treats those the same will recommend hauling a SAR 200 gasket across the country.
- A full **min-cost-flow / transportation** formulation is available if optimality ever justifies
  the complexity. For a POC, greedy is the right call.

### Capability 6 — Working-capital scenarios

- A **parameter sweep** across service levels, re-running the policy engine at each and plotting
  cash released against expected stockouts.
- The risk side comes from **Monte Carlo simulation** of demand over the horizon.
- Presented as a slider with a live curve, labelled on screen as a simplified model.

### Capability 7 — Conversational interface

- **Claude with tool use** (function calling) against a **fixed set of typed tools** —
  `get_items(filters)`, `get_stockouts(site, criticality)`, `get_slob(threshold)`,
  `get_transfer_candidates()`, and so on.
- **Not free-form text-to-SQL.** A model writing its own database queries is unpredictable and
  hard to audit. A fixed tool surface is testable, reviewable and safe.
- **The model never calculates.** It chooses the tool, passes arguments, receives structured
  numbers back, and narrates them. Every answer displays the figures and the item list it was
  given.
- Optionally, **embedding search** over material descriptions for "find me parts like this" —
  but any number in the answer still comes from the engine.

**Why this boundary matters:** if that interface invents a stock figure once, in front of a
planner, it will never be trusted again. Restricting it to narration is a deliberate design
decision, not a limitation we ran into.

---

## 5. Proposed stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Where the forecasting and data libraries live |
| API | FastAPI | Fast, typed, self-documenting |
| Data | pandas, numpy | Standard |
| Forecasting | `statsforecast` (Croston / SBA / TSB), LightGBM | Intermittent-demand methods already implemented and tested |
| Matching | RapidFuzz, scikit-learn TF-IDF, sentence-transformers | Duplicate detection |
| Database | PostgreSQL | Standard; no exotic requirement |
| AI layer | Claude, tool use | Narration over a fixed tool surface |
| Frontend | React + TypeScript | Dashboard, work queue, scenario simulator, chat |

Nothing here is exotic, and that is deliberate. A domain expert must be able to follow how a
reorder point was calculated. An auditable system is worth more than a clever one.

---

## 6. The data

The POC runs on a **synthetic Ma'aden Aluminium dataset that we generate**. No client data
needed, so we can start immediately.

The important design decision: **we plant the problems on purpose and keep a sealed answer key
the engine never sees.**

- 2 geographic locations, ~5 storerooms
- ~20,000 material master records on a PiLog-style ISO 8000 taxonomy
- 3 years of issues, receipts, transfers and returns, spread realistically across the four
  demand classes
- Equipment hierarchy with criticality, and maintenance plans including shutdowns
- **Planted defects:** duplicate part numbers, obsolete spares for scrapped equipment, negative
  stock rows, blank manufacturer part numbers, UOM errors, overstocked items, critical items
  below reorder point
- Values in SAR; English and Arabic descriptions where PiLog multilingual handling matters

A generator producing clean random data would give the AI nothing to find, and would let us
claim anything. With an answer key, we can be scored.

---

## 7. Build order

Each step is useless without the one before it.

| Step | What | Why here |
|---|---|---|
| 1 | **Synthetic data generator + answer key** | Everything is judged against it; nothing can be measured until it exists |
| 2 | **Data quality / anomaly engine** (cap 4) | Nothing downstream is trustworthy first |
| 3 | **Demand classifier** (ADI × CV²) | Routes every item; gates capabilities 1 and 3 |
| 4 | **Forecasters** (cap 1) | Croston / SBA / TSB + LightGBM + maintenance overlay |
| 5 | **Stocking policy engine** (cap 3) | Reorder points, safety stock, criticality override |
| 6 | **Dead money + transfers** (caps 2, 5) | Both read the policy engine's output |
| 7 | **API + dashboard + work queue + scenarios** (cap 6) | Makes it visible |
| 8 | **Conversational layer** (cap 7) | Last — it narrates what the engine already computes |

---

## 8. How we prove it works

Two mechanisms, both designed in from the start rather than added at the end.

**Defect scoring.** The generator's sealed answer key lists every planted problem. The system is
scored against it: found versus planted, plus false positives. The result is *"found 94 of 100
planted, 6 false positives"* — not *"it looks good."*

**Backtesting.** The recommended stocking policy is replayed over three years of history and
compared with a conventional min/max baseline on the same data — counting stockout-days, units
short, and capital employed. Same conditions, two methods.

**And one commitment:** every industry benchmark we quote is labelled as borrowed. We do not use
the common "50–60% of MRO is obsolete" figure — we could not trace it to a primary study. We use
the conservative 20–40% band, and Phase 2 replaces it with Ma'aden's own measured number.

---

## 9. Phases

| Phase | What | Outcome |
|---|---|---|
| **0** — done | Understanding and proposal | This document |
| **1** — the ask | Proof of concept on synthetic data, scored | Feasibility proven, opportunity sized |
| **2** | Pilot on one site, real ERP + PiLog extract | A real, defensible savings figure |
| **3** | Scale to all Aluminium BU sites, live integration | Operational system |
| **4** | Extend to phosphate, gold, industrial minerals | Enterprise platform |

Durations deliberately left open until scope is agreed.

**The design note that makes Phase 2 cheap:** the synthetic generator sits behind the same
interface a real SAP and PiLog connector would use. So *"how long before this runs on our real
data?"* is answered by **replacing one layer** — not rebuilding the system.

---

## 10. What we need from Ma'aden

None of these block the POC. Each one sharpens it.

1. **Which ERP and version** — SAP S/4HANA or ECC?
2. **Is there a CMMS or EAM** (SAP PM, IBM Maximo)? Capability 1 needs maintenance plans and
   equipment criticality; capability 2 needs the equipment link to tell an obsolete part from an
   insurance spare. A real dependency, not an assumption.
3. **How many storerooms, and how are they structured in SAP** — separate plants, or storage
   locations under one plant? This sets the transfer cost tiers.
4. **Total MRO inventory value and active SKU count** — to size the opportunity in SAR instead of
   in percentages.
5. **Are the Alba and ex-Alcoa material masters merged**, or still separate?
