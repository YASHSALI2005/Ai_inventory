# AI-Powered Inventory Intelligence & MRO Optimization
## Understanding & Proof-of-Concept Proposal — Ma'aden Aluminium

**SOW reference:** MD-404-1000-OE-DG-SOW-0000_ · Revision 0.0 · Use Case 01
**Issue date of SOW:** 13 August 2026 (DRAFT)
**Status of this document:** Phase 0 — understanding and proposal, for management review

---

## Executive summary

**We propose a proof-of-concept that proves, on data, that a meaningful share of Ma'aden
Aluminium's MRO inventory is dead capital — and that the parts which actually matter can be
protected better than they are today, for less money.**

Industry benchmarks put 20–40% of typical MRO inventory in the excess-or-obsolete category
while the same plants still face stockout risk on 10–15% of their critical parts. Both
problems have one root cause: stocking levels are set by memory and habit rather than by each
part's own demand behaviour, lead time and consequence-of-failure.

The POC will be built on a synthetic Ma'aden Aluminium dataset that we generate ourselves —
no client data required, no data-sharing delay. Crucially, we plant known defects in that
data and keep an answer key, so the POC can be **scored** rather than merely demonstrated. We
will report how many of the planted problems the system found, and how the recommended
stocking policy performs against a conventional min/max baseline when replayed over history.

We are asking for a decision on one thing: proceed to build the POC.

---

## 1. The problem, as we understand it

The SOW's problem statement describes something every asset-intensive operator recognises:

> *the storeroom is full and the plant is still short.*

Ma'aden Aluminium operates a fully integrated chain — bauxite mine, 600 km rail link, alumina
refinery, aluminium smelter, rolling mill. Every one of those is a continuous process. An
hour of unplanned downtime costs far more than the part that caused it, which creates a
rational but expensive instinct: **when in doubt, stock it.**

Repeated across thousands of items, several warehouses and multiple decades of plant history,
that instinct produces exactly the four symptoms the SOW names:

| Symptom | What causes it |
|---|---|
| **Excess inventory** | Levels set once, never revisited as consumption changed |
| **Duplicate stock** | The same physical part held under different part numbers and descriptions |
| **Obsolete materials** | Equipment was decommissioned; its spares were not |
| **Stockouts** | Attention and budget went to the wrong items — the ones that were easy to see |

None of these is a discipline failure. They are a **visibility** failure. No planner can hold
20,000 items across five warehouses in their head, and no spreadsheet distinguishes a part
that hasn't moved in three years because it's obsolete from one that hasn't moved in three
years because it's the insurance spare that keeps the smelter running.

---

## 2. Ma'aden Aluminium — context

*(All figures from public sources; see References.)*

### The company
| | |
|---|---|
| Founded / headquarters | 1997 · Riyadh |
| Ownership | ~50% Saudi government (PIF) · ~50% listed on Tadawul |
| FY2025 revenue | ~SAR 38.6 billion (~USD 10.3 billion), **+19% year on year** |
| FY2025 net profit | ~USD 2.0 billion |
| Employees | 8,000+ |
| Business segments | **Aluminium**, Phosphate, Gold & Base Metals, Industrial Minerals, Zinc & Copper |

### The Aluminium business unit — the scope of this use case
| Asset | Location | Nameplate capacity |
|---|---|---|
| Al Ba'itha bauxite mine | Al Ba'itha, Qassim region | 4.0 Mt/y bauxite |
| Rail link | Al Ba'itha → Ras Al Khair | 600 km |
| Alumina refinery | Ras Al Khair | 1.8 Mt/y alumina |
| Aluminium smelter | Ras Al Khair | 740–750 kt/y primary aluminium |
| Rolling mill (flat-rolled products) | Ras Al Khair | 380 kt/y |

The Aluminium BU generated approximately **USD 5.26 billion in H1 2025 alone**, with
flat-rolled product volumes up 24% year on year.

### How this is laid out on the ground — and why it matters

This is **two geographic locations, not five.** The bauxite mine stands alone in central
Arabia. The refinery, smelter and rolling mill are **all on one site** at Ras Al Khair — a
single ~20 km² integrated complex on the Gulf coast, 90 km north of Jubail, marketed as the
most vertically integrated aluminium complex in the world.

Two consequences for the platform:

**Transfers must be costed by distance, not treated alike.** A move between two storerooms
inside the Ras Al Khair site is hours and a truck across the campus — almost always cheaper
than buying. A move between Al Ba'itha and Ras Al Khair is 600 km, several days and real
freight cost, worth it only above a value threshold. A recommendation engine that treats
those identically will propose hauling a SAR 200 gasket 600 km.

**One site does not mean one storeroom.** 20 km² is not a walk; standard practice is a main
warehouse plus satellite storerooms per plant. Three plants on one campus, each raising its
own requisitions against its own store, with nobody holding a view across all three, is the
*same* duplicate-stock mechanism as the Alcoa/Alba consolidation — operating locally and
continuously. Their actual storeroom structure is not public; see Open Question 6.

### Why this problem is live right now

During 2025 Ma'aden completed two major consolidations: it acquired **Alcoa's** interests in
the aluminium joint venture (closed July 2025) and **SABIC's** stake in **Aluminium Bahrain
(Alba)**.

This matters directly to the SOW. Two established asset bases were absorbed, each arriving
with its own material master, its own part-numbering conventions, its own warehouses and its
own stocking history. That is the standard mechanism by which the same bearing ends up
stocked three times under three different descriptions.

**The SOW's "duplicate stock" and "material master data issues" bullets are not hypothetical
risks. They are the predictable arithmetic of a consolidation that completed last year.** Any
platform built for Ma'aden Aluminium should treat cross-master reconciliation as a first-class
requirement rather than a nice-to-have.

---

## 3. What is actually in this inventory

Understanding the *content* of the inventory is what separates a generic inventory tool from
one that works here.

| Area | Representative MRO content |
|---|---|
| **Smelter (potline)** | Anode assemblies, cathode blocks, pot-lining refractory, busbar and rodding components, crucibles, tapping equipment, alumina handling conveyors |
| **Alumina refinery** | Digester and pressure-vessel spares, slurry pumps, valves, high-wear piping and liners, filter cloths, heat-exchanger tubes, caustic-service seals and gaskets |
| **Rolling mill** | Work rolls and backup rolls, bearings and chocks, hydraulic and lubrication systems, shears and knives, coilers, rolling-emulsion filtration |
| **Mine and rail** | Haul truck, shovel, crusher and conveyor components; tyres; ground-engaging tools; rolling-stock spares |
| **Site-wide** | Transformers, MV switchgear, drives, cabling, motors, gearboxes, bearings, seals, instrumentation, lubricants, process chemicals, PPE, general consumables |

### The single most important technical observation

**This is not one inventory. It is two populations sharing a warehouse.**

**Population A — insurance spares.** A few thousand items: a spare mill drive, a main
transformer, a large motor stator. Value per unit is very high. Lead times run 6 to 18
months. They may be consumed once a decade. If one is missing on the day it is needed, the
plant stops. Statistically, there is almost **no demand history to learn from**.

**Population B — consumables.** Tens of thousands of items: gaskets, filters, fasteners,
lubricants, standard bearings. Individually inexpensive, consumed continuously, with rich
history that is straightforward to forecast.

Conventional safety-stock mathematics — the textbook `z · σ · √LT` formula — assumes demand
follows a bell curve. That assumption is reasonable for Population B and **quietly wrong for
Population A**, which is precisely where the expensive mistakes live. A system that applies
one method to both will produce confident, well-formatted, incorrect numbers on exactly the
items that matter most.

**Handling these two populations by different methods is the technical spine of what we
propose, and the thing that makes it more than a dashboard.**

---

## 4. What the seven required capabilities mean in practice

The SOW lists seven expected capabilities. Restated for a non-specialist reader:

| # | The requirement | What it means in practice | Business value |
|---|---|---|---|
| **1** | Predict spare parts and consumable demand using historical consumption, maintenance plans, equipment criticality and operational data | *How many of this part will we need over the next six months?* Learn from issue history **and** from the maintenance schedule — a planned shutdown is a known future demand spike, not a surprise | Buy ahead at planned prices instead of expediting at 3–5× cost |
| **2** | Identify slow-moving, obsolete, duplicate and excess inventory | *Which of this money is dead?* Items never issued; spares for equipment that no longer exists; the same part under several numbers; 400 units held where 40 would do | The largest and fastest one-time release of cash |
| **3** | Recommend optimal inventory levels, reorder points and stocking policies | *When to reorder, and how much* — computed per item from its own demand pattern, lead time and criticality, rather than a figure entered years ago | Less capital frozen at the same or better service level |
| **4** | Detect inventory anomalies and material master data issues | *What is demonstrably wrong?* Negative stock balances, consumption with no matching work order, missing units of measure, blank manufacturer part numbers, UOM inconsistencies | Data trust — nothing downstream is credible without it |
| **5** | Recommend stock transfers between warehouses and sites | *One site holds 40 units it isn't using while another is about to purchase 5* — move it, don't buy it | Free inventory; avoids the purchase entirely |
| **6** | Provide AI-driven optimization scenarios to reduce working capital while maintaining service levels | *"What happens if we accept 95% service instead of 98%?"* — cash released plotted against risk accepted, with the specific items each scenario touches | Converts a stocking argument into a priced executive decision |
| **7** | Generate insights and recommendations through a conversational AI interface integrated with MDRM (PiLog) and ERP | *Ask in plain language:* "which critical spares at the smelter are below reorder point?" | Adoption — a planner who will not learn a BI tool will type a question |

**How they fit together.** Capability 4 cleans the data. Capability 1 predicts demand.
Capability 3 turns that into policy. Capabilities 2 and 5 release the trapped cash.
Capability 6 prices the trade-off for executives. Capability 7 makes all of it reachable
without training. **Capability 4 is the foundation; capability 7 is the front door.**

---

## 5. The size of the prize

Published benchmarks for MRO inventory in asset-intensive industry:

- **20–40%** of typical MRO inventory is excess or obsolete. McKinsey has put **more than
  40%** of heavy-industry spares in the slow-moving, rarely-consumed category.
- **30–50%** of parts have not moved in 24 months.
- Asset-intensive plants typically carry **20–30% excess inventory** *while simultaneously*
  facing stockout risk on **10–15% of critical parts**.
- Emergency or expedited procurement costs **3–5×** the equivalent planned purchase — and
  more once expedited freight and customs are included.

**A note on honesty.** A widely circulated figure claims 50–60% of MRO inventory is
slow-moving or obsolete. We have not been able to trace it to a primary study; it appears to
originate in consultant estimates drawn from self-selected engagements. **We therefore quote
the conservative 20–40% band**, and we commit to replacing every one of these external
benchmarks with Ma'aden's own measured figures in the pilot phase.

The method for sizing the opportunity is deliberately simple and reproducible: apply the
conservative excess band to Ma'aden Aluminium's stated MRO inventory value, and apply the
expedite premium to its unplanned-purchase volume. We would rather present a range a manager
can reproduce on the back of an envelope than a precise number they cannot.

---

## 6. What we propose to build

**Principle: all seven capabilities demonstrated end-to-end; three built deep.**

A demo that omits a capability invites the question "so it doesn't do number five?" A demo
where all seven are shallow reads as a mockup. Depth goes where the money and the technical
credibility are.

### Built deep — real algorithms, defensible in front of domain experts

**Capability 2 — Slow-moving, obsolete, duplicate and excess detection.** The largest,
fastest and most provable release of cash. Includes cross-master duplicate detection against
a PiLog-style ISO-8000 taxonomy — the Alcoa/Alba consolidation problem described in §2.

**Capability 3 — Reorder point and safety-stock optimization.** Each item is classified by
its demand pattern (the Syntetos-Boylan-Croston scheme: smooth, erratic, intermittent, lumpy)
and routed to the appropriate method. Lumpy and intermittent items — the majority in MRO —
use an empirical, non-parametric demand distribution rather than the bell-curve formula. A
criticality override ensures a never-consumed insurance spare is still stocked, regardless of
what its history says.

**Capability 7 — Conversational interface.** The demonstration moment. A natural-language
question is translated into a structured query against the analytics engine; the result is
narrated back with the numbers and the underlying item list always visible.

### Built solid — real logic, narrower scope

**Capability 1 — Demand forecasting.** Croston / SBA / TSB methods for intermittent demand, a
gradient-boosted model for fast movers, and a maintenance-plan overlay so scheduled shutdowns
appear as forecast demand. Accuracy reported honestly and separately per demand class.

**Capability 4 — Anomaly and master-data quality.** Negative stock, consumption without a
work order, implausible lead times, missing or blank mandatory attributes, unit-of-measure
inconsistencies, and a taxonomy-completeness score.

**Capability 5 — Inter-warehouse transfers.** A ranked list of transfer opportunities with
value freed, sized so the sending storeroom is not stripped below its own requirement, and
**costed in two tiers** — within the Ras Al Khair site, versus the 600 km move to or from
Al Ba'itha.

### Built as an interactive demonstration — simplified model, and we say so

**Capability 6 — Working-capital scenarios.** A service-level control producing a live
cash-released-versus-risk-accepted curve, with the specific items each scenario affects.

### Explicitly out of scope for the POC

Stated plainly so it cannot become a surprise later:

- Live read/write integration with ERP or PiLog MDRM
- Production authentication and SSO
- Production-scale transaction volumes
- Automatic purchase order creation

**The POC reads and recommends. A human decides.** That boundary is deliberate and, in our
view, should survive into production for anything above a value threshold.

---

## 7. The dataset

The POC will run on a synthetic Ma'aden Aluminium dataset that we generate. This removes any
dependency on client data access and lets us begin immediately.

A demonstration is only as convincing as its data. A generator producing clean random numbers
gives the AI nothing to find. **We therefore plant defects deliberately and keep a
ground-truth answer key** — which turns "this looks plausible" into "it found 94 of the 100
problems we hid, with 6 false positives."

Target shape:

- **Two geographic locations, five storerooms** — Al Ba'itha mine (Qassim), and the Ras Al
  Khair site with a storeroom each for refinery, smelter and rolling mill plus a central
  warehouse. **The five-storeroom split is our assumption**, not published fact — see the
  transfer-cost note below and Open Question 6
- **~20,000 material master records** on a PiLog-style ISO-8000 taxonomy (noun–modifier plus
  characteristics), with the MRO content mix described in §3
- **Three years of goods movements** — issues, receipts, transfers, returns — distributed
  realistically across the four demand classes, with intermittent and lumpy items in the
  majority as they are in reality
- **Equipment hierarchy with criticality ratings** and **maintenance plans including planned
  shutdowns**, so capability 1 has genuine signal to work with
- **Planted defects with an answer key** — duplicate part numbers under differing descriptions
  (the consolidation scenario), obsolete spares for decommissioned equipment, negative stock
  rows, blank manufacturer part numbers, unit-of-measure errors, overstocked items, and
  critical items sitting below their reorder point
- Values in **SAR**; English and Arabic descriptions where PiLog's multilingual handling is
  relevant

---

## 8. Architecture

```
   SOURCES                INGESTION            INTELLIGENCE             SURFACE
┌──────────────┐      ┌───────────────┐   ┌────────────────────┐   ┌───────────────┐
│ ERP (SAP)    │      │               │   │ Data quality &     │   │ Executive     │
│ stock, POs,  ├─────▶│  Adapter      │   │ anomaly engine     │   │ dashboard     │
│ movements    │      │  layer        │   ├────────────────────┤   ├───────────────┤
├──────────────┤      │               │   │ Demand classifier  │   │ Planner       │
│ PiLog MDRM   │─────▶│  (synthetic   ├──▶│ → forecaster       ├──▶│ work queue    │
│ taxonomy     │      │   generator   │   ├────────────────────┤   ├───────────────┤
├──────────────┤      │   plugs in    │   │ Stocking policy    │   │ Scenario      │
│ CMMS / EAM   │─────▶│   here for    │   │ engine (RoP / SS)  │   │ simulator     │
│ WOs, crit.   │      │   the POC)    │   ├────────────────────┤   ├───────────────┤
└──────────────┘      └───────────────┘   │ SLOB / duplicate / │   │ Conversational│
                                          │ transfer optimiser │   │ interface     │
                                          └────────────────────┘   └───────────────┘
```

### Two design decisions worth stating to management

**The adapter layer.** The synthetic generator sits behind the same interface a real SAP and
PiLog connector would use. This means the answer to *"how long before this runs on our real
data?"* is **"replace one layer"** rather than "rebuild it." The POC is built to be promoted,
not thrown away.

**The AI boundary.** The conversational layer translates a question into a call against the
analytics engine and narrates the structured result. **It does not perform calculations and
it does not generate figures.** Every answer displays the numbers and the underlying item
list. This is the difference between a tool planners come to trust and a demonstration that
invents a stock figure in front of the CFO.

---

## 9. Delivery phases

| Phase | Content | Outcome |
|---|---|---|
| **0 — Understanding** *(this document)* | Problem framing, company research, proposed scope | Decision to proceed |
| **1 — Proof of concept** | Synthetic dataset, all seven capabilities, three built deep, demo-ready | Feasibility proven; opportunity sized |
| **2 — Pilot** | One site (proposed: RAK smelter), real ERP and PiLog extract, benchmarks re-baselined on Ma'aden's own data | A real, defensible savings figure |
| **3 — Scale** | All Aluminium BU sites, live integration, planner workflow, change management | Operational system |
| **4 — Extend** | Other Ma'aden business units — phosphate, gold, industrial minerals | Enterprise platform |

Phase durations are intentionally left open until scope is agreed. Committing to dates before
the work is costed is how projects acquire deadlines nobody can meet.

---

## 10. How the POC will be verified

The POC is designed to be measured, not just shown. Two mechanisms:

**Defect detection scoring.** The synthetic generator writes a ground-truth answer key of
every planted defect. The POC is scored against it: defects found versus defects planted,
plus false positives. This produces a precision and recall figure for capabilities 2 and 4.

**Policy backtesting.** The recommended stocking policy is replayed against three years of
history and compared with a conventional min/max baseline, counting stockout-days, units
short, and capital employed. This produces a like-for-like comparison rather than a claim.

**The intent is that every number in the final presentation is one we measured, and every
number we borrowed from industry is labelled as borrowed.**

---

## 11. Open questions for Ma'aden

These do not block the POC, but each one sharpens it:

1. **Which ERP and version** — SAP S/4HANA or ECC?
2. **Is there a CMMS/EAM** (SAP PM, IBM Maximo, or other)? Capability 1 requires maintenance
   plans and equipment criticality, which live in the maintenance system rather than the ERP
   stock tables. This is a dependency, not an assumption we can quietly make.
3. **Scope** — Aluminium BU only, or all Ma'aden business units?
4. **Current total MRO inventory value and active SKU count** — needed to size the opportunity
   in SAR rather than in percentages.
5. **Are the Alba and former-Alcoa material masters already merged**, or still maintained
   separately?
6. **How many storerooms are there, and how are they structured in SAP** — separate plants,
   or one plant with multiple storage locations? This determines whether cross-store
   visibility is a reporting change or an integration one, and it sets the cost tiers for
   transfer recommendations.

---

## References

Company and operational data:
- Arabian Business — *Saudi mining giant Ma'aden posts $2bn profit as 2025 revenue rises to $10.3bn*
- Arab News — *Ma'aden posts 91% profit surge to $1.51bn in first 9 months of 2025*
- Fluor — *Ma'aden Aluminum Project Management* (site capacities)
- Wikipedia — *Ma'aden (company)* (segments, ownership, employee count)

Master data:
- PiLog Group — *Material Master Taxonomy 4.0 for SAP Master Data Governance*

MRO benchmarks:
- Verusen — *Obsolete & Slow-Moving (SLOB) MRO Inventory: A Guide*
- ReliaMag — *MRO and Spare Parts Inventory Statistics*
- McKinsey, as cited in the above

Forecasting methods:
- Syntetos & Boylan — demand classification for intermittent demand
- Croston / SBA / TSB — intermittent demand forecasting methods

---

*Prepared as Phase 0 of the response to MD-404-1000-OE-DG-SOW-0000_ Rev 0.0, Use Case 01.*
