# HANDOVER — Ma'aden MRO Intelligence POC

**Read this first.** Living status board, updated every session. Not a log — history lives
in git and `DECISIONS.md`.

## What this project is

Response to Ma'aden SOW `MD-404-1000-OE-DG-SOW-0000_` Rev 0.0, **Use Case 01 — AI-Powered
Inventory Intelligence & MRO Optimization**. A proof of concept on synthetic data.

**Scope was fixed on 2026-09-10 to three claims and nothing else** — see
[`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md), which is now the authority on what
gets built:

1. We can find data problems, measured against a sealed answer key.
2. We can set better stock levels than the plant's min/max, measured by backtest.
3. A planner can ask a question in English and get a checkable answer.

If a piece of work does not serve one of those three, it is out of scope. Explicitly
**not being built**: LightGBM, embedding-based matching, Arabic, login, SAP connection,
purchase orders, or any screen beyond the dashboard and the item view.

Build plan in plain words (algorithms named): **[`docs/build-plan.html`](docs/build-plan.html)**
→ https://claude.ai/code/artifact/2d0d30b3-41c0-4460-8160-b5537a378b35 (source text: `docs/BUILD-PLAN.md`).
Client-facing scope, benchmarks and architecture: **[`docs/PROPOSAL.md`](docs/PROPOSAL.md)**.
Read it before touching anything — it is the agreed statement of what we are building and why.

## Status — 2026-09-10

**Phase 0 approved. Phase 1 (POC) in progress — vertical slice runs end to end at
both presets, and the dataset now survives review.**

Run it:

```
python cli.py all --preset toy      # build + engine + scoreboard   (~1s)
python cli.py all --preset full     # 20k materials                 (~33s)
python -m pytest -q                 # 128 tests
python cli.py serve --preset full   # the three screens
python -m ruff check .
```

Stages are separate on purpose: `build` writes the dataset and answer key, `run`
executes the engine and never touches `answer_key_dir`, `score` grades what `run`
produced. `--data-dir` redirects everything, which is how the CLI smoke test works.

| Step | State |
|---|---|
| `contracts/` schemas + config | Done. Cutoff date, cost model and dead-money rule live here |
| `sim/` replenishment | Done. Vectorised across items, stochastic lead time, shared by generator and scoring |
| 1 · generator + answer key | **Done, both presets.** Typed equipment, positions, shutdown overlay, real work orders |
| 2 · data quality (cap 4) | **Done — all 7 checks + matcher.** 99% recall, 99% precision at full |
| 3 · classifier (ADI × CV²) | **Done.** Monthly periods, 97.6% agreement with `PROFILE_TO_SBC_CLASS` |
| 4 · forecast (Croston family) | **Done.** TSB for sparse, SES for the rest; MASE 0.84–0.87, all four beat naive |
| 5 · levels + backtest | **Done — headline number two.** Total cost −8% on the held-out year, with the service-level sweep and order quantities |
| 6a · dead money | Not started — scorer stubbed; engine figure goes beside truth on the dashboard |
| Screens | **Done — overview, stock board, item drawer.** Vendored JS, inline SVG, no CDN |
| 8 · chat, thin | Not started — four tools, twenty golden questions |
| 6b · transfers, slider, work queue | **Only if everything above is green** |

**Current score, full preset** — every planted defect type now has a check:

| Check | Planted | Found | Missed | False | Recall | Precision |
|---|---|---|---|---|---|---|
| BLANK_MPN | 262 | 262 | 0 | 0 | 100% | 100% |
| BLANK_UOM | 60 | 60 | 0 | 0 | 100% | 100% |
| DUPLICATE_MATERIAL | 140 | 134 | 6 | 19 | **96%** | **88%** |
| IMPOSSIBLE_LEAD_TIME | 60 | 60 | 0 | 0 | 100% | 100% |
| ISSUE_WITHOUT_WORK_ORDER | 594 | 594 | 0 | 0 | 100% | 100% |
| NEGATIVE_STOCK | 100 | 100 | 0 | 0 | 100% | 100% |
| UOM_MISMATCH | 80 | 69 | 11 | 0 | 86% | 100% |
| **Total** | **1,296** | **1,279** | **17** | **19** | **99%** | **99%** |

LEDGER_MISMATCH raises 100 informational findings, excluded from precision.

Two known limits, both measured rather than assumed:
- **UOM_MISMATCH** catches an item swapped into a *rare* unit, never one swapped
  into its group's dominant unit — all 11 misses are that shape.
- **Duplicates** lose most to `token_dropped` (72%): when the size is simply left
  off the re-keyed record there is little left to match on. `token_front` and
  `abbrev` are at 98-100%.

### Dataset properties — all asserted in tests, all measured by `scoring/dataset_report.py`

The report is the single place these are computed, so the console and the test
suite cannot disagree about what "in band" means.

| Property | Toy | Full | Target |
|---|---|---|---|
| Lines idle >24 months | 35% | 35% | 30–50% |
| Stock value dead | 15% | 29% | 20–40% at full; wide sanity range at toy |
| Shutdown issue-rate multiple | 3.1× | 3.5× | ≥3× baseline |
| Issues per work order | 1.85 | 1.99 | ≥1.5 |
| Planned WOs raised in advance | 100%, 37d median | 100%, 38d | 100% |
| Unexplained ledger mismatches | 0 | 0 | 0 |
| Unplanted negative balances | 0 | 0 | 0 |
| Materials in >1 storeroom | 20% | 17% | ≥10% |
| Descriptions repeated outside planted copies | 0 | 0 | 0 |

Idle share, dead money, overstock, obsolescence and stockouts are all **emergent**
— they come from the stale min/max policy running against drifting demand and from
equipment being decommissioned mid-history. Only *data* defects are planted.

> **Dead value is asserted at full scale only.** It is a value-weighted share, so at
> 300 materials a handful of expensive rows decide it: 15% on toy against 29% on
> full from the same generator, moving several points on any reshuffle of the random
> stream. Toy keeps a wide sanity range so a genuinely broken generator still fails
> there. Do not tune the generator to make toy land in the industry band — that is
> fitting to noise.

## Headline number two — the backtest, full preset

The final year (365 days nothing had seen) replayed twice over 24,887 positions on
**identical demand and identical lead-time draws** — the two policies differ in
nothing but their levels.

| | plant's min/max | ours | change |
|---|---|---|---|
| Days waiting for a part | 842,897 | 376,732 | **−55%** |
| Units short | 600,292 | 237,022 | **−61%** |
| Capital on the shelf | SAR 1.367bn | SAR 2.046bn | **+50%** |
| Cost of being short | SAR 473m | SAR 236m | −50% |
| Cost of holding | SAR 342m | SAR 512m | +50% |
| Cost of placing orders | SAR 31.3m | SAR 32.3m | +3% |
| **All three together** | **SAR 846m** | **SAR 780m** | **−8%** |
| Orders placed | 34,808 | 35,848 | +3% |

**Say this out loud, it is the honest framing:** our levels hold *more* stock, not
less. We spend 50% more capital to buy a 55% cut in days waiting, and the three
costs together net out 8% cheaper. That runs the opposite way to the "release cash
at the same service level" line in the pitch — the cash release belongs to step 6a
(dead money), not here. Underneath the net, SAR 11.7m comes off 990 positions and
SAR 691m goes onto 15,639.

By criticality the improvement lands where it should: A 285,998 → 126,149 stockout
days, B 287,793 → 110,156, C 269,106 → 140,427.

How the level is set: TSB's demand probability × a bootstrap of the part's own issue
sizes over lead time + review, quantile taken at that item's newsvendor fractile
(A 99.4%, B 96.0%, C 80.0%), then floored by criticality. Every position carries a
sentence — *"Holding 796,179 Grm covers 90% of past 25-day stretches; A-critical,
9-day lead time."*

**Lead times flagged by step 2 are not used to size stock.** A record saying 3,650
days produced a reorder point of 35,826 against a plant figure of 318; the material
group's median is substituted (73 positions) and the reason string says so. That is
what makes step 2 a check rather than a report.

### The service-level sweep — and the number we cannot claim

The same year replayed at ten service levels, same demand and same lead-time draws:

| Aim to have the part | Days waiting | Capital | Orders | All costs |
|---|---|---|---|---|
| 50% | 624,678 | SAR 1.583bn | 32,616 | SAR 771m |
| 70% | 503,843 | SAR 1.677bn | 33,837 | SAR 753m |
| 80% | 445,254 | SAR 1.750bn | 34,666 | **SAR 751m** |
| 90% | 378,464 | SAR 1.868bn | 35,764 | SAR 759m |
| 95% | 341,120 | SAR 1.964bn | 36,629 | SAR 772m |
| 99.5% | 291,285 | SAR 2.228bn | 38,126 | SAR 824m |
| plant's own | 842,897 | SAR 1.367bn | 34,808 | SAR 846m |
| **ours (per item)** | **376,732** | **SAR 2.046bn** | **35,848** | **SAR 780m** |

**The plant sits off the left end of that curve.** It waits longer than our lowest
sampled service level manages while holding less capital than any point on it. So
the headline "at their service level we need X% less capital" **has no honest
answer here** — their policy is under-serving, not over-invested. Do not go looking
for a way to phrase it that produces a number; the cash-release story is dead money
(step 6a), and this is the sentence that says why.

Our recommended levels are deliberately not on the curve: each item gets its own
service level from its own economics, which is why they beat every blanket setting
on total cost.

### Order quantities

The first cut placed **71% more purchase orders** than the plant does for the same
material flow — a trickle every week, which looked free because placing an order was
free in the model. Three changes: an order must cover at least the demand expected
while it is in transit; it is rounded up to the pack the plant is already receiving
in (read off its own receipt history — there is no pack-size column); and
`cfg.costs.order_cost_sar` charges SAR 900 per order into the total. Orders placed
are now **+3%**.

## The screens

`python cli.py serve --preset full` — three screens, vendored JS, inline SVG, no
CDN and no build step. Every figure is read from `results/positions.parquet`, which
`run` writes; the API filters and pages a frame and computes nothing.

- **Overview** — stock value, idle share and dead value (still answer-key measured),
  the backtest headline with the honest callout, by-storeroom table, the defect
  scoreboard, and forecast accuracy with the plain-English note on why we lose to
  forecasting zero on sparse movers.
- **Stock board** — one table ranked by what it costs to ignore (criticality weight
  × unit price × units below our reorder point), band and demand-class chips,
  search, 25 rows a page.
- **Item drawer** — 36 months of usage as inline SVG with the cut-off line, the
  forecast and the known maintenance demand overlaid, and a paragraph that ends with
  the engine's own reason string verbatim.

Routes are a contract: `#/board` and `#/board/{material}/{storeroom}` are what the
progress document photographs.

## Next — step 6a, dead money

1. Engine computes its own dead-money list from step 5's justified quantity plus
   obsolescence inferred from equipment status and demand cessation. Ranked in SAR
   at SAP moving average.
2. Scored against `truth`: SAR found / true / wrongly flagged; obsolete
   found / missed / falsely flagged. Engine figure sits beside the truth figure.
3. Then the thin chat (four tools, twenty golden questions). The scenario slider
   now has its data (`results/frontier.json`); transfers and the work queue only
   if everything above is green.

Full order and the exclusions are in [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md).

## Things to avoid

- **Never let `engine/` import `sim/`, `generator/` or `scoring/`.** A test parses
  the AST and fails if it does. If the engine could see the answer key, the score
  would be meaningless and nobody would notice until a Ma'aden engineer asked how
  it was measured.
- **Do not plant overstock, obsolescence or critical-below-reorder.** They must
  emerge from the stale policy and from equipment decommissioning, and are scored
  against `truth`. Planting them would grade the engine on our own injection rules.
- **Never write `stock.on_hand` by hand.** It is recomputed from the movement
  ledger, and negatives are planted last. Any balance not backed by movements shows
  up as a LEDGER_MISMATCH the engine is right to flag and we were wrong to create.
- **Never mix per-day and per-event costs in the newsvendor fractile.** That bug
  pinned every service level to the cap and silently disabled the whole idea.
- **`shortage_cost_per_unit` is defined once**, in `CostModel`. It feeds the
  service level, the SAR work-queue ranking and dead-money valuation. Three
  different versions is how a demo contradicts itself on stage.
- **Do not report "value idle for 24 months" as dead money.** That is 90% of stock
  value and it is wrong: insurance spares correctly sit still for years.
- **Fit on `cfg.train_slice()`, score on `cfg.eval_slice()`.** Never touch the
  movements frame directly for either.
- **Never let a screen calculate.** The API reads `results/positions.parquet` and
  filters it. A page that recomputes will disagree with the scoreboard beside it,
  and will stall on 25,000 positions while somebody is watching.
- **No CDN, ever.** A demo laptop on a plant site may have no route out.
  `tests/test_screens.py` fails on any remote `src` or `href`.
- **Never let the two backtest policies draw their own lead times.** They share one
  pre-drawn matrix (`sim.replenish.walk(lead_time_draws=…)`). Separate draws make
  part of any improvement luck, and nothing in the output would show it.
- **Do not apply `z · σ · √LT` across the board** — wrong for the insurance-spare
  population, which is where the expensive errors are.
- **Do not let the LLM compute anything.** It calls the engine and narrates.
- **Do not quote the "50–60% of MRO is SLOB" benchmark.** No traceable source.
- **`noah-stock-v2` / `noah-stock-ui-v2` are reference only** — a prior project.
  Read for design ideas; do not fork, do not import.

## Related docs

- [`docs/PROPOSAL.md`](docs/PROPOSAL.md) — the client-facing proposal (the substantive doc)
- [`docs/deck.html`](docs/deck.html) — published management deck, same content, presentation form
- [`DECISIONS.md`](DECISIONS.md) — why things are the way they are
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system shape
- [`CONSTRAINTS.md`](CONSTRAINTS.md) — what must never happen here
