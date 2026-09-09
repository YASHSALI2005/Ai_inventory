# ARCHITECTURE — Ma'aden MRO Intelligence POC

System shape, not implementation detail. Update when the shape changes.

**Status: designed, not built.** No code exists yet (Phase 0). This is the target.

---

## Layers

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

Data flows left to right only. Nothing in Intelligence reaches back to Sources; nothing in
Surface computes.

---

## Layer responsibilities

### Sources
For the POC these are simulated. Named here because the adapter interface is designed to
their real shapes, not to the generator's convenience.

- **ERP (SAP, version TBC)** — stock balances, goods movements, purchase orders, lead times
- **PiLog MDRM** — material master, ISO 8000 / 22745 taxonomy, descriptions
- **CMMS / EAM (SAP PM or Maximo, existence TBC)** — work orders, equipment hierarchy,
  criticality, maintenance plans. **Open dependency** — capability 1 needs it.

### Ingestion — the adapter layer
**The load-bearing design choice.** One interface; the synthetic generator implements it for
Phase 1, a real connector implements it for Phase 2. Normalises source records into the
internal model regardless of origin.

Also where the generator's **ground-truth answer key** is emitted — separately from the data
itself, so the intelligence layer can never see it.

### Intelligence — pure computation, no I/O
Four engines, ordered by dependency:

1. **Data quality & anomaly engine** (capability 4) — runs first; everything downstream
   depends on its output being trusted. Negative stock, consumption without a work order,
   implausible lead times, missing mandatory attributes, UOM inconsistency, taxonomy
   completeness.
2. **Demand classifier → forecaster** (capability 1) — classifies each item by ADI × CV²
   into smooth / erratic / intermittent / lumpy, then routes: Croston/SBA/TSB for
   intermittent, gradient-boosted model for fast movers, maintenance-plan overlay for known
   future spikes. **This classifier is the two-populations split** and gates the policy engine.
3. **Stocking policy engine** (capability 3) — reorder point, safety stock, order quantity.
   Empirical non-parametric quantiles over the protection window for lumpy/intermittent
   items; criticality override for insurance spares with no history.
4. **SLOB / duplicate / transfer optimiser** (capabilities 2, 5) — dead-money detection and
   cross-warehouse redistribution, both ranked in SAR.

Capability 6 (scenario simulation) is a parameter sweep over 3, not a fifth engine.

### Surface
Reads from Intelligence. Computes nothing.

- **Executive dashboard** — capital at risk, dead money, service level, by site
- **Planner work queue** — ranked by expected cost of being wrong, in SAR, not by severity label
- **Scenario simulator** — service level in, cash-versus-risk curve out
- **Conversational interface** (capability 7) — natural language in, engine call out,
  narrated result with numbers and item list always shown

---

## The AI boundary

The conversational layer sits **outside** the intelligence layer and calls into it. It
translates a question into a structured query and narrates the structured result.

**It performs no arithmetic and generates no figures.** Every answer displays the numbers it
was given and the underlying item list. See `DECISIONS.md`, 2026-09-09.

---

## Verification surfaces

Two, both designed in from the start rather than bolted on:

- **Answer-key scorer** — compares detected defects against the generator's ground truth.
  Precision and recall for capabilities 2 and 4.
- **Backtest harness** — replays the stocking policy against three years of generated history
  versus a conventional min/max baseline. Stockout-days, units short, capital employed.

---

## Open architectural questions

- ERP version (S/4HANA vs ECC) changes the connector, not the shape.
- Whether a CMMS exists and is reachable. If not, capability 1 loses its maintenance-plan
  overlay and degrades to history-only forecasting — worth stating to the client as a
  dependency, not discovering at Phase 2.
